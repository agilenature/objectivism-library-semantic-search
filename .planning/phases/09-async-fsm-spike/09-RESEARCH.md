# Phase 9: Wave 1 -- Async FSM Library Spike - Research

**Researched:** 2026-02-20
**Domain:** Async state machine implementation with concurrent SQLite writes
**Confidence:** MEDIUM-HIGH (library API verified via Context7 + official docs; some aiosqlite edge cases LOW)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

| Decision | Choice | Confidence |
|----------|--------|-----------|
| Library | python-statemachine (pivot to hand-rolled if async guard fails) | Recommended |
| Fallback library | None -- pivot directly to hand-rolled | Consensus |
| Affirmative evidence | JSON log + DB invariants + thread/task leak check | Consensus |
| Same-file concurrency | asyncio.Lock + DB version column (OCC), reject on conflict | Consensus |
| Error recovery | Rollback if pre-commit; `failed` if post-commit | Consensus |
| DB authority | DB is sole source of truth; in-memory is cache | Consensus |
| FSM lifecycle | Ephemeral per transition in spike | Recommended |
| WAL mode | Enabled in spike test DB from the start | Recommended |
| Protocol interface | Defined before library trial | Recommended |
| aiosqlite pattern | Per-transition connection via factory (no sharing) | Consensus |
| SQLITE_BUSY retry | 3 attempts, 50ms initial, 2x multiplier | Needs tuning |

### Claude's Discretion

- Exact file/module structure for the spike
- JSON log format details (field names, structure)
- DB invariant checker implementation approach
- Test harness runner structure (single script vs pytest)
- How to implement the thread/task leak check

### Deferred Ideas (OUT OF SCOPE)

- Performance thresholds (Phase 14)
- Transition log DB table (Phase 12)
- `failed -> untracked` recovery path (Phase 10)
- Long-lived FSM instances with per-file locks (Phase 12)
- Property-based testing enhancement (iterative addition)
- STALE state and scanner (v3)
- Concurrency lock (v3)
</user_constraints>

## Summary

Phase 9 requires proving that an FSM approach works correctly under adversarial concurrent async conditions with aiosqlite writes. The locked decision is to trial `python-statemachine` 2.6.0 first, with immediate pivot to hand-rolled if async guards fail.

Research confirms that `python-statemachine` 2.6.0 has genuine native async support via its `AsyncEngine`, including async guards (`cond` parameter referencing `async def` methods), async callbacks (`on_enter_*`, `on_exit_*`, `before_*`, `on_*`, `after_*`), and a sophisticated dependency injection system that passes trigger arguments to callbacks. The library automatically selects `AsyncEngine` when any callback is async, and when instantiated inside a running event loop (as with `asyncio.run()` from Typer), it reuses that loop rather than creating a new one. This is the critical compatibility point for the Typer integration pattern.

The aiosqlite pattern is well-established in this project (see `AsyncUploadStateManager`). Per-transition connections with `BEGIN IMMEDIATE`, WAL mode, and exponential backoff for `sqlite3.OperationalError("database is locked")` are the verified approach. The main risk area is the interaction between python-statemachine's callback execution model and the ephemeral DB connection pattern -- the spike must prove this works.

**Primary recommendation:** Define `FileStateMachineProtocol` first, then implement a python-statemachine adapter that delegates DB writes to per-transition aiosqlite connections. Test with 10 concurrent transitions including same-file adversarial cases. If async guards fail (the library calls the guard synchronously instead of awaiting it), pivot to a hand-rolled async FSM class that satisfies the same Protocol.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| python-statemachine | 2.6.0 | FSM framework with native async support | AsyncEngine, async guards, dependency injection for trigger args |
| aiosqlite | 0.22.1 | Async SQLite bridge | Already a project dependency; per-connection background thread |
| asyncio (stdlib) | Python 3.13 | Event loop, Lock, gather | Standard async primitives |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-asyncio | >=0.24 | Async test support | Already in dev dependencies; `asyncio_mode = "auto"` configured |
| json (stdlib) | -- | Structured event log | Emit JSON lines to stdout during test harness |
| threading (stdlib) | -- | Thread leak detection | `threading.active_count()` baseline check |
| uuid (stdlib) | -- | Attempt ID generation | Unique ID per transition attempt for log correlation |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| python-statemachine | Hand-rolled class | Full control, no dependency, but must build guard dispatch, callback routing, transition validation manually. Falls back to this if library trial fails. |
| python-statemachine | pytransitions AsyncMachine | Documented async issues; requires AsyncState not base State; bolted-on async. All providers recommend against. |
| aiosqlite | asqlite (rapptz) | Higher benchmark score (92.8 vs 60.7), built-in WAL + FK defaults, connection pooling. But not currently in project deps; aiosqlite already proven in codebase. |

