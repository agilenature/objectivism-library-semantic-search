"""Crash recovery protocol for the upload pipeline.

Handles three recovery scenarios per locked decision #9 (Crash Recovery):

1. **Interrupted uploads** -- Files in ``uploading`` status where the process
   crashed between recording intent and receiving the API response.
2. **Pending operations** -- Import operations that were submitted but never
   polled to completion.
3. **Expiration deadlines** -- Files approaching or past the 48-hour TTL
   (locked decision #1), which must be reset for re-upload.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from objlib.models import UploadConfig
from objlib.upload.client import GeminiFileSearchClient
from objlib.upload.exceptions import OCCConflictError
from objlib.upload.state import AsyncUploadStateManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class RecoveryTimeoutError(Exception):
    """Raised when recovery takes longer than the configured timeout."""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class RecoveryResult:
    """Summary of a recovery run.

    Attributes:
        recovered_operations: Operations polled to completion during recovery.
        reset_to_pending: Files reset from ``uploading`` or expired to ``pending``.
        expired_files: Files whose 48-hour TTL had passed completely.
        deadline_critical: Files within 8 hours of their expiration deadline.
        errors: Human-readable descriptions of non-fatal errors encountered.
    """

    recovered_operations: int = 0
    reset_to_pending: int = 0
    expired_files: int = 0
    deadline_critical: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Recovery manager
# ---------------------------------------------------------------------------


class RecoveryManager:
    """Orchestrates crash recovery across the three recovery phases.

    Intended to be called once at the start of every upload run, before
    processing new files.  Recovers from any previous crash or interruption.

    Args:
        client: Gemini File Search API client for polling operations.
        state: Async SQLite state manager for reading/writing file state.
        config: Upload configuration (provides ``recovery_timeout_seconds``).
    """

    def __init__(
        self,
        client: GeminiFileSearchClient,
        state: AsyncUploadStateManager,
        config: UploadConfig,
    ) -> None:
        self._client = client
        self._state = state
        self._config = config

    async def run(self) -> RecoveryResult:
        """Execute the full recovery protocol with a timeout guard.

        Returns:
            :class:`RecoveryResult` summarising what was recovered.

        Raises:
            RecoveryTimeoutError: If recovery exceeds
                ``config.recovery_timeout_seconds`` (default 4 hours).
        """
        timeout = self._config.recovery_timeout_seconds
        try:
            return await asyncio.wait_for(
                self._recover(), timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.critical(
                "Recovery timed out after %d seconds", timeout
            )
            raise RecoveryTimeoutError(
                f"Recovery exceeded {timeout}s timeout"
            ) from None

    # ------------------------------------------------------------------
    # Internal recovery phases
    # ------------------------------------------------------------------

    async def _recover(self) -> RecoveryResult:
        """Run all three recovery phases sequentially."""
        result = RecoveryResult()

        logger.info("Starting crash recovery...")

        # Phase 1: Interrupted uploads
        await self._recover_interrupted_uploads(result)

        # Phase 2: Pending operations
        await self._recover_pending_operations(result)

        # Phase 3: Expiration deadlines
        await self._check_expiration_deadlines(result)

        logger.info(
            "Recovery complete: %d ops recovered, %d reset to pending, "
            "%d expired, %d deadline-critical, %d errors",
            result.recovered_operations,
            result.reset_to_pending,
            result.expired_files,
            result.deadline_critical,
            len(result.errors),
        )

        return result

    async def _recover_interrupted_uploads(self, result: RecoveryResult) -> None:
        """Phase 1: Handle files stuck in ``uploading`` status.

        If a file has a ``gemini_file_id`` the upload itself succeeded but
        the import may not have been recorded.  If there is no
        ``gemini_file_id`` the upload never completed and the file should
        be reset to ``pending`` for re-upload.
        """
        uploading = await self._state.get_uploading_files()
        if not uploading:
            logger.debug("Phase 1: No interrupted uploads found")
            return

        logger.info("Phase 1: Found %d interrupted uploads", len(uploading))

        for file_info in uploading:
            file_path = file_info["file_path"]
            try:
                # Check if a gemini_file_id was recorded (upload succeeded
                # but import may be incomplete)
                db = self._state._ensure_connected()
                cursor = await db.execute(
                    "SELECT gemini_file_id, remote_expiration_ts "
                    "FROM files WHERE file_path = ?",
                    (file_path,),
                )
                row = await cursor.fetchone()

                if row and row["gemini_file_id"]:
                    # Upload succeeded -- check if the remote file is
                    # still valid (not expired)
                    expiration_str = row["remote_expiration_ts"]
                    if expiration_str and self._is_expired(expiration_str):
                        logger.warning(
                            "File %s has expired remote copy, resetting",
                            file_path,
                        )
                        await self._reset_file_to_pending(file_path)
                        result.reset_to_pending += 1
                        result.expired_files += 1
                    else:
                        # File is uploaded and still valid -- mark as
                        # indexed (import may have completed but state
                        # was not updated due to crash)
                        logger.info(
                            "File %s has valid remote copy, marking indexed",
                            file_path,
                        )
                        now = self._state._now_iso()
                        await db.execute(
                            "UPDATE files SET gemini_state = 'indexed', "
                            "updated_at = ? WHERE file_path = ?",
                            (now, file_path),
                        )
                        await db.commit()
                        result.recovered_operations += 1
                else:
                    # No gemini_file_id -- upload never completed, reset
                    logger.info(
                        "File %s has no remote copy, resetting to pending",
                        file_path,
                    )
                    await self._reset_file_to_pending(file_path)
                    result.reset_to_pending += 1

            except Exception as exc:
                msg = f"Error recovering interrupted upload for {file_path}: {exc}"
                logger.error(msg)
                result.errors.append(msg)

    async def _recover_pending_operations(self, result: RecoveryResult) -> None:
        """Phase 2: Poll pending/in-progress operations to completion.

        For each tracked operation, attempts a short poll.  Completed
        operations update the file status; failed or expired operations
        reset the file to ``pending`` for re-upload.
        """
        operations = await self._state.get_pending_operations()
        if not operations:
            logger.debug("Phase 2: No pending operations found")
            return

        logger.info("Phase 2: Found %d pending operations", len(operations))

        for op_info in operations:
            op_name = op_info["operation_name"]
            file_path = op_info["file_path"]

            try:
                # Create a minimal operation-like object for the client
                op_proxy = _OperationProxy(op_name)
                completed = await asyncio.wait_for(
                    self._client.poll_operation(op_proxy, timeout=60),
                    timeout=65,  # slightly longer than poll timeout
                )

                done = getattr(completed, "done", None)
                error = getattr(completed, "error", None)

                if done is True and not error:
                    await self._state.record_import_success(
                        file_path, op_name
                    )
                    result.recovered_operations += 1
                    logger.info(
                        "Operation %s completed successfully", op_name
                    )
                elif done is True and error:
                    await self._state.update_operation_state(
                        op_name, "failed", str(error)
                    )
                    await self._reset_file_to_pending(file_path)
                    result.reset_to_pending += 1
                    logger.warning(
                        "Operation %s failed: %s", op_name, error
                    )
                else:
                    # Not done yet -- leave for the orchestrator to poll
                    logger.info(
                        "Operation %s still in progress, leaving for "
                        "orchestrator",
                        op_name,
                    )

            except (asyncio.TimeoutError, TimeoutError):
                # Operation poll timed out -- leave as pending
                logger.warning(
                    "Timeout polling operation %s, will retry later", op_name
                )

            except Exception as exc:
                # API error (file expired, not found, etc.)
                msg = f"Error polling operation {op_name}: {exc}"
                logger.error(msg)
                result.errors.append(msg)

                # Reset file for re-upload since we can't determine status
                await self._state.update_operation_state(
                    op_name, "failed", str(exc)
                )
                await self._reset_file_to_pending(file_path)
                result.reset_to_pending += 1

    async def _check_expiration_deadlines(self, result: RecoveryResult) -> None:
        """Phase 3: Identify files approaching or past the 48-hour TTL.

        Queries all files with a ``remote_expiration_ts`` set and checks:
        * **Expired** (past deadline): reset gemini identifiers and status
          to ``pending``
        * **Danger zone** (within 8 hours): log a warning and track as
          ``deadline_critical``
        """
        db = self._state._ensure_connected()
        cursor = await db.execute(
            """SELECT file_path, gemini_file_id, gemini_file_uri,
                      remote_expiration_ts, gemini_state
               FROM files
               WHERE remote_expiration_ts IS NOT NULL
                 AND gemini_state IN ('uploading', 'indexed')"""
        )
        rows = await cursor.fetchall()

        if not rows:
            logger.debug("Phase 3: No files with expiration deadlines")
            return

        logger.info(
            "Phase 3: Checking %d files with expiration deadlines",
            len(rows),
        )

        now = datetime.now(timezone.utc)

        for row in rows:
            file_path = row["file_path"]
            expiration_str = row["remote_expiration_ts"]

            if not expiration_str:
                continue

            try:
                expiration = datetime.fromisoformat(
                    expiration_str.replace("Z", "+00:00")
                )
                # Ensure timezone-aware
                if expiration.tzinfo is None:
                    expiration = expiration.replace(tzinfo=timezone.utc)

                hours_remaining = (expiration - now).total_seconds() / 3600

                if hours_remaining <= 0:
                    current_state = row["gemini_state"]
                    if current_state == "indexed":
                        # Indexed files: raw file expired but store doc is
                        # permanent. Just clear stale raw-file fields.
                        logger.debug(
                            "File %s raw file expired (%.1fh past) but "
                            "indexed -- clearing raw fields only",
                            file_path,
                            abs(hours_remaining),
                        )
                        db_inner = self._state._ensure_connected()
                        now_iso = self._state._now_iso()
                        await db_inner.execute(
                            """UPDATE files
                               SET gemini_file_uri = NULL,
                                   gemini_file_id = NULL,
                                   remote_expiration_ts = NULL,
                                   updated_at = ?
                               WHERE file_path = ?""",
                            (now_iso, file_path),
                        )
                        await db_inner.commit()
                        result.expired_files += 1
                    else:
                        # Non-indexed (uploading): truly stuck, reset
                        logger.warning(
                            "File %s has EXPIRED (%.1f hours past deadline)",
                            file_path,
                            abs(hours_remaining),
                        )
                        await self._reset_file_to_pending(file_path, clear_remote=True)
                        result.expired_files += 1
                        result.reset_to_pending += 1

                elif hours_remaining <= 8:
                    # Danger zone: log warning
                    logger.warning(
                        "File %s approaching deadline: %.1f hours remaining",
                        file_path,
                        hours_remaining,
                    )
                    result.deadline_critical += 1

            except (ValueError, TypeError) as exc:
                msg = f"Error parsing expiration for {file_path}: {exc}"
                logger.error(msg)
                result.errors.append(msg)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _reset_file_to_pending(
        self, file_path: str, *, clear_remote: bool = False
    ) -> None:
        """Reset a file for re-upload, optionally clearing Gemini IDs."""
        db = self._state._ensure_connected()
        now = self._state._now_iso()

        if clear_remote:
            await db.execute(
                """UPDATE files
                   SET gemini_state = 'untracked',
                       gemini_file_uri = NULL,
                       gemini_file_id = NULL,
                       remote_expiration_ts = NULL,
                       upload_timestamp = NULL,
                       updated_at = ?
                   WHERE file_path = ?""",
                (now, file_path),
            )
        else:
            await db.execute(
                "UPDATE files SET gemini_state = 'untracked', "
                "updated_at = ? WHERE file_path = ?",
                (now, file_path),
            )
        await db.commit()

    @staticmethod
    def _is_expired(expiration_str: str) -> bool:
        """Check whether an expiration timestamp is in the past."""
        try:
            expiration = datetime.fromisoformat(
                expiration_str.replace("Z", "+00:00")
            )
            if expiration.tzinfo is None:
                expiration = expiration.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) > expiration
        except (ValueError, TypeError):
            return False


# ---------------------------------------------------------------------------
# Internal proxy for operation polling
# ---------------------------------------------------------------------------


class _OperationProxy:
    """Lightweight proxy that looks like a Gemini Operation for polling.

    The :meth:`client.poll_operation` method passes the operation object
    to ``client.aio.operations.get(operation)``.  The SDK accepts the
    operation name string, so we expose ``.name`` for compatibility.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"_OperationProxy({self.name!r})"


