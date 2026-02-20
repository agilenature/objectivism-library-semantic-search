# Phase 10: Transition Atomicity Spike - Research

**Researched:** 2026-02-20
**Domain:** Write-ahead intent pattern, crash recovery, idempotent API wrappers, asyncio crash simulation
**Confidence:** HIGH

## Summary

Phase 10 implements a write-ahead intent pattern for the two-API-call reset transition (delete_store_document + delete_file + DB finalize). The research confirms all locked decisions are technically feasible with the existing stack. The key technical findings are: (1) google-genai SDK raises `google.genai.errors.ClientError` with `code=404` for deleted resources -- verified empirically against SDK v1.63.0; (2) python-statemachine 2.6.0 requires removing `final=True` from `failed` and `indexed` states to enable `retry` and `reset` transitions; (3) `asyncio.CancelledError` is a `BaseException` (not `Exception`), so it propagates through `except Exception:` blocks, making it an effective crash simulator; (4) aiosqlite ALTER TABLE + PRAGMA table_info provides a clean idempotent migration pattern.

The spike will live in `spike/phase10_spike/` following the same structure as Phase 9's spike. All tests run against in-memory SQLite with mocked Gemini API calls. The two-transaction OCC pattern (Txn A writes intent, Txn B finalizes with version increment) has been verified to work correctly with aiosqlite.

**Primary recommendation:** Follow the Phase 9 spike structure exactly. Extend the FSM with `reset` and `retry` transitions (removing `final=True` from indexed/failed). Use `google.genai.errors.ClientError` with `exc.code == 404` for safe_delete wrappers. Use mock `side_effect` + `asyncio.CancelledError` for crash simulation.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

**GA-1: Write-ahead intent = extra columns on `files` table**
- `intent_type TEXT` (NULL or 'reset_intent')
- `intent_started_at TEXT` (ISO timestamp)
- `intent_api_calls_completed INTEGER` (0, 1, or 2)
- NOT a new FSM state, NOT a separate table

**GA-2: API idempotency**
- safe_delete wrappers: 404 = success, all other errors re-raise
- Must empirically confirm google-genai SDK exception class for 404

**GA-3: Recovery crawler**
- Startup blocking recovery as primary mechanism
- Optional background monitor (detect only, no auto-recovery)
- Scans: WHERE intent_type IS NOT NULL

**GA-4: FAILED state escape**
- FAILED -> UNTRACKED via `retry` FSM event
- CLI command `objlib recover --failed`
- No auto-retry from recovery crawler (prevents loops)

**GA-5: Crash simulation**
- Mock side_effect + asyncio.CancelledError
- Three focused crash point tests
- Fresh RecoveryCrawler instance verifies recovery

**GA-6: OCC + intent atomicity**
- Txn A: write intent columns (no version increment) WHERE gemini_state='indexed' AND version=N
- Progress tracking: UPDATE intent_api_calls_completed (no OCC check needed)
- Txn B: finalize with OCC WHERE version=N; sets gemini_state='untracked', version=N+1, clears intent

**GA-7: Reset end state = UNTRACKED**
- FSM path: INDEXED -> (intent) -> (APIs) -> UNTRACKED
- Not UPLOADING, not FAILED

**GA-8: Minimal observability**
- INFO log per recovered file
- objlib status shows count of files with active intent

**GA-9: SC3 measurement = line count**
- Recovery code for all 3 crash point handlers combined <= lines of transition code
- Each recovery path: single focused test <= 40 lines
- Zero retry loops in recovery code

### Claude's Discretion
- Internal code organization within `spike/phase10_spike/`
- Naming conventions for test files and helper modules
- Whether to reuse Phase 9 modules or copy/adapt them

### Deferred Ideas (OUT OF SCOPE)
- Production integration in `src/objlib/` (Phase 12+)
- UPLOADING state cleanup at startup (Phase 13)
- Dedicated `intents list` CLI command (Phase 13+)
- Formal cyclomatic complexity measurement
- Background recovery monitor implementation (optional, not required for gate)