**Installation:**
```bash
pip install python-statemachine==2.6.0
```

Note: `aiosqlite>=0.22` and `pytest-asyncio>=0.24` already in `pyproject.toml`.

## Architecture Patterns

### Recommended Spike File Structure
```
spike/                              # Isolated spike directory (NOT in src/objlib)
  phase9_spike/
    __init__.py
    protocol.py                     # FileStateMachineProtocol
    states.py                       # FSM state/transition definitions
    db.py                           # Per-transition aiosqlite connection factory + OCC
    exceptions.py                   # StaleTransitionError, GuardRejectedError
    event_log.py                    # Structured JSON log emitter
    adapters/
      __init__.py
      statemachine_adapter.py       # python-statemachine implementation
      handrolled_adapter.py         # Fallback hand-rolled implementation (if needed)
    tests/
      __init__.py
      test_async_guards.py          # Binary pass/fail: async guard with DB query
      test_concurrent_transitions.py # 10 concurrent transitions, same-file rejection
      test_error_injection.py       # Pre-commit, post-commit, guard failure injection
      test_db_invariants.py         # Post-run DB state validation
      test_leak_check.py            # Thread/task baseline comparison
      conftest.py                   # Spike-specific fixtures (tmp DB, etc.)
    harness.py                      # Adversarial test runner (combines all checks)
```

### Pattern 1: FileStateMachineProtocol (Interface-First)

**What:** Define the FSM interface as a Python Protocol before any implementation.
**When to use:** Always -- all test harness code targets this Protocol.
**Confidence:** HIGH (standard Python typing.Protocol pattern)

```python
# Source: CONTEXT.md locked decision Q6
from typing import Protocol, runtime_checkable

@runtime_checkable
class FileStateMachineProtocol(Protocol):
    """Interface for file lifecycle state machines.

    All test harness code is written against this Protocol.
    Both the python-statemachine adapter and the hand-rolled
    fallback must satisfy this interface.
    """

    @property
    def current_state(self) -> str:
        """Current FSM state as a string ('untracked', 'uploading', etc.)."""
        ...

    async def trigger(self, event: str, **kwargs) -> None:
        """Trigger a state transition.

        Args:
            event: Transition event name (e.g., 'start_upload', 'complete_processing')
            **kwargs: Passed through to guards and callbacks (e.g., db_path, file_id)

        Raises:
            StaleTransitionError: If OCC version check fails (concurrent modification)
            GuardRejectedError: If guard condition returns False
            TransitionNotAllowed: If event is invalid for current state
        """
        ...

    async def can_trigger(self, event: str, **kwargs) -> bool:
        """Check if the event can be triggered without side effects."""
        ...
```

### Pattern 2: python-statemachine Adapter with Async Guards

**What:** Wrap python-statemachine's StateMachine class to satisfy the Protocol.
**When to use:** Primary trial approach (Plan 09-01).
**Confidence:** MEDIUM (async guard support verified in docs but not yet tested in this stack)

