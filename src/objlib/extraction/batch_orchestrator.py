"""Batch extraction orchestrator for Mistral Batch API.

Integrates Mistral Batch API with existing extraction pipeline:
1. Loads pending files from database
2. Builds batch requests with proper prompts
3. Submits batch job to Mistral
4. Polls for completion with progress updates
5. Parses results and updates database
6. Tracks failures for retry

Advantages:
- 50% cost savings vs synchronous extraction
- Zero rate limiting issues
- Handles 116-1,093 files easily (well under 10k inline limit)
- Perfect for offline bulk processing
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from objlib.extraction.batch_client import BatchRequest, MistralBatchClient
from objlib.extraction.confidence import calculate_confidence
from objlib.extraction.parser import parse_magistral_response
from objlib.extraction.prompts import build_system_prompt, build_user_prompt
from objlib.extraction.validator import validate_extraction

if TYPE_CHECKING:
    from objlib.database import Database

logger = logging.getLogger(__name__)

# Token limits for Mistral models
# Leave headroom for system/user prompts (~8K tokens)
MAX_DOCUMENT_TOKENS = 100_000  # Mistral has 128K context window
TOKENS_PER_WORD = 1.3  # Approximation for English text


def _estimate_token_count(text: str) -> int:
    """Estimate token count for text (words * 1.3 approximation).

    Args:
        text: Input text string.

    Returns:
        Estimated token count.
    """
    word_count = len(text.split())
    return int(word_count * TOKENS_PER_WORD)


class BatchExtractionOrchestrator:
    """Orchestrator for batch metadata extraction using Mistral Batch API.

    Manages the end-to-end workflow from database query to result persistence,
    tracking failed requests for retry.

    Args:
        db: Database instance for state management.
        client: MistralBatchClient for API interactions.
        strategy_name: Strategy name for prompt selection (default: "minimalist").
    """

    def __init__(
        self,
        db: "Database",
        client: MistralBatchClient,
        strategy_name: str = "minimalist",
    ) -> None:
        self._db = db
        self._client = client
        self._strategy_name = strategy_name

    async def run_batch_extraction(
        self,
        max_files: int | None = None,
        job_name: str | None = None,
        poll_interval: int = 30,
    ) -> dict:
        """Run complete batch extraction workflow.

        Steps:
        1. Load pending files from database
        2. Build batch requests with extraction prompts
        3. Submit batch job
        4. Poll until completion
        5. Download and parse results
        6. Update database with extracted metadata
        7. Return summary with failed request tracking

        Args:
            max_files: Maximum files to process (None = all pending).
            job_name: Descriptive name for batch job.
            poll_interval: Seconds between status polls (default: 30).

        Returns:
            Summary dict:
            {
                "batch_id": str,
                "total": int,
                "succeeded": int,
                "failed": int,
                "failed_files": list[str],  # File paths that failed
                "processing_time_seconds": float,
            }
        """
        import time

        start_time = time.time()

        # Step 1: Load pending files
        print("DEBUG: Loading pending files...", flush=True)
        logger.info("Loading pending files from database...")
        pending_files = self._get_pending_files(max_files)
        print(f"DEBUG: Got {len(pending_files)} pending files", flush=True)

        if not pending_files:
            logger.warning("No pending files found for batch extraction")
            return {
                "batch_id": None,
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "failed_files": [],
                "processing_time_seconds": 0,
            }

        logger.info("Found %d pending files for batch extraction", len(pending_files))

        # Step 2: Build batch requests (skip oversized files)
        print("DEBUG: Building batch requests...", flush=True)
        logger.info("Building batch requests...")
        batch_requests = []
        file_map = {}  # custom_id -> file_path mapping
        oversized_files = []  # Track files too large for Mistral

        for idx, file_record in enumerate(pending_files):
            print(f"DEBUG: Processing file {idx+1}/{len(pending_files)}", flush=True)
            file_path = file_record["file_path"]
            custom_id = str(idx)  # Use simple numeric ID

            # Read file content
            try:
                content = Path(file_path).read_text(encoding="utf-8")
            except Exception as e:
                logger.error("Failed to read file %s: %s", file_path, e)
                continue

            # Check if file is too large for Mistral context window
            estimated_tokens = _estimate_token_count(content)
            if estimated_tokens > MAX_DOCUMENT_TOKENS:
                logger.warning(
                    "Skipping oversized file %s (~%d tokens, max %d)",
                    Path(file_path).name,
                    estimated_tokens,
                    MAX_DOCUMENT_TOKENS,
                )
                oversized_files.append(file_path)
                # Mark as skipped in database (will upload to Gemini without enrichment)
                self._mark_oversized(file_path, estimated_tokens)
                continue

            # Build prompts using existing extraction logic
            system_prompt = build_system_prompt(self._strategy_name)
            user_prompt = build_user_prompt(content, self._strategy_name)

            # Create batch request
            request = self._client.build_extraction_request(
                custom_id=custom_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=1.0,  # Production temperature
                max_tokens=8000,
            )

            batch_requests.append(request)
            file_map[custom_id] = file_path

        if not batch_requests:
            logger.error("No valid batch requests created")
            return {
                "batch_id": None,
                "total": len(pending_files),
                "succeeded": 0,
                "failed": len(pending_files) - len(oversized_files),
                "failed_files": [f["file_path"] for f in pending_files if f["file_path"] not in oversized_files],
                "oversized_files": oversized_files,
                "processing_time_seconds": time.time() - start_time,
            }

        logger.info("Built %d batch requests", len(batch_requests))

        # Debug: Log first request structure
        if batch_requests:
            import json
            logger.info("Sample request structure: %s", json.dumps(
                {
                    "custom_id": batch_requests[0].custom_id,
                    "method": batch_requests[0].method,
                    "url": batch_requests[0].url,
                    "body_keys": list(batch_requests[0].body.keys()) if batch_requests[0].body else []
                },
                indent=2
            ))

        # Step 3: Submit batch
        print(f"DEBUG: About to submit {len(batch_requests)} requests...", flush=True)
        logger.info("Submitting batch job to Mistral...")
        batch_id = await self._client.submit_batch(
            requests=batch_requests,
            job_name=job_name or f"extraction-{len(batch_requests)}",
            metadata={"strategy": self._strategy_name},
        )
        print(f"DEBUG: Batch submitted, ID: {batch_id}", flush=True)

        logger.info("Batch job submitted: %s", batch_id)

        # Step 4: Poll until completion
        print(f"DEBUG: Starting to poll (interval={poll_interval}s)...", flush=True)
        logger.info("Polling for batch completion (interval=%ds)...", poll_interval)
        try:
            final_status = await self._client.wait_for_completion(
                batch_id=batch_id,
                poll_interval=poll_interval,
                timeout=7200,  # 2 hours max
            )
            print(f"DEBUG: Polling completed, status: {final_status}", flush=True)

            logger.info(
                "Batch completed: %d succeeded, %d failed",
                final_status["succeeded_requests"],
                final_status["failed_requests"],
            )
        except (TimeoutError, RuntimeError) as e:
            logger.error("Batch job failed: %s", e)
            return {
                "batch_id": batch_id,
                "total": len(batch_requests),
                "succeeded": 0,
                "failed": len(batch_requests),
                "failed_files": list(file_map.values()),
                "oversized_files": oversized_files,
                "processing_time_seconds": time.time() - start_time,
            }

        # Step 5: Download and parse results
        logger.info("Downloading batch results...")
        results = await self._client.download_results(batch_id)

        # Step 6: Process results and update database
        logger.info("Processing %d results (submitted %d requests)...", len(results), len(batch_requests))

        # Debug: Check if all requests got results
        if len(results) != len(batch_requests):
            logger.warning(
                "Result count mismatch! Submitted %d requests but received %d results",
                len(batch_requests),
                len(results),
            )
        succeeded_count = 0
        failed_files = []

        for result in results:
            file_path = file_map.get(result.custom_id)
            if not file_path:
                logger.warning("Unknown custom_id in results: %s", result.custom_id)
                continue

            if result.error:
                # Request failed
                logger.error("Extraction failed for %s: %s", file_path, result.error)
                failed_files.append(file_path)
                self._mark_failed(file_path, str(result.error))
            elif result.response:
                # Request succeeded, validate and save
                try:
                    # Parse response (same structure as sync API)
                    # Response should have choices[0].message.content with JSON
                    metadata_dict = self._extract_metadata_from_response(result.response)

                    # Read transcript for confidence calculation and semantic topic selection
                    transcript_text = Path(file_path).read_text(encoding="utf-8")
                    transcript_length = len(transcript_text)

                    # Validate extraction (with document text for semantic topic selection)
                    validation = validate_extraction(metadata_dict, document_text=transcript_text)

                    if not validation.hard_failures:
                        # Passed validation (extracted or needs_review)
                        # Calculate confidence score
                        try:
                            model_confidence = float(metadata_dict.get("confidence_score", 0))
                        except (TypeError, ValueError):
                            model_confidence = 0.0

                        confidence = calculate_confidence(
                            model_confidence=model_confidence,
                            validation=validation,
                            transcript_length=transcript_length,
                        )

                        # Determine status based on confidence and soft warnings
                        if validation.soft_warnings or confidence < 0.85:
                            status = "needs_review"
                        else:
                            status = "extracted"

                        # Save to database
                        self._save_extracted_metadata(
                            file_path,
                            metadata_dict,
                            confidence,
                            status,
                        )
                        succeeded_count += 1
                        print(f"✓ Saved: {Path(file_path).name} (conf: {confidence*100:.1f}%, status={status})")
                    else:
                        # Hard validation failures - reject
                        logger.warning("Hard validation failures for %s: %s", file_path, validation.hard_failures)
                        failed_files.append(file_path)
                        self._mark_failed(file_path, f"Validation failed: {', '.join(validation.hard_failures)}")

                except Exception as e:
                    logger.error("Failed to process result for %s: %s", file_path, e)
                    failed_files.append(file_path)
                    self._mark_failed(file_path, str(e))
            else:
                logger.warning("Result for %s has no response or error", file_path)
                failed_files.append(file_path)
                self._mark_failed(file_path, "No response or error in result")

        processing_time = time.time() - start_time

        logger.info(
            "Batch extraction complete: %d succeeded, %d failed, %d oversized (%.1fs)",
            succeeded_count,
            len(failed_files),
            len(oversized_files),
            processing_time,
        )

        return {
            "batch_id": batch_id,
            "total": len(batch_requests),
            "succeeded": succeeded_count,
            "failed": len(failed_files),
            "failed_files": failed_files,
            "oversized_files": oversized_files,
            "processing_time_seconds": processing_time,
        }

    def _get_pending_files(self, max_files: int | None) -> list[dict]:
        """Get pending files from database for batch extraction."""
        query = """
            SELECT file_path, metadata_json
            FROM files
            WHERE ai_metadata_status = 'pending'
              AND (file_path LIKE '%.txt' OR file_path LIKE '%.md')
            ORDER BY file_path
        """

        if max_files:
            query += f" LIMIT {max_files}"

        cursor = self._db.conn.execute(query)
        return [{"file_path": row[0], "metadata_json": row[1]} for row in cursor.fetchall()]

    def _extract_metadata_from_response(self, response: dict) -> dict:
        """Extract metadata dict from Mistral API response.

        Response structure:
        {
            "choices": [{
                "message": {
                    "content": "{...JSON...}"
                }
            }],
            "usage": {...}
        }
        """
        if "choices" not in response or not response["choices"]:
            raise ValueError("Response missing 'choices' field")

        message_content = response["choices"][0]["message"]["content"]

        # Parse JSON content using existing parser
        # (handles thinking blocks, etc.)
        import json
        from mistralai.models import ChatCompletionResponse

        # Create a minimal response object for parser
        class MinimalChoice:
            def __init__(self, content):
                self.message = type('obj', (object,), {'content': content})

        class MinimalResponse:
            def __init__(self, content):
                self.choices = [MinimalChoice(content)]

        minimal_response = MinimalResponse(message_content)
        return parse_magistral_response(minimal_response)

    def _save_extracted_metadata(
        self,
        file_path: str,
        metadata: dict,
        confidence_score: float,
        status: str = "extracted",
    ) -> None:
        """Save extracted metadata to database (matches synchronous orchestrator pattern)."""
        import json

        with self._db.conn:
            # 1. Update files table status
            self._db.conn.execute(
                "UPDATE files SET ai_metadata_status = ?, ai_confidence_score = ? "
                "WHERE file_path = ?",
                (status, confidence_score, file_path),
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
                    json.dumps(metadata),
                    "magistral-medium-latest",  # Model used in batch
                    "batch-v1",  # Batch API version
                    f"batch-{self._strategy_name}",  # Config identifier
                ),
            )

            # 4. Insert primary topics
            valid_topics = metadata.get("primary_topics", [])
            if valid_topics:
                # Clear existing topics
                self._db.conn.execute(
                    "DELETE FROM file_primary_topics WHERE file_path = ?",
                    (file_path,),
                )
                # Insert new topics
                for topic in valid_topics:
                    self._db.conn.execute(
                        "INSERT INTO file_primary_topics (file_path, topic_tag) "
                        "VALUES (?, ?)",
                        (file_path, topic),
                    )

        self._db.conn.commit()

    def _mark_failed(self, file_path: str, error_message: str) -> None:
        """Mark file as failed in database for retry tracking."""
        self._db.conn.execute(
            """
            UPDATE files
            SET ai_metadata_status = 'failed_validation',
                error_message = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')
            WHERE file_path = ?
            """,
            (error_message, file_path),
        )
        self._db.conn.commit()

    def _mark_oversized(self, file_path: str, token_count: int) -> None:
        """Mark file as oversized (skip extraction, use Gemini File Search only).

        These files exceed Mistral's context window and will be uploaded to
        Gemini File Search without enriched metadata extraction.

        Args:
            file_path: Path to oversized file.
            token_count: Estimated token count.
        """
        self._db.conn.execute(
            """
            UPDATE files
            SET ai_metadata_status = 'skipped',
                error_message = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')
            WHERE file_path = ?
            """,
            (f"Oversized for extraction (~{token_count} tokens, max {MAX_DOCUMENT_TOKENS}). Will use Gemini File Search without enrichment.", file_path),
        )
        self._db.conn.commit()
