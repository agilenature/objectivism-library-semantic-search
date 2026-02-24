# CONTEXT.md — Phase 9: Wave 1 — Async FSM Library Spike

**Generated:** 2026-02-19
**Phase Goal:** A specific FSM approach (library or hand-rolled) is selected with affirmative evidence of correct async behavior under concurrent load
**Synthesis Source:** Multi-provider AI analysis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research)
**Distrust Level:** HOSTILE — "no errors thrown" does NOT pass the gate

---

## Overview

Phase 9 selects the FSM approach that will govern all Gemini file lifecycle transitions for ~1,748 files. The choice must be proven correct under adversarial concurrent conditions — not just shown to work on the happy path. Three major technical questions drive this phase: (1) which FSM approach has genuine async compatibility with the aiosqlite + Typer stack, (2) what "affirmative evidence" concretely means, and (3) how concurrent transitions on the same file are handled safely.

**Confidence markers:**
- ✅ **Consensus** — All 3 providers identified this as critical
- ⚠️ **Recommended** — 2 providers identified this as important
- 🔍 **Needs Clarification** — 1 provider identified, potentially important

---

## Gray Areas Identified

### ✅ 1. Library Selection: python-statemachine vs pytransitions vs hand-rolled (Consensus)

**What needs to be decided:**
Which FSM approach to use for Wave 2+: the `python-statemachine` library, the `pytransitions` library (with AsyncMachine), or a hand-rolled class-based FSM.

**Why it's ambiguous:**
- `pytransitions` AsyncMachine has documented issues: requires `AsyncState` (not base `State`), has open bugs with async callbacks from core.py producing RuntimeWarning, and its async support is bolted onto a sync architecture.
- `python-statemachine` has native async support via automatic engine selection (SyncEngine vs AsyncEngine), supports async guards natively, and was designed to handle the Typer→asyncio.run() boundary correctly.
- Hand-rolled gives complete control but requires building serialization, guard dispatch, and callback routing manually.

**Provider synthesis:**
- **OpenAI:** Lean toward hand-rolled. "Libraries often optimize ergonomics, not hostile concurrency proof; hand-rolled can be simpler to prove and integrate with SQLite OCC." States mandatory criteria and says to prefer hand-rolled if any library fails async guard/callback clarity test.
- **Gemini:** Library-agnostic but conditional: if library fails async guard test or argument injection test, immediately pivot to hand-rolled. Proposes defining a Protocol interface up front so pivot is cheap.
- **Perplexity:** Specifically recommends `python-statemachine`. "Provides optimal balance for this architecture. Native async support with automatic engine selection. Permits async guards, async actions, async on_enter/on_exit callbacks without special workarounds." Explicitly calls out pytransitions AsyncMachine's workarounds as violations of separation of concerns.

**Proposed implementation decision:**
Trial `python-statemachine` first (Plan 09-01). Test it against all mandatory criteria: async guard support, argument injection into callbacks, no internal event loop creation, no library-native state serialization. If it fails any criterion → immediately pivot to hand-rolled (no third-library fallback). Define a `FileStateMachine` Protocol interface before the trial so that a pivot doesn't require rewriting callers.

**Open questions:**
- Does minimizing dependencies take priority over library adoption? (Affects hand-rolled preference.)
- Is it acceptable for the library to internally await guards, or must guards be callable synchronously with their results inspected?

**Confidence:** ✅ All 3 providers agree the selection must be empirically verified, not assumed.

---

### ✅ 2. Definition of "Affirmative Evidence" of Concurrent Correctness (Consensus)

**What needs to be decided:**
What specific signals, artifacts, and assertions constitute "positive evidence" that concurrent transitions behaved correctly — as opposed to merely "no exception was raised."

**Why it's ambiguous:**
HOSTILE distrust explicitly bars accepting absence-of-failure as proof. But without a concrete definition, the spike could subjectively "pass" while missing subtle bugs (swallowed exceptions, tasks never completing, inconsistent DB state).

