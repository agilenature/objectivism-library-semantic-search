# Phase 12: 50-File FSM-Managed Upload - Research

**Researched:** 2026-02-20
**Domain:** FSM integration into Gemini File Search upload pipeline (python-statemachine + aiosqlite + google-genai SDK)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Q1 -- FSM Integration Architecture:** Wrapper-based. New `transition_to_*()` methods added to `AsyncUploadStateManager`. FSM `on_enter_*` async callbacks call these. Per-file FSM instances. Legacy methods preserved but not called in FSM path. Dual-write `status` + `gemini_state` for backward compat.
- **Q2 -- _reset_existing_files() fix:** Use `gemini_store_doc_id` from DB directly (not list+map). Fallback to list+map if `gemini_store_doc_id IS NULL`. Write-ahead intent before delete API calls.
- **Q3 -- RecoveryCrawler SC6 fix:** Production `_recover_file()` raises `OCCConflictError` on False return from `finalize_reset()`. Outer `recover_all()` loop catches per-file, continues recovery. SC6 test injects version increment to force OCC conflict.
- **Q4 -- 50-file corpus:** First 50 alphabetically by `file_path` WHERE `gemini_state='untracked'` AND `filename LIKE '%.txt'`.
- **Q5 -- SUMMARY.md content:** Verbatim: check_stability output, DB counts (2 queries), store-sync dry-run output, 5 TUI queries, timestamp.
- **Q6 -- SC2 algorithm:** Step A: documents.get() per file, check for 404. Step B: list_store_documents() count=50, all names in DB. Pass = 0 missing + 0 orphans.
- **Q7 -- Gate policy:** Zero-failure after retry. Retry FAILED files before gate assessment.

### Claude's Discretion
None specified -- all major decisions are locked.

### Deferred Ideas (OUT OF SCOPE)
None specified.
</user_constraints>

## Summary

Phase 12 integrates the FSM machinery proven in Phases 9-11 into the production upload pipeline, then executes a 50-file upload with temporal stability verification across 36 hours. The work divides into two distinct parts: (1) Plan 12-01 wires the FSM into production code, and (2) Plans 12-02 through 12-05 execute the upload and verify stability at T=0, T+4h, T+24h, and T+36h.

The codebase is well-prepared. The Phase 9 spike proved python-statemachine 2.6.0 works with async+aiosqlite, the Phase 10 spike proved write-ahead intent patterns and OCC-guarded transitions, and Phase 11 proved display_name behavior and import lag characteristics. The production DB already has `gemini_state`, `gemini_store_doc_id`, and `gemini_state_updated_at` columns (V9 migration, Phase 8). However, the production DB does NOT have the Phase 10 intent columns (`version`, `intent_type`, `intent_api_calls_completed`, `intent_started_at`) -- these exist only in the spike DB and must be added via a V10 migration.

**Critical finding:** The `ImportFileOperation.response.document_name` field in the google-genai SDK (v1.63.0) provides the store document resource name after import completes. The `operations.get()` method is typed `T -> T`, so polling an `ImportFileOperation` returns an `ImportFileOperation` with the `response` field populated. However, the Phase 11 spike encountered issues with this path and used raw API calls instead. The production implementation should try the typed approach first but include the raw API fallback pattern from the spike.

**Primary recommendation:** Add V10 migration for `version` + intent columns, create `FileLifecycleSM` class in production `src/objlib/upload/`, add `transition_to_*()` methods to `AsyncUploadStateManager`, then build an `FSMUploadOrchestrator` that replaces the legacy `status` write path with FSM-mediated `gemini_state` transitions.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| python-statemachine | 2.6.0 | FSM with async engine, guards, callbacks | Already proven in Phase 9 spike; AsyncEngine handles `async def` callbacks natively |
| aiosqlite | 0.22.1 | Async SQLite access for state persistence | Already in production; WAL mode + BEGIN IMMEDIATE for correctness |
| google-genai | 1.63.0 | Gemini File Search API (upload, import, poll, documents.get/list) | Already in production client wrapper |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tenacity | (bundled) | Exponential backoff polling | Already used in production `GeminiFileSearchClient` for `poll_operation` and `wait_for_active` |
| keyring | (installed) | API key storage | Used by `check_stability.py` and CLI |

