---
phase: 12-50-file-fsm-upload
plan: 02
subsystem: upload, recovery
tags: [fsm, occ, recovery, sc3, sc6, statemachine, sqlite, async]

# Dependency graph
requires:
  - phase: 12-50-file-fsm-upload
    plan: 01
    provides: V10 schema, FileLifecycleSM, transition_to_*() methods, OCCConflictError
provides:
  - FSMUploadOrchestrator with FSM-mediated upload path (run_fsm entry point)
  - SC3-compliant _reset_existing_files_fsm() (store doc before raw file)
  - write_reset_intent/update_intent_progress/finalize_reset on AsyncUploadStateManager
  - Production RecoveryCrawler with SC6 OCC guard (raises on finalize_reset failure)
  - retry_failed_file() standalone FAILED->UNTRACKED escape function
  - 23-test suite covering FSM transitions, OCC, SC3, SC6, lifecycle
affects: [12-03-PLAN, 12-04-PLAN, 12-05-PLAN, 12-06-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns: [write-ahead intent for multi-step reset, linear step resumption recovery, SC3 delete ordering]

key-files:
  created:
    - tests/test_fsm.py
  modified:
    - src/objlib/upload/orchestrator.py
    - src/objlib/upload/recovery.py
    - src/objlib/upload/state.py
    - tests/test_schema.py

key-decisions:
  - "retry_failed_file writes gemini_state directly (6th allowed write site) -- standalone escape path per Phase 10 design"
  - "RecoveryCrawler.recover_all returns tuple of (recovered, occ_failures) for caller visibility"
  - "write_reset_intent does NOT increment version (Txn A pattern from Phase 10)"

patterns-established:
  - "SC3 delete order: store document before raw file in all reset paths"
  - "Write-ahead intent pattern: write_reset_intent -> API calls -> finalize_reset"
  - "Linear step resumption: RecoveryCrawler resumes from intent_api_calls_completed"

# Metrics
duration: 8min
completed: 2026-02-20
---

# Phase 12 Plan 02: FSM Upload Pipeline, RecoveryCrawler, and Test Suite Summary

**FSMUploadOrchestrator with SC3-compliant reset, production RecoveryCrawler with SC6 OCC guard, and 23-test suite validating FSM transitions, OCC conflicts, and delete ordering**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-20T18:27:26Z
- **Completed:** 2026-02-20T18:36:01Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- FSMUploadOrchestrator drives files through untracked -> uploading -> processing -> indexed via transition_to_*() methods
- _reset_existing_files_fsm() enforces SC3: deletes store document BEFORE raw file with write-ahead intent for crash recovery
- RecoveryCrawler._recover_file() raises OCCConflictError on finalize_reset failure (SC6), recover_all() catches per-file and continues
- 23 tests cover all 8 legal FSM transitions, 3 illegal transitions, OCC guard behavior, full lifecycle, SC6 recovery, SC3 delete order, and reset intent methods
- display_name.strip() applied in _upload_fsm_file() per Phase 11 finding

## Task Commits

Each task was committed atomically:

1. **Task 1: FSMUploadOrchestrator and fixed _reset_existing_files()** - `b615302` (feat)
2. **Task 2: Production RecoveryCrawler and test suite** - `33c9875` (feat)

## Files Created/Modified
- `src/objlib/upload/orchestrator.py` - FSMUploadOrchestrator class with run_fsm(), _upload_fsm_file(), _poll_fsm_operation(), _reset_existing_files_fsm()
- `src/objlib/upload/state.py` - write_reset_intent(), update_intent_progress(), finalize_reset() methods
- `src/objlib/upload/recovery.py` - RecoveryCrawler class with SC6 OCC guard, retry_failed_file() function
- `tests/test_fsm.py` - 23 tests: FSM transitions (11), OCC guard (2), lifecycle (2), SC6 (2), SC3 (1), retry (2), reset intent (3)
- `tests/test_schema.py` - Updated version assertion from V9 to V10

## Decisions Made
- retry_failed_file() writes gemini_state directly as a 6th allowed write site -- this is the designated FAILED->UNTRACKED escape per Phase 10 design (not an SC4 violation)
- RecoveryCrawler.recover_all() returns a tuple of (recovered_paths, occ_failure_paths) for caller visibility into failures
- write_reset_intent does NOT increment version, following Phase 10 Txn A pattern (intent write without version bump, finalize increments)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed stale test_schema version assertion**
- **Found during:** Task 2 (full test suite regression check)
- **Issue:** test_user_version_is_9 expects PRAGMA user_version=9 but V10 migration (Plan 12-01) bumped it to 10
- **Fix:** Updated test to assert version == 10 and renamed to test_user_version_is_10
- **Files modified:** tests/test_schema.py
- **Verification:** Full test suite (462 tests) passes
- **Committed in:** 33c9875 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Pre-existing test failure from V10 migration, trivial fix. No scope creep.

## Issues Encountered
- `git stash` during regression check accidentally reverted recovery.py changes; re-applied edits after stash pop. No data lost.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- FSMUploadOrchestrator ready for CLI wiring in Plan 12-03
- RecoveryCrawler ready for integration into FSM upload startup sequence
- All transition methods and reset infrastructure tested and committed
- 462 total tests pass with no regressions

## Self-Check: PASSED

All files verified present:
- FOUND: src/objlib/upload/orchestrator.py
- FOUND: src/objlib/upload/recovery.py
- FOUND: src/objlib/upload/state.py
- FOUND: tests/test_fsm.py
- FOUND: tests/test_schema.py

All commits verified:
- FOUND: b615302 (Task 1)
- FOUND: 33c9875 (Task 2)

---
*Phase: 12-50-file-fsm-upload*
*Completed: 2026-02-20*