**Provider synthesis:**
- **OpenAI:** DB invariants (state in allowed enum, no illegal edges, exactly one terminal outcome per file, no orphaned artifacts) + structured event tracing with UUID correlation IDs asserting ordering constraints. Must produce a JUnit/JSON report + SQLite snapshot.
- **Gemini:** Trace-ID Logger Assertions — every transition attempt emits structured JSON lines with `attempt_id`, `file_id`, `from_state`, `to_state`, `guard_result`, `db_txn_id`, timestamps. Success = parsing log and validating state chain for every UUID. Also: `threading.active_count()` and `asyncio.all_tasks()` return to baseline after batch (leak check).
- **Perplexity:** Verifying 3 layers: (1) all transitions reach target states consistently under load, (2) FSM invariants never violated, (3) database state accurately reflects FSM state even under concurrent modification. Recommends property-based testing for invariant verification.

**Proposed implementation decision:**
Affirmative evidence = ALL of the following:
1. **DB invariants** (checked by script after every test run): `gemini_state` always in valid enum; no file has a state not reachable from its prior state; UNIQUE constraints hold (no duplicate transitions).
2. **Structured transition log** (JSON lines emitted during test): each attempt has UUID, file_id, from_state, to_state, guard_result, outcome. Log is parsed and every UUID's state chain is validated.
3. **Thread/task leak check**: `threading.active_count()` and `len(asyncio.all_tasks())` at baseline before and after the 10-concurrent-attempt harness.
4. **Guard rejection proof**: adversarial concurrent-same-file attempts log exactly N rejections and 1 success (or 0 successes if guard correctly blocks all).

**Open questions:**
- Should performance thresholds (e.g., 10 concurrent attempts complete within X seconds) be part of "affirmative evidence" here, or deferred to Phase 14?
- Should the transition log be committed to the repo as a golden trace for regression?

**Confidence:** ✅ All 3 providers agree concrete measurement artifacts are required.

---

### ✅ 3. aiosqlite Connection Management Under Concurrency (Consensus)

**What needs to be decided:**
How FSM transition callbacks access aiosqlite connections: per-transition connection, connection pool, or connection passed as argument — and whether WAL mode is required from the start.

**Why it's ambiguous:**
aiosqlite connections are NOT thread-safe and must not be shared across coroutines. Each connection runs on a dedicated thread. Under concurrent transitions, incorrect sharing causes hard-to-reproduce failures. Pool sizing, WAL mode configuration, and SQLITE_BUSY handling are non-trivial decisions.

**Provider synthesis:**
- **OpenAI:** Per-transition connection via `async with aiosqlite.connect(db_path) as db:`. Never store connection on FSM instance; pass `db_path` or connection factory into callbacks. WAL mode mandatory.
- **Gemini:** Callback argument injection — FSM library must support passing `db_cursor=cursor` through trigger → callbacks/guards. Any library requiring global state or unable to pass call-time arguments is disqualified.
- **Perplexity:** Connection pooling (aiosqlitepool, pool size 5-10 for write-heavy), WAL mode essential, exponential backoff retry for SQLITE_BUSY, BEGIN IMMEDIATE for write transactions to avoid upgrade failures.

**Proposed implementation decision:**
1. Enable WAL mode at DB initialization (apply once, persists).
2. Pass `db_path` (connection factory) into FSM callbacks — never a live connection. Each callback opens its own `async with aiosqlite.connect(db_path)` context.
3. Use `BEGIN IMMEDIATE` for state-update transactions (avoids upgrade-lock failures under concurrent writes).
4. Implement exponential backoff retry (3 attempts, 50ms initial delay) for SQLITE_BUSY within callbacks.
5. Verify the chosen FSM library supports passing arguments through trigger → callback → guard chain (this is a binary disqualification criterion for libraries).

**Open questions:**
- Is per-transition connection overhead acceptable at 1,748-file batch scale, or is a pool needed from Phase 9?
- Should `PRAGMA synchronous=NORMAL` be set (faster writes, acceptable durability) or `FULL` (safer)?

**Confidence:** ✅ All 3 providers flagged connection management as a binary failure point.

---

### ✅ 4. Async Guard Function Support (Consensus)

**What needs to be decided:**
Whether the chosen FSM library natively awaits async guard functions, or whether guards must be synchronous (which would block DB queries inside guards).

