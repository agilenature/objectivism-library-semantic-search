---
plan: "01"
phase: "18-rxpy-codebase-wide-async-migration"
status: complete
dependency_graph:
  requires:
    - "17-04 (Phase 17 complete)"
  provides:
    - "Go/No-Go gate for 18-02"
    - "Operator contracts for 18-02 through 18-04"
    - "RxPY 3.x API corrections (retry_when, flat_map max_concurrent)"
  affects:
    - "18-02 (Tier 3 migration)"
    - "18-03 (Tier 2 migration)"
    - "18-04 (Tier 1 migration)"
tech_stack:
  added:
    - "RxPY 3.2.0 (rx) — already installed from Phase 17"
    - "aiosqlite 0.22.1 — already installed"
  patterns:
    - "occ_transition: internal fn() retry, NOT outer re-subscribe"
    - "dynamic_semaphore: coroutine factories, NOT pre-started futures"
    - "shutdown_gate: two take_until operators at different pipeline points"
    - "make_retrying_observable: custom replacement for missing retry_when"
    - "Future-based subscription: replacement for .run() in async contexts"
    - "ops.map + ops.merge(max_concurrent=N): replacement for flat_map(max_concurrent=N)"
key_files:
  created:
    - "spike/phase18_spike/__init__.py"
    - "spike/phase18_spike/test_harness.py"
    - "spike/phase18_spike/design_doc.md"
  modified: []
decisions:
  - key: "RxPY 3.x API corrections"
    value: "retry_when, flat_map(max_concurrent), delay_when do not exist; custom operators needed"
  - key: "shutdown_gate is composition, not operator"
    value: "Two take_until operators at different pipeline points (before/after flat_map)"
  - key: "dynamic_semaphore requires factories"
    value: "Source must emit coroutine factories, not pre-started futures/tasks"
  - key: ".run() forbidden in async"
    value: "Future-based subscription pattern required for all async contexts"
metrics:
  duration_minutes: 25
  completed: "2026-02-27"
tags:
  - spike
  - rxpy
  - hostile-gate
  - operator-patterns
---

# Phase 18 Plan 01: RxPY Operator Pattern Spike Summary

Custom RxPY operators (occ_transition, dynamic_semaphore, make_retrying_observable) validated with HOSTILE evidence; shutdown_gate proven as two-signal composition pattern; 3 RxPY 3.x API corrections documented

## Objective

Validate the 5 highest-risk RxPY operator patterns before committing to full migration. HOSTILE distrust posture: positive affirmative evidence required for each pattern.

## Status: Complete

### Verdict: GO for Plan 18-02

All 5 patterns passed. Phase 18 migration may proceed.

### Tasks Completed

| # | Task | Commit |
|---|------|--------|
| 1 | Scaffold spike directory and shared helpers | `0383242` |
| 2 | Pattern 1: AsyncIOScheduler + aiosqlite SINGLETON | `c10252f` |
| 3 | Pattern 2: OCC retry observable | `365d08a` |
| 4 | Patterns 3, 4, 5: dynamic_semaphore, shutdown_gate, retry | `1502840` |
| 5 | Design doc + SUMMARY | (this commit) |

### Pattern Results

| Pattern | Name | Verdict | Key Evidence |
|---------|------|---------|-------------|
| 1 | AsyncIOScheduler + aiosqlite SINGLETON | PASS | 30 rows via 10 concurrent streams, 1 connection ID, 0 errors, retry-safe |
| 2 | OCC-guarded transition | PASS | 10 concurrent, counter=10, 18 retries resolved, 0 errors |
| 3 | dynamic_semaphore (BehaviorSubject) | PASS | Limit drop 10->2, post-drop max concurrency=2, no item loss |
| 4 | Two-signal shutdown_gate | PASS | 3/3 sub-tests: stop_accepting gates input, force_kill kills in-flight, sequence works |
| 5 | Tenacity replacement | PASS | 3 retries + success, exponential backoff (0.01, 0.02, 0.04), MaxRetriesExceeded escalation |

### Key Files

**Created:**
- `spike/phase18_spike/__init__.py` — Package marker
- `spike/phase18_spike/test_harness.py` — Full test harness with all 5 patterns + evidence collection
- `spike/phase18_spike/design_doc.md` — Operator contracts, pattern mapping table, production guidelines, API corrections

