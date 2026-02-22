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
from objlib.upload.exceptions import OCCConflictError
from objlib.upload.fsm import create_fsm
from objlib.upload.metadata_builder import build_enriched_metadata, compute_upload_hash
from objlib.upload.recovery import RecoveryManager, retry_failed_file
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

                # Reset for re-upload in database
                await db.execute(
                    """UPDATE files
                       SET error_message = NULL,
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


class FSMUploadOrchestrator(EnrichedUploadOrchestrator):
    """Upload orchestrator using FSM-mediated state transitions.

    Replaces legacy status-based upload path with FSM transitions.
    All ``gemini_state`` mutations go through ``transition_to_*()``
    methods on :class:`AsyncUploadStateManager` (SC4 compliance).

    Key differences from :class:`EnrichedUploadOrchestrator`:

    * Uses ``get_fsm_pending_files()`` (gemini_state='untracked')
      instead of ``get_pending_files()`` (status='pending').
    * All state transitions validated by :func:`create_fsm` before
      DB persistence.
    * ``_reset_existing_files_fsm()`` deletes store document BEFORE
      raw file (SC3 compliance) with write-ahead intent.
    * display_name sanitized with ``.strip()`` before upload
      (Phase 11 finding: leading whitespace causes import hang).

    Usage::

        orchestrator = FSMUploadOrchestrator(client, state, cb, config)
        await orchestrator.run_fsm("objectivism-library")
    """

    # ------------------------------------------------------------------
    # FSM upload entry point
    # ------------------------------------------------------------------

    async def run_fsm(self, store_display_name: str) -> dict[str, int]:
        """Execute the FSM-mediated upload pipeline.

        1. Setup signal handlers
        2. Ensure Gemini store exists
        3. Acquire single-writer lock
        4. Optionally reset already-indexed files (SC3-compliant)
        5. Fetch untracked files via get_fsm_pending_files()
        6. Process in batches using FSM transitions
        7. Release lock and return summary

        Args:
            store_display_name: Display name for the Gemini File Search store.

        Returns:
            Summary dict with total, succeeded, failed, skipped, reset counts.
        """
        self.setup_signal_handlers()

        # Step 1: Ensure store exists
        logger.info("Ensuring store '%s' exists...", store_display_name)
        await self._client.get_or_create_store(store_display_name)

        # Step 2: Acquire single-writer lock
        locked = await self._state.acquire_lock(self._instance_id)
        if not locked:
            logger.error("Could not acquire upload lock -- another instance may be running")
            return self.enriched_summary

        try:
            # Step 3: Reset already-indexed files if requested
            if self._reset_existing:
                await self._reset_existing_files_fsm(limit=self._file_limit)

            # Step 4: Get FSM pending files (untracked)
            limit = self._file_limit if self._file_limit > 0 else 50
            pending = await self._state.get_fsm_pending_files(limit=limit)
            self._total = len(pending)

            if not pending:
                logger.info("No untracked files to upload")
                return self.enriched_summary

            logger.info(
                "Found %d untracked files, processing in batches of %d",
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
                    await self._process_fsm_batch(batch_files, batch_num)
            finally:
                if self._progress is not None:
                    self._progress.stop()

        except asyncio.CancelledError:
            logger.warning("Upload cancelled, saving state...")
        finally:
            # Step 6: Release lock
            await self._state.release_lock()
            logger.info(
                "FSM upload complete: %d succeeded, %d failed, %d skipped, "
                "%d reset of %d total",
                self._succeeded,
                self._failed,
                self._skipped,
                self._reset_count,
                self._total,
            )

        return self.enriched_summary

    # ------------------------------------------------------------------
    # FSM batch processing
    # ------------------------------------------------------------------

    async def _process_fsm_batch(
        self, files: list[dict], batch_number: int
    ) -> None:
        """Process a batch of files through FSM-mediated upload.

        Same structure as parent ``_process_enriched_batch`` but uses
        FSM transition methods. Includes a retry pass for transient
        failures (30s cooldown).
        """
        batch_id = await self._state.create_batch(batch_number, len(files))

        if self._progress is not None:
            self._progress.start_batch(batch_number, len(files))

        logger.info(
            "Starting FSM batch %d (%d files)", batch_number, len(files)
        )

        # Phase 1: Upload all files with staggered launches
        upload_tasks = []
        file_map: dict[str, dict] = {}
        for i, f in enumerate(files):
            if i > 0:
                await asyncio.sleep(1.0)  # Stagger to prevent burst
            task = asyncio.create_task(self._upload_fsm_file(f))
            upload_tasks.append(task)
            file_map[f["file_path"]] = f

        upload_results = await asyncio.gather(*upload_tasks, return_exceptions=True)

        # Collect successful operations for polling
        operations: list[tuple[str, Any, int]] = []  # (file_path, operation, version)
        batch_succeeded = 0
        batch_failed = 0

        for result in upload_results:
            if isinstance(result, Exception):
                batch_failed += 1
                logger.error("FSM upload task exception: %s", result)
            elif result is None:
                # Skipped (shutdown, circuit breaker, or invalid transition)
                pass
            else:
                operations.append(result)

        # Phase 2: Poll all operations
        failed_files: list[dict] = []
        if operations:
            poll_tasks = [
                self._poll_fsm_operation(op_info) for op_info in operations
            ]
            poll_results = await asyncio.gather(*poll_tasks, return_exceptions=True)

            for i, result in enumerate(poll_results):
                if isinstance(result, Exception):
                    batch_failed += 1
                    logger.error("FSM poll task exception: %s", result)
                    file_path = operations[i][0]
                    if file_path in file_map:
                        failed_files.append(file_map[file_path])
                elif result is True:
                    batch_succeeded += 1
                else:
                    batch_failed += 1
                    file_path = operations[i][0]
                    if file_path in file_map:
                        failed_files.append(file_map[file_path])

        # Phase 3: Retry pass for failures
        retry_succeeded = 0
        retry_failed = 0
        if failed_files and not self._shutdown_event.is_set():
            logger.info(
                "FSM batch %d: %d failures detected, starting retry pass after 30s cooldown...",
                batch_number,
                len(failed_files),
            )
            await asyncio.sleep(30.0)

            # Reset failed files back to untracked before retrying
            retry_operations = []
            for f in failed_files:
                fp = f["file_path"]
                # Use retry_failed_file to reset FAILED -> UNTRACKED
                reset_ok = await retry_failed_file(self._state, fp)
                if not reset_ok:
                    logger.warning(
                        "Could not reset %s for retry (not in failed state?)", fp
                    )
                    continue
                # Re-read current version and state from DB
                state_val, version_val = await self._state.get_file_version(fp)
                f_updated = dict(f)
                f_updated["version"] = version_val
                f_updated["gemini_state"] = state_val
                result = await self._upload_fsm_file(f_updated)
                if result is not None:
                    retry_operations.append(result)

            if retry_operations:
                retry_poll_tasks = [
                    self._poll_fsm_operation(op_info)
                    for op_info in retry_operations
                ]
                retry_poll_results = await asyncio.gather(
                    *retry_poll_tasks, return_exceptions=True
                )

                for result in retry_poll_results:
                    if isinstance(result, Exception):
                        retry_failed += 1
                        logger.error("FSM retry poll exception: %s", result)
                    elif result is True:
                        retry_succeeded += 1
                        batch_succeeded += 1
                        batch_failed -= 1
                        self._retry_succeeded += 1
                    else:
                        retry_failed += 1

            logger.info(
                "FSM batch %d retry pass: %d succeeded, %d still failed",
                batch_number,
                retry_succeeded,
                retry_failed,
            )

        # Update batch record
        status = "completed" if batch_failed == 0 else "failed"
        await self._state.update_batch(
            batch_id, batch_succeeded, batch_failed, status
        )

        if self._progress is not None:
            self._progress.complete_batch(batch_number)

        logger.info(
            "FSM batch %d complete: %d succeeded, %d failed%s",
            batch_number,
            batch_succeeded,
            batch_failed,
            f" (after {retry_succeeded} retries)" if retry_succeeded > 0 else "",
        )

    # ------------------------------------------------------------------
    # FSM single file upload
    # ------------------------------------------------------------------

    async def _upload_fsm_file(
        self, file_info: dict
    ) -> tuple[str, Any, int] | None:
        """Upload a single file through FSM-mediated transitions.

        Lifecycle: untracked -> uploading -> processing (after upload API).
        The polling phase completes processing -> indexed.

        Returns:
            Tuple of (file_path, operation, current_version) for polling,
            or None if skipped.
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

        # Read version from file_info (already provided by get_fsm_pending_files)
        version = file_info.get("version", 0)
        current_state = file_info.get("gemini_state", "untracked")

        # Validate transition is legal via ephemeral FSM
        try:
            fsm = create_fsm(current_state)
            fsm.start_upload()
        except Exception as exc:
            logger.warning(
                "Invalid FSM transition for %s (state=%s): %s",
                file_path, current_state, exc,
            )
            self._skipped += 1
            return None

        try:
            # Write-ahead intent: transition to uploading (OCC-guarded)
            version = await self._state.transition_to_uploading(file_path, version)

            # Build display_name with .strip() (Phase 11: leading whitespace causes hang)
            display_name = file_info.get("filename", os.path.basename(file_path))[:512].strip()

            # Parse metadata and build enriched metadata if available
            metadata_json = file_info.get("metadata_json") or "{}"
            metadata = json.loads(metadata_json)
            custom_metadata = self._client.build_custom_metadata(metadata)

            # Prepare content (use enriched content if AI metadata available)
            upload_path = file_path
            temp_path = None
            ai_json = file_info.get("ai_metadata_json")
            if ai_json:
                ai_metadata = json.loads(ai_json)
                custom_metadata = build_enriched_metadata(
                    metadata, ai_metadata,
                    file_info.get("entity_names", []),
                )
                temp_path = prepare_enriched_content(file_path, ai_metadata)
                if temp_path is not None:
                    upload_path = temp_path

            try:
                # Upload with semaphore-limited concurrency
                async with self._upload_semaphore:
                    file_obj, operation = await self._client.upload_and_import(
                        upload_path, display_name, custom_metadata
                    )
            finally:
                cleanup_temp_file(temp_path)

            # Transition to processing: record Gemini file identifiers
            version = await self._state.transition_to_processing(
                file_path,
                version,
                getattr(file_obj, "name", ""),
                getattr(file_obj, "uri", ""),
            )

            if self._progress is not None:
                self._progress.file_uploaded(file_path)

            return (file_path, operation, version)

        except OCCConflictError as exc:
            logger.warning("OCC conflict uploading %s: %s", file_path, exc)
            self._skipped += 1
            return None

        except RateLimitError as exc:
            logger.warning("Rate limited uploading %s: %s", file_path, exc)
            try:
                await self._state.transition_to_failed(file_path, version, str(exc))
            except OCCConflictError:
                pass
            self._failed += 1
            if self._progress is not None:
                self._progress.file_rate_limited(file_path)
            return None

        except Exception as exc:
            logger.error("Failed to upload %s: %s", file_path, exc)
            try:
                await self._state.transition_to_failed(file_path, version, str(exc))
            except OCCConflictError:
                pass
            self._failed += 1
            if self._progress is not None:
                self._progress.file_failed(file_path, str(exc))
            return None

    # ------------------------------------------------------------------
    # FSM operation polling
    # ------------------------------------------------------------------

    async def _poll_fsm_operation(
        self, operation_info: tuple[str, Any, int]
    ) -> bool:
        """Poll an operation and transition to indexed or failed.

        Args:
            operation_info: Tuple of (file_path, operation, current_version).

        Returns:
            True if the operation succeeded and file is indexed.
        """
        file_path, operation, version = operation_info

        try:
            async with self._poll_semaphore:
                completed = await self._client.poll_operation(
                    operation, timeout=self._config.poll_timeout_seconds
                )

            done = getattr(completed, "done", False)
            error = getattr(completed, "error", None)

            if done and not error:
                # Extract document_name (gemini_store_doc_id)
                gemini_store_doc_id = None
                response = getattr(completed, "response", None)
                if response is not None:
                    gemini_store_doc_id = getattr(response, "document_name", None)
                    if gemini_store_doc_id is None:
                        # Fallback: check name attribute
                        gemini_store_doc_id = getattr(response, "name", None)

                # If still None, try raw dict parsing
                if gemini_store_doc_id is None:
                    raw = getattr(completed, "_raw_response", None)
                    if isinstance(raw, dict):
                        resp = raw.get("response", {})
                        gemini_store_doc_id = resp.get("documentName") or resp.get("name")

                if gemini_store_doc_id is None:
                    logger.warning(
                        "Could not extract document_name from operation response for %s",
                        file_path,
                    )
                    gemini_store_doc_id = ""

                # Transition to indexed
                await self._state.transition_to_indexed(
                    file_path, version, gemini_store_doc_id
                )
                self._succeeded += 1
                return True
            else:
                error_msg = str(error) if error else "Operation did not complete"
                await self._state.transition_to_failed(file_path, version, error_msg)
                self._failed += 1
                if self._progress is not None:
                    self._progress.file_failed(file_path, error_msg)
                return False

        except OCCConflictError as exc:
            logger.warning("OCC conflict polling %s: %s", file_path, exc)
            self._failed += 1
            return False

        except Exception as exc:
            logger.error("Poll failed for %s: %s", file_path, exc)
            try:
                await self._state.transition_to_failed(file_path, version, str(exc))
            except OCCConflictError:
                pass
            self._failed += 1
            if self._progress is not None:
                self._progress.file_failed(file_path, str(exc))
            return False

    # ------------------------------------------------------------------
    # SC3-compliant reset: store doc BEFORE raw file
    # ------------------------------------------------------------------

    async def _reset_existing_files_fsm(self, limit: int = 0) -> None:
        """Reset indexed files for re-upload using FSM transitions.

        SC3 compliance: deletes store document BEFORE raw file.
        Uses write-ahead intent for crash recovery.

        1. Write reset intent (OCC-guarded)
        2. Delete store document (permanent indexed entry)
        3. Delete raw file (temporary 48hr file)
        4. Finalize reset (clear IDs, set untracked)

        Args:
            limit: Max files to reset (0 = no limit).
        """
        db = self._state._ensure_connected()
        cursor = await db.execute(
            """SELECT file_path, gemini_file_id, gemini_store_doc_id, version
               FROM files
               WHERE gemini_state = 'indexed'
                 AND gemini_store_doc_id IS NOT NULL"""
        )
        files_to_reset = [dict(r) for r in await cursor.fetchall()]

        if limit > 0:
            files_to_reset = files_to_reset[:limit]

        if not files_to_reset:
            logger.info("No indexed files need FSM reset")
            return

        logger.info(
            "Resetting %d indexed files for re-upload (SC3-compliant)",
            len(files_to_reset),
        )

        for file_info in files_to_reset:
            file_path = file_info["file_path"]
            version = file_info["version"]
            gemini_store_doc_id = file_info.get("gemini_store_doc_id")
            gemini_file_id = file_info.get("gemini_file_id")

            try:
                # Step 1: Write-ahead intent (OCC-guarded, no version increment)
                await self._state.write_reset_intent(file_path, version)

                # Step 2: Delete store document FIRST (SC3 order)
                if gemini_store_doc_id:
                    # Construct full resource name if DB stores only the suffix
                    doc_resource_name = gemini_store_doc_id
                    if not doc_resource_name.startswith("fileSearchStores/"):
                        store_name = self._client.store_name or ""
                        doc_resource_name = f"{store_name}/documents/{gemini_store_doc_id}"
                    try:
                        await self._client.delete_store_document(doc_resource_name)
                    except Exception as exc:
                        exc_str = str(exc)
                        if "404" not in exc_str and "NOT_FOUND" not in exc_str:
                            raise
                    await self._state.update_intent_progress(file_path, 1)
                else:
                    # Legacy path: gemini_store_doc_id missing, try list+map lookup
                    if gemini_file_id:
                        doc_name = await self._client.find_store_document_name(gemini_file_id)
                        if doc_name:
                            try:
                                await self._client.delete_store_document(doc_name)
                            except Exception as exc:
                                exc_str = str(exc)
                                if "404" not in exc_str and "NOT_FOUND" not in exc_str:
                                    raise
                    await self._state.update_intent_progress(file_path, 1)

                # Step 3: Delete raw file SECOND
                if gemini_file_id:
                    file_name = gemini_file_id
                    if not file_name.startswith("files/"):
                        file_name = f"files/{file_name}"
                    try:
                        await self._client.delete_file(file_name)
                    except Exception as exc:
                        exc_str = str(exc)
                        if "404" not in exc_str and "NOT_FOUND" not in exc_str:
                            raise
                await self._state.update_intent_progress(file_path, 2)

                # Step 4: Finalize (OCC-guarded, increments version)
                success = await self._state.finalize_reset(file_path, version)
                if success:
                    self._reset_count += 1
                    logger.info("Reset %s (store doc -> raw file -> finalize)", file_path)
                else:
                    logger.warning(
                        "OCC conflict finalizing reset for %s (another writer?)",
                        file_path,
                    )

            except OCCConflictError as exc:
                logger.warning("OCC conflict resetting %s: %s", file_path, exc)

            except Exception as exc:
                logger.error("Failed to reset %s: %s", file_path, exc)
