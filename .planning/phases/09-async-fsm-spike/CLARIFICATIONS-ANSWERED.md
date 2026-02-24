# CLARIFICATIONS-ANSWERED.md

## Phase 9: Wave 1 — Async FSM Library Spike — Stakeholder Decisions

**Generated:** 2026-02-19
**Mode:** YOLO (balanced strategy — synthesis recommendations adopted)
**Source:** Auto-generated from CLARIFICATIONS-NEEDED.md + 09-CONTEXT.md

---

## Decision Summary

**Total questions:** 8
**Tier 1 (Blocking):** 4 answered
**Tier 2 (Important):** 3 answered
**Tier 3 (Polish):** 1 answered

---

## Tier 1: Blocking Decisions

### Q1: Library Trial Strategy — Which Candidate First?

**YOLO DECISION:** **Option A — Trial python-statemachine first, hand-rolled as fallback**

**Rationale:**
- Confidence level: ⚠️ Recommended (strong Perplexity endorsement, conditional Gemini, OpenAI hand-rolled preference)
- Perplexity performed the most detailed library analysis specific to this architecture (aiosqlite + Typer + asyncio.run()) and found python-statemachine compatible
- python-statemachine has native async support (AsyncEngine), async guards, automatic engine selection — it was designed for this pattern
- Avoiding pytransitions entirely (documented async issues, no provider endorsement)
- The Protocol interface (Q6) makes the pivot to hand-rolled a ~2 hour task, not a rewrite — this removes the risk from starting with a library

**Sub-decisions:**
- If python-statemachine fails the async guard test (test_async_guards.py): **pivot immediately to hand-rolled** — no other library evaluation
- External library dependency: **acceptable** — python-statemachine is a stable, maintained library with no security concerns for this offline CLI tool

---

### Q2: "Affirmative Evidence" — What Exactly Must Be Proven?

**YOLO DECISION:** **Option B — Structured JSON log + DB invariants + thread/task leak check**

**Rationale:**
- Confidence level: ✅ Consensus (OpenAI + Gemini both proposed this; Perplexity added property testing)
- Property-based testing (Option C enhancement) is deferred — adds value but not required for Phase 9 gate
- Performance thresholds: **out of scope** for Phase 9 — deferred to Phase 14 (Wave 6 Batch Performance)

**Concrete definition of "affirmative evidence" (YOLO-decided, binding for this phase):**

The test harness PASSES the Phase 9 gate when ALL of the following are true after each run:

1. **DB Invariants** (verified by post-run assertion script):
   - All `gemini_state` values are in `{'untracked', 'uploading', 'processing', 'indexed', 'failed'}`
   - No illegal state edges (no file jumped from `untracked` directly to `indexed`)
   - UNIQUE constraints held (no duplicate concurrent advances for same file)

2. **Structured JSON event log** (emitted to stdout during harness run, parseable):
   - Every transition attempt has: `attempt_id`, `file_id`, `from_state`, `to_state`, `guard_result`, `outcome` (`success|rejected|failed`)
   - Log parser validates every attempt's state chain is a valid FSM edge
   - Guard rejections logged with `outcome: "rejected"` and reason

3. **Thread/task leak check**:
   - `threading.active_count()` at baseline (before harness) == count after harness completes
   - `len(asyncio.all_tasks())` returns 0 (or only current task) after `asyncio.run()` completes

4. **Adversarial concurrent same-file test**:
   - 10 concurrent attempts to transition the same file
   - Exactly 1 succeeds (logged as `outcome: "success"`)
   - Remaining 9 are rejected (logged as `outcome: "rejected"`) — NOT errors or panics

**JSON log location:** stdout (not a file) — test harness captures and parses it in-process.

---

### Q3: Concurrency on Same File — Reject or Queue?

**YOLO DECISION:** **Option A — Reject immediately (StaleTransitionError)**

**Rationale:**
- Confidence level: ✅ Consensus (all 3 providers)
- Rejection via asyncio.Lock per file (in-process) + `UPDATE ... WHERE state=? AND version=?` (DB-level)
- The upload pipeline controls concurrency at a higher level — same-file contention is not a common case to optimize

**Sub-decisions:**
- Rejection mechanism: **Python exception** (`StaleTransitionError`) raised from within the FSM, caught by caller
- Logging: **logged as debug-level warning** (not error — rejection under concurrent load is expected behavior)
- Retry: **caller's responsibility** — FSM does not auto-retry

---

### Q4: Error Recovery — What State After Mid-Transition Failure?

**YOLO DECISION:** **Option C — Error phase determines recovery**

**Rationale:**
- Confidence level: ✅ Consensus (all 3 providers converge on this split)

