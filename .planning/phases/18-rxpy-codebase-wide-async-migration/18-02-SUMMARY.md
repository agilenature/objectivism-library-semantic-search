---
phase: 18-rxpy-codebase-wide-async-migration
plan: 02
subsystem: async, search, services
tags: [rxpy, observable, asyncio, retry, executor, migration]

# Dependency graph
requires:
  - phase: 18-01
    provides: RxPY operator contracts (make_retrying_observable, subscribe_awaitable, Future-based subscription)
provides:
  - Shared RxPY operator module (_operators.py) with make_retrying_observable and subscribe_awaitable
  - Tier 3 modules (services/search, services/library, search/client) migrated from asyncio.to_thread/tenacity to RxPY
  - Audit confirming sync/orchestrator.py has no asyncio primitives to migrate
affects: [18-03, 18-04, 18-05]

# Tech tracking
tech-stack:
  added: []
  patterns: [make_retrying_observable replaces tenacity @retry, _run_in_executor helper for uniform RxPY executor pattern]

key-files:
  created:
    - src/objlib/upload/_operators.py
    - tests/test_operators.py
  modified:
    - src/objlib/search/client.py
    - src/objlib/services/search.py
    - src/objlib/services/library.py

key-decisions:
  - "query_with_retry converted from sync to async -- caller updated to await directly instead of asyncio.to_thread"
  - "LibraryService._run_in_executor helper DRYs 7 identical asyncio.to_thread -> RxPY patterns"
  - "sync/orchestrator.py skipped -- audit found zero asyncio primitives"

patterns-established:
  - "make_retrying_observable(fn, max_retries, base_delay): exponential backoff retry via RxPY observable"
  - "subscribe_awaitable(obs): Future-based subscription for async contexts (avoids obs.run() deadlock)"
  - "_run_in_executor(fn): uniform helper for sync-to-async via RxPY observable + executor"

# Metrics
duration: 7min
completed: 2026-02-27
---

# Phase 18 Plan 02: Tier 3 Migration -- Services & Search Summary

**Migrated 12 asyncio.to_thread/tenacity calls across 3 Tier 3 modules to RxPY observables with shared _operators.py**

## Performance

- **Duration:** 7 min
- **Started:** 2026-02-27T17:38:35Z
- **Completed:** 2026-02-27T17:45:53Z
- **Tasks:** 6
- **Files modified:** 5 (3 migrated + 2 created)

## Accomplishments
- Created shared `_operators.py` with `make_retrying_observable` and `subscribe_awaitable` (6 tests)
- Replaced tenacity `@retry` in `search/client.py` with RxPY retry observable (async, executor-backed)
- Migrated 10 `asyncio.to_thread()` calls across `services/search.py` and `services/library.py` to RxPY executor pattern
- Confirmed `sync/orchestrator.py` requires no migration (no asyncio primitives)
- Full 476-test regression suite passes

## Task Commits

Each task was committed atomically:

1. **Task 1: Audit Tier 3 modules** - `16e298d` (docs -- migration map in commit message)
2. **Task 2: Create _operators.py** - `49e41c3` (feat -- make_retrying_observable + subscribe_awaitable + 6 tests)
3. **Task 3: Migrate search/client.py** - `be87a59` (refactor -- tenacity @retry -> make_retrying_observable)
4. **Task 4: Migrate services/search.py and library.py** - `5e9a77f` (refactor -- 10x asyncio.to_thread -> RxPY executor)
5. **Task 5: Migrate sync/orchestrator.py** - `ad0283e` (docs -- no migration needed)
6. **Task 6: Full regression check** - `555caa6` (test -- 476/476 pass)

## Files Created/Modified
- `src/objlib/upload/_operators.py` - Shared RxPY operators: make_retrying_observable, subscribe_awaitable
- `tests/test_operators.py` - 6 tests covering retry success, transient error, exhaustion, timing, subscription
- `src/objlib/search/client.py` - Removed tenacity, query_with_retry now async with RxPY retry observable
- `src/objlib/services/search.py` - 4 asyncio.to_thread calls replaced with RxPY executor pattern
- `src/objlib/services/library.py` - 7 asyncio.to_thread calls replaced with _run_in_executor helper

## Decisions Made
- **query_with_retry made async**: The sync tenacity @retry was wrapping a sync Gemini API call. Converting to async required updating the caller in services/search.py (Rule 3 auto-fix). The sync query() method remains sync for backward compatibility.
- **_run_in_executor helper**: LibraryService had 7 identical asyncio.to_thread patterns. A private helper method DRYs the RxPY boilerplate without changing public API signatures.
- **sync/orchestrator.py skipped**: Audit confirmed zero asyncio primitives (only async/await for client.* calls). No migration needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated services/search.py call site in Task 3**
- **Found during:** Task 3 (search/client.py migration)
- **Issue:** Making query_with_retry async meant the caller in services/search.py could no longer use asyncio.to_thread() to call it
- **Fix:** Changed `asyncio.to_thread(query_with_retry, ...)` to `await query_with_retry(...)` directly
- **Files modified:** src/objlib/services/search.py
- **Verification:** 27 search tests pass
- **Committed in:** be87a59 (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary consequence of making query_with_retry async. No scope creep.

## Issues Encountered
- Plan assumed tenacity.AsyncRetrying would be found; actual code used sync @retry. Migration pattern adjusted accordingly (sync query() stays sync, wrapped in run_in_executor within async retry loop).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Tier 3 migration complete, 18-03 (Tier 2: Upload Pipeline) unblocked
- `_operators.py` shared module available for Tier 2 and Tier 1 migrations
- services/session.py still has asyncio.to_thread() calls (not in Tier 3 scope, may need migration in later plans)

## Self-Check: PASSED
- All 5 created/modified files exist on disk
- All 6 task commits found in git log
- 476/476 tests pass

---
*Phase: 18-rxpy-codebase-wide-async-migration*
*Completed: 2026-02-27*
