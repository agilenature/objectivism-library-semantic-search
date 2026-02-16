"""Batch upload orchestrator for the Gemini File Search pipeline.

Composes the upload primitives (client, state manager, circuit breaker,
rate limiter, progress tracker) into a complete upload engine that:

* Processes pending files in configurable batch sizes
* Limits concurrency with ``asyncio.Semaphore``
* Writes state before every API call (crash recovery)
* Polls import operations to completion
* Handles graceful shutdown on Ctrl+C (SIGINT/SIGTERM)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import uuid
from typing import Any

from objlib.models import UploadConfig
from objlib.upload.circuit_breaker import CircuitState, RollingWindowCircuitBreaker
from objlib.upload.client import GeminiFileSearchClient, RateLimitError
from objlib.upload.state import AsyncUploadStateManager

logger = logging.getLogger(__name__)


class UploadOrchestrator:
    """Main upload engine coordinating the full Gemini upload pipeline.

    Usage::

        orchestrator = UploadOrchestrator(client, state, circuit_breaker, config)
        await orchestrator.run("objectivism-library-v1")

    Args:
        client: Gemini File Search API client.
        state: Async SQLite state manager.
        circuit_breaker: Rolling-window circuit breaker for 429 tracking.
        config: Upload pipeline configuration.
        progress: Optional Rich progress tracker (omit for headless mode).
    """

    def __init__(
        self,
        client: GeminiFileSearchClient,
        state: AsyncUploadStateManager,
        circuit_breaker: RollingWindowCircuitBreaker,
        config: UploadConfig,
        progress: Any | None = None,
    ) -> None:
        self._client = client
        self._state = state
        self._circuit_breaker = circuit_breaker
        self._config = config
        self._progress = progress

        self._upload_semaphore = asyncio.Semaphore(config.max_concurrent_uploads)
        self._poll_semaphore = asyncio.Semaphore(config.max_concurrent_polls)
        self._shutdown_event = asyncio.Event()

        # Tracking
        self._succeeded = 0
        self._failed = 0
        self._skipped = 0
        self._total = 0
        self._instance_id = f"upload-{uuid.uuid4().hex[:8]}-{os.getpid()}"

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------

    def setup_signal_handlers(self) -> None:
        """Register SIGINT/SIGTERM handlers for graceful shutdown.

        First signal sets the shutdown event (complete current uploads).
        Second signal forces immediate exit.
        """
        self._signal_count = 0

        def _handler(signum: int, frame: Any) -> None:
            self._signal_count += 1
            if self._signal_count == 1:
                logger.warning(
                    "Graceful shutdown initiated, completing current uploads..."
                )
                self._shutdown_event.set()
            else:
                logger.warning("Forced shutdown. Exiting immediately.")
                raise SystemExit(1)

        try:
            signal.signal(signal.SIGINT, _handler)
            signal.signal(signal.SIGTERM, _handler)
        except (OSError, ValueError):
            # signal handlers can only be set in main thread
            logger.debug("Could not set signal handlers (not main thread)")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self, store_display_name: str) -> dict[str, int]:
        """Execute the full upload pipeline.

        1. Ensure Gemini store exists
        2. Acquire single-writer lock
        3. Fetch pending files from SQLite
        4. Split into batches and process
        5. Release lock and return summary

        Args:
            store_display_name: Display name for the Gemini File Search store.

        Returns:
            Summary dict with total, succeeded, failed, skipped counts.
        """
        self.setup_signal_handlers()

        # Step 1: Ensure store exists
        logger.info("Ensuring store '%s' exists...", store_display_name)
        await self._client.get_or_create_store(store_display_name)

        # Step 2: Acquire single-writer lock
        locked = await self._state.acquire_lock(self._instance_id)
        if not locked:
            logger.error("Could not acquire upload lock -- another instance may be running")
            return self.summary

        try:
            # Step 3: Get pending files
            pending = await self._state.get_pending_files(limit=10000)
            self._total = len(pending)

            if not pending:
                logger.info("No pending files to upload")
                return self.summary

            logger.info(
                "Found %d pending files, processing in batches of %d",
                self._total,
                self._config.batch_size,
            )

            # Step 4: Split into batches and process
            batches = [
                pending[i : i + self._config.batch_size]
                for i in range(0, len(pending), self._config.batch_size)
            ]

            if self._progress is not None:
                self._progress.start()

            try:
                for batch_num, batch_files in enumerate(batches, start=1):
                    if self._shutdown_event.is_set():
                        logger.warning("Shutdown requested, skipping remaining batches")
                        self._skipped += sum(
                            len(b)
                            for b in batches[batch_num:]
                        )
                        break
                    await self._process_batch(batch_files, batch_num)
            finally:
                if self._progress is not None:
                    self._progress.stop()

        except asyncio.CancelledError:
            logger.warning("Upload cancelled, saving state...")
        finally:
            # Step 5: Release lock
            await self._state.release_lock()
            logger.info(
                "Upload complete: %d succeeded, %d failed, %d skipped of %d total",
                self._succeeded,
                self._failed,
                self._skipped,
                self._total,
            )

        return self.summary

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    async def _process_batch(
        self, files: list[dict], batch_number: int
    ) -> None:
        """Process a single logical batch of files.

        Uploads all files concurrently (semaphore-limited), then polls
        all resulting operations concurrently.
        """
        batch_id = await self._state.create_batch(batch_number, len(files))

        if self._progress is not None:
            self._progress.start_batch(batch_number, len(files))

        logger.info(
            "Starting batch %d (%d files)", batch_number, len(files)
        )

        # Phase 1: Upload all files in this batch
        upload_tasks = [self._upload_single_file(f) for f in files]
        upload_results = await asyncio.gather(*upload_tasks, return_exceptions=True)

        # Collect successful operations for polling
        operations: list[tuple[str, Any]] = []
        batch_succeeded = 0
        batch_failed = 0

        for result in upload_results:
            if isinstance(result, Exception):
                batch_failed += 1
                logger.error("Upload task exception: %s", result)
            elif result is None:
                # Skipped (shutdown or circuit breaker open)
                pass
            else:
                operations.append(result)

        # Phase 2: Poll all operations
        if operations:
            poll_tasks = [self._poll_single_operation(op) for op in operations]
            poll_results = await asyncio.gather(*poll_tasks, return_exceptions=True)

            for result in poll_results:
                if isinstance(result, Exception):
                    batch_failed += 1
                    logger.error("Poll task exception: %s", result)
                elif result is True:
                    batch_succeeded += 1
                else:
                    batch_failed += 1

        # Update batch record
        status = "completed" if batch_failed == 0 else "failed"
        await self._state.update_batch(
            batch_id, batch_succeeded, batch_failed, status
        )

        if self._progress is not None:
            self._progress.complete_batch(batch_number)

        logger.info(
            "Batch %d complete: %d succeeded, %d failed",
            batch_number,
            batch_succeeded,
            batch_failed,
        )

    # ------------------------------------------------------------------
    # Single file upload
    # ------------------------------------------------------------------

    async def _upload_single_file(
        self, file_info: dict
    ) -> tuple[str, Any] | None:
        """Upload a single file through the two-step pipeline.

        1. Check shutdown and circuit breaker state
        2. Record intent in SQLite (BEFORE API call)
        3. Upload file and import to store
        4. Record success in SQLite (AFTER API response)

        Returns:
            Tuple of (file_path, operation) on success, or None if skipped.
        """
        file_path = file_info["file_path"]

        # Check shutdown
        if self._shutdown_event.is_set():
            self._skipped += 1
            return None

        # Check circuit breaker
        if self._circuit_breaker.state == CircuitState.OPEN:
            logger.warning(
                "Circuit breaker OPEN, skipping %s", file_path
            )
            self._skipped += 1
            if self._progress is not None:
                self._progress.file_rate_limited(file_path)
            return None

        # Record intent BEFORE API call (crash recovery anchor)
        await self._state.record_upload_intent(file_path)

        try:
            # Parse metadata
            metadata_json = file_info.get("metadata_json") or "{}"
            metadata = json.loads(metadata_json)
            custom_metadata = self._client.build_custom_metadata(metadata)

            # Build display name (truncated to 512 chars)
            display_name = file_info.get("filename", os.path.basename(file_path))[:512]

            # Upload with semaphore-limited concurrency
            async with self._upload_semaphore:
                file_obj, operation = await self._client.upload_and_import(
                    file_path, display_name, custom_metadata
                )

            # Record success AFTER API response
            await self._state.record_upload_success(
                file_path,
                getattr(file_obj, "uri", ""),
                getattr(file_obj, "name", ""),
                getattr(operation, "name", ""),
            )

            if self._progress is not None:
                self._progress.file_uploaded(file_path)

            # Adjust semaphore based on circuit breaker recommendation
            recommended = self._circuit_breaker.get_recommended_concurrency(
                self._config.max_concurrent_uploads
            )
            if recommended != self._upload_semaphore._value:
                self._upload_semaphore = asyncio.Semaphore(recommended)
                if self._progress is not None:
                    self._progress.update_circuit_state(
                        self._circuit_breaker.state.value, recommended
                    )

            return (file_path, operation)

        except RateLimitError as exc:
            logger.warning("Rate limited uploading %s: %s", file_path, exc)
            await self._state.record_upload_failure(file_path, str(exc))
            self._failed += 1
            if self._progress is not None:
                self._progress.file_rate_limited(file_path)
            return None

        except Exception as exc:
            logger.error("Failed to upload %s: %s", file_path, exc)
            await self._state.record_upload_failure(file_path, str(exc))
            self._failed += 1
            if self._progress is not None:
                self._progress.file_failed(file_path, str(exc))
            return None

    # ------------------------------------------------------------------
    # Operation polling
    # ------------------------------------------------------------------

    async def _poll_single_operation(
        self, operation_info: tuple[str, Any]
    ) -> bool:
        """Poll a single operation until completion.

        Args:
            operation_info: Tuple of (file_path, operation).

        Returns:
            True if the operation succeeded, False otherwise.
        """
        file_path, operation = operation_info

        try:
            async with self._poll_semaphore:
                completed = await self._client.poll_operation(
                    operation, timeout=self._config.poll_timeout_seconds
                )

            # Check if operation completed successfully
            done = getattr(completed, "done", False)
            error = getattr(completed, "error", None)

            if done and not error:
                op_name = getattr(operation, "name", "")
                await self._state.record_import_success(file_path, op_name)
                self._succeeded += 1
                return True
            else:
                error_msg = str(error) if error else "Operation did not complete"
                op_name = getattr(operation, "name", "")
                await self._state.update_operation_state(
                    op_name, "failed", error_msg
                )
                await self._state.record_upload_failure(file_path, error_msg)
                self._failed += 1
                if self._progress is not None:
                    self._progress.file_failed(file_path, error_msg)
                return False

        except Exception as exc:
            logger.error("Poll failed for %s: %s", file_path, exc)
            op_name = getattr(operation, "name", "")
            await self._state.update_operation_state(
                op_name, "timeout", str(exc)
            )
            await self._state.record_upload_failure(file_path, str(exc))
            self._failed += 1
            if self._progress is not None:
                self._progress.file_failed(file_path, str(exc))
            return False

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    @property
    def summary(self) -> dict[str, int]:
        """Return upload summary counts."""
        return {
            "total": self._total,
            "succeeded": self._succeeded,
            "failed": self._failed,
            "skipped": self._skipped,
            "pending": self._total - self._succeeded - self._failed - self._skipped,
        }
