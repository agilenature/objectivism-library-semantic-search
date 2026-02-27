---
phase: 17-rxpy-tui
plan: 02
subsystem: testing
tags: [uat, behavioral-invariants, textual, tui, pre-migration-baseline, pilot-press]

# Dependency graph
requires:
  - phase: 17-rxpy-tui-01
    provides: "HOSTILE spike confirming RxPY + Textual integration viability"
provides:
  - "7 pre-UAT behavioral invariant tests capturing exact current TUI behavior"
  - "Measured contract values: debounce count, Enter immediacy, stale cancellation, filter re-search, history nav delta, clear immediacy, error containment"
affects: [17-03, 17-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "pilot.press() for end-to-end SearchBar->debounce->App pipeline testing (NOT post_message)"
    - "Measured baselines: capture specific numeric/string values as behavioral contract"
    - "tracked_search side_effect pattern for observing search start/end lifecycle"

key-files:
  created:
    - "tests/test_uat_tui_behavioral.py"
  modified: []

key-decisions:
  - "All 7 tests drive input through pilot.press() to exercise full pipeline end-to-end"
  - "HISTORY_NAV_SEARCH_DELTA=0: Up/Down arrows do NOT fire searches within the test window (debounce timers from value change are superseded by rapid navigation)"
  - "Stale cancellation contract: both alpha and beta searches start AND complete (300ms sleep is short enough that exclusive=True doesn't cancel alpha before it finishes); app.query correctly reflects 'beta'"
  - "Test 7 error containment: RuntimeError caught by _run_search except block, is_searching resets via finally"

patterns-established:
  - "Pre/post UAT pattern: capture measured values in current code, assert same values after migration"
  - "Contract printing: each test prints CONTRACT line for manual inspection during -s runs"

# Metrics
duration: 4min
completed: 2026-02-27
---

# Phase 17 Plan 02: Pre-UAT Behavioral Baseline Summary

**7 behavioral invariant tests (431 lines) capturing exact TUI debounce/Enter/stale-cancel/filter/history/clear/error behavior as the gate contract for RxPY migration**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-27T10:19:38Z
- **Completed:** 2026-02-27T10:24:09Z
- **Tasks:** 1
- **Files created:** 1

## Accomplishments

- Created 7 pre-UAT behavioral invariant tests exercising the full SearchBar -> debounce -> App pipeline via pilot.press()
- All 7 tests pass against the current (pre-RxPY) codebase in 12.02s
- Measured baselines captured as the behavioral parity contract for plan 17-04 post-migration validation
- Existing 118 test_tui.py tests confirmed passing (zero regressions)

## Measured Contract Values

| Invariant | Test | Measured Value |
|-----------|------|----------------|
| 1. Debounce | test_uat_debounce_fires_once | searches_before=0, searches_after=1, query='hello' |
| 2. Enter | test_uat_enter_fires_immediately | immediate_count=1, post_debounce_count=1 |
| 3. Stale cancel | test_uat_stale_cancellation | starts=['alpha','beta'], ends=['alpha','beta'], app.query='beta' |
| 4. Filter | test_uat_filter_triggers_search | initial=1, after_filter=2 |
| 5. History | test_uat_history_navigation | up1='beta', up2='alpha', down1='beta', down2='', SEARCH_DELTA=0 |
| 6. Clear | test_uat_empty_query_clears_immediately | results=[], query='', selected_index=None within 50ms |
| 7. Error | test_uat_error_containment | is_searching=False, search_calls=1 |

## Task Commits

Each task was committed atomically:

1. **Task 1: Create pre-UAT behavioral test suite for all 7 invariants** - `32dc2f9` (test)

## Files Created/Modified

- `tests/test_uat_tui_behavioral.py` (431 lines) - 7 behavioral invariant tests with fixtures, measured baselines, and contract printing

## Decisions Made

- **pilot.press() not post_message():** Tests exercise the full SearchBar -> on_input_changed -> debounce timer -> _fire_search -> post_message(SearchRequested) -> App.on_search_requested -> _run_search pipeline end-to-end
- **HISTORY_NAV_SEARCH_DELTA=0:** The measured value for history navigation is 0 additional searches. When Up/Down arrows set self.value, this triggers on_input_changed which starts a debounce timer, but rapid navigation supersedes each timer before it fires. The 0.5s wait at the end of the test confirms no pending timers fire. This becomes the post-UAT contract.
- **Stale cancellation shows both complete:** With 300ms simulated latency, @work(exclusive=True) cancellation does not prevent alpha from completing because the Task has already progressed past its await point. The contract captures this actual behavior rather than an idealized "alpha cancelled" scenario.

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 17-03 (RxPY pipeline implementation) is UNBLOCKED -- has both the spike (17-01) and the pre-UAT baseline (17-02) as prerequisites
- Plan 17-04 (post-UAT validation) will run these exact 7 tests after migration to confirm behavioral parity
- The contract values table above is the gate: all 7 measured values must match after RxPY migration

---
*Phase: 17-rxpy-tui*
*Plan: 02*
*Completed: 2026-02-27*
