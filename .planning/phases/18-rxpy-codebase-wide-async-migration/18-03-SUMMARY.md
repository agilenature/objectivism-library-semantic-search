---
phase: 18-rxpy-codebase-wide-async-migration
plan: 03
subsystem: extraction
tags: [rxpy, rx.interval, rx.timer, subscribe_awaitable, batch-api, mistral, polling, rate-limiting]

# Dependency graph
requires:
  - phase: 18-02
    provides: "_operators.py with subscribe_awaitable and make_retrying_observable"
provides:
  - "Extraction pipeline (batch_client, batch_orchestrator, orchestrator) migrated from asyncio primitives to RxPY"
  - "Polling loop in batch_client.py uses rx.interval + take_while + subscribe_awaitable"
  - "Rate limiting in orchestrator.py uses rx.timer-based pacing instead of AsyncLimiter"
affects: [18-04, 18-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "rx.interval polling: rx.interval(N).pipe(ops.map(defer(check)), ops.merge(1), ops.take_while(not_done, inclusive=True), ops.last())"
    - "rx.timer rate pacing: await subscribe_awaitable(rx.timer(delay_seconds)) replaces AsyncLimiter and asyncio.sleep"

key-files:
  created: []
  modified:
    - "src/objlib/extraction/batch_client.py"
    - "src/objlib/extraction/batch_orchestrator.py"
    - "src/objlib/extraction/orchestrator.py"

key-decisions:
  - "Polling loop migrated in batch_client.py (not batch_orchestrator.py) because that is where asyncio.sleep actually lived"
  - "AsyncLimiter replaced with rx.timer-based fixed-interval pacing (60 req/min = 1s delay per call)"
  - "No concat_map wave chaining needed: run_wave1 and run_production are separate CLI entry points, not sequential in same function"
  - "asyncio.Semaphore removed entirely: calls were sequential (for-loop), semaphore was a no-op"

patterns-established:
  - "rx.timer pacing: simple rx.timer(delay) via subscribe_awaitable replaces AsyncLimiter for sequential rate limiting"
  - "rx.interval polling: observable polling loop with take_while(inclusive=True) for terminal state detection"

# Metrics
duration: 7min
completed: 2026-02-27
---

# Phase 18 Plan 03: Tier 2 Extraction Pipeline Migration Summary

**Extraction pipeline migrated from asyncio.Semaphore/AsyncLimiter/asyncio.sleep to RxPY rx.interval polling and rx.timer rate pacing**

## Performance

- **Duration:** 7 min
- **Started:** 2026-02-27T17:48:45Z
- **Completed:** 2026-02-27T17:55:57Z
- **Tasks:** 5 (3 code tasks + 1 smoke test + 1 regression)
- **Files modified:** 3

## Accomplishments

- Migrated batch_client.py polling loop from while+asyncio.sleep to rx.interval+take_while+subscribe_awaitable
- Replaced AsyncLimiter (aiolimiter) with rx.timer-based pacing in orchestrator.py
- Replaced asyncio.sleep(backoff) with subscribe_awaitable(rx.timer(backoff)) for exponential backoff
- Removed asyncio.Semaphore (was guarding sequential calls -- effectively a no-op)
- All 476 tests pass, batch-extract smoke test exits cleanly (0 pending files)

## Task Commits

Each task was committed atomically:

1. **Task 1: Audit Tier 2 modules** - (no commit -- audit only, findings folded into Task 2)
2. **Task 2: Migrate batch_client.py + batch_orchestrator.py** - `48c0ad2` (refactor)
3. **Task 3: Migrate orchestrator.py** - `c1e9e1b` (refactor)
4. **Task 4: Batch-extract smoke test** - (no commit -- 0 pending files, exits cleanly)
5. **Task 5: Full test suite regression check** - (no commit -- 476 pass, no failures to fix)

## Files Created/Modified

- `src/objlib/extraction/batch_client.py` - Polling loop in wait_for_completion() replaced with rx.interval observable pipeline
- `src/objlib/extraction/batch_orchestrator.py` - Removed unused asyncio import (no asyncio primitives existed)
- `src/objlib/extraction/orchestrator.py` - asyncio.Semaphore, AsyncLimiter, asyncio.sleep all replaced with RxPY equivalents

## Decisions Made

1. **Polling loop lives in batch_client.py, not batch_orchestrator.py** -- The plan assumed batch_orchestrator.py had the polling loop, but batch_orchestrator.py only does sequential `await` calls. The actual `while + asyncio.sleep` polling lives in `batch_client.py:wait_for_completion()`. Migrated the correct file.

2. **No concat_map wave chaining** -- The plan expected wave 1/2 to be chained via concat_map. In reality, `run_wave1()` and `run_production()` are separate entry points invoked by different CLI commands. They are never called sequentially within the same function. No concat_map was needed.

3. **Semaphore removed (not replaced)** -- `asyncio.Semaphore(3)` was initialized in `__init__` and acquired in `_process_one()` and `run_production()`. But all calls are sequential (for-loops, no gather/create_task), so the semaphore never actually blocked. Removed it rather than replacing with an equivalent no-op.

4. **AsyncLimiter replaced with rx.timer pacing** -- `AsyncLimiter(60, 60)` (60 req/min leaky bucket) replaced with `await subscribe_awaitable(rx.timer(1.0))` (1-second fixed delay between calls). Slightly more conservative but correct for sequential processing.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Polling loop in wrong file**
- **Found during:** Task 1 (audit)
- **Issue:** Plan targeted batch_orchestrator.py for polling migration, but asyncio.sleep polling was in batch_client.py
- **Fix:** Migrated batch_client.py:wait_for_completion() instead
- **Files modified:** src/objlib/extraction/batch_client.py
- **Verification:** AST check confirms no asyncio.sleep in extraction/ code
- **Committed in:** 48c0ad2 (Task 2 commit)

**2. [Rule 3 - Blocking] No concat_map wave chaining needed**
- **Found during:** Task 1 (audit)
- **Issue:** Plan expected wave 1 -> wave 2 sequential chaining via concat_map, but run_wave1/run_production are separate CLI commands
- **Fix:** Skipped concat_map migration (no sequential dependency exists in code)
- **Files modified:** None
- **Verification:** Code review confirms separate entry points

---

**Total deviations:** 2 auto-fixed (2 blocking -- plan assumptions corrected)
**Impact on plan:** Both deviations were plan inaccuracies about code structure. Actual migration was smaller in scope but correct.

## Issues Encountered

None -- all migrations straightforward once correct migration targets identified.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

- Tier 2 (extraction pipeline) fully migrated to RxPY
- Plan 18-04 (Tier 1 upload pipeline) is UNBLOCKED
- All 476 tests pass
- Zero asyncio concurrency primitives remain in src/objlib/extraction/

## Self-Check: PASSED

- 18-03-SUMMARY.md: FOUND
- batch_client.py: FOUND
- batch_orchestrator.py: FOUND
- orchestrator.py: FOUND
- Commit 48c0ad2: FOUND
- Commit c1e9e1b: FOUND
- Tests: 476 passed

---
*Phase: 18-rxpy-codebase-wide-async-migration*
*Completed: 2026-02-27*
