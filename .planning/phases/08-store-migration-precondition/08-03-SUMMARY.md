---
phase: 08-store-migration-precondition
plan: 03
subsystem: infra
tags: [gemini, fsm, stability-check, sqlite, genai-sdk]

# Dependency graph
requires:
  - phase: 08-01
    provides: V9 schema with gemini_state, gemini_store_doc_id, gemini_state_updated_at columns
provides:
  - v2 FSM-aware stability instrument (scripts/check_stability.py)
  - 3-tier exit codes (0=STABLE, 1=UNSTABLE, 2=ERROR) usable as automated wave gates
  - 6 independent assertions checking gemini_state='indexed' sync
  - Prerequisite validation preventing false positives from misconfiguration
affects: [phase-09, phase-10, phase-11, phase-12, phase-13, phase-14, phase-15, phase-16]

# Tech tracking
tech-stack:
  added: []
  patterns: [prerequisite-gating, vacuous-pass-on-empty, 3-tier-exit-codes]

key-files:
  created: []
  modified: [scripts/check_stability.py]

key-decisions:
  - "v2 stability instrument uses raw genai SDK directly, no dependency on objlib search layer"
  - "Prerequisite failures (DB missing, schema wrong, store not found) produce exit 2 not exit 1"
  - "Vacuous pass on empty store: all 6 assertions pass when indexed_count=0 and store has 0 docs"
  - "DEFAULT_STORE changed from objectivism-library-test to objectivism-library"

patterns-established:
  - "Prerequisite gating: validate environment before assertions, exit 2 on config error"
  - "Vacuous pass: assertions pass trivially on empty state to avoid false negatives during migration"
  - "3-tier exit: 0=pass, 1=fail, 2=error -- scripts can distinguish test failure from env problem"

# Metrics
duration: 3min
completed: 2026-02-19
---

# Phase 8 Plan 3: Stability Instrument v2 Summary

**FSM-aware stability checker with 6 assertions using gemini_state='indexed', prerequisite gating (exit 2), and vacuous pass logic for empty stores**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-20T00:47:35Z
- **Completed:** 2026-02-20T00:50:40Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Rewrote check_stability.py from v1 (status='uploaded') to v2 (gemini_state='indexed')
- Added prerequisite validation producing exit 2 for DB missing, schema not migrated, API key absent, store not found
- Implemented vacuous pass logic so assertions 2, 3, 5, 6 pass trivially on empty stores
- Removed dependency on objlib.search.client and objlib.search.citations -- uses raw genai SDK
- All 6 assertions now use FSM columns: gemini_state, gemini_store_doc_id

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite check_stability.py as v2 FSM-aware stability instrument** - `0ceca79` (feat)
2. **Task 2: Verify prerequisite checks** - verification only, no code changes needed (Task 1 code was correct)

## Files Created/Modified
- `scripts/check_stability.py` - v2 FSM-aware stability instrument with 6 assertions, prerequisite gating, vacuous pass logic

## Decisions Made
- Used raw genai SDK instead of objlib search layer to keep stability instrument independent of application code
- Prerequisite failures exit 2 (error) not 1 (unstable) -- this distinguishes environment problems from actual sync failures
- Vacuous pass on empty store prevents false negatives during the migration window (Phases 8-11 have no indexed files)
- DEFAULT_STORE changed to "objectivism-library" to match the v2 store created by 08-02

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Stability instrument ready to serve as automated wave gate for all subsequent phases (9-16)
- Will produce vacuous STABLE (exit 0) on the empty "objectivism-library" store created by 08-02
- First meaningful (non-vacuous) stability check happens after Phase 12 uploads 50 files

## Self-Check: PASSED

- FOUND: scripts/check_stability.py
- FOUND: commit 0ceca79

---
*Phase: 08-store-migration-precondition*
*Completed: 2026-02-19*
