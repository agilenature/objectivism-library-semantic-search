# Phase 13: Legacy `status` Column Retirement Inventory

**Date:** 2026-02-22
**Phase:** 13 -- State Column Retirement
**Purpose:** Complete inventory of every `status` column reference across the codebase, with migration mapping for each site. This artifact drives all code changes in plan 13-02.
**Scope:** All Python files under `src/`, `tests/`, `scripts/` per locked decision #6.

---

## Precondition Verification Results

All preconditions verified via `sqlite3` CLI against `data/library.db` on 2026-02-22T09:37Z.

| Check | Query | Result | Pass |
|-------|-------|--------|------|
| gemini_state NULL count | `SELECT COUNT(*) FROM files WHERE gemini_state IS NULL` | **0** | PASS |
| Transient state count | `SELECT COUNT(*) FROM files WHERE gemini_state IN ('uploading', 'processing')` | **0** | PASS |
| LOCAL_DELETE/missing count | `SELECT COUNT(*) FROM files WHERE status IN ('LOCAL_DELETE', 'missing')` | **0** | PASS |
| Schema version | `PRAGMA user_version` | **10** | PASS |
| gemini_state plain strings (SC-2) | `SELECT DISTINCT gemini_state FROM files` | `indexed`, `untracked` | PASS |
| Status distinct values | `SELECT status, COUNT(*) FROM files GROUP BY status` | `skipped: 136`, `uploaded: 1748` | PASS |
| Cross-tabulation | `SELECT status, gemini_state, COUNT(*) FROM files GROUP BY status, gemini_state` | `skipped/untracked: 136`, `uploaded/indexed: 50`, `uploaded/untracked: 1698` | PASS |

**Conclusion:** All 7 preconditions pass. Migration can proceed.

---

## Migration Window Scope (SC-3)

- **Window opened:** Phase 8, V9 migration (2026-02-20). The `gemini_state` column was added to the `files` table with `DEFAULT 'untracked'`. All 1,884 existing files were populated with `gemini_state = 'untracked'`. From this point forward, `gemini_state` became the authoritative state column.

- **`status` frozen since Phase 8:** No FSM code path writes to `status` as the primary state. The Phase 12 FSM transition methods included `status = '...'` dual-write lines for backward compatibility only -- `gemini_state` was always the sole state read by FSM logic.

- **Phase 12 confirmed FSM correctness:** The 50-file FSM upload (Phase 12) proved the FSM pipeline works end-to-end using `gemini_state` exclusively. The T+36h temporal stability gate (confirmed 2026-02-22T08:43Z) verified zero drift in `gemini_state` values over 60+ hours.

- **Phase 13 closes the window permanently:** Plan 13-02 executes the V11 migration which physically drops the `status` column from the `files` table. There is no open-ended dual-write period -- the window ends with plan 13-02 execution.

- **Timeline:**
  - Phase 8 (2026-02-20): `gemini_state` added, all files populated, `status` becomes stale
  - Phase 12 (2026-02-20 to 2026-02-22): FSM proven with 50-file upload, dual-write for backward compat
  - Phase 13 plan 13-01 (2026-02-22): Inventory and precondition verification (this document)
  - Phase 13 plan 13-02 (next): V11 migration drops `status`, removes all code references, full test pass

---

## Category A: SQL READ Sites

Every SQL query that reads the `status` column for filtering, grouping, or selecting.

