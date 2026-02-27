---
phase: 18-rxpy-codebase-wide-async-migration
plan: 04
subsystem: upload
tags: [rxpy, asyncio, semaphore, gather, tenacity, observable, merge, timeout, shutdown]

requires:
  - phase: 18-03
    provides: "Tier 2 extraction pipeline migrated; regression-free baseline"
  - phase: 18-01
    provides: "Spike-validated operator contracts (Q2-Q4)"
provides:
  - "Tier 1 upload pipeline fully migrated from asyncio to RxPY"
  - "5 custom operators in _operators.py (occ_transition, upload_with_retry, shutdown_gate, dynamic_semaphore)"
  - "Zero tenacity imports remaining across entire src/"
  - "Two-signal shutdown (stop_accepting + force_kill) via RxPY Subject"
affects: [18-05-post-migration-validation]

tech-stack:
  added: [rx.subject.Subject, rx.subject.BehaviorSubject]
  patterns: ["ops.map(factory) + ops.merge(max_concurrent=N) for bounded concurrency", "subscribe_awaitable for async/Observable bridge", "Two-signal Subject shutdown (Q4 contract)", "upload_with_retry for 429-specific retry with full-jitter backoff"]

key-files:
  created: []
  modified:
    - src/objlib/upload/_operators.py
    - src/objlib/upload/client.py
    - src/objlib/upload/orchestrator.py
    - src/objlib/upload/recovery.py

key-decisions:
  - "state.py has no asyncio primitives -- OCC is pure SQL WHERE version=?, no migration needed"
  - "asyncio.sleep retained inside coroutine factories (stagger, cooldown) -- not a coordination primitive"
  - "asyncio.create_task retained inside rx.from_future wrappers -- necessary for Observable bridge"
  - "ops.timeout raises Exception('Timeout') not asyncio.TimeoutError -- handler checks str(exc)"
  - "Dynamic semaphore resize uses self._max_concurrent_uploads mutation (simpler than BehaviorSubject for this use case)"

patterns-established:
  - "ops.map(factory).pipe(ops.merge(max_concurrent=N)) replaces asyncio.Semaphore + asyncio.gather"
  - "subscribe_awaitable bridges Observable results into async contexts"
  - "upload_with_retry encapsulates 429 retry with full-jitter exponential backoff"
  - "Two-signal Subject shutdown: stop_accepting gates input, force_kill terminates active chains"

duration: 17min
completed: 2026-02-27
---

# Phase 18 Plan 04: Tier 1 Migration -- FSM Upload Pipeline Summary

**Upload pipeline (orchestrator, client, recovery) migrated from asyncio.Semaphore+gather+Event+tenacity to RxPY ops.merge+Subject+make_retrying_observable with 476 tests green and check_stability STABLE**

## Performance

- **Duration:** 17 min
- **Started:** 2026-02-27T18:00:52Z
- **Completed:** 2026-02-27T18:18:32Z
- **Tasks:** 7
- **Files modified:** 4

## Accomplishments

- All asyncio coordination primitives (Semaphore, gather, Event) replaced across 3 orchestrator classes
- tenacity AsyncRetrying removed from client.py -- zero tenacity imports remain in src/
- 5 custom RxPY operators added to _operators.py (occ_transition, occ_transition_async, upload_with_retry, shutdown_gate, dynamic_semaphore)
- Two-signal shutdown system (stop_accepting + force_kill) replaces single asyncio.Event
- 476 tests pass, check_stability STABLE (7/7 assertions, 20/20 files retrievable), store-sync 0 orphans

## Task Commits

Each task was committed atomically:

1. **Tasks 1+2: Audit + _operators.py** - `20c2657` (feat: add 5 custom operators)
2. **Task 3: client.py migration** - `18596e9` (refactor: tenacity to make_retrying_observable)
3. **Task 4: recovery.py migration** - `5cdad5d` (refactor: wait_for to ops.timeout)
4. **Task 5: orchestrator.py migration** - `868c34d` (refactor: Semaphore+gather to RxPY merge)
5. **Task 6: Regression check** - `55efbc4` (test: 476 tests pass)
6. **Task 7: FSM behavioral gate** - `59a35f3` (test: check_stability STABLE)

## Files Modified

- `src/objlib/upload/_operators.py` -- Added 5 operators: occ_transition, occ_transition_async, upload_with_retry, shutdown_gate, dynamic_semaphore (288 lines added)
- `src/objlib/upload/client.py` -- Replaced AsyncRetrying+TryAgain with make_retrying_observable in wait_for_active() and poll_operation()
- `src/objlib/upload/recovery.py` -- Replaced asyncio.wait_for with rx.from_future+ops.timeout in RecoveryManager.run() and _recover_pending_operations()
- `src/objlib/upload/orchestrator.py` -- Replaced all asyncio.Semaphore+gather with ops.map+ops.merge(max_concurrent=N); asyncio.Event with Subject shutdown; 429 retry loop with upload_with_retry

## Pattern Replacements by File

### client.py (2 sites migrated)
| Before | After | Function |
|--------|-------|----------|
| `AsyncRetrying` + `retry_if_result` | `make_retrying_observable` + `_StillProcessing` sentinel | `wait_for_active()` |
| `AsyncRetrying` + `TryAgain` | `make_retrying_observable` + `_OperationNotDone` sentinel | `poll_operation()` |

### recovery.py (2 sites migrated)
| Before | After | Function |
|--------|-------|----------|
| `asyncio.wait_for(coro, timeout)` | `rx.from_future(ensure_future(coro)).pipe(ops.timeout(timeout))` | `RecoveryManager.run()` |
| `asyncio.wait_for(coro, timeout=65)` | `rx.from_future(ensure_future(coro)).pipe(ops.timeout(65))` | `_recover_pending_operations()` |