# ---------------------------------------------------------------------------
# FSM Recovery Crawler (Phase 12)
# ---------------------------------------------------------------------------


class RecoveryCrawler:
    """Startup recovery for files with pending write-ahead intents.

    Scans for files with ``intent_type IS NOT NULL`` (indicating a crash
    during a multi-step transition) and recovers each to 'untracked'
    using linear step resumption.  No retry loops (GA-9).

    SC6: :meth:`_recover_file` raises :class:`OCCConflictError` if
    :meth:`finalize_reset` returns ``False``.  The outer
    :meth:`recover_all` catches per-file and continues.

    Args:
        state: Async SQLite state manager.
        client: Gemini File Search API client for deletion calls.
    """

    def __init__(
        self,
        state: AsyncUploadStateManager,
        client: GeminiFileSearchClient,
    ) -> None:
        self._state = state
        self._client = client

    async def recover_all(self) -> tuple[list[str], list[str]]:
        """Scan for pending intents and recover each file.

        Returns:
            Tuple of (recovered_paths, occ_failure_paths).
        """
        db = self._state._ensure_connected()
        cursor = await db.execute(
            """SELECT file_path, intent_type, intent_api_calls_completed,
                      gemini_store_doc_id, gemini_file_id, version
               FROM files WHERE intent_type IS NOT NULL
               ORDER BY intent_started_at ASC"""
        )
        rows = [dict(r) for r in await cursor.fetchall()]

        recovered: list[str] = []
        occ_failures: list[str] = []
        for row in rows:
            try:
                await self._recover_file(row)
                recovered.append(row["file_path"])
            except OCCConflictError as exc:
                logger.error(
                    "Recovery OCC conflict (file will retry next startup): %s", exc
                )
                occ_failures.append(row["file_path"])
                # Per Q3: catch per-file, continue to next
            except Exception as exc:
                logger.error("Failed to recover %s: %s", row["file_path"], exc)
        return recovered, occ_failures

    async def _recover_file(self, row: dict) -> None:
        """Linear step resumption from crash point.

        SC6: raises :class:`OCCConflictError` on OCC conflict in
        :meth:`finalize_reset`.
        """
        file_path = row["file_path"]
        completed = row["intent_api_calls_completed"] or 0

        # Step 1: Delete store document (if not already done)
        if completed < 1 and row.get("gemini_store_doc_id"):
            try:
                await self._client.delete_store_document(row["gemini_store_doc_id"])
            except Exception as exc:
                if "404" not in str(exc) and "NOT_FOUND" not in str(exc):
                    raise
            await self._state.update_intent_progress(file_path, 1)

        # Step 2: Delete raw file (if not already done)
        if completed < 2 and row.get("gemini_file_id"):
            file_name = row["gemini_file_id"]
            if not file_name.startswith("files/"):
                file_name = f"files/{file_name}"
            try:
                await self._client.delete_file(file_name)
            except Exception as exc:
                if "404" not in str(exc) and "NOT_FOUND" not in str(exc):
                    raise
            await self._state.update_intent_progress(file_path, 2)

        # Step 3: Finalize (SC6 fix -- check return value and raise)
        result = await self._state.finalize_reset(file_path, row["version"])
        if not result:
            raise OCCConflictError(
                f"finalize_reset() OCC conflict during recovery: {file_path}"
            )
        logger.info(
            "Recovered %s: intent=%s, resumed_from_step=%d",
            file_path, row["intent_type"], completed,
        )


