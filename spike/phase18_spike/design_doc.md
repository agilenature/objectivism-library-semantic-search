# Phase 18 RxPY Operator Pattern Spike — Design Document

**Date:** 2026-02-27
**Phase:** 18 — RxPY Codebase-Wide Async Migration
**Plan:** 18-01 (Spike)
**Status:** Complete

---

## Section 1: Go/No-Go Verdict

### GO for Plan 18-02

All 5 high-risk patterns validated with positive affirmative evidence (HOSTILE posture).
No hidden complexity discovered. All operators work correctly with:
- Correct state mutations (DB rows, counters)
- Proper error propagation
- Clean completion (no dangling subscriptions)
- Correct behavior under concurrent load

The Phase 18 migration may proceed.

---

## Section 2: Pattern Mapping Table (Confirmed)

All 10 patterns from CONTEXT.md, updated with spike findings.

| # | Pattern | Current Implementation | Confirmed RxPY Target | Risk | Spike Evidence |
|---|---------|----------------------|----------------------|------|---------------|
| 1 | `asyncio.gather` fan-out | List of coroutines | `ops.map(factory).pipe(ops.merge(max_concurrent=N))` | Low | N/A (covered by Pattern 3 operator) |
| 2 | `asyncio.Semaphore` | Context manager | `ops.map(factory).pipe(ops.merge(max_concurrent=N))` for STATIC limit; `dynamic_semaphore(limit$)` for DYNAMIC limit | Low/High | Pattern 3 PASS: dynamic limit drop 10->2, no item loss |
| 3 | `asyncio.to_thread` | Thread wrapper | Future-based subscription (see Section 4 Tier 3) | Low | Not spiked (low risk, standard pattern) |
| 4 | Tenacity `AsyncRetrying` | `with attempt:` + `TryAgain` | `make_retrying_observable(fn, max_retries, base_delay)` custom operator | Low | Pattern 5 PASS: 3 retries + success, exponential backoff verified, MaxRetriesExceeded escalation |
| 5 | `asyncio.sleep` (stagger) | `await sleep(N)` | `ops.delay(N)` or `rx.zip(source, rx.interval(period))` | Medium | Not spiked (medium risk, standard operator) |
| 6 | `asyncio.Event` (shutdown) | `event.is_set()` polling | Two-signal pattern: `gate_input(stop_accepting$)` + `gate_output(force_kill$)` | Medium | Pattern 4 PASS: all 3 sub-tests (stop, kill, sequence) |
| 7 | OCC conflict retry | Manual check + raise `OCCConflictError` | `occ_transition(fn, max_attempts, base_delay)` custom operator | High | Pattern 2 PASS: 10 concurrent, 18 retries resolved, counter=10 |
| 8 | Dynamic semaphore resize | Mutate `Semaphore._value` | `dynamic_semaphore(limit$: BehaviorSubject[int])` custom operator | High | Pattern 3 PASS: limit drop 10->2, post-drop max concurrency=2 |
| 9 | Polling loop (batch job) | `asyncio.sleep` + `while not done:` | `rx.interval(period).pipe(ops.take_while(not_done))` | Medium | Not spiked (standard operator composition) |
| 10 | `asyncio.wait_for` timeout | `await asyncio.wait_for(coro, timeout=N)` | `.pipe(ops.timeout(N))` | Low | Not spiked (low risk, standard operator) |

**Key corrections from spike:**
- Pattern 1/2: `flat_map(max_concurrent=N)` does NOT exist in RxPY 3.x. Correct idiom: `ops.map(factory).pipe(ops.merge(max_concurrent=N))`.
- Pattern 4: `retry_when` does NOT exist in RxPY 3.x. Only `ops.retry(count)` exists. Custom `make_retrying_observable` operator needed.
- Pattern 6: Single `shutdown$` Subject is insufficient. Two-signal pattern with signals applied at DIFFERENT pipeline points required.

---

## Section 3: Operator Contracts

### 3.1 `occ_transition(fn, max_attempts=5, base_delay=0.01)`

**Purpose:** Retry a coroutine factory on OCCConflictError with exponential backoff + jitter.

```
Input:      fn: async () -> T (coroutine factory; reads fresh DB state on each call)
Retry:      On OCCConflictError, call fn() again after delay
Backoff:    min(base_delay * 2^attempt + random(0, 0.005), 1.0)
Terminal:   Raises OCCConflictError after max_attempts exhausted
Returns:    Observable<T> — emits fn()'s return value on success, then completes
Side-effect: fn() is called up to max_attempts times; each call may write to DB
Contract:   fn() is retried INTERNALLY. Outer observable is NOT re-subscribed.
```

**Location:** `src/objlib/upload/_operators.py` (18-04)

### 3.2 `occ_transition_async(fn, max_attempts=5, base_delay=0.01)`

**Purpose:** Async wrapper for `occ_transition` — for use in `async def` methods that cannot use `.run()`.

