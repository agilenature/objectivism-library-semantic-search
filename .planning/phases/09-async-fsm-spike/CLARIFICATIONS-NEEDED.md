# CLARIFICATIONS-NEEDED.md

## Phase 9: Wave 1 — Async FSM Library Spike — Stakeholder Decisions Required

**Generated:** 2026-02-19
**Mode:** Multi-provider synthesis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research)
**Source:** 3 AI providers analyzed Phase 9 requirements

---

## Decision Summary

**Total questions:** 8
**Tier 1 (Blocking):** 4 questions — Must answer before planning
**Tier 2 (Important):** 3 questions — Should answer for quality
**Tier 3 (Polish):** 1 question — Can defer to implementation

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: Library Trial Strategy — Which Candidate First?

**Question:** Should the spike trial `python-statemachine` first and pivot to hand-rolled on failure, or should we build hand-rolled from the start and avoid library risk entirely?

**Why it matters:** If we start with a library that turns out to have incompatible async semantics (pytransitions has documented issues), we waste implementation time. Choosing the trial order determines Phase 9 scope.

**Options identified by providers:**

**A. Trial python-statemachine first, hand-rolled as fallback**
- Perplexity recommends python-statemachine specifically for this architecture (native async guards, automatic engine selection, no internal event loop creation)
- Define a Protocol interface first — pivot is cheap if trial fails
- Faster if library works; wasted day if it doesn't
- _(Proposed by: Perplexity)_

**B. Build hand-rolled from the start**
- OpenAI: "Libraries often optimize ergonomics, not hostile concurrency proof; hand-rolled can be simpler to prove and integrate with SQLite OCC"
- Complete control over transaction boundaries and async semantics
- More code to write but zero library compatibility uncertainty
- _(Proposed by: OpenAI)_

**C. Trial pytransitions AsyncMachine**
- Established library with broad usage
- Documented issues: requires AsyncState (not base State), open bugs with async callbacks
- Perplexity explicitly recommends against this path
- _(Proposed by: nobody — included for completeness)_

**Synthesis recommendation:** ⚠️ **Option A — Trial python-statemachine with Protocol interface as safety net**
- Perplexity (most detailed analysis) specifically evaluated python-statemachine against this exact architecture and found it compatible
- The Protocol interface makes the pivot to hand-rolled cheap (one day of work, not a rewrite)
- Avoid pytransitions entirely (documented async issues, not recommended by any provider)

**Sub-questions:**
- If python-statemachine fails the async guard test, should we pivot immediately to hand-rolled (fastest) or evaluate one more library?
- Is external library dependency acceptable, or is no-new-dependency a constraint?

---

### Q2: "Affirmative Evidence" — What Exactly Must Be Proven?

**Question:** What specific artifacts must the test harness produce to constitute passing the HOSTILE distrust gate for concurrent FSM correctness?

**Why it matters:** Without a concrete definition, the spike's pass/fail is subjective. HOSTILE distrust requires affirmative proof — but proof of what, exactly?

**Options identified by providers:**

**A. DB invariant assertions only**
- Query SQLite after test run; verify all states are in valid enum, no illegal edges, UNIQUE constraints hold
- Machine-checkable but misses in-flight bugs (swallowed exceptions, tasks that never complete)
- _(Proposed by: OpenAI partial)_

**B. Structured JSON event log + DB invariants**
- Every transition attempt emits JSON line: `{"attempt_id": "...", "file_id": "...", "from": "...", "to": "...", "guard_result": true/false, "outcome": "success|rejected|failed"}`
- Test harness parses log and validates every attempt's state chain is legal
- Plus DB invariants after completion
- Thread/task leak check: baseline before and after
- _(Proposed by: OpenAI + Gemini — strong consensus)_

**C. Option B + property-based testing**
- Add property: "no file ever transitions backward through states"
- Add property: "exactly one terminal outcome per file per test run"
- _(Proposed by: Perplexity)_

