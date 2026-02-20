"""Thread and task leak detection tests.

Verifies that threading.active_count() and asyncio task counts return
to baseline after concurrent transitions complete (locked decision #2,
affirmative evidence point 3).
"""

import asyncio
import threading

import pytest

from spike.phase9_spike.adapters.statemachine_adapter import StateMachineAdapter
from spike.phase9_spike.db import read_file_state
from spike.phase9_spike.event_log import EventCollector
from spike.phase9_spike.exceptions import GuardRejectedError, StaleTransitionError


class TestLeakCheck:
    """Thread and task leak detection after concurrent transitions."""

    async def test_no_thread_leak_after_concurrent_transitions(
        self, spike_db, seed_file
    ):
        """Thread count returns to baseline after 10 concurrent transitions."""
        # Seed 10 different files
        file_ids = [f"/test/leak_check_{i}.txt" for i in range(10)]
        for fid in file_ids:
            await seed_file(fid, state="untracked", version=0)

        # Record baseline
        thread_baseline = threading.active_count()

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

        # Run concurrent transitions
        await asyncio.gather(*[attempt(fid) for fid in file_ids])

        # Allow brief settle time for aiosqlite thread cleanup
        await asyncio.sleep(0.2)

        thread_after = threading.active_count()

        # Thread count should return to baseline (within tolerance of +1)
        assert thread_after <= thread_baseline + 1, (
            f"Thread leak detected: {thread_after} threads after "
            f"(baseline: {thread_baseline})"
        )

    async def test_no_task_leak_after_concurrent_transitions(
        self, spike_db, seed_file
    ):
        """Task count returns to baseline after 10 concurrent transitions."""
        # Seed 10 different files
        file_ids = [f"/test/task_leak_{i}.txt" for i in range(10)]
        for fid in file_ids:
            await seed_file(fid, state="untracked", version=0)

        # Record baseline (the running test task itself)
        task_baseline = len(asyncio.all_tasks())

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

        # Run concurrent transitions
        await asyncio.gather(*[attempt(fid) for fid in file_ids])

        # Allow settle time
        await asyncio.sleep(0.1)

        task_after = len(asyncio.all_tasks())

        # Task count should return to baseline
        assert task_after <= task_baseline, (
            f"Task leak detected: {task_after} tasks after "
            f"(baseline: {task_baseline})"
        )

    async def test_no_leak_after_mixed_same_and_different_files(
        self, spike_db, seed_file
    ):
        """No leaks after a mix of same-file contention and different files."""
        from collections import defaultdict

        # Seed 5 unique files + 1 contended file
        contended_id = "/test/leak_contended.txt"
        await seed_file(contended_id, state="untracked", version=0)

        unique_ids = [f"/test/leak_unique_{i}.txt" for i in range(5)]
        for fid in unique_ids:
            await seed_file(fid, state="untracked", version=0)

        thread_baseline = threading.active_count()
        task_baseline = len(asyncio.all_tasks())

        collector = EventCollector()
        locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

        async def attempt_with_lock(file_id: str):
            async with locks[file_id]:
                state, version = await read_file_state(spike_db, file_id)
                if state != "untracked":
                    collector.emit(
                        file_id=file_id,
                        from_state=state,
                        to_state="uploading",
                        event="start_upload",
                        outcome="rejected",
                        guard_result=False,
                        error=f"Already {state}",
                    )
                    return

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
                    pass

        # 5 attempts on contended file + 5 unique files = 10 total
        coros = [attempt_with_lock(contended_id) for _ in range(5)]
        coros += [attempt_with_lock(fid) for fid in unique_ids]
        await asyncio.gather(*coros)

        # Settle
        await asyncio.sleep(0.2)

        thread_after = threading.active_count()
        task_after = len(asyncio.all_tasks())

        assert thread_after <= thread_baseline + 1, (
            f"Thread leak: {thread_after} after (baseline: {thread_baseline})"
        )
        assert task_after <= task_baseline, (
            f"Task leak: {task_after} after (baseline: {task_baseline})"
        )
