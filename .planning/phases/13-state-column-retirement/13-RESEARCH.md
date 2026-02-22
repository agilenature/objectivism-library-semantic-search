# Phase 13: State Column Retirement - Research

**Researched:** 2026-02-22
**Domain:** SQLite schema migration, legacy column retirement, code audit
**Confidence:** HIGH

## Summary

Phase 13 retires the legacy `status` column from the `files` table. Research confirms that `gemini_state` is fully populated (zero NULLs), the legacy `status` column holds exactly two values (`uploaded`: 1748, `skipped`: 136), and the dual-write pattern in the FSM transition methods is the only active write path to `status`. The live DB cross-tabulation shows perfect alignment: all 50 `gemini_state='indexed'` files have `status='uploaded'`, and all 136 `skipped` files are `gemini_state='untracked'`.

The codebase has **extensive** status references -- 80+ lines across 12 source files and 8 test files. These fall into clear categories: (1) SQL queries reading `status` for filtering/grouping, (2) SQL writes setting `status` in FSM transitions and legacy upload paths, (3) schema definitions with CHECK constraints, (4) trigger/index infrastructure, and (5) the `FileStatus` enum and `FileRecord.status` field in `models.py`. The V11 migration must use a full table rebuild (like V7) because adding a CHECK constraint to `gemini_state` requires `CREATE TABLE ... INSERT ... DROP ... RENAME`.

**Critical discovery:** The `status` column serves double duty -- it tracks both upload state AND file presence state (`LOCAL_DELETE`, `missing`). However, **zero files currently have LOCAL_DELETE or missing status in the live DB**, and the `missing_since` column already exists as a parallel tracking mechanism. This simplifies the migration significantly.

**Primary recommendation:** Use the V7 table rebuild pattern for V11 -- it is proven in this codebase. Drop the `log_status_change` trigger, the `idx_status` index, and the `status` column simultaneously. Add `CHECK(gemini_state IN ('untracked','uploading','processing','indexed','failed'))` in the rebuilt table definition. Replace `status != 'LOCAL_DELETE'` filters with `is_deleted = 0` (new boolean column) and `status = 'missing'` with `missing_since IS NOT NULL`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
1. gemini_state is already authoritative -- status is legacy metadata only
2. No backfill needed -- Phase 8 pre-populated all gemini_state values (verify no NULLs)
3. Physical DROP COLUMN status in plan 13-02 via V11 DB migration (clean end to window)
4. ADD CHECK (gemini_state IN ('untracked','uploading','processing','indexed','failed')) in same V11 migration
5. SC-1 inventory artifact at docs/migrations/phase13-status-inventory.md (Markdown table format)
6. Query-site scope: all Python files under src/, tests/, scripts/
7. 2 plans as designed: 13-01 (audit) and 13-02 (migration + test pass)
8. TUI labels: display gemini_state values as-is; no translation layer

### Claude's Discretion
- V11 migration implementation strategy (simple DROP vs full table rebuild)
- Order of code changes within 13-02

### Deferred Ideas (OUT OF SCOPE)
- Error persistence model
- NOT NULL constraint on gemini_state (documented as invariant in code instead)
</user_constraints>

## Live Database State

### Current Schema Version
`PRAGMA user_version = 10`

### Status Column Values (Live DB)
| status | count | gemini_state correlation |
|--------|-------|------------------------|
| `uploaded` | 1748 | 50 are `indexed`, 1698 are `untracked` |
| `skipped` | 136 | all 136 are `untracked` |

**Total files:** 1884

**CONFIRMED ABSENT status values (zero rows):**
- `pending`: 0
- `uploading`: 0
- `failed`: 0
- `LOCAL_DELETE`: 0
- `missing`: 0
- `error`: 0

**Also confirmed:** `missing_since IS NOT NULL` count: 0

### Gemini State Column Values (Live DB)
| gemini_state | count |
|-------------|-------|
| `indexed` | 50 |
| `untracked` | 1834 |

### NULL Check
- `gemini_state IS NULL`: **0** (confirmed -- Phase 8 populated all rows)
- No transient states (`uploading`, `processing`): **0** (Phase 12 completed cleanly)

### Existing CHECK Constraint on Status
```sql
CHECK(status IN ('pending', 'uploading', 'uploaded', 'failed', 'skipped', 'LOCAL_DELETE', 'missing', 'error'))
```

