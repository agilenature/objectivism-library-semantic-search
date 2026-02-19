# Phase 8: Store Migration Precondition - Research

**Researched:** 2026-02-19
**Domain:** SQLite schema migration, Google Gemini File Search store lifecycle, Python stability instrumentation
**Confidence:** HIGH

## Summary

Phase 8 is a precondition phase that touches three system boundaries: the local SQLite database (schema migration + state reset), the Gemini File Search API (old store deletion + new store creation), and a standalone Python stability instrument (`check_stability.py`). All decisions have been locked in CONTEXT.md, so this research focuses on verifying the technical feasibility and documenting precise API signatures, codebase patterns, and implementation details the planner needs.

The existing codebase already has an `scripts/check_stability.py` implementation (v1 from the v1.0 era) that must be evolved to use `gemini_state='indexed'` instead of `status='uploaded'`. The `GeminiFileSearchClient` in `src/objlib/upload/client.py` has `create_store()` and `list_store_documents()` but does NOT have `delete_store()` or `get_store()` methods -- these must be added or called via the raw SDK. The database module (`src/objlib/database.py`) already has 8 migration versions (V1-V8) with an established pattern; Phase 8's schema changes will be V9.

**Primary recommendation:** Use the established migration pattern (ALTER TABLE ADD COLUMN with try/except for idempotency, bump user_version to 9). For store operations, call the `google-genai` SDK directly via `client.aio.file_search_stores.get()`, `.create()`, and `.delete()` since the existing `GeminiFileSearchClient` wrapper lacks these methods.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **Assertion 5/6 on empty store:** Vacuously PASS when store is empty. Count invariant drives whether assertions 5 and 6 are evaluated.
2. **Migration order:** Create `objectivism-library` FIRST, verify `name` field non-empty, THEN delete `objectivism-library-test`. Recovery logic: Old present + New absent = retry Step 1; Old absent + New present = done, skip; Old absent + New absent = print "migration partially failed", exit 2; Old present + New present = skip Step 1, run Step 2.
3. **Schema migration:** Raw SQL `ALTER TABLE files ADD COLUMN` (3 statements in one transaction). Backup `data/library.db` -> `data/library.db.bak-phase8`. `PRAGMA integrity_check` before. `PRAGMA table_info(files)` verify after.
4. **MIGR-04 reset scope:** Also null `gemini_file_id`: `UPDATE files SET gemini_state='untracked', gemini_store_doc_id=NULL, gemini_file_id=NULL, gemini_state_updated_at=:migration_ts WHERE status='uploaded'`
5. **gemini_state_updated_at:** Set to migration start timestamp (ISO 8601 UTC, captured once before batch UPDATE).
6. **Exit codes:** EXIT 2 = store not found, missing API key, DB file not found, schema missing columns, unhandled exception; EXIT 1 = prerequisites pass but at least one assertion fails; EXIT 0 = all prerequisites pass AND all applicable assertions pass.
7. **check_stability.py architecture:** Standalone script at `scripts/check_stability.py`. Args: `--store <name>` (required), `--db <path>` (default: `data/library.db`), `--verbose`. Pattern: `if __name__ == '__main__': sys.exit(main())`. Uses existing internal modules for DB access and Gemini client.
8. **Pre-flight count:** Check store metadata first (`get_store()` response fields), fall back to paginated `list_store_documents()` with Rich spinner. Also query `SELECT COUNT(*) FROM files WHERE status='uploaded'`.
9. **Raw file cleanup:** No deletion -- just warn if any raw files found via `list_files()`.
10. **Store creation:** `display_name` only for `create_store()`.

### Claude's Discretion

None specified -- all decisions are locked.

### Deferred Ideas (OUT OF SCOPE)