</user_constraints>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| python-statemachine | 2.6.0 | FSM definition and transitions | Already selected in Phase 9; async support verified |
| aiosqlite | (installed) | Async SQLite for spike DB operations | Phase 9 standard; per-connection WAL + BEGIN IMMEDIATE |
| google-genai | 1.63.0 | Gemini API SDK (mocked in spike) | Production dependency; error classes used for safe_delete |
| pytest | (installed) | Test framework | Project standard |
| pytest-asyncio | >=0.24 | Async test support | Project config: `asyncio_mode = "auto"` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| unittest.mock | stdlib | AsyncMock, patch, side_effect | Crash simulation, API mocking |
| asyncio | stdlib | CancelledError for crash simulation | Crash point 2/3 testing |

### Alternatives Considered
None -- all libraries are locked from Phase 9 decisions and CONTEXT.md.

**Installation:**
No new dependencies required. All libraries are already installed.

## Architecture Patterns

### Recommended Project Structure
```
spike/phase10_spike/
    __init__.py
    db.py                    # Extended schema (Phase 9 + intent columns + gemini IDs)
    exceptions.py            # Reuse Phase 9 or extend
    states.py                # Extended states (add reset, retry, fail_reset events)
    safe_delete.py           # safe_delete_store_document(), safe_delete_file()
    transition_reset.py      # ResetTransitionManager (Txn A -> APIs -> Txn B)
    recovery_crawler.py      # RecoveryCrawler (startup scan + per-file recovery)
    tests/
        __init__.py
        conftest.py          # Fixtures: spike_db, seed_file (with intent columns)
        test_crash_points.py # 3 crash point tests (CP1, CP2, CP3)
        test_recovery.py     # RecoveryCrawler tests + FAILED->UNTRACKED
        test_safe_delete.py  # safe_delete wrapper tests (404 handling)
```

### Pattern 1: Extended FSM (No final States)
**What:** Remove `final=True` from `indexed` and `failed` states to enable `reset` (indexed->untracked) and `retry` (failed->untracked) transitions.
**When to use:** Always in Phase 10 spike (required by GA-4, GA-7).
**Critical finding:** python-statemachine 2.6.0 raises `InvalidDefinition: Cannot declare transitions from final state` if you try to add outgoing transitions from a `final=True` state. Verified empirically.
**Example:**
```python
# Source: Empirical verification against python-statemachine 2.6.0
from statemachine import State, StateMachine

class FileLifecycleSM(StateMachine):
    untracked = State("untracked", initial=True, value="untracked")
    uploading = State("uploading", value="uploading")
    processing = State("processing", value="processing")
    indexed = State("indexed", value="indexed")       # NOT final=True
    failed = State("failed", value="failed")           # NOT final=True

    # Forward transitions
    start_upload = untracked.to(uploading, cond="cond_not_stale")
    complete_upload = uploading.to(processing, cond="cond_not_stale")
    complete_processing = processing.to(indexed, cond="cond_not_stale")
    fail_upload = uploading.to(failed)
    fail_processing = processing.to(failed)

    # Phase 10 additions
    reset = indexed.to(untracked)       # GA-7: reset end state = UNTRACKED
    retry = failed.to(untracked)        # GA-4: FAILED escape path
    fail_reset = indexed.to(failed)     # Transition on reset failure
```

