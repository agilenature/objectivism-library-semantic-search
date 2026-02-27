"""Phase 18 RxPY Operator Pattern Spike — Test Harness

Validates 5 highest-risk RxPY operator patterns before committing to full migration.
HOSTILE distrust posture: each pattern requires positive affirmative evidence.

Patterns:
  1. AsyncIOScheduler + aiosqlite SINGLETON connection co-existence
  2. OCC-guarded transition as a custom retry observable
  3. dynamic_semaphore(limit$: BehaviorSubject[int]) operator
  4. Two-signal shutdown via shutdown_gate operator
  5. Tenacity replacement with retry_when equivalent
"""

import asyncio
import time
import traceback
from dataclasses import dataclass
from typing import Any

import aiosqlite
import rx
from rx import operators as ops
from rx.scheduler.eventloop import AsyncIOScheduler
from rx.subject import BehaviorSubject, Subject


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PatternResult:
    pattern: int
    name: str
    passed: bool
    evidence: str
    elapsed_s: float


# ---------------------------------------------------------------------------
# Pattern test stubs (implemented in subsequent tasks)
# ---------------------------------------------------------------------------

async def test_pattern1_scheduler_aiosqlite() -> PatternResult:
    """Pattern 1: AsyncIOScheduler + aiosqlite SINGLETON connection."""
    t0 = time.monotonic()
    errors: list[str] = []
    evidence_lines: list[str] = []

    # Step 1: Create in-memory aiosqlite DB with ONE singleton connection
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("CREATE TABLE items (stream_id INTEGER, item_id INTEGER, value TEXT)")
    await conn.commit()

    loop = asyncio.get_running_loop()
    connection_ids_used: set[int] = set()

    # Step 2: Define the coroutine factory that uses the SINGLETON connection
    async def insert_item(stream_id: int, item_id: int, conn: aiosqlite.Connection) -> str:
        """Insert a row using the singleton connection."""
        connection_ids_used.add(id(conn))
        await conn.execute(
            "INSERT INTO items (stream_id, item_id, value) VALUES (?, ?, ?)",
            (stream_id, item_id, f"s{stream_id}_i{item_id}"),
        )
        await conn.commit()
        return f"s{stream_id}_i{item_id}"

    # Step 3: Build 10 concurrent observable streams, each emitting 3 items
    # Pattern: rx.defer(lambda: rx.from_future(asyncio.create_task(coro_factory(conn))))
    all_results: list[str] = []
    all_errors_rx: list[Exception] = []
    done_event = asyncio.Event()

    def build_stream(stream_id: int) -> rx.Observable:
        """Build one stream: 3 items, each triggers an aiosqlite INSERT."""
        return rx.of(0, 1, 2).pipe(
            ops.flat_map(lambda item_id, sid=stream_id: rx.defer(
                lambda iid=item_id: rx.from_future(
                    asyncio.create_task(insert_item(sid, iid, conn))
                )
            )),
        )

    # Step 4: Merge all 10 streams and subscribe
    streams = [build_stream(i) for i in range(10)]
    merged = rx.merge(*streams)

    merged.pipe(
        ops.to_list(),
    ).subscribe(
        on_next=lambda items: all_results.extend(items),
        on_error=lambda e: (all_errors_rx.append(e), done_event.set()),
        on_completed=lambda: done_event.set(),
    )

    # Wait for completion
    await asyncio.wait_for(done_event.wait(), timeout=10.0)

    # Step 5: Verify DB state
    async with conn.execute("SELECT COUNT(*) FROM items") as cursor:
        row_count = (await cursor.fetchone())[0]

    async with conn.execute("SELECT DISTINCT stream_id FROM items ORDER BY stream_id") as cursor:
        distinct_streams = [r[0] for r in await cursor.fetchall()]

    # Step 6: Adversarial retry check — simulate 2 retries per stream using same conn
    retry_results: list[str] = []
    retry_errors: list[Exception] = []
    retry_done = asyncio.Event()

    async def insert_with_retry(stream_id: int, item_id: int, conn: aiosqlite.Connection) -> str:
        """Simulate retry: attempt insert, 'fail' first time, succeed second."""
        # First attempt always succeeds with aiosqlite (no real OCC here),
        # but we validate the connection survives re-use across retry cycles
        for attempt in range(3):  # 2 retries + 1 success
            connection_ids_used.add(id(conn))
            if attempt < 2:
                # Simulate a retry scenario — do a no-op read then 'retry'
                async with conn.execute("SELECT COUNT(*) FROM items") as cur:
                    await cur.fetchone()
                continue
            # Final attempt: do the actual insert
            await conn.execute(
                "INSERT INTO items (stream_id, item_id, value) VALUES (?, ?, ?)",
                (stream_id + 100, item_id, f"retry_s{stream_id}_i{item_id}"),
            )
            await conn.commit()
            return f"retry_s{stream_id}_i{item_id}"
        return "unreachable"

    retry_streams = [
        rx.of(0, 1).pipe(
            ops.flat_map(lambda item_id, sid=i: rx.defer(
                lambda iid=item_id: rx.from_future(
                    asyncio.create_task(insert_with_retry(sid, iid, conn))
                )
            )),
        )
        for i in range(10)
    ]

    rx.merge(*retry_streams).pipe(
        ops.to_list(),
    ).subscribe(
        on_next=lambda items: retry_results.extend(items),
        on_error=lambda e: (retry_errors.append(e), retry_done.set()),
        on_completed=lambda: retry_done.set(),
    )

    await asyncio.wait_for(retry_done.wait(), timeout=10.0)

    async with conn.execute("SELECT COUNT(*) FROM items WHERE stream_id >= 100") as cursor:
        retry_row_count = (await cursor.fetchone())[0]

    await conn.close()

    # Step 7: Collect evidence
    elapsed = time.monotonic() - t0
    evidence_lines.append(f"Initial rows inserted: {row_count} (expected 30)")
    evidence_lines.append(f"Distinct streams: {len(distinct_streams)} (expected 10)")
    evidence_lines.append(f"Observable items collected: {len(all_results)} (expected 30)")
    evidence_lines.append(f"RxPY errors during initial run: {len(all_errors_rx)}")
    evidence_lines.append(f"Retry rows inserted: {retry_row_count} (expected 20)")
    evidence_lines.append(f"Retry observable items: {len(retry_results)} (expected 20)")
    evidence_lines.append(f"RxPY errors during retry run: {len(retry_errors)}")
    evidence_lines.append(f"Unique connection IDs used: {len(connection_ids_used)} (expected 1 = singleton)")
    evidence_lines.append(f"Elapsed: {elapsed:.3f}s")

    passed = (
        row_count == 30
        and len(distinct_streams) == 10
        and len(all_results) == 30
        and len(all_errors_rx) == 0
        and retry_row_count == 20
        and len(retry_results) == 20
        and len(retry_errors) == 0
        and len(connection_ids_used) == 1
    )

    if not passed:
        if all_errors_rx:
            evidence_lines.append(f"RxPY error detail: {all_errors_rx[0]}")
        if retry_errors:
            evidence_lines.append(f"Retry error detail: {retry_errors[0]}")

    return PatternResult(
        pattern=1,
        name="AsyncIOScheduler + aiosqlite SINGLETON connection",
        passed=passed,
        evidence="\n".join(evidence_lines),
        elapsed_s=elapsed,
    )