# ---------------------------------------------------------------------------
# Standalone retry helper (Phase 12)
# ---------------------------------------------------------------------------


async def retry_failed_file(
    state: AsyncUploadStateManager, file_path: str
) -> bool:
    """Transition a FAILED file back to UNTRACKED for re-upload.

    This is the production equivalent of the Phase 10 spike's
    ``retry_failed_file()`` -- a standalone function (not an FSM
    adapter) for the FAILED->UNTRACKED escape path.

    Args:
        state: Async SQLite state manager.
        file_path: Primary key of the file to retry.

    Returns:
        True if the file was successfully reset, False otherwise.
    """
    db = state._ensure_connected()
    now = state._now_iso()
    cursor = await db.execute(
        """UPDATE files
           SET gemini_state = 'untracked',
               gemini_file_id = NULL,
               gemini_file_uri = NULL,
               gemini_store_doc_id = NULL,
               upload_timestamp = NULL,
               remote_expiration_ts = NULL,
               intent_type = NULL,
               intent_started_at = NULL,
               intent_api_calls_completed = NULL,
               error_message = NULL,
               version = version + 1,
               gemini_state_updated_at = ?
           WHERE file_path = ?
             AND gemini_state = 'failed'""",
        (now, file_path),
    )
    await db.commit()
    return cursor.rowcount == 1