None specified.
</user_constraints>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| google-genai | 1.63.0 | Gemini File Search store CRUD | Already installed; project's sole Gemini SDK |
| sqlite3 (stdlib) | 3.12+ | Schema migration, state reset | Project uses raw sqlite3 everywhere, no ORM |
| keyring | 25.0+ | API key retrieval | Project pattern for all API keys |
| rich | 13.0+ | Console output, spinners, tables | Project's standard output library |
| argparse (stdlib) | 3.12+ | CLI args for `check_stability.py` | Standalone script; existing v1 uses argparse, not typer |
| shutil (stdlib) | 3.12+ | DB file backup before migration | Standard file copy |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncio (stdlib) | 3.12+ | Async Gemini API calls | Store listing, deletion, creation |
| pathlib (stdlib) | 3.12+ | Path manipulation | File existence checks, backup paths |
| datetime (stdlib) | 3.12+ | ISO 8601 timestamps | `gemini_state_updated_at` migration timestamp |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw sqlite3 ALTER TABLE | Alembic/sqlalchemy-migrate | Overkill for 3 column additions; project has never used an ORM |
| argparse | typer | Decision locked: standalone script, not CLI subcommand |

**Installation:**
No new dependencies needed. Everything is already in the project.

## Architecture Patterns

### Recommended Project Structure
```
scripts/
    check_stability.py      # Evolved v2 stability instrument (standalone)
src/objlib/
    database.py             # Add MIGRATION_V9_SQL + bump user_version to 9
    upload/
        client.py           # (Optional) Add get_store() and delete_store() wrappers
```

### Pattern 1: Migration Script as Standalone Python
**What:** The migration itself (08-01 and 08-02) should be a standalone script in `scripts/` (e.g., `scripts/migrate_phase8.py`) OR a dedicated function in the codebase called from a script. It is NOT an automatic migration in `Database._setup_schema()` because it requires user confirmation and is destructive.
**When to use:** One-time irreversible operations that need explicit user consent.
**Rationale:** The existing `_setup_schema()` auto-applies migrations silently on every DB open. Phase 8's migration deletes a store, resets 873 file states, and creates a new store. This MUST NOT happen silently. Separate it from the auto-migration path.

**CRITICAL INSIGHT:** The 3 new columns (MIGR-03) CAN go into `_setup_schema()` as V9 because they are non-destructive additions. But MIGR-04 (state reset) and MIGR-02 (store deletion/creation) MUST be in a separate script requiring explicit confirmation.

### Pattern 2: Existing Database Migration Convention
**What:** The project uses `PRAGMA user_version` for schema versioning with sequential migration blocks in `_setup_schema()`.
**When to use:** Non-destructive schema additions.
**Example:**
```python
# Source: src/objlib/database.py, verified in codebase
# Current: user_version = 8
# After Phase 8: user_version = 9

MIGRATION_V9_SQL = """
-- Phase 8: Gemini FSM state columns
-- These columns support the new FSM-based upload lifecycle.
-- gemini_state tracks the file's Gemini lifecycle state.
-- gemini_store_doc_id tracks the store document resource name.
-- gemini_state_updated_at tracks when the state last changed.
"""

# In _setup_schema():
if version < 9:
    for alter_sql in [
        "ALTER TABLE files ADD COLUMN gemini_store_doc_id TEXT",
        "ALTER TABLE files ADD COLUMN gemini_state TEXT DEFAULT 'untracked'",
        "ALTER TABLE files ADD COLUMN gemini_state_updated_at TEXT",
    ]:
        try:
            conn.execute(alter_sql)
        except sqlite3.OperationalError:
            pass  # Column already exists
    # DO NOT do MIGR-04 state reset here -- that's in the migration script

self.conn.execute("PRAGMA user_version = 9")
```

### Pattern 3: Gemini SDK Direct Calls (Not Through GeminiFileSearchClient)
**What:** The existing `GeminiFileSearchClient` wraps async calls with circuit breaker and rate limiter. For migration one-off operations (get store, delete store), call the SDK directly.
**When to use:** One-time administrative operations where circuit breaker/rate limiter add complexity without benefit.
**Example:**
```python
# Source: google-genai SDK 1.63.0, verified via introspection
from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)

# Get store metadata (includes document counts)
store = client.file_search_stores.get(name=store_resource_name)
print(f"Active docs: {store.active_documents_count}")
print(f"Pending docs: {store.pending_documents_count}")

# Create a new store
new_store = client.file_search_stores.create(
    config={"display_name": "objectivism-library"}
)
assert new_store.name  # Verify non-empty resource name

# Delete a store with all its documents
client.file_search_stores.delete(
    name=store_resource_name,
    config=types.DeleteFileSearchStoreConfig(force=True),
)
```

