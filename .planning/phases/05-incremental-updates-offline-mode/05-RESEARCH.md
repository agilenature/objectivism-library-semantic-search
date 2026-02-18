# Phase 5: Incremental Updates & Offline Mode - Research

**Researched:** 2026-02-18
**Domain:** SQLite migration, Gemini File Search store management, incremental sync pipeline, offline CLI guards
**Confidence:** HIGH (codebase-verified) / MEDIUM (Gemini store documents API)

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **Sync Atomicity -- Upload-First Strategy**: Upload NEW file first -> get new_gemini_file_id -> update SQLite -> attempt delete OLD (fire-and-forget). Store old ID in `orphaned_gemini_file_id` column. On crash: old entry still live (acceptable). Add `sync --cleanup-orphans`.

2. **Disk Availability -- Multi-Layer Mount Check**: `check_disk_availability(library_root)` returns `'available'`, `'unavailable'`, or `'degraded'`. Checks `os.path.isdir(mount_point)`, `os.listdir(mount_point)`, `os.path.isdir(library_root)`. Orphan cleanup ONLY runs when disk returns `'available'`. sync/scan/upload fail fast when `'unavailable'`.

3. **Sync Pipeline -- Enriched by Default**: sync reuses `EnrichedUploadOrchestrator` from Phase 6.2. Add `--skip-enrichment` flag for emergency fast sync. If AI metadata extraction fails: fall back to raw upload (log warning, don't skip file).

4. **Orphan Deletion Policy -- Mark-Missing, Never Auto-Delete**: First detection of absent file: set `status='missing'`, record `missing_since=now()`. Gemini deletion NEVER happens automatically. Require explicit `--prune-missing` flag. Add `sync --dry-run` for preview. Default age threshold: 7 days.

5. **Partial Sync Failure -- Per-File SQLite Commits**: Per-file commits after each successful file (existing Phase 2 pattern). Errors: mark `status='error'`, continue batch, report summary at end. Max 3 retries with exponential backoff.

6. **Gemini 48hr TTL -- Store-Level Deletion, 404=Success**: Use store-document deletion API. Wrap in try/except NotFound -- 404 is acceptable. Must test: does raw file TTL expiry auto-remove store entry?

7. **File Identity -- Path-Based, Rename = Delete+Add**: Existing absolute path as primary key. Rename/move -> old record becomes `'missing'`, new record created as `'pending_upload'`.

8. **Hash Strategy -- Source Hash + Upload Hash + Enrichment Version**: `content_hash` = SHA-256 of raw file bytes (existing). `upload_hash` = SHA-256 of enriched bytes actually uploaded (new column). `enrichment_version` = short hash of (prompt template + model name + injection schema version) (new column). Sync re-uploads if `source_hash` OR `enrichment_version` changed.

9. **Offline Metadata -- Verify SQLite metadata_json Sufficiency**: Verify `view` command reads from SQLite for metadata display. If gap found, add migration to backfill.

10. **Offline Scope -- Disk-Offline Only for Phase 5**: "Offline mode" = USB drive not connected, internet/Gemini still available. Network-offline = out of scope for Phase 5 (existing error handling covers it).

11. **mtime Hybrid Optimization -- Implement**: Store mtime in SQLite. If mtime matches: skip hash computation. If mtime differs: compute hash. APFS/HFS+ on macOS: mtime is reliable.

12. **Enrichment Version Tracking -- Implement**: `enrichment_version = sha256(prompt_template + model_name + schema_version)[:8]`

13. **Gemini Store Consistency Guard -- Implement**: New table: `library_config (key TEXT PRIMARY KEY, value TEXT)`. Store `gemini_store_name`. Verify on startup. Fail with error on mismatch.

### Schema V7 Changes Required (from CONTEXT.md)
- Add `mtime` column to files table
- Add `orphaned_gemini_file_id` column to files table
- Add `missing_since` column to files table
- Add `upload_hash` column to files table
- Add `enrichment_version` column to files table
- Add `library_config` table (key/value store)

### Claude's Discretion
No items marked as Claude's discretion in CONTEXT.md.

### Deferred Ideas (OUT OF SCOPE)
- Network-offline mode (existing error handling covers it)
- inode-based file identity tracking

</user_constraints>

## Summary

Phase 5 integrates two capabilities into the existing `objlib` codebase: an incremental sync pipeline that detects new/modified/deleted files and updates only what changed in the Gemini index, and an offline mode where query commands work without the USB drive connected. The codebase already has strong foundations: `FileScanner.detect_changes()` computes changesets via set operations, `EnrichedUploadOrchestrator` handles metadata-enriched uploads with per-file commits, and `GeminiFileSearchClient` wraps the SDK's async APIs.

The critical technical findings are: (1) the Gemini File Search store has a `documents` sub-API (`client.aio.file_search_stores.documents.delete/list`) separate from the raw Files API -- the current codebase only uses `client.aio.files.delete` which deletes the temporary 48hr file, NOT the indexed store entry; (2) raw file TTL expiry does NOT remove store entries -- indexed data persists indefinitely until explicitly deleted via `documents.delete()`; (3) the SQLite `status` column has a CHECK constraint that blocks new values like `'missing'` -- the V7 migration must recreate the table or use SQLite's table-rebuild approach; (4) the `view` command reads Phase 1 metadata from `files.metadata_json` which IS stored in SQLite, confirming offline view works without changes to data access (OFFL-01 verified).

**Primary recommendation:** Build the sync command as a new `src/objlib/sync/` module that composes `FileScanner.detect_changes()` with `EnrichedUploadOrchestrator`, adding a new `SyncOrchestrator` that handles the upload-first replacement strategy, mtime optimization, and missing-file detection. Add disk availability checks as an early guard in the CLI callback.

## Standard Stack

### Core (already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| google-genai | >=1.63.0 | Gemini File Search API (upload, import, store documents) | Only official SDK; aio support for async |
| aiosqlite | >=0.22 | Async SQLite for upload pipeline state management | Already used in Phase 2 upload state manager |
| typer | >=0.12 | CLI framework with rich help, subcommands | Already used; `sync` becomes new command |
| rich | >=13.0 | CLI output formatting, progress tracking | Already used across all commands |
| tenacity | >=9.1 | Retry with exponential backoff | Already used in upload client and search client |

### Supporting (already in project)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| hashlib (stdlib) | N/A | SHA-256 for content_hash, upload_hash, enrichment_version | Change detection, idempotency |
| os (stdlib) | N/A | `os.path.isdir`, `os.listdir`, `os.stat` for disk availability and mtime | Disk check, mtime optimization |

### No New Dependencies Required
All Phase 5 work uses existing libraries. No new packages needed.

## Architecture Patterns

### Recommended Module Structure
```
src/objlib/
  sync/
    __init__.py          # SyncOrchestrator public API
    detector.py          # Change detection (wraps scanner + mtime)
    replacer.py          # Upload-first file replacement logic
    orphan.py            # Missing file detection, orphan cleanup
    disk.py              # Disk availability checking
  cli.py                 # New sync command + offline guards on existing commands
  database.py            # V7 migration, new queries
  models.py              # New FileStatus values, SyncConfig dataclass
```

### Pattern 1: Upload-First Atomic Replacement
**What:** When a file's content changes, upload the new version BEFORE deleting the old store entry. This ensures the file is always searchable.
**When to use:** Every file update during sync.
**How it maps to existing code:**

```python
# Source: Codebase analysis of upload/orchestrator.py + upload/client.py
async def replace_file_in_store(
    client: GeminiFileSearchClient,
    store_name: str,
    file_path: str,
    old_gemini_file_id: str,
    display_name: str,
    custom_metadata: list[dict],
) -> tuple[str, str]:
    """Upload-first replacement: upload new -> delete old -> return new IDs."""
    # Step 1: Upload new file (reuse existing upload_and_import)
    file_obj, operation = await client.upload_and_import(
        file_path, display_name, custom_metadata
    )
    new_gemini_file_id = file_obj.name  # "files/xyz123"

    # Step 2: Poll operation to completion (reuse existing poll)
    await client.poll_operation(operation)

    # Step 3: Delete old STORE DOCUMENT (not raw file!)
    # CRITICAL: Use documents.delete, not files.delete
    try:
        # Need to find document name in store for old file
        await client._client.aio.file_search_stores.documents.delete(
            name=f"{store_name}/documents/{old_gemini_file_id}"
        )
    except Exception:
        # 404 = already gone (TTL or prior cleanup). Store as orphan.
        pass  # Record orphaned_gemini_file_id in SQLite

    return new_gemini_file_id, file_obj.uri
```

### Pattern 2: Disk Availability Guard
**What:** Check disk mount status before any filesystem-dependent operation.
**When to use:** At the start of sync, scan, upload commands. Also as a conditional check in view --full.
**Integration point:** CLI callback or per-command guard.

```python
# Source: CONTEXT.md decision #2
import os
from typing import Literal

def check_disk_availability(library_root: str) -> Literal['available', 'unavailable', 'degraded']:
    mount_point = "/Volumes/U32 Shadow"
    if not os.path.isdir(mount_point):
        return 'unavailable'
    try:
        os.listdir(mount_point)
    except OSError:
        return 'unavailable'
    if not os.path.isdir(library_root):
        return 'degraded'
    return 'available'
```

### Pattern 3: mtime-First Change Detection
**What:** Use file modification time as a fast pre-filter before computing SHA-256 hash.
**When to use:** During sync change detection for every file.
**How it extends existing code:**

```python
# Source: Codebase analysis of scanner.py + CONTEXT.md decision #11
import os
from pathlib import Path

def detect_change_with_mtime(
    file_path: Path,
    stored_mtime: float | None,
    stored_hash: str,
) -> tuple[bool, float, str]:
    """Returns (changed, current_mtime, current_hash)."""
    stat = file_path.stat()
    current_mtime = stat.st_mtime

    if stored_mtime is not None and current_mtime == stored_mtime:
        # mtime unchanged -> assume content unchanged, skip hash
        return False, current_mtime, stored_hash

    # mtime differs -> compute full hash
    current_hash = FileScanner.compute_hash(file_path)
    changed = current_hash != stored_hash
    return changed, current_mtime, current_hash
```

### Pattern 4: Per-File Commit Recovery (Existing Pattern)
**What:** Commit SQLite after each successful file operation.
**Where it exists:** `AsyncUploadStateManager.record_upload_success()` and `record_import_success()` both call `await db.commit()` immediately.
**How sync reuses it:** Same pattern -- after each file is synced, commit the status change. On crash, files in `'uploading'` status are retried on next run.

### Pattern 5: Schema V7 Migration with Table Rebuild
**What:** SQLite cannot alter CHECK constraints. Must rebuild the files table.
**Why it's needed:** Current CHECK constraint: `status IN ('pending', 'uploading', 'uploaded', 'failed', 'skipped', 'LOCAL_DELETE')`. Phase 5 needs `'missing'` and `'error'` statuses.
**How:**

```python
# Source: SQLite documentation on table rebuild
MIGRATION_V7_SQL = """
-- Step 1: Create new table with expanded CHECK and new columns
CREATE TABLE IF NOT EXISTS files_v7 (
    file_path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    metadata_json TEXT,
    metadata_quality TEXT DEFAULT 'unknown'
        CHECK(metadata_quality IN ('complete', 'partial', 'minimal', 'none', 'unknown')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'uploading', 'uploaded', 'failed', 'skipped',
                         'LOCAL_DELETE', 'missing', 'error')),
    error_message TEXT,
    gemini_file_uri TEXT,
    gemini_file_id TEXT,
    upload_timestamp TEXT,
    remote_expiration_ts TEXT,
    embedding_model_version TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    -- V3 columns
    ai_metadata_status TEXT DEFAULT 'pending',
    ai_confidence_score REAL,
    -- V4 columns
    entity_extraction_version TEXT,
    entity_extraction_status TEXT DEFAULT 'pending',
    -- V5 columns
    upload_attempt_count INTEGER DEFAULT 0,
    last_upload_hash TEXT,
    -- V7 new columns
    mtime REAL,
    orphaned_gemini_file_id TEXT,
    missing_since TEXT,
    upload_hash TEXT,
    enrichment_version TEXT
);

-- Step 2: Copy data from old table
INSERT INTO files_v7 SELECT
    file_path, content_hash, filename, file_size,
    metadata_json, metadata_quality, status, error_message,
    gemini_file_uri, gemini_file_id, upload_timestamp,
    remote_expiration_ts, embedding_model_version,
    created_at, updated_at,
    ai_metadata_status, ai_confidence_score,
    entity_extraction_version, entity_extraction_status,
    upload_attempt_count, last_upload_hash,
    NULL, NULL, NULL, NULL, NULL  -- New V7 columns default to NULL
FROM files;

-- Step 3: Drop old table and rename
DROP TABLE files;
ALTER TABLE files_v7 RENAME TO files;

-- Step 4: Recreate indexes
CREATE INDEX IF NOT EXISTS idx_content_hash ON files(content_hash);
CREATE INDEX IF NOT EXISTS idx_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_metadata_quality ON files(metadata_quality);

-- Step 5: Recreate triggers
CREATE TRIGGER IF NOT EXISTS update_files_timestamp
    AFTER UPDATE ON files FOR EACH ROW
    BEGIN
        UPDATE files SET updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')
        WHERE file_path = NEW.file_path;
    END;

CREATE TRIGGER IF NOT EXISTS log_status_change
    AFTER UPDATE OF status ON files FOR EACH ROW
    WHEN OLD.status != NEW.status
    BEGIN
        INSERT INTO _processing_log(file_path, old_status, new_status)
        VALUES (NEW.file_path, OLD.status, NEW.status);
    END;

-- Step 6: Create library_config table
CREATE TABLE IF NOT EXISTS library_config (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""
```

### Anti-Patterns to Avoid
- **Using `client.aio.files.delete()` for index cleanup:** This deletes the raw temporary file (48hr TTL), NOT the indexed store entry. The indexed data persists indefinitely. MUST use `client.aio.file_search_stores.documents.delete()` for actual index cleanup.
- **Deleting from Gemini when disk is unavailable:** A disconnected USB drive makes ALL files appear "deleted." Never trigger orphan cleanup unless `check_disk_availability()` returns `'available'`.
- **Inserting `'missing'` status without V7 migration:** The existing CHECK constraint will reject it with error code 19.
- **Holding SQLite transactions across `await` boundaries:** Already documented in `AsyncUploadStateManager` -- commit immediately after each write operation.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Change detection | Custom diff algorithm | `FileScanner.detect_changes()` (scanner.py) | Already computes new/modified/deleted/unchanged sets via set operations against DB |
| Enriched upload pipeline | New upload logic | `EnrichedUploadOrchestrator.run_enriched()` | Already handles metadata building, content injection, idempotency, retry, per-file commits |
| Content hash computation | Custom hasher | `FileScanner.compute_hash()` | Already handles streaming SHA-256, permission errors, OSError |
| Upload hash computation | Custom hash | `compute_upload_hash()` (metadata_builder.py) | Already computes deterministic hash of phase1+ai+entities+content |
| Rate limiting | Custom rate limiter | `AdaptiveRateLimiter` + `RollingWindowCircuitBreaker` | Already integrated in GeminiFileSearchClient |
| Retry logic | Custom retry loop | `tenacity` with `AsyncRetrying` | Already used throughout upload and search clients |

**Key insight:** Phase 5 is primarily an orchestration task -- composing existing primitives (scanner, upload, state manager) into a new sync workflow. The main new code is: (1) the sync orchestrator that coordinates detection + upload-first replacement + missing detection, (2) disk availability checking, (3) the store-level document deletion method (currently missing from the client), and (4) the V7 migration.

## Common Pitfalls

### Pitfall 1: Wrong Gemini Deletion API
**What goes wrong:** Using `client.aio.files.delete(name="files/xyz")` to remove a file from the search index. This only deletes the temporary raw File object (which expires in 48h anyway). The indexed store entry persists and continues appearing in search results.
**Why it happens:** The existing `GeminiFileSearchClient.delete_file()` method uses `self._client.aio.files.delete` -- this was fine for Phase 6.2 (deleting before re-upload), but for Phase 5 orphan cleanup, the store entry must be explicitly removed.
**How to avoid:** Add a new `delete_store_document()` method that uses `self._client.aio.file_search_stores.documents.delete(name=...)`. The document resource name format is `fileSearchStores/{store-id}/documents/{document-id}`.
**Warning signs:** After `sync --prune-missing`, deleted files still appear in search results.

### Pitfall 2: CHECK Constraint Blocks New Status Values
**What goes wrong:** `sqlite3.IntegrityError: CHECK constraint failed` when setting `status='missing'` or `status='error'`.
**Why it happens:** The original `CREATE TABLE files` includes `CHECK(status IN ('pending', 'uploading', 'uploaded', 'failed', 'skipped', 'LOCAL_DELETE'))`. SQLite does not support `ALTER TABLE ... DROP CONSTRAINT`.
**How to avoid:** V7 migration MUST use the table-rebuild approach: create new table -> copy data -> drop old -> rename new. This is a standard SQLite pattern for schema changes that affect constraints.
**Warning signs:** Any INSERT or UPDATE with a new status value fails with error code 19.

### Pitfall 3: Gemini Store Document ID vs File ID Mapping
**What goes wrong:** Cannot delete a store document because the document ID format (`fileSearchStores/{store}/documents/{doc-id}`) is unknown -- the current database stores `gemini_file_id` as `files/{id}`, not the store document resource name.
**Why it happens:** When `import_file()` is called, it returns an operation -- not a document resource name. The document ID within the store is not the same as the raw file ID.
**How to avoid:** After import completes, use `client.aio.file_search_stores.documents.list(parent=store_name)` to discover the document name for a given file. Alternatively, store the operation result which may contain the document reference. This mapping needs investigation during implementation.
**Warning signs:** Cannot correlate SQLite records with store documents for deletion.

### Pitfall 4: Disk Disconnection During Sync
**What goes wrong:** USB drive is disconnected mid-sync, causing all remaining files to appear "deleted." If orphan detection runs, it marks every file as missing.
**Why it happens:** `os.path.exists()` returns `False` for disconnected volume paths.
**How to avoid:** Check disk availability BEFORE each batch of orphan detection, not just at sync start. If availability transitions from `'available'` to `'unavailable'` mid-sync, abort orphan detection immediately.
**Warning signs:** Large number of files suddenly marked `'missing'` after a sync run.

### Pitfall 5: mtime Comparison Precision
**What goes wrong:** mtime comparison reports false changes due to floating-point precision differences between `os.stat()` and SQLite storage.
**Why it happens:** `st_mtime` is a float with nanosecond-level precision on APFS. SQLite REAL stores as 8-byte IEEE 754 double. Rounding during storage can cause `!=` to trigger false positives.
**How to avoid:** Store mtime as REAL in SQLite (native float storage). Compare with a small epsilon (1e-6 seconds) or truncate to microsecond precision before comparison.
**Warning signs:** Sync always computes hashes despite no file changes.

### Pitfall 6: Enrichment Fallback Creates Two-Tier Index
**What goes wrong:** When AI metadata extraction fails during sync, falling back to raw upload creates files without enriched metadata in the store, degrading search quality for those files.
**Why it happens:** Decision #3 says "fall back to raw upload" on failure. But the raw upload uses `GeminiFileSearchClient.build_custom_metadata()` which only has Phase 1 fields, not the enriched fields (topics, aspects, entities, key_themes).
**How to avoid:** Log a clear warning when fallback occurs. Mark the file with a flag so it can be re-enriched later. Consider a `sync --retry-enrichment` pass.
**Warning signs:** Some files have `source_type=objectivism_library` metadata but no `topics` or `entities` fields.

## Code Examples

### Store-Level Document Deletion (NEW -- not in codebase yet)
```python
# Source: Google AI official docs - File Search store management
# This method MUST be added to GeminiFileSearchClient

async def delete_store_document(self, document_name: str) -> None:
    """Delete an indexed document from the File Search store.

    Unlike delete_file() which deletes the temporary raw File (48hr TTL),
    this removes the indexed content that persists indefinitely.

    Args:
        document_name: Full resource name, e.g.
            'fileSearchStores/abc123/documents/doc456'
    """
    try:
        await self._safe_call(
            self._client.aio.file_search_stores.documents.delete,
            name=document_name,
        )
        logger.info("Deleted store document %s", document_name)
    except Exception as exc:
        # 404 = document already gone (acceptable)
        if "404" in str(exc) or "NOT_FOUND" in str(exc):
            logger.info("Store document already deleted: %s", document_name)
        else:
            raise
```

### Listing Store Documents to Find Document Name
```python
# Source: Google AI official docs
async def find_document_name(
    client: genai.Client, store_name: str, gemini_file_id: str
) -> str | None:
    """Find the store document name for a given file ID.

    Args:
        store_name: e.g. "fileSearchStores/abc123"
        gemini_file_id: e.g. "files/xyz789"

    Returns:
        Full document resource name or None if not found.
    """
    async for doc in client.aio.file_search_stores.documents.list(
        parent=store_name
    ):
        # Check if this document corresponds to our file
        if hasattr(doc, 'file_name') and doc.file_name == gemini_file_id:
            return doc.name
    return None
```

### V7 Migration Integration Point
```python
# Source: Codebase analysis of database.py _setup_schema()
# Add this block after the existing `if version < 6:` block:

if version < 7:
    # V7 requires table rebuild for expanded CHECK constraint
    # Uses BEGIN/COMMIT for atomic migration
    self.conn.executescript(MIGRATION_V7_SQL)

self.conn.execute("PRAGMA user_version = 7")
```

### Sync Command CLI Pattern
```python
# Source: Codebase analysis of cli.py enriched-upload command pattern
@app.command()
def sync(
    library_path: Annotated[Path | None, typer.Option("--library", "-l")] = None,
    store_name: Annotated[str, typer.Option("--store", "-s")] = "objectivism-library-test",
    db_path: Annotated[Path, typer.Option("--db", "-d")] = Path("data/library.db"),
    force: Annotated[bool, typer.Option("--force")] = False,
    skip_enrichment: Annotated[bool, typer.Option("--skip-enrichment")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    prune_missing: Annotated[bool, typer.Option("--prune-missing")] = False,
    cleanup_orphans: Annotated[bool, typer.Option("--cleanup-orphans")] = False,
) -> None:
    """Detect changes and sync with Gemini File Search store."""
    # 1. Check disk availability
    availability = check_disk_availability(library_path or DEFAULT_LIBRARY)
    if availability == 'unavailable':
        console.print("[red]Library disk not available.[/red]")
        raise typer.Exit(code=1)
    # 2. Run change detection (scanner.detect_changes + mtime optimization)
    # 3. Upload new/modified files (EnrichedUploadOrchestrator)
    # 4. Mark missing files (only if disk available)
    # 5. Prune if --prune-missing and missing_since > threshold
    # 6. Cleanup orphaned Gemini entries if --cleanup-orphans
```

### Offline Guard Pattern for Existing Commands
```python
# Source: Codebase analysis of cli.py scan/upload commands
# These commands already check db_path.exists() -- add disk check for scan/upload

# For scan command (line 186):
# BEFORE: if not config.library_path.exists():
# AFTER: add disk availability check first
availability = check_disk_availability(str(config.library_path))
if availability == 'unavailable':
    console.print(
        "[red]Error:[/red] Library disk not connected.\n"
        "[dim]Mount the USB drive and try again.[/dim]"
    )
    raise typer.Exit(code=1)

# For view --full (line 1078):
# ALREADY handles gracefully:
# source_path = Path(file_path)
# if source_path.exists(): ... else: console.print("[yellow]Warning:...")
# This is correct for OFFL-02 -- just needs a clearer message
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `client.aio.files.delete()` for cleanup | `client.aio.file_search_stores.documents.delete()` for store cleanup | Phase 5 (new) | Raw file deletion does NOT remove indexed store content. Must use documents API. |
| Status CHECK constraint with 6 values | Table rebuild with 8 values | Phase 5 V7 migration | Required for `'missing'` and `'error'` statuses |
| Full SHA-256 hash on every scan | mtime-first with hash fallback | Phase 5 (new) | Significant speedup for USB drive with ~1,749 files |
| `content_hash` only for change detection | `content_hash` + `upload_hash` + `enrichment_version` | Phase 5 (new) | Detects both source changes and enrichment config changes |

**Key findings about current state:**
- Current database has 1,902 total files: 1,884 LOCAL_DELETE, 18 pending, 0 uploaded
- 1,748 files have AI metadata in `file_metadata_ai` table
- No files currently have `gemini_file_id` set (all are in pending/LOCAL_DELETE status)
- `files.metadata_json` contains Phase 1 metadata (category, course, year, etc.) -- sufficient for offline `view`
- `file_metadata_ai.metadata_json` contains AI metadata (topics, aspects, semantic_description) -- available for richer offline display if desired

## Open Questions

1. **Store Document ID Discovery**
   - What we know: `import_file()` returns an Operation, not a document resource name. Documents can be listed via `documents.list(parent=store_name)`.
   - What's unclear: What attribute on the listed document object maps back to the original `gemini_file_id` (files/xxx)? Is it `file_name`, `source_file`, or something else?
   - Recommendation: During implementation, call `documents.list()` on the test store and inspect the returned document objects to discover the attribute mapping. Store the document resource name in a new column or derive it from the file ID.

2. **Duplicate display_name During Upload-First Replacement**
   - What we know: Upload-first means briefly TWO files with the same `display_name` exist in the store simultaneously.
   - What's unclear: Does Gemini allow duplicate `display_name` values in a store? If not, the new upload would fail.
   - Recommendation: Test with the actual store. If duplicates are blocked, use a temporary display_name with a suffix (e.g., `filename.txt.REPLACING`) then rename after old deletion. Alternatively, Gemini may use the file resource name as the unique key, not display_name.

3. **EnrichedUploadOrchestrator Single-File Mode**
   - What we know: The existing `run_enriched()` method processes batches of pending files with full pipeline (lock, recovery, batch processing).
   - What's unclear: For sync, we need to upload individual files on-demand (after detecting changes), not batch-process all pending files.
   - Recommendation: Extract the single-file upload logic from `_upload_enriched_file()` into a reusable method that sync can call per-file. Or create a new `SyncUploadOrchestrator` that wraps the client and state manager for individual file operations.

4. **`error` vs `failed` Status Semantics**
   - What we know: Decision #5 says "mark status='error'" for sync failures. But `FileStatus` already has `FAILED = "failed"`.
   - What's unclear: Should sync use the existing `'failed'` status or introduce a new `'error'` status?
   - Recommendation: Reuse existing `'failed'` status for sync upload failures. Reserve the new `'error'` status for sync-specific errors (e.g., disk read failure during hash computation) if a distinction is needed. Or simply reuse `'failed'` throughout and avoid adding `'error'` to the CHECK constraint.

## Sources

### Primary (HIGH confidence)
- **Codebase analysis** -- Direct reading of all source files:
  - `src/objlib/database.py` -- Schema V1-V6, CHECK constraints, UPSERT logic, all queries
  - `src/objlib/scanner.py` -- `FileScanner.detect_changes()`, `compute_hash()`, file discovery
  - `src/objlib/upload/orchestrator.py` -- `UploadOrchestrator`, `EnrichedUploadOrchestrator`, per-file commits
  - `src/objlib/upload/client.py` -- `GeminiFileSearchClient`, two-step upload, `delete_file()` (raw file only)
  - `src/objlib/upload/state.py` -- `AsyncUploadStateManager`, enriched pending queries, lock management
  - `src/objlib/upload/content_preparer.py` -- Tier 4 content injection
  - `src/objlib/upload/metadata_builder.py` -- `build_enriched_metadata()`, `compute_upload_hash()`
  - `src/objlib/cli.py` -- All commands (scan, upload, search, view, browse, filter), AppState callback
  - `src/objlib/models.py` -- `FileStatus`, `FileRecord`, `AppState`, `UploadConfig`
  - `src/objlib/config.py` -- API key management, `ScannerConfig`
  - `src/objlib/search/client.py` -- `GeminiSearchClient`, `resolve_store_name()`
  - `src/objlib/search/formatter.py` -- `display_detailed_view()` reads from metadata dict
- **SQLite database** -- Direct query of data/library.db:
  - Schema version 6, 1902 files, CHECK constraint verified to block 'missing' status
  - 1748 AI metadata entries in file_metadata_ai

### Secondary (MEDIUM confidence)
- **Google AI official docs** (https://ai.google.dev/gemini-api/docs/file-search) -- Confirmed:
  - `client.file_search_stores.documents.delete(name=...)` exists for store-level document deletion
  - `client.file_search_stores.documents.list(parent=...)` exists for listing store documents
  - Raw file 48hr TTL does NOT affect indexed store data (persists indefinitely)
  - Document resource name format: `fileSearchStores/{store-id}/documents/{doc-id}`

### Tertiary (LOW confidence)
- **Store document ID mapping:** The exact attribute on listed documents that maps to the original file ID is not confirmed in docs. Needs runtime verification.
- **Duplicate display_name handling:** Not explicitly documented whether stores enforce unique display_name. Needs testing.
- **Async documents API:** Assumed `client.aio.file_search_stores.documents.delete/list` exists (by analogy with `client.aio.file_search_stores.create/list/import_file`). Needs verification.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already in use, no new dependencies
- Architecture: HIGH -- patterns derived from direct codebase analysis, composing existing primitives
- Schema migration: HIGH -- CHECK constraint enforcement verified by direct SQLite test
- Gemini store documents API: MEDIUM -- confirmed via official docs, but document-to-file ID mapping unverified
- Pitfalls: HIGH -- derived from actual code analysis and verified constraints

**Research date:** 2026-02-18
**Valid until:** 2026-03-18 (stable domain, 30-day validity)
