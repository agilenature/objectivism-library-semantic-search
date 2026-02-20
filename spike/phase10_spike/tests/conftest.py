"""Shared fixtures for Phase 10 spike tests."""

import asyncio
import os
from collections.abc import Callable

import aiosqlite
import pytest

from spike.phase10_spike.db import init_spike_db


@pytest.fixture
async def spike_db(tmp_path) -> str:
    """Create a temporary Phase 10 spike database, yield its path, clean up."""
    db_path = str(tmp_path / "phase10_spike.db")
    await init_spike_db(db_path)
    yield db_path
    # Clean up WAL/SHM files
    for suffix in ("", "-wal", "-shm"):
        path = db_path + suffix
        if os.path.exists(path):
            os.remove(path)


@pytest.fixture
def seed_indexed_file(spike_db: str) -> Callable:
    """Factory fixture: insert a file with gemini_state='indexed', version=5, with Gemini IDs."""

    async def _seed(
        file_path: str = "test/indexed_file.txt",
        version: int = 5,
        gemini_file_id: str = "files/test123",
        gemini_store_doc_id: str = "fileSearchStores/store1/documents/doc1",
    ) -> str:
        async with aiosqlite.connect(spike_db) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                """INSERT INTO files
                   (file_path, gemini_state, version, gemini_file_id, gemini_store_doc_id)
                   VALUES (?, 'indexed', ?, ?, ?)""",
                (file_path, version, gemini_file_id, gemini_store_doc_id),
            )
            await db.commit()
        return file_path

    return _seed


@pytest.fixture
def seed_failed_file(spike_db: str) -> Callable:
    """Factory fixture: insert a file with gemini_state='failed', version=3."""

    async def _seed(
        file_path: str = "test/failed_file.txt",
        version: int = 3,
    ) -> str:
        async with aiosqlite.connect(spike_db) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                """INSERT INTO files
                   (file_path, gemini_state, version)
                   VALUES (?, 'failed', ?)""",
                (file_path, version),
            )
            await db.commit()
        return file_path

    return _seed