```
Input:      Same as occ_transition
Returns:    Awaitable<T> — resolves to fn()'s return value on success
Pattern:    Creates a Future, subscribes occ_transition observable to resolve it
Usage:      result = await occ_transition_async(fn, max_attempts=5)
Contract:   .run() MUST NOT be used inside async contexts (blocks event loop)
```

**Implementation sketch:**
```python
async def occ_transition_async(fn, max_attempts=5, base_delay=0.01):
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    occ_transition(fn, max_attempts, base_delay).subscribe(
        on_next=lambda v: future.set_result(v) if not future.done() else None,
        on_error=lambda e: future.set_exception(e) if not future.done() else None,
    )
    return await future
```

**Location:** `src/objlib/upload/_operators.py` (18-04), co-located with `occ_transition`

### 3.3 `upload_with_retry(fn, max_retries=5, base_delay=1.0, max_delay=60.0)`

**Purpose:** Retry an upload/API coroutine factory on transient errors with full-jitter exponential backoff.

```
Input:      fn: async () -> T (coroutine factory)
Retry:      On any Exception, call fn() again after delay
Backoff:    random.uniform(0, min(max_delay, base_delay * 2^attempt))  [full jitter]
Terminal:   Raises MaxRetriesExceeded after max_retries+1 total attempts
Returns:    Observable<T> — emits fn()'s return value on success
```

**Backoff formula matches tenacity's observed range:** base=1.0s, cap=60s, max_attempts=5.

**Location:** `src/objlib/upload/_operators.py` (18-04)

### 3.4 `shutdown_gate` — Two-Signal Pattern

**Purpose:** Two-signal graceful + forced shutdown for pipeline lifecycle management.

**Architectural finding from spike:** The two signals must be applied at DIFFERENT POINTS in the pipeline. This is NOT a single operator — it is a composition pattern using two `take_until` operators.

```
Signals:
  stop_accepting$: Subject()  — gates input; no new items enter pipeline
  force_kill$: Subject()      — terminates active chains (immediate stop)

Usage:
  source.pipe(
      gate_input(stop_accepting$),       # take_until BEFORE flat_map
      ops.flat_map(process_fn),           # processing happens here
      gate_output(force_kill$),           # take_until AFTER flat_map
  )

  gate_input = lambda s: ops.take_until(s)   # gates source emission
  gate_output = lambda s: ops.take_until(s)  # kills in-flight processing

Shutdown sequences:
  Normal:    fire stop_accepting$ -> await drain -> fire force_kill$
  Emergency: fire both simultaneously
```

**Key insight:** `stop_accepting$` applied BEFORE `flat_map` prevents new items from entering processing but allows in-flight items to complete. `force_kill$` applied AFTER `flat_map` terminates the entire chain including in-flight items.

**Location:** Inline composition in `src/objlib/upload/orchestrator.py` (18-04), not a separate operator file

### 3.5 `dynamic_semaphore(limit$: BehaviorSubject[int])`

**Purpose:** Custom operator controlling concurrency dynamically via a BehaviorSubject-driven limit.

```
Input:      Source emitting Callable[[], Awaitable[T]] (coroutine factories)
            MUST be factories, NOT pre-started futures/tasks
Limit:      limit$: BehaviorSubject[int] — current concurrency limit
Behavior:   Maintains internal buffer of pending factories
            Only starts work (calls factory) when active_count < current_limit
            On limit decrease: in-flight items complete normally (NO cancellation)
            New items blocked until active_count drops below new limit
            On limit increase: immediately dispatches buffered items up to new limit
Buffer:     Unbounded (source is bounded — all items already known)
Returns:    Observable<T> — emits results as items complete
Contract:   No item loss, no deadlock, no cancellation of in-flight work
```

**Location:** `src/objlib/upload/_operators.py` (18-04)

---

## Section 4: Production Implementation Guidelines

### Tier 3: `asyncio.to_thread` Replacement (18-02)

**DO NOT use `.run()` inside `async def` methods.**

`.run()` calls `threading.Event.wait()` which blocks the calling thread. Inside an `async def`, this permanently blocks the asyncio event loop — coroutines scheduled with `asyncio.ensure_future()` never execute. `.run()` must only be used at the top-level (outside any running event loop).

**Correct pattern — Future-based subscription:**
```python
async def some_service_method(self, *args):
    result_future = asyncio.get_running_loop().create_future()
    rx.from_callable(
        lambda: fn(*args),
        scheduler=NewThreadScheduler()
    ).subscribe(
        on_next=lambda v: result_future.set_result(v) if not result_future.done() else None,
        on_error=lambda e: result_future.set_exception(e) if not result_future.done() else None,
    )
    return await result_future
```

This replaces `asyncio.to_thread(fn, *args)` with an equivalent that routes through RxPY's scheduler system.

### Tier 2: `asyncio.Semaphore` + `gather` Replacement (18-03)