```python
# Source: python-statemachine docs (Context7 + readthedocs)
from statemachine import StateMachine, State

class FileLifecycleSM(StateMachine):
    """python-statemachine FSM for file lifecycle.

    States: untracked -> uploading -> processing -> indexed -> failed
    """
    untracked = State("untracked", initial=True, value="untracked")
    uploading = State("uploading", value="uploading")
    processing = State("processing", value="processing")
    indexed = State("indexed", final=True, value="indexed")
    failed = State("failed", value="failed")

    # Transitions
    start_upload = untracked.to(uploading)
    complete_upload = uploading.to(processing)
    complete_processing = processing.to(indexed)

    # Error transitions (from any non-terminal state)
    fail_upload = uploading.to(failed)
    fail_processing = processing.to(failed)

    # Async guard: checks DB state before allowing transition
    async def cond_not_stale(self, file_id: str, db_path: str, expected_version: int) -> bool:
        """Guard that verifies OCC version before transition."""
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            row = await db.execute_fetchone(
                "SELECT version FROM files WHERE file_path = ?", (file_id,)
            )
            return row is not None and row[0] == expected_version

    # Async callback: writes state to DB
    async def on_enter_state(self, target: State, file_id: str, db_path: str, **kwargs):
        """Persist state change to DB on every state entry."""
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "UPDATE files SET gemini_state = ?, version = version + 1 WHERE file_path = ?",
                (target.value, file_id)
            )
            await db.commit()
```

**CRITICAL:** The `start_value` parameter enables ephemeral initialization from DB state:
```python
# Read current state from DB, then create ephemeral FSM
current_state = "uploading"  # from DB query
sm = FileLifecycleSM(start_value="uploading")
# sm.current_state_value == "uploading"
```

**CRITICAL for async context:** When instantiated inside `asyncio.run()`, must explicitly activate:
```python
async def transition_file(file_id, db_path):
    sm = FileLifecycleSM(start_value=current_db_state)
    await sm.activate_initial_state()  # Required in async context
    await sm.send("start_upload", file_id=file_id, db_path=db_path)
```

### Pattern 3: Per-Transition aiosqlite Connection Factory

**What:** Each transition callback opens its own aiosqlite connection; never shares connections.
**When to use:** Every DB write in FSM callbacks.
**Confidence:** HIGH (established pattern in this codebase -- see `AsyncUploadStateManager`)

```python
# Source: Existing pattern from src/objlib/upload/state.py + aiosqlite docs
import aiosqlite
import asyncio

async def execute_with_retry(
    db_path: str,
    sql: str,
    params: tuple = (),
    max_retries: int = 3,
    initial_delay: float = 0.05,
    multiplier: float = 2.0,
) -> int:
    """Execute a write with BEGIN IMMEDIATE and exponential backoff.

    Returns: rowcount from the executed statement.
    Raises: sqlite3.OperationalError after max_retries exhausted.
    """
    for attempt in range(max_retries):
        try:
            async with aiosqlite.connect(db_path) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA synchronous=NORMAL")
                await db.execute("PRAGMA foreign_keys=ON")
                await db.execute("BEGIN IMMEDIATE")
                cursor = await db.execute(sql, params)
                await db.commit()
                return cursor.rowcount
        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                delay = initial_delay * (multiplier ** attempt)
                await asyncio.sleep(delay)
            else:
                raise
    raise RuntimeError("Unreachable")
```

### Pattern 4: OCC with Version Column

**What:** Optimistic Concurrency Control using a `version INTEGER` column.
**When to use:** Every state-changing DB write in FSM callbacks.
**Confidence:** HIGH (standard OCC pattern)

```python
# The atomic state transition query
UPDATE_STATE_SQL = """
    UPDATE files
    SET gemini_state = ?,
        version = version + 1,
        gemini_state_updated_at = ?
    WHERE file_path = ?
      AND gemini_state = ?
      AND version = ?
"""

# In the transition callback:
rowcount = await execute_with_retry(
    db_path, UPDATE_STATE_SQL,
    (new_state, now_iso, file_id, expected_old_state, expected_version)
)
if rowcount == 0:
    raise StaleTransitionError(
        f"OCC conflict: file {file_id} was modified concurrently "
        f"(expected state={expected_old_state}, version={expected_version})"
    )
```

