# CONTEXT.md — Phase 10: Transition Atomicity Spike

**Generated:** 2026-02-20
**Phase Goal:** Every identified crash point in multi-API-call FSM transitions has a tested automatic recovery path -- no stuck state requires manual SQL to escape
**Synthesis Source:** Multi-provider AI analysis (OpenAI gpt-4.1, Gemini Pro, Perplexity Sonar Deep Research)

---

## Overview

Phase 10 establishes write-ahead intent semantics for the two-API-call reset transition (`delete_store_document` → `delete_file` → DB update) and proves every crash point has a tested automatic recovery path. The startup recovery crawler handles all partial states.

HOSTILE distrust applies: recovery paths must be *demonstrated* to work through crash simulation tests, not just designed.

**Confidence markers:**
- ✅ **Consensus** — All 3 providers identified this as critical
- ⚠️ **Recommended** — 2 providers identified this as important
- 🔍 **Needs Clarification** — 1 provider identified, potentially important

---

## Gray Areas Identified

### ✅ GA-1: Write-Ahead Intent Representation (Consensus)

**What needs to be decided:**
How to record "intent to perform a multi-step operation" in the DB so recovery can detect partial states. Three options: (a) new intermediate FSM state (e.g., `RESETTING`), (b) extra columns on the `files` table, (c) separate `transition_intents` table.

**Why it's ambiguous:**
- A new FSM state (`RESETTING`) keeps everything in the existing schema but clutters the FSM with transient states — and requires Phase 13's status-column migration to also handle `RESETTING`
- Extra columns on `files` avoid FSM proliferation but add nullable columns with complex invariants
- A separate `transition_intents` table is cleanest (append-only audit log) but adds join complexity to recovery code

**Provider synthesis:**
- **OpenAI:** Separate `transition_intents` table (append-only with `active` flag, `(file_id, active)` unique constraint, explicit step enum: CREATED/STORE_DOC_DELETED/FILE_DELETED/DB_COMMITTED/ABORTED)
- **Gemini:** New `RESETTING` FSM state + `recovery_context` JSON column on `files` table (single-row, simple `SELECT WHERE state='RESETTING'`)
- **Perplexity:** Extra columns on `files` table (`intent_type`, `intent_started_at`, `intent_api_calls_completed`); intent columns do NOT participate in OCC version increment

**Proposed decision:**
**Extra columns on `files` table.** Rationale: keeps recovery query as a simple `SELECT WHERE intent_type IS NOT NULL` (no joins, no FSM state proliferation). Intent columns are orthogonal to FSM state and do not increment the OCC version — they track progress within a transition. Schema: `intent_type TEXT` (NULL or 'reset_intent'), `intent_started_at TEXT` (ISO timestamp), `intent_api_calls_completed INTEGER` (0, 1, or 2). These columns are added in Phase 10's DB migration.

**Open questions:**
- Are there transitions beyond the reset that also need intent tracking now? (If so, should `intent_type` be an enum to distinguish them?)
- Should a `pending_intent` block new transitions as a cross-process mutex?

---

### ✅ GA-2: API Idempotency for Delete Operations (Consensus)

**What needs to be decided:**
When recovery re-runs `delete_store_document()` or `delete_file()` on a resource that was already deleted, the Google Gemini API returns a 404/Not Found error. This must be treated as success, not as a recovery failure.

**Why it's ambiguous:**
The Google Gemini SDK doesn't document idempotency guarantees for delete operations. Recovery code will call these methods a second time for crash points 1 and 2. Without explicit handling, a 404 on retry would incorrectly transition the file to `FAILED`.

**Provider synthesis:**
- **OpenAI:** Implement "safe delete" wrappers that swallow 404; propagate all other errors
- **Gemini:** Same — treat 404 as idempotent success; re-raises real errors
- **Perplexity:** Same — "design recovery to recognize idempotent outcomes, not rely on API guarantees"

**Proposed decision:**
Implement `safe_delete_store_document()` and `safe_delete_file()` wrappers: catch 404/Not Found → return True (success). All other exceptions re-raise. The exact exception class from the google-genai SDK for "resource not found" must be identified during Plan 10-01 implementation (e.g., `google.api_core.exceptions.NotFound`).

**Open questions:**
- Exact exception class from `google-genai` SDK for 404 — needs empirical verification in 10-01
- What about 403 Forbidden? Should that go to `FAILED` with a non-retriable reason?

---

### ✅ GA-3: Recovery Crawler Scope and Trigger (Consensus)

**What needs to be decided:**
When the recovery crawler runs (startup-only vs. periodic), what it scans for, and whether it blocks application readiness.

**Why it's ambiguous:**
"Startup recovery crawler" implies one-shot at startup, but if the application stays up for hours (e.g., batch upload), a crash mid-batch won't be recovered until the next restart. However, a continuous background crawler adds complexity and potential interference with normal transitions.