### Pattern 2: Two-Transaction Reset with Write-Ahead Intent
**What:** Txn A records intent before API calls; Txn B finalizes after APIs complete. Version only increments at Txn B.
**When to use:** For any multi-API-call transition (currently: reset only).
**Example:**
```python
# Source: Verified against aiosqlite with WAL mode

# Txn A: Record intent (no version increment)
async def write_intent(db_path: str, file_path: str, expected_version: int) -> bool:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            """UPDATE files SET
                intent_type = 'reset_intent',
                intent_started_at = ?,
                intent_api_calls_completed = 0
            WHERE file_path = ?
                AND gemini_state = 'indexed'
                AND version = ?""",
            (datetime.now(timezone.utc).isoformat(), file_path, expected_version),
        )
        await db.commit()
        return cursor.rowcount == 1

# Progress tracking (no OCC check)
async def update_progress(db_path: str, file_path: str, completed: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(
            "UPDATE files SET intent_api_calls_completed = ? WHERE file_path = ?",
            (completed, file_path),
        )
        await db.commit()

# Txn B: Finalize with OCC (version increment)
async def finalize_reset(db_path: str, file_path: str, expected_version: int) -> bool:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            """UPDATE files SET
                gemini_state = 'untracked',
                gemini_store_doc_id = NULL,
                gemini_file_id = NULL,
                intent_type = NULL,
                intent_started_at = NULL,
                intent_api_calls_completed = NULL,
                version = version + 1,
                gemini_state_updated_at = ?
            WHERE file_path = ?
                AND version = ?
                AND intent_type = 'reset_intent'""",
            (datetime.now(timezone.utc).isoformat(), file_path, expected_version),
        )
        await db.commit()
        return cursor.rowcount == 1
```

### Pattern 3: Safe Delete Wrappers
**What:** Idempotent delete wrappers that treat 404 as success.
**When to use:** All delete API calls during reset and recovery.
**Example:**
```python
# Source: Empirical verification against google-genai 1.63.0
from google.genai import errors as genai_errors

async def safe_delete_store_document(
    delete_fn,  # Callable (or mock) that performs the delete
    document_name: str,
) -> bool:
    """Delete store document. 404 = success (already deleted)."""
    try:
        await delete_fn(document_name)
        return True
    except genai_errors.ClientError as exc:
        if exc.code == 404:
            return True  # Already deleted; idempotent success
        raise  # 403, 400, etc. -> propagate

async def safe_delete_file(
    delete_fn,  # Callable (or mock) that performs the delete
    file_name: str,
) -> bool:
    """Delete raw file. 404 = success (already deleted or expired)."""
    try:
        await delete_fn(file_name)
        return True
    except genai_errors.ClientError as exc:
        if exc.code == 404:
            return True  # Already deleted or TTL expired
        raise
```

### Pattern 4: Crash Point Simulation
**What:** Use mock `side_effect` to inject failures at specific points; use `asyncio.CancelledError` for DB-write crash simulation.
**When to use:** All three crash point tests.
**Critical finding:** `asyncio.CancelledError` is a `BaseException`, NOT an `Exception`. This means `except Exception:` blocks will NOT catch it, making it propagate like a real process crash would. This is the correct behavior for crash simulation.
**Example:**
```python
# Source: Empirical verification against Python 3.13

# Crash Point 1: delete_store_document succeeds, delete_file crashes
mock_delete_store_doc = AsyncMock(return_value=None)  # succeeds
mock_delete_file = AsyncMock(side_effect=RuntimeError("simulated crash"))

# Crash Point 2: both APIs succeed, crash before Txn B
# Use CancelledError to escape through except Exception blocks
mock_delete_store_doc = AsyncMock(return_value=None)
mock_delete_file = AsyncMock(return_value=None)
# Then raise asyncio.CancelledError before finalize_reset()

# Crash Point 3: both APIs succeed, Txn B fails
# Mock the finalize DB write to raise
mock_finalize = AsyncMock(side_effect=RuntimeError("DB crash"))
```

