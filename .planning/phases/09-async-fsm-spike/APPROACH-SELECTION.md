# Phase 9: Async FSM Approach Selection

**Selected approach:** python-statemachine 2.6.0 (StateMachineAdapter)
**Decision date:** 2026-02-20
**Gate status:** Phase 9 BLOCKING gate PASSED

---

## Executive Summary

python-statemachine 2.6.0 is selected as the FSM implementation for the Gemini file lifecycle. It passes all test criteria under adversarial concurrent conditions. The HandRolledAdapter remains implemented as a documented fallback but is not needed. pytransitions AsyncMachine was rejected without testing based on documented async issues.

---

## Candidates Evaluated

### A. python-statemachine 2.6.0

- **Package:** `python-statemachine==2.6.0`
- **Adapter:** `StateMachineAdapter` in `spike/phase9_spike/adapters/statemachine_adapter.py`
- **Status:** SELECTED -- passes all criteria

### B. Hand-Rolled Class-Based FSM

- **Adapter:** `HandRolledAdapter` in `spike/phase9_spike/adapters/handrolled_adapter.py`
- **Status:** IMPLEMENTED as documented fallback -- not needed since python-statemachine passes

### C. pytransitions AsyncMachine

- **Package:** `transitions` with `AsyncMachine`
- **Status:** REJECTED without testing -- documented async issues make it unsuitable

---

## Test Matrix

| Criterion | python-statemachine | hand-rolled | pytransitions |
|-----------|:-------------------:|:-----------:|:-------------:|
| Async guard support (binary test) | PASS | PASS (by design) | REJECTED (not tested) |
| Concurrent 10-same-file (1 success, 9 rejections) | PASS | N/A (not primary) | N/A |
| Error injection -- pre-commit leaves state unchanged | PASS | N/A | N/A |
| Error injection -- post-commit advances state | PASS | N/A | N/A |
| DB invariants hold (0 violations) | PASS | N/A | N/A |
| Thread/task leak (0 leaked) | PASS | N/A | N/A |
| No library-native state serialization | PASS (string values) | PASS (by design) | UNKNOWN |
| Arg injection into callbacks | PASS | PASS | BLOCKED (documented issue) |
| FileStateMachineProtocol satisfied | PASS | PASS | N/A |

**Legend:** PASS = tested and verified. N/A = not the primary candidate, not tested under full adversarial conditions. REJECTED = excluded before testing based on documented evidence. UNKNOWN = no data available.

---

## Evidence Artifacts

### Test Files

| Test File | What It Tests | Result |
|-----------|---------------|--------|
| `spike/phase9_spike/tests/test_async_guards.py` | Async guard binary test (3 tests) | ALL PASS |
| `spike/phase9_spike/tests/test_concurrent_transitions.py` | 10-same-file adversarial + 10-different-file concurrent | ALL PASS |
| `spike/phase9_spike/tests/test_error_injection.py` | Pre-commit, post-commit, guard error injection (4 tests) | ALL PASS |
| `spike/phase9_spike/tests/test_db_invariants.py` | DB invariant checker (4 tests) | ALL PASS |
| `spike/phase9_spike/tests/test_leak_check.py` | Thread/task leak detection (3 tests) | ALL PASS |

### Combined Harness Output

Run command: `python -m spike.phase9_spike.harness`

Source: `spike/phase9_spike/harness.py`

```
======================================================================
Phase 9 Spike: Adversarial FSM Test Harness
======================================================================

[SETUP] Protocol check: PASS
[SETUP] Seeded 11 test files (10 unique + 1 contended)

[BASELINE] Threads: 1
[BASELINE] Tasks: 1

[TEST 1] 10 concurrent transitions on different files...
  Successes: 10/10 - PASS

[TEST 2] 10 concurrent transitions on same file...
  Successes: 1 (expected 1)
  Rejections: 9 (expected 9)
  Result: PASS

[TEST 3] JSON event log validation...
  Total events: 20
  Violations: 0
  Result: PASS
  Sample event: {
  "attempt_id": "b3cc70a9-36f8-481c-978f-6b7053adb445",
  "timestamp": "2026-02-20T10:50:11.352091+00:00",
  "file_id": "/test/unique_7.txt",
  "event": "start_upload",
  "from_state": "untracked",
  "to_state": "uploading",
  "guard_result": true,
  "outcome": "success",
  "error": null
}

[TEST 4] DB invariant check...
  Violations: 0
  Result: PASS

[TEST 5] Thread/task leak check...
  Threads: 1 -> 1 (PASS)
  Tasks: 1 -> 1 (PASS)
  Result: PASS

[CLEANUP] DB removed: YES

======================================================================
ALL CHECKS PASSED
======================================================================

Full results (JSON):
{
  "protocol": {
    "passed": true,
    "message": "StateMachineAdapter satisfies FileStateMachineProtocol"
  },
  "different_files": {
    "passed": true,
    "successes": 10,
    "rejections": 0,
    "failures": 0
  },
  "same_file_contention": {
    "passed": true,
    "successes": 1,
    "rejections": 9,
    "failures": 0
  },
  "event_log": {
    "passed": true,
    "total_events": 20,
    "violations": []
  },
  "db_invariants": {
    "passed": true,
    "violations": []
  },
  "leak_check": {
    "passed": true,
    "thread_baseline": 1,
    "thread_after": 1,
    "task_baseline": 1,
    "task_after": 1
  }
}
```