**Note:** The `version INTEGER DEFAULT 0` column must be added to the spike DB schema. Production DB already has `gemini_state` (Phase 8) but no `version` column yet -- that is Phase 10's migration concern.

### Pattern 5: Per-File asyncio.Lock

**What:** In-process lock per file_id to serialize concurrent transitions on the same file.
**When to use:** Before any transition attempt on a file.
**Confidence:** HIGH (standard asyncio pattern)

```python
import asyncio
from collections import defaultdict

class FileLockManager:
    """Manages per-file asyncio.Lock instances."""

    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def get_lock(self, file_id: str) -> asyncio.Lock:
        return self._locks[file_id]
```

**Usage in test harness:**
```python
lock_manager = FileLockManager()

async def attempt_transition(file_id: str, event: str, db_path: str):
    lock = lock_manager.get_lock(file_id)
    async with lock:
        # Read current state from DB
        # Create ephemeral FSM with start_value
        # Execute transition
        pass
```

### Pattern 6: Structured JSON Event Log

**What:** Every transition attempt emits a JSON line to stdout.
**When to use:** During all test harness runs.
**Confidence:** HIGH (standard structured logging)

```python
import json
import uuid
from datetime import datetime, timezone

def emit_event(
    file_id: str,
    from_state: str,
    to_state: str,
    event: str,
    outcome: str,  # "success" | "rejected" | "failed"
    guard_result: bool | None = None,
    error: str | None = None,
) -> dict:
    """Emit and return a structured JSON event line."""
    record = {
        "attempt_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "file_id": file_id,
        "event": event,
        "from_state": from_state,
        "to_state": to_state,
        "guard_result": guard_result,
        "outcome": outcome,
        "error": error,
    }
    print(json.dumps(record))
    return record
```

### Anti-Patterns to Avoid

- **Sharing aiosqlite connections across coroutines:** Each aiosqlite connection runs on a dedicated background thread. Sharing a connection between coroutines leads to overlapping actions on the same thread queue. Always open a fresh connection per callback.
- **Storing a live aiosqlite connection on the FSM instance:** The FSM is ephemeral; connections are ephemeral. Pass `db_path` (a factory parameter), not a connection.
- **Using aiosqlite's autocommit (implicit transactions):** Always use explicit `BEGIN IMMEDIATE` for writes to avoid deferred lock upgrades that fail under contention.
- **Checking in-memory FSM state after DB failure:** If the DB write fails, the in-memory state may have already been updated by the library. Always re-read from DB to determine true state.
- **Creating nested event loops:** Never call `asyncio.run()` inside a callback that is already running in an event loop. python-statemachine's AsyncEngine reuses the existing loop -- do not fight this.
- **Forgetting `activate_initial_state()` in async context:** When creating an FSM instance inside `asyncio.run()`, either call `await sm.activate_initial_state()` or send the first event immediately (which implicitly activates).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Guard dispatch + condition evaluation | Custom if/elif chain | python-statemachine `cond` parameter | Library handles boolean expressions, short-circuit evaluation, multiple guards per transition |
| Callback ordering (before/on/after) | Manual callback sequence | python-statemachine lifecycle hooks | Library guarantees correct execution order: validators -> conditions -> before -> exit -> on -> enter -> after |
| Dependency injection for callbacks | Manual kwargs plumbing | python-statemachine parameter injection | Library inspects callback signatures and injects only declared parameters automatically |
| Async/sync engine detection | Runtime `inspect.iscoroutinefunction` checks | python-statemachine automatic engine selection | Library detects async callbacks at class definition time and selects the right engine |
| SQLITE_BUSY retry with backoff | Sleep-loop | Dedicated `execute_with_retry()` utility | Encapsulates retry logic, jitter, and exception handling in one place |

**Key insight:** The library's value is NOT in state tracking (trivial) but in the guard/callback/injection machinery. If the library fails the async guard test, the hand-rolled replacement must still implement guard dispatch and callback ordering -- just without the library's help.

## Common Pitfalls

