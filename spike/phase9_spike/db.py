"""Per-transition aiosqlite connection factory with OCC, BEGIN IMMEDIATE, and retry.

Each DB operation opens a fresh connection (locked decision #9: per-transition
connection via factory, no sharing). WAL mode and BEGIN IMMEDIATE are set on
every connection (locked decisions #5, #7).
"""

import asyncio
import sqlite3

import aiosqlite


async def _configure_connection(db: aiosqlite.Connection) -> None:
    """Apply standard pragmas to a fresh connection."""
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA foreign_keys=ON")


async def execute_with_retry(
    db_path: str,
    sql: str,
    params: tuple = (),
    max_retries: int = 3,
    initial_delay: float = 0.05,
    multiplier: float = 2.0,
) -> int:
    """Execute a write with BEGIN IMMEDIATE and exponential backoff.

    Opens a fresh aiosqlite connection per call. Uses BEGIN IMMEDIATE to
    acquire a write lock immediately (avoids deferred lock upgrade failures).
    Retries on sqlite3.OperationalError("database is locked").

    Returns:
        rowcount from the executed statement.

    Raises:
        sqlite3.OperationalError: After max_retries exhausted.
    """
    for attempt in range(max_retries):
        try:
            async with aiosqlite.connect(db_path) as db:
                await _configure_connection(db)
                await db.execute("BEGIN IMMEDIATE")
                cursor = await db.execute(sql, params)
                await db.commit()
                return cursor.rowcount
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                delay = initial_delay * (multiplier ** attempt)
                await asyncio.sleep(delay)
            else:
                raise
    # Unreachable -- the loop either returns or raises
    raise RuntimeError("execute_with_retry: unreachable")


async def init_spike_db(db_path: str) -> None:
    """Create the spike schema (files table + index). Sets WAL mode.

    This creates a minimal schema for Phase 9 spike testing.
    NOT the production schema -- spike DB is isolated at /tmp/phase9_spike.db.
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
                failure_info TEXT
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_gemini_state ON files(gemini_state)"
        )
        await db.commit()


async def read_file_state(db_path: str, file_id: str) -> tuple[str, int]:
    """Read (gemini_state, version) from DB.

    DB is the sole source of truth (locked decision #5).

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