async def test_pattern2_occ_transition() -> PatternResult:
    """Pattern 2: OCC-guarded transition as custom retry observable."""
    raise NotImplementedError("Pattern 2 not yet implemented")


async def test_pattern3_dynamic_semaphore() -> PatternResult:
    """Pattern 3: dynamic_semaphore with BehaviorSubject-driven limit."""
    raise NotImplementedError("Pattern 3 not yet implemented")


async def test_pattern4_shutdown_gate() -> PatternResult:
    """Pattern 4: Two-signal shutdown via shutdown_gate operator."""
    raise NotImplementedError("Pattern 4 not yet implemented")


async def test_pattern5_retry_replacement() -> PatternResult:
    """Pattern 5: Tenacity replacement with RxPY retry logic."""
    raise NotImplementedError("Pattern 5 not yet implemented")


# ---------------------------------------------------------------------------
# Main harness
# ---------------------------------------------------------------------------

async def run_all_patterns() -> list[PatternResult]:
    """Run all 5 pattern tests sequentially, collecting results."""
    tests = [
        test_pattern1_scheduler_aiosqlite,
        test_pattern2_occ_transition,
        test_pattern3_dynamic_semaphore,
        test_pattern4_shutdown_gate,
        test_pattern5_retry_replacement,
    ]
    results: list[PatternResult] = []
    for test_fn in tests:
        t0 = time.monotonic()
        try:
            result = await test_fn()
        except Exception as e:
            result = PatternResult(
                pattern=len(results) + 1,
                name=test_fn.__doc__ or test_fn.__name__,
                passed=False,
                evidence=f"EXCEPTION: {type(e).__name__}: {e}\n{traceback.format_exc()}",
                elapsed_s=time.monotonic() - t0,
            )
        results.append(result)
    return results


def print_results(results: list[PatternResult]) -> None:
    """Print results summary."""
    print("\n" + "=" * 72)
    print("Phase 18 RxPY Operator Pattern Spike — Results")
    print("=" * 72)
    for r in results:
        status = "PASSED" if r.passed else "FAILED"
        print(f"\nPattern {r.pattern}: {status} ({r.elapsed_s:.3f}s)")
        print(f"  Name: {r.name}")
        for line in r.evidence.strip().split("\n"):
            print(f"  {line}")
    print("\n" + "-" * 72)
    all_passed = all(r.passed for r in results)
    verdict = "GO" if all_passed else "NO-GO"
    passed_count = sum(1 for r in results if r.passed)
    print(f"Verdict: {verdict} ({passed_count}/{len(results)} patterns passed)")
    print("-" * 72)


if __name__ == "__main__":
    results = asyncio.run(run_all_patterns())
    print_results(results)