### Pattern 4: Store Resolution by Display Name
**What:** The project resolves store display names to resource names by listing all stores and matching.
**When to use:** Any operation that needs the store resource name.
**Example:**
```python
# Source: scripts/check_stability.py line 131, verified in codebase
# Also: src/objlib/search/client.py line 131
for store in client.file_search_stores.list():
    if getattr(store, "display_name", None) == display_name:
        resource_name = store.name
        break
```

### Anti-Patterns to Avoid
- **Auto-applying destructive migrations in _setup_schema():** Never put store deletion, state resets, or operations requiring confirmation in the auto-migration path. A developer opening the DB for a quick query should not trigger a store deletion.
- **Mixing sync and async Gemini calls in the same function:** The existing `check_stability.py` uses `client.file_search_stores.list()` (sync) for store resolution but `client.aio.file_search_stores.documents.list()` (async) for document listing. This works but is confusing. For new code, pick one and stick with it.
- **Relying on display_name uniqueness for store identification:** Display names are not unique. After migration, check that ONLY ONE store named `objectivism-library` exists. If both old and new coexist (normal during migration), the code must distinguish them by resource name.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Schema migration framework | Custom migration tracker | `PRAGMA user_version` + sequential blocks | Project already uses this; 8 versions proven |
| DB backup | Custom WAL-aware backup | `shutil.copy2()` on the DB file | SQLite WAL is replayed on next open; simple copy works for cold backup |
| Store document counting | Paginated list + manual count | `store.active_documents_count` from `get()` | API provides this field directly; saves ~2k API calls |
| ANSI terminal colors | Manual escape codes | Keep existing pattern in `check_stability.py` | The v1 script already has GREEN/RED/YELLOW constants; extend them |
| Confirmation prompt | Raw input() | `typer.confirm()` for CLI scripts or `rich.prompt.Confirm` | Consistent with project UX patterns |

**Key insight:** The GenAI SDK's `FileSearchStore.active_documents_count` field (discovered via introspection) means the pre-flight check does NOT need to paginate through all ~2,038 store documents just to get a count. Use `client.file_search_stores.get(name=...)` instead.

## Common Pitfalls

### Pitfall 1: Store Deletion Without `force=True`
**What goes wrong:** `client.file_search_stores.delete(name=...)` raises `FAILED_PRECONDITION` if the store contains any documents and `force` is not set to `True`.
**Why it happens:** The SDK's `DeleteFileSearchStoreConfig` defaults `force` to `None` (treated as False).
**How to avoid:** Always pass `config=types.DeleteFileSearchStoreConfig(force=True)` when deleting a non-empty store.
**Warning signs:** `FAILED_PRECONDITION` error from the delete call.

### Pitfall 2: ALTER TABLE ADD COLUMN with CHECK Constraint
**What goes wrong:** SQLite's `ALTER TABLE ADD COLUMN` does NOT support `CHECK` constraints on the new column in older SQLite versions.
**Why it happens:** SQLite before 3.31.0 restricts what ALTER TABLE ADD COLUMN can do. Python 3.12+ ships with SQLite 3.41+, so this is safe for this project, but do NOT add a CHECK constraint inline with ALTER TABLE.
**How to avoid:** Add the column without CHECK, then enforce the valid values in application code. The `gemini_state` column uses `DEFAULT 'untracked'` but does NOT need a CHECK constraint -- the FSM in Phase 9+ will enforce valid transitions.
**Warning signs:** `sqlite3.OperationalError` on the ALTER TABLE statement.