| File | Line(s) | Current Query Pattern | Migration Action | Module/Function |
|------|---------|----------------------|-----------------|-----------------|
| `src/objlib/database.py` | 705 | `WHERE status != ?` (LOCAL_DELETE) | Replace with `WHERE NOT is_deleted` | `get_active_files()` |
| `src/objlib/database.py` | 734-737 | `SELECT status, COUNT(*) ... GROUP BY status` | Replace with `SELECT gemini_state, COUNT(*) ... GROUP BY gemini_state` | `get_status_counts()` |
| `src/objlib/database.py` | 802 | `AND status != 'LOCAL_DELETE'` | Replace with `AND NOT is_deleted` | `get_citation_file()` |
| `src/objlib/database.py` | 878 | `WHERE status = 'uploaded' AND gemini_file_id IS NOT NULL` | Replace with `WHERE gemini_state = 'indexed'` | `get_canonical_file_ids()` (store sync) |
| `src/objlib/database.py` | 903 | `WHERE status = ? (PENDING)` | Replace with `WHERE gemini_state = 'untracked'` | `get_pending_files()` |
| `src/objlib/database.py` | 955 | `AND status != 'LOCAL_DELETE'` | Replace with `AND NOT is_deleted` | `get_category_counts()` |
| `src/objlib/database.py` | 975 | `AND status != 'LOCAL_DELETE'` | Replace with `AND NOT is_deleted` | `get_course_counts()` |
| `src/objlib/database.py` | 1008 | `AND status != 'LOCAL_DELETE'` | Replace with `AND NOT is_deleted` | `get_files_by_course()` |
| `src/objlib/database.py` | 1044 | `AND status != 'LOCAL_DELETE'` | Replace with `AND NOT is_deleted` | `get_items_by_category()` |
| `src/objlib/database.py` | 1082 | `status != 'LOCAL_DELETE'` | Replace with `NOT is_deleted` | `filter_files_by_metadata()` |
| `src/objlib/database.py` | 1408 | `AND status != 'LOCAL_DELETE'` | Replace with `AND NOT is_deleted` | `get_entity_stats()` (total_txt) |
| `src/objlib/database.py` | 1416-1430 | `AND status != 'LOCAL_DELETE'` (3 queries) | Replace with `AND NOT is_deleted` | `get_entity_stats()` (counts) |
| `src/objlib/database.py` | 1488 | `AND status != 'LOCAL_DELETE'` | Replace with `AND NOT is_deleted` | `get_files_needing_entity_extraction()` (pending) |
| `src/objlib/database.py` | 1493 | `AND status = 'uploaded'` | Replace with `AND gemini_state = 'indexed'` | `get_files_needing_entity_extraction()` (backfill) |
| `src/objlib/database.py` | 1499 | `AND status != 'LOCAL_DELETE'` | Replace with `AND NOT is_deleted` | `get_files_needing_entity_extraction()` (force) |
| `src/objlib/database.py` | 1506 | `AND status != 'LOCAL_DELETE'` | Replace with `AND NOT is_deleted` | `get_files_needing_entity_extraction()` (upgrade) |
| `src/objlib/database.py` | 1596-1597 | `status = 'missing'`, `status != 'missing'` | Replace with `missing_since IS NOT NULL` / `missing_since IS NULL` (drop status write) | `mark_missing()` |
| `src/objlib/database.py` | 1616, 1625 | `WHERE status = 'missing'` | Replace with `WHERE missing_since IS NOT NULL` | `get_missing_files()` |
| `src/objlib/database.py` | 1752, 1765 | `SELECT ... status`, `row["status"]` | Remove status from SELECT; return gemini_state instead | `get_file_with_sync_data()` |
| `src/objlib/database.py` | 1779 | `WHERE status NOT IN (?, ?)` (LOCAL_DELETE, MISSING) | Replace with `WHERE NOT is_deleted AND missing_since IS NULL` | `get_all_active_files_with_mtime()` |
| `src/objlib/cli.py` | 261-269 | `get_status_counts()` display | Rewrite to show `gemini_state` counts | `status` command |
| `src/objlib/cli.py` | 378 | `WHERE status = 'LOCAL_DELETE'` | Replace with `WHERE is_deleted = 1` | `purge` command |
| `src/objlib/cli.py` | 2047, 2058 | `SELECT ... status`, display `row['status']` | Replace with `gemini_state` | `metadata show` command |
| `src/objlib/extraction/batch_orchestrator.py` | 361 | `AND status != 'skipped'` | REMOVE filter (no skipped after migration; they are just untracked) | `_get_pending_files()` |
| `src/objlib/extraction/sampler.py` | 56 | `AND status != 'LOCAL_DELETE'` | Replace with `AND NOT is_deleted` | `sample_files()` |
| `src/objlib/upload/state.py` | 101 | `WHERE status = 'pending'` | Legacy path -- has FSM equivalent `get_fsm_pending_files()`. Remove or rewrite to `gemini_state = 'untracked'` | `get_pending_files()` |
| `src/objlib/upload/state.py` | 115 | `WHERE status = 'uploading'` | Legacy path for recovery. Remove or rewrite to `gemini_state = 'uploading'` | `get_uploading_files()` |
| `src/objlib/upload/state.py` | 404 | `AND f.status = 'pending'` | Legacy enriched upload path. Rewrite to `f.gemini_state = 'untracked'` | `get_enriched_pending_files()` |
| `src/objlib/upload/state.py` | 450, 457 | `f.status`, `f.status IN ('uploaded', 'failed')` | Legacy enriched upload path. Rewrite to `f.gemini_state IN ('indexed', 'failed')` | `get_files_to_reset()` |
| `src/objlib/upload/state.py` | 489 | `row["status"] == "failed"` | Legacy enriched upload path. Rewrite to `row["gemini_state"] == "failed"` | Reset decision logic |
| `src/objlib/upload/recovery.py` | 297-300 | `remote_expiration_ts, status`, `status IN ('uploading', 'uploaded')` | Legacy recovery path. Rewrite to `gemini_state IN ('uploading', 'indexed')` | Expiration deadline check |
| `src/objlib/sync/orchestrator.py` | 439-440 | `SELECT status ... WHERE status = 'LOCAL_DELETE'` | Replace with `WHERE is_deleted = 1` | Restore local deletes |