**Use `ops.map(...).pipe(ops.merge(max_concurrent=N))` — NOT `ops.flat_map(mapper, max_concurrent=N)`.**

RxPY 3.x `ops.flat_map()` does NOT accept a `max_concurrent` parameter. The correct bounded concurrency pattern:

```python
source.pipe(
    ops.map(lambda item: rx.from_future(asyncio.ensure_future(process(item)))),
    ops.merge(max_concurrent=N),
)
```

`ops.merge(max_concurrent=N)` is a pipeable operator that subscribes to at most N inner observables concurrently.

**`AsyncLimiter` replacement:** `ops.throttle_with_timeout(period)` for rate limiting.

**Async coroutines inside the pipeline:** Use `asyncio.ensure_future(coro)` + `rx.from_future()`, NOT `asyncio.run(coro)` (which raises RuntimeError when an event loop is already running).

### Tier 1: Upload Pipeline (18-04)

All custom operators from Section 3:

- **`dynamic_semaphore(limit$)`** (Pattern 3): Replaces `asyncio.Semaphore` with dynamic resize capability. Source MUST emit coroutine factories, not pre-started tasks.
- **Two-signal `shutdown_gate`** (Pattern 4): Replaces `asyncio.Event` shutdown. `gate_input` before processing, `gate_output` after processing.
- **`occ_transition` / `occ_transition_async`** (Pattern 2): Replaces manual OCC retry loops. Use `await occ_transition_async(...)` in `state.py` async methods (NOT `.run()`).
- **`make_retrying_observable` / `upload_with_retry`** (Pattern 5): Replaces `tenacity.AsyncRetrying`. Custom operator needed because RxPY 3.x lacks `retry_when`.

---

## Section 5: Risks and Mitigations

### Risk 1: RxPY 3.x Missing Operators

**Finding:** Several operators mentioned in CONTEXT.md do not exist in RxPY 3.2.0:
- `retry_when` — only `retry(count)` exists (no error-conditioned retry)
- `flat_map(max_concurrent=N)` — `flat_map` takes no concurrency param
- `delay_when` — not available

**Mitigation:** Custom operators fill the gap. `make_retrying_observable` replaces `retry_when`, `ops.map + ops.merge(max_concurrent=N)` replaces `flat_map(max_concurrent=N)`. All spike-validated.

### Risk 2: dynamic_semaphore Requires Coroutine Factories

**Finding:** The `dynamic_semaphore` operator MUST receive coroutine factories (callables returning awaitables), not pre-started futures/tasks. If a future is created via `asyncio.ensure_future()` before reaching the operator, the work starts immediately and concurrency control is bypassed entirely.

**Mitigation:** Document this contract clearly. In production, `ops.map(lambda item: lambda: process(item))` creates the factory; `dynamic_semaphore` calls it when a slot is available.

### Risk 3: Two-Signal Shutdown is a Composition Pattern, Not a Single Operator

**Finding:** The shutdown_gate cannot be implemented as a single pipeable operator because the two signals must be applied at different points in the pipeline. `stop_accepting$` must be `take_until` BEFORE `flat_map` (to gate input), while `force_kill$` must be `take_until` AFTER `flat_map` (to terminate in-flight work).

**Mitigation:** Document as a composition pattern. In 18-04, the orchestrator pipeline applies both `take_until` operators explicitly at the correct positions.

### Risk 4: `.run()` Deadlock in Async Contexts

**Finding:** RxPY's `.run()` method uses `threading.Event.wait()` which blocks the calling thread. Inside an `async def` (where an event loop is running), this deadlocks the entire application.

**Mitigation:** Use Future-based subscription pattern (Section 4, Tier 3). `occ_transition_async` wrapper provides the correct async interface.

### Risk 5: BehaviorSubject Initial Value Triggers Dispatch

**Finding:** When subscribing to a BehaviorSubject, the initial value fires immediately. In `dynamic_semaphore`, this triggers an initial dispatch that may race with items arriving from the source. In practice this is benign (items arrive synchronously before the event loop yields), but should be documented.

**Mitigation:** No code change needed. The dispatch lock serializes access. Documented in operator contract.

---

## Appendix: RxPY 3.2.0 API Corrections

These corrections override assumptions in CONTEXT.md and CLARIFICATIONS-ANSWERED.md:

| Assumed API | Actual API in RxPY 3.2.0 | Correction |
|---|---|---|
| `ops.retry_when(handler)` | Does not exist | Custom `make_retrying_observable` operator |
| `ops.flat_map(fn, max_concurrent=N)` | `flat_map` has no `max_concurrent` param | `ops.map(fn).pipe(ops.merge(max_concurrent=N))` |
| `ops.delay_when(handler)` | Does not exist | `ops.delay(N)` for fixed delay; custom for dynamic |
| `shutdown_gate(obs, stop$, kill$)` | Single operator insufficient | Two `take_until` operators at different pipeline points |
