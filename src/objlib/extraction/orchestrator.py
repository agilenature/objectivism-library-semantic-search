"""Async batch orchestrator for Wave 1 competitive strategy extraction.

Processes test files through 3 competitive strategy lanes concurrently,
enforcing rate limits (60 req/min) and concurrency limits (3 simultaneous)
via asyncio Semaphore and aiolimiter.

Results are saved atomically per-file per-strategy to the wave1_results
table. On credit exhaustion (HTTP 402), saves checkpoint and exits cleanly.
On rate limiting (HTTP 429), applies exponential backoff with jitter.

Resume from checkpoint skips already-completed (file, strategy) pairs.
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
from objlib.extraction.client import CreditExhaustedException, RateLimitException
from objlib.extraction.prompts import PROMPT_VERSION, build_system_prompt, build_user_prompt
from objlib.extraction.schemas import ExtractedMetadata
from objlib.extraction.strategies import StrategyConfig

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
    """Async batch orchestrator for Wave 1 competitive strategy extraction.

    Processes files through multiple strategy lanes with concurrency and
    rate limiting. Saves results atomically per-file per-strategy.

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
        self, files: list[dict], prompt_template: str
    ) -> dict:
        """Placeholder for Wave 2 production processing.

        Will be implemented in Plan 04 with the validated prompt
        template from Wave 1 results.

        Args:
            files: List of file dicts to process.
            prompt_template: Validated prompt template from Wave 1.

        Raises:
            NotImplementedError: Always, until Plan 04 implementation.
        """
        raise NotImplementedError(
            "Wave 2 production processing implemented in Plan 04"
        )
