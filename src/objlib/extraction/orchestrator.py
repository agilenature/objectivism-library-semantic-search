"""Async batch orchestrator for metadata extraction (Wave 1 and Wave 2).

Wave 1: Competitive strategy extraction through 3 lanes concurrently.
Wave 2: Production batch processing with validated prompt template,
two-level validation, multi-dimensional confidence scoring, and
versioned metadata persistence to file_metadata_ai / file_primary_topics.

Both waves enforce rate limits (60 req/min) and concurrency limits (3
simultaneous) via asyncio Semaphore and aiolimiter. On credit exhaustion
(HTTP 402), saves checkpoint and exits cleanly. On rate limiting (HTTP 429),
applies exponential backoff with jitter.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from aiolimiter import AsyncLimiter
from pydantic import ValidationError

from objlib.extraction.checkpoint import CheckpointManager, CreditExhaustionHandler
from objlib.extraction.chunker import prepare_transcript
from objlib.extraction.client import CreditExhaustedException, RateLimitException
from objlib.extraction.confidence import calculate_confidence
from objlib.extraction.prompts import (
    PROMPT_VERSION,
    build_production_prompt,
    build_system_prompt,
    build_user_prompt,
    hash_extraction_config,
)
from objlib.extraction.schemas import CONTROLLED_VOCABULARY, ExtractedMetadata, MetadataStatus
from objlib.extraction.strategies import StrategyConfig
from objlib.extraction.validator import ValidationResult, build_retry_prompt, validate_extraction

if TYPE_CHECKING:
    from objlib.database import Database
    from objlib.extraction.client import MistralClient

logger = logging.getLogger(__name__)

# Cost estimate: ~$0.02 per request for magistral-medium-latest (approximate)
_ESTIMATED_COST_PER_REQUEST = 0.02


@dataclass
class ExtractionConfig:
    """Configuration for the extraction orchestrator.

    Attributes:
        max_concurrent: Maximum simultaneous API requests.
        rate_limit_rpm: Maximum requests per minute.
        max_retries: Maximum retry attempts for rate-limited requests.
    """

    max_concurrent: int = 3
    rate_limit_rpm: int = 60
    max_retries: int = 2


class ExtractionOrchestrator:
    """Async batch orchestrator for metadata extraction (Wave 1 and Wave 2).

    Wave 1: Processes files through multiple strategy lanes with concurrency
    and rate limiting. Saves results atomically per-file per-strategy.

    Wave 2: Production processing with validated prompt template, two-level
    validation (hard failures = reject+retry, soft warnings = accept+flag),
    multi-dimensional confidence scoring, and versioned metadata persistence.

    Args:
        client: MistralClient instance for API calls.
        db: Database instance for result storage.
        checkpoint: CheckpointManager for pause/resume.
        config: ExtractionConfig with concurrency/rate settings.
    """

    def __init__(
        self,
        client: "MistralClient",
        db: "Database",
        checkpoint: CheckpointManager,
        config: ExtractionConfig | None = None,
    ) -> None:
        self._client = client
        self._db = db
        self._checkpoint = checkpoint
        self._config = config or ExtractionConfig()
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent)
        self._rate_limiter = AsyncLimiter(
            self._config.rate_limit_rpm, 60
        )
        self._total_calls = 0
        self._credit_handler = CreditExhaustionHandler()

    async def run_wave1(
        self,
        test_files: list[dict],
        strategies: dict[str, StrategyConfig],
    ) -> dict:
        """Run Wave 1 competitive extraction across all strategy lanes.

        For each file, for each strategy: reads file content, builds
        prompts, calls the API, validates the response, and saves
        results. Handles credit exhaustion and rate limiting.

        If resuming from checkpoint, skips already-completed pairs.

        Args:
            test_files: List of file dicts from sampler (file_path, filename, etc.).
            strategies: Dict mapping strategy name to StrategyConfig.

        Returns:
            Summary dict: {strategy_name: {completed: int, failed: int,
            total_tokens: int, avg_latency_ms: float}}
        """
        # Check for existing checkpoint to resume from
        checkpoint_data = self._checkpoint.load()
        completed_pairs: set[tuple[str, str]] = set()
        if checkpoint_data:
            logger.info("Resuming from checkpoint: %s", checkpoint_data.get("timestamp"))
            for lane_name, lane_data in checkpoint_data.get("lanes", {}).items():
                for fp in lane_data.get("completed", []):
                    completed_pairs.add((fp, lane_name))
                for fp in lane_data.get("failed", []):
                    completed_pairs.add((fp, lane_name))

        # Track results per strategy
        results: dict[str, dict] = {
            name: {
                "completed": 0,
                "failed": 0,
                "total_tokens": 0,
                "latencies_ms": [],
            }
            for name in strategies
        }

        # Also track per-lane file lists for checkpoint
        lane_state: dict[str, dict] = {
            name: {"completed": [], "failed": [], "tokens": 0}
            for name in strategies
        }

        # Restore lane state from checkpoint
        if checkpoint_data:
            for lane_name, lane_data in checkpoint_data.get("lanes", {}).items():
                if lane_name in lane_state:
                    lane_state[lane_name] = {
                        "completed": list(lane_data.get("completed", [])),
                        "failed": list(lane_data.get("failed", [])),
                        "tokens": lane_data.get("tokens", 0),
                    }
                    results[lane_name]["completed"] = len(lane_data.get("completed", []))
                    results[lane_name]["failed"] = len(lane_data.get("failed", []))
                    results[lane_name]["total_tokens"] = lane_data.get("tokens", 0)

        try:
            for file_info in test_files:
                file_path = file_info["file_path"]

                # Read file content from disk
                try:
                    transcript = Path(file_path).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as e:
                    logger.error("Failed to read file %s: %s", file_path, e)
                    for strategy_name in strategies:
                        if (file_path, strategy_name) not in completed_pairs:
                            lane_state[strategy_name]["failed"].append(file_path)
                            results[strategy_name]["failed"] += 1
                    continue

                # Process through each strategy lane
                for strategy_name, strategy_config in strategies.items():
                    if (file_path, strategy_name) in completed_pairs:
                        logger.info(
                            "Skipping %s/%s (already completed)",
                            strategy_name, file_info["filename"],
                        )
                        continue

                    result = await self._process_one(
                        file_path, transcript, strategy_config
                    )

                    if result["status"] == "success":
                        self._save_wave1_result(
                            file_path, strategy_name, result
                        )
                        lane_state[strategy_name]["completed"].append(file_path)
                        lane_state[strategy_name]["tokens"] += result.get("tokens", 0)
                        results[strategy_name]["completed"] += 1
                        results[strategy_name]["total_tokens"] += result.get("tokens", 0)
                        results[strategy_name]["latencies_ms"].append(
                            result.get("latency_ms", 0)
                        )
                    else:
                        lane_state[strategy_name]["failed"].append(file_path)
                        results[strategy_name]["failed"] += 1

                    self._total_calls += 1

        except CreditExhaustedException:
            # Save checkpoint and notify stakeholder
            self._checkpoint.save({
                "wave": "wave1",
                "lanes": lane_state,
                "next_file_index": self._find_file_index(test_files, file_path),
                "prompt_version": PROMPT_VERSION,
            })
            estimated_cost = self._total_calls * _ESTIMATED_COST_PER_REQUEST
            self._credit_handler.display_pause_notification(
                lanes=lane_state,
                total_calls=self._total_calls,
                estimated_cost=estimated_cost,
                total_files=len(test_files),
            )
            sys.exit(0)

        # Clear checkpoint on successful completion
        self._checkpoint.clear()

        # Calculate averages
        summary: dict[str, dict] = {}
        for name, data in results.items():
            latencies = data.pop("latencies_ms")
            avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
            summary[name] = {
                **data,
                "avg_latency_ms": round(avg_latency, 1),
            }

        return summary

    async def _process_one(
        self,
        file_path: str,
        transcript: str,
        strategy: StrategyConfig,
    ) -> dict:
        """Process a single file with a single strategy.

        Acquires semaphore and rate limiter, builds prompts, calls API,
        validates response against Pydantic model, and returns result.

        Handles RateLimitException with exponential backoff and jitter.
        Re-raises CreditExhaustedException for orchestrator-level handling.

        Args:
            file_path: Path to the file being processed.
            transcript: File content text.
            strategy: Strategy configuration to use.

        Returns:
            Result dict with keys: status, metadata (if success),
            tokens, latency_ms, confidence_score, validation_status.
        """
        system_prompt = build_system_prompt(strategy.system_prompt_strategy)
        user_prompt = build_user_prompt(transcript, strategy.system_prompt_strategy)

        for attempt in range(self._config.max_retries + 1):
            try:
                async with self._semaphore:
                    async with self._rate_limiter:
                        start_time = time.monotonic()
                        metadata_dict, tokens = await self._client.extract_metadata(
                            transcript_text=user_prompt,
                            system_prompt=system_prompt,
                            max_tokens=8000,
                            temperature=strategy.temperature,
                        )
                        latency_ms = int((time.monotonic() - start_time) * 1000)

                # Validate against Pydantic model
                try:
                    validated = ExtractedMetadata.model_validate(metadata_dict)
                    return {
                        "status": "success",
                        "metadata": validated.model_dump(),
                        "tokens": tokens,
                        "latency_ms": latency_ms,
                        "confidence_score": validated.confidence_score,
                        "validation_status": "extracted",
                    }
                except ValidationError as e:
                    logger.warning(
                        "Validation failed for %s/%s: %s",
                        strategy.name, file_path, e,
                    )
                    if attempt == self._config.max_retries:
                        return {
                            "status": "failed",
                            "error": f"Validation error: {e}",
                            "metadata": metadata_dict,
                            "tokens": tokens,
                            "latency_ms": latency_ms,
                            "confidence_score": 0.0,
                            "validation_status": "failed_validation",
                        }
                    # Retry on validation failure
                    continue

            except CreditExhaustedException:
                raise  # Let orchestrator handle

            except RateLimitException:
                if attempt < self._config.max_retries:
                    backoff = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "Rate limited on %s/%s, backing off %.1fs (attempt %d)",
                        strategy.name, file_path, backoff, attempt + 1,
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error(
                        "Max retries on rate limit for %s/%s",
                        strategy.name, file_path,
                    )
                    return {
                        "status": "failed",
                        "error": "Rate limit exceeded after max retries",
                        "tokens": 0,
                        "latency_ms": 0,
                        "confidence_score": 0.0,
                        "validation_status": "failed_rate_limit",
                    }

            except Exception as e:
                logger.error(
                    "Unexpected error for %s/%s: %s",
                    strategy.name, file_path, e,
                )
                return {
                    "status": "failed",
                    "error": str(e),
                    "tokens": 0,
                    "latency_ms": 0,
                    "confidence_score": 0.0,
                    "validation_status": "failed_error",
                }

        # Should not reach here, but just in case
        return {
            "status": "failed",
            "error": "Max retries exhausted",
            "tokens": 0,
            "latency_ms": 0,
            "confidence_score": 0.0,
            "validation_status": "failed_retries",
        }

    def _save_wave1_result(
        self, file_path: str, strategy: str, result: dict
    ) -> None:
        """Save a Wave 1 result to the database immediately.

        Inserts into the wave1_results table for competitive strategy
        comparison. Results are saved atomically per-file per-strategy
        to ensure checkpoint resume has accurate progress.

        Args:
            file_path: File path processed.
            strategy: Strategy name used.
            result: Result dict from _process_one.
        """
        metadata_json = json.dumps(result.get("metadata", {}))

        with self._db.conn:
            self._db.conn.execute(
                """INSERT INTO wave1_results
                   (file_path, strategy, metadata_json, token_count,
                    latency_ms, confidence_score)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    file_path,
                    strategy,
                    metadata_json,
                    result.get("tokens", 0),
                    result.get("latency_ms", 0),
                    result.get("confidence_score", 0.0),
                ),
            )

    @staticmethod
    def _find_file_index(test_files: list[dict], current_path: str) -> int:
        """Find the index of the current file in the test files list.

        Args:
            test_files: The list of test file dicts.
            current_path: The file_path being processed when paused.

        Returns:
            Index of the file, or len(test_files) if not found.
        """
        for i, f in enumerate(test_files):
            if f["file_path"] == current_path:
                return i
        return len(test_files)

    async def run_production(
        self, files: list[dict], strategy_name: str
    ) -> dict:
        """Run Wave 2 production extraction on a batch of files.

        Processes each file through the validated prompt template with:
        - Adaptive chunking via prepare_transcript()
        - Two-level validation via validate_extraction()
        - Retry with schema reminder on hard validation failure
        - Multi-dimensional confidence scoring via calculate_confidence()
        - Versioned metadata persistence to file_metadata_ai and
          file_primary_topics tables

        Temperature is always 1.0 for production (magistral requirement).

        On credit exhaustion (HTTP 402): saves checkpoint and exits.
        On rate limiting (HTTP 429): exponential backoff with jitter.
        Each file's result is saved atomically (checkpoint per file).

        Args:
            files: List of file dicts with file_path, filename, file_size.
            strategy_name: Winning strategy from Wave 1 (e.g., 'minimalist').

        Returns:
            Summary dict: {total, extracted, needs_review, failed, partial,
            total_tokens, estimated_cost, avg_latency_ms}
        """
        # Get temperature from Wave 1 strategy config
        from objlib.extraction.strategies import WAVE1_STRATEGIES
        strategy_config = WAVE1_STRATEGIES.get(strategy_name)
        if not strategy_config:
            raise ValueError(f"Unknown strategy: {strategy_name}")
        temperature = strategy_config.temperature

        system_prompt = build_production_prompt(
            strategy_name, "production"
        )

        # Config hash for versioning
        import hashlib

        vocab_hash = hashlib.sha256(
            ",".join(sorted(CONTROLLED_VOCABULARY)).encode()
        ).hexdigest()[:16]

        config_hash = hash_extraction_config(
            temperature=1.0,
            timeout=240,
            schema_version="1.0",
            vocab_hash=vocab_hash,
        )

        # Check checkpoint for resume
        checkpoint_data = self._checkpoint.load()
        completed_files: set[str] = set()
        if checkpoint_data and checkpoint_data.get("wave") == "production":
            logger.info(
                "Resuming production from checkpoint: %s",
                checkpoint_data.get("timestamp"),
            )
            completed_files = set(checkpoint_data.get("completed", []))

        # Track results
        results = {
            "total": len(files),
            "extracted": 0,
            "needs_review": 0,
            "failed": 0,
            "partial": 0,
            "total_tokens": 0,
            "latencies_ms": [],
        }

        # Track file lists for checkpoint
        prod_state: dict = {
            "completed": list(completed_files),
            "failed": [],
        }

        current_file_path = ""
        try:
            for file_info in files:
                file_path = file_info["file_path"]
                current_file_path = file_path

                if file_path in completed_files:
                    logger.info(
                        "Skipping %s (already completed)", file_info.get("filename", file_path)
                    )
                    continue

                # Read and chunk transcript
                try:
                    transcript = prepare_transcript(file_path)
                except (OSError, FileNotFoundError) as e:
                    logger.error("Failed to read file %s: %s", file_path, e)
                    results["failed"] += 1
                    prod_state["failed"].append(file_path)
                    continue

                transcript_length = len(transcript)

                # Build user prompt
                user_prompt = build_user_prompt(transcript, strategy_name)

                # API call with validation and retry
                metadata_dict = None
                tokens = 0
                latency_ms = 0
                validation = None

                for attempt in range(2):  # Initial + 1 retry
                    try:
                        async with self._semaphore:
                            async with self._rate_limiter:
                                start_time = time.monotonic()
                                retry_suffix = ""
                                if attempt > 0 and validation and validation.hard_failures:
                                    retry_suffix = build_retry_prompt(validation.hard_failures)

                                metadata_dict, tokens = await self._client.extract_metadata(
                                    transcript_text=user_prompt + retry_suffix,
                                    system_prompt=system_prompt,
                                    max_tokens=8000,
                                    temperature=temperature,  # From Wave 1 winning strategy
                                )
                                latency_ms = int((time.monotonic() - start_time) * 1000)

                        self._total_calls += 1

                        # Validate extraction (pass transcript for semantic topic normalization)
                        validation = validate_extraction(
                            metadata_dict,
                            document_text=transcript,
                            filename=Path(file_path).name,
                        )

                        if not validation.hard_failures:
                            # Passed validation (extracted or needs_review)
                            break

                        if attempt == 0:
                            logger.warning(
                                "Hard validation failure for %s (attempt 1), retrying: %s",
                                file_path, validation.hard_failures,
                            )
                        # Continue to retry

                    except CreditExhaustedException:
                        raise  # Let orchestrator handle

                    except RateLimitException:
                        backoff = (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            "Rate limited on %s, backing off %.1fs (attempt %d)",
                            file_path, backoff, attempt + 1,
                        )
                        await asyncio.sleep(backoff)

                    except Exception as e:
                        logger.error(
                            "Unexpected error for %s: %s", file_path, e
                        )
                        metadata_dict = None
                        validation = ValidationResult(
                            status=MetadataStatus.FAILED_VALIDATION,
                            hard_failures=[str(e)],
                        )
                        break

                # Calculate confidence and determine final status
                if metadata_dict is not None and validation is not None:
                    model_confidence = metadata_dict.get("confidence_score", 0.0)
                    try:
                        model_confidence = float(model_confidence)
                    except (TypeError, ValueError):
                        model_confidence = 0.0

                    confidence = calculate_confidence(
                        model_confidence=model_confidence,
                        validation=validation,
                        transcript_length=transcript_length,
                    )

                    # Save result to database
                    self._save_production_result(
                        file_path=file_path,
                        metadata=metadata_dict,
                        validation=validation,
                        confidence=confidence,
                        tokens=tokens,
                        config={
                            "model": self._client._model,
                            "prompt_version": PROMPT_VERSION,
                            "config_hash": config_hash,
                        },
                    )

                    # Track results
                    status_value = validation.status.value
                    if status_value == "extracted":
                        results["extracted"] += 1
                        logger.info("✓ Extracted: %s (conf: %.1f%%, %dms)",
                                    file_info.get("filename", file_path), confidence * 100, latency_ms)
                    elif status_value == "needs_review":
                        results["needs_review"] += 1
                        logger.info("⚠ Needs review: %s (conf: %.1f%%, %dms)",
                                    file_info.get("filename", file_path), confidence * 100, latency_ms)
                    elif status_value == "failed_validation":
                        results["failed"] += 1
                    else:
                        results["partial"] += 1

                    results["total_tokens"] += tokens
                    results["latencies_ms"].append(latency_ms)

                    prod_state["completed"].append(file_path)

                else:
                    results["failed"] += 1
                    prod_state["failed"].append(file_path)

                # Save checkpoint after each file
                self._checkpoint.save({
                    "wave": "production",
                    "completed": prod_state["completed"],
                    "failed": prod_state["failed"],
                    "prompt_version": PROMPT_VERSION,
                    "strategy": strategy_name,
                })

        except CreditExhaustedException:
            # Save checkpoint and notify
            self._checkpoint.save({
                "wave": "production",
                "completed": prod_state["completed"],
                "failed": prod_state["failed"],
                "prompt_version": PROMPT_VERSION,
                "strategy": strategy_name,
                "paused_at": current_file_path,
            })
            estimated_cost = self._total_calls * _ESTIMATED_COST_PER_REQUEST
            self._credit_handler.display_pause_notification(
                lanes={"production": {
                    "completed": prod_state["completed"],
                    "failed": prod_state["failed"],
                    "tokens": results["total_tokens"],
                }},
                total_calls=self._total_calls,
                estimated_cost=estimated_cost,
                total_files=len(files),
            )
            sys.exit(0)

        # Clear checkpoint on successful completion
        self._checkpoint.clear()

        # Calculate averages
        latencies = results.pop("latencies_ms")
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        return {
            **results,
            "estimated_cost": round(self._total_calls * _ESTIMATED_COST_PER_REQUEST, 2),
            "avg_latency_ms": round(avg_latency, 1),
        }

    def _save_production_result(
        self,
        file_path: str,
        metadata: dict,
        validation: ValidationResult,
        confidence: float,
        tokens: int,
        config: dict,
    ) -> None:
        """Save a production extraction result to the database atomically.

        In a single transaction:
        1. Updates files table: ai_metadata_status, ai_confidence_score
        2. Marks previous metadata versions as not current
        3. Inserts new versioned metadata into file_metadata_ai
        4. Clears and re-inserts primary topics into file_primary_topics

        Args:
            file_path: File path of the processed file.
            metadata: Raw metadata dict from API response.
            validation: ValidationResult from validate_extraction().
            confidence: Calculated confidence score.
            tokens: Token count for this extraction.
            config: Dict with model, prompt_version, config_hash keys.
        """
        metadata_json = json.dumps(metadata)
        status = validation.status.value

        with self._db.conn:
            # 1. Update files table
            self._db.conn.execute(
                "UPDATE files SET ai_metadata_status = ?, ai_confidence_score = ? "
                "WHERE file_path = ?",
                (status, confidence, file_path),
            )

            # 2. Mark previous versions as not current
            self._db.conn.execute(
                "UPDATE file_metadata_ai SET is_current = 0 "
                "WHERE file_path = ? AND is_current = 1",
                (file_path,),
            )

            # 3. Insert new versioned metadata
            self._db.conn.execute(
                """INSERT INTO file_metadata_ai
                   (file_path, metadata_json, model, prompt_version,
                    extraction_config_hash, is_current)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (
                    file_path,
                    metadata_json,
                    config.get("model", "magistral-medium-latest"),
                    config.get("prompt_version", PROMPT_VERSION),
                    config.get("config_hash", ""),
                ),
            )

            # 4. Clear old topics and insert new ones
            self._db.conn.execute(
                "DELETE FROM file_primary_topics WHERE file_path = ?",
                (file_path,),
            )

            primary_topics = metadata.get("primary_topics", [])
            if isinstance(primary_topics, list):
                valid_topics = [t for t in primary_topics if t in CONTROLLED_VOCABULARY]
                for topic in valid_topics:
                    self._db.conn.execute(
                        "INSERT INTO file_primary_topics (file_path, topic_tag) "
                        "VALUES (?, ?)",
                        (file_path, topic),
                    )

    def _get_pending_extraction_files(self) -> list[dict]:
        """Query files pending AI metadata extraction.

        Returns .txt files with unknown category that have not yet been
        extracted or have a retryable status. Excludes files already
        processed in Wave 1 results.

        Returns:
            List of dicts with file_path, filename, file_size keys.
        """
        rows = self._db.conn.execute(
            """SELECT file_path, filename, file_size FROM files
               WHERE filename LIKE '%.txt'
                 AND json_extract(metadata_json, '$.category') = 'unknown'
                 AND ai_metadata_status IN ('pending', 'failed_json', 'retry_scheduled')
               ORDER BY file_path""",
        ).fetchall()

        # Exclude Wave 1 test files
        wave1_files: set[str] = set()
        try:
            wave1_rows = self._db.conn.execute(
                "SELECT DISTINCT file_path FROM wave1_results"
            ).fetchall()
            wave1_files = {r["file_path"] for r in wave1_rows}
        except Exception:
            pass  # wave1_results table may not exist

        return [
            {"file_path": r["file_path"], "filename": r["filename"], "file_size": r["file_size"]}
            for r in rows
            if r["file_path"] not in wave1_files
        ]