**Synthesis recommendation:** ✅ **Option B — Structured JSON log + DB invariants + thread/task leak check**
- All 3 providers agree concrete measurement artifacts are required
- Perplexity's property-based testing adds value but can be added iteratively (not blocking)
- Thread/task leak check is critical for detecting async resource leaks that don't raise exceptions

**Sub-questions:**
- Should the JSON log go to stdout (simpler) or a file (committable as golden trace)?
- Is a performance threshold (complete within X seconds) in scope for Phase 9, or deferred to Phase 14?

---

### Q3: Concurrency on Same File — Reject or Queue?

**Question:** When 10 concurrent coroutines all attempt to transition the same file, should concurrent attempts (after the first succeeds) be **rejected immediately** (return error) or **queued with automatic retry**?

**Why it matters:** This determines the concurrency model for the entire upload pipeline. "Reject" is simpler and safer; "queue" is more user-friendly but adds complexity that might introduce new failure modes.

**Options identified by providers:**

**A. Reject immediately (StaleTransitionError)**
- asyncio.Lock per file — second attempt waits for lock, checks guard, finds state changed → rejected
- DB-level: `UPDATE ... WHERE state=? AND version=?` → rowcount=0 → rejected
- Caller handles rejection: skip (file already transitioned), log, or surface as error
- _(Proposed by: OpenAI + Gemini)_

**B. Queue with automatic retry**
- Concurrent attempt waits for lock, retries guard check with backoff
- Eventually succeeds or times out
- More complex but "invisible" to higher layers
- _(Proposed by: nobody explicitly — included as alternative)_

**Synthesis recommendation:** ✅ **Option A — Reject immediately**
- All 3 providers recommend rejection or lock-based serialization, not queueing
- The upload pipeline controls concurrency at a higher level (semaphore over the batch) — same-file concurrency should be rare, not a common case to optimize
- Rejection is observable and testable; queueing with retry is harder to prove correct under HOSTILE distrust

**Sub-questions:**
- Should rejection be a Python exception (caught by caller) or a return value (boolean)?
- Should rejected attempts be logged as warnings or silently skipped?

---

### Q4: Error Recovery — What State After Mid-Transition Failure?

**Question:** When an exception occurs mid-transition, what state should the file be in afterward — unchanged (rollback to prior state), or advanced to `failed`?

**Why it matters:** This determines the recovery story for Phase 10. Getting the semantics wrong now means Phase 10 has to compensate for undefined behavior.

**Options identified by providers:**

**A. Rollback to prior state (error during DB transaction)**
- DB transaction wraps the state update — exception causes rollback
- File remains in previous state; caller retries when ready
- Simplest recovery: just try again
- _(Proposed by: OpenAI + Gemini — consensus)_

**B. Advance to `failed` (error after DB commit)**
- If DB commit succeeded but subsequent non-DB side effect failed
- File is in `failed` state with `last_error` field populated
- Phase 10 provides the `failed → untracked` recovery path
- _(Proposed by: OpenAI + Gemini — consensus for post-commit errors)_

**C. Separate by error phase**
- Pre-commit error → rollback to prior state (Option A)
- Post-commit error → advance to `failed` (Option B)
- This is the synthesis of A+B: the DB transaction boundary determines which rule applies
- _(Proposed by: all 3 providers convergently)_

**Synthesis recommendation:** ✅ **Option C — Error phase determines recovery**
- Pre-commit: rollback → prior state unchanged
- Post-commit: `→ failed` with `last_error` field
- Phase 9 spike must test both cases (inject failure before commit, inject failure after commit)

---

## Tier 2: Important Decisions (⚠️ Recommended)

### Q5: WAL Mode + Transaction Isolation — From Phase 9 or Phase 12?

**Question:** Should WAL mode and `BEGIN IMMEDIATE` be configured in the Phase 9 spike, or deferred to Phase 12 when FSM integrates into the production pipeline?

**Why it matters:** WAL mode is global to the DB file. Configuring it in the spike might conflict with existing production use.