### Existing Trigger on Status
```sql
CREATE TRIGGER log_status_change
    AFTER UPDATE OF status ON files
    FOR EACH ROW
    WHEN OLD.status != NEW.status
    BEGIN
        INSERT INTO _processing_log(file_path, old_status, new_status)
        VALUES (NEW.file_path, OLD.status, NEW.status);
    END;
```

### Existing Index on Status
```sql
CREATE INDEX idx_status ON files(status);
```

### _processing_log Table
- 19,080 rows of historical status transition logs
- Table remains after migration (historical data preserved)
- Trigger will be dropped (no more status column to watch)

## Complete Status Reference Inventory

### Category A: SQL Queries That READ Status (filter/group/select)

These must be rewritten to use `gemini_state` or alternative mechanisms.

| File | Line(s) | Code Pattern | Category | Migration Action |
|------|---------|-------------|----------|-----------------|
| `src/objlib/database.py` | 705 | `WHERE status != ?` (LOCAL_DELETE) | Active file filter | Replace with `WHERE NOT is_deleted` |
| `src/objlib/database.py` | 734-737 | `SELECT status, COUNT(*) ... GROUP BY status` | Status counts | Replace with `gemini_state` grouping |
| `src/objlib/database.py` | 802 | `AND status != 'LOCAL_DELETE'` | Citation lookup filter | Replace with `AND NOT is_deleted` |
| `src/objlib/database.py` | 878 | `WHERE status = 'uploaded' AND gemini_file_id IS NOT NULL` | Store sync canonical IDs | Replace with `WHERE gemini_state = 'indexed'` |
| `src/objlib/database.py` | 903 | `WHERE status = ? (PENDING)` | Get pending files | Replace with `WHERE gemini_state = 'untracked'` |
| `src/objlib/database.py` | 955 | `AND status != 'LOCAL_DELETE'` | Category counts | Replace with `AND NOT is_deleted` |
| `src/objlib/database.py` | 975 | `AND status != 'LOCAL_DELETE'` | Course counts | Replace with `AND NOT is_deleted` |
| `src/objlib/database.py` | 1008 | `AND status != 'LOCAL_DELETE'` | Files by course | Replace with `AND NOT is_deleted` |
| `src/objlib/database.py` | 1044 | `AND status != 'LOCAL_DELETE'` | Items by category | Replace with `AND NOT is_deleted` |
| `src/objlib/database.py` | 1082 | `status != 'LOCAL_DELETE'` | Filter files by metadata | Replace with `NOT is_deleted` |
| `src/objlib/database.py` | 1408 | `AND status != 'LOCAL_DELETE'` | Entity stats total_txt | Replace with `AND NOT is_deleted` |
| `src/objlib/database.py` | 1416-1430 | `AND status != 'LOCAL_DELETE'` (3 queries) | Entity stats counts | Replace with `AND NOT is_deleted` |
| `src/objlib/database.py` | 1488 | `AND status != 'LOCAL_DELETE'` | Files needing entity extraction (pending) | Replace with `AND NOT is_deleted` |
| `src/objlib/database.py` | 1493 | `AND status = 'uploaded'` | Files needing entity extraction (backfill) | Replace with `gemini_state = 'indexed'` |
| `src/objlib/database.py` | 1499 | `AND status != 'LOCAL_DELETE'` | Files needing entity extraction (force) | Replace with `AND NOT is_deleted` |
| `src/objlib/database.py` | 1506 | `AND status != 'LOCAL_DELETE'` | Files needing entity extraction (upgrade) | Replace with `AND NOT is_deleted` |
| `src/objlib/database.py` | 1596-1597 | `status = 'missing'`, `status != 'missing'` | Mark missing | Replace with `missing_since` only (drop status write) |
| `src/objlib/database.py` | 1616, 1625 | `WHERE status = 'missing'` | Get missing files | Replace with `WHERE missing_since IS NOT NULL` |
| `src/objlib/database.py` | 1752, 1765 | `SELECT ... status`, `row["status"]` | get_file_with_sync_data | Remove status from SELECT, return gemini_state instead |
| `src/objlib/database.py` | 1779 | `WHERE status NOT IN (?, ?)` (LOCAL_DELETE, MISSING) | get_all_active_files_with_mtime | Replace with `WHERE NOT is_deleted AND missing_since IS NULL` |
| `src/objlib/cli.py` | 261-269 | `get_status_counts()` display | Status command | Rewrite to show gemini_state counts |
| `src/objlib/cli.py` | 378 | `WHERE status = 'LOCAL_DELETE'` | Purge command | Replace with `WHERE is_deleted = 1` |
| `src/objlib/cli.py` | 2047, 2058 | `SELECT ... status`, display `row['status']` | Metadata show command | Replace with gemini_state |
| `src/objlib/extraction/batch_orchestrator.py` | 361 | `AND status != 'skipped'` | Batch extraction pending files | Remove (no skipped files after migration -- they're just untracked) |
| `src/objlib/extraction/sampler.py` | 56 | `AND status != 'LOCAL_DELETE'` | Extraction sampling | Replace with `AND NOT is_deleted` |
| `src/objlib/upload/state.py` | 101 | `WHERE status = 'pending'` | get_pending_files | Legacy path -- has FSM equivalent `get_fsm_pending_files()` |
| `src/objlib/upload/state.py` | 115 | `WHERE status = 'uploading'` | get_uploading_files | Legacy path for recovery |
| `src/objlib/upload/state.py` | 404 | `AND f.status = 'pending'` | get_enriched_pending_files | Legacy enriched upload path |
| `src/objlib/upload/state.py` | 450, 457 | `f.status`, `f.status IN ('uploaded', 'failed')` | get_files_to_reset | Legacy enriched upload path |
| `src/objlib/upload/state.py` | 489 | `row["status"] == "failed"` | Reset decision logic | Legacy enriched upload path |
| `src/objlib/upload/recovery.py` | 297-300 | `remote_expiration_ts, status`, `status IN ('uploading', 'uploaded')` | Expiration deadline check | Legacy recovery path |
| `src/objlib/sync/orchestrator.py` | 439-440 | `SELECT status ... WHERE status = 'LOCAL_DELETE'` | Restore local deletes | Replace with `WHERE is_deleted = 1` |

### Category B: SQL Queries/Code That WRITE Status

These are the dual-write sites that must stop writing status.

| File | Line(s) | Code Pattern | Category | Migration Action |
|------|---------|-------------|----------|-----------------|
| `src/objlib/upload/state.py` | 148 | `SET status = 'uploading'` | record_upload_intent | Legacy write -- remove status SET |
| `src/objlib/upload/state.py` | 202 | `SET status = 'uploaded'` | record_import_success | Legacy write -- remove status SET |
| `src/objlib/upload/state.py` | 219 | `SET status = 'failed'` | record_upload_failure | Legacy write -- remove status SET |
| `src/objlib/upload/state.py` | 532 | `status = 'uploading'` | transition_to_uploading (FSM dual-write) | **Remove the `status = 'uploading'` line** |
| `src/objlib/upload/state.py` | 627 | `status = 'uploaded'` | transition_to_indexed (FSM dual-write) | **Remove the `status = 'uploaded'` line** |
| `src/objlib/upload/state.py` | 674 | `status = 'failed'` | transition_to_failed (FSM dual-write) | **Remove the `status = 'failed'` line** |
| `src/objlib/upload/state.py` | 808 | `status = 'pending'` | finalize_reset (FSM dual-write) | **Remove the `status = 'pending'` line** |
| `src/objlib/upload/recovery.py` | 192 | `SET status = 'uploaded'` | Interrupted upload recovery | Legacy recovery path -- remove status SET |
| `src/objlib/upload/recovery.py` | 371, 382 | `SET status = 'pending'` | Reset file to pending | Legacy recovery path -- remove status SET |
| `src/objlib/upload/recovery.py` | 553 | `status = 'pending'` | retry_failed_file (dual-write) | **Remove the `status = 'pending'` line** |
| `src/objlib/upload/orchestrator.py` | 685 | `SET status = 'pending'` | _reset_existing_files | Legacy enriched upload -- remove status SET |
| `src/objlib/sync/orchestrator.py` | 453 | `SET status = 'uploaded'` | Restore local deletes | Replace with `SET is_deleted = 0` |
| `src/objlib/database.py` | 671, 692 | `record.status.value` | UPSERT SQL | Remove status from UPSERT |
| `src/objlib/database.py` | 724 | `SET status = ?` (LOCAL_DELETE) | mark_deleted | Replace with `SET is_deleted = 1` |
| `src/objlib/database.py` | 919-920 | `status = ?` in SET clause | update_file_status method | **Remove entire method** |
| `src/objlib/database.py` | 1596 | `SET status = 'missing'` | mark_missing | Remove status SET (keep missing_since SET) |
| `src/objlib/cli.py` | 2158 | `status = ?` (pending) | metadata update --set-pending | Remove or repurpose |
| `src/objlib/cli.py` | 2256 | `status = ?` (pending) | metadata batch-update --set-pending | Remove or repurpose |
| `src/objlib/cli.py` | 2698 | `SET status = 'pending'` | Wave 2 extraction --set-pending | Remove or repurpose |

### Category C: Schema/Infrastructure References

| File | Line(s) | Code Pattern | Category | Migration Action |
|------|---------|-------------|----------|-----------------|
| `src/objlib/database.py` | 31-32 | `status TEXT NOT NULL DEFAULT 'pending' CHECK(...)` | SCHEMA_SQL (V1 DDL) | Update DDL to remove status column |
| `src/objlib/database.py` | 49 | `CREATE INDEX ... idx_status ON files(status)` | SCHEMA_SQL index | Remove |
| `src/objlib/database.py` | 72-79 | `log_status_change` trigger | SCHEMA_SQL trigger | Remove trigger definition |
| `src/objlib/database.py` | 359-360 | `status TEXT ...` | MIGRATION_V7_SQL table rebuild | Leave as-is (historical V7) |
| `src/objlib/database.py` | 397-407 | `status` in INSERT column list | MIGRATION_V7_SQL data copy | Leave as-is (historical V7) |
| `src/objlib/database.py` | 422 | `idx_status` in V7 index recreation | MIGRATION_V7_SQL | Leave as-is (historical V7) |
| `src/objlib/database.py` | 434-441 | `log_status_change` in V7 trigger recreation | MIGRATION_V7_SQL | Leave as-is (historical V7) |
| `src/objlib/database.py` | 499 | `status` in UPSERT_SQL column list | UPSERT SQL template | Remove status from UPSERT |
| `src/objlib/database.py` | 504-508 | `status = CASE ... ELSE files.status END` | UPSERT ON CONFLICT | Remove status from UPSERT |
| `src/objlib/models.py` | 10-18 | `class FileStatus(str, Enum)` | FileStatus enum | **Remove entirely** |
| `src/objlib/models.py` | 43 | `status: FileStatus = FileStatus.PENDING` | FileRecord dataclass | Remove field |
| `src/objlib/models.py` | 49 | `d["status"] = self.status.value` | to_dict() | Remove |
| `src/objlib/scanner.py` | 256 | `status=FileStatus.PENDING` | FileRecord construction | Remove |

### Category D: Test References

| File | Line(s) | Description | Migration Action |
|------|---------|------------|-----------------|
| `tests/test_fsm.py` | 54, 61-69 | `_insert_test_file` with status param | Remove status from INSERT |
| `tests/test_fsm.py` | 255, 296, 308, 366, 435, 453, 476, 503, 534 | `status="uploaded"` / `status="failed"` in test setup | Remove status param |
| `tests/test_upload.py` | 228-234 | INSERT with status column | Remove status column |
| `tests/test_upload.py` | 251-267 | Pending status tests | Rewrite for gemini_state |
| `tests/test_upload.py` | 313-317 | `SELECT status ... assert row["status"] == "failed"` | Rewrite for gemini_state |
| `tests/test_upload.py` | 347-368 | INSERT with status column | Remove status |
| `tests/test_upload.py` | 406-431 | `SELECT status`, status assertions | Rewrite for gemini_state |
| `tests/test_database.py` | 22-32 | `_make_record` with status param | Remove status |
| `tests/test_database.py` | 70, 84-121 | Status assertions and update_file_status tests | Major rewrite needed |
| `tests/test_database.py` | 125-136 | mark_deleted status assertions | Rewrite for is_deleted |
| `tests/test_database.py` | 144-200 | Status change and get_status_counts tests | Rewrite for gemini_state counts |
| `tests/test_database_crud.py` | 39-91 | Status assertions in CRUD tests | Major rewrite needed |
| `tests/test_database_crud.py` | 139-156 | update_file_status tests | Remove (method removed) |
| `tests/test_database_crud.py` | 279-290 | Entity result status | Unrelated (entity_extraction_status -- NO CHANGE) |
| `tests/test_database_crud.py` | 353 | mark_missing status | Rewrite for missing_since |
| `tests/test_schema.py` | 115-149 | Trigger and status change log tests | Major rewrite (trigger will be gone) |
| `tests/test_search.py` | 167-198 | Custom schema with status column | Rewrite schema setup |
| `tests/test_browse_filter.py` | 95 | `status=FileStatus.LOCAL_DELETE` | Rewrite for is_deleted mechanism |
| `tests/conftest.py` | 128-137 | `populated_db` fixture with status | Rewrite fixture |

### Category E: Script References

| File | Line(s) | Description | Migration Action |
|------|---------|------------|-----------------|
| `scripts/monitor_upload.sh` | 32 | `SELECT status, COUNT(*)` | Update to gemini_state |
| `scripts/monitor_enriched_upload.sh` | 16-20, 38 | `SELECT status, COUNT(*)`, status filtering | Update to gemini_state |
| `scripts/watch_progress.sh` | 17-21 | `CASE WHEN status = ...` | Update to gemini_state |
| `scripts/check_status.sh` | 19-42 | Multiple status queries | Update to gemini_state |
| `scripts/monitor_extraction.sh` | 18 | `WHERE status = 'uploaded'` | Update to `gemini_state = 'indexed'` |
| `scripts/check_stability.py` | 13, 190 | Already uses gemini_state (comment references status) | Update comment only |
| `scripts/migrate_phase8.py` | 136-455 | Extensive status references | Historical script -- leave as-is |

### Category F: Non-Status "status" References (NO CHANGE NEEDED)

These use the word "status" but do NOT reference the `files.status` column:

| File | Line(s) | Description | Why No Change |
|------|---------|------------|---------------|
| `src/objlib/tui/app.py` | 68, 182, 217, etc. | `#status-bar` CSS selector and widget | TUI status bar, not DB column |
| `src/objlib/tui/widgets/results.py` | 5, 120, 150 | Status messages in search results | UI state, not DB column |
| `src/objlib/search/client.py` | 28 | Retry status display | API retry state |
| `src/objlib/extraction/batch_client.py` | 189-329 | Batch job status | Mistral API batch status |
| `src/objlib/extraction/batch_orchestrator.py` | 97, 230, 297-319 | Extraction status, poll_interval | AI extraction status |
| `src/objlib/extraction/orchestrator.py` | 194-697 | Extraction result status | AI extraction result status |
| `src/objlib/extraction/validator.py` | 52-288 | ValidationResult.status | Metadata validation status |
| `src/objlib/extraction/review.py` | 67-382 | AI metadata status display | ai_metadata_status, not files.status |
| `src/objlib/extraction/quality_gates.py` | 132-133 | Gate pass/fail status | Quality gate display |
| `src/objlib/entities/models.py` | 30 | EntityExtractionResult.status | Entity extraction status |
| `src/objlib/entities/extractor.py` | 117, 151 | `status="entities_done"` | Entity extraction result |
| `src/objlib/upload/progress.py` | 53-175 | Rich progress bar status fields | UI progress display |
| `src/objlib/upload/orchestrator.py` | 256, 829, 1232 | Batch status (completed/failed) | upload_batches.status, not files.status |
| `src/objlib/database.py` | 126-127 | `upload_batches` table status column | Different table entirely |
| `src/objlib/database.py` | 1163-1253 | ai_metadata_status methods | Different column (ai_metadata_status) |
| `src/objlib/database.py` | 1357-1389 | entity_extraction_status | Different column |
| `src/objlib/cli.py` | 278-284 | `def status()` CLI command name | Function name, not column |
| `src/objlib/cli.py` | 2719-2755 | `--status` flag for metadata review | ai_metadata_status filter |
| `tests/test_tui.py` | 626-1196 | TUI status bar tests | UI tests, not DB column |
| `tests/test_entity_extraction.py` | 234-280 | Entity result status assertions | entity_extraction_status |

## CRITICAL DISCOVERY: LOCAL_DELETE / MISSING Status Values

**The `status` column serves double duty** -- it tracks both upload state AND file presence state (`LOCAL_DELETE`, `missing`). These have NO `gemini_state` equivalent.

**However, the live DB confirms ZERO files with these states:**
- `LOCAL_DELETE`: 0 rows
- `missing`: 0 rows
- `missing_since IS NOT NULL`: 0 rows

**This simplifies migration significantly.** No data migration is needed for these states -- only code path adjustments.

**Recommended replacement mechanism:**

1. **LOCAL_DELETE** -> New `is_deleted` BOOLEAN DEFAULT 0 column (added in V11 table rebuild)
   - `mark_deleted()`: sets `is_deleted = 1` instead of `status = 'LOCAL_DELETE'`
   - All `status != 'LOCAL_DELETE'` filters become `NOT is_deleted` or `is_deleted = 0`
   - This is cleaner than overloading `gemini_state` (which is Gemini-specific)

2. **missing** -> Use existing `missing_since` column (already set by `mark_missing()`)
   - `mark_missing()`: only sets `missing_since = now()` (drops `status = 'missing'`)
   - `get_missing_files()`: queries `WHERE missing_since IS NOT NULL` instead of `WHERE status = 'missing'`
   - `get_all_active_files_with_mtime()`: replaces `status NOT IN (LOCAL_DELETE, MISSING)` with `NOT is_deleted AND missing_since IS NULL`

3. **FileStatus enum**: Remove entirely. Replace `FileStatus.LOCAL_DELETE` usage with direct `is_deleted` boolean operations. Replace `FileStatus.MISSING` with `missing_since` operations.

## Existing Migration Pattern (V9/V10)

### V9 Pattern (Phase 8 -- ALTER TABLE ADD COLUMN)
```python
if version < 9:
    for alter_sql in [
        "ALTER TABLE files ADD COLUMN gemini_store_doc_id TEXT",
        "ALTER TABLE files ADD COLUMN gemini_state TEXT DEFAULT 'untracked'",
        "ALTER TABLE files ADD COLUMN gemini_state_updated_at TEXT",
    ]:
        try:
            self.conn.execute(alter_sql)
        except sqlite3.OperationalError:
            pass  # Column already exists
```
- Uses try/except for idempotency
- Individual ALTER TABLE statements (not executescript)
- Version guard: `if version < 9`

### V7 Pattern (Full Table Rebuild -- closest to V11 needs)
```python
if version < 7:
    self.conn.execute("PRAGMA foreign_keys = OFF")
    self.conn.executescript(MIGRATION_V7_SQL)
    self.conn.execute("PRAGMA foreign_keys = ON")
```
Where `MIGRATION_V7_SQL` does:
1. `DROP TABLE IF EXISTS files_v7` (safety)
2. `CREATE TABLE files_v7 (...)` with new schema
3. `INSERT INTO files_v7 (...) SELECT ... FROM files`
4. `DROP TABLE files`
5. `ALTER TABLE files_v7 RENAME TO files`
6. Recreate indexes
7. Recreate triggers

### V11 Migration Pattern: Recommendation

**Use the V7 full table rebuild pattern because:**
1. Adding CHECK constraint on `gemini_state` requires table rebuild (SQLite limitation -- confirmed by testing)
2. Adding `is_deleted` column in the same rebuild avoids a separate migration
3. Dropping `status` requires removing trigger and index first -- rebuild handles this implicitly
4. ~1,884 rows -- rebuild takes milliseconds
5. Proven pattern in this codebase (V7 did the same thing)

**Key differences from V7:**
- `status` column omitted from new table definition
- `status` column omitted from INSERT ... SELECT
- `log_status_change` trigger NOT recreated
- `idx_status` index NOT recreated
- `gemini_state` gets `CHECK(gemini_state IN ('untracked','uploading','processing','indexed','failed'))`
- New `is_deleted` BOOLEAN DEFAULT 0 column added

**SQLite version:** 3.51.0 (supports ALTER TABLE DROP COLUMN natively since 3.35.0, but table rebuild is still needed for CHECK)

**Verified by testing:** `ALTER TABLE ... ADD CONSTRAINT` and `ALTER TABLE ... ADD CHECK` are both unsupported in SQLite. Table rebuild is the only way to add CHECK constraints. Also verified: `ALTER TABLE DROP COLUMN` fails if a trigger references the column -- must drop trigger first.

## Architecture Patterns

### Recommended V11 Migration SQL Structure
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

-- Step 2: Copy all existing data (omit status, set is_deleted from status)
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

-- Step 4: Recreate indexes (NO idx_status, ADD idx_is_deleted)
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

### Files Table Current Column List (for V11 rebuild)
From live schema -- 32 columns currently, becoming 32 after migration (drop status, add is_deleted):

**Dropped:** `status` TEXT NOT NULL DEFAULT 'pending' CHECK(...)
**Added:** `is_deleted` INTEGER NOT NULL DEFAULT 0

All other 31 columns preserved exactly as-is.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Table rebuild migration | Custom migration framework | V7 pattern already proven in codebase | Tested, handles FK OFF, indexes, triggers |
| Status-to-gemini_state mapping | Runtime translation layer | Direct query rewrites | No ongoing overhead, clean break |
| LOCAL_DELETE filtering | Overloading gemini_state | `is_deleted` boolean column | Keep FSM states pure (5 states for Gemini lifecycle) |
| Missing file tracking | New missing status value | Existing `missing_since` column | Already implemented, more informative than boolean |

## Common Pitfalls

### Pitfall 1: LOCAL_DELETE and Missing File States
**What goes wrong:** Dropping `status` removes the `LOCAL_DELETE` and `missing` tracking that sync depends on.
**Why it happens:** `status` column serves double duty -- upload state AND file presence state.
**How to avoid:** Add `is_deleted` column in V11 rebuild. Use existing `missing_since` column for missing tracking. Both replacement mechanisms preserve exact semantics.
**Warning signs:** Tests for `mark_deleted()`, `mark_missing()`, `get_missing_files()`, purge command will all break if not updated.

### Pitfall 2: UPSERT_SQL References Status
**What goes wrong:** The `UPSERT_SQL` template includes `status` as a column with a CASE expression for conditional reset on hash change.
**Why it happens:** `upsert_file()` and `upsert_files()` pass `record.status.value` as a parameter.
**How to avoid:** Remove `status` from UPSERT_SQL. Remove `FileRecord.status` field. Scanner creates records with `status=FileStatus.PENDING` -- remove this. The UPSERT no longer needs to conditionally reset status on hash change since gemini_state is managed by the FSM.
**Warning signs:** Every `upsert_file()` call will fail if status column is gone but code still references it.

### Pitfall 3: Historical Migration SQL
**What goes wrong:** Someone modifies MIGRATION_V7_SQL to remove status references.
**Why it happens:** Enthusiasm for cleaning up all references.
**How to avoid:** MIGRATION_V7_SQL is historical -- it ran once and should never run again (DB is already at V10). Leave it unchanged. Only update: SCHEMA_SQL (V1 DDL) and new MIGRATION_V11_SQL. Previous migration strings are frozen.
**Warning signs:** V7 SQL is in the `version < 7` code path -- only runs on fresh databases or those below V7.

### Pitfall 4: FileStatus Enum Used Beyond Database
**What goes wrong:** Removing `FileStatus` breaks code that uses it for non-DB purposes.
**Why it happens:** `FileStatus.LOCAL_DELETE` and `FileStatus.MISSING` are used as markers in sync logic, scanner, and tests.
**How to avoid:** Search for all `FileStatus` imports and usages. Replace with direct boolean/string operations on the new columns. There are 8 files importing FileStatus.
**Warning signs:** Import errors for `FileStatus` across multiple modules.

### Pitfall 5: Dual-Write Lines in FSM Transitions
**What goes wrong:** The FSM `transition_to_*()` methods write both `gemini_state` and `status` in the same UPDATE. Removing `status` column without updating these SQL strings causes runtime errors.
**Why it happens:** Phase 12 added dual-write for backward compatibility.
**How to avoid:** Remove the `, status = '...'` fragments from exactly these 5 UPDATE statements in `state.py` and 1 in `recovery.py`:
  - `transition_to_uploading` (state.py line 532)
  - `transition_to_indexed` (state.py line 627)
  - `transition_to_failed` (state.py line 674)
  - `finalize_reset` (state.py line 808)
  - `retry_failed_file` (recovery.py line 553)

### Pitfall 6: Fresh Database Creation
**What goes wrong:** `SCHEMA_SQL` is run on fresh databases. If it still references `status`, fresh DBs will have the column.
**Why it happens:** V1 DDL creates the initial schema; migrations upgrade it.
**How to avoid:** Update `SCHEMA_SQL` to create the modern schema (without status, with is_deleted, with gemini_state CHECK). Then set `PRAGMA user_version = 11` at the end of `_setup_schema()`. The V11 migration only runs if version < 11.

### Pitfall 7: --set-pending CLI Options
**What goes wrong:** Three CLI commands have `--set-pending` flags that write `status = 'pending'`.
**Why it happens:** Legacy upload pipeline used status to trigger re-upload.
**How to avoid:** Either remove these flags (FSM handles upload state now) or repurpose them to reset `gemini_state = 'untracked'` via FSM transition. Decision needed in 13-01 audit.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|-----------------|--------------|--------|
| `status='uploaded'` | `gemini_state='indexed'` | Phase 8 (V9) | All new code uses gemini_state |
| `status='pending'` | `gemini_state='untracked'` | Phase 8 (V9) | Legacy upload path still uses status |
| `status='LOCAL_DELETE'` | `is_deleted = 1` | Phase 13 (V11) | Cleaner boolean flag |
| `status='missing'` | `missing_since IS NOT NULL` | Phase 13 (V11) | Already had the column |
| Dual-write (gemini_state + status) | Single-write (gemini_state only) | Phase 13 (this phase) | Removes backward compat overhead |
| `log_status_change` trigger | No equivalent | Phase 13 (V11) | Historical data preserved in _processing_log |

## Open Questions

### 1. --set-pending CLI Flag Fate
- **What we know:** Three CLI commands (`metadata update`, `metadata batch-update`, `metadata extract-wave2`) have `--set-pending` flags that set `status = 'pending'` to trigger re-upload.
- **What's unclear:** Should these be removed (the FSM pipeline doesn't use status='pending' anymore) or repurposed to set `gemini_state = 'untracked'`?
- **Recommendation:** Remove the `--set-pending` flags. The FSM upload pipeline uses `gemini_state = 'untracked'` to find pending files, and the FSM `reset` transition handles indexed-to-untracked. If a CLI "re-upload" capability is needed, it should go through the FSM.