**Binding rules:**
- **Pre-commit error** (exception before `await db.commit()`): DB transaction rollback → file state UNCHANGED → file remains in prior state → caller may retry
- **Post-commit error** (exception in callback after `db.commit()` succeeded): file state IS advanced to new state (DB committed) → any non-DB side effects that failed: set `gemini_state = 'failed'`, write `last_error` to a `failure_info TEXT` column (to be added alongside Phase 9 schema work)
- Phase 10 designs the `failed → untracked` recovery path — Phase 9 only needs `failed` to be reachable

**Test harness adversarial injection points:**
1. Inject exception BEFORE `await db.commit()` → assert state UNCHANGED in DB
2. Inject exception AFTER `await db.commit()` → assert state is `failed` in DB
3. Inject exception DURING guard evaluation → assert state UNCHANGED in DB, guard logged as `outcome: "failed"`

---

## Tier 2: Important Decisions

### Q5: WAL Mode + Transaction Isolation — From Phase 9 or Phase 12?

**YOLO DECISION:** **Option A — Configure in Phase 9 spike test DB**

**Rationale:**
- Confidence level: ⚠️ Recommended
- Spike uses its own isolated SQLite file (not `data/library.db`) — zero conflict with production
- WAL mode is essential for the 10-concurrent-write test to avoid immediate lock errors
- Skip WAL mode in Phase 9 → Phase 9 results are not representative of production behavior

**Spike DB configuration:**
- `PRAGMA journal_mode=WAL` (applied on connection open)
- `PRAGMA synchronous=NORMAL` (balanced performance/safety)
- `PRAGMA foreign_keys=ON`
- Spike creates a temporary SQLite file (e.g., `/tmp/phase9_spike.db`), deleted on teardown

---

### Q6: FileStateMachine Protocol — Define Up Front?

**YOLO DECISION:** **Option A — Define Protocol first (interface-first development)**

**Rationale:**
- Confidence level: ⚠️ Recommended (Gemini proposal; low-cost, high risk-reduction)
- ~30 min of design that eliminates rework if library pivot is needed

**Protocol to define at the start of Plan 09-01:**
```python
from typing import Protocol

class FileStateMachineProtocol(Protocol):
    current_state: str

    async def trigger(self, event: str, **kwargs) -> None:
        """Trigger a state transition. Raises StaleTransitionError if guard rejects."""
        ...

    async def can_trigger(self, event: str, **kwargs) -> bool:
        """Check if the event can be triggered without side effects."""
        ...
```

All test harness code written against `FileStateMachineProtocol`. Both the library adapter and the hand-rolled implementation satisfy this Protocol.

---

### Q7: FSM Instance Lifecycle — Ephemeral or Long-Lived?

**YOLO DECISION:** **Option A — Ephemeral for Phase 9 spike**

**Rationale:**
- Confidence level: ⚠️ Recommended for spike (long-lived deferred to Phase 12)
- Ephemeral: created per transition attempt, initialized from DB, discarded after
- DB is authoritative by design (no in-memory state drift possible)
- Phase 12 will evaluate long-lived instances with per-file locks for throughput

---

## Tier 3: Polish Decisions

### Q8: SQLITE_BUSY Retry Parameters

**YOLO DECISION:** **3 attempts, 50ms initial delay, 2x exponential multiplier**

**Rationale:**
- Confidence level: 🔍 Needs clarification (1 provider; tuned empirically)
- These are defaults — tune during Phase 9 spike if concurrent write tests show excessive failures
- Phase 14 (Wave 6 Batch Performance) will optimize

---

## Architectural Decisions Summary (Binding for Phase 9)

These decisions are locked for all Phase 9 plans:

| Decision | Choice | Confidence |
|----------|--------|-----------|
| Library | python-statemachine (pivot to hand-rolled if async guard fails) | ⚠️ |
| Fallback library | None — pivot directly to hand-rolled | ✅ |
| Affirmative evidence | JSON log + DB invariants + thread/task leak check | ✅ |
| Same-file concurrency | asyncio.Lock + DB version column (OCC), reject on conflict | ✅ |
| Error recovery | Rollback if pre-commit; `failed` if post-commit | ✅ |
| DB authority | DB is sole source of truth; in-memory is cache | ✅ |
| FSM lifecycle | Ephemeral per transition in spike | ⚠️ |
| WAL mode | Enabled in spike test DB from the start | ⚠️ |
| Protocol interface | Defined before library trial | ⚠️ |
| aiosqlite pattern | Per-transition connection via factory (no sharing) | ✅ |
| SQLITE_BUSY retry | 3 attempts, 50ms initial, 2x multiplier | 🔍 |

---

## Next Steps

1. ✅ Clarifications answered (YOLO mode)
2. ⏭ Proceed to `/gsd:plan-phase 9` to create execution plan
3. 📋 Review YOLO decisions before implementation — override any that conflict with personal preference

---

*Auto-generated by discuss-phase-ai --yolo (balanced strategy)*
*Human review recommended before final implementation*
*Generated: 2026-02-19*
