"""RecoveryCrawler: Startup recovery for partial-intent files (GA-3).

Scans the DB for files with intent_type IS NOT NULL (indicating a crash
during a multi-step transition) and recovers each one to 'untracked' using
linear step resumption. No retry loops (GA-9).

Also provides retry_failed_file() for the FAILED -> UNTRACKED escape path (GA-4).
"""

import logging
from collections.abc import Callable
from datetime import datetime, timezone

import aiosqlite

from spike.phase10_spike.db import finalize_reset, update_progress
from spike.phase10_spike.safe_delete import (
    safe_delete_file,
    safe_delete_store_document,
)

logger = logging.getLogger(__name__)


class RecoveryCrawler:
    """Recovers files left in partial-intent state after a crash.

    Linear step resumption based on intent_api_calls_completed (GA-9).
    No retry loops. Non-404 errors propagate.
    """

    def __init__(self, db_path: str, delete_store_doc_fn: Callable, delete_file_fn: Callable) -> None:
        self._db_path = db_path
        self._delete_store_doc_fn = delete_store_doc_fn
        self._delete_file_fn = delete_file_fn

    async def recover_all(self) -> list[str]:
        """Scan for pending intents and recover each file to 'untracked'."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT file_path, intent_type, intent_api_calls_completed,
                          gemini_store_doc_id, gemini_file_id, version
                   FROM files WHERE intent_type IS NOT NULL
                   ORDER BY intent_started_at ASC"""
            )
            rows = [dict(r) for r in await cursor.fetchall()]
        recovered = []
        for row in rows:
            await self._recover_file(row)
            recovered.append(row["file_path"])
        return recovered

    async def _recover_file(self, row: dict) -> None:
        """Linear step resumption: resume from where the crash interrupted."""
        file_path = row["file_path"]
        completed = row["intent_api_calls_completed"] or 0
        if completed < 1:
            await safe_delete_store_document(self._delete_store_doc_fn, row["gemini_store_doc_id"])
            await update_progress(self._db_path, file_path, 1)
        if completed < 2:
            await safe_delete_file(self._delete_file_fn, row["gemini_file_id"])
            await update_progress(self._db_path, file_path, 2)
        await finalize_reset(self._db_path, file_path, row["version"])
        logger.info("Recovered %s: intent=%s, resumed_from_step=%d", file_path, row["intent_type"], completed)


async def retry_failed_file(db_path: str, file_path: str) -> bool:
    """Transition a FAILED file back to UNTRACKED (GA-4).

    This is the escape path for files stuck in 'failed' state. Uses a single
    atomic UPDATE with WAL + BEGIN IMMEDIATE. Clears all Gemini IDs and intent
    columns, increments version.

    Args:
        db_path: Path to the spike database.
        file_path: Path of the file to retry.

    Returns:
        True if the file was transitioned (rowcount==1), False if file was not
        in 'failed' state or did not exist.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            """UPDATE files
               SET gemini_state = 'untracked',
                   gemini_file_id = NULL,
                   gemini_store_doc_id = NULL,
                   intent_type = NULL,
                   intent_started_at = NULL,
                   intent_api_calls_completed = NULL,
                   version = version + 1,
                   gemini_state_updated_at = ?
               WHERE file_path = ?
                 AND gemini_state = 'failed'""",
            (now_iso, file_path),
        )
        await db.commit()
        return cursor.rowcount == 1