### Pitfall 1: python-statemachine `start_value` Type Mismatch
**What goes wrong:** Passing a string state name (like `"uploading"`) to `start_value` when states are defined with integer `value` parameters, or vice versa.
**Why it happens:** `start_value` matches against the `value` parameter on each `State()`, NOT the state's `id` or name.
**How to avoid:** Define all states with explicit string `value` parameters matching the DB enum values: `State("uploading", value="uploading")`. Then `start_value="uploading"` works directly.
**Warning signs:** `InvalidStateValue` exception on instantiation.

### Pitfall 2: `activate_initial_state()` Omission in Async Context
**What goes wrong:** Creating a `FileLifecycleSM(start_value=...)` inside `asyncio.run()` and immediately checking `current_state` raises `InvalidStateValue: There's no current state set`.
**Why it happens:** Python cannot `await` during `__init__`. If any state has async `on_enter_*` callbacks, initial state activation is deferred.
**How to avoid:** Always call `await sm.activate_initial_state()` after instantiation in async contexts, OR rely on the first `await sm.send(...)` call to implicitly activate.
**Warning signs:** `InvalidStateValue` exception when accessing `sm.current_state` before activation.

### Pitfall 3: In-Memory State Divergence After DB Write Failure
**What goes wrong:** python-statemachine updates its internal `current_state` during the transition callback chain. If the DB write inside `on_enter_state` fails, the in-memory state says "uploading" but the DB says "untracked".
**Why it happens:** The library updates state as part of its transition processing, before/during callbacks fire -- not after all callbacks succeed.
**How to avoid:** After any DB failure in a callback, either: (a) raise an exception that causes the FSM to handle the error, or (b) ignore in-memory state entirely and always re-read from DB. Since FSM instances are ephemeral (created per-transition, discarded after), divergence is short-lived. The test harness MUST verify DB state, never in-memory state.
**Warning signs:** Test assertions that check `sm.current_state` instead of DB state.

### Pitfall 4: aiosqlite Connection Sharing Under asyncio.gather
**What goes wrong:** Multiple coroutines sharing one aiosqlite connection via closure or global variable. Under `asyncio.gather`, they interleave `execute` and `commit` calls on the same connection's internal thread queue.
**Why it happens:** aiosqlite uses a single background thread per connection with a request queue. Multiple coroutines sending requests to the same queue get their operations interleaved.
**How to avoid:** Each coroutine opens its own `async with aiosqlite.connect(db_path) as db:` context.
**Warning signs:** Corrupted transactions, partial commits, "cannot operate on closed database" errors.

### Pitfall 5: BEGIN IMMEDIATE Omission
**What goes wrong:** Default SQLite transactions are DEFERRED. A `SELECT` starts a read transaction. A subsequent `UPDATE` in the same transaction tries to upgrade to a write lock, which fails if another connection holds a write lock.
**Why it happens:** DEFERRED is the default transaction mode; `BEGIN IMMEDIATE` must be explicit.
**How to avoid:** Always use `await db.execute("BEGIN IMMEDIATE")` before any state-update query in FSM callbacks.
**Warning signs:** `sqlite3.OperationalError: database is locked` even with WAL mode enabled, particularly under concurrent writes.

### Pitfall 6: Thread Leak from Unclosed aiosqlite Connections
**What goes wrong:** aiosqlite spawns a background thread per connection. If a connection is not properly closed (e.g., exception during callback skips the `async with` cleanup), the thread persists.
**Why it happens:** Exception propagation from within `async with` blocks should handle cleanup, but early returns or cancellation can bypass it.
**How to avoid:** Always use `async with aiosqlite.connect(...)` context manager. Never use the procedural open/close pattern. The thread/task leak check in the test harness will catch this.
**Warning signs:** `threading.active_count()` after harness > before harness.

### Pitfall 7: SQLite WAL Mode Persistence
**What goes wrong:** Setting `PRAGMA journal_mode=WAL` is persistent to the database file, not per-connection. If the spike accidentally sets WAL on a production database, it stays.
**Why it happens:** WAL mode is a database-level property, not a connection-level property.
**How to avoid:** The spike uses `/tmp/phase9_spike.db` exclusively. Production `data/library.db` is NEVER opened by spike code. The production DB already uses WAL (see `Database._setup_pragmas()`), so this is a minor concern, but isolation is still important.
**Warning signs:** N/A -- WAL is already production config.

