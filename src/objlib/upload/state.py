"""Async SQLite state manager for upload pipeline operations.

Wraps aiosqlite to provide async CRUD operations for the upload workflow.
Implements write-ahead intent logging per locked decision #6
(SQLite-as-Source-of-Truth): state is written BEFORE every API call and
updated AFTER every API response.

Each write method commits immediately -- no transactions are held across
``await`` boundaries (per Pitfall 5: aiosqlite connection sharing).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiosqlite

from objlib.upload.exceptions import OCCConflictError

logger = logging.getLogger(__name__)


class AsyncUploadStateManager:
    """Async SQLite state manager for upload intent/result tracking.

    Usage::

        async with AsyncUploadStateManager("data/library.db") as state:
            pending = await state.get_pending_files(limit=200)
            await state.record_upload_intent(pending[0]["file_path"])
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open an aiosqlite connection with WAL mode and foreign keys."""
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA foreign_keys=ON")

    async def close(self) -> None:
        """Close the connection if open."""
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> AsyncUploadStateManager:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Not connected -- use 'async with' or call connect()")
        return self._db

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")

    # ------------------------------------------------------------------
    # Read queries
    # ------------------------------------------------------------------

    async def get_pending_files(self, limit: int = 200) -> list[dict]:
        """Return files with ``status = 'pending'``, ordered by path.

        Filters to .txt files only -- other file types are skipped.

        Args:
            limit: Maximum rows to return.

        Returns:
            List of dicts with file_path, content_hash, filename,
            file_size, metadata_json keys (only .txt files).
        """
        db = self._ensure_connected()
        cursor = await db.execute(
            """SELECT file_path, content_hash, filename, file_size, metadata_json
               FROM files
               WHERE gemini_state = 'untracked' AND filename LIKE '%.txt'
               ORDER BY file_path
               LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_uploading_files(self) -> list[dict]:
        """Return files with ``gemini_state = 'uploading'`` (crash recovery candidates)."""
        db = self._ensure_connected()
        cursor = await db.execute(
            """SELECT file_path, content_hash, filename, file_size, metadata_json
               FROM files
               WHERE gemini_state = 'uploading'
               ORDER BY file_path"""
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_pending_operations(self) -> list[dict]:
        """Return operations in ``pending`` or ``in_progress`` state."""
        db = self._ensure_connected()
        cursor = await db.execute(
            """SELECT operation_name, file_path, gemini_file_name,
                      operation_state, created_at, last_polled_at
               FROM upload_operations
               WHERE operation_state IN ('pending', 'in_progress')
               ORDER BY created_at"""
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Write operations (each commits immediately)
    # ------------------------------------------------------------------

    async def record_upload_intent(self, file_path: str) -> None:
        """Write upload intent BEFORE the API call (legacy path).

        If the process crashes between this call and the API response,
        recovery will find this file and retry.
        """
        db = self._ensure_connected()
        now = self._now_iso()
        await db.execute(
            "UPDATE files SET gemini_state = 'uploading', updated_at = ? WHERE file_path = ?",
            (now, file_path),
        )
        await db.commit()
        logger.debug("Recorded upload intent for %s", file_path)

    async def record_upload_success(
        self,
        file_path: str,
        gemini_file_uri: str,
        gemini_file_id: str,
        operation_name: str,
    ) -> None:
        """Record successful upload and create operation tracking row.

        Updates the files table with Gemini identifiers and inserts a
        pending operation into ``upload_operations``.
        """
        db = self._ensure_connected()
        now = self._now_iso()
        expiration = (
            datetime.now(timezone.utc) + timedelta(hours=48)
        ).strftime("%Y-%m-%dT%H:%M:%S.%f")

        await db.execute(
            """UPDATE files
               SET gemini_file_uri = ?,
                   gemini_file_id = ?,
                   upload_timestamp = ?,
                   remote_expiration_ts = ?,
                   updated_at = ?
               WHERE file_path = ?""",
            (gemini_file_uri, gemini_file_id, now, expiration, now, file_path),
        )
        await db.execute(
            """INSERT OR REPLACE INTO upload_operations
                   (operation_name, file_path, gemini_file_name, operation_state, created_at)
               VALUES (?, ?, ?, 'pending', ?)""",
            (operation_name, file_path, gemini_file_id, now),
        )
        await db.commit()
        logger.debug("Recorded upload success for %s (op=%s)", file_path, operation_name)

    async def record_import_success(self, file_path: str, operation_name: str) -> None:
        """Mark an import operation as succeeded (legacy path)."""
        db = self._ensure_connected()
        now = self._now_iso()
        await db.execute(
            """UPDATE upload_operations
               SET operation_state = 'succeeded', completed_at = ?
               WHERE operation_name = ?""",
            (now, operation_name),
        )
        await db.execute(
            "UPDATE files SET updated_at = ? WHERE file_path = ?",
            (now, file_path),
        )
        await db.commit()
        logger.debug("Recorded import success for %s", file_path)

    async def record_upload_failure(
        self,
        file_path: str,
        error_message: str,
        retry_count: int = 0,
    ) -> None:
        """Mark a file upload as failed."""
        db = self._ensure_connected()
        now = self._now_iso()
        await db.execute(
            """UPDATE files
               SET gemini_state = 'failed', error_message = ?, updated_at = ?
               WHERE file_path = ?""",
            (error_message, now, file_path),
        )
        # Update operation row if one exists for this file
        await db.execute(
            """UPDATE upload_operations
               SET operation_state = 'failed', error_message = ?,
                   completed_at = ?, retry_count = ?
               WHERE file_path = ? AND operation_state IN ('pending', 'in_progress')""",
            (error_message, now, retry_count, file_path),
        )
        await db.commit()
        logger.debug("Recorded upload failure for %s: %s", file_path, error_message)

    async def update_operation_state(
        self,
        operation_name: str,
        state: str,
        error_message: str | None = None,
    ) -> None:
        """Update the state of a tracked operation."""
        db = self._ensure_connected()
        now = self._now_iso()

        if state in ("succeeded", "failed"):
            if error_message:
                await db.execute(
                    """UPDATE upload_operations
                       SET operation_state = ?, last_polled_at = ?,
                           completed_at = ?, error_message = ?
                       WHERE operation_name = ?""",
                    (state, now, now, error_message, operation_name),
                )
            else:
                await db.execute(
                    """UPDATE upload_operations
                       SET operation_state = ?, last_polled_at = ?, completed_at = ?
                       WHERE operation_name = ?""",
                    (state, now, now, operation_name),
                )
        else:
            await db.execute(
                """UPDATE upload_operations
                   SET operation_state = ?, last_polled_at = ?
                   WHERE operation_name = ?""",
                (state, now, operation_name),
            )
        await db.commit()

    # ------------------------------------------------------------------
    # Batch tracking
    # ------------------------------------------------------------------

    async def create_batch(self, batch_number: int, file_count: int) -> int:
        """Insert a new batch record and return its batch_id."""
        db = self._ensure_connected()
        now = self._now_iso()
        cursor = await db.execute(
            """INSERT INTO upload_batches (batch_number, file_count, status, started_at)
               VALUES (?, ?, 'in_progress', ?)""",
            (batch_number, file_count, now),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def update_batch(
        self,
        batch_id: int,
        succeeded: int,
        failed: int,
        status: str,
    ) -> None:
        """Update batch counters and status."""
        db = self._ensure_connected()
        now = self._now_iso()
        if status in ("completed", "failed"):
            await db.execute(
                """UPDATE upload_batches
                   SET succeeded_count = ?, failed_count = ?,
                       status = ?, completed_at = ?
                   WHERE batch_id = ?""",
                (succeeded, failed, status, now, batch_id),
            )
        else:
            await db.execute(
                """UPDATE upload_batches
                   SET succeeded_count = ?, failed_count = ?, status = ?
                   WHERE batch_id = ?""",
                (succeeded, failed, status, batch_id),
            )
        await db.commit()

    # ------------------------------------------------------------------
    # Single-writer lock (locked decision #10)
    # ------------------------------------------------------------------

    async def acquire_lock(self, instance_id: str) -> bool:
        """Acquire the single-writer upload lock.

        Uses INSERT OR REPLACE into the ``upload_locks`` table (which
        has a CHECK constraint enforcing at most one row).

        Returns:
            True if the lock was acquired.
        """
        db = self._ensure_connected()
        now = self._now_iso()
        try:
            await db.execute(
                """INSERT OR REPLACE INTO upload_locks (lock_id, instance_id, acquired_at, last_heartbeat)
                   VALUES (1, ?, ?, ?)""",
                (instance_id, now, now),
            )
            await db.commit()
            logger.info("Acquired upload lock (instance=%s)", instance_id)
            return True
        except Exception:
            logger.exception("Failed to acquire upload lock")
            return False

    async def release_lock(self) -> None:
        """Release the single-writer lock."""
        db = self._ensure_connected()
        await db.execute("DELETE FROM upload_locks")
        await db.commit()
        logger.info("Released upload lock")

    async def update_heartbeat(self, instance_id: str) -> None:
        """Update the lock heartbeat timestamp."""
        db = self._ensure_connected()
        now = self._now_iso()
        await db.execute(
            "UPDATE upload_locks SET last_heartbeat = ? WHERE instance_id = ?",
            (now, instance_id),
        )
        await db.commit()

    # ------------------------------------------------------------------
    # Enriched upload queries (Phase 6.2)
    # ------------------------------------------------------------------

    async def get_enriched_pending_files(
        self, limit: int = 200, include_needs_review: bool = True
    ) -> list[dict]:
        """Return files ready for enriched upload.

        Requires ALL of:
        - ``.txt`` file extension
        - AI metadata extracted (``file_metadata_ai.is_current=1``)
        - Entity extraction complete (``entity_extraction_status='entities_done'``)
        - Upload status ``pending``
        - AI metadata status in ``('extracted', 'approved')`` or also
          ``'needs_review'`` if *include_needs_review* is True

        For each file, also fetches canonical entity names from
        ``transcript_entity JOIN person``.

        Args:
            limit: Maximum rows to return.
            include_needs_review: Whether to include files with
                ``ai_metadata_status='needs_review'``.

        Returns:
            List of dicts with file_path, content_hash, filename,
            file_size, phase1_metadata_json, ai_metadata_json,
            last_upload_hash, and entity_names (list[str]).
        """
        db = self._ensure_connected()

        if include_needs_review:
            status_clause = "AND f.ai_metadata_status IN ('extracted', 'approved', 'needs_review')"
        else:
            status_clause = "AND f.ai_metadata_status IN ('extracted', 'approved')"

        cursor = await db.execute(
            f"""SELECT f.file_path, f.content_hash, f.filename, f.file_size,
                       f.metadata_json AS phase1_metadata_json,
                       m.metadata_json AS ai_metadata_json,
                       f.last_upload_hash
                FROM files f
                JOIN file_metadata_ai m
                    ON f.file_path = m.file_path AND m.is_current = 1
                WHERE f.filename LIKE '%.txt'
                  AND f.entity_extraction_status = 'entities_done'
                  AND f.gemini_state = 'untracked'
                  {status_clause}
                ORDER BY f.file_path
                LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()

        results = []
        for row in rows:
            file_dict = dict(row)
            entity_cursor = await db.execute(
                """SELECT p.canonical_name
                   FROM transcript_entity te
                   JOIN person p ON te.person_id = p.person_id
                   WHERE te.transcript_id = ?
                   ORDER BY te.mention_count DESC""",
                (row["file_path"],),
            )
            entity_rows = await entity_cursor.fetchall()
            file_dict["entity_names"] = [r["canonical_name"] for r in entity_rows]
            results.append(file_dict)

        return results

    async def get_files_to_reset_for_enriched_upload(self) -> list[dict]:
        """Return already-uploaded or failed files that have enriched metadata.

        These files were uploaded with Phase 1 metadata only (or failed
        during a previous attempt) and need to be deleted from Gemini
        and re-uploaded with enriched metadata for consistency.

        IMPORTANT: Only returns files where the enriched metadata has changed
        since last upload (or was never uploaded with enriched metadata).
        Files with matching upload hashes are excluded to prevent unnecessary
        re-uploads.

        Returns:
            List of dicts with file_path, filename, status,
            gemini_file_id, ai_metadata_json, and entity_names.
        """
        from objlib.upload.metadata_builder import compute_upload_hash
        import json

        db = self._ensure_connected()
        cursor = await db.execute(
            """SELECT f.file_path, f.filename, f.gemini_state,
                      f.gemini_file_id, f.last_upload_hash,
                      f.content_hash, f.metadata_json AS phase1_metadata_json,
                      m.metadata_json AS ai_metadata_json
               FROM files f
               JOIN file_metadata_ai m
                   ON f.file_path = m.file_path AND m.is_current = 1
               WHERE f.gemini_state IN ('indexed', 'failed')
                 AND f.filename LIKE '%.txt'
                 AND f.entity_extraction_status = 'entities_done'
                 AND f.ai_metadata_status IN ('extracted', 'approved', 'needs_review')
               ORDER BY f.file_path"""
        )
        rows = await cursor.fetchall()

        results = []
        for row in rows:
            # Get entity names
            entity_cursor = await db.execute(
                """SELECT p.canonical_name
                   FROM transcript_entity te
                   JOIN person p ON te.person_id = p.person_id
                   WHERE te.transcript_id = ?
                   ORDER BY te.mention_count DESC""",
                (row["file_path"],),
            )
            entity_rows = await entity_cursor.fetchall()
            entity_names = [r["canonical_name"] for r in entity_rows]

            # Compute current upload hash
            phase1_metadata = json.loads(row["phase1_metadata_json"] or "{}")
            ai_metadata = json.loads(row["ai_metadata_json"] or "{}")
            current_hash = compute_upload_hash(
                phase1_metadata, ai_metadata, entity_names, row["content_hash"]
            )

            # Always retry failed files (polling timeout, API errors, etc.)
            # For uploaded files, only reset if hash changed
            should_reset = (
                row["gemini_state"] == "failed"  # Always retry failures
                or row["last_upload_hash"] is None  # Never uploaded with enriched metadata
                or row["last_upload_hash"] != current_hash  # Metadata changed
            )

            if should_reset:
                file_dict = dict(row)
                file_dict["entity_names"] = entity_names
                results.append(file_dict)

        return results

    # ------------------------------------------------------------------
    # FSM-mediated transition methods (Phase 12)
    # ------------------------------------------------------------------
    #
    # Each method:
    # - Dual-writes gemini_state + status (backward compat per Q1 decision)
    # - Uses OCC guard: WHERE version = ? (raises OCCConflictError on mismatch)
    # - Commits immediately (no held transactions across await boundaries)
    # - Returns the new version (expected_version + 1)

    async def transition_to_uploading(
        self, file_path: str, expected_version: int
    ) -> int:
        """Transition a file from untracked to uploading.

        Args:
            file_path: Primary key of the file.
            expected_version: OCC version guard.

        Returns:
            New version number (expected_version + 1).

        Raises:
            OCCConflictError: If the version has changed since read.
        """
        db = self._ensure_connected()
        now = self._now_iso()
        new_version = expected_version + 1
        cursor = await db.execute(
            """UPDATE files
               SET gemini_state = 'uploading',
                   gemini_state_updated_at = ?,
                   version = ?
               WHERE file_path = ?
                 AND gemini_state = 'untracked'
                 AND version = ?""",
            (now, new_version, file_path, expected_version),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise OCCConflictError(
                f"Version conflict on {file_path}: expected version {expected_version}"
            )
        logger.debug(
            "Transitioned %s to uploading (v%d->v%d)", file_path, expected_version, new_version
        )
        return new_version

    async def transition_to_processing(
        self,
        file_path: str,
        expected_version: int,
        gemini_file_id: str,
        gemini_file_uri: str,
    ) -> int:
        """Transition a file from uploading to processing.

        Records the Gemini file identifiers returned by the upload API.

        Args:
            file_path: Primary key of the file.
            expected_version: OCC version guard.
            gemini_file_id: Gemini file resource name (e.g. 'files/abc123').
            gemini_file_uri: Gemini file URI.

        Returns:
            New version number (expected_version + 1).

        Raises:
            OCCConflictError: If the version has changed since read.
        """
        db = self._ensure_connected()
        now = self._now_iso()
        new_version = expected_version + 1
        cursor = await db.execute(
            """UPDATE files
               SET gemini_state = 'processing',
                   gemini_file_id = ?,
                   gemini_file_uri = ?,
                   upload_timestamp = ?,
                   gemini_state_updated_at = ?,
                   version = ?
               WHERE file_path = ?
                 AND gemini_state = 'uploading'
                 AND version = ?""",
            (gemini_file_id, gemini_file_uri, now, now, new_version, file_path, expected_version),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise OCCConflictError(
                f"Version conflict on {file_path}: expected version {expected_version}"
            )
        logger.debug(
            "Transitioned %s to processing (v%d->v%d)", file_path, expected_version, new_version
        )
        return new_version

    async def transition_to_indexed(
        self,
        file_path: str,
        expected_version: int,
        gemini_store_doc_id: str,
    ) -> int:
        """Transition a file from processing to indexed.

        Records the store document ID after successful import.

        Args:
            file_path: Primary key of the file.
            expected_version: OCC version guard.
            gemini_store_doc_id: Gemini store document resource name.

        Returns:
            New version number (expected_version + 1).

        Raises:
            OCCConflictError: If the version has changed since read.
        """
        db = self._ensure_connected()
        now = self._now_iso()
        new_version = expected_version + 1
        cursor = await db.execute(
            """UPDATE files
               SET gemini_state = 'indexed',
                   gemini_store_doc_id = ?,
                   gemini_state_updated_at = ?,
                   version = ?
               WHERE file_path = ?
                 AND gemini_state = 'processing'
                 AND version = ?""",
            (gemini_store_doc_id, now, new_version, file_path, expected_version),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise OCCConflictError(
                f"Version conflict on {file_path}: expected version {expected_version}"
            )
        logger.debug(
            "Transitioned %s to indexed (v%d->v%d)", file_path, expected_version, new_version
        )
        return new_version

    async def transition_to_failed(
        self,
        file_path: str,
        expected_version: int,
        error_message: str,
    ) -> int:
        """Transition a file to failed state from any in-flight state.

        No gemini_state guard -- failure can come from uploading or
        processing.

        Args:
            file_path: Primary key of the file.
            expected_version: OCC version guard.
            error_message: Human-readable error description.

        Returns:
            New version number (expected_version + 1).

        Raises:
            OCCConflictError: If the version has changed since read.
        """
        db = self._ensure_connected()
        now = self._now_iso()
        new_version = expected_version + 1
        cursor = await db.execute(
            """UPDATE files
               SET gemini_state = 'failed',
                   error_message = ?,
                   gemini_state_updated_at = ?,
                   version = ?
               WHERE file_path = ?
                 AND version = ?""",
            (error_message, now, new_version, file_path, expected_version),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise OCCConflictError(
                f"Version conflict on {file_path}: expected version {expected_version}"
            )
        logger.debug(
            "Transitioned %s to failed (v%d->v%d)", file_path, expected_version, new_version
        )
        return new_version

    # ------------------------------------------------------------------
    # FSM read helpers (Phase 12)
    # ------------------------------------------------------------------

    async def get_fsm_pending_files(self, limit: int = 50) -> list[dict]:
        """Return files in untracked gemini_state ready for FSM upload.

        This is the FSM-path equivalent of ``get_pending_files()`` (which
        uses the legacy ``status='pending'`` column).

        Args:
            limit: Maximum rows to return.

        Returns:
            List of dicts with file_path, content_hash, filename,
            file_size, metadata_json, version, gemini_state.
        """
        db = self._ensure_connected()
        cursor = await db.execute(
            """SELECT file_path, content_hash, filename, file_size,
                      metadata_json, version, gemini_state
               FROM files
               WHERE gemini_state = 'untracked'
                 AND filename LIKE '%.txt'
               ORDER BY file_path
               LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # FSM reset transition methods (Phase 12)
    # ------------------------------------------------------------------

    async def write_reset_intent(
        self, file_path: str, expected_version: int
    ) -> int:
        """Write a reset intent BEFORE any API deletion calls.

        Per Phase 10 pattern: Txn A writes intent without version
        increment.  The version guard ensures no concurrent modification
        has occurred since the caller's read.

        Args:
            file_path: Primary key of the file.
            expected_version: OCC version guard.

        Returns:
            The same expected_version (no increment on intent write).

        Raises:
            OCCConflictError: If the version has changed since read.
        """
        db = self._ensure_connected()
        now = self._now_iso()
        cursor = await db.execute(
            """UPDATE files
               SET intent_type = 'reset',
                   intent_started_at = ?,
                   intent_api_calls_completed = 0
               WHERE file_path = ?
                 AND version = ?""",
            (now, file_path, expected_version),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise OCCConflictError(
                f"Version conflict writing reset intent on {file_path}: "
                f"expected version {expected_version}"
            )
        logger.debug("Wrote reset intent for %s (v%d)", file_path, expected_version)
        return expected_version

    async def update_intent_progress(
        self, file_path: str, api_calls_completed: int
    ) -> None:
        """Update intent progress counter (no OCC check -- simple marker).

        Args:
            file_path: Primary key of the file.
            api_calls_completed: Number of API steps completed (1 or 2).
        """
        db = self._ensure_connected()
        await db.execute(
            """UPDATE files
               SET intent_api_calls_completed = ?
               WHERE file_path = ?""",
            (api_calls_completed, file_path),
        )
        await db.commit()
        logger.debug(
            "Updated intent progress for %s: %d calls completed",
            file_path, api_calls_completed,
        )

    async def finalize_reset(
        self, file_path: str, expected_version: int
    ) -> bool:
        """Finalize a reset: clear Gemini IDs and intent columns.

        Sets gemini_state='untracked', status='pending', increments
        version.  OCC-guarded.

        Args:
            file_path: Primary key of the file.
            expected_version: OCC version guard.

        Returns:
            True on success, False on OCC conflict.
        """
        db = self._ensure_connected()
        now = self._now_iso()
        new_version = expected_version + 1
        cursor = await db.execute(
            """UPDATE files
               SET gemini_state = 'untracked',
                   gemini_file_id = NULL,
                   gemini_file_uri = NULL,
                   gemini_store_doc_id = NULL,
                   upload_timestamp = NULL,
                   remote_expiration_ts = NULL,
                   error_message = NULL,
                   intent_type = NULL,
                   intent_started_at = NULL,
                   intent_api_calls_completed = NULL,
                   gemini_state_updated_at = ?,
                   version = ?
               WHERE file_path = ?
                 AND version = ?""",
            (now, new_version, file_path, expected_version),
        )
        await db.commit()
        if cursor.rowcount == 0:
            logger.warning(
                "OCC conflict finalizing reset on %s: expected v%d",
                file_path, expected_version,
            )
            return False
        logger.debug(
            "Finalized reset for %s (v%d->v%d)",
            file_path, expected_version, new_version,
        )
        return True

    async def get_file_version(self, file_path: str) -> tuple[str, int]:
        """Return the current (gemini_state, version) for a file.

        Args:
            file_path: Primary key of the file.

        Returns:
            Tuple of (gemini_state, version).

        Raises:
            ValueError: If the file is not found.
        """
        db = self._ensure_connected()
        cursor = await db.execute(
            "SELECT gemini_state, version FROM files WHERE file_path = ?",
            (file_path,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"File not found: {file_path}")
        return (row["gemini_state"], row["version"])