### Alternatives Considered
None -- all decisions are locked. The stack is what was proven in Phases 8-11.

**Installation:**
No new packages needed. All dependencies already installed.

## Architecture Patterns

### Production DB Schema Gap (V10 Migration Required)

**Current production DB (V9):** Has `gemini_state`, `gemini_store_doc_id`, `gemini_state_updated_at` but is MISSING:
- `version INTEGER NOT NULL DEFAULT 0` -- OCC guard
- `intent_type TEXT` -- write-ahead intent marker
- `intent_started_at TEXT` -- intent timestamp
- `intent_api_calls_completed INTEGER` -- progress tracker

These columns exist in the spike DBs (`spike/phase9_spike/db.py`, `spike/phase10_spike/db.py`) but have never been migrated to production. The V10 migration is non-destructive (ALTER TABLE ADD COLUMN).

**Verification:** `PRAGMA user_version` = 9; columns verified missing via `PRAGMA table_info(files)`.

### Recommended Project Structure for New Files
```
src/objlib/upload/
    fsm.py              # FileLifecycleSM class + production FSM logic
    exceptions.py       # OCCConflictError + existing error types
    state.py            # AsyncUploadStateManager (existing + new transition_to_* methods)
    orchestrator.py     # EnrichedUploadOrchestrator (existing + FSM-mediated path)
    client.py           # GeminiFileSearchClient (existing, unchanged)

src/objlib/
    database.py         # MIGRATION_V10_SQL + _setup_schema() update

scripts/
    check_stability.py  # Existing, no changes needed
```

### Pattern 1: Per-File Ephemeral FSM Instance
**What:** Each file gets its own `FileLifecycleSM` instance, initialized at the file's current `gemini_state` from DB. Used for one transition, then discarded. DB is the sole source of truth.
**When to use:** Every state transition in the upload pipeline.
**Source:** Phase 9 spike `StateMachineAdapter` pattern.

```python
# Source: spike/phase9_spike/adapters/statemachine_adapter.py (proven pattern)
from statemachine import State, StateMachine

class FileLifecycleSM(StateMachine):
    """Production FSM for file lifecycle."""
    untracked = State("untracked", initial=True, value="untracked")
    uploading = State("uploading", value="uploading")
    processing = State("processing", value="processing")
    indexed = State("indexed", value="indexed")
    failed = State("failed", value="failed")

    # Forward transitions
    start_upload = untracked.to(uploading)
    complete_upload = uploading.to(processing)
    complete_processing = processing.to(indexed)
    fail_upload = uploading.to(failed)
    fail_processing = processing.to(failed)

    # Phase 10 additions (reset, retry)
    reset = indexed.to(untracked)
    retry = failed.to(untracked)
    fail_reset = indexed.to(failed)
```

**CRITICAL:** No `final=True` on any state. Phase 10 proved that `final=True` on `indexed`/`failed` causes `InvalidDefinition` because they have outgoing transitions (`reset`, `retry`, `fail_reset`).

**Initialization:** Use `start_value` parameter:
```python
# Source: Phase 9 spike statemachine_adapter.py line 130
fsm = FileLifecycleSM(start_value=current_gemini_state)
```

### Pattern 2: FSM Wrapper on AsyncUploadStateManager
**What:** New `transition_to_*()` methods on `AsyncUploadStateManager` that write `gemini_state` + `gemini_store_doc_id` + `version` atomically. FSM `on_enter_state` callbacks call these methods. Legacy methods (`record_upload_intent`, `record_import_success`) remain for backward compat but are not called in the FSM path.
**When to use:** All `gemini_state` mutations.

