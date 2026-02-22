---
phase: 13-state-column-retirement
plan: 02
subsystem: database
tags: [sqlite, migration, v11, status-column, gemini_state, is_deleted, test-suite]

# Dependency graph
requires:
  - plan: 13-01
    provides: Inventory artifact at docs/migrations/phase13-status-inventory.md, all preconditions verified
provides:
  - V11 migration applied to live database (user_version=11)
  - status column physically dropped from files table
  - is_deleted column added (replaces LOCAL_DELETE semantics)
  - CHECK constraint on gemini_state (5 valid FSM states)
  - FileStatus enum removed from models.py
  - All source code and tests migrated, full test pass
affects: [database.py, models.py, scanner.py, cli.py, upload/state.py, upload/recovery.py, upload/orchestrator.py, sync/orchestrator.py, extraction/batch_orchestrator.py, extraction/sampler.py, tests/*, scripts/*]

# Tech tracking
tech-stack:
  added: []
  patterns: [full-table-rebuild-migration, check-constraint-enforcement]

key-files:
  created: []
  modified:
    - src/objlib/database.py
    - src/objlib/models.py
    - src/objlib/scanner.py
    - src/objlib/cli.py
    - src/objlib/upload/state.py
    - src/objlib/upload/recovery.py
    - src/objlib/upload/orchestrator.py
    - src/objlib/sync/orchestrator.py
    - src/objlib/extraction/batch_orchestrator.py
    - src/objlib/extraction/sampler.py
    - tests/conftest.py
    - tests/test_database.py
    - tests/test_database_crud.py
    - tests/test_upload.py
    - tests/test_fsm.py
    - tests/test_schema.py
    - tests/test_search.py
    - tests/test_browse_filter.py
    - scripts/check_status.sh
    - scripts/monitor_upload.sh
    - scripts/monitor_enriched_upload.sh
    - scripts/monitor_extraction.sh
    - scripts/watch_progress.sh

key-decisions:
  - "Legacy record_upload_intent/record_upload_failure retain gemini_state writes (uploading/failed) for backward compat"
  - "V11 uses executescript for full table rebuild (same pattern as V7)"
  - "fresh-DB shortcut: version==0 sets user_version=11 directly, skips all migrations"

patterns-established:
  - "V11 migration: full table rebuild via files_v11, INSERT...SELECT mapping status to is_deleted, DROP, RENAME"
  - "CHECK constraint on gemini_state enforced at DB level post-migration"

# Metrics
duration: 25min
completed: 2026-02-22
---

# Phase 13 Plan 02: V11 Migration + Full Code Rewrite

**V11 migration applied: status column physically dropped, is_deleted and CHECK(gemini_state) added, all 84 code references rewritten, 459 tests passing**

## Performance

- **Duration:** ~25 min (including resume)
- **Completed:** 2026-02-22
- **Tasks:** 2
- **Files modified:** 23

## What Was Built

Applied the V11 SQLite migration via full table rebuild: the legacy `status` column is physically absent from the `files` table, replaced by `is_deleted INTEGER NOT NULL DEFAULT 0` and a `CHECK(gemini_state IN ('untracked','uploading','processing','indexed','failed'))` constraint. Removed the `FileStatus` enum from `models.py` and rewrote all 84 code references across 10 source files, 8 test files, and 5 shell scripts. All 459 tests pass.

## Tasks Completed

| Task | Status | Notes |
|------|--------|-------|
| 1. V11 migration + all source code rewrites | ✓ | Database migrated, FileStatus removed, 84 sites rewritten |
| 2. Update all tests + full test suite pass | ✓ | 459 passed, 0 failed |

## Success Criteria Verified

| SC | Check | Result |
|----|-------|--------|
| SC-1 | docs/migrations/phase13-status-inventory.md committed (plan 13-01) | PASS |
| SC-2 | `DISTINCT gemini_state FROM files` = `indexed`, `untracked` (plain strings) | PASS |
| SC-2 | CHECK constraint active: `CHECK(gemini_state IN (...))` in schema | PASS |
| SC-3 | `PRAGMA user_version` = 11, no status column in schema | PASS |
| SC-4 | `python -m pytest tests/ -v` = 459 passed, 0 failed | PASS |
| SC-4 | `python -m objlib status` displays gemini_state counts correctly | PASS |

## Post-Migration Database State

```
PRAGMA user_version      → 11
DISTINCT gemini_state    → indexed, untracked
COUNT(*) FROM files      → 1884 (zero data loss)
triggers                 → update_files_timestamp only (log_status_change gone)
is_deleted = 1 count     → 0 (no LOCAL_DELETE rows existed)
```

## Key Changes

### models.py
- Removed `FileStatus` enum entirely (was: PENDING, UPLOADED, FAILED, LOCAL_DELETE, MISSING, SKIPPED)
- Removed `FileRecord.status` field and `to_dict()` entry

### database.py
- Added `MIGRATION_V11_SQL`: full table rebuild, status -> is_deleted mapping, gemini_state CHECK
- Updated `SCHEMA_SQL`: no status column, added is_deleted, added gemini_state with CHECK
- Removed `update_file_status()` method
- Rewrote `mark_deleted()`: `SET is_deleted = 1`
- Rewrote `get_missing_files()`: `WHERE missing_since IS NOT NULL`
- Rewrote `get_status_counts()`: `GROUP BY gemini_state`
- Rewrote `get_all_active_files_with_mtime()`: `WHERE NOT is_deleted AND missing_since IS NULL`
- ~12 filter sites: `status != 'LOCAL_DELETE'` → `NOT is_deleted`
- 2 upload query sites: `status = 'uploaded'` → `gemini_state = 'indexed'`
- UPSERT_SQL: 6 columns (status removed)

### upload/state.py
- Removed 5 FSM dual-write lines (status= from transition_to_uploading, transition_to_indexed, transition_to_failed, finalize_reset, retry_failed_file)
- Legacy `record_upload_intent`: sets `gemini_state = 'uploading'` (replaces old `status = 'uploading'`)
- Legacy `record_upload_failure`: sets `gemini_state = 'failed'` (replaces old `status = 'failed'`)

### cli.py
- Status display: shows gemini_state counts
- Removed `--set-pending` flags from 3 commands (metadata update, batch-update, extract-wave2)

## Decisions Made

- **Legacy methods retain gemini_state writes**: `record_upload_intent` and `record_upload_failure` write `gemini_state` directly (not via FSM). Tests confirmed this semantic contract. Since the FSM path is the production path for Phase 12+, these are legacy maintenance paths that still need correct behavior.

## Deviations from Plan

- Agent ran out of turns on first pass; resumed to complete sync/orchestrator.py fixes and all test updates.
- Final 2 test failures (test_record_upload_intent_changes_status, test_record_failure) fixed by orchestrator after agent return: added `gemini_state = 'uploading'` and `gemini_state = 'failed'` to legacy methods that had only had `status=` writes removed.

## Self-Check

| Check | Result |
|-------|--------|
| All tasks executed | ✓ |
| Each task committed | ✓ |
| Verify steps passed | ✓ |
| 459 tests passing | ✓ |
| STATE.md updated | ✓ |

## Self-Check: PASSED
