---
phase: 08-store-migration-precondition
plan: 01
subsystem: database
tags: [sqlite, schema-migration, fsm, gemini]

# Dependency graph
requires:
  - phase: 07-interactive-tui
    provides: V8 schema (session_events bookmark support)
provides:
  - V9 schema with gemini_store_doc_id, gemini_state, gemini_state_updated_at columns
  - MIGR-04 state reset script (all uploaded files reset to untracked)
  - Verified database backup at data/library.bak-phase8
affects: [08-02-store-migration, 08-03-stability-check, 09-async-fsm-spike]

# Tech tracking
tech-stack:
  added: []
  patterns: [ALTER TABLE ADD COLUMN with try/except for idempotency, standalone migration scripts for destructive operations]

key-files:
  created: [scripts/migrate_phase8.py]
  modified: [src/objlib/database.py, tests/test_schema.py]

key-decisions:
  - "V9 migration uses individual ALTER TABLE statements (not executescript) for column-exists safety"
  - "Destructive state reset lives in standalone script, not auto-migration -- requires explicit user invocation"
  - "No CHECK constraint on gemini_state -- FSM enforces valid transitions in application code"
  - "Migration script uses raw sqlite3 (not Database class) for WAL checkpoint and integrity control"

patterns-established:
  - "Standalone migration scripts for destructive DB operations (scripts/migrate_phase8.py pattern)"
  - "Pre/post verification of sacred data (metadata_json, entity tables) around any destructive operation"

# Metrics
duration: 4min
completed: 2026-02-19
---

# Phase 8 Plan 01: DB Schema + State Reset Summary

**V9 schema migration adds 3 Gemini FSM columns; standalone script resets 873 uploaded files to untracked with verified metadata preservation**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-20T00:38:07Z
- **Completed:** 2026-02-20T00:42:22Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- V9 schema auto-migration adds gemini_store_doc_id, gemini_state, gemini_state_updated_at on any DB open
- Migration script (MIGR-04) reset 873 uploaded files: gemini_state='untracked', gemini_file_id=NULL, gemini_store_doc_id=NULL
- Verified backup created at data/library.bak-phase8 (22MB) before destructive operations
- Post-migration verification confirmed 3389 entity records and all metadata_json values intact
- Script is idempotent on re-run (detects already-migrated state)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add V9 schema migration to database.py** - `5244c9f` (feat)
2. **Task 2: Create scripts/migrate_phase8.py (state reset + backup)** - `dcd70e9` (feat)

## Files Created/Modified
- `src/objlib/database.py` - V9 migration block (3 ALTER TABLE ADD COLUMN), MIGRATION_V9_SQL constant, PRAGMA user_version = 9
- `scripts/migrate_phase8.py` - Standalone MIGR-04 migration script with backup, dry-run, verification
- `tests/test_schema.py` - Updated version assertion from 8 to 9

## Decisions Made
- V9 migration uses individual ALTER TABLE statements wrapped in try/except rather than executescript, because ADD COLUMN must be individual statements and column-exists errors must be caught
- No CHECK constraint on gemini_state column -- SQLite ALTER TABLE ADD COLUMN with CHECK is fragile; FSM enforcement belongs in application code (Phase 9+)
- Migration script uses raw sqlite3 instead of the Database class for lower-level control (WAL checkpoint, integrity check, connection lifecycle around backup)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated stale test assertion for schema version**
- **Found during:** Task 1 (V9 schema migration)
- **Issue:** tests/test_schema.py::TestSchemaCreation::test_user_version_is_8 asserted version == 8, now fails with version 9
- **Fix:** Renamed test to test_user_version_is_9, updated assertion to version == 9
- **Files modified:** tests/test_schema.py
- **Verification:** All 439 tests pass
- **Committed in:** 5244c9f (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Necessary update to stale test. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- DB schema is at V9 with all 3 FSM columns present
- All 873 uploaded files are in gemini_state='untracked' with NULL Gemini IDs
- Ready for 08-02 (store deletion + new store creation) and 08-03 (stability check)
- Backup available at data/library.bak-phase8 for rollback if needed

---
## Self-Check: PASSED

All files verified present, all commit hashes verified in git log.

---
*Phase: 08-store-migration-precondition*
*Completed: 2026-02-19*