### Pitfall 3: Database Backup in WAL Mode
**What goes wrong:** A naive `shutil.copy()` copies the main DB file but not the `-wal` and `-shm` files. If there are uncommitted WAL entries, the backup may be incomplete.
**Why it happens:** WAL mode writes to a separate file until checkpoint.
**How to avoid:** Before copying, either (a) run `PRAGMA wal_checkpoint(TRUNCATE)` to flush WAL to the main file, or (b) copy all three files (`.db`, `.db-wal`, `.db-shm`). For this project, option (a) is simpler since we control the connection.
**Warning signs:** Backup file opens but shows stale data or missing recent changes.

### Pitfall 4: Race Between Schema Addition and State Reset
**What goes wrong:** If the migration script adds columns (V9) and then resets state, but the `_setup_schema()` auto-migration also fires on the next DB open, it might try to re-add columns. This is safe because the try/except handles duplicates, but the user_version must be set to 9 in BOTH places (auto-migration and manual script).
**Why it happens:** The manual migration script and auto-migration are separate code paths.
**How to avoid:** The manual migration script should check `PRAGMA user_version` first. If already >= 9, skip the ALTER TABLE steps.

### Pitfall 5: Existing check_stability.py Uses Different Column Names
**What goes wrong:** The existing v1 `check_stability.py` checks `status='uploaded'` and `gemini_file_id`, but STAB-01 requires checking `gemini_state='indexed'`. After Phase 8 migration, status remains 'uploaded' but gemini_state is set to 'untracked'.
**Why it happens:** v1 was built for the pre-FSM world where `status` tracked both file processing state and Gemini upload state.
**How to avoid:** The v2 `check_stability.py` must query `gemini_state='indexed'` for assertions 1-3, NOT `status='uploaded'`. Since Phase 8 resets all files to `gemini_state='untracked'`, immediately post-migration the indexed count is 0, the store is empty, and all 6 assertions should vacuously pass.

### Pitfall 6: Pre-flight `active_documents_count` May Be Stale
**What goes wrong:** The `active_documents_count` from `get_store()` may not be perfectly up-to-date if documents are being processed.
**Why it happens:** This is a cached/computed field, not a live count.
**How to avoid:** Use it as a fast estimate in the pre-flight display. If exact count is needed (e.g., for assertion verification), fall back to `list_store_documents()` and count manually.

## Code Examples

Verified patterns from codebase and SDK introspection:

### Get Store Metadata (Pre-flight Count)
```python
# Source: google-genai SDK 1.63.0, verified via Python introspection
from google import genai

client = genai.Client(api_key=api_key)

# Resolve display_name to resource_name
resource_name = None
for store in client.file_search_stores.list():
    if getattr(store, "display_name", None) == "objectivism-library-test":
        resource_name = store.name
        break

if resource_name:
    store_info = client.file_search_stores.get(name=resource_name)
    # FileSearchStore fields (all Optional[int]):
    #   active_documents_count, pending_documents_count,
    #   failed_documents_count, size_bytes
    print(f"Active: {store_info.active_documents_count}")
    print(f"Pending: {store_info.pending_documents_count}")
    print(f"Failed: {store_info.failed_documents_count}")
    print(f"Size: {store_info.size_bytes} bytes")
```

### Create Store
```python
# Source: src/objlib/upload/client.py line 119, verified in codebase
# The existing create_store() does exactly this:
store = await client.aio.file_search_stores.create(
    config={"display_name": "objectivism-library"},
)
assert store.name, "Store creation failed: empty resource name"
# store.name will be like "fileSearchStores/abc123"
```

### Delete Store (with force)
```python
# Source: google-genai SDK 1.63.0, verified via Python introspection
from google.genai import types

# CRITICAL: force=True required when store has documents
await client.aio.file_search_stores.delete(
    name=old_store_resource_name,
    config=types.DeleteFileSearchStoreConfig(force=True),
)
```

### DB Schema Migration (V9)
```python
# Source: src/objlib/database.py migration pattern, verified in codebase
# In _setup_schema(), after existing version < 8 block:

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

self.conn.execute("PRAGMA user_version = 9")
```

