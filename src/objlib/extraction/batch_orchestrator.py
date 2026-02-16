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
from objlib.extraction.parser import parse_magistral_response
from objlib.extraction.prompts import build_system_prompt, build_user_prompt
from objlib.extraction.validator import validate_and_score

if TYPE_CHECKING:
    from objlib.database import Database

logger = logging.getLogger(__name__)


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
        logger.info("Loading pending files from database...")
        pending_files = self._get_pending_files(max_files)

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

        # Step 2: Build batch requests
        logger.info("Building batch requests...")
        batch_requests = []
        file_map = {}  # custom_id -> file_path mapping

        for idx, file_record in enumerate(pending_files):
            file_path = file_record["file_path"]
            custom_id = str(idx)  # Use simple numeric ID

            # Read file content
            try:
                content = Path(file_path).read_text(encoding="utf-8")
            except Exception as e:
                logger.error("Failed to read file %s: %s", file_path, e)
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
                "failed": len(pending_files),
                "failed_files": [f["file_path"] for f in pending_files],
                "processing_time_seconds": time.time() - start_time,
            }

        logger.info("Built %d batch requests", len(batch_requests))

        # Step 3: Submit batch
        logger.info("Submitting batch job to Mistral...")
        batch_id = await self._client.submit_batch(
            requests=batch_requests,
            job_name=job_name or f"extraction-{len(batch_requests)}",
            metadata={"strategy": self._strategy_name},
            use_inline=len(batch_requests) <= 10_000,  # Use inline if possible
        )

        logger.info("Batch job submitted: %s", batch_id)

        # Step 4: Poll until completion
        logger.info("Polling for batch completion (interval=%ds)...", poll_interval)
        try:
            final_status = await self._client.wait_for_completion(
                batch_id=batch_id,
                poll_interval=poll_interval,
                timeout=7200,  # 2 hours max
            )

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
                "processing_time_seconds": time.time() - start_time,
            }

        # Step 5: Download and parse results
        logger.info("Downloading batch results...")
        results = await self._client.download_results(batch_id)

        # Step 6: Process results and update database
        logger.info("Processing %d results...", len(results))
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

                    # Validate using existing validator
                    validation_result = validate_and_score(
                        metadata_dict,
                        Path(file_path).read_text(encoding="utf-8"),
                    )

                    if validation_result["validation_status"] == "extracted":
                        # Success - save to database
                        self._save_extracted_metadata(
                            file_path,
                            validation_result["metadata"],
                            validation_result["confidence_score"],
                        )
                        succeeded_count += 1
                        logger.info("✓ Saved: %s (conf: %.1f%%)", Path(file_path).name, validation_result["confidence_score"] * 100)
                    else:
                        # Validation failed
                        logger.warning("Validation failed for %s: %s", file_path, validation_result)
                        failed_files.append(file_path)
                        self._mark_failed(file_path, f"Validation failed: {validation_result}")

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
            "Batch extraction complete: %d succeeded, %d failed (%.1fs)",
            succeeded_count,
            len(failed_files),
            processing_time,
        )

        return {
            "batch_id": batch_id,
            "total": len(batch_requests),
            "succeeded": succeeded_count,
            "failed": len(failed_files),
            "failed_files": failed_files,
            "processing_time_seconds": processing_time,
        }

    def _get_pending_files(self, max_files: int | None) -> list[dict]:
        """Get pending files from database for batch extraction."""
        query = """
            SELECT file_path, metadata_json
            FROM files
            WHERE ai_metadata_status = 'pending'
              AND status != 'skipped'
              AND file_path LIKE '%.txt'
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
    ) -> None:
        """Save extracted metadata to database."""
        import json

        self._db.conn.execute(
            """
            UPDATE files
            SET ai_metadata_json = ?,
                ai_metadata_status = 'extracted',
                ai_confidence_score = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')
            WHERE file_path = ?
            """,
            (json.dumps(metadata), confidence_score, file_path),
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
