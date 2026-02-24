# CLARIFICATIONS-NEEDED.md

## Phase 10: Transition Atomicity Spike — Stakeholder Decisions Required

**Generated:** 2026-02-20
**Mode:** Multi-provider synthesis (OpenAI gpt-4.1, Gemini Pro, Perplexity Sonar Deep Research)

---

## Decision Summary

**Total questions:** 9
**Tier 1 (Blocking):** 4 questions — Must answer before Plan 10-01
**Tier 2 (Important):** 3 questions — Must answer before Plan 10-02
**Tier 3 (Polish):** 2 questions — Can defer to implementation

---

## Tier 1: Blocking Decisions

### Q1: How should write-ahead intent be represented in the DB?

**Question:** Should crash-recovery intent be stored as (a) extra columns on the `files` table, (b) a separate `transition_intents` table, or (c) a new `RESETTING` FSM state?

**Why it matters:** This determines the DB migration needed in Plan 10-01, the recovery crawler query, and whether the FSM grows a new state.

**Options:**

**A. Extra columns on `files` table (intent_type, intent_started_at, intent_api_calls_completed)**
- Simple recovery query: `WHERE intent_type IS NOT NULL`
- No joins, no new FSM state
- Nullable columns on files table
- _(Proposed by: Perplexity, OpenAI partial)_

**B. Separate `transition_intents` table (append-only log)**
- Cleanest schema separation
- Requires join in recovery
- Natural audit trail
- _(Proposed by: OpenAI)_

**C. New `RESETTING` intermediate FSM state + `recovery_context` JSON column**
- Integrates with FSM naturally
- Recovery crawler scans `WHERE state='RESETTING'`
- Adds transient state to Phase 13 migration
- _(Proposed by: Gemini)_

**Synthesis recommendation:** ✅ **Option A — Extra columns on files table**
- Rationale: No new FSM states (Phase 9 decision: FSM states = untracked/uploading/processing/indexed/failed, exactly). Recovery query is trivial. Three nullable columns added in Plan 10-01 DB migration.

---

### Q2: What is the final FSM state after a successful reset?

**Question:** After `delete_store_document()` + `delete_file()` + DB update complete successfully, what is `gemini_state`? `UNTRACKED`? `UPLOADING`?

**Why it matters:** Determines what state recovery must land the file in after crash recovery. Determines what the upload pipeline expects to find.

**Options:**

**A. UNTRACKED — clean slate, awaiting re-upload**
- Both remote resources deleted, both IDs cleared to NULL
- Upload pipeline picks it up in the next run
- Matches the state name semantics
- _(Proposed by: synthesis from all providers)_

