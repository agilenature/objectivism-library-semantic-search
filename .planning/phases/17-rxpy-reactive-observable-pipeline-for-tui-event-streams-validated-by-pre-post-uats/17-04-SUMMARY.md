---
phase: 17-rxpy-tui
plan: 04
subsystem: tui
tags: [rxpy, reactivex, textual, uat, behavioral-parity, post-migration-validation]

# Dependency graph
requires:
  - phase: 17-rxpy-tui-02
    provides: "7 pre-UAT behavioral invariant tests with measured contract values"
  - phase: 17-rxpy-tui-03
    provides: "RxPY reactive pipeline replacing manual debounce/@work in TUI"
provides:
  - "Post-migration UAT validation confirming all 7 behavioral invariants match pre-UAT contract"
  - "10 test_tui.py tests updated from SearchRequested/_fire_search to RxPY Subject-driven API"
  - "Full project test suite green: 470/470 tests pass"
  - "Phase 17 gate: PASSED -- Phase 18 UNBLOCKED"
affects: [phase-18]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Test pattern: use _enter_subject.on_next(query) to drive search in tests (replaces post_message(SearchRequested))"
    - "Test pattern: use input_subject.on_next('') to trigger empty-query clear subscription"
    - "Test pattern: use _filter_subject.on_next(FilterSet) to feed combine_latest in filter tests"
    - "Test pattern: typing + pilot.press('enter') for tests requiring history management"

key-files:
  created: []
  modified:
    - "tests/test_tui.py"
    - "tests/test_schema.py"

key-decisions:
  - "Tests drive search via _enter_subject.on_next() (Subject injection) rather than pilot.press() for speed and determinism"
  - "Empty-query clear test requires mock_search_service so RxPY pipeline (including clear subscription) is wired in on_mount"
  - "Filter re-search test emits query through pipeline first (combine_latest requires both streams to have emitted)"
  - "_fire_search history tests replaced with pilot.press('enter') to test full on_key path including history management"
  - "test_schema.py EXPECTED_TABLES and user_version updated for Phase 16.6 CRAD tables (pre-existing gap, not Phase 17)"

patterns-established:
  - "Test migration pattern: SearchRequested message path -> Subject.on_next() injection"
  - "Pipeline prerequisite: tests needing RxPY behavior must provide search_service to wire subscriptions"

# Metrics
duration: 15min
completed: 2026-02-27
---

# Phase 17 Plan 04: Post-UAT Validation Summary

**All 7 behavioral invariants pass against RxPY-migrated code, 10 broken test_tui.py tests fixed for Subject-driven API, full project suite 470/470 green -- Phase 17 gate PASSED, Phase 18 UNBLOCKED**

## Performance

- **Duration:** 15 min
- **Started:** 2026-02-27T12:36:52Z
- **Completed:** 2026-02-27T12:52:17Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- All 7 behavioral UAT invariants pass with identical contract values as pre-migration baseline
- Fixed 10 test_tui.py tests that used removed internal APIs (SearchRequested handler, _fire_search method)
- Fixed 2 pre-existing test_schema.py failures (CRAD tables and user_version from Phase 16.6)
- Full project test suite: 470/470 tests pass with zero failures

## Behavioral Parity Verification (7/7 invariants match)

| Invariant | Pre-UAT Contract | Post-UAT Result | Status |
|-----------|-----------------|-----------------|--------|
| 1. Debounce fires once | searches_before=0, after=1, query='hello' | Identical | PASS |
| 2. Enter fires immediately | immediate=1, post_debounce=1 (no double-fire) | Identical | PASS |
| 3. Stale cancellation | starts=['alpha','beta'], ends=['alpha','beta'], query='beta' | Identical | PASS |
| 4. Filter triggers re-search | initial=1, after_filter=2 | Identical | PASS |
| 5. History navigation | up1='beta', up2='alpha', down1='beta', down2='', DELTA=0 | Identical | PASS |
| 6. Clear is immediate | results=[], query='', selected_index=None within 50ms | Identical | PASS |
| 7. Error containment | is_searching=False, search_calls=1 | Identical | PASS |

## Remnant Verification

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| `@work` in src/objlib/tui/ | 0 matches | 0 matches | CLEAN |
| `_debounce_timer` in src/objlib/tui/ | 0 matches | 0 matches | CLEAN |
| `_debounce_gen` in src/objlib/tui/ | 0 matches | 0 matches | CLEAN |
| `SearchRequested` in search_bar.py | 0 matches | 0 matches | CLEAN |
| `switch_map` in app.py | >= 1 | 1 | PRESENT |
| `combine_latest` in app.py | >= 1 | 1 | PRESENT |

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix 10 broken test_tui.py tests for RxPY pipeline** - `c22fbd0` (fix)
2. **Task 2: Fix test_schema.py and verify full project suite** - `9874d37` (fix)

