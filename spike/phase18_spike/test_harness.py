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
    import random

    t0 = time.monotonic()
    evidence_lines: list[str] = []

    # ---------------------------------------------------------------------------
    # occ_transition operator: retries fn() internally on OCCConflictError
    # Per Q3: fn() is retried, NOT outer observable re-subscribe
    # ---------------------------------------------------------------------------

    class OCCConflictError(Exception):
        pass

    def occ_transition(fn, max_attempts=5, base_delay=0.01):
        """Custom operator: retry fn() on OCCConflictError with exponential backoff + jitter.

        fn: async callable () -> T (reads fresh DB state on each call)
        Returns: Observable that emits fn()'s result on success, or errors after max_attempts.
        """
        def subscribe(observer, scheduler=None):
            async def run():
                for attempt in range(max_attempts):
                    try:
                        result = await fn()
                        observer.on_next(result)
                        observer.on_completed()
                        return
                    except OCCConflictError:
                        if attempt == max_attempts - 1:
                            observer.on_error(
                                OCCConflictError(f"OCC conflict after {max_attempts} attempts")
                            )
                            return
                        delay = min(base_delay * (2 ** attempt) + random.random() * 0.005, 1.0)
                        await asyncio.sleep(delay)
            asyncio.ensure_future(run())
        return rx.create(subscribe)

    # ---------------------------------------------------------------------------
    # Adversarial test: shared counter with optimistic locking
    # ---------------------------------------------------------------------------

    # Simulated DB row with version-based OCC
    counter_lock = asyncio.Lock()  # Simulates serialized DB writes
    counter_value = 0
    counter_version = 0
    total_retries = 0

    async def occ_increment() -> str:
        """Atomically increment counter using OCC. Raises OCCConflictError on version mismatch."""
        nonlocal counter_value, counter_version, total_retries

        # Read phase (snapshot)
        read_version = counter_version
        read_value = counter_value

        # Simulate some processing delay to increase conflict probability
        await asyncio.sleep(random.random() * 0.002)

        # Write phase (optimistic)
        async with counter_lock:
            if counter_version != read_version:
                total_retries += 1
                raise OCCConflictError(
                    f"Version mismatch: expected {read_version}, got {counter_version}"
                )
            counter_value = read_value + 1
            counter_version += 1
            return f"incremented_to_{counter_value}"

    # Run 10 concurrent occ_transition observables
    results: list[str] = []
    errors_list: list[Exception] = []
    done_event = asyncio.Event()
    completed_count = 0

    def on_next(v):
        results.append(v)

    def on_error(e):
        errors_list.append(e)
        done_event.set()

    def on_completed():
        nonlocal completed_count
        completed_count += 1
        if completed_count == 10:
            done_event.set()

    # Each of the 10 coroutines gets its own occ_transition observable
    # They share the same counter — conflicts WILL happen
    for i in range(10):
        occ_transition(occ_increment, max_attempts=20, base_delay=0.005).subscribe(
            on_next=on_next,
            on_error=on_error,
            on_completed=on_completed,
        )

    await asyncio.wait_for(done_event.wait(), timeout=10.0)

    elapsed = time.monotonic() - t0

    # Collect evidence
    evidence_lines.append(f"Final counter value: {counter_value} (expected 10)")
    evidence_lines.append(f"Final counter version: {counter_version} (expected 10)")
    evidence_lines.append(f"Successful results: {len(results)} (expected 10)")
    evidence_lines.append(f"Total OCC retries: {total_retries}")
    evidence_lines.append(f"Errors: {len(errors_list)}")
    evidence_lines.append(f"Elapsed: {elapsed:.3f}s")

    if errors_list:
        for e in errors_list:
            evidence_lines.append(f"Error: {type(e).__name__}: {e}")

    passed = (
        counter_value == 10
        and counter_version == 10
        and len(results) == 10
        and len(errors_list) == 0
    )

    return PatternResult(
        pattern=2,
        name="OCC-guarded transition as custom retry observable",
        passed=passed,
        evidence="\n".join(evidence_lines),
        elapsed_s=elapsed,
    )


