---
phase: 10-transition-atomicity
plan: 01
subsystem: database, infra
tags: [python-statemachine, aiosqlite, write-ahead-intent, crash-recovery, spike]
requires:
  - phase: 09-async-fsm-spike
    provides: "StateMachineAdapter, FileLockManager, adversarial test harness"
provides:
  - "Extended spike DB schema with intent columns"
  - "FileLifecycleSM with reset/retry/fail_reset transitions (no final states)"
  - "safe_delete wrappers (404 = success)"
  - "ResetTransitionManager with Txn A -> APIs -> Txn B"
  - "3 crash point tests proving recoverable partial state"
affects: [10-02]
tech-stack:
  added: []
  patterns: [write-ahead-intent, two-transaction-OCC, safe-delete-idempotency]
key-files:
  created:
    - spike/phase10_spike/__init__.py
    - spike/phase10_spike/db.py
    - spike/phase10_spike/exceptions.py
    - spike/phase10_spike/states.py
    - spike/phase10_spike/safe_delete.py
    - spike/phase10_spike/transition_reset.py
    - spike/phase10_spike/tests/__init__.py
    - spike/phase10_spike/tests/conftest.py
    - spike/phase10_spike/tests/test_safe_delete.py
    - spike/phase10_spike/tests/test_crash_points.py
  modified: []
key-decisions:
  - "intent columns on files table (not separate table, not new FSM state)"
  - "safe_delete: catch ClientError with code==404, re-raise all others"
  - "Txn A writes intent (no version increment), Txn B finalizes (increments version)"
  - "ResetTransitionManager bypasses StateMachineAdapter for multi-step execution"
  - "conftest.py uses async fixture instead of deprecated get_event_loop()"
patterns-established:
  - "Write-ahead intent: record intent before side effects, track progress, finalize after"
  - "Two-transaction OCC: Txn A (no version bump) -> side effects -> Txn B (version bump)"
  - "Safe delete idempotency: 404 from Gemini API = success (resource already gone)"
duration: 3min
completed: 2026-02-20
---

# Phase 10 Plan 01: Write-Ahead Intent Spike Summary

**Write-ahead intent pattern for two-API-call reset transition (INDEXED -> UNTRACKED) with 3 crash point tests proving deterministic partial state recording at every failure point**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-20T14:46:04Z
- **Completed:** 2026-02-20T14:49:57Z
- **Tasks:** 2
- **Files created:** 10

## Accomplishments
- Extended Phase 9 DB schema with 5 new columns (gemini IDs + write-ahead intent) for total of 11 columns
- FileLifecycleSM with 5 states (none final), 8 transitions including reset/retry/fail_reset
- safe_delete wrappers that treat Gemini API 404 as idempotent success (4 tests)
- ResetTransitionManager implementing full Txn A -> safe_delete APIs -> Txn B flow
- 3 crash point tests proving every failure scenario leaves deterministic recoverable state

## Task Commits

Each task was committed atomically:

1. **Task 1: Spike infrastructure -- extended DB schema, FSM states, safe_delete wrappers** - `b011fb2` (feat)
2. **Task 2: ResetTransitionManager and 3 crash point tests** - `90dac40` (feat/test)

**Plan metadata:** [pending] (docs: complete plan)

## Files Created
- `spike/phase10_spike/__init__.py` - Package marker
- `spike/phase10_spike/db.py` - Extended schema (11 columns), write_intent/update_progress/finalize_reset
- `spike/phase10_spike/exceptions.py` - Re-exports Phase 9 exceptions
- `spike/phase10_spike/states.py` - FileLifecycleSM with 8 transitions, no final states
- `spike/phase10_spike/safe_delete.py` - Idempotent delete wrappers (404 = success)
- `spike/phase10_spike/transition_reset.py` - ResetTransitionManager with Txn A -> APIs -> Txn B
- `spike/phase10_spike/tests/__init__.py` - Test package marker
- `spike/phase10_spike/tests/conftest.py` - Shared fixtures (spike_db, seed_indexed_file, seed_failed_file)
- `spike/phase10_spike/tests/test_safe_delete.py` - 4 tests for safe_delete wrappers
- `spike/phase10_spike/tests/test_crash_points.py` - 3 crash point tests

## Decisions Made
- Intent columns live on the files table directly (not a separate intent table) -- keeps schema simple and avoids cross-table joins during recovery scans
- safe_delete catches `google.genai.errors.ClientError` with `exc.code == 404` specifically -- other HTTP errors (403, 500) propagate to caller
- Txn A writes intent without incrementing version; Txn B finalizes and increments version -- this means recovery can retry Txn B with the original version
- ResetTransitionManager bypasses StateMachineAdapter entirely -- multi-step transitions need direct DB control, not the single-step FSM trigger pattern
- conftest.py spike_db fixture uses `async def` instead of deprecated `asyncio.get_event_loop().run_until_complete()`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed DeprecationWarning in conftest.py fixture**
- **Found during:** Task 2 (test execution)
- **Issue:** `asyncio.get_event_loop().run_until_complete()` triggers DeprecationWarning in Python 3.13
- **Fix:** Changed `spike_db` fixture to `async def` (pytest-asyncio handles the event loop)
- **Files modified:** spike/phase10_spike/tests/conftest.py
- **Verification:** All 7 tests pass with 0 warnings
- **Committed in:** 90dac40 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Minor fix for Python 3.13 compatibility. No scope creep.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Write-ahead intent pattern proven with 3 crash point tests
- Recovery (Plan 10-02) can use intent columns to deterministically resume interrupted resets
- All crash points leave gemini_state='indexed' with intent columns recording exact progress
- Version never incremented during partial execution -- Txn B can be retried with original version

## Self-Check: PASSED

- All 11 created files: FOUND
- Commit b011fb2 (Task 1): FOUND
- Commit 90dac40 (Task 2): FOUND
- 7/7 tests passing: VERIFIED

---
*Phase: 10-transition-atomicity*
*Completed: 2026-02-20*