### Pattern 5: Recovery Crawler
**What:** Startup-blocking scan of `WHERE intent_type IS NOT NULL`; resumes from last completed step.
**When to use:** At application startup, before any transitions.
**Example:**
```python
# Source: Phase 10 CONTEXT.md decisions

class RecoveryCrawler:
    def __init__(self, db_path: str, delete_store_doc_fn, delete_file_fn):
        self.db_path = db_path
        self._delete_store_doc = delete_store_doc_fn
        self._delete_file = delete_file_fn

    async def recover_all(self) -> list[str]:
        """Scan and recover all files with active intent. Returns recovered file paths."""
        rows = await self._scan_pending_intents()
        recovered = []
        for row in rows:
            await self._recover_file(row)
            recovered.append(row["file_path"])
        return recovered

    async def _scan_pending_intents(self) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT file_path, intent_type, intent_api_calls_completed,
                          gemini_store_doc_id, gemini_file_id, version
                   FROM files WHERE intent_type IS NOT NULL
                   ORDER BY intent_started_at ASC"""
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def _recover_file(self, row: dict) -> None:
        """Resume from last completed step. Linear step resumption, no retry loops."""
        file_path = row["file_path"]
        completed = row["intent_api_calls_completed"]

        # Step 1: delete_store_document (if not already done)
        if completed < 1:
            await safe_delete_store_document(self._delete_store_doc, row["gemini_store_doc_id"])
            await update_progress(self.db_path, file_path, 1)

        # Step 2: delete_file (if not already done)
        if completed < 2:
            await safe_delete_file(self._delete_file, row["gemini_file_id"])
            await update_progress(self.db_path, file_path, 2)

        # Step 3: finalize (always needed -- if we're here, Txn B hasn't run)
        await finalize_reset(self.db_path, file_path, row["version"])
        logger.info("Recovered %s: %s cp=%d", file_path, row["intent_type"], completed)
```

### Anti-Patterns to Avoid
- **Marking `indexed` or `failed` as `final=True`:** python-statemachine 2.6.0 raises `InvalidDefinition` for outgoing transitions from final states. Use non-final states with no _implicit_ outgoing transitions.
- **Incrementing version in Txn A:** Version should ONLY increment at finalization (Txn B). If Txn A increments, recovery sees version=N+1 but file is still logically INDEXED, breaking OCC invariants.
- **OCC check on progress updates:** Progress tracking (`intent_api_calls_completed`) does not need OCC version check. It's written by the single coroutine holding the file lock. Adding OCC here creates unnecessary failure modes.
- **Auto-retrying FAILED files in recovery crawler:** Creates infinite loops if the failure is persistent. FAILED -> UNTRACKED must be explicit CLI action (GA-4).
- **Using `except Exception:` to catch `asyncio.CancelledError`:** CancelledError is a BaseException. If your code catches Exception to handle API errors, CancelledError will propagate through it -- this is the DESIRED behavior for crash simulation.
- **Sharing aiosqlite connections between Txn A and Txn B:** Each transaction must use its own connection (per Phase 9 locked decision: per-transaction connection factory).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| FSM state machine | Custom if/else state logic | python-statemachine 2.6.0 | Already proven in Phase 9; handles guard conditions, state validation |
| Async DB operations | Raw sqlite3 with threads | aiosqlite | Already proven in Phase 9; WAL + BEGIN IMMEDIATE pattern established |
| 404 detection | String matching on exception message | `genai_errors.ClientError` with `exc.code == 404` | Typed exception with integer code is more reliable than string matching |
| Test async functions | Manual event loop management | pytest-asyncio with `asyncio_mode="auto"` | Project-wide configuration; automatic async test detection |

**Key insight:** The existing production `delete_store_document()` in `src/objlib/upload/client.py` uses string matching (`"404" in exc_str or "NOT_FOUND" in exc_str`). The spike should use the proper typed exception check (`isinstance(exc, ClientError) and exc.code == 404`) which is more reliable. This pattern can later replace the string matching in production.

## Common Pitfalls