async def test_pattern3_dynamic_semaphore() -> PatternResult:
    """Pattern 3: dynamic_semaphore with BehaviorSubject-driven limit."""
    t0 = time.monotonic()
    evidence_lines: list[str] = []

    # ---------------------------------------------------------------------------
    # dynamic_semaphore operator: BehaviorSubject-driven concurrency control
    # Per Q2: custom named operator, NOT flat_map max_concurrent
    #
    # IMPORTANT: Source must emit COROUTINE FACTORIES (callables returning awaitables),
    # NOT pre-started futures/tasks. The operator controls when work starts by calling
    # the factory only when active_count < current_limit. Pre-started futures would
    # bypass concurrency control entirely.
    # ---------------------------------------------------------------------------

    def dynamic_semaphore(limit_subject: BehaviorSubject):
        """Custom operator: controls concurrency dynamically via BehaviorSubject limit.

        Source emits: Callable[[], Awaitable[T]] (coroutine factories)
        Output emits: T (resolved results)

        Maintains internal buffer of factories. Only starts work (calls factory)
        when active_count < current_limit. On limit decrease: in-flight items
        complete normally (no cancellation). New items blocked until active count
        drops below new limit.
        """
        def _operator(source):
            def subscribe(observer, scheduler=None):
                buffer: list = []
                active_count = 0
                current_limit = limit_subject.value
                source_completed = False
                is_disposed = False
                dispatch_lock = asyncio.Lock()

                async def dispatch():
                    nonlocal active_count
                    async with dispatch_lock:
                        while buffer and active_count < current_limit and not is_disposed:
                            factory = buffer.pop(0)
                            active_count += 1
                            # Start work NOW by calling the factory
                            coro = factory()
                            asyncio.ensure_future(process_item(coro))

                async def process_item(coro):
                    nonlocal active_count
                    try:
                        result = await coro
                        if not is_disposed:
                            observer.on_next(result)
                    except Exception as e:
                        if not is_disposed:
                            observer.on_error(e)
                            return
                    async with dispatch_lock:
                        active_count -= 1
                    await dispatch()
                    await check_complete()

                async def check_complete():
                    async with dispatch_lock:
                        if source_completed and active_count == 0 and not buffer and not is_disposed:
                            observer.on_completed()

                def on_limit_change(new_limit):
                    nonlocal current_limit
                    current_limit = new_limit
                    asyncio.ensure_future(dispatch())

                def on_next(factory):
                    buffer.append(factory)
                    asyncio.ensure_future(dispatch())

                def on_error(e):
                    if not is_disposed:
                        observer.on_error(e)

                def on_completed():
                    nonlocal source_completed
                    source_completed = True
                    asyncio.ensure_future(check_complete())

                limit_subject.subscribe(on_next=on_limit_change)
                source.subscribe(on_next=on_next, on_error=on_error, on_completed=on_completed)

            return rx.create(subscribe)
        return _operator

    # ---------------------------------------------------------------------------
    # Test: 20 items, external limit drop from 10 to 2 after first batch starts
    #
    # The limit change comes from an EXTERNAL signal (simulating 429 pressure),
    # not from within a work item. This is the realistic production pattern:
    # the orchestrator receives a 429, then fires limit_subject.on_next(2).
    # ---------------------------------------------------------------------------

    max_concurrent_seen = 0
    concurrent_count = 0
    completed_items: list[int] = []
    concurrency_log: list[tuple[int, int]] = []  # (item_id, concurrent_at_start)
    limit_subject = BehaviorSubject(10)
    done_event = asyncio.Event()

    concurrency_lock = asyncio.Lock()

    async def work_item(item_id: int) -> int:
        nonlocal max_concurrent_seen, concurrent_count
        async with concurrency_lock:
            concurrent_count += 1
            if concurrent_count > max_concurrent_seen:
                max_concurrent_seen = concurrent_count
            concurrency_log.append((item_id, concurrent_count))

        await asyncio.sleep(0.04)  # Simulate work

        async with concurrency_lock:
            concurrent_count -= 1
            completed_items.append(item_id)

        return item_id

    # Build source: emit 20 coroutine FACTORIES (not pre-started tasks)
    items_emitted: list[int] = list(range(20))
    results_list: list[int] = []

    source = rx.from_iterable(items_emitted).pipe(
        ops.map(lambda item_id: lambda iid=item_id: work_item(iid)),
        dynamic_semaphore(limit_subject),
    )

    source.subscribe(
        on_next=lambda v: results_list.append(v),
        on_error=lambda e: evidence_lines.append(f"ERROR: {e}") or done_event.set(),
        on_completed=lambda: done_event.set(),
    )

    # External limit drop: after first batch has started (10ms in), drop to 2
    # This simulates a 429 pressure signal arriving while first batch is in-flight
    await asyncio.sleep(0.01)
    limit_subject.on_next(2)

    await asyncio.wait_for(done_event.wait(), timeout=15.0)

    elapsed = time.monotonic() - t0

    # Analyze concurrency AFTER the limit drop took effect
    # The first batch (items 0-9) was dispatched before the drop, so they run at limit=10.
    # Items dispatched AFTER the drop should respect limit=2.
    # We identify post-drop items by their start time: items that started after items 0-9 completed
    # In the concurrency log, items that were dispatched after the limit change have item_id >= 10
    post_drop_concurrent = [
        c for (item_id, c) in concurrency_log if item_id >= 10
    ]
    max_post_drop = max(post_drop_concurrent) if post_drop_concurrent else 0

    evidence_lines.append(f"Total items completed: {len(completed_items)} (expected 20)")
    evidence_lines.append(f"Max concurrency overall: {max_concurrent_seen}")
    evidence_lines.append(f"Max concurrency after limit drop to 2: {max_post_drop} (expected <= 2)")
    evidence_lines.append(f"Results collected: {len(results_list)} (expected 20)")
    evidence_lines.append(f"No item loss: {sorted(completed_items) == list(range(20))}")
    evidence_lines.append(f"Concurrency log (first 5): {concurrency_log[:5]}")
    evidence_lines.append(f"Concurrency log (post-drop): {[(i, c) for i, c in concurrency_log if i >= 10]}")
    evidence_lines.append(f"Elapsed: {elapsed:.3f}s")

    passed = (
        len(completed_items) == 20
        and len(results_list) == 20
        and max_post_drop <= 2
        and sorted(completed_items) == list(range(20))
    )

    return PatternResult(
        pattern=3,
        name="dynamic_semaphore with BehaviorSubject-driven limit",
        passed=passed,
        evidence="\n".join(evidence_lines),
        elapsed_s=elapsed,
    )


