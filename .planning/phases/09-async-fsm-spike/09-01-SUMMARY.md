---
phase: 09-async-fsm-spike
plan: 01
subsystem: database, infra
tags: [python-statemachine, aiosqlite, fsm, async, occ, concurrent, sqlite, wal]

# Dependency graph
requires:
  - phase: 08-store-migration-precondition
    provides: "V9 schema with gemini_state column and store migration"
provides:
  - "FileStateMachineProtocol interface for adapter swapping"
  - "StateMachineAdapter wrapping python-statemachine 2.6.0 with async guards"
  - "HandRolledAdapter as documented fallback (not needed)"
  - "Per-transition aiosqlite connection factory with OCC, BEGIN IMMEDIATE, retry"
  - "EventCollector for structured JSON event log capture"
  - "DB invariant checker (reusable for Phase 10+)"
  - "Affirmative evidence: all 4 criteria pass under adversarial concurrent load"
affects: [09-02, 10-transition-atomicity, 12-fsm-upload]

# Tech tracking
tech-stack:
  added: [python-statemachine 2.6.0]
  patterns: [ephemeral FSM per transition, per-file asyncio.Lock + DB OCC, per-transition aiosqlite connection, structured JSON event log]

key-files:
  created:
    - spike/phase9_spike/protocol.py
    - spike/phase9_spike/adapters/statemachine_adapter.py
    - spike/phase9_spike/adapters/handrolled_adapter.py
    - spike/phase9_spike/db.py
    - spike/phase9_spike/states.py
    - spike/phase9_spike/exceptions.py
    - spike/phase9_spike/event_log.py
    - spike/phase9_spike/harness.py
    - spike/phase9_spike/tests/test_async_guards.py
    - spike/phase9_spike/tests/test_concurrent_transitions.py
    - spike/phase9_spike/tests/test_error_injection.py
    - spike/phase9_spike/tests/test_db_invariants.py
    - spike/phase9_spike/tests/test_leak_check.py
    - spike/phase9_spike/tests/conftest.py
  modified: []

key-decisions:
  - "python-statemachine 2.6.0 PASSES async guard binary test -- library path confirmed, no pivot needed"
  - "on_enter_state callback parameters must be optional (defaults=None) because activate_initial_state() fires without trigger kwargs"
  - "source.value is None during initial state activation -- use this as the skip sentinel for DB writes"

patterns-established:
  - "Ephemeral FSM: create adapter from DB state, use for ONE transition, discard"
  - "Per-transition connection: each callback opens async with aiosqlite.connect(db_path)"
  - "OCC UPDATE: WHERE file_path=? AND gemini_state=? AND version=? with rowcount check"
  - "EventCollector: in-memory structured JSON log for test assertions"
  - "FileLockManager: defaultdict(asyncio.Lock) for per-file serialization"

# Metrics
duration: 7min
completed: 2026-02-20
---

# Phase 9 Plan 1: Spike Infrastructure Summary

**python-statemachine 2.6.0 confirmed with async guards, OCC DB writes, and adversarial concurrent testing -- all 4 affirmative evidence criteria pass**

## Performance

- **Duration:** 7 min
- **Started:** 2026-02-20T10:38:13Z
- **Completed:** 2026-02-20T10:45:50Z
- **Tasks:** 2
- **Files modified:** 17

## Accomplishments

- python-statemachine 2.6.0 passes the async guard binary test -- the library genuinely awaits async guards with DB queries
- 10 concurrent same-file transitions produce exactly 1 success and 9 rejections (adversarial proof)
- Error injection at 3 points confirms correct recovery: pre-commit unchanged, post-commit advanced, guard error unchanged
- DB invariants hold (0 violations), thread/task counts return to baseline (0 leaks)
- Combined harness produces "ALL CHECKS PASSED" with structured JSON evidence

## Task Commits

Each task was committed atomically:

1. **Task 1: Scaffold spike infrastructure** - `e351d5c` (feat)
2. **Task 2: FSM adapter and adversarial test harness** - `2fe594b` (feat)

## Files Created/Modified