### Pitfall 1: final=True Blocks Outgoing Transitions
**What goes wrong:** Adding `reset = indexed.to(untracked)` when `indexed` is marked `final=True` raises `InvalidDefinition` at class definition time (not at runtime).
**Why it happens:** python-statemachine enforces that final states have zero outgoing transitions.
**How to avoid:** Remove `final=True` from both `indexed` and `failed` states in the Phase 10 FSM. Neither state is truly "final" anymore.
**Warning signs:** `InvalidDefinition: Cannot declare transitions from final state. Invalid state(s): ['indexed']`

### Pitfall 2: CancelledError Not Caught by except Exception
**What goes wrong:** In Python 3.9+, `asyncio.CancelledError` inherits from `BaseException`, not `Exception`. Code that does `except Exception as e:` will NOT catch it.
**Why it happens:** Python 3.9 changed the inheritance (previously it was an Exception subclass).
**How to avoid:** For crash simulation, this is actually DESIRED. For error handling in production code that must also handle cancellation, use `except BaseException:` or explicit `except asyncio.CancelledError:`.
**Warning signs:** Test seems to "pass through" the except block without being caught.

### Pitfall 3: Txn A OCC Race with Concurrent Reset Requests
**What goes wrong:** Two coroutines both try to write intent for the same file. Without the per-file lock, both could read version=N, but only one UPDATE will match.
**How to avoid:** Always acquire `FileLockManager.acquire(file_path)` before Txn A. The per-file lock serializes concurrent requests. The OCC `WHERE version=?` check is the safety net if the lock is bypassed.
**Warning signs:** Txn A returns rowcount=0 unexpectedly.

### Pitfall 4: Recovery Crawler Must Use safe_delete (Not Raw Delete)
**What goes wrong:** Recovery re-deletes a resource that was already deleted in the original attempt. Raw delete raises 404 error, which triggers FAILED state.
**Why it happens:** Crash point 1 means delete_store_document already succeeded. Recovery calls it again.
**How to avoid:** RecoveryCrawler ALWAYS uses `safe_delete_store_document()` and `safe_delete_file()`, never raw delete methods.
**Warning signs:** Recovery transitions file to FAILED instead of UNTRACKED.

### Pitfall 5: Spike DB Schema Must Include gemini_file_id and gemini_store_doc_id
**What goes wrong:** Phase 9 spike DB only has `file_path, gemini_state, version, last_error, failure_info`. The reset transition needs `gemini_file_id` and `gemini_store_doc_id` to know WHAT to delete.
**Why it happens:** Phase 9 only tested state transitions, not API-interacting transitions.
**How to avoid:** Phase 10 spike DB schema must extend Phase 9 with: `gemini_file_id TEXT`, `gemini_store_doc_id TEXT`, `intent_type TEXT`, `intent_started_at TEXT`, `intent_api_calls_completed INTEGER`.
**Warning signs:** Recovery crawler can't find the resource names to delete.

### Pitfall 6: aiosqlite Connection Must Configure WAL on Every Connection
**What goes wrong:** `PRAGMA journal_mode=WAL` is per-connection in SQLite. A new `aiosqlite.connect()` starts in DELETE journal mode by default.
**Why it happens:** SQLite pragmas are connection-scoped, not database-scoped (though WAL mode persists on disk once set, the PRAGMA still needs to be issued).
**How to avoid:** Call `_configure_connection(db)` on every new aiosqlite connection, as Phase 9's `db.py` already does.
**Warning signs:** "database is locked" errors under concurrent access.

## Code Examples

### Extended Spike DB Schema
```python
# Source: Phase 9 db.py + CONTEXT.md GA-1 locked decisions

async def init_spike_db(db_path: str) -> None:
    """Create the Phase 10 spike schema. Extends Phase 9 with intent + ID columns."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS files (
                file_path TEXT PRIMARY KEY,
                gemini_state TEXT NOT NULL DEFAULT 'untracked',
                gemini_state_updated_at TEXT,
                version INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                failure_info TEXT,
                -- Phase 10 additions: Gemini resource IDs
                gemini_file_id TEXT,
                gemini_store_doc_id TEXT,
                -- Phase 10 additions: Write-ahead intent columns (GA-1)
                intent_type TEXT,
                intent_started_at TEXT,
                intent_api_calls_completed INTEGER
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_gemini_state ON files(gemini_state)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_intent ON files(intent_type)"
        )
        await db.commit()
```