**B. UPLOADING — immediately queued for re-upload**
- Implies upload is actively happening (which it isn't yet)
- Overloads the UPLOADING state semantics
- _(Roadmap text suggests this but may be imprecise)_

**Synthesis recommendation:** ✅ **Option A — UNTRACKED**
- The roadmap's "INDEXED→UPLOADING reset transition" describes the *intent* (reset so file can be re-uploaded) not the literal FSM end state. The FSM path is INDEXED → (reset) → UNTRACKED. A subsequent `start_upload` event transitions UNTRACKED → UPLOADING when the upload pipeline processes the file.

---

### Q3: How should the OCC version interact with intent writes?

**Question:** When recording intent (Txn A) before API calls, should the OCC version be incremented? Or only at finalize (Txn B)?

**Why it matters:** Version increment at Txn A would mean recovery sees a file at version N+1 that's still logically INDEXED. Version increment only at Txn B means the state is internally inconsistent during the transition window.

**Options:**

**A. Version incremented only at Txn B (finalize)**
- Txn A writes intent columns WHERE `gemini_state='indexed' AND version=N`; version stays at N
- Txn B finalizes with `WHERE version=N`; sets `version=N+1`, clears intent, sets `gemini_state='untracked'`
- Intent columns are "pre-version" — not part of the versioned state
- _(Proposed by: OpenAI, Perplexity)_

**B. Version incremented at Txn A to signal "in-progress"**
- Higher version prevents other coroutines from starting conflicting transitions
- But recovery would see version N+1 while state is INDEXED — confusing
- _(Not recommended by any provider)_

**Synthesis recommendation:** ✅ **Option A — Version only at Txn B**
- Intent columns are transient bookkeeping, not versioned state. Recovery uses intent columns directly (not the version). The `FileLockManager` (per-file asyncio.Lock) already serializes concurrent transitions on the same file — version increment at finalize is correct.

---

### Q4: How should safe-delete wrappers handle 404 vs. other errors?

**Question:** When recovery re-calls `delete_store_document()` on an already-deleted resource, the API returns 404. Should that be treated as success? What about 403, 429, or 5xx?

**Why it matters:** A wrong answer here breaks automatic recovery: treating 404 as failure means recovery loops forever; treating 403 as success silently skips auth errors.

**Options:**

**A. 404 = success, all other errors re-raise**
- Simple and safe
- Wrong auth/config errors propagate correctly → file goes to FAILED
- _(Proposed by: all 3 providers)_

**B. 404 + 403 = success (tolerate all "gone" outcomes)**
- Over-permissive: hides real auth errors
- _(Not recommended)_

**Synthesis recommendation:** ✅ **Option A — 404 = success, all other errors re-raise**
- Must empirically confirm the exact exception class from `google-genai` SDK during 10-01. Expected: `google.api_core.exceptions.NotFound` or similar.

---

## Tier 2: Important Decisions

### Q5: When does the recovery crawler run?

**Question:** Should the startup recovery crawler be: (a) startup-only blocking scan, (b) startup + periodic background task, or (c) startup + on-demand via CLI?

**Options:**

**A. Startup blocking + optional periodic background monitor (detect only)**
- Startup: blocks app until all intent_type IS NOT NULL files are recovered
- Background: detects intents older than 30min, logs warning, does NOT auto-recover
- _(Proposed by: Perplexity, Gemini)_

**B. Startup blocking only**
- Simpler; no background complexity
- If app runs for hours and a crash occurs mid-batch, recovery waits until next restart
- _(Acceptable for Phase 10 spike scope)_

**C. Startup + periodic with auto-recovery**
- Most robust but adds concurrency concerns
- _(Proposed by: OpenAI)_

**Synthesis recommendation:** ⚠️ **Option A — Startup blocking + optional background monitor (detect only)**
- Background monitor logs but does not auto-recover, avoiding infinite retry loops. Phase 10-02 implements both components.

---

### Q6: What is the FAILED state escape path?

**Question:** How does a file escape FAILED state without manual SQL? Auto-retry on startup? Explicit CLI command? Scheduled task?

**Options:**

**A. Explicit CLI command only: `objlib recover --failed`**
- Operator-controlled; no surprise retries
- No infinite loop risk
- Still satisfies "no manual SQL" requirement
- _(Synthesis recommendation)_

**B. Auto-retry on startup**
- Convenient but risks retry loops if cause is permanent (auth, quota)
- Would need `failed_reason` enum to distinguish
- _(Partial: OpenAI, Gemini)_

**C. Scheduled auto-retry after timeout**
- Most automated
- Hardest to reason about; risk of hammering APIs
- _(OpenAI partial)_

**Synthesis recommendation:** ⚠️ **Option A — Explicit CLI command**
- Satisfies FSM-02 ("automatic" = no SQL, not "no human trigger"). Prevents retry loops. Add `objlib recover --failed` in Plan 10-02.

---

### Q7: How to simulate crashes in async tests?

**Question:** How to inject crashes at each of the 3 crash points in pytest?

**Options:**

**A. Mock side_effect + asyncio.CancelledError**
- Crash point 1: mock raises exception after first API call
- Crash point 2: mock raises exception after second API call
- Crash point 3: CancelledError after incrementing intent_api_calls_completed=2 but before Txn B finalize
- _(Proposed by: Gemini + Perplexity)_

**B. Subprocess crash (os._exit)**
- Most realistic
- Much harder to integrate with pytest; slow; flaky
- _(Proposed by: OpenAI as optional)_

**Synthesis recommendation:** ⚠️ **Option A — Mock + CancelledError**
- Meets HOSTILE distrust requirement: tests that a NEW RecoveryCrawler instance resolves the partial DB state. No need for actual process kill.

---

## Tier 3: Polish Decisions

### Q8: What observability is needed for recovery?

**Question:** How much CLI/log visibility is needed for recovery operations?

**Synthesis recommendation:** 🔍 Minimal for Phase 10: log each recovered file at INFO level. `objlib status` shows count of files with active intent. Full intent listing can be added in Phase 13 if needed.

---

### Q9: How to objectively measure SC3 (recovery simpler than transition)?

**Question:** What measurement satisfies "recovery code demonstrably simpler than transition code"?

**Synthesis recommendation:** 🔍 Line count + branch count: recovery code for all 3 crash point handlers combined is ≤ total lines of transition code. Each recovery path is a single focused test case. No retry loops in recovery code.

---

## Next Steps

1. ✅ Clarifications answered (YOLO mode — see CLARIFICATIONS-ANSWERED.md)
2. ⏭ Proceed to `/gsd:plan-phase 10`

---

*Multi-provider synthesis: OpenAI gpt-4.1 + Gemini Pro + Perplexity Sonar Deep Research*
*Generated: 2026-02-20 (YOLO mode)*