- `spike/phase9_spike/protocol.py` - FileStateMachineProtocol interface (both adapters satisfy this)
- `spike/phase9_spike/adapters/statemachine_adapter.py` - StateMachineAdapter wrapping python-statemachine with OCC DB writes
- `spike/phase9_spike/adapters/handrolled_adapter.py` - HandRolledAdapter fallback (documented, not needed)
- `spike/phase9_spike/db.py` - execute_with_retry, init_spike_db, read_file_state
- `spike/phase9_spike/states.py` - VALID_STATES, VALID_EDGES, EVENTS constants
- `spike/phase9_spike/exceptions.py` - StaleTransitionError, GuardRejectedError, TransitionNotAllowedError
- `spike/phase9_spike/event_log.py` - emit_event() and EventCollector class
- `spike/phase9_spike/harness.py` - Combined adversarial test runner (ALL CHECKS PASSED)
- `spike/phase9_spike/tests/test_async_guards.py` - Binary pass/fail for async guard support (3 tests PASS)
- `spike/phase9_spike/tests/test_concurrent_transitions.py` - 10-concurrent same-file and different-file tests
- `spike/phase9_spike/tests/test_error_injection.py` - Pre-commit, post-commit, guard error injection (4 tests)
- `spike/phase9_spike/tests/test_db_invariants.py` - DB invariant checker + tests (4 tests)
- `spike/phase9_spike/tests/test_leak_check.py` - Thread/task leak detection (3 tests)
- `spike/phase9_spike/tests/conftest.py` - Fixtures: spike_db, seed_file, event_collector

## Decisions Made

1. **python-statemachine 2.6.0 is the chosen FSM approach** -- async guard binary test passed definitively (all 3 tests). The library awaits async guards, supports start_value with string values, and the AsyncEngine correctly reuses the running event loop.

2. **on_enter_state callback must use optional parameters** -- During `activate_initial_state()`, the library fires `on_enter_state` with the `__initial__` event. No trigger kwargs (file_id, db_path, expected_version) are available. Fix: make them optional with `None` defaults and skip DB write when `source.value is None`.

3. **Library propagates exceptions from callbacks** -- When `on_enter_state` raises after the DB commit, the library propagates the exception to the caller. It does NOT roll back internal state. This means post-commit errors leave the DB in an advanced state (correct behavior per locked decision #4).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] on_enter_state fires during activate_initial_state without trigger kwargs**
- **Found during:** Task 2 (adapter implementation)
- **Issue:** `on_enter_state` had required parameters `file_id`, `db_path`, `expected_version` but these are not available during `activate_initial_state()` which fires the `__initial__` event
- **Fix:** Made parameters optional with `None` defaults. Added guard: skip DB write when `source is None or source.value is None`
- **Files modified:** spike/phase9_spike/adapters/statemachine_adapter.py
- **Verification:** All 16 tests pass, harness prints ALL CHECKS PASSED
- **Committed in:** 2fe594b (Task 2 commit)

**2. [Rule 1 - Bug] current_state property fails before activation**
- **Found during:** Task 2 (adapter implementation)
- **Issue:** Accessing `self._sm.current_state_value` before `activate_initial_state()` raises an exception
- **Fix:** Added try/except fallback to `_initial_state` in the `current_state` property
- **Files modified:** spike/phase9_spike/adapters/statemachine_adapter.py
- **Verification:** All tests pass
- **Committed in:** 2fe594b (Task 2 commit)

**3. [Rule 1 - Bug] Error injection test used wrong callback signature**
- **Found during:** Task 2 (error injection tests)
- **Issue:** `failing_on_enter` mock function used `kwargs.get("source")` but the library injects `source` as a named parameter via dependency injection
- **Fix:** Updated mock signature to match the fixed `on_enter_state`: `source` as named param, optional `file_id`/`db_path`/`expected_version`
- **Files modified:** spike/phase9_spike/tests/test_error_injection.py
- **Verification:** All 4 error injection tests pass
- **Committed in:** 2fe594b (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (3 bugs)
**Impact on plan:** All fixes necessary for correct library integration. The `on_enter_state` signature issue is a key finding that will inform Phase 10 production integration. No scope creep.

## Issues Encountered

None beyond the auto-fixed deviations above. The library worked as documented for all major features (async guards, start_value, callback injection).

## User Setup Required

None - no external service configuration required.

## Affirmative Evidence Summary

All 4 criteria required by the Phase 9 gate definition:

| Criterion | Result | Evidence |
|-----------|--------|----------|
| DB Invariants | PASS | 0 violations after all test runs |
| Structured JSON Event Log | PASS | 20 events with all required fields |
| Thread/Task Leak Check | PASS | Threads: 1->1, Tasks: 1->1 |
| Same-File Adversarial Test | PASS | 1 success, 9 rejections |

## Next Phase Readiness

- Phase 9 Plan 2 (approach selection documentation) can proceed -- all evidence artifacts are produced
- Phase 10 can use `StateMachineAdapter` pattern directly with the `on_enter_state` optional-params fix
- The `FileStateMachineProtocol` is stable and both adapters satisfy it
- Key learning for Phase 10: always make `on_enter_state` callback params optional for `activate_initial_state()` compatibility

## Self-Check: PASSED

- All 18 key files exist on disk
- Commits e351d5c and 2fe594b found in git log
- 16/16 pytest tests pass
- Harness prints "ALL CHECKS PASSED"

---
*Phase: 09-async-fsm-spike*
*Completed: 2026-02-20*