```python
# New methods on AsyncUploadStateManager:
async def transition_to_uploading(self, file_path: str, expected_version: int) -> int:
    """Write gemini_state='uploading', increment version. OCC-guarded.
    Returns new version. Raises OCCConflictError if version mismatch."""
    db = self._ensure_connected()
    now = self._now_iso()
    cursor = await db.execute(
        """UPDATE files
           SET gemini_state = 'uploading',
               gemini_state_updated_at = ?,
               version = version + 1,
               status = 'uploading'  -- dual-write for backward compat
           WHERE file_path = ?
             AND gemini_state = 'untracked'
             AND version = ?""",
        (now, file_path, expected_version),
    )
    await db.commit()
    if cursor.rowcount == 0:
        raise OCCConflictError(f"OCC conflict: {file_path}")
    return expected_version + 1

async def transition_to_processing(self, file_path: str,
                                    expected_version: int,
                                    gemini_file_id: str,
                                    gemini_file_uri: str) -> int:
    """Write gemini_state='processing', store gemini_file_id."""
    # ...similar OCC pattern...

async def transition_to_indexed(self, file_path: str,
                                 expected_version: int,
                                 gemini_store_doc_id: str) -> int:
    """Write gemini_state='indexed', store gemini_store_doc_id."""
    # ...OCC pattern, also writes status='uploaded' for backward compat...

async def transition_to_failed(self, file_path: str,
                                expected_version: int,
                                error_message: str) -> int:
    """Write gemini_state='failed', store error."""
    # ...OCC pattern, also writes status='failed' for backward compat...
```

**Dual-write rationale:** The legacy `status` column is read by `get_pending_files()`, `get_enriched_pending_files()`, and other queries throughout the codebase. Changing all those queries is out of scope for Phase 12. The `transition_to_*()` methods write both `gemini_state` (FSM-tracked) and `status` (legacy) in the same atomic UPDATE.

### Pattern 3: Document Name Extraction from Import Operation
**What:** After `import_file()` returns an `ImportFileOperation` and is polled to `done=True`, extract `document_name` from `completed_operation.response.document_name`. The document_name may be just the doc ID (needs prefixing) or a full resource path.
**When to use:** After polling confirms import complete, before transitioning to INDEXED.

```python
# Source: spike/phase11_spike/spike.py lines 274-286 (proven pattern)
# The SDK returns ImportFileOperation which has .response.document_name
completed_op = await poll_import_operation(operation)
document_name = None
if completed_op.response:
    raw_doc_name = completed_op.response.document_name
    if raw_doc_name:
        if "/" in raw_doc_name:
            document_name = raw_doc_name  # Already full resource path
        else:
            document_name = f"{store_name}/documents/{raw_doc_name}"

# This document_name becomes the gemini_store_doc_id stored in DB
```

**CRITICAL DETAIL:** The Phase 11 spike's raw_results.json shows document names like:
`fileSearchStores/phase11spiketest-etq1w37zrj14/documents/sqowzecl39n8-1emgk2sqooug`

The document name pattern is: `{store_resource_name}/documents/{file_id}-{suffix}`.

### Pattern 4: Import Operation Polling (Typed Return)
**What:** The `client.aio.operations.get()` method is typed `T -> T`. Passing an `ImportFileOperation` returns an `ImportFileOperation` with `response` field populated when `done=True`. However, the Phase 11 spike used raw API calls instead, suggesting the typed approach may not reliably populate `response`.

**Recommended approach:** Try the SDK typed path first. If `completed_op.response` is None despite `done=True`, fall back to the Phase 11 spike's raw API approach.

```python
# Primary: Use SDK's typed operations.get()
operation = await client.aio.file_search_stores.import_file(...)
# Poll via operations.get() which returns ImportFileOperation
while not operation.done:
    await asyncio.sleep(interval)
    operation = await client.aio.operations.get(operation)

# Fallback: Raw API if response is None
if operation.done and (operation.response is None or operation.response.document_name is None):
    # Use raw API approach from Phase 11 spike
    raw_response = await client._client.aio._api_client.async_request(
        "get", operation.name, {}, None
    )
    response_dict = json.loads(raw_response.body) if raw_response.body else {}
    doc_name = response_dict.get("response", {}).get("documentName")
```

### Pattern 5: Display Name Sanitization
**What:** Apply `.strip()` to display_name before upload. Phase 11 proved that leading whitespace causes import hangs.
**When to use:** Before every `upload_file()` call.

```python
# Source: Phase 11 TRIGGER-STRATEGY.md Section 7
display_name = file_info.get("filename", os.path.basename(file_path))[:512].strip()
```