## Files Created/Modified

- `tests/test_tui.py` - Updated 10 tests from SearchRequested/post_message to _enter_subject.on_next() and pilot.press("enter") for RxPY pipeline
- `tests/test_schema.py` - Added file_discrimination_phrases and series_genus to EXPECTED_TABLES, updated user_version 11 -> 12

## Test Fixes Applied (10 tests)

| Test | Old API | New API | Reason |
|------|---------|---------|--------|
| test_empty_search_clears_results | post_message(SearchRequested(query="")) | input_subject.on_next("") | SearchRequested handler removed |
| test_search_triggers_service_call | post_message(SearchRequested(query=...)) | _enter_subject.on_next(query) | SearchRequested handler removed |
| test_search_results_populate_list | post_message(SearchRequested(query=...)) | _enter_subject.on_next(query) | SearchRequested handler removed |
| test_search_updates_reactive_query | post_message(SearchRequested(query=...)) | _enter_subject.on_next(query) | SearchRequested handler removed |
| test_search_with_active_filters | post_message(SearchRequested) + app.active_filters | _enter_subject.on_next + _filter_subject.on_next | combine_latest needs both streams |
| test_search_with_empty_filters | post_message(SearchRequested(query=...)) | _enter_subject.on_next(query) | SearchRequested handler removed |
| test_search_logs_to_active_session | post_message(SearchRequested(query=...)) | _enter_subject.on_next(query) | SearchRequested handler removed |
| test_filter_changed_with_active_query | app.query = "..." + FilterChanged | _enter_subject.on_next first, then FilterChanged | combine_latest requires query emission |
| test_search_bar_fire_search_adds_to_history | bar._fire_search("virtue") | pilot.press("enter") after typing | _fire_search method removed |
| test_search_bar_fire_search_deduplicates | bar._fire_search() x3 | pilot.press("enter") with typing | _fire_search method removed |

## Decisions Made

- **Subject injection over pilot typing for search tests:** Using `_enter_subject.on_next(query)` is faster and more deterministic than typing each character via pilot.press(). Pilot typing is only used for history tests where on_key behavior matters.
- **Empty-query test needs mock_search_service:** The RxPY clear subscription is only wired when search_service is not None (on_mount guard). Tests that need the clear path must provide a search_service.
- **Filter test emits query first:** combine_latest requires both streams to have emitted. Setting app.query directly bypasses the pipeline, so the filter test now fires a query through _enter_subject first.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_schema.py EXPECTED_TABLES missing CRAD tables**
- **Found during:** Task 2 (full project test suite run)
- **Issue:** test_schema.py expected 16 tables but schema now has 18 (file_discrimination_phrases and series_genus added in Phase 16.6 CRAD)
- **Fix:** Added both tables to EXPECTED_TABLES set, updated comment from "16 tables" to "18 tables"
- **Files modified:** tests/test_schema.py
- **Verification:** test_fresh_schema_all_tables and test_schema_idempotency both pass
- **Committed in:** 9874d37

**2. [Rule 1 - Bug] Fixed test_schema.py user_version assertion**
- **Found during:** Task 2 (full project test suite run)
- **Issue:** test_user_version_is_11 asserted version == 11 but schema is now version 12 (V12: CRAD tables)
- **Fix:** Updated assertion to version == 12, renamed test to test_user_version_is_12
- **Files modified:** tests/test_schema.py
- **Verification:** Test passes
- **Committed in:** 9874d37

---

**Total deviations:** 2 auto-fixed (2 pre-existing bugs in test_schema.py, not caused by Phase 17)
**Impact on plan:** Both fixes necessary for full suite green gate. No scope creep.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **Phase 17 gate: PASSED** -- All 7 behavioral invariants confirmed, full suite 470/470 green
- **Phase 18 is UNBLOCKED** -- RxPY reactive pipeline is production-ready
- Manual debounce/generation-tracking fully replaced by RxPY operators
- @work(exclusive=True) replaced by switch_map + defer_task()
- Scattered filter-refire unified into combine_latest pipeline

## Self-Check: PASSED

- FOUND: `tests/test_tui.py`
- FOUND: `tests/test_schema.py`
- FOUND: `tests/test_uat_tui_behavioral.py`
- FOUND: `17-04-SUMMARY.md`
- FOUND: commit `c22fbd0`
- FOUND: commit `9874d37`

---
*Phase: 17-rxpy-tui*
*Plan: 04*
*Completed: 2026-02-27*
