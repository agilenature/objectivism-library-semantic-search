"""Spike-specific test fixtures for Phase 9."""

import pytest

from spike.phase9_spike.db import init_spike_db
from spike.phase9_spike.event_log import EventCollector


@pytest.fixture
async def spike_db(tmp_path):
    """Create a temporary spike DB with the Phase 9 schema.

    Yields the path as a string. Cleanup is automatic via tmp_path.
    """
    db_path = str(tmp_path / "spike_test.db")
    await init_spike_db(db_path)
    return db_path


@pytest.fixture
def seed_file(spike_db):
    """Factory fixture to insert a file row with given state and version.

    Usage:
        await seed_file("test.txt")  # defaults: untracked, version=0
        await seed_file("test.txt", state="uploading", version=1)
    """
    import aiosqlite

    async def _seed(
        file_path: str,
        state: str = "untracked",
        version: int = 0,
    ) -> None:
        async with aiosqlite.connect(spike_db) as db:
            await db.execute(
                """INSERT INTO files (file_path, gemini_state, version)
                   VALUES (?, ?, ?)""",
                (file_path, state, version),
            )
            await db.commit()

    return _seed


@pytest.fixture
def event_collector():
    """Return a fresh EventCollector instance."""
    return EventCollector()