### 2. Legacy Upload Path Methods
- **What we know:** `AsyncUploadStateManager` has legacy methods (`get_pending_files`, `get_uploading_files`, `record_upload_intent`, `record_import_success`, `record_upload_failure`) that operate on status column. The FSM equivalents exist (`get_fsm_pending_files`, `transition_to_*`).
- **What's unclear:** Are the legacy methods still called by any active code path?
- **Recommendation:** Check if `UploadOrchestrator` (non-FSM) is still used or only `FSMUploadOrchestrator`. If only FSM path is active, the legacy methods can be removed or left as dead code (they'll fail gracefully since status column won't exist). The planner should audit call sites.

### 3. SCHEMA_SQL Update Strategy
- **What we know:** `SCHEMA_SQL` is run on every `Database()` init (uses `CREATE TABLE IF NOT EXISTS`). It defines V1 schema. Migrations upgrade from there.
- **What's unclear:** Should SCHEMA_SQL be updated to represent the V11 schema (no status, with is_deleted, with gemini_state CHECK) or left as V1 for historical reference?
- **Recommendation:** Update SCHEMA_SQL to V11 schema. This ensures fresh databases start correct. The `version < 11` guard in `_setup_schema()` skips the migration for fresh databases (where `PRAGMA user_version` starts at 0 but the schema is already modern because SCHEMA_SQL creates it).