**Total Category A sites: 32**

---

## Category B: SQL WRITE Sites

Every SQL query or code path that writes (UPDATE/INSERT) the `status` column.

### FSM Dual-Write Sites (5 sites -- remove `status = '...'` from UPDATE)

| File | Line(s) | Current Query Pattern | Migration Action | Module/Function |
|------|---------|----------------------|-----------------|-----------------|
| `src/objlib/upload/state.py` | 532 | `status = 'uploading'` in UPDATE SET | **Remove the `status = 'uploading'` line** | `transition_to_uploading()` (FSM dual-write) |
| `src/objlib/upload/state.py` | 627 | `status = 'uploaded'` in UPDATE SET | **Remove the `status = 'uploaded'` line** | `transition_to_indexed()` (FSM dual-write) |
| `src/objlib/upload/state.py` | 674 | `status = 'failed'` in UPDATE SET | **Remove the `status = 'failed'` line** | `transition_to_failed()` (FSM dual-write) |
| `src/objlib/upload/state.py` | 808 | `status = 'pending'` in UPDATE SET | **Remove the `status = 'pending'` line** | `finalize_reset()` (FSM dual-write) |
| `src/objlib/upload/recovery.py` | 553 | `status = 'pending'` in UPDATE SET | **Remove the `status = 'pending'` line** | `retry_failed_file()` (dual-write) |

### Legacy Write Sites (13 sites -- remove status SET or replace with is_deleted/missing_since)

| File | Line(s) | Current Query Pattern | Migration Action | Module/Function |
|------|---------|----------------------|-----------------|-----------------|
| `src/objlib/upload/state.py` | 148 | `SET status = 'uploading'` | Remove status SET from UPDATE | `record_upload_intent()` (legacy) |
| `src/objlib/upload/state.py` | 202 | `SET status = 'uploaded'` | Remove status SET from UPDATE | `record_import_success()` (legacy) |
| `src/objlib/upload/state.py` | 219 | `SET status = 'failed'` | Remove status SET from UPDATE | `record_upload_failure()` (legacy) |
| `src/objlib/upload/recovery.py` | 192 | `SET status = 'uploaded'` | Remove status SET from UPDATE | Interrupted upload recovery (legacy) |
| `src/objlib/upload/recovery.py` | 371, 382 | `SET status = 'pending'` | Remove status SET from UPDATE | Reset file to pending (legacy) |
| `src/objlib/upload/orchestrator.py` | 685 | `SET status = 'pending'` | Remove status SET from UPDATE | `_reset_existing_files()` (legacy enriched upload) |
| `src/objlib/sync/orchestrator.py` | 453 | `SET status = 'uploaded'` | Replace with `SET is_deleted = 0` | Restore local deletes |
| `src/objlib/database.py` | 671, 692 | `record.status.value` | Remove status from UPSERT parameters | `upsert_file()` / `upsert_files()` |
| `src/objlib/database.py` | 724 | `SET status = ?` (LOCAL_DELETE) | Replace with `SET is_deleted = 1` | `mark_deleted()` |
| `src/objlib/database.py` | 919-920 | `SET status = ?` (update_file_status method) | **Remove entire method** | `update_file_status()` |
| `src/objlib/database.py` | 1596 | `SET status = 'missing'` | Remove status SET (keep `missing_since` SET only) | `mark_missing()` |
| `src/objlib/cli.py` | 2158 | `status = ?` (pending) | **REMOVE `--set-pending` flag** (FSM handles upload state) | `metadata update --set-pending` |
| `src/objlib/cli.py` | 2256 | `status = ?` (pending) | **REMOVE `--set-pending` flag** (FSM handles upload state) | `metadata batch-update --set-pending` |
| `src/objlib/cli.py` | 2698 | `SET status = 'pending'` | **REMOVE `--set-pending` flag** (FSM handles upload state) | `metadata extract-wave2 --set-pending` |