async def cleanup_and_reset_failed_files(
    state: AsyncUploadStateManager,
    client: GeminiFileSearchClient,
) -> tuple[int, int]:
    """Reconcile FAILED files against actual Gemini state.

    Called at fsm-upload startup (after RecoveryCrawler) to resolve files whose
    DB state diverged from Gemini reality due to the ``done`` attribute polling bug.

    Discovery findings (2026-02-23):
    - 20/20 sampled FAILED files are Class B: raw file ACTIVE, store doc STATE_ACTIVE.
    - The ``done`` default mismatch caused a false FAILED label -- imports succeeded.
    - ``DocumentState`` has 4 values: STATE_ACTIVE, STATE_PENDING, STATE_FAILED,
      STATE_UNSPECIFIED.  Presence in the store alone is NOT sufficient for upgrade --
      the state must be explicitly STATE_ACTIVE (HOSTILE distrust principle, Phase 9).

    Classification by (store_doc_state, store_doc_present):
        STATE_ACTIVE   → upgrade ``failed`` → ``indexed``, set ``gemini_store_doc_id``
        STATE_PENDING  → leave as ``failed``; import in progress, pick up next startup
        STATE_FAILED   → delete store doc + raw file, reset ``failed`` → ``untracked``
        not in store   → delete raw file (if any), reset ``failed`` → ``untracked``

    Args:
        state: Async SQLite state manager.
        client: Gemini client for store document listing.

    Returns:
        Tuple of (upgraded_to_indexed, reset_to_untracked) counts.
    """
    from google.genai.types import DocumentState

    db = state._ensure_connected()

    rows = await db.execute_fetchall(
        """SELECT file_path, gemini_file_id
           FROM files
           WHERE gemini_state = 'failed'""",
    )

    if not rows:
        return (0, 0)

    # Build store-doc lookup once: normalised file_id -> (doc_name_suffix, doc_state, full_name).
    # doc.display_name == file resource ID (Phase 11 finding).
    # gemini_store_doc_id stores only the suffix (Phase 12-03 decision).
    # doc.state is checked for STATE_ACTIVE before upgrading (HOSTILE distrust principle).
    store_doc_by_file_id: dict[str, tuple[str, object, str]] = {}
    try:
        store_docs = await client.list_store_documents()
        for doc in store_docs:
            display_name = getattr(doc, "display_name", None)
            full_name = getattr(doc, "name", None)
            doc_state = getattr(doc, "state", None)
            if display_name and full_name:
                key = display_name if display_name.startswith("files/") else f"files/{display_name}"
                doc_suffix = full_name.rsplit("/", 1)[-1]
                store_doc_by_file_id[key] = (doc_suffix, doc_state, full_name)
    except Exception:
        logger.warning(
            "cleanup_and_reset_failed_files: could not list store documents; "
            "resetting all failed files to untracked without upgrade"
        )
        reset_count = 0
        for row in rows:
            if await retry_failed_file(state, row["file_path"]):
                reset_count += 1
        return (0, reset_count)

    upgraded = 0
    reset = 0
    now = state._now_iso()

    for row in rows:
        file_path = row["file_path"]
        gemini_file_id = row["gemini_file_id"]

        file_id_key = (
            gemini_file_id
            if (gemini_file_id or "").startswith("files/")
            else f"files/{gemini_file_id}"
        ) if gemini_file_id else None

        store_entry = store_doc_by_file_id.get(file_id_key) if file_id_key else None

        if store_entry is not None:
            doc_suffix, doc_state, full_doc_name = store_entry

            if doc_state == DocumentState.STATE_ACTIVE:
                # Affirmative evidence: import succeeded, doc is searchable.
                # Upgrade to indexed (8th authorized gemini_state write site).
                cursor = await db.execute(
                    """UPDATE files
                       SET gemini_state          = 'indexed',
                           gemini_store_doc_id   = ?,
                           error_message         = NULL,
                           intent_type           = NULL,
                           intent_started_at     = NULL,
                           intent_api_calls_completed = NULL,
                           version               = version + 1,
                           gemini_state_updated_at = ?
                       WHERE file_path = ?
                         AND gemini_state = 'failed'""",
                    (doc_suffix, now, file_path),
                )
                await db.commit()
                if cursor.rowcount == 1:
                    upgraded += 1
                    logger.debug(
                        "cleanup_and_reset_failed_files: upgraded %s -> indexed (doc=%s)",
                        file_path, doc_suffix,
                    )

            elif doc_state == DocumentState.STATE_PENDING:
                # Import still in progress -- leave as 'failed'; will be resolved
                # by the next startup invocation once Gemini finishes indexing.
                logger.debug(
                    "cleanup_and_reset_failed_files: %s store doc STATE_PENDING, leaving as failed",
                    file_path,
                )

            else:
                # STATE_FAILED or STATE_UNSPECIFIED: Gemini store indexing failed.
                # Delete the failed store doc and raw file; reset to untracked.
                try:
                    await client.delete_store_document(full_doc_name)
                    logger.debug(
                        "cleanup_and_reset_failed_files: deleted STATE_FAILED store doc %s for %s",
                        doc_suffix, file_path,
                    )
                except Exception as exc:
                    logger.warning(
                        "cleanup_and_reset_failed_files: could not delete store doc for %s: %s",
                        file_path, exc,
                    )
                if gemini_file_id:
                    raw_name = (
                        gemini_file_id if gemini_file_id.startswith("files/")
                        else f"files/{gemini_file_id}"
                    )
                    try:
                        await client.delete_file(raw_name)
                    except Exception:
                        pass
                did_reset = await retry_failed_file(state, file_path)
                if did_reset:
                    reset += 1

        else:
            # Not in store at all -- raw file only or nothing.
            # Clean up raw file (may already be expired) and reset to untracked.
            if gemini_file_id:
                file_name = (
                    gemini_file_id
                    if gemini_file_id.startswith("files/")
                    else f"files/{gemini_file_id}"
                )
                try:
                    await client.delete_file(file_name)
                    logger.debug(
                        "cleanup_and_reset_failed_files: deleted raw file %s for %s",
                        file_name, file_path,
                    )
                except Exception as exc:
                    logger.debug(
                        "cleanup_and_reset_failed_files: raw file deletion skipped for %s: %s",
                        file_path, exc,
                    )

            did_reset = await retry_failed_file(state, file_path)
            if did_reset:
                reset += 1
                logger.debug(
                    "cleanup_and_reset_failed_files: reset %s -> untracked", file_path
                )

    logger.info(
        "cleanup_and_reset_failed_files: upgraded %d to indexed, reset %d to untracked",
        upgraded, reset,
    )
    return (upgraded, reset)


