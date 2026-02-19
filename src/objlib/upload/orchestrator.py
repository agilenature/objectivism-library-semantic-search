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
from objlib.upload.content_preparer import cleanup_temp_file, prepare_enriched_content
from objlib.upload.metadata_builder import build_enriched_metadata, compute_upload_hash
from objlib.upload.recovery import RecoveryManager
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

        # Step 0: Run crash recovery
        recovery = RecoveryManager(self._client, self._state, self._config)
        recovery_result = await recovery.run()
        if recovery_result.recovered_operations > 0 or recovery_result.reset_to_pending > 0:
            logger.info(
                "Recovery: %d ops recovered, %d files reset to pending",
                recovery_result.recovered_operations,
                recovery_result.reset_to_pending,
            )

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


class EnrichedUploadOrchestrator(UploadOrchestrator):
    """Upload orchestrator for enriched metadata uploads.

    Extends :class:`UploadOrchestrator` to upload files with 4-tier AI
    metadata, entity mentions, and Tier 4 content injection. Key differences
    from the parent:

    * Uses ``get_enriched_pending_files()`` instead of ``get_pending_files()``
      (strict entity gate: AI metadata + entity extraction + pending status).
    * Optionally resets already-uploaded files for re-upload with enriched
      metadata (``--reset-existing``).
    * Builds ``CustomMetadata`` with ``string_list_value`` fields via
      ``build_enriched_metadata()``.
    * Prepends Tier 4 AI analysis to file content via
      ``prepare_enriched_content()``.
    * Skips files whose ``last_upload_hash`` matches (idempotency).
    * Conservative concurrency: ``Semaphore(2)`` default with 1-second
      staggered launch delay.

    Usage::

        orchestrator = EnrichedUploadOrchestrator(client, state, cb, config)
        await orchestrator.run_enriched("objectivism-library-test")
    """

    def __init__(
        self,
        client: GeminiFileSearchClient,
        state: AsyncUploadStateManager,
        circuit_breaker: RollingWindowCircuitBreaker,
        config: UploadConfig,
        progress: Any | None = None,
        reset_existing: bool = True,
        include_needs_review: bool = True,
        file_limit: int = 0,
    ) -> None:
        super().__init__(client, state, circuit_breaker, config, progress)
        self._reset_existing = reset_existing
        self._include_needs_review = include_needs_review
        self._file_limit = file_limit
        self._reset_count = 0
        self._retry_succeeded = 0  # Track post-batch retry successes

    # ------------------------------------------------------------------
    # Enriched upload entry point
    # ------------------------------------------------------------------

    async def run_enriched(self, store_display_name: str) -> dict[str, int]:
        """Execute the enriched upload pipeline.

        1. Ensure Gemini store exists
        2. Acquire single-writer lock
        3. Optionally reset already-uploaded files for re-upload
        4. Fetch enriched pending files from SQLite
        5. Split into batches and process with enriched upload
        6. Release lock and return summary

        Args:
            store_display_name: Display name for the Gemini File Search store.

        Returns:
            Summary dict with total, succeeded, failed, skipped, reset counts.
        """
        self.setup_signal_handlers()

        # Step 0: Run crash recovery
        recovery = RecoveryManager(self._client, self._state, self._config)
        recovery_result = await recovery.run()
        if recovery_result.recovered_operations > 0 or recovery_result.reset_to_pending > 0:
            logger.info(
                "Recovery: %d ops recovered, %d files reset to pending",
                recovery_result.recovered_operations,
                recovery_result.reset_to_pending,
            )

        # Step 1: Ensure store exists
        logger.info("Ensuring store '%s' exists...", store_display_name)
        await self._client.get_or_create_store(store_display_name)

        # Step 2: Acquire single-writer lock
        locked = await self._state.acquire_lock(self._instance_id)
        if not locked:
            logger.error("Could not acquire upload lock -- another instance may be running")
            return self.enriched_summary

        try:
            # Step 3: Reset already-uploaded files if requested
            if self._reset_existing:
                await self._reset_existing_files(limit=self._file_limit)

            # Step 4: Get enriched pending files
            limit = self._file_limit if self._file_limit > 0 else 10000
            pending = await self._state.get_enriched_pending_files(
                limit=limit,
                include_needs_review=self._include_needs_review,
            )
            self._total = len(pending)

            if not pending:
                logger.info("No enriched pending files to upload")
                return self.enriched_summary

            logger.info(
                "Found %d enriched pending files, processing in batches of %d",
                self._total,
                self._config.batch_size,
            )

            # Step 5: Split into batches and process
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
                    await self._process_enriched_batch(batch_files, batch_num)
            finally:
                if self._progress is not None:
                    self._progress.stop()

        except asyncio.CancelledError:
            logger.warning("Upload cancelled, saving state...")
        finally:
            # Step 6: Release lock
            await self._state.release_lock()
            logger.info(
                "Enriched upload complete: %d succeeded, %d failed, %d skipped, "
                "%d reset of %d total",
                self._succeeded,
                self._failed,
                self._skipped,
                self._reset_count,
                self._total,
            )

        return self.enriched_summary

    # ------------------------------------------------------------------
    # Reset already-uploaded files
    # ------------------------------------------------------------------

    async def _reset_existing_files(self, limit: int = 0) -> None:
        """Delete already-uploaded files from Gemini and reset to pending.

        Identifies files that were uploaded with Phase 1 metadata only
        (or failed) and have enriched metadata available. For each:
        1. Delete from Gemini via client.delete_file() if gemini_file_id exists
        2. Reset status to 'pending' in the database

        Args:
            limit: Max files to reset (0 = no limit). Should match file_limit
                so that --limit N resets at most N files, not all eligible files.
        """
        files_to_reset = await self._state.get_files_to_reset_for_enriched_upload()
        if limit > 0:
            files_to_reset = files_to_reset[:limit]

        if not files_to_reset:
            logger.info("No files need resetting for enriched re-upload")
            return

        logger.info(
            "Resetting %d already-uploaded/failed files for enriched re-upload",
            len(files_to_reset),
        )

        db = self._state._ensure_connected()
        now = self._state._now_iso()

        # Fetch all store documents once to build an O(1) lookup.
        # Avoids calling list_store_documents() inside the loop (which would be O(N²)).
        doc_name_by_file_id: dict[str, str] = {}
        try:
            store_documents = await self._client.list_store_documents()
            for _doc in store_documents:
                _doc_name = getattr(_doc, "name", "") or ""
                # display_name holds the plain file ID set at import time.
                # The document resource name uses a compound suffix that does
                # not match DB gemini_file_id values directly.
                _display = getattr(_doc, "display_name", "") or ""
                if _doc_name and _display:
                    doc_name_by_file_id[_display] = _doc_name
            logger.info(
                "Built store document lookup with %d entries for reset cleanup",
                len(doc_name_by_file_id),
            )
        except Exception as exc:
            logger.warning(
                "Could not list store documents for reset cleanup: %s -- "
                "store documents will not be deleted during this reset",
                exc,
            )

        for file_info in files_to_reset:
            file_path = file_info["file_path"]
            gemini_file_id = file_info.get("gemini_file_id")

            try:
                # Delete from Gemini if there's a remote file
                if gemini_file_id:
                    # Normalize to full resource name if needed
                    if not gemini_file_id.startswith("files/"):
                        gemini_file_id = f"files/{gemini_file_id}"
                    try:
                        await self._client.delete_file(gemini_file_id)
                        logger.info("Deleted %s from Gemini", gemini_file_id)
                    except Exception as exc:
                        # File may already be expired/deleted -- continue
                        logger.warning(
                            "Could not delete %s from Gemini: %s",
                            gemini_file_id,
                            exc,
                        )

                    # Delete the corresponding store document (permanently indexed entry).
                    # Raw files (Files API) expire in 48hr; store documents never expire
                    # and must be explicitly deleted. Without this, every --reset-existing
                    # run leaves an orphaned store document that accumulates indefinitely
                    # and causes [Unresolved file #N] in search results.
                    file_id_suffix = gemini_file_id.replace("files/", "")
                    store_doc_name = doc_name_by_file_id.get(file_id_suffix)
                    if store_doc_name:
                        try:
                            await self._client.delete_store_document(store_doc_name)
                            logger.info(
                                "Deleted store document %s for %s",
                                store_doc_name,
                                gemini_file_id,
                            )
                        except Exception as exc:
                            logger.warning(
                                "Could not delete store document %s: %s",
                                store_doc_name,
                                exc,
                            )

                # Reset to pending in database
                await db.execute(
                    """UPDATE files
                       SET status = 'pending',
                           error_message = NULL,
                           upload_attempt_count = 0,
                           gemini_file_uri = NULL,
                           gemini_file_id = NULL,
                           remote_expiration_ts = NULL,
                           upload_timestamp = NULL,
                           updated_at = ?
                       WHERE file_path = ?""",
                    (now, file_path),
                )
                await db.commit()
                self._reset_count += 1

            except Exception as exc:
                logger.error("Failed to reset %s: %s", file_path, exc)

    # ------------------------------------------------------------------
    # Enriched batch processing
    # ------------------------------------------------------------------

    async def _process_enriched_batch(
        self, files: list[dict], batch_number: int
    ) -> None:
        """Process a batch of enriched files with staggered launches and retry pass.

        Same structure as parent _process_batch but uses enriched upload
        method, adds 1-second delay between task launches, and includes
        a post-batch retry pass for transient failures.

        Retry Pass:
          - Collects all failures after main batch polling
          - Waits 30 seconds (API cooldown)
          - Retries failed files once more
          - Reports final success/failure counts
        """
        batch_id = await self._state.create_batch(batch_number, len(files))

        if self._progress is not None:
            self._progress.start_batch(batch_number, len(files))

        logger.info(
            "Starting enriched batch %d (%d files)", batch_number, len(files)
        )

        # Phase 1: Upload all files with staggered launches
        upload_tasks = []
        file_map = {}  # Track file_path -> file_info for retry
        for i, f in enumerate(files):
            if i > 0:
                await asyncio.sleep(1.0)  # Stagger to prevent burst
            task = asyncio.create_task(self._upload_enriched_file(f))
            upload_tasks.append(task)
            file_map[f["file_path"]] = f

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
                # Skipped (shutdown, circuit breaker open, or idempotent)
                pass
            else:
                operations.append(result)

        # Phase 2: Poll all operations
        failed_files = []
        if operations:
            poll_tasks = [self._poll_single_operation(op) for op in operations]
            poll_results = await asyncio.gather(*poll_tasks, return_exceptions=True)

            for i, result in enumerate(poll_results):
                if isinstance(result, Exception):
                    batch_failed += 1
                    logger.error("Poll task exception: %s", result)
                    # Track for retry
                    file_path = operations[i][0]
                    if file_path in file_map:
                        failed_files.append(file_map[file_path])
                elif result is True:
                    batch_succeeded += 1
                else:
                    batch_failed += 1
                    # Track for retry
                    file_path = operations[i][0]
                    if file_path in file_map:
                        failed_files.append(file_map[file_path])

        # Phase 3: Retry pass for failures (Option 3)
        retry_succeeded = 0
        retry_failed = 0
        if failed_files and not self._shutdown_event.is_set():
            logger.info(
                "Batch %d: %d failures detected, starting retry pass after 30s cooldown...",
                batch_number,
                len(failed_files),
            )
            await asyncio.sleep(30.0)  # API cooldown

            # Retry each failed file
            retry_operations = []
            for f in failed_files:
                result = await self._upload_enriched_file(f)
                if result is not None:
                    retry_operations.append(result)

            # Poll retry operations
            if retry_operations:
                retry_poll_tasks = [
                    self._poll_single_operation(op) for op in retry_operations
                ]
                retry_poll_results = await asyncio.gather(
                    *retry_poll_tasks, return_exceptions=True
                )

                for result in retry_poll_results:
                    if isinstance(result, Exception):
                        retry_failed += 1
                        logger.error("Retry poll exception: %s", result)
                    elif result is True:
                        retry_succeeded += 1
                        # Adjust batch counters
                        batch_succeeded += 1
                        batch_failed -= 1
                        # Track global retry successes
                        self._retry_succeeded += 1
                    else:
                        retry_failed += 1

            logger.info(
                "Batch %d retry pass: %d succeeded, %d still failed",
                batch_number,
                retry_succeeded,
                retry_failed,
            )

        # Update batch record with final counts
        status = "completed" if batch_failed == 0 else "failed"
        await self._state.update_batch(
            batch_id, batch_succeeded, batch_failed, status
        )

        if self._progress is not None:
            self._progress.complete_batch(batch_number)

        logger.info(
            "Enriched batch %d complete: %d succeeded, %d failed%s",
            batch_number,
            batch_succeeded,
            batch_failed,
            f" (after {retry_succeeded} retries)" if retry_succeeded > 0 else "",
        )

    # ------------------------------------------------------------------
    # Enriched single file upload
    # ------------------------------------------------------------------

    async def _upload_enriched_file(
        self, file_info: dict
    ) -> tuple[str, Any] | None:
        """Upload a single file with enriched metadata and content injection.

        1. Parse Phase 1 metadata, AI metadata, and entity names
        2. Compute upload hash for idempotency
        3. Build enriched CustomMetadata via build_enriched_metadata()
        4. Prepare enriched content via prepare_enriched_content()
        5. Upload with semaphore-limited concurrency
        6. Record success and update upload hash

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
            logger.warning("Circuit breaker OPEN, skipping %s", file_path)
            self._skipped += 1
            if self._progress is not None:
                self._progress.file_rate_limited(file_path)
            return None

        # Parse metadata
        phase1_json = file_info.get("phase1_metadata_json") or "{}"
        ai_json = file_info.get("ai_metadata_json") or "{}"
        phase1_metadata = json.loads(phase1_json)
        ai_metadata = json.loads(ai_json)
        entity_names = file_info.get("entity_names", [])
        content_hash = file_info.get("content_hash", "")

        # Idempotency check via upload hash
        upload_hash = compute_upload_hash(
            phase1_metadata, ai_metadata, entity_names, content_hash
        )
        if file_info.get("last_upload_hash") == upload_hash:
            logger.debug("Skipping %s (upload hash unchanged)", file_path)
            self._skipped += 1
            return None

        # Build enriched CustomMetadata
        custom_metadata = build_enriched_metadata(
            phase1_metadata, ai_metadata, entity_names
        )

        # Prepare enriched content (temp file with Tier 4 header)
        temp_path = None
        try:
            temp_path = prepare_enriched_content(file_path, ai_metadata)
            upload_path = temp_path if temp_path is not None else file_path

            # Build display name (truncated to 512 chars)
            display_name = file_info.get("filename", os.path.basename(file_path))[:512]

            # Record intent BEFORE API call
            await self._state.record_upload_intent(file_path)

            # Upload with semaphore-limited concurrency
            async with self._upload_semaphore:
                file_obj, operation = await self._client.upload_and_import(
                    upload_path, display_name, custom_metadata
                )

            # Record success AFTER API response
            await self._state.record_upload_success(
                file_path,
                getattr(file_obj, "uri", ""),
                getattr(file_obj, "name", ""),
                getattr(operation, "name", ""),
            )

            # Update upload hash and attempt count
            db = self._state._ensure_connected()
            now = self._state._now_iso()
            await db.execute(
                """UPDATE files
                   SET last_upload_hash = ?,
                       upload_attempt_count = COALESCE(upload_attempt_count, 0) + 1,
                       updated_at = ?
                   WHERE file_path = ?""",
                (upload_hash, now, file_path),
            )
            await db.commit()

            if self._progress is not None:
                self._progress.file_uploaded(file_path)

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

        finally:
            # Always clean up temp file
            cleanup_temp_file(temp_path)

    # ------------------------------------------------------------------
    # Enriched summary
    # ------------------------------------------------------------------

    @property
    def enriched_summary(self) -> dict[str, int]:
        """Return enriched upload summary counts."""
        return {
            "total": self._total,
            "succeeded": self._succeeded,
            "failed": self._failed,
            "skipped": self._skipped,
            "reset": self._reset_count,
            "retried": self._retry_succeeded,  # Post-batch retry successes
            "pending": self._total - self._succeeded - self._failed - self._skipped,
        }