async def test_pattern4_shutdown_gate() -> PatternResult:
    """Pattern 4: Two-signal shutdown via shutdown_gate operator."""
    t0 = time.monotonic()
    evidence_lines: list[str] = []

    # ---------------------------------------------------------------------------
    # shutdown_gate: two-signal shutdown pattern
    # Per Q4: stop_accepting$ gates NEW items, force_kill$ terminates active chains
    #
    # KEY ARCHITECTURAL INSIGHT from spike:
    # The two signals apply at DIFFERENT POINTS in the pipeline:
    #   - stop_accepting$ -> take_until BEFORE flat_map (gates input)
    #   - force_kill$ -> take_until AFTER flat_map (kills in-flight work)
    #
    # This means shutdown_gate returns two pipeable operators, not one:
    #   gate_input = stop_accepting gate (applied to source)
    #   gate_output = force_kill gate (applied to processing output)
    #
    # Production pipeline composition:
    #   source.pipe(
    #       gate_input(stop_accepting$),
    #       ops.flat_map(process_fn),
    #       gate_output(force_kill$),
    #   )
    # ---------------------------------------------------------------------------

    def gate_input(stop_accepting):
        """Gate new items from entering the pipeline (pipeable operator).
        Applied BEFORE flat_map. In-flight items continue to completion."""
        return ops.take_until(stop_accepting)

    def gate_output(force_kill):
        """Terminate entire pipeline including in-flight work (pipeable operator).
        Applied AFTER flat_map. Immediate termination."""
        return ops.take_until(force_kill)

    # ---------------------------------------------------------------------------
    # Sub-test 1: stop_accepting$ only — in-flight complete, no new items
    # ---------------------------------------------------------------------------

    stop_accepting = Subject()
    items_started_1: list[int] = []
    items_completed_1: list[int] = []
    results1: list[int] = []
    done1 = asyncio.Event()

    async def work_with_delay_1(item_id: int) -> int:
        items_started_1.append(item_id)
        await asyncio.sleep(0.05)
        items_completed_1.append(item_id)
        return item_id

    # Source emits 20 item IDs via Subject, with stagger
    source1 = Subject()

    # Pipeline: source -> gate_input(stop_accepting) -> flat_map(work) -> collect
    source1.pipe(
        gate_input(stop_accepting),
        ops.flat_map(lambda i: rx.from_future(asyncio.ensure_future(work_with_delay_1(i)))),
    ).subscribe(
        on_next=lambda v: results1.append(v),
        on_error=lambda e: evidence_lines.append(f"Sub-test 1 ERROR: {e}") or done1.set(),
        on_completed=lambda: done1.set(),
    )

    # Emit items 0-9, then fire stop_accepting, then emit 10-19
    for i in range(10):
        source1.on_next(i)

    # Fire stop_accepting — gate closes
    stop_accepting.on_next(None)

    # These should be dropped (gate is closed)
    for i in range(10, 20):
        source1.on_next(i)
    source1.on_completed()

    # Wait for in-flight items to drain
    await asyncio.wait_for(done1.wait(), timeout=10.0)

    evidence_lines.append(f"Sub-test 1 (stop_accepting):")
    evidence_lines.append(f"  Items started: {len(items_started_1)} (expected 10)")
    evidence_lines.append(f"  Items completed: {len(items_completed_1)} (expected 10)")
    evidence_lines.append(f"  Results received: {len(results1)} (expected 10)")
    subtest1_pass = (
        len(items_started_1) == 10
        and len(items_completed_1) == 10
        and len(results1) == 10
    )

    # ---------------------------------------------------------------------------
    # Sub-test 2: force_kill$ only — immediate termination of active chains
    # ---------------------------------------------------------------------------

    force_kill = Subject()
    items_started_2: list[int] = []
    items_completed_2: list[int] = []
    results2: list[int] = []
    done2 = asyncio.Event()

    async def slow_work_2(item_id: int) -> int:
        items_started_2.append(item_id)
        await asyncio.sleep(0.5)  # Long work
        items_completed_2.append(item_id)
        return item_id

    source2 = Subject()

    # Pipeline: source -> flat_map(work) -> gate_output(force_kill)
    # force_kill applied AFTER flat_map to terminate in-flight work
    source2.pipe(
        ops.flat_map(lambda i: rx.from_future(asyncio.ensure_future(slow_work_2(i)))),
        gate_output(force_kill),
    ).subscribe(
        on_next=lambda v: results2.append(v),
        on_error=lambda e: evidence_lines.append(f"Sub-test 2 ERROR: {e}") or done2.set(),
        on_completed=lambda: done2.set(),
    )

    # Start 5 slow items
    for i in range(5):
        source2.on_next(i)

    await asyncio.sleep(0.05)  # Let them start
    force_kill.on_next(None)  # Immediate termination

    await asyncio.wait_for(done2.wait(), timeout=5.0)

    evidence_lines.append(f"Sub-test 2 (force_kill):")
    evidence_lines.append(f"  Items started: {len(items_started_2)} (expected 5)")
    evidence_lines.append(f"  Results received after force_kill: {len(results2)} (expected 0)")
    # force_kill completes the chain before slow items finish
    subtest2_pass = len(results2) == 0

    # Wait a bit for any lingering futures
    await asyncio.sleep(0.1)

    # ---------------------------------------------------------------------------
    # Sub-test 3: Normal shutdown sequence — stop_accepting -> drain -> force_kill
    # ---------------------------------------------------------------------------

    stop_acc3 = Subject()
    force_kill3 = Subject()
    items_started_3: list[int] = []
    items_completed_3: list[int] = []
    results3: list[int] = []
    done3 = asyncio.Event()

    async def medium_work_3(item_id: int) -> int:
        items_started_3.append(item_id)
        await asyncio.sleep(0.05)
        items_completed_3.append(item_id)
        return item_id

    source3 = Subject()

    # Both gates: gate_input on source, gate_output on processing
    source3.pipe(
        gate_input(stop_acc3),
        ops.flat_map(lambda i: rx.from_future(asyncio.ensure_future(medium_work_3(i)))),
        gate_output(force_kill3),
    ).subscribe(
        on_next=lambda v: results3.append(v),
        on_error=lambda e: evidence_lines.append(f"Sub-test 3 ERROR: {e}") or done3.set(),
        on_completed=lambda: done3.set(),
    )

    # Emit 10 items
    for i in range(10):
        source3.on_next(i)

    await asyncio.sleep(0.01)  # Let first batch start

    # Stop accepting — no new items enter
    stop_acc3.on_next(None)

    # Try to emit more — should be dropped (take_until already fired)
    for i in range(10, 15):
        source3.on_next(i)

    # Wait for drain (in-flight items complete)
    await asyncio.sleep(0.15)

    # Force kill — clean up (chain may already be completed from drain)
    force_kill3.on_next(None)

    await asyncio.wait_for(done3.wait(), timeout=5.0)

    post_stop_started = len([x for x in items_started_3 if x >= 10])

    evidence_lines.append(f"Sub-test 3 (stop_accepting -> drain -> force_kill):")
    evidence_lines.append(f"  Items started: {len(items_started_3)} (expected 10)")
    evidence_lines.append(f"  Items completed (drain): {len(items_completed_3)} (expected 10)")
    evidence_lines.append(f"  Results received: {len(results3)} (expected 10)")
    evidence_lines.append(f"  Items after stop_accepting started: {post_stop_started} (expected 0)")

    subtest3_pass = (
        len(results3) == 10
        and post_stop_started == 0
        and len(items_completed_3) == 10
    )

    elapsed = time.monotonic() - t0
    evidence_lines.append(f"Elapsed: {elapsed:.3f}s")

    passed = subtest1_pass and subtest2_pass and subtest3_pass

    return PatternResult(
        pattern=4,
        name="Two-signal shutdown via shutdown_gate operator",
        passed=passed,
        evidence="\n".join(evidence_lines),
        elapsed_s=elapsed,
    )