# ---------------------------------------------------------------------------
# Untracked-with-store-doc recovery (Phase 16)
# ---------------------------------------------------------------------------


async def recover_untracked_with_store_doc(
    state: AsyncUploadStateManager,
    client: GeminiFileSearchClient,
) -> tuple[int, int]:
    """Recover untracked files that already have valid store documents.

    Called when the RecoveryManager incorrectly reset indexed files to
    untracked due to raw file expiration (the ``remote_expiration_ts`` bug in
    ``_check_expiration_deadlines`` which checked ``gemini_state = 'indexed'``).

    These files have ``gemini_store_doc_id`` set (the reset preserved it) but
    ``gemini_file_id`` cleared.  We look up each doc suffix in the live store
    and restore the file to ``indexed`` iff the doc is ``STATE_ACTIVE``.

    Classification by doc state in live store:
        STATE_ACTIVE   → restore ``untracked`` → ``indexed``
        STATE_PENDING  → leave as ``untracked`` (import still completing)
        STATE_FAILED   → delete store doc, clear ``gemini_store_doc_id``
        not in store   → clear ``gemini_store_doc_id``, re-upload cleanly

    Args:
        state: Async SQLite state manager.
        client: Gemini client for store document listing.

    Returns:
        Tuple of (restored_to_indexed, cleared_store_doc_id) counts.
    """
    from google.genai.types import DocumentState

    db = state._ensure_connected()

    rows = await db.execute_fetchall(
        """SELECT file_path, gemini_store_doc_id
           FROM files
           WHERE gemini_state = 'untracked'
             AND gemini_store_doc_id IS NOT NULL
             AND gemini_store_doc_id != ''""",
    )

    if not rows:
        return (0, 0)

    logger.info(
        "recover_untracked_with_store_doc: found %d untracked files with store doc IDs",
        len(rows),
    )

    # Build store-doc lookup once: doc_name_suffix -> (doc_state, full_name).
    store_doc_by_suffix: dict[str, tuple[object, str]] = {}
    try:
        store_docs = await client.list_store_documents()
        for doc in store_docs:
            full_name = getattr(doc, "name", None)
            doc_state = getattr(doc, "state", None)
            if full_name:
                suffix = full_name.rsplit("/", 1)[-1]
                store_doc_by_suffix[suffix] = (doc_state, full_name)
    except Exception as exc:
        logger.warning(
            "recover_untracked_with_store_doc: could not list store documents: %s; "
            "clearing all store doc IDs so files re-upload cleanly",
            exc,
        )
        now = state._now_iso()
        cleared = 0
        for row in rows:
            await db.execute(
                "UPDATE files SET gemini_store_doc_id = NULL, updated_at = ? WHERE file_path = ?",
                (now, row["file_path"]),
            )
            cleared += 1
        await db.commit()
        return (0, cleared)

    restored = 0
    cleared = 0
    now = state._now_iso()

    for row in rows:
        file_path = row["file_path"]
        doc_suffix = row["gemini_store_doc_id"]
        store_entry = store_doc_by_suffix.get(doc_suffix)

        if store_entry is not None:
            doc_state, full_doc_name = store_entry

            if doc_state == DocumentState.STATE_ACTIVE:
                # Affirmative evidence: store doc searchable.  Restore to indexed.
                cursor = await db.execute(
                    """UPDATE files
                       SET gemini_state          = 'indexed',
                           remote_expiration_ts  = NULL,
                           version               = version + 1,
                           gemini_state_updated_at = ?
                       WHERE file_path = ?
                         AND gemini_state = 'untracked'""",
                    (now, file_path),
                )
                await db.commit()
                if cursor.rowcount == 1:
                    restored += 1
                    logger.debug(
                        "recover_untracked_with_store_doc: restored %s -> indexed (doc=%s)",
                        file_path, doc_suffix,
                    )

            elif doc_state == DocumentState.STATE_PENDING:
                # Import still completing -- leave as untracked; re-checked next startup.
                logger.debug(
                    "recover_untracked_with_store_doc: %s doc STATE_PENDING, leaving",
                    file_path,
                )

            else:
                # STATE_FAILED or STATE_UNSPECIFIED: delete and clear for re-upload.
                try:
                    await client.delete_store_document(full_doc_name)
                    logger.debug(
                        "recover_untracked_with_store_doc: deleted STATE_FAILED doc %s for %s",
                        doc_suffix, file_path,
                    )
                except Exception as exc:
                    logger.warning(
                        "recover_untracked_with_store_doc: could not delete doc %s: %s",
                        doc_suffix, exc,
                    )
                cursor = await db.execute(
                    "UPDATE files SET gemini_store_doc_id = NULL, updated_at = ? WHERE file_path = ?",
                    (now, file_path),
                )
                await db.commit()
                if cursor.rowcount == 1:
                    cleared += 1

        else:
            # Not in store: clear store doc ID so file re-uploads cleanly.
            cursor = await db.execute(
                "UPDATE files SET gemini_store_doc_id = NULL, updated_at = ? WHERE file_path = ?",
                (now, file_path),
            )
            await db.commit()
            if cursor.rowcount == 1:
                cleared += 1
                logger.debug(
                    "recover_untracked_with_store_doc: %s doc %s not found, cleared",
                    file_path, doc_suffix,
                )

    logger.info(
        "recover_untracked_with_store_doc: restored %d to indexed, cleared %d store doc IDs",
        restored, cleared,
    )
    return (restored, cleared)


