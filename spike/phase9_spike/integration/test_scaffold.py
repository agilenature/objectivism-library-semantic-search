"""Tests for FileTransitionManager integration scaffold.

Proves the bridge pattern works end-to-end:
  FileTransitionManager -> StateMachineAdapter -> DB

Uses the same spike_db and seed_file fixtures from the Phase 9 test suite.
"""

import asyncio

import pytest

from spike.phase9_spike.db import read_file_state
from spike.phase9_spike.event_log import EventCollector
from spike.phase9_spike.exceptions import (
    GuardRejectedError,
    StaleTransitionError,
)
from spike.phase9_spike.integration.scaffold import FileTransitionManager


# ---------------------------------------------------------------------------
# Fixtures (reuse conftest from parent tests/)
# ---------------------------------------------------------------------------

@pytest.fixture
async def spike_db(tmp_path):
    """Create a temporary spike DB with the Phase 9 schema."""
    from spike.phase9_spike.db import init_spike_db

    db_path = str(tmp_path / "scaffold_test.db")
    await init_spike_db(db_path)
    return db_path


@pytest.fixture
def seed_file(spike_db):
    """Factory to insert a file row with given state and version."""
    import aiosqlite

    async def _seed(
        file_path: str,
        state: str = "untracked",
        version: int = 0,
    ) -> None:
        async with aiosqlite.connect(spike_db) as db:
            await db.execute(
                "INSERT INTO files (file_path, gemini_state, version) "
                "VALUES (?, ?, ?)",
                (file_path, state, version),
            )
            await db.commit()

    return _seed


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigger_transition_success(spike_db, seed_file):
    """Seed file as 'untracked'. Trigger start_upload. Assert 'uploading'."""
    await seed_file("/test/scaffold_a.txt")

    manager = FileTransitionManager(spike_db)
    new_state = await manager.trigger_transition(
        "/test/scaffold_a.txt", "start_upload"
    )

    assert new_state == "uploading"

    # Verify DB directly
    db_state, db_version = await read_file_state(spike_db, "/test/scaffold_a.txt")
    assert db_state == "uploading"
    assert db_version == 1


@pytest.mark.asyncio
async def test_trigger_transition_concurrent_same_file(spike_db, seed_file):
    """Seed 1 file. Run 5 concurrent start_upload. Exactly 1 succeeds."""
    await seed_file("/test/scaffold_contended.txt")

    manager = FileTransitionManager(spike_db)
    collector = EventCollector()

    results: list[str] = []
    errors: list[Exception] = []

    async def attempt():
        try:
            state = await manager.trigger_transition(
                "/test/scaffold_contended.txt",
                "start_upload",
                event_collector=collector,
            )
            results.append(state)
        except (StaleTransitionError, GuardRejectedError) as e:
            errors.append(e)

    await asyncio.gather(*[attempt() for _ in range(5)])

    # Exactly 1 success (per-file lock serializes, but after first transition
    # the state is 'uploading' so subsequent attempts get TransitionNotAllowed
    # which is wrapped as GuardRejectedError by the adapter)
    assert len(results) == 1
    assert results[0] == "uploading"
    assert len(errors) == 4

    # Verify DB shows final state
    db_state, _ = await read_file_state(spike_db, "/test/scaffold_contended.txt")
    assert db_state == "uploading"


@pytest.mark.asyncio
async def test_trigger_transition_concurrent_different_files(spike_db, seed_file):
    """Seed 5 files. Run 5 concurrent start_upload on different files. All succeed."""
    for i in range(5):
        await seed_file(f"/test/scaffold_diff_{i}.txt")

    manager = FileTransitionManager(spike_db)
    results: list[str] = []

    async def attempt(file_path: str):
        state = await manager.trigger_transition(file_path, "start_upload")
        results.append(state)

    await asyncio.gather(
        *[attempt(f"/test/scaffold_diff_{i}.txt") for i in range(5)]
    )

    assert len(results) == 5
    assert all(s == "uploading" for s in results)

    # Verify each file in DB
    for i in range(5):
        db_state, _ = await read_file_state(spike_db, f"/test/scaffold_diff_{i}.txt")
        assert db_state == "uploading"


@pytest.mark.asyncio
async def test_get_file_state(spike_db, seed_file):
    """Seed file. Check state before and after transition."""
    await seed_file("/test/scaffold_state.txt")

    manager = FileTransitionManager(spike_db)

    # Before transition
    state = await manager.get_file_state("/test/scaffold_state.txt")
    assert state == "untracked"

    # Trigger transition
    await manager.trigger_transition("/test/scaffold_state.txt", "start_upload")

    # After transition
    state = await manager.get_file_state("/test/scaffold_state.txt")
    assert state == "uploading"