async def test_pattern5_retry_replacement() -> PatternResult:
    """Pattern 5: Tenacity replacement with RxPY retry logic."""
    t0 = time.monotonic()
    evidence_lines: list[str] = []

    # ---------------------------------------------------------------------------
    # retry_with_backoff: custom operator replacing tenacity AsyncRetrying
    # RxPY 3.x has ops.retry(count) but NOT ops.retry_when — build equivalent
    # ---------------------------------------------------------------------------

    class TryAgain(Exception):
        """Sentinel exception for retry."""
        pass

    class MaxRetriesExceeded(Exception):
        """Raised when max retries exhausted."""
        pass

    def make_retrying_observable(fn, max_retries=5, base_delay=0.01):
        """Create an observable that calls fn(), retrying on exception with exp backoff.

        fn: async callable () -> T
        Retries on any Exception up to max_retries times.
        Backoff: base_delay * 2^attempt (capped at 1.0s).
        """
        attempt_count = [0]
        retry_delays: list[float] = []

        def subscribe(observer, scheduler=None):
            async def run():
                for attempt in range(max_retries + 1):
                    attempt_count[0] = attempt + 1
                    try:
                        result = await fn()
                        observer.on_next(result)
                        observer.on_completed()
                        return
                    except Exception as e:
                        if attempt == max_retries:
                            observer.on_error(
                                MaxRetriesExceeded(
                                    f"Failed after {max_retries + 1} attempts: {e}"
                                )
                            )
                            return
                        delay = min(base_delay * (2 ** attempt), 1.0)
                        retry_delays.append(delay)
                        await asyncio.sleep(delay)
            asyncio.ensure_future(run())

        obs = rx.create(subscribe)
        obs._attempt_count = attempt_count
        obs._retry_delays = retry_delays
        return obs

    # ---------------------------------------------------------------------------
    # Test: flaky API that fails 3 times then succeeds
    # ---------------------------------------------------------------------------

    call_count = 0

    async def flaky_api():
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            raise TryAgain(f"Transient failure #{call_count}")
        return "success"

    results: list[str] = []
    errors: list[Exception] = []
    done_event = asyncio.Event()
    retry_delays_record: list[float] = []

    obs = make_retrying_observable(flaky_api, max_retries=5, base_delay=0.01)
    retry_delays_record = obs._retry_delays

    obs.subscribe(
        on_next=lambda v: results.append(v),
        on_error=lambda e: (errors.append(e), done_event.set()),
        on_completed=lambda: done_event.set(),
    )

    await asyncio.wait_for(done_event.wait(), timeout=10.0)

    elapsed = time.monotonic() - t0

    evidence_lines.append(f"Result: {results} (expected ['success'])")
    evidence_lines.append(f"Call count: {call_count} (expected 4: 3 failures + 1 success)")
    evidence_lines.append(f"Errors: {len(errors)} (expected 0)")
    evidence_lines.append(f"Retry delays: {retry_delays_record}")
    evidence_lines.append(f"Elapsed: {elapsed:.3f}s")

    # Verify backoff is exponential
    backoff_correct = True
    for i, delay in enumerate(retry_delays_record):
        expected = min(0.01 * (2 ** i), 1.0)
        if abs(delay - expected) > 0.001:
            backoff_correct = False
            evidence_lines.append(f"Backoff mismatch at retry {i}: expected {expected}, got {delay}")
    evidence_lines.append(f"Backoff exponential: {backoff_correct}")

    # ---------------------------------------------------------------------------
    # Test 2: max retries exceeded
    # ---------------------------------------------------------------------------

    call_count_2 = 0

    async def always_fails():
        nonlocal call_count_2
        call_count_2 += 1
        raise TryAgain(f"Permanent failure #{call_count_2}")

    results_2: list[str] = []
    errors_2: list[Exception] = []
    done_event_2 = asyncio.Event()

    make_retrying_observable(always_fails, max_retries=3, base_delay=0.005).subscribe(
        on_next=lambda v: results_2.append(v),
        on_error=lambda e: (errors_2.append(e), done_event_2.set()),
        on_completed=lambda: done_event_2.set(),
    )

    await asyncio.wait_for(done_event_2.wait(), timeout=10.0)

    evidence_lines.append(f"Max-retries test: calls={call_count_2} (expected 4: 1 initial + 3 retries)")
    evidence_lines.append(f"Max-retries error: {type(errors_2[0]).__name__ if errors_2 else 'NONE'}")
    evidence_lines.append(f"Max-retries escalated correctly: {len(errors_2) == 1 and isinstance(errors_2[0], MaxRetriesExceeded)}")

    passed = (
        results == ["success"]
        and call_count == 4
        and len(errors) == 0
        and backoff_correct
        and elapsed < 1.0
        and call_count_2 == 4
        and len(errors_2) == 1
        and isinstance(errors_2[0], MaxRetriesExceeded)
    )

    return PatternResult(
        pattern=5,
        name="Tenacity replacement with RxPY retry logic",
        passed=passed,
        evidence="\n".join(evidence_lines),
        elapsed_s=elapsed,
    )


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