# ---------------------------------------------------------------------------
# Store-sync downgrade helper (Phase 15)
# ---------------------------------------------------------------------------


async def downgrade_to_failed(
    db_path: str,
    file_path: str,
    reason: str = "store-sync detected missing from store",
) -> bool:
    """Downgrade an INDEXED file to FAILED when store-sync detects inconsistency.

    This is the **7th authorized gemini_state write site** (see
    ``governance/store-sync-contract.md`` Section 5).

    Callers: store-sync reconciliation only.  Not part of the normal upload
    pipeline -- this is an emergency correction when empirical searchability
    disagrees with FSM state.

    Uses an OCC guard (``AND gemini_state = 'indexed'``) to prevent
    overwriting a state that has already been changed by another process.

    Args:
        db_path: Path to the SQLite database.
        file_path: Primary key (``files.file_path``) of the file to downgrade.
        reason: Human-readable reason for the downgrade.

    Returns:
        True if the file was downgraded (was INDEXED), False if the file
        was not in INDEXED state (no change made).
    """
    import aiosqlite

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """UPDATE files
               SET gemini_state = 'failed',
                   gemini_store_doc_id = NULL,
                   error_message = ?,
                   gemini_state_updated_at = datetime('now')
               WHERE file_path = ? AND gemini_state = 'indexed'""",
            (reason, file_path),
        )
        await db.commit()
        downgraded = cursor.rowcount > 0

    if downgraded:
        logger.warning(
            "Downgraded file %s to FAILED: %s", file_path, reason
        )
    else:
        logger.info(
            "File %s not in INDEXED state -- no downgrade needed", file_path
        )

    return downgraded