### Pattern 6: Bidirectional Cross-Verification (SC2)
**What:** Two-step verification: (A) For each DB record with `gemini_state='indexed'`, call `documents.get(name=gemini_store_doc_id)` and confirm no 404. (B) Call `list_store_documents()` and verify count matches and all names appear in DB.
**When to use:** T=0 and T+24h checkpoints.

### Anti-Patterns to Avoid
- **Never set `final=True`** on `indexed` or `failed` states in the FSM. Causes `InvalidDefinition` because reset/retry transitions exist.
- **Never mutate `gemini_state` outside FSM transitions.** SC4 requires a grep audit confirming no raw `UPDATE SET gemini_state =` statements outside `transition_to_*()` methods.
- **Never assume `Document.display_name == File.display_name`.** Phase 11 proved Document.display_name = Files API resource ID, not the submitted name. Citation mapping must use `gemini_file_id` -> DB lookup.
- **Never call `delete_file()` without also calling `delete_store_document()`.** This is the root cause of the orphan accumulation problem (MEMORY.md).
- **Never hold transactions across `await` boundaries.** Each write must commit immediately (Pitfall 5: aiosqlite connection sharing). The `transition_to_*()` methods follow this pattern.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| State machine transitions | Custom if/elif chains | python-statemachine 2.6.0 `StateMachine` class | Async engine, guards, on_enter callbacks; proven in Phase 9 |
| OCC conflict detection | Manual version tracking | OCC UPDATE WHERE version=? pattern in `transition_to_*()` methods | Proven in Phase 9/10 spikes; atomic with state change |
| API call retry with backoff | Manual sleep loops | tenacity `AsyncRetrying` | Already used in production client |
| Display name sanitization | Regex/manual parsing | `.strip()` before upload | Phase 11 proved: only leading whitespace causes hangs |
| Document name from import | List-and-match after import | `ImportFileOperation.response.document_name` | O(1) direct field access vs O(N) list scan |

**Key insight:** The entire FSM pattern (states, transitions, guards, OCC, write-ahead intent) has been proven in spike code. Phase 12 moves it to production, not invents it. Copy spike patterns faithfully.

## Common Pitfalls

### Pitfall 1: Production DB Missing V10 Columns
**What goes wrong:** Code references `version`, `intent_type`, `intent_api_calls_completed` columns that don't exist in production DB (only in spike DBs).
**Why it happens:** Phases 9-10 were spikes with their own isolated DBs at `/tmp/`. Production DB is at V9.
**How to avoid:** Add V10 migration as the FIRST task in Plan 12-01. Use the same ALTER TABLE ADD COLUMN pattern as V9.
**Warning signs:** `sqlite3.OperationalError: no such column: version`

### Pitfall 2: operations.get() Response Field Not Populated
**What goes wrong:** After polling an `ImportFileOperation` via `client.aio.operations.get()`, `completed_op.response` is `None` even though `done=True`.
**Why it happens:** The SDK's generic `operations.get()` may not fully deserialize the operation-specific response fields. The Phase 11 spike bypassed this by using the raw API client.
**How to avoid:** Check `completed_op.response` for None and fall back to raw API parsing if needed. The raw API returns JSON with `response.documentName`.
**Warning signs:** `gemini_store_doc_id` is NULL after upload completes successfully.

### Pitfall 3: FSM Activation During Construction
**What goes wrong:** python-statemachine calls `activate_initial_state()` during construction, which fires `on_enter_state` with `source=None`. If the callback tries to write to DB, it fails.
**Why it happens:** The library's normal behavior is to activate the initial state on creation.
**How to avoid:** Guard all `on_enter_state` callbacks: skip DB writes when `source is None or source.value is None`. This is already implemented in both Phase 9 and Phase 10 spike FSM classes.
**Warning signs:** Unexpected DB writes during FSM creation.

### Pitfall 4: Dual-Write Status + gemini_state Inconsistency
**What goes wrong:** Legacy `status` column drifts from `gemini_state` if one is updated without the other.
**Why it happens:** Legacy code writes `status` directly; new FSM code writes `gemini_state`. If both paths are active, they diverge.
**How to avoid:** The `transition_to_*()` methods write BOTH columns atomically in the same UPDATE. SC4 audit must verify no legacy callsites write to `gemini_state` outside these methods.
**Warning signs:** `check_stability.py` passes but `status` column counts don't match `gemini_state` counts.

