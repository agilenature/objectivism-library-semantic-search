"""Adversarial concurrent transition tests.

Tests the 10-concurrent same-file scenario (locked decision #2) and
the 10-concurrent different-file scenario.

Uses per-file asyncio.Lock (locked decision #3) + OCC version column.
"""

import asyncio
from collections import defaultdict

import aiosqlite
import pytest

from spike.phase9_spike.adapters.statemachine_adapter import StateMachineAdapter
from spike.phase9_spike.db import read_file_state
from spike.phase9_spike.event_log import EventCollector
from spike.phase9_spike.exceptions import (
    GuardRejectedError,
    StaleTransitionError,
    TransitionNotAllowedError,
)


class FileLockManager:
    """Per-file asyncio.Lock manager (locked decision #3)."""

    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def get_lock(self, file_id: str) -> asyncio.Lock:
        return self._locks[file_id]


class TestConcurrentSameFile:
    """10 concurrent attempts to transition the SAME file."""

    async def test_exactly_1_success_9_rejections(self, spike_db, seed_file):
        """Adversarial same-file test: exactly 1 success, 9 rejections."""
        file_id = "/test/concurrent_same_file.txt"
        await seed_file(file_id, state="untracked", version=0)

        lock_manager = FileLockManager()
        collector = EventCollector()

        async def attempt(attempt_num: int):
            lock = lock_manager.get_lock(file_id)
            async with lock:
                # Read current state from DB (DB is source of truth)
                state, version = await read_file_state(spike_db, file_id)

                if state != "untracked":
                    # Already transitioned by another attempt
                    collector.emit(
                        file_id=file_id,
                        from_state=state,
                        to_state="uploading",
                        event="start_upload",
                        outcome="rejected",
                        guard_result=False,
                        error=f"State already '{state}'",
                    )
                    return

                # Create ephemeral adapter and attempt transition
                adapter = StateMachineAdapter(
                    file_id=file_id,
                    db_path=spike_db,
                    initial_state=state,
                    initial_version=version,
                    event_collector=collector,
                )
                try:
                    await adapter.trigger("start_upload")
                except (GuardRejectedError, StaleTransitionError):
                    pass  # Already logged by adapter

        # Launch 10 concurrent attempts
        await asyncio.gather(*[attempt(i) for i in range(10)])

        # Verify outcomes
        successes = collector.successes()
        rejections = collector.rejections()

        assert len(successes) == 1, (
            f"Expected 1 success, got {len(successes)}: {successes}"
        )
        assert len(rejections) == 9, (
            f"Expected 9 rejections, got {len(rejections)}: {rejections}"
        )

        # Verify DB state
        state, version = await read_file_state(spike_db, file_id)
        assert state == "uploading", f"Expected 'uploading', got '{state}'"
        assert version == 1, f"Expected version 1, got {version}"

        # Verify event log completeness
        all_events = collector.for_file(file_id)
        assert len(all_events) == 10, (
            f"Expected 10 event log entries, got {len(all_events)}"
        )

        # Verify required fields in every event
        required_fields = {
            "attempt_id", "file_id", "from_state", "to_state",
            "guard_result", "outcome",
        }
        for event in all_events:
            missing = required_fields - set(event.keys())
            assert not missing, f"Event missing fields {missing}: {event}"


class TestConcurrentDifferentFiles:
    """10 concurrent transitions on 10 DIFFERENT files (all should succeed)."""

    async def test_all_10_succeed(self, spike_db, seed_file):
        """10 different files, 10 concurrent transitions -- all succeed."""
        file_ids = [f"/test/file_{i}.txt" for i in range(10)]
        for fid in file_ids:
            await seed_file(fid, state="untracked", version=0)

        collector = EventCollector()

        async def attempt(file_id: str):
            state, version = await read_file_state(spike_db, file_id)
            adapter = StateMachineAdapter(
                file_id=file_id,
                db_path=spike_db,
                initial_state=state,
                initial_version=version,
                event_collector=collector,
            )
            await adapter.trigger("start_upload")

        # Launch 10 concurrent transitions on different files
        await asyncio.gather(*[attempt(fid) for fid in file_ids])

        # All 10 should succeed
        successes = collector.successes()
        assert len(successes) == 10, (
            f"Expected 10 successes, got {len(successes)}"
        )
        assert len(collector.rejections()) == 0, "No rejections expected"
        assert len(collector.failures()) == 0, "No failures expected"

        # Verify DB state for all files
        for fid in file_ids:
            state, version = await read_file_state(spike_db, fid)
            assert state == "uploading", (
                f"{fid}: expected 'uploading', got '{state}'"
            )
            assert version == 1, f"{fid}: expected version 1, got {version}"