**Wait -- this creates a subtlety:** If SCHEMA_SQL creates a modern schema WITHOUT status, then the V7 migration (which references status) would fail on a completely fresh database that somehow ends up at version < 7. Resolution: SCHEMA_SQL should create the final schema, and `_setup_schema()` should set `PRAGMA user_version = 11` at the end. All `if version < N` guards still run but the `CREATE TABLE IF NOT EXISTS` in SCHEMA_SQL means V7's `files_v7` logic would try to copy from a `files` table that has no `status` column. **This is actually the existing pattern** -- V7 SQL assumes the old schema. The solution: if version is 0 (fresh DB), skip all migrations and set user_version = 11 directly.

## Sources

### Primary (HIGH confidence)
- **Live DB queries** -- Direct sqlite3 queries against `data/library.db` (2026-02-22)
- **Codebase grep** -- Exhaustive search of all `\bstatus\b` references in src/, tests/, scripts/
- **Source file reads** -- Full content of database.py, state.py, recovery.py, fsm.py, models.py, cli.py, orchestrator.py, scanner.py
- **SQLite capability testing** -- In-memory Python tests confirming:
  - DROP COLUMN works after dropping referencing triggers (SQLite 3.51.0)
  - ALTER TABLE ADD CONSTRAINT / ADD CHECK are NOT supported (syntax error)
  - Table rebuild is required for CHECK constraints
  - Existing CHECK constraints survive DROP COLUMN

### Secondary (MEDIUM confidence)
- **SQLite documentation** -- DROP COLUMN supported since 3.35.0 (current version: 3.51.0)
- **V7 migration pattern** -- Proven table rebuild approach already in codebase

## Metadata

**Confidence breakdown:**
- Live DB state: HIGH -- direct queries, confirmed all counts
- Status reference inventory: HIGH -- exhaustive grep + manual verification of every hit
- Migration pattern: HIGH -- V7 pattern proven in codebase, SQLite version and capabilities confirmed by testing
- LOCAL_DELETE/missing resolution: HIGH -- confirmed zero rows with these statuses, replacement mechanisms clear
- Test update scope: HIGH -- all test files with status references identified with line numbers

**Research date:** 2026-02-22
**Valid until:** Indefinite (codebase-specific findings, not library-dependent)