**Total Category B sites: 18**

---

## Category C: Schema/Infrastructure References

| File | Line(s) | Current Code Pattern | Migration Action | Module/Function |
|------|---------|---------------------|-----------------|-----------------|
| `src/objlib/database.py` | 31-32 | `status TEXT NOT NULL DEFAULT 'pending' CHECK(...)` | Update SCHEMA_SQL: remove status column, add `is_deleted`, add `gemini_state` CHECK | SCHEMA_SQL (V1 DDL) |
| `src/objlib/database.py` | 49 | `CREATE INDEX ... idx_status ON files(status)` | Remove from SCHEMA_SQL | SCHEMA_SQL index |
| `src/objlib/database.py` | 72-79 | `log_status_change` trigger definition | Remove from SCHEMA_SQL | SCHEMA_SQL trigger |
| `src/objlib/database.py` | 499 | `status` in UPSERT_SQL column list | Remove status from UPSERT_SQL column list | UPSERT_SQL template |
| `src/objlib/database.py` | 504-508 | `status = CASE ... ELSE files.status END` | Remove status from UPSERT ON CONFLICT clause | UPSERT_SQL ON CONFLICT |
| `src/objlib/models.py` | 10-18 | `class FileStatus(str, Enum)` | **Remove entire class** | FileStatus enum |
| `src/objlib/models.py` | 43 | `status: FileStatus = FileStatus.PENDING` | Remove field from FileRecord dataclass | FileRecord.status |
| `src/objlib/models.py` | 49 | `d["status"] = self.status.value` | Remove from `to_dict()` | FileRecord.to_dict() |
| `src/objlib/scanner.py` | 256 | `status=FileStatus.PENDING` | Remove `status=` param from FileRecord construction | Scanner FileRecord creation |

**Note:** Historical migration SQL strings (MIGRATION_V7_SQL at database.py lines 359-441) are left unchanged. They are frozen historical artifacts that only run on databases below V7.

**Total Category C sites: 9**

---

## Category D: Test References

| File | Line(s) | Description | Migration Action |
|------|---------|------------|-----------------|
| `tests/test_fsm.py` | 54, 61-69 | `_insert_test_file` helper with `status` param in INSERT | Remove status column from INSERT statement |
| `tests/test_fsm.py` | 255, 296, 308, 366, 435, 453, 476, 503, 534 | `status="uploaded"` / `status="failed"` in test setup calls | Remove status param from `_insert_test_file()` calls |
| `tests/test_upload.py` | 228-234 | INSERT with status column in test fixture | Remove status column from INSERT |
| `tests/test_upload.py` | 251-267 | Pending status tests (`WHERE status = 'pending'`) | Rewrite to use `gemini_state = 'untracked'` |
| `tests/test_upload.py` | 313-317 | `SELECT status ... assert row["status"] == "failed"` | Rewrite to use `gemini_state` assertions |
| `tests/test_upload.py` | 347-368 | INSERT with status column | Remove status column from INSERT |
| `tests/test_upload.py` | 406-431 | `SELECT status`, status assertions | Rewrite for `gemini_state` |
| `tests/test_database.py` | 22-32 | `_make_record` helper with `status` param | Remove status field from helper |
| `tests/test_database.py` | 70, 84-121 | Status assertions and `update_file_status` tests | Major rewrite -- remove `update_file_status` tests, update assertions |
| `tests/test_database.py` | 125-136 | `mark_deleted` status assertions | Rewrite to assert `is_deleted = 1` instead of `status = 'LOCAL_DELETE'` |
| `tests/test_database.py` | 144-200 | Status change and `get_status_counts` tests | Rewrite for `gemini_state` counts |
| `tests/test_database_crud.py` | 39-91 | Status assertions in CRUD tests | Major rewrite -- remove status assertions, add `gemini_state` assertions |
| `tests/test_database_crud.py` | 139-156 | `update_file_status` tests | **Remove entirely** (method being removed) |
| `tests/test_database_crud.py` | 353 | `mark_missing` status assertion | Rewrite to assert `missing_since IS NOT NULL` |
| `tests/test_schema.py` | 115-149 | Trigger and status change log tests | Major rewrite -- `log_status_change` trigger will be gone |
| `tests/test_search.py` | 167-198 | Custom schema with status column in test setup | Remove status from test schema setup |
| `tests/test_browse_filter.py` | 95 | `status=FileStatus.LOCAL_DELETE` | Rewrite to use `is_deleted` mechanism |
| `tests/conftest.py` | 128-137 | `populated_db` fixture with status in INSERT | Remove status from fixture INSERT |