### orchestrator.py (19 sites migrated)
| Before | After | Count |
|--------|-------|-------|
| `asyncio.Semaphore(N)` | `self._max_concurrent_uploads / _polls` | 3 |
| `asyncio.gather(*tasks)` | `ops.map(factory).pipe(ops.merge(max_concurrent=N), ops.to_list())` | 8 |
| `asyncio.Event()` | `Subject()` (stop_accepting + force_kill) | 1 |
| `asyncio.Event.is_set()` | `self._shutdown_requested` bool | 7 |
| `asyncio.sleep(jittered)` 429 retry | `upload_with_retry` operator | 1 |

### state.py (0 sites -- no migration needed)
OCC guard is pure SQL `WHERE version = ?` with immediate `OCCConflictError` raise. No asyncio primitives present.

## Custom Operators Added to _operators.py

| Operator | Contract | Replaces |
|----------|----------|----------|
| `occ_transition(fn, max_attempts, base_delay)` | Q3: internal retry on OCCConflictError, NOT outer re-subscribe | Manual OCC retry loops |
| `occ_transition_async(fn, max_attempts, base_delay)` | Async wrapper via Future-based subscription | `.run()` in async context |
| `upload_with_retry(file_record, upload_fn, max_attempts)` | 429-specific retry, full-jitter exponential backoff | In-place for-loop retry |
| `shutdown_gate(source, stop_accepting, force_kill)` | Q4: two-signal system, stop_accepting gates input, force_kill terminates | `asyncio.Event.is_set()` polling |
| `dynamic_semaphore(limit_subject)` | Q2: BehaviorSubject-driven concurrency, in-flight items complete on decrease | `asyncio.Semaphore._value` mutation |

## Behavioral Gate Evidence

### check_stability.py (alternative to fsm-upload --limit 20)

No UNTRACKED files with approved metadata available (136 untracked files lack AI metadata approval / 8 primary topics). Used check_stability as alternative gate:

```
Passed:   7
Failed:   0
Warnings: 0
Elapsed:  153.7s
VERDICT: STABLE
```

### store-sync

```
Canonical uploaded file IDs in DB: 1749
Canonical store doc IDs in DB: 1749
Total store documents: 1749
Canonical documents: 1749
Orphaned documents: 0
Store is clean -- nothing to purge.
```

### DB State

```
indexed|1749
untracked|136
```

Pre-existing indexed count (1749) unchanged from pre-Phase 18.

### Remaining tenacity usage

```
grep -rn "from tenacity|import tenacity" src/ --include="*.py" -> 0 results
```

Zero tenacity imports remain across entire `src/`.

## Decisions Made

1. **state.py skipped** -- has no asyncio primitives. OCC is pure SQL WHERE version=? with immediate raise. The plan expected OCC retry loops but they don't exist in state.py; retry responsibility lies with callers.
2. **asyncio.sleep retained** -- inside coroutine factories for stagger delays (1s between file launches) and retry cooldowns (30s). These are not coordination primitives; they execute inside Observable-wrapped coroutines.
3. **asyncio.create_task retained** -- needed by `rx.from_future(asyncio.create_task(...))` pattern for bridging coroutines into observables.
4. **Exception("Timeout") handling** -- RxPY ops.timeout raises plain `Exception("Timeout")` not `asyncio.TimeoutError`. Handler checks `str(exc) == "Timeout"` in addition to isinstance checks.
5. **Dynamic concurrency** -- Uses `self._max_concurrent_uploads` mutation (simpler approach) rather than BehaviorSubject for the UploadOrchestrator class, since the concurrency is updated per-batch not mid-stream.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] RxPY ops.timeout exception type mismatch**
- **Found during:** Task 4 (recovery.py migration)
- **Issue:** ops.timeout raises `Exception("Timeout")`, not `asyncio.TimeoutError`. Test `test_recovery_timeout_raises` failed because the except clause checked `type(exc).__name__` which was just "Exception".
- **Fix:** Changed timeout detection to check `str(exc) == "Timeout"` in addition to isinstance checks.
- **Files modified:** `src/objlib/upload/recovery.py`
- **Verification:** All 5 recovery tests pass
- **Committed in:** `5cdad5d`

**2. [Deviation] state.py migration skipped -- no asyncio primitives exist**
- **Found during:** Task 1 (audit)
- **Issue:** Plan expected OCC retry loops (`while True: try: transition(); break; except OCCConflictError: await sleep(backoff)`) but state.py has pure SQL OCC with immediate raise. No asyncio primitives to replace.
- **Impact:** None -- operators still created in _operators.py for use by orchestrator.py callers if needed.
- **Committed in:** `20c2657` (documented in commit message)

---

**Total deviations:** 1 auto-fixed (Exception type bug), 1 plan mismatch (state.py already clean)
**Impact on plan:** Bug fix was necessary for test correctness. state.py skip is harmless -- module was already async-primitive-free.

## Issues Encountered

None beyond the ops.timeout exception type mismatch documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **18-05 UNBLOCKED**: All Tier 1 modules migrated, 476 tests pass, behavioral gate passed
- Pre-existing corpus (1749 indexed files) confirmed untouched
- Zero tenacity imports remaining -- 18-05 can safely remove tenacity from dependencies
- All custom operators documented with contracts in _operators.py

---
*Phase: 18-rxpy-codebase-wide-async-migration*
*Completed: 2026-02-27*