### Affirmative Evidence Summary (4 Criteria)

| Criterion | Result | Evidence |
|-----------|--------|----------|
| DB Invariants | 0 violations | All states in VALID_STATES, versions non-negative, edges valid |
| Structured JSON Event Log | 20 events, all with required fields | attempt_id, file_id, from_state, to_state, guard_result, outcome |
| Thread/Task Leak Check | 0 leaked | Threads: 1->1, Tasks: 1->1 |
| Same-File Adversarial Test | 1 success, 9 rejections | Per-file asyncio.Lock + OCC UPDATE with rowcount check |

---

## Rationale for python-statemachine

### Why it was selected

1. **Native async guard support.** The library genuinely awaits async coroutines in guard conditions (`cond="cond_not_stale"`). The `AsyncEngine` detects the running event loop and uses it correctly -- no thread pool executor workarounds needed. Verified by the binary test in `test_async_guards.py`.

2. **`start_value=` parameter supports ephemeral lifecycle.** The adapter creates a `FileLifecycleSM(start_value=initial_state)` from the DB state, uses it for one transition, then discards it. This matches the locked decision that DB is the sole source of truth -- the FSM is a validator/enforcer, not the state owner.

3. **Structured `on_enter_state` callbacks with argument injection.** The library injects named parameters (`target`, `source`, plus trigger kwargs) into callbacks. This allows the `on_enter_state` callback to receive `file_id`, `db_path`, and `expected_version` for the OCC DB write.

4. **State values are plain strings.** Using `State("untracked", value="untracked")` means `current_state_value` returns a plain string. No library-internal serialization format -- the FSM state is always a string that maps directly to the `gemini_state` DB column.

5. **Library propagates exceptions from callbacks.** When `on_enter_state` raises (e.g., `StaleTransitionError` after OCC conflict), the exception propagates to the caller. The library does not catch or swallow callback exceptions.

### Discovery: on_enter_state kwargs must be optional

During `activate_initial_state()`, the library fires `on_enter_state` with the `__initial__` event. No trigger kwargs (`file_id`, `db_path`, `expected_version`) are available at this point.

**Fix:** All `on_enter_state` parameters are optional with `None` defaults. The callback skips the DB write when `source is None or source.value is None`.

This is a minor usage constraint, not a limitation. Phase 10 must follow the same pattern.

---

## Rationale for NOT Selecting Hand-Rolled

python-statemachine passes all criteria -- there is no reason to take on the maintenance burden of a hand-rolled FSM.

The `HandRolledAdapter` in `spike/phase9_spike/adapters/handrolled_adapter.py` remains implemented as a documented fallback. If future library issues arise (breaking changes, async regressions, abandonment), the hand-rolled approach provides a swap path via the `FileStateMachineProtocol` interface.

Both adapters satisfy `FileStateMachineProtocol` (verified by `isinstance()` check in the harness).

---

## Rationale for Rejecting pytransitions

pytransitions was rejected without empirical testing based on documented evidence:

1. **AsyncMachine requires `AsyncState` (not base `State`).** Async support is bolted on, not native. The `AsyncState` class is a separate hierarchy from `State`, requiring explicit opt-in at every state definition.

2. **Open bugs with async callbacks.** `core.py` produces `RuntimeWarning` when async callbacks are invoked. The library's internal callback dispatch sometimes calls `asyncio.run()` when an event loop is already running, which fails in aiosqlite's environment.

3. **Arg injection into callbacks is BLOCKED.** The library's callback mechanism does not support arbitrary keyword argument injection the way python-statemachine does. This would require workarounds (closures, partial functions) that add complexity.

4. **No provider endorsement.** The Perplexity research specifically called out pytransitions async issues and recommended python-statemachine as the more mature async-capable option.

---

## Phase 10 Integration Implications

### Selected approach carries forward

- `StateMachineAdapter` is the FSM implementation for Phase 10 production integration
- `FileStateMachineProtocol` defines the interface that both adapters satisfy

### Integration bridge pattern

- `FileTransitionManager` (scaffold in `spike/phase9_spike/integration/scaffold.py`) shows how the FSM adapter connects to the existing `AsyncUploadStateManager` pattern
- The scaffold demonstrates the exact bridge: read state from DB, create ephemeral adapter, trigger transition, adapter writes new state back to DB

### Patterns that carry forward to Phase 10

1. **Ephemeral adapter lifecycle:** Create adapter from DB state, use for ONE transition, discard. The DB is always the source of truth.

2. **Per-file asyncio.Lock (FileLockManager):** Serializes transitions on the same file. Prevents two coroutines from simultaneously reading the same state and both attempting the same transition.

3. **OCC UPDATE pattern:** `WHERE file_path=? AND gemini_state=? AND version=?` with `rowcount` check. If `rowcount==0`, another coroutine won the race.

4. **Per-transition aiosqlite connection:** Each `on_enter_state` callback opens a fresh `aiosqlite.connect()`. No connection sharing between transitions or between the FSM and `AsyncUploadStateManager`.

5. **on_enter_state optional kwargs:** All callback parameters must have `None` defaults for `activate_initial_state()` compatibility.

---

*Document produced as part of Phase 9 Plan 2 (09-02-PLAN.md)*
*Evidence captured: 2026-02-20*
