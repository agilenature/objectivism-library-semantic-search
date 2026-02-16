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
                        # uploaded (import may have completed but status
                        # was not updated due to crash)
                        logger.info(
                            "File %s has valid remote copy, marking uploaded",
                            file_path,
                        )
                        now = self._state._now_iso()
                        await db.execute(
                            "UPDATE files SET status = 'uploaded', updated_at = ? "
                            "WHERE file_path = ?",
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

                done = getattr(completed, "done", False)
                error = getattr(completed, "error", None)

                if done and not error:
                    await self._state.record_import_success(
                        file_path, op_name
                    )
                    result.recovered_operations += 1
                    logger.info(
                        "Operation %s completed successfully", op_name
                    )
                elif done and error:
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
                      remote_expiration_ts, status
               FROM files
               WHERE remote_expiration_ts IS NOT NULL
                 AND status IN ('uploading', 'uploaded')"""
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
                    # Expired: reset everything
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
        """Reset a file's status to ``pending``, optionally clearing Gemini IDs."""
        db = self._state._ensure_connected()
        now = self._state._now_iso()

        if clear_remote:
            await db.execute(
                """UPDATE files
                   SET status = 'pending',
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
                "UPDATE files SET status = 'pending', updated_at = ? "
                "WHERE file_path = ?",
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
