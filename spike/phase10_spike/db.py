"""Extended spike DB schema with write-ahead intent columns for Phase 10.

Extends Phase 9's 6-column schema with 5 new columns:
  - gemini_file_id: raw file resource name (e.g., "files/abc123")
  - gemini_store_doc_id: store document resource name
  - intent_type: NULL or 'reset_intent' (write-ahead intent marker)
  - intent_started_at: ISO timestamp when intent was written
  - intent_api_calls_completed: 0, 1, or 2 (progress tracker)

Each write function opens a fresh aiosqlite connection with WAL mode +
BEGIN IMMEDIATE (same pattern as Phase 9 execute_with_retry).
"""

import asyncio
import sqlite3
from datetime import datetime, timezone

import aiosqlite


async def _configure_connection(db: aiosqlite.Connection) -> None:
    """Apply standard pragmas to a fresh connection."""
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA foreign_keys=ON")


async def init_spike_db(db_path: str) -> None:
    """Create the Phase 10 spike schema (11 columns + indexes).

    Extends Phase 9 schema with gemini ID columns and write-ahead intent columns.
    """
    async with aiosqlite.connect(db_path) as db:
        await _configure_connection(db)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS files (
                file_path TEXT PRIMARY KEY,
                gemini_state TEXT NOT NULL DEFAULT 'untracked',
                gemini_state_updated_at TEXT,
                version INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                failure_info TEXT,
                gemini_file_id TEXT,
                gemini_store_doc_id TEXT,
                intent_type TEXT,
                intent_started_at TEXT,
                intent_api_calls_completed INTEGER
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_gemini_state ON files(gemini_state)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_intent ON files(intent_type)"
        )
        await db.commit()


async def read_file_state(db_path: str, file_id: str) -> tuple[str, int]:
    """Read (gemini_state, version) from DB.

    Returns:
        Tuple of (gemini_state, version).

    Raises:
        ValueError: If file_id not found in DB.
    """
    async with aiosqlite.connect(db_path) as db:
        await _configure_connection(db)
        cursor = await db.execute(
            "SELECT gemini_state, version FROM files WHERE file_path = ?",
            (file_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"File not found in DB: {file_id}")
        return (row[0], row[1])


async def read_file_full(db_path: str, file_id: str) -> dict:
    """Read all columns for a file as a dict.

    Returns:
        Dict with all column values.

    Raises:
        ValueError: If file_id not found in DB.
    """
    async with aiosqlite.connect(db_path) as db:
        await _configure_connection(db)
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM files WHERE file_path = ?",
            (file_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"File not found in DB: {file_id}")
        return dict(row)


async def write_intent(
    db_path: str, file_path: str, expected_version: int
) -> bool:
    """Txn A: Write reset intent with OCC check. Does NOT increment version.

    Sets intent_type='reset_intent', intent_started_at=now, intent_api_calls_completed=0.
    Only succeeds if gemini_state='indexed' AND version matches.

    Returns:
        True if rowcount==1 (success), False if OCC conflict.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    for attempt in range(3):
        try:
            async with aiosqlite.connect(db_path) as db:
                await _configure_connection(db)
                await db.execute("BEGIN IMMEDIATE")
                cursor = await db.execute(
                    """UPDATE files
                       SET intent_type = 'reset_intent',
                           intent_started_at = ?,
                           intent_api_calls_completed = 0
                       WHERE file_path = ?
                         AND gemini_state = 'indexed'
                         AND version = ?""",
                    (now_iso, file_path, expected_version),
                )
                await db.commit()
                return cursor.rowcount == 1
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < 2:
                await asyncio.sleep(0.05 * (2 ** attempt))
            else:
                raise
    raise RuntimeError("write_intent: unreachable")


async def update_progress(
    db_path: str, file_path: str, api_calls_completed: int
) -> None:
    """Update intent_api_calls_completed. No OCC check (simple progress marker).

    Args:
        db_path: Path to spike database.
        file_path: File being reset.
        api_calls_completed: 1 or 2 (number of API calls completed so far).
    """
    for attempt in range(3):
        try:
            async with aiosqlite.connect(db_path) as db:
                await _configure_connection(db)
                await db.execute("BEGIN IMMEDIATE")
                await db.execute(
                    """UPDATE files
                       SET intent_api_calls_completed = ?
                       WHERE file_path = ?""",
                    (api_calls_completed, file_path),
                )
                await db.commit()
                return
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < 2:
                await asyncio.sleep(0.05 * (2 ** attempt))
            else:
                raise
    raise RuntimeError("update_progress: unreachable")


async def finalize_reset(
    db_path: str, file_path: str, expected_version: int
) -> bool:
    """Txn B: Finalize the reset transition. Increments version.

    Clears gemini_file_id, gemini_store_doc_id, and all intent columns.
    Sets gemini_state='untracked'. Only succeeds if version matches AND
    intent_type='reset_intent'.

    Returns:
        True if rowcount==1 (success), False if OCC conflict.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    for attempt in range(3):
        try:
            async with aiosqlite.connect(db_path) as db:
                await _configure_connection(db)
                await db.execute("BEGIN IMMEDIATE")
                cursor = await db.execute(
                    """UPDATE files
                       SET gemini_state = 'untracked',
                           gemini_state_updated_at = ?,
                           version = version + 1,
                           gemini_file_id = NULL,
                           gemini_store_doc_id = NULL,
                           intent_type = NULL,
                           intent_started_at = NULL,
                           intent_api_calls_completed = NULL
                       WHERE file_path = ?
                         AND version = ?
                         AND intent_type = 'reset_intent'""",
                    (now_iso, file_path, expected_version),
                )
                await db.commit()
                return cursor.rowcount == 1
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < 2:
                await asyncio.sleep(0.05 * (2 ** attempt))
            else:
                raise
    raise RuntimeError("finalize_reset: unreachable")