**Options:**

**A. Configure in Phase 9 spike (isolated test DB)**
- Spike uses a temporary/test DB — no conflict with production
- Validates that WAL mode + async concurrent writes work in this stack
- _(Synthesis recommendation)_

**B. Defer to Phase 12**
- Spike uses default journal mode
- Might miss concurrency issues that only appear in WAL mode

**Synthesis recommendation:** ⚠️ **Option A — Configure in spike test DB**
- The spike uses its own isolated SQLite file, not `data/library.db`
- WAL mode is essential for the concurrent write test to not immediately hit lock errors
- Deferred configuration means Phase 9 results are less representative of production

---

### Q6: FileStateMachine Protocol — Define Up Front?

**Question:** Should a `FileStateMachineProtocol` (Python Protocol/ABC) be defined before the library trial, so callers are written against the interface and a library pivot doesn't require rewriting them?

**Why it matters:** If python-statemachine fails the async guard test halfway through Plan 09-01, a Protocol means the pivot to hand-rolled doesn't cascade into rewriting test harness code.

**Options:**

**A. Define Protocol first (interface-first development)**
- Protocol: `current_state: str`, `async trigger(event: str, **kwargs)`, `async can_trigger(event: str) -> bool`
- All test harness code written against Protocol
- Library or hand-rolled class satisfies Protocol
- Cost: ~30 min of design up front
- _(Proposed by: Gemini)_

**B. Write against library API directly**
- Faster initial implementation
- Pivot is more expensive if trial fails

**Synthesis recommendation:** ⚠️ **Option A — Define Protocol first**
- Gemini's recommendation is low-cost and eliminates a class of rework risk
- The Protocol definition is also useful documentation for Phase 12 integration

---

### Q7: FSM Instance Lifecycle — Ephemeral or Long-Lived?

**Question:** Should `FileStateMachine` instances be created fresh for each transition (ephemeral) or maintained as long-lived objects (one per file, shared across multiple transitions)?

**Why it matters:** Ephemeral instances are simpler (no shared state) but have initialization overhead. Long-lived instances enable richer state (in-memory cache) but require careful management under concurrent access.

**Options:**

**A. Ephemeral — create per transition, discard after**
- No shared in-memory state between transitions
- Always reads from DB to initialize — DB is authoritative by design
- Simplest under HOSTILE distrust (no in-memory state drift possible)
- _(Synthesis recommendation for Phase 9 spike)_

**B. Long-lived — one per file, persisted in manager**
- Enables event history, caching, richer state
- Requires careful Lock management (per-file lock in manager dict)
- Perplexity's `FileProcessingManager` pattern
- _(Better for Phase 12 production integration)_

**Synthesis recommendation:** ⚠️ **Option A — Ephemeral for Phase 9 spike, long-lived for Phase 12**
- Phase 9 spike is about proving FSM correctness, not building production architecture
- Ephemeral is easier to prove correct under HOSTILE distrust
- Phase 12 can adopt long-lived instances with per-file locks if throughput requires

---

## Tier 3: Polish Decisions (🔍 Can Defer)

### Q8: SQLITE_BUSY Retry Parameters

**Question:** What backoff parameters should SQLITE_BUSY retry logic use (attempts, initial delay, multiplier)?

**Why it matters:** Too aggressive → high contention; too conservative → slow tests.

**Synthesis recommendation:** 🔍 **Default: 3 attempts, 50ms initial, 2x multiplier**
- Can tune empirically during Phase 9 spike based on observed contention
- Phase 14 (Wave 6: Batch Performance) will benchmark and tune properly

---

## Next Steps (Non-YOLO Mode)

**Since YOLO mode is active, CLARIFICATIONS-ANSWERED.md will be auto-generated.**

---

*Multi-provider synthesis: OpenAI gpt-5.2-2025-12-11 + Gemini Pro + Perplexity Sonar Deep Research*
*Generated: 2026-02-19*
*YOLO mode: Auto-answers will be generated*