**Note:** `tests/test_database_crud.py` line 279-290 references `entity_extraction_status` -- this is a different column and requires NO CHANGE.

**Total Category D sites: 18 entries across 8 test files**

---

## Category E: Script References

| File | Line(s) | Description | Migration Action |
|------|---------|------------|-----------------|
| `scripts/monitor_upload.sh` | 32 | `SELECT status, COUNT(*)` | Update to `SELECT gemini_state, COUNT(*) ... GROUP BY gemini_state` |
| `scripts/monitor_enriched_upload.sh` | 16-20, 38 | `SELECT status, COUNT(*)`, status filtering | Update to `gemini_state` grouping and filtering |
| `scripts/watch_progress.sh` | 17-21 | `CASE WHEN status = ...` | Update CASE to use `gemini_state` values |
| `scripts/check_status.sh` | 19-42 | Multiple status queries | Update all queries to use `gemini_state` and `is_deleted` |
| `scripts/monitor_extraction.sh` | 18 | `WHERE status = 'uploaded'` | Update to `WHERE gemini_state = 'indexed'` |
| `scripts/check_stability.py` | 13, 190 | Already uses `gemini_state` (comment references status) | Update comment only |
| `scripts/migrate_phase8.py` | 136-455 | Extensive status references | **Leave as-is** -- historical migration script, never runs again |

**Total Category E sites: 7 entries (6 requiring changes, 1 historical/frozen)**

---

## Category F: Non-Status References (NO CHANGE)

These files contain the word "status" but do NOT reference the `files.status` column. They were audited and confirmed to reference other uses of "status" (TUI status bar, Mistral batch status, entity extraction status, etc.).

| File | Lines | Description | Why No Change |
|------|-------|------------|---------------|
| `src/objlib/tui/app.py` | 68, 182, 217, etc. | `#status-bar` CSS selector and widget | TUI status bar, not DB column |
| `src/objlib/tui/widgets/results.py` | 5, 120, 150 | Status messages in search results | UI state, not DB column |
| `src/objlib/search/client.py` | 28 | Retry status display | API retry state |
| `src/objlib/extraction/batch_client.py` | 189-329 | Batch job status | Mistral API batch status |
| `src/objlib/extraction/batch_orchestrator.py` | 97, 230, 297-319 | Extraction status, poll_interval | AI extraction status |
| `src/objlib/extraction/orchestrator.py` | 194-697 | Extraction result status | AI extraction result status |
| `src/objlib/extraction/validator.py` | 52-288 | `ValidationResult.status` | Metadata validation status |
| `src/objlib/extraction/review.py` | 67-382 | AI metadata status display | `ai_metadata_status`, not `files.status` |
| `src/objlib/extraction/quality_gates.py` | 132-133 | Gate pass/fail status | Quality gate display |
| `src/objlib/entities/models.py` | 30 | `EntityExtractionResult.status` | Entity extraction status |
| `src/objlib/entities/extractor.py` | 117, 151 | `status="entities_done"` | Entity extraction result |
| `src/objlib/upload/progress.py` | 53-175 | Rich progress bar status fields | UI progress display |
| `src/objlib/upload/orchestrator.py` | 256, 829, 1232 | Batch status (completed/failed) | `upload_batches.status`, not `files.status` |
| `src/objlib/database.py` | 126-127 | `upload_batches` table status column | Different table entirely |
| `src/objlib/database.py` | 1163-1253 | `ai_metadata_status` methods | Different column (`ai_metadata_status`) |
| `src/objlib/database.py` | 1357-1389 | `entity_extraction_status` | Different column |
| `src/objlib/cli.py` | 278-284 | `def status()` CLI command name | Function name, not column |
| `src/objlib/cli.py` | 2719-2755 | `--status` flag for metadata review | `ai_metadata_status` filter |
| `tests/test_tui.py` | 626-1196 | TUI status bar tests | UI tests, not DB column |
| `tests/test_entity_extraction.py` | 234-280 | Entity result status assertions | `entity_extraction_status` |

