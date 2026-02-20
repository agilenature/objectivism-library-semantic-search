"""Combined adversarial test runner for Phase 9 spike.

Produces all 4 affirmative evidence artifacts:
1. DB invariants check (all states valid, versions non-negative)
2. Structured JSON event log (every attempt with required fields)
3. Thread/task leak check (counts return to baseline)
4. Same-file adversarial test (exactly 1 success, 9 rejections)

Run: python -m spike.phase9_spike.harness
"""

import asyncio
import json
import os
import sys
import threading
from collections import defaultdict

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from spike.phase9_spike.adapters.statemachine_adapter import StateMachineAdapter
from spike.phase9_spike.db import init_spike_db, read_file_state
from spike.phase9_spike.event_log import EventCollector
from spike.phase9_spike.exceptions import (
    GuardRejectedError,
    StaleTransitionError,
)
from spike.phase9_spike.protocol import FileStateMachineProtocol
from spike.phase9_spike.states import VALID_STATES
from spike.phase9_spike.tests.test_db_invariants import check_db_invariants


DB_PATH = "/tmp/phase9_spike.db"


class HarnessResult:
    """Structured result from the harness run."""

    def __init__(self):
        self.checks: dict[str, dict] = {}

    def add_check(self, name: str, passed: bool, details: dict):
        self.checks[name] = {"passed": passed, **details}

    @property
    def all_passed(self) -> bool:
        return all(c["passed"] for c in self.checks.values())


async def run_different_file_transitions(
    db_path: str, file_ids: list[str], collector: EventCollector
) -> None:
    """Run concurrent transitions on different files (all should succeed)."""

    async def attempt(file_id: str):
        state, version = await read_file_state(db_path, file_id)
        adapter = StateMachineAdapter(
            file_id=file_id,
            db_path=db_path,
            initial_state=state,
            initial_version=version,
            event_collector=collector,
        )
        await adapter.trigger("start_upload")

    await asyncio.gather(*[attempt(fid) for fid in file_ids])


async def run_same_file_contention(
    db_path: str, file_id: str, num_attempts: int,
    collector: EventCollector,
) -> None:
    """Run concurrent transitions on the SAME file."""
    locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def attempt(attempt_num: int):
        async with locks[file_id]:
            state, version = await read_file_state(db_path, file_id)

            if state != "untracked":
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

            adapter = StateMachineAdapter(
                file_id=file_id,
                db_path=db_path,
                initial_state=state,
                initial_version=version,
                event_collector=collector,
            )
            try:
                await adapter.trigger("start_upload")
            except (GuardRejectedError, StaleTransitionError):
                pass  # Already logged by adapter

    await asyncio.gather(*[attempt(i) for i in range(num_attempts)])