**Provider synthesis:**
- **OpenAI:** Periodic async task (every N minutes), scans `transition_intents WHERE active=1`, uses exponential backoff per intent
- **Gemini:** Blocking startup scan of `RESETTING/UPLOADING/PROCESSING` states; blocking ensures no race condition with user actions on "zombie" files
- **Perplexity:** Startup blocking recovery as primary; optional background monitor for anomaly detection only (alerts but doesn't auto-recover)

**Proposed decision:**
**Startup blocking recovery as primary mechanism.** Scan `SELECT WHERE intent_type IS NOT NULL` at startup before any upload operations begin. This is a blocking scan — application waits for recovery before proceeding. Optionally add a lightweight background monitor that detects but does NOT auto-recover intents older than 30 minutes (logs a warning, surfaces via CLI `status` command). Recovery crawler itself is tested as part of Plan 10-02.

**Open questions:**
- Should `UPLOADING` files (not just intent-tagged ones) also be reset to `UNTRACKED` at startup? (An `UPLOADING` file with no active upload task is stuck.)

---

### ✅ GA-4: FAILED State Escape Path (Consensus)

**What needs to be decided:**
Whether `FAILED` is a permanent tombstone or a recoverable intermediate state, and what transition(s) allow a file to escape `FAILED` without manual SQL.

**Why it's ambiguous:**
FSM-02 requires "every path into FAILED state has a designed and tested automatic recovery mechanism." But the escape path policy isn't specified: does the recovery crawler auto-retry FAILED files? Is a CLI command required? Is `FAILED → UNTRACKED` always safe?

**Provider synthesis:**
- **OpenAI:** `failed_reason` enum (AUTH/QUOTA/TRANSIENT/etc.); FAILED→UPLOADING for transient errors; FAILED blocked for AUTH/CONFIG; CLI `recover --all`
- **Gemini:** `retry_failed` transition → INDEXED (to retry the reset) or UNTRACKED; scheduled task every 6 hours auto-retries transient failures
- **Perplexity:** FAILED is recoverable intermediate; `retry_reset` and `mark_untracked` as explicit FSM transitions; recovery code decides which to trigger based on analysis

**Proposed decision:**
`FAILED` is a recoverable intermediate state (not terminal). The FSM exposes a `retry` transition: `FAILED → UNTRACKED`. The startup recovery crawler does NOT auto-retry FAILED files (to avoid infinite retry loops). A CLI command `objlib recover --failed` triggers retry of all FAILED files. The `FAILED` state retains `intent_type` and `intent_api_calls_completed` as audit context (not cleared on entry to FAILED — only cleared after successful retry completes). This satisfies VLID-02 with no manual SQL required.

**Open questions:**
- Should recovery crawler auto-retry FAILED after a timeout (e.g., 1 hour)? Or always require explicit CLI invocation?

---

### ⚠️ GA-5: Crash Simulation Test Methodology (Recommended)

**What needs to be decided:**
How to reliably inject crashes at the three specific crash points in async Python code for testing. True process kill is not practical in pytest. Injection via exception raising is testable but simulates a different failure mode than actual process termination.

**Why it's ambiguous:**
The HOSTILE distrust requirement demands "tested recovery, not designed recovery." But "tested" is ambiguous — does it mean pytest unit tests with injected failures, or subprocess crash tests?

**Provider synthesis:**
- **Gemini:** Crash proxy pattern (subclass or decorator accepting `crash_at_step` enum; raises `SimulatedCrash` exception; new `RecoveryCrawler` instance tests recovery)
- **Perplexity:** Three-tier approach: mock side_effect with controlled call counting; asyncio.CancelledError to simulate process crash (doesn't run cleanup); asyncio.timeout for timeout simulation

**Proposed decision:**
**Mock-based injection with CancelledError for DB-write crash simulation.** Three crash points:
1. After `delete_store_document()` → mock raises exception; DB has `intent_api_calls_completed=0`
2. After `delete_file()` → mock raises on second call; DB has `intent_api_calls_completed=1`
3. After both API calls but before finalize → raise `asyncio.CancelledError` after incrementing `intent_api_calls_completed=2` but before the final OCC UPDATE

Each crash point gets a dedicated pytest test. After injection, a fresh `RecoveryCrawler` instance runs and test asserts: (a) file reaches consistent non-stuck state, (b) intent columns cleared, (c) no manual SQL invoked.

---

### ⚠️ GA-6: OCC Version + Intent Atomicity Boundary (Recommended)

**What needs to be decided:**
The exact ordering of DB writes: when does the intent get written relative to the OCC version increment, and how many SQLite transactions are needed?

**Why it's ambiguous:**
Intent must be durable BEFORE any API call. But intent write and the initial state change (INDEXED → in-progress) need to be atomic. The OCC version should only increment when the transition *completes*, not when it starts (otherwise recovery has version=N+1 but file is still effectively INDEXED).

**Provider synthesis:**
- **OpenAI:** Two explicit transactions: Txn A (write intent + set `pending_intent_id` with OCC guard, no version increment); Txn B (finalize: OCC UPDATE + clear intent + increment version)
- **Perplexity:** Same two-transaction structure; intent columns don't participate in OCC version checks

**Proposed decision:**
Two-transaction structure:
- **Txn A (pre-API):** Write intent columns (`intent_type`, `intent_started_at`, `intent_api_calls_completed=0`) WHERE `gemini_state='indexed' AND version=?`. Commit. Version NOT incremented.
- **API calls:** Each success → UPDATE `intent_api_calls_completed` (single-row UPDATE, no version check needed, recovery context only).
- **Txn B (finalize):** OCC UPDATE: set `gemini_state='untracked'`, clear intent columns, `gemini_store_doc_id=NULL`, `gemini_file_id=NULL`, `version=version+1` WHERE `version=?`. Commit.

---

### ⚠️ GA-7: Reset Transition End State Semantics (Recommended)

**What needs to be decided:**
What is the final `gemini_state` after a successful reset? And what happens to `gemini_file_id` and `gemini_store_doc_id` during the transition?

**Why it's ambiguous:**
The roadmap says "INDEXED→UPLOADING reset transition" but the end state after deleting both remote resources should logically be `UNTRACKED` (clean slate) rather than `UPLOADING` (which implies upload is actively in progress). These are distinct states.

**Provider synthesis:**
- **OpenAI:** Final state = `UPLOADING`; clear `gemini_store_document_id` and `gemini_file_id`; set `upload_requested_at=now` to signal re-upload
- **Perplexity/Gemini:** Final state = `FAILED` (the reset landed at FAILED, then upload begins from UNTRACKED per recovery) — but this seems wrong

**Proposed decision:**
Final state after a successful reset = **`UNTRACKED`** (clean slate: both remote resources deleted, both ID columns cleared). The `UPLOADING` state is entered by the upload pipeline in a subsequent transition (`UNTRACKED → UPLOADING`). The "INDEXED→UPLOADING reset transition" in the roadmap refers to the intent (you reset a file so it can be re-uploaded), not the literal FSM path. The actual FSM path is: `INDEXED → (intent written) → APIs called → UNTRACKED`.

---

### 🔍 GA-8: Observability During Recovery (Needs Clarification)

**What needs to be decided:**
What CLI output / logging is needed for operators to see that recovery happened, is in progress, or is stuck?

**Provider synthesis:**
- **OpenAI:** `intents list` CLI command showing active intents, step, last_error, attempts; structured JSON logs; stuck detector (attempt>X → FAILED with `failed_reason=RECOVERY_STUCK`)

**Proposed decision:**
Add minimal observability: the startup recovery crawler logs each recovered file (INFO level). The `objlib status` command shows count of files with `intent_type IS NOT NULL`. No dedicated `intents list` command for Phase 10 (can add in Phase 13+ if needed). FAILED files with reason show in `objlib status`.

---

### 🔍 GA-9: SC3 Simplicity Measurement (Needs Clarification)

**What needs to be decided:**
How to objectively measure "recovery code simpler than transition code" for Success Criterion 3.

**Provider synthesis:**
- **Perplexity:** Cyclomatic complexity ≤60% of transition code; fewer external dependencies; fully deterministic given DB state

**Proposed decision:**
Measure by line count and branch count: recovery code for all 3 crash points combined should have fewer lines than the transition code itself. Criterion is satisfied if: (a) each crash point's recovery path is a single test case under 30 lines, (b) the recovery crawler's `recover_file()` function has no retry loops or error branches (just linear step resumption).

---

## Summary: Decision Checklist

**Tier 1 (Blocking — must decide before Plan 10-01):**
- [ ] GA-1: Intent representation → extra columns on `files` table
- [ ] GA-2: API idempotency → safe_delete wrappers, 404=success
- [ ] GA-6: OCC atomicity boundary → two-transaction structure
- [ ] GA-7: Reset end state → UNTRACKED (not UPLOADING, not FAILED)

**Tier 2 (Important — must decide before Plan 10-02):**
- [ ] GA-3: Crawler scope → startup blocking + optional background monitor
- [ ] GA-4: FAILED escape → `FAILED → UNTRACKED` transition, CLI `recover --failed`
- [ ] GA-5: Crash simulation → mock injection + CancelledError

**Tier 3 (Polish):**
- [ ] GA-8: Observability → minimal logging + status count
- [ ] GA-9: SC3 measurement → line count + branch count

---

*Multi-provider synthesis by: OpenAI gpt-4.1, Gemini Pro, Perplexity Sonar Deep Research*
*Generated: 2026-02-20*