**Total Category F entries: 20 (all confirmed NO CHANGE)**

---

## Locked Decisions Summary

These decisions were made during the Phase 13 discuss phase and are locked for plan 13-02 execution.

1. **gemini_state is already authoritative** -- `status` is legacy metadata only. No code should read `status` to determine current state; all reads switch to `gemini_state`.

2. **No backfill needed** -- Phase 8 pre-populated all `gemini_state` values. Verified: `SELECT COUNT(*) FROM files WHERE gemini_state IS NULL` returns 0.

3. **Physical DROP COLUMN in V11** -- Plan 13-02 executes a V11 DB migration that physically drops the `status` column. Clean end to the migration window.

4. **CHECK constraint on gemini_state in V11** -- `CHECK(gemini_state IN ('untracked','uploading','processing','indexed','failed'))` added in the same table rebuild. Defense-in-depth.

5. **V7 full table rebuild pattern** -- V11 uses the proven V7 pattern: CREATE TABLE files_v11 -> INSERT ... SELECT -> DROP TABLE files -> ALTER TABLE RENAME. Required because SQLite cannot add CHECK constraints via ALTER TABLE.

6. **TUI labels: display gemini_state as-is** -- No translation layer. Values like `indexed`, `failed`, `untracked` are already user-meaningful.

7. **--set-pending flags: REMOVE** -- Three CLI commands (`metadata update`, `metadata batch-update`, `metadata extract-wave2`) have `--set-pending` flags that wrote `status = 'pending'`. These are removed. The FSM handles upload state via `gemini_state`.

8. **is_deleted replaces LOCAL_DELETE** -- New `is_deleted INTEGER NOT NULL DEFAULT 0` column in V11. Replaces `status = 'LOCAL_DELETE'` filtering with `is_deleted = 1`.

9. **missing_since replaces status='missing'** -- Existing `missing_since` column already tracks missing files. Drop `status = 'missing'` writes; use `missing_since IS NOT NULL` for queries.

10. **Legacy upload path methods: executor's discretion** -- Legacy methods in `AsyncUploadStateManager` (`get_pending_files`, `get_uploading_files`, `record_upload_intent`, etc.) can be removed or rewritten at the executor's discretion during plan 13-02.

---

## V11 Migration SQL

This is the complete V11 migration SQL that plan 13-02 will implement. It follows the V7 full table rebuild pattern proven in this codebase.