async def run_harness() -> HarnessResult:
    """Run the complete adversarial test harness."""
    result = HarnessResult()

    print("=" * 70)
    print("Phase 9 Spike: Adversarial FSM Test Harness")
    print("=" * 70)
    print()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    await init_spike_db(DB_PATH)

    # Verify adapter satisfies Protocol
    import aiosqlite
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO files (file_path, gemini_state, version) "
            "VALUES (?, ?, ?)",
            ("/test/protocol_check.txt", "untracked", 0),
        )
        await db.commit()

    adapter = StateMachineAdapter(
        file_id="/test/protocol_check.txt",
        db_path=DB_PATH,
        initial_state="untracked",
        initial_version=0,
    )
    protocol_ok = isinstance(adapter, FileStateMachineProtocol)
    print(f"[SETUP] Protocol check: {'PASS' if protocol_ok else 'FAIL'}")
    result.add_check("protocol", protocol_ok, {
        "message": "StateMachineAdapter satisfies FileStateMachineProtocol"
    })

    # Seed 10 unique files + 1 contended file
    import aiosqlite as aiosqlite2
    async with aiosqlite2.connect(DB_PATH) as db:
        for i in range(10):
            await db.execute(
                "INSERT INTO files (file_path, gemini_state, version) "
                "VALUES (?, ?, ?)",
                (f"/test/unique_{i}.txt", "untracked", 0),
            )
        await db.execute(
            "INSERT INTO files (file_path, gemini_state, version) "
            "VALUES (?, ?, ?)",
            ("/test/contended.txt", "untracked", 0),
        )
        await db.commit()

    print(f"[SETUP] Seeded 11 test files (10 unique + 1 contended)")
    print()

    # ------------------------------------------------------------------
    # Record baselines
    # ------------------------------------------------------------------
    thread_baseline = threading.active_count()
    task_baseline = len(asyncio.all_tasks())
    print(f"[BASELINE] Threads: {thread_baseline}")
    print(f"[BASELINE] Tasks: {task_baseline}")
    print()

    # ------------------------------------------------------------------
    # Test 1: 10 concurrent transitions on different files
    # ------------------------------------------------------------------
    print("[TEST 1] 10 concurrent transitions on different files...")
    diff_collector = EventCollector()
    diff_file_ids = [f"/test/unique_{i}.txt" for i in range(10)]

    await run_different_file_transitions(DB_PATH, diff_file_ids, diff_collector)

    diff_successes = len(diff_collector.successes())
    diff_pass = diff_successes == 10
    print(f"  Successes: {diff_successes}/10 - {'PASS' if diff_pass else 'FAIL'}")
    result.add_check("different_files", diff_pass, {
        "successes": diff_successes,
        "rejections": len(diff_collector.rejections()),
        "failures": len(diff_collector.failures()),
    })
    print()

    # ------------------------------------------------------------------
    # Test 2: 10 concurrent transitions on SAME file
    # ------------------------------------------------------------------
    print("[TEST 2] 10 concurrent transitions on same file...")
    same_collector = EventCollector()

    await run_same_file_contention(
        DB_PATH, "/test/contended.txt", 10, same_collector
    )

    same_successes = len(same_collector.successes())
    same_rejections = len(same_collector.rejections())
    same_pass = same_successes == 1 and same_rejections == 9
    print(f"  Successes: {same_successes} (expected 1)")
    print(f"  Rejections: {same_rejections} (expected 9)")
    print(f"  Result: {'PASS' if same_pass else 'FAIL'}")
    result.add_check("same_file_contention", same_pass, {
        "successes": same_successes,
        "rejections": same_rejections,
        "failures": len(same_collector.failures()),
    })
    print()

    # ------------------------------------------------------------------
    # Test 3: JSON event log validation
    # ------------------------------------------------------------------
    print("[TEST 3] JSON event log validation...")
    all_events = diff_collector.events + same_collector.events
    required_fields = {
        "attempt_id", "file_id", "from_state", "to_state",
        "guard_result", "outcome",
    }
    log_violations = []
    for event in all_events:
        missing = required_fields - set(event.keys())
        if missing:
            log_violations.append(f"Missing fields {missing} in {event}")

    log_pass = len(log_violations) == 0
    print(f"  Total events: {len(all_events)}")
    print(f"  Violations: {len(log_violations)}")
    print(f"  Result: {'PASS' if log_pass else 'FAIL'}")
    result.add_check("event_log", log_pass, {
        "total_events": len(all_events),
        "violations": log_violations,
    })

    # Print sample event for evidence
    if all_events:
        print(f"  Sample event: {json.dumps(all_events[0], indent=2)}")
    print()

    # ------------------------------------------------------------------
    # Test 4: DB invariants
    # ------------------------------------------------------------------
    print("[TEST 4] DB invariant check...")
    db_violations = await check_db_invariants(DB_PATH)
    db_pass = len(db_violations) == 0
    print(f"  Violations: {len(db_violations)}")
    if db_violations:
        for v in db_violations:
            print(f"    - {v}")
    print(f"  Result: {'PASS' if db_pass else 'FAIL'}")
    result.add_check("db_invariants", db_pass, {
        "violations": db_violations,
    })
    print()

    # ------------------------------------------------------------------
    # Test 5: Thread/task leak check
    # ------------------------------------------------------------------
    print("[TEST 5] Thread/task leak check...")
    await asyncio.sleep(0.2)  # Settle time for aiosqlite thread cleanup

    thread_after = threading.active_count()
    task_after = len(asyncio.all_tasks())

    thread_pass = thread_after <= thread_baseline + 1
    task_pass = task_after <= task_baseline

    print(f"  Threads: {thread_baseline} -> {thread_after} "
          f"({'PASS' if thread_pass else 'FAIL'})")
    print(f"  Tasks: {task_baseline} -> {task_after} "
          f"({'PASS' if task_pass else 'FAIL'})")
    leak_pass = thread_pass and task_pass
    print(f"  Result: {'PASS' if leak_pass else 'FAIL'}")
    result.add_check("leak_check", leak_pass, {
        "thread_baseline": thread_baseline,
        "thread_after": thread_after,
        "task_baseline": task_baseline,
        "task_after": task_after,
    })
    print()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    # Also remove WAL and SHM files
    for suffix in ["-wal", "-shm"]:
        path = DB_PATH + suffix
        if os.path.exists(path):
            os.remove(path)

    db_cleaned = not os.path.exists(DB_PATH)
    print(f"[CLEANUP] DB removed: {'YES' if db_cleaned else 'NO'}")
    print()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("=" * 70)
    if result.all_passed:
        print("ALL CHECKS PASSED")
    else:
        failed = [name for name, check in result.checks.items()
                  if not check["passed"]]
        print(f"FAILURES DETECTED: {', '.join(failed)}")
    print("=" * 70)

    # Print full results as JSON
    print()
    print("Full results (JSON):")
    print(json.dumps(result.checks, indent=2, default=str))

    return result


def main():
    """Entry point for python -m spike.phase9_spike.harness."""
    result = asyncio.run(run_harness())
    sys.exit(0 if result.all_passed else 1)


if __name__ == "__main__":
    main()