### State Reset (MIGR-04)
```python
# Source: CONTEXT.md locked decision Q4
from datetime import datetime, timezone

migration_ts = datetime.now(timezone.utc).isoformat()

with conn:
    cursor = conn.execute(
        """UPDATE files
           SET gemini_state = 'untracked',
               gemini_store_doc_id = NULL,
               gemini_file_id = NULL,
               gemini_state_updated_at = ?
           WHERE status = 'uploaded'""",
        (migration_ts,),
    )
    print(f"Reset {cursor.rowcount} files to 'untracked'")
```

### DB Backup with WAL Checkpoint
```python
# Source: SQLite documentation + project convention
import shutil
from pathlib import Path

db_path = Path("data/library.db")
backup_path = Path("data/library.db.bak-phase8")

# Flush WAL to main file before backup
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

shutil.copy2(str(db_path), str(backup_path))
print(f"Backup created: {backup_path}")
```

### List Raw Files (Warning Check)
```python
# Source: google-genai SDK 1.63.0, verified via Python introspection
# client.files.list() returns all files in the account (not store-specific)
raw_files = list(client.files.list())
if raw_files:
    print(f"WARNING: {len(raw_files)} raw File API resources still exist")
    print("These will auto-expire after 48h. No action needed.")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `status='uploaded'` tracks Gemini state | `gemini_state` column (FSM) | Phase 8 (v2.0) | Decouples file processing status from Gemini lifecycle |
| `gemini_file_id` is sole Gemini reference | `gemini_store_doc_id` added | Phase 8 (v2.0) | Enables direct store document management without list+scan |
| `check_stability.py` checks `status='uploaded'` | Checks `gemini_state='indexed'` | Phase 8 (v2.0) | Aligns stability instrument with FSM states |
| `objectivism-library-test` (test store) | `objectivism-library` (permanent store) | Phase 8 (v2.0) | Clean baseline for v2.0 upload pipeline |

**Deprecated/outdated:**
- `objectivism-library-test` store: will be deleted during migration
- `objectivism-library-v1` default in app callback (line 61 of cli.py): will need updating in a later phase
- v1 `check_stability.py`: will be replaced by v2 that uses `gemini_state`

## API Reference: FileSearchStore

**Verified via Python introspection of google-genai 1.63.0** (HIGH confidence)

### FileSearchStore Model Fields
| Field | Type | Description |
|-------|------|-------------|
| `name` | `Optional[str]` | Resource name, e.g., `fileSearchStores/abc123` |
| `display_name` | `Optional[str]` | Human-readable name |
| `create_time` | `Optional[datetime]` | Creation timestamp |
| `update_time` | `Optional[datetime]` | Last update timestamp |
| `active_documents_count` | `Optional[int]` | Documents ready for retrieval |
| `pending_documents_count` | `Optional[int]` | Documents being processed |
| `failed_documents_count` | `Optional[int]` | Documents that failed processing |
| `size_bytes` | `Optional[int]` | Total size of ingested raw bytes |

### API Methods (sync and async variants)
| Method | Signature | Returns |
|--------|-----------|---------|
| `create` | `config={"display_name": str}` | `FileSearchStore` |
| `get` | `name=str` | `FileSearchStore` |
| `delete` | `name=str, config=DeleteFileSearchStoreConfig(force=bool)` | `None` |
| `list` | (no required args) | `Pager[FileSearchStore]` |

### DeleteFileSearchStoreConfig
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `force` | `Optional[bool]` | `None` | If True, delete store AND all its documents. If False/None, fails if store has documents. |

## Existing Codebase Inventory

### Files That Will Be Modified
| File | Change | Reason |
|------|--------|--------|
| `src/objlib/database.py` | Add `MIGRATION_V9_SQL`, update `_setup_schema()` to version 9 | MIGR-03: 3 new columns |
| `scripts/check_stability.py` | Rewrite to v2 (gemini_state, vacuous pass, exit codes) | STAB-01 through STAB-04 |

### Files That Will Be Created
| File | Purpose |
|------|---------|
| `scripts/migrate_phase8.py` | One-time migration script: pre-flight, store migration, state reset |

### Current Database State (Verified)
| Metric | Value |
|--------|-------|
| `PRAGMA user_version` | 8 |
| Files with `status='uploaded'` | 873 |
| Files with `gemini_file_id IS NOT NULL` AND `status='uploaded'` | 873 |
| `gemini_store_doc_id` column exists | No |
| `gemini_state` column exists | No |
| `gemini_state_updated_at` column exists | No |
| Total file records | 1,884 (873 uploaded + 864 pending + 136 skipped + 11 failed) |

### Existing check_stability.py (v1) Assessment
The existing script at `scripts/check_stability.py` is 507 lines and implements the 6 checks conceptually, but:
- Uses `status='uploaded'` instead of `gemini_state='indexed'` for assertions 1-3
- Has no vacuous-pass logic for empty stores (assertion 5 would FAIL on empty store)
- Exit code 2 is used for setup errors, but STAB-03 (old store name detection) is not implemented
- Uses `DEFAULT_STORE = "objectivism-library-test"` -- needs to change to `"objectivism-library"`
- `main()` calls `sys.exit()` instead of returning the exit code (needs `if __name__ == '__main__': sys.exit(main())` pattern)
- The `StabilityChecker` class structure is sound and should be preserved/evolved

## Open Questions

1. **Should the migration script be idempotent?**
   - What we know: The user wants a one-time migration, but if it fails partway through, re-running should be safe.
   - What's unclear: The CONTEXT.md defines recovery logic for store state combinations, which implies idempotency is expected.
   - Recommendation: Yes, make it idempotent. Check store states before each step. Check user_version before ALTER TABLE. Check if gemini_state column already has values before running the UPDATE.

2. **Should `check_stability.py` use `--store` as required or optional?**
   - What we know: CONTEXT.md says `--store <name>` (required). The existing v1 has it as optional with a default.
   - What's unclear: Making it required means you always have to type it.
   - Recommendation: Keep the existing v1 pattern of optional with default, but change the default from `objectivism-library-test` to `objectivism-library` after migration. This is consistent with STAB-03: passing the old store name should return exit 2.

3. **Where does the migration script live?**
   - What we know: It needs user confirmation, so it cannot be in `_setup_schema()`.
   - What's unclear: `scripts/` vs `src/objlib/` -- both patterns exist in the project.
   - Recommendation: `scripts/migrate_phase8.py` following the existing `scripts/check_stability.py` pattern. Standalone, `if __name__ == '__main__'` entry point.

## Sources

### Primary (HIGH confidence)
- `google-genai` SDK 1.63.0, verified via Python introspection:
  - `FileSearchStore` model fields (active_documents_count, pending_documents_count, etc.)
  - `file_search_stores.get()`, `.create()`, `.delete()` method signatures
  - `DeleteFileSearchStoreConfig.force` parameter behavior
  - Async equivalents: `client.aio.file_search_stores.*` (same method set)
- `src/objlib/database.py` -- Current schema, migration pattern (V1-V8), user_version convention
- `src/objlib/upload/client.py` -- GeminiFileSearchClient methods available
- `scripts/check_stability.py` -- Existing v1 implementation structure
- SQLite ALTER TABLE behavior verified via in-memory tests (3 ADD COLUMN in transaction: works)
- Current DB state verified via direct query: 873 uploaded, user_version=8, no new columns yet

### Secondary (MEDIUM confidence)
- `src/objlib/config.py` -- API key retrieval pattern (keyring + env var fallback)
- `src/objlib/search/client.py` -- Store name resolution pattern
- `src/objlib/cli.py` -- App callback pattern, store-sync command pattern

### Tertiary (LOW confidence)
- None. All findings verified against codebase or SDK introspection.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already in use, no new dependencies
- Architecture: HIGH -- migration pattern is established (8 versions); store API verified via introspection
- Pitfalls: HIGH -- force=True requirement verified via SDK source; WAL backup behavior is well-documented SQLite behavior; ALTER TABLE idempotency tested
- API surface: HIGH -- every method signature and type field verified via live Python introspection of installed SDK

**Research date:** 2026-02-19
**Valid until:** 2026-03-19 (stable -- SQLite and google-genai SDK are not moving fast)