**Why it's ambiguous:**
Many "async" FSM libraries make transition *callbacks* async but leave *guards* synchronous. Guards that must query DB state (`is this file already indexed?`) cannot be sync without blocking the event loop or using `run_until_complete` (which fails inside a running loop).

**Provider synthesis:**
- **OpenAI:** Async guards are a hard requirement. Blocking a guard with sync wrappers causes deadlocks inside `asyncio.run()`.
- **Gemini:** Async guard mandate — spike must explicitly test `async def check_if_exists(self): return await self.db.exists(...)`. If library requires sync guards → immediately pivot to hand-rolled.
- **Perplexity:** python-statemachine explicitly supports async guards via `cond` parameter with async coroutines returning bool. The library awaits them during transition evaluation.

**Proposed implementation decision:**
- Write the guard test first (`test_async_guards.py`): define a guard that performs `await db.execute(...)` and returns bool. If the library executes this correctly (awaits it, uses result for transition decision) → PASS. If it calls the coroutine synchronously (not awaited) or raises → FAIL → pivot to hand-rolled.
- This test must run before any other Phase 9 work (it's the fastest disqualification check).

**Open questions:**
- None — this is a binary test with a clear pass/fail criterion.

**Confidence:** ✅ All 3 providers identified this as a blocking technical question.

---

### ✅ 5. Concurrency on Same File: Guard Rejection Semantics (Consensus)

**What needs to be decided:**
When multiple coroutines attempt to transition the **same file** simultaneously, what is the exact mechanism for ensuring exactly one succeeds and others are correctly rejected — and whether this uses in-process locks, DB constraints, or optimistic concurrency control.

**Why it's ambiguous:**
FSM library guards protect in-memory state, but under concurrent access the "check state → attempt transition" gap is a race condition. An in-memory lock protects the FSM instance but not cross-process access. DB constraints (version column, OCC) protect at the persistence layer.

**Provider synthesis:**
- **OpenAI:** DB-backed optimistic concurrency: add `version INTEGER` column. Transition executes `UPDATE files SET state=?, version=version+1 WHERE file_id=? AND state=? AND version=?`. rowcount==0 → rejected as `ConcurrentTransitionRejected`. Works cross-process.
- **Gemini:** Application-level `asyncio.Semaphore(1)` for the state-writing portion. Plus: hostile test must log how many attempts were made and if any `database locked` errors leaked through.
- **Perplexity:** Per-file `asyncio.Lock` in a `FileProcessingManager`. `async with lock: await fsm.upload()`. Serializes access to same FSM instance. Combined with UNIQUE DB constraints for deeper protection.

**Proposed implementation decision:**
Use BOTH layers:
1. **In-process**: `asyncio.Lock` per file_id (keyed dict in the upload manager). Serializes concurrent transitions on the same file within a single process.
2. **DB layer**: Optimistic concurrency with `version INTEGER` column. `UPDATE ... WHERE state=? AND version=?`. rowcount==0 → raises `StaleTransitionError`. This handles cross-process safety if multi-process ever occurs.
- The adversarial test must demonstrate both: (a) 10 concurrent same-file attempts with 1 success and 9 lock-blocked, (b) the DB version column prevents any double-advance.

**Open questions:**
- Is "reject immediately" the correct behavior for concurrent same-file attempts, or should we queue/retry?
- Do we expect multi-process invocations of `objlib upload` before Phase 16?

**Confidence:** ✅ All 3 providers flagged this as requiring both in-process and DB-layer protection.

---

### ✅ 6. DB as Sole Source of Truth: In-Memory State vs DB State (Consensus)

**What needs to be decided:**
Whether the FSM in-memory state object is authoritative (with DB as cache), or the DB is authoritative (with in-memory state derived from it).

**Why it's ambiguous:**
Standard FSM libraries modify a Python object's `state` attribute first, then callbacks persist to DB. If the DB write fails, the in-memory object says "indexed" but the DB says "processing" — inconsistent. The prior orphan accumulation problem was exactly this category of inconsistency.

**Provider synthesis:**
- **OpenAI:** "FSM must treat the DB as the only source of truth." Transition callbacks must execute within a context manager that rolls back in-memory state if DB write fails. Test must assert: after simulated DB write failure, in-memory `state` matches DB `state` (both previous state).
- **Gemini:** "Transactional State Advancement." In-memory state updated ONLY after successful DB commit. Full transaction rollback on DB failure. Test harness requirement: after DB write failure, in-memory object state = DB state.
- **Perplexity:** `sm.current_state.value` used to write string to DB. Load FSM with `start_value=` from DB for resumption. Note: if initial state has async on_enter callbacks, must `await fsm.activate_initial_state()` explicitly.

**Proposed implementation decision:**
DB is authoritative. Implementation pattern:
1. Before transition: read current state from DB.
2. Attempt transition: execute `UPDATE ... WHERE state=old_state` inside explicit transaction.
3. On success: update in-memory state to match DB.
4. On failure: leave in-memory state unchanged (or set to `failed` if non-recoverable).
- FSM library's in-memory `state` attribute is a cache of DB state, not a source of truth.
- Every `FileStateMachine` instance is initialized by reading `gemini_state` from DB, not from memory.

**Open questions:**
- Should FSM instances be ephemeral (created per-transition, discarded after) or long-lived (created once per file)?

**Confidence:** ✅ All 3 providers treat this as fundamental to preventing the orphan problem.

---

### ✅ 7. Error Recovery Semantics: Known State After Transition Failure (Consensus)

**What needs to be decided:**
When an exception occurs mid-transition (during DB write, during API call, during callback), what state should be persisted and whether rollback to previous state or advance to `failed` is correct.

**Why it's ambiguous:**
The Phase 9 success criteria requires "recovery to known state" after error injection. But "known state" isn't defined: is it the prior state (rollback), `failed` (advance), or a new `needs_cleanup` intermediate?

**Provider synthesis:**
- **OpenAI:** If error during transactional portion → transaction rollback → state remains unchanged. Write failure record separately (`last_error`, `error_at`). For non-transactional side effects: move to `failed` with `failure_stage` and `needs_cleanup=1`. `failed` is terminal but supports explicit `retry` transition back to `uploading`.
- **Gemini:** Same pattern — transaction rollback, then separate failure record. Test must assert: after simulated failure, state in DB matches expected prior state.
- **Perplexity:** fault injection scenario — FSM recovers by retrying (if transient) or moving to `failed` (if permanent). States are `untracked`, `uploading`, `processing`, `indexed`, `failed`. `failed` has tested automatic recovery via `FAILED → UNTRACKED` transition (to be designed in Phase 10).

**Proposed implementation decision:**
- If error occurs DURING DB transaction: rollback → state stays as prior state (no advance).
- If error occurs AFTER DB commit but during non-DB side effect: state is now advanced (committed), record error in a `last_error` column, state becomes `failed`.
- `failed` is a terminal state in Phase 9. The recovery path (`failed → untracked`) is Phase 10's job.
- Test harness must explicitly inject failures at: (a) before DB write, (b) after DB commit during callback, (c) during guard evaluation — and assert the correct state in each case.

**Open questions:**
- Should recovery from `failed` be explicit operator action only, or automatic on next upload attempt?

**Confidence:** ✅ All 3 providers specify the recovery pattern; Phase 10 owns the recovery crawler.

---

### ⚠️ 8. Typer + asyncio.run() Boundary: Reentrancy and Nesting (2 Providers)

**What needs to be decided:**
Whether any FSM library creates its own internal event loop (which would conflict with `asyncio.run()` from Typer), and how to guard against nested loop bugs.

**Why it's ambiguous:**
Typer commands are sync; each calls `asyncio.run()` once per command invocation. If the FSM library internally calls `asyncio.run()` or `get_event_loop().run_until_complete()`, this creates a nested loop → RuntimeError. The spike must verify this is not the case.

**Provider synthesis:**
- **OpenAI:** "The FSM library must expose only async APIs and never call `asyncio.run()` internally." Add guard in CLI: if running loop detected, fail with clear message.
- **Perplexity:** `asyncio.run()` always creates a new event loop; all async code within that single call shares one loop. The danger is nested calls. python-statemachine's AsyncEngine detects running event loop and reuses it (does not create new one).

**Proposed implementation decision:**
- Test: within `asyncio.run(main())`, trigger a transition. Verify no `RuntimeError: This event loop is already running` is raised. This is part of the test harness.
- Add a startup assertion in CLI: `assert asyncio.get_event_loop().is_running() == False` before `asyncio.run()` (guards against future integration).
- The FSM library must never call `asyncio.run()` internally — document as selection criterion.

**Confidence:** ⚠️ 2 providers flagged (OpenAI + Perplexity). Critical for Typer integration.

---

### ⚠️ 9. State Persistence Model: gemini_state String + Transition Log (2 Providers)

**What needs to be decided:**
Whether to track only `gemini_state` (current state only) or also persist an append-only transition log table — and whether the transition log is required for Phase 9 "affirmative evidence" or can be deferred.

**Why it's ambiguous:**
The requirement specifies `gemini_state` as plain string enum (already implemented in Phase 8). But "affirmative evidence" requires per-attempt tracing. Whether to build the log table now (enables evidence) or fake it with stdout logging is unclear.

**Provider synthesis:**
- **OpenAI:** Add `file_state_transitions(id, file_id, attempt_id, from_state, to_state, status, reason, created_at)` — append-only log. Enables postmortems, prevents repeats of orphan incidents.
- **Gemini:** Structured JSON log per attempt (stdout, not necessarily SQLite). Parsed by test harness to validate state chains.

**Proposed implementation decision:**
Use JSON stdout logging for Phase 9 spike (faster to implement, sufficient for evidence). The transition log table is a Phase 12 concern (when FSM is integrated into production pipeline). Phase 9 spike writes structured JSON lines to stdout during test harness runs.

**Confidence:** ⚠️ 2 providers recommend; deferred DB table is acceptable for spike phase.

---

### 🔍 10. Library Selection Protocol Interface (1 Provider)

**What needs to be decided:**
Whether to define a `FileStateMachine` Protocol/ABC before library trials so a library pivot doesn't require rewriting callers.

**Why it's ambiguous:**
If the library trial fails midway through implementation, callers already written against the library's specific API will need rewriting. A Protocol defined up front absorbs this cost.

**Provider synthesis:**
- **Gemini:** "Define Hand-Rolled Interface: define the Protocol for the FSM so if the library fails, we can swap in a custom class without rewriting the calling code."

**Proposed implementation decision:**
Yes — define a `FileStateMachineProtocol` at the start of Plan 09-01 with the minimal interface: `current_state: str`, `async transition(trigger: str, **kwargs)`, `async can_transition(trigger: str) -> bool`. All test harness code is written against this Protocol.

**Confidence:** 🔍 1 provider (Gemini). Strongly recommended as low-cost risk mitigation.

---

## Summary: Decision Checklist

Before planning, confirm:

**Tier 1 (Blocking — must decide before implementation):**
- [ ] Which library to trial first (python-statemachine vs hand-rolled directly)
- [ ] Concrete "affirmative evidence" definition (DB invariants + JSON log + thread/task baseline)
- [ ] aiosqlite connection pattern (per-transition with db_path factory)
- [ ] DB as sole source of truth (in-memory is a cache)
- [ ] Error recovery semantics (rollback vs failed state)

**Tier 2 (Important — should decide before Plan 09-01 runs):**
- [ ] WAL mode + BEGIN IMMEDIATE from the start
- [ ] Per-file asyncio.Lock + version column for concurrency
- [ ] Typer boundary guard (no nested asyncio.run())
- [ ] Protocol interface defined before library trial

**Tier 3 (Polish — can decide during implementation):**
- [ ] SQLITE_BUSY retry backoff parameters
- [ ] Performance threshold (in scope for Phase 14, not Phase 9)
- [ ] Transition log table (deferred to Phase 12)

---

*Multi-provider synthesis by: OpenAI gpt-5.2-2025-12-11, Gemini Pro, Perplexity Sonar Deep Research*
*Generated: 2026-02-19*