### Pitfall 5: RecoveryCrawler finalize_reset() Silent Ignore
**What goes wrong:** `_recover_file()` calls `finalize_reset()` without checking the return value. If `finalize_reset()` returns `False` (OCC conflict), recovery silently succeeds when it should raise.
**Why it happens:** Original spike code at `spike/phase10_spike/recovery_crawler.py:65` does `await finalize_reset(...)` without checking the bool return.
**How to avoid:** Production RecoveryCrawler must: `if not result: raise OCCConflictError(...)`. Outer loop catches per-file.
**Warning signs:** SC6 test fails -- injected OCC conflict does not raise.

### Pitfall 6: _reset_existing_files() Store Document Deletion Order
**What goes wrong:** If store document is deleted AFTER raw file, the store document becomes "orphaned" in an inconsistent state.
**Why it happens:** The current `_reset_existing_files()` deletes raw file first, store document second. SC3 requires delete store document FIRST.
**How to avoid:** Reverse the order: `delete_store_document(gemini_store_doc_id)` BEFORE `delete_file(gemini_file_id)`. Write-ahead intent before both.
**Warning signs:** SC3 verification fails; store document count doesn't decrease after reset.

### Pitfall 7: 50-File Selection Contamination
**What goes wrong:** Some of the 50 selected files already have store documents (from prior test runs), causing SC2 bidirectional check to find unexpected documents.
**Why it happens:** Prior test or spike runs may have uploaded some files without cleaning up.
**How to avoid:** Before the 50-file upload, verify that none of the 50 selected file_paths have any existing `gemini_store_doc_id` or `gemini_file_id` values. Also verify `list_store_documents()` returns 0 documents (or a known baseline).
**Warning signs:** SC2 bidirectional check finds more store documents than expected.

### Pitfall 8: check_stability.py --store Flag
**What goes wrong:** Using `--store objectivism-library-test` (the old store name) instead of `--store objectivism-library` (the Phase 8 migrated store).
**Why it happens:** MEMORY.md and old scripts reference `objectivism-library-test`. Phase 8 migrated to `objectivism-library`.
**How to avoid:** Always use `--store objectivism-library`. The old store was deleted in Phase 8.
**Warning signs:** Exit code 2 from check_stability.py with "Store not found".

## Code Examples

### V10 Migration SQL (Required Before Any FSM Code)
```python
# Source: spike/phase10_spike/db.py schema (adapted for production)
MIGRATION_V10_SQL = """-- V10: Phase 10 OCC + write-ahead intent columns
ALTER TABLE files ADD COLUMN version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE files ADD COLUMN intent_type TEXT;
ALTER TABLE files ADD COLUMN intent_started_at TEXT;
ALTER TABLE files ADD COLUMN intent_api_calls_completed INTEGER;
"""
# Apply in _setup_schema():
if version < 10:
    for alter_sql in [
        "ALTER TABLE files ADD COLUMN version INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE files ADD COLUMN intent_type TEXT",
        "ALTER TABLE files ADD COLUMN intent_started_at TEXT",
        "ALTER TABLE files ADD COLUMN intent_api_calls_completed INTEGER",
    ]:
        try:
            self.conn.execute(alter_sql)
        except sqlite3.OperationalError:
            pass  # Column already exists
    # Also create index for intent recovery queries
    self.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_intent_type ON files(intent_type)"
    )
    self.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_gemini_state ON files(gemini_state)"
    )

self.conn.execute("PRAGMA user_version = 10")
```

### 50-File Selection Query
```sql
-- Source: CONTEXT.md Q4 (locked decision)
SELECT file_path FROM files
WHERE gemini_state = 'untracked'
  AND filename LIKE '%.txt'
ORDER BY file_path
LIMIT 50
```
Current result (first 5):
1. `/Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Ben Bayer - Ayn Rand's Distinctive Case for Individualism.txt`
2. `/Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Ben Bayer, Michael Mazza, Gregory Salmieri - Q and A About Objectivism.txt`
3. `/Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Ben Bayer, Michael Mazza, Gregory Salmieri - Reading Discussion...txt`
4. `/Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Gregory Salmieri - The Scope of Rationality.txt`
5. `/Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Michael Mazza - Ayn Rand's Radical New Approach to Ethics.txt`