```sql
-- V11: Retire legacy status column, add CHECK on gemini_state, add is_deleted
-- Safety: drop partial migration artifact if previous attempt failed
DROP TABLE IF EXISTS files_v11;

-- Step 1: Create new table WITHOUT status column, WITH gemini_state CHECK
CREATE TABLE files_v11 (
    file_path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    metadata_json TEXT,
    metadata_quality TEXT DEFAULT 'unknown'
        CHECK(metadata_quality IN ('complete', 'partial', 'minimal', 'none', 'unknown')),
    -- status column REMOVED
    is_deleted INTEGER NOT NULL DEFAULT 0,  -- replaces status='LOCAL_DELETE'
    error_message TEXT,
    gemini_file_uri TEXT,
    gemini_file_id TEXT,
    upload_timestamp TEXT,
    remote_expiration_ts TEXT,
    embedding_model_version TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    ai_metadata_status TEXT DEFAULT 'pending',
    ai_confidence_score REAL,
    entity_extraction_version TEXT,
    entity_extraction_status TEXT DEFAULT 'pending',
    upload_attempt_count INTEGER DEFAULT 0,
    last_upload_hash TEXT,
    mtime REAL,
    orphaned_gemini_file_id TEXT,
    missing_since TEXT,
    upload_hash TEXT,
    enrichment_version TEXT,
    gemini_store_doc_id TEXT,
    gemini_state TEXT NOT NULL DEFAULT 'untracked'
        CHECK(gemini_state IN ('untracked','uploading','processing','indexed','failed')),
    gemini_state_updated_at TEXT,
    version INTEGER NOT NULL DEFAULT 0,
    intent_type TEXT,
    intent_started_at TEXT,
    intent_api_calls_completed INTEGER
);

-- Step 2: Copy all existing data (omit status, derive is_deleted from status)
INSERT INTO files_v11 (
    file_path, content_hash, filename, file_size,
    metadata_json, metadata_quality,
    is_deleted,
    error_message,
    gemini_file_uri, gemini_file_id, upload_timestamp,
    remote_expiration_ts, embedding_model_version,
    created_at, updated_at,
    ai_metadata_status, ai_confidence_score,
    entity_extraction_version, entity_extraction_status,
    upload_attempt_count, last_upload_hash,
    mtime, orphaned_gemini_file_id, missing_since,
    upload_hash, enrichment_version,
    gemini_store_doc_id, gemini_state, gemini_state_updated_at,
    version, intent_type, intent_started_at, intent_api_calls_completed
)
SELECT
    file_path, content_hash, filename, file_size,
    metadata_json, metadata_quality,
    CASE WHEN status = 'LOCAL_DELETE' THEN 1 ELSE 0 END,
    error_message,
    gemini_file_uri, gemini_file_id, upload_timestamp,
    remote_expiration_ts, embedding_model_version,
    created_at, updated_at,
    ai_metadata_status, ai_confidence_score,
    entity_extraction_version, entity_extraction_status,
    upload_attempt_count, last_upload_hash,
    mtime, orphaned_gemini_file_id, missing_since,
    upload_hash, enrichment_version,
    gemini_store_doc_id, gemini_state, gemini_state_updated_at,
    version, intent_type, intent_started_at, intent_api_calls_completed
FROM files;

-- Step 3: Drop old table, rename new
DROP TABLE files;
ALTER TABLE files_v11 RENAME TO files;

-- Step 4: Recreate indexes (NO idx_status, ADD idx_is_deleted optionally)
CREATE INDEX idx_content_hash ON files(content_hash);
CREATE INDEX idx_metadata_quality ON files(metadata_quality);
CREATE INDEX idx_intent_type ON files(intent_type);
CREATE INDEX idx_gemini_state ON files(gemini_state);

-- Step 5: Recreate triggers (NO log_status_change)
CREATE TRIGGER update_files_timestamp
    AFTER UPDATE ON files
    FOR EACH ROW
    BEGIN
        UPDATE files SET updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')
        WHERE file_path = NEW.file_path;
    END;
```

**Key differences from V7 migration:**
- `status` column omitted from new table definition
- `status` column omitted from INSERT ... SELECT (derived as `is_deleted` via CASE)
- `log_status_change` trigger NOT recreated (historical data preserved in `_processing_log`)
- `idx_status` index NOT recreated
- `gemini_state` gets CHECK constraint
- New `is_deleted` column added (INTEGER NOT NULL DEFAULT 0)

**SCHEMA_SQL update note:** The V1 DDL (`SCHEMA_SQL`) in `database.py` must also be updated to match V11 schema for fresh database creation. Fresh databases should skip all migrations and set `PRAGMA user_version = 11` directly.

---

## Summary Statistics

| Category | Count | Description |
|----------|-------|-------------|
| A: SQL READ | 32 | Queries reading `status` for filter/group/select |
| B: SQL WRITE | 18 | Queries/code writing `status` (5 FSM dual-write + 13 legacy) |
| C: Schema/Infrastructure | 9 | DDL, UPSERT template, enum, dataclass |
| D: Tests | 18 entries across 8 files | Test fixtures, assertions, helpers |
| E: Scripts | 7 (6 active + 1 frozen) | Shell/Python monitoring scripts |
| F: No Change | 20 | Audited, confirmed NOT `files.status` references |
| **Total inventoried** | **104** | **84 requiring changes + 20 no-change** |