### Decisions Made

1. **RxPY 3.x API corrections:** `retry_when`, `flat_map(max_concurrent=N)`, and `delay_when` do not exist in RxPY 3.2.0. Custom operators fill the gap. This corrects assumptions in CONTEXT.md.
2. **shutdown_gate is a composition pattern:** Two `take_until` operators applied at DIFFERENT pipeline points (before/after `flat_map`), not a single operator. `gate_input(stop_accepting$)` before processing, `gate_output(force_kill$)` after processing.
3. **dynamic_semaphore requires coroutine factories:** Source MUST emit `Callable[[], Awaitable[T]]`, not pre-started `Future`/`Task` objects. Pre-started futures bypass concurrency control.
4. **`.run()` forbidden in async contexts:** Uses `threading.Event.wait()` which deadlocks the event loop. Future-based subscription pattern required for all Tier 1-3 migrations.
5. **Bounded concurrency idiom:** `ops.map(factory).pipe(ops.merge(max_concurrent=N))` replaces the non-existent `flat_map(max_concurrent=N)`.

### Deviations from Plan

**1. [Rule 1 - Bug] Pattern 3 test initially used pre-started futures**
- **Found during:** Task 4
- **Issue:** `asyncio.ensure_future(work_item(i))` creates the future before it reaches `dynamic_semaphore`, bypassing concurrency control entirely (all 20 items ran simultaneously).
- **Fix:** Changed source to emit coroutine factories (`lambda: work_item(i)`) instead of pre-started futures. Operator calls factory only when a concurrency slot is available.
- **Impact:** This is a critical production insight documented in the operator contract.

**2. [Rule 1 - Bug] Pattern 4 shutdown_gate could not be a single operator**
- **Found during:** Task 4
- **Issue:** A single `take_until(force_kill$)` applied before `flat_map` stops new items but does not terminate in-flight items (flat_map's inner observables continue). Applied after `flat_map`, it terminates in-flight but doesn't gate input separately.
- **Fix:** Redesigned as two-operator composition: `gate_input` before `flat_map`, `gate_output` after. Each is simply `ops.take_until(signal)`.
- **Impact:** shutdown_gate contract in CONTEXT.md updated in design_doc.md.

**3. [Rule 3 - Blocking] RxPY 3.x missing retry_when operator**
- **Found during:** Task 4
- **Issue:** Plan specified `ops.retry_when(handler)` which does not exist in RxPY 3.2.0. Only `ops.retry(count)` is available.
- **Fix:** Implemented custom `make_retrying_observable(fn, max_retries, base_delay)` operator that handles retry logic internally (async loop with exponential backoff).
- **Impact:** All Tier 1-3 plans must use custom retry operator instead of `retry_when`.

### Issues Encountered

None beyond the deviations documented above. All issues were resolved inline during implementation.

### Gate Status

**18-02: UNBLOCKED.** All 5 patterns validated. Operator contracts finalized in design_doc.md.

### Verification Checklist

1. `python spike/phase18_spike/test_harness.py` exits 0 with all 5 patterns PASSED -- **VERIFIED**
2. `spike/phase18_spike/design_doc.md` contains operator contracts for occ_transition, occ_transition_async, upload_with_retry, shutdown_gate, dynamic_semaphore -- **VERIFIED**
3. design_doc.md addresses all 10 pattern mappings from CONTEXT.md table -- **VERIFIED**
4. Pattern 1 validates singleton connection (Q5) -- **VERIFIED**
5. Pattern 3 validates named dynamic_semaphore operator (Q2) -- **VERIFIED**
6. Pattern 4 validates TWO-signal shutdown pattern (Q4) -- **VERIFIED**
7. design_doc.md Section 4 prescribes `ops.map + ops.merge(max_concurrent=N)` -- **VERIFIED**
8. design_doc.md Section 4 prescribes Future-based subscription pattern -- **VERIFIED**
9. 18-01-SUMMARY.md contains GO verdict -- **VERIFIED** (this file)
10. No production code modified (spike only) -- **VERIFIED**
11. All existing tests still pass: 470/470 -- **VERIFIED**