## Code Examples

### Example 1: Complete Spike DB Schema (for /tmp/phase9_spike.db)

```sql
-- Minimal schema for Phase 9 spike (NOT production schema)
CREATE TABLE IF NOT EXISTS files (
    file_path TEXT PRIMARY KEY,
    gemini_state TEXT NOT NULL DEFAULT 'untracked',
    gemini_state_updated_at TEXT,
    version INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    failure_info TEXT
);

CREATE INDEX IF NOT EXISTS idx_gemini_state ON files(gemini_state);
```

### Example 2: Adversarial Same-File Concurrent Test

```python
# Source: Locked decision Q3 (reject immediately) + Q2 (affirmative evidence)
import asyncio

async def test_concurrent_same_file(db_path: str):
    """10 concurrent attempts to transition the same file.

    Expected: exactly 1 success, 9 rejections.
    """
    file_id = "/test/concurrent_file.txt"
    lock_manager = FileLockManager()
    results = []

    async def attempt(attempt_num: int):
        lock = lock_manager.get_lock(file_id)
        async with lock:
            # Read current state from DB
            async with aiosqlite.connect(db_path) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                row = await db.execute_fetchone(
                    "SELECT gemini_state, version FROM files WHERE file_path = ?",
                    (file_id,)
                )
                if row is None:
                    results.append(("failed", "file not found"))
                    return
                current_state, current_version = row

            if current_state != "untracked":
                # Already transitioned by another attempt
                results.append(("rejected", f"state already {current_state}"))
                emit_event(file_id, current_state, "uploading", "start_upload",
                          "rejected", guard_result=False)
                return

            # Attempt OCC transition
            rowcount = await execute_with_retry(
                db_path,
                """UPDATE files SET gemini_state = 'uploading',
                   version = version + 1,
                   gemini_state_updated_at = datetime('now')
                   WHERE file_path = ? AND gemini_state = 'untracked' AND version = ?""",
                (file_id, current_version)
            )

            if rowcount == 0:
                results.append(("rejected", "OCC conflict"))
                emit_event(file_id, "untracked", "uploading", "start_upload",
                          "rejected", guard_result=False)
            else:
                results.append(("success", None))
                emit_event(file_id, "untracked", "uploading", "start_upload",
                          "success", guard_result=True)

    # Launch 10 concurrent attempts
    await asyncio.gather(*[attempt(i) for i in range(10)])

    successes = [r for r in results if r[0] == "success"]
    rejections = [r for r in results if r[0] == "rejected"]

    assert len(successes) == 1, f"Expected 1 success, got {len(successes)}"
    assert len(rejections) == 9, f"Expected 9 rejections, got {len(rejections)}"
```

### Example 3: Error Injection Test Points

```python
# Source: Locked decision Q4 (error phase determines recovery)

async def test_pre_commit_error(db_path: str, file_id: str):
    """Inject exception BEFORE db.commit() -> state UNCHANGED."""
    # Insert file in 'untracked' state
    # Attempt transition with injected error before commit
    # Assert: DB still shows 'untracked'

async def test_post_commit_error(db_path: str, file_id: str):
    """Inject exception AFTER db.commit() -> state is 'failed'."""
    # Insert file in 'untracked' state
    # Attempt transition; commit succeeds; then raise in after-callback
    # Assert: DB shows 'failed' (or advanced state if error handling writes 'failed')

async def test_guard_error(db_path: str, file_id: str):
    """Inject exception DURING guard evaluation -> state UNCHANGED."""
    # Insert file in 'untracked' state
    # Guard function raises exception
    # Assert: DB still shows 'untracked'
    # Assert: event log shows outcome='failed' for this attempt
```

### Example 4: Thread/Task Leak Check