**Total available:** 1,748 untracked .txt files (1,884 total files, all untracked, 136 non-.txt).

### OCCConflictError Exception
```python
# Source: spike/phase9_spike/exceptions.py (bring to production)
class OCCConflictError(Exception):
    """OCC version conflict -- another coroutine modified the file concurrently."""
    pass
```

### Post-Import Visibility Check with Fallback Polling
```python
# Source: spike/phase11_spike/TRIGGER-STRATEGY.md Section 3
# Primary path (expected 100% of the time):
doc = await client.aio.file_search_stores.documents.get(name=document_name)
# If document_name resolves -> transition to INDEXED

# Fallback path (defensive):
# If documents.get() returns 404:
interval = 0.5
max_interval = 10.0
timeout = 300.0
start = time.monotonic()
while time.monotonic() - start < timeout:
    await asyncio.sleep(interval)
    try:
        doc = await client.aio.file_search_stores.documents.get(name=document_name)
        break  # visible
    except Exception as e:
        if "404" in str(e) or "NOT_FOUND" in str(e):
            interval = min(interval * 1.5, max_interval)
            continue
        raise  # non-404 error -> FAILED
else:
    # timeout exceeded -> FAILED
```

### SC2 Bidirectional Cross-Verification Script
```python
# Source: CONTEXT.md Q6 (locked decision)
# Step A: DB -> Store (all 50 indexed files exist in store)
for row in indexed_files:
    try:
        doc = await client.aio.file_search_stores.documents.get(
            name=row["gemini_store_doc_id"]
        )
    except Exception as e:
        if "404" in str(e):
            missing.append(row["file_path"])
        else:
            raise

# Step B: Store -> DB (all store documents have matching DB records)
store_docs = await client.list_store_documents()
db_doc_ids = {row["gemini_store_doc_id"] for row in indexed_files}
for doc in store_docs:
    if doc.name not in db_doc_ids:
        orphans.append(doc.name)

# Pass condition: len(missing) == 0 AND len(orphans) == 0 AND len(store_docs) == 50
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Legacy `status` column for upload state | Dual-write `gemini_state` + `status` | Phase 8 (V9 migration) | FSM tracks `gemini_state`; `status` kept for backward compat |
| `objectivism-library-test` store | `objectivism-library` store | Phase 8 (store migration) | Old store deleted; resource name in `library_config` |
| `Document.display_name` for citation mapping | `gemini_file_id` -> DB lookup | Phase 11 (display_name finding) | `Document.display_name` = file resource ID, NOT submitted name |
| `list_store_documents()` for doc name lookup | Direct `gemini_store_doc_id` from DB | Phase 12 (Q2 decision) | O(1) lookup vs O(N) scan |
| `delete_file()` only during reset | `delete_store_document()` + `delete_file()` | Phase 12 (Q2/SC3) | Prevents orphan accumulation |
| Silent `finalize_reset()` ignore | Raise `OCCConflictError` on False | Phase 12 (Q3/SC6) | Makes OCC conflicts visible |

**Deprecated/outdated:**
- `objectivism-library-test` store: DELETED in Phase 8. Use `objectivism-library`.
- `spike/phase9_spike/adapters/statemachine_adapter.py` `final=True` on indexed/failed states: Causes `InvalidDefinition` with Phase 10 transitions. Phase 10 spike's `states.py` removes `final=True`.

## Open Questions

1. **operations.get() Response Deserialization Reliability**
   - What we know: The SDK's `operations.get()` is typed `T -> T` and should return `ImportFileOperation` with populated `response.document_name` when `done=True`. The `from_api_response()` method exists on `ImportFileOperation`.
   - What's unclear: The Phase 11 spike bypassed the SDK and used raw API calls (lines 141-166 of `spike.py`). Was this because `operations.get()` didn't populate `response`, or because the spike was written before discovering the typed path?
   - Recommendation: Try the SDK typed path in production. Add a fallback that uses raw API parsing if `response` is None. This is a medium-risk item that should be tested early in Plan 12-01 implementation.
   - Confidence: MEDIUM

2. **Version Column DEFAULT 0 on Existing Rows**
   - What we know: `ALTER TABLE ADD COLUMN version INTEGER NOT NULL DEFAULT 0` will set version=0 on all 1,884 existing rows. This is correct -- all files are in `untracked` state with no prior FSM transitions.
   - What's unclear: SQLite's `NOT NULL DEFAULT 0` on ALTER TABLE may be handled differently than in CREATE TABLE for existing rows.
   - Recommendation: Verify after migration that all rows have `version=0`.
   - Confidence: HIGH (SQLite documentation confirms DEFAULT works with ALTER TABLE ADD COLUMN for existing rows)

3. **Concurrent Access During 50-File Upload**
   - What we know: The upload pipeline uses `asyncio.Semaphore` for concurrency limiting. Each file gets its own FSM instance with OCC-guarded DB writes.
   - What's unclear: The production `AsyncUploadStateManager` shares a single `aiosqlite.Connection`. The Phase 9 spike used per-transition connection factories (fresh connection per write).
   - Recommendation: The `transition_to_*()` methods use the shared connection with immediate commits (same pattern as existing `record_upload_intent()`). WAL mode enables concurrent reads. Single-writer lock prevents multiple pipeline instances. This should be safe for the 50-file batch.
   - Confidence: HIGH

## Sources

### Primary (HIGH confidence)
- Production source: `src/objlib/upload/state.py` -- current AsyncUploadStateManager
- Production source: `src/objlib/upload/orchestrator.py` -- current EnrichedUploadOrchestrator
- Production source: `src/objlib/upload/client.py` -- GeminiFileSearchClient with documented API methods
- Production source: `src/objlib/database.py` -- SCHEMA_SQL through MIGRATION_V9_SQL, V9 migration applied
- Production source: `scripts/check_stability.py` -- v2 stability instrument (557 lines, 6 assertions)
- Spike source: `spike/phase9_spike/adapters/statemachine_adapter.py` -- proven FSM adapter pattern
- Spike source: `spike/phase10_spike/states.py` -- extended FSM with reset/retry transitions
- Spike source: `spike/phase10_spike/recovery_crawler.py` -- RecoveryCrawler with silent-ignore defect (SC6)
- Spike source: `spike/phase10_spike/db.py` -- write-ahead intent pattern (write_intent, finalize_reset)
- Spike source: `spike/phase10_spike/transition_reset.py` -- ResetTransitionManager pattern
- Spike source: `spike/phase10_spike/safe_delete.py` -- idempotent delete wrappers (404=success)
- Spike source: `spike/phase11_spike/spike.py` -- document_name extraction from ImportFileOperation.response
- Spike source: `spike/phase11_spike/raw_results.json` -- empirical data: 13/13 display_name round-trips, lag P50=0.243s
- Spike source: `spike/phase11_spike/TRIGGER-STRATEGY.md` -- committed polling strategy
- SDK source: `google/genai/types.py` -- `ImportFileOperation.response: Optional[ImportFileResponse]`, `ImportFileResponse.document_name: Optional[str]`
- SDK source: `google/genai/operations.py:484` -- `async def get(self, operation: T) -> T` preserves type
- Phase 8 VERIFICATION.md: confirmed V9 migration, store migration, all 1884 files untracked
- Phase 11 VERIFICATION.md: confirmed SC1/SC2/SC3 all passed, display_name + lag + trigger strategy

### Secondary (MEDIUM confidence)
- `CONTEXT.md` for Phase 12 -- multi-provider AI synthesis of 7 gray areas with locked decisions

### Tertiary (LOW confidence)
- None. All findings verified against source code and SDK inspection.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already installed and proven in prior phases
- Architecture (FSM integration): HIGH -- patterns directly from proven spike code
- Architecture (document_name extraction): MEDIUM -- Phase 11 spike used raw API fallback; typed SDK path unverified in production
- DB Migration: HIGH -- standard ALTER TABLE pattern, same as V9
- Pitfalls: HIGH -- all identified from actual codebase analysis and prior phase findings
- SC verification procedures: HIGH -- locked decisions with concrete algorithms

**Research date:** 2026-02-20
**Valid until:** 2026-03-20 (30 days -- stable domain, no external dependency changes expected)