### Seed Fixture for Indexed File (Ready for Reset)
```python
# Source: Phase 9 conftest.py pattern extended for Phase 10

@pytest.fixture
def seed_indexed_file(spike_db):
    """Factory to insert a file in 'indexed' state with Gemini IDs."""
    import aiosqlite

    async def _seed(
        file_path: str,
        gemini_file_id: str = "files/test123",
        gemini_store_doc_id: str = "fileSearchStores/store1/documents/doc1",
        version: int = 5,
    ) -> None:
        async with aiosqlite.connect(spike_db) as db:
            await db.execute(
                """INSERT INTO files
                   (file_path, gemini_state, version, gemini_file_id, gemini_store_doc_id)
                   VALUES (?, 'indexed', ?, ?, ?)""",
                (file_path, version, gemini_file_id, gemini_store_doc_id),
            )
            await db.commit()

    return _seed
```

### Crash Point Test Template
```python
# Source: Phase 9 test_error_injection.py pattern + CONTEXT.md GA-5

async def test_crash_point_1_after_delete_store_doc(spike_db, seed_indexed_file):
    """CP1: delete_store_document succeeds, crash before delete_file.
    Recovery: safe_delete both (404=ok for first), finalize to untracked."""
    file_path = "/test/cp1.txt"
    await seed_indexed_file(file_path)

    # Set up mocks: store doc delete succeeds, file delete crashes
    mock_delete_store_doc = AsyncMock(return_value=None)
    mock_delete_file = AsyncMock(side_effect=RuntimeError("simulated crash"))

    # Run transition (should fail at delete_file)
    manager = ResetTransitionManager(spike_db, mock_delete_store_doc, mock_delete_file)
    with pytest.raises(RuntimeError, match="simulated crash"):
        await manager.execute_reset(file_path)

    # Verify partial state: intent recorded, API call 1 completed
    state, version = await read_file_state(spike_db, file_path)
    assert state == "indexed"  # Not yet finalized
    intent = await read_intent(spike_db, file_path)
    assert intent["intent_api_calls_completed"] == 1

    # Recovery: fresh crawler with safe_delete wrappers
    mock_safe_delete_doc = AsyncMock(return_value=True)   # 404 = success
    mock_safe_delete_file = AsyncMock(return_value=True)   # 404 = success
    crawler = RecoveryCrawler(spike_db, mock_safe_delete_doc, mock_safe_delete_file)
    recovered = await crawler.recover_all()

    # Verify recovery
    assert file_path in recovered
    state, version = await read_file_state(spike_db, file_path)
    assert state == "untracked"
    assert version == 6  # version incremented by Txn B
    intent = await read_intent(spike_db, file_path)
    assert intent["intent_type"] is None  # Intent cleared
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `asyncio.CancelledError(Exception)` | `asyncio.CancelledError(BaseException)` | Python 3.9 | `except Exception:` no longer catches cancellation |
| String-matching 404 errors | Typed `ClientError` with `exc.code` | google-genai 1.x | More reliable error classification |
| Phase 9: `final=True` on indexed/failed | Phase 10: Non-final states | Phase 10 | Enables reset and retry transitions |
| Phase 9: Single-event transitions only | Phase 10: Multi-step transitions with intent | Phase 10 | Write-ahead intent tracks progress across API calls |

**Deprecated/outdated:**
- The existing `delete_store_document()` in `src/objlib/upload/client.py` uses string matching for 404 detection (`"404" in exc_str`). The Phase 10 spike should demonstrate the typed `ClientError` approach as the replacement pattern.

## Open Questions

1. **Should ResetTransitionManager bypass FileTransitionManager or extend it?**
   - What we know: FileTransitionManager does single-event transitions (read state, create adapter, trigger, read state). The reset transition needs Txn A + API calls + Txn B, which is a fundamentally different flow.
   - What's unclear: Whether to create a separate `ResetTransitionManager` class or extend `FileTransitionManager` with a `trigger_multi_step()` method.
   - Recommendation: Create a separate `ResetTransitionManager` class for the spike. It can use `FileLockManager` for per-file locking but manages its own transaction flow. Cleaner separation for spike code; production integration can decide on the final structure.

2. **How to handle the `on_enter_state` callback for the reset transition?**
   - What we know: Phase 9's `on_enter_state` in `StateMachineAdapter` writes the state change to DB with OCC. The reset transition's Txn B serves this purpose instead.
   - What's unclear: If `ResetTransitionManager` calls `sm.send('reset')` on the FSM, the `on_enter_state` will fire and try to do its own DB write with OCC.
   - Recommendation: The reset transition should NOT use the `StateMachineAdapter.trigger()` path. Instead, `ResetTransitionManager` manages the DB writes directly (Txn A and Txn B). The FSM adapter is not used for multi-step transitions. Alternatively, the `on_enter_state` could detect reset transitions and skip its write. For the spike, direct DB management is simpler.

3. **Should the spike reuse or copy Phase 9 modules?**
   - What we know: Phase 9 spike code is in `spike/phase9_spike/`. Phase 10 spike will be in `spike/phase10_spike/`.
   - Recommendation: Import and reuse `FileLockManager` and `EventCollector` from Phase 9. Copy and extend `db.py` (new schema), `states.py` (new events), and `exceptions.py` (if needed). Don't modify Phase 9 code.

## Sources

### Primary (HIGH confidence)
- **google-genai SDK v1.63.0** - Empirically verified: `google.genai.errors.ClientError` with `code=404`, `status='NOT_FOUND'` for deleted resources. Exception hierarchy: `APIError > ClientError (4xx)`, `APIError > ServerError (5xx)`. Verified via `pip show google-genai` and `inspect.getsource()`.
- **python-statemachine 2.6.0** - Empirically verified: `final=True` states cannot have outgoing transitions (`InvalidDefinition` error). Async `send()` works correctly. `start_value` parameter initializes FSM at a given state.
- **aiosqlite** - Empirically verified: ALTER TABLE ADD COLUMN, PRAGMA table_info for column-exists check, BEGIN IMMEDIATE for write locks, per-connection WAL mode.
- **Python 3.13 asyncio** - Empirically verified: `asyncio.CancelledError` inherits from `BaseException`, not `Exception`.

### Secondary (MEDIUM confidence)
- **Phase 9 spike code** (`spike/phase9_spike/`) - Reviewed all modules: `db.py`, `states.py`, `exceptions.py`, `protocol.py`, `event_log.py`, `adapters/statemachine_adapter.py`, `integration/scaffold.py`, all test files. Patterns and fixtures verified.
- **Production code** (`src/objlib/upload/client.py`) - Reviewed `_safe_call`, `delete_file`, `delete_store_document`, `find_store_document_name`. Existing 404 handling uses string matching; spike improves this.
- **Production DB** (`src/objlib/database.py`) - Reviewed migration V9 pattern. Production DB does NOT have a `version` column (only spike DB has it). Phase 10 spike creates its own schema.

### Tertiary (LOW confidence)
- None. All findings empirically verified.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries empirically verified, same as Phase 9
- Architecture: HIGH - Two-transaction pattern verified with aiosqlite, FSM transitions verified with python-statemachine
- Pitfalls: HIGH - All pitfalls discovered through empirical testing (final=True error, CancelledError inheritance, schema gaps)
- API error handling: HIGH - google-genai error classes inspected at source level and instantiated

**Research date:** 2026-02-20
**Valid until:** 2026-03-20 (stable stack, no fast-moving dependencies)