```python
# Source: Locked decision Q2 (affirmative evidence point 3)
import threading
import asyncio

async def run_with_leak_check(harness_coro):
    """Run test harness with before/after thread and task count comparison."""
    thread_baseline = threading.active_count()
    task_baseline = len(asyncio.all_tasks())

    await harness_coro

    # Allow brief settle time for cleanup
    await asyncio.sleep(0.1)

    thread_after = threading.active_count()
    task_after = len(asyncio.all_tasks())

    # Task count: should be back to 1 (the current task) or equal to baseline
    assert task_after <= task_baseline, (
        f"Task leak: {task_after} tasks after (baseline: {task_baseline})"
    )
    # Thread count: should be equal to or less than baseline
    # (aiosqlite threads should be cleaned up)
    assert thread_after <= thread_baseline + 1, (
        f"Thread leak: {thread_after} threads after (baseline: {thread_baseline})"
    )
```

### Example 5: DB Invariant Checker

```python
# Source: Locked decision Q2 (affirmative evidence point 1)
VALID_STATES = {"untracked", "uploading", "processing", "indexed", "failed"}
VALID_EDGES = {
    ("untracked", "uploading"),
    ("uploading", "processing"),
    ("processing", "indexed"),
    ("uploading", "failed"),
    ("processing", "failed"),
}

async def check_db_invariants(db_path: str) -> list[str]:
    """Return list of invariant violations (empty = pass)."""
    violations = []
    async with aiosqlite.connect(db_path) as db:
        # Check 1: All states are valid enum values
        async with db.execute(
            "SELECT file_path, gemini_state FROM files WHERE gemini_state NOT IN (?, ?, ?, ?, ?)",
            tuple(VALID_STATES)
        ) as cursor:
            async for row in cursor:
                violations.append(f"Invalid state '{row[1]}' for {row[0]}")

        # Check 2: Version is non-negative
        async with db.execute(
            "SELECT file_path, version FROM files WHERE version < 0"
        ) as cursor:
            async for row in cursor:
                violations.append(f"Negative version {row[1]} for {row[0]}")

    return violations
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| pytransitions AsyncMachine | python-statemachine AsyncEngine | python-statemachine 2.3.0 (2024) | AsyncEngine is native, not bolted-on; automatic engine selection eliminates configuration |
| Explicit engine selection | Automatic async detection | python-statemachine 2.3.0 | Library inspects callbacks at class definition time; no developer configuration needed |
| sync-only guards | Async guards via `cond` | python-statemachine 2.3.0+ | Guards can now `await` DB queries without blocking the event loop |
| Manual callback arg threading | Dependency injection | python-statemachine 2.x | Callbacks declare only the parameters they need; library injects automatically |

**Deprecated/outdated:**
- pytransitions `AsyncMachine`: Requires `AsyncState` (not base `State`), has open bugs with async callbacks producing RuntimeWarning. All three AI providers recommend against.
- python-statemachine `MachineMixin`: Older pattern for Django/ORM integration. Still works but not needed for this use case (we manage persistence ourselves).

## Open Questions

1. **`start_value` with string values -- verified?**
   - What we know: The `start_value` parameter matches against `State(value=...)`. Our states use string values like `"uploading"`. The official API docs confirm `start_value` is "an optional start state value." Perplexity claims it works with string values matching the `value` parameter.
   - What's unclear: No official code example shows `start_value` with string values specifically. All examples use integer values. This MUST be tested in the first spike task.
   - Recommendation: Define states with `value="uploading"` etc. and test `start_value="uploading"` immediately. If it only accepts integers, define integer values and maintain a string-to-int mapping.

2. **python-statemachine guard failure semantics**
   - What we know: When a `cond` guard returns `False`, the library raises `TransitionNotAllowed`. Multiple transitions on the same event are tried in declaration order.
   - What's unclear: When a guard RAISES AN EXCEPTION (not returns False), does the library catch it, propagate it, or leave the FSM in a bad state? The error injection test (guard failure) depends on this.
   - Recommendation: Test explicitly in `test_async_guards.py`. If the library swallows guard exceptions, the hand-rolled approach must be used.

3. **python-statemachine state update timing relative to callbacks**
   - What we know: The library documents that during `on_transition` callbacks, the state is being updated. After `on_enter_state`, the new state is active.
   - What's unclear: If `on_enter_state` raises an exception, does the library roll back to the previous state? Or is the state already updated? This determines whether our "pre-commit rollback" strategy works with the library or requires wrapping.
   - Recommendation: Test explicitly. If the library does NOT roll back on callback exception, the adapter must wrap transitions in try/except and manually handle state.

4. **aiosqlite `execute_fetchone` availability**
   - What we know: Standard aiosqlite API uses `await db.execute()` returning a cursor, then `await cursor.fetchone()`.
   - What's unclear: Whether `execute_fetchone` is a convenience method in aiosqlite 0.22.1 or only in newer versions.
   - Recommendation: Use the standard two-step pattern (`execute` + `fetchone`) to avoid version issues.

## Approach Selection Documentation Requirements

The Phase 9 success criterion #3 requires committed documentation. The document must contain:

1. **Candidates tested:** python-statemachine 2.6.0 (primary) and hand-rolled (fallback, if tested)
2. **Test matrix results:** For each candidate, pass/fail on:
   - Async guard with DB query (binary)
   - Trigger argument injection (binary)
   - No internal event loop creation (binary)
   - 10 concurrent transitions (quantitative: success/rejection counts)
   - Same-file rejection (quantitative: exactly 1 success)
   - Error injection recovery (3 scenarios: pre-commit, post-commit, guard)
   - Thread/task leak check (quantitative: counts)
   - DB invariant check (list of violations, empty = pass)
3. **Evidence artifacts:**
   - JSON event log (parsed, validated)
   - DB snapshot (invariant check results)
   - Thread/task count before and after
4. **Rationale for final choice:** Why the selected approach is correct for production integration in Phase 10+
5. **Committed to repo:** As a markdown file in `.planning/phases/09-async-fsm-spike/`

## Sources

### Primary (HIGH confidence)
- Context7 `/fgmacedo/python-statemachine` (135 snippets) -- async callbacks, guards/conditions, dependency injection, state definitions
- python-statemachine readthedocs: states.html, async.html, api.html, guards.html, actions.html -- `start_value`, `activate_initial_state()`, engine selection, condition syntax
- Context7 `/omnilib/aiosqlite` (33 snippets) -- connection patterns, context manager usage

### Secondary (MEDIUM confidence)
- Perplexity Deep Research: python-statemachine async architecture deep dive -- AsyncEngine selection matrix, event loop detection, `run_async_from_sync()` utility, callback execution pipeline, thread safety limitations
- Perplexity Search: aiosqlite BEGIN IMMEDIATE pattern -- confirmed via SQLite docs and Piccolo ORM tutorial, `sqlite3.OperationalError` for SQLITE_BUSY
- Perplexity Search: `start_value` parameter -- confirmed existence, string value support claimed but not independently verified

### Tertiary (LOW confidence)
- Perplexity Search: `start_value` with string values -- single-source claim that string values work. Needs validation in spike.
- aiosqlite `execute_fetchone` convenience method -- unverified; use standard two-step pattern instead.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- python-statemachine 2.6.0 confirmed via Context7 + official docs; aiosqlite 0.22.1 already in project
- Architecture: MEDIUM-HIGH -- patterns verified in docs; interaction between library callback model and per-transition aiosqlite connections needs spike validation
- Pitfalls: HIGH -- documented in official sources; several confirmed by existing codebase patterns
- python-statemachine async guards: MEDIUM -- documented as supported but no verified code example showing `async def guard` with `cond` parameter using a DB query; the spike's first test validates this
- `start_value` with strings: LOW -- claimed by Perplexity, not shown in any official example; must test immediately
- aiosqlite BEGIN IMMEDIATE: MEDIUM-HIGH -- confirmed via SQLite official docs + Piccolo ORM patterns; aiosqlite wraps sqlite3 so same semantics apply

**Research date:** 2026-02-20
**Valid until:** 2026-03-20 (stable libraries, 30-day validity)
