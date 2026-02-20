# CONTEXT.md — Phase 12: 50-File FSM-Managed Upload

**Generated:** 2026-02-20
**Phase Goal:** 50 test files complete the full FSM lifecycle (UNTRACKED through INDEXED) with correct, verifiable `gemini_store_doc_id` for every file — the first real end-to-end proof.
**Synthesis Source:** Multi-provider AI analysis (Gemini Pro, Perplexity Sonar Deep Research)

---

## Overview

Phase 12 is the first real end-to-end integration of the FSM machinery proven in Phases 9–11. It has two distinct parts: (1) **12-01** wires the FSM into the production upload pipeline, and (2) **12-02 through 12-05** execute a 50-file upload and verify temporal stability across 36 hours using the Temporal Stability Protocol.

The synthesis identified **7 gray areas** across both providers, with strong consensus on 3 critical ones.

**Confidence markers:**
- ✅ **Consensus** — Both providers identified this as critical
- ⚠️ **Recommended** — One provider, strong rationale
- 🔍 **Needs Clarification** — Context-specific decision required

---

## Gray Areas Identified

### ✅ 1. FSM–AsyncUploadStateManager Wiring Architecture

**What needs to be decided:**
How exactly the FSM becomes the **sole authorized path** for `gemini_state` / `gemini_store_doc_id` mutations, given that `AsyncUploadStateManager` currently has direct SQL write methods (`record_upload_intent`, `record_import_success`, etc.) that do NOT call the FSM.

**Why it's ambiguous:**
Two valid architectures exist:
- **Option A: FSM wraps state manager.** FSM callbacks invoke `AsyncUploadStateManager` methods as side effects. FSM is the orchestrator. State manager becomes a data-access layer.
- **Option B: State manager calls FSM.** Every write method in `AsyncUploadStateManager` calls `fsm.send_event()` first. But this couples the data layer to the FSM library — a bad dependency direction.

**Provider synthesis:**
- **Gemini:** "FSM as the Driver" — use `on_enter_state` callbacks in the FSM that call `state_manager.persist_transition()`. SC4 enforcement = remove all raw `UPDATE SET gemini_state =` from codebase.
- **Perplexity:** "Wrapper-based integration" — FSM is orchestrator, state manager is data-access layer via dependency injection. FSM transition callbacks invoke `AsyncUploadStateManager` methods.

**Proposed implementation decision:**
**Option A: FSM wraps state manager.** The `AsyncUploadStateManager` gets new FSM-aware write methods:
- `transition_to_uploading(file_path)` — writes `gemini_state='uploading'`
- `transition_to_processing(file_path, gemini_file_id)` — writes `gemini_state='processing'`, stores `gemini_file_id`
- `transition_to_indexed(file_path, gemini_store_doc_id)` — writes `gemini_state='indexed'`, stores `gemini_store_doc_id`
- `transition_to_failed(file_path, reason)` — writes `gemini_state='failed'`

The FSM's `on_enter_*` callbacks call these. The legacy `record_upload_intent`, `record_import_success` methods are **preserved but no longer called in the new FSM path** (they remain for backward compat until Phase 13). SC4 audit = grep confirming no new callsites for the legacy methods write to `gemini_state`.

**Note on python-statemachine 2.6.0:** The async callbacks (`on_enter_state`, `before_transition`) can be declared `async def` — the library's `AsyncEngine` handles them automatically.

**Open questions:**
- Should the FSM instance be per-file (ephemeral, created for each upload task) or per-orchestrator (shared state machine)? **Answer: per-file.** Each file is an independent FSM instance loaded with `current_state=row['gemini_state']`.

---

### ✅ 2. `_reset_existing_files()` Store Document Lookup (SC3 Prerequisite)

**What needs to be decided:**
How `_reset_existing_files()` locates the store document to delete, given that:
1. Phase 11 proved `Document.display_name` = Files API resource ID (e.g., `"sqowzecl39n8"`), NOT the human-readable name.
2. The current `EnrichedUploadOrchestrator._reset_existing_files()` already does the lookup correctly (maps `gemini_file_id` suffix → Document.display_name = resource ID). This actually works.
3. But in the new FSM-managed pipeline, `gemini_store_doc_id` is explicitly persisted to DB after import — making a simpler direct lookup possible.

**Why it's ambiguous:**
Two approaches for the reset document lookup:
- **Option A:** Build `{file_resource_id: document_resource_name}` map from `list_store_documents()` on every reset. Already implemented in old code. Works via Document.display_name = file_id.
- **Option B:** Use `gemini_store_doc_id` directly from DB (set by FSM transition). No list call needed. O(1) direct lookup.

**Provider synthesis:**
- **Gemini:** Trust `gemini_store_doc_id` in DB first; fall back to list+scan if null.
- **Perplexity:** Same — DB-first lookup, list as fallback for ghost cleanup.

**Proposed implementation decision:**
**Option B for new FSM-managed files, Option A as fallback.**
After the FSM pipeline runs, every file with `gemini_state='indexed'` has a valid `gemini_store_doc_id` in the DB. The reset path should:
1. Use `gemini_store_doc_id` from DB directly → call `delete_store_document(gemini_store_doc_id)`.
2. Fall back to `list_store_documents()` map only if `gemini_store_doc_id IS NULL` (legacy files from pre-FSM runs).
3. Write-ahead: set `gemini_state='uploading'` (reset intent) BEFORE calling `delete_store_document()` — Phase 10 pattern.

**SC3 verification procedure:** Upload 50 files → confirm all indexed → get store document count via `list_store_documents()` → run reset on 5 specific files → confirm store document count decreased by exactly 5 → confirm 5 files have `gemini_state='untracked'` in DB.

---

### ✅ 3. RecoveryCrawler `finalize_reset()` Silent Ignore (SC6)

**What needs to be decided:**
How to fix `spike/phase10_spike/recovery_crawler.py:65` which calls `finalize_reset()` without checking the return value. SC6 requires the **production** `RecoveryCrawler._recover_file()` to raise (not silently succeed) when `finalize_reset()` returns `False` (OCC conflict).

**Why it's ambiguous:**
SC6 says "raises rather than silently succeeds." But:
- If the crawler raises **and aborts the whole batch**, a single OCC conflict leaves all remaining files unrecovered.
- If the crawler raises **per-file but continues**, that satisfies the spirit of SC6 while keeping batch recovery safe.

**Provider synthesis:**
- **Gemini:** Raise `ResetFailedError`, catch at the **outer loop level** per file, mark file as FAILED, continue to next file. Don't abort batch.
- **Perplexity:** Raise custom `OCCConflict` exception, retry 3x with backoff. Escalate to operator if all retries fail.

**Proposed implementation decision:**
The production `RecoveryCrawler._recover_file()` must:
```python
result = await finalize_reset(self._db_path, file_path, row["version"])
if not result:
    raise OCCConflictError(f"finalize_reset() OCC conflict: {file_path}")
```

The outer `recover_all()` loop catches `OCCConflictError` per file, logs it, and **continues to next file** (does not abort). This satisfies SC6's "raises" requirement while preserving batch recovery. A test simulates an OCC conflict by injecting a version increment during `finalize_reset()` and confirms the exception is raised.

**Test for SC6:** The spike's `finalize_reset()` increments version with OCC check (`WHERE version = ?`). To inject OCC conflict: increment the version in the DB AFTER the crawler reads it but BEFORE `finalize_reset()` writes. Confirm `OCCConflictError` is raised, not silently logged as "Recovered."

---

### ⚠️ 4. 50-File Test Corpus Selection

**What needs to be decided:**
Which 50 files (from 818 with `gemini_state='untracked'`) to use for Phase 12.

**Why it's ambiguous:**
Random selection makes debugging harder; first-N is reproducible but may miss edge cases; stratified sampling is rigorous but requires classification work.

**Provider synthesis:**
- **Gemini:** First 50 alphabetically by filename — minimizes variables, tests machinery not content.
- **Perplexity:** Stratified random sampling by file type, size bucket, metadata coverage.

**Proposed implementation decision:**
Since all 818 files are `.txt` (uniform format), size-based stratification is most useful. Select:
```sql
SELECT file_path FROM files
WHERE gemini_state = 'untracked'
  AND filename LIKE '%.txt'
ORDER BY file_path
LIMIT 50
```
This is reproducible, deterministic, and selects the first 50 alphabetically. Before running, verify none of these 50 paths exist in `list_store_documents()` (confirming clean baseline).

Document the selected 50 paths in the T=0 SUMMARY.md so subsequent sessions can cross-check.

---

### ⚠️ 5. SUMMARY.md Content Requirements for Temporal Stability Protocol

**What needs to be decided:**
What specific data must each SUMMARY.md checkpoint capture verbatim so that a fresh Claude session can verify system state without relying on prior session memory.

**Why it's ambiguous:**
"Sufficient context" is vague. If the SUMMARY.md only records pass/fail verdicts, a fresh session can't independently re-verify. If it records raw output verbatim, a fresh session can compare directly.

**Provider synthesis (Perplexity):** SUMMARY.md should contain: project context, implementation state, test corpus manifest, gray area decisions, verification procedures, and handoff checklist. Key principle: **raw script output verbatim**, not summarized.

**Proposed implementation decision (aligned with ROADMAP requirements):**
Each SUMMARY.md must contain **verbatim raw output** of:
1. `check_stability.py --store objectivism-library` — full output, exit code
2. DB query: `SELECT COUNT(*) FROM files WHERE gemini_state='indexed'` — exact number
3. DB query: `SELECT COUNT(*) FROM files WHERE gemini_store_doc_id IS NOT NULL` — exact number
4. `python -m objlib store-sync --store objectivism-library` (dry-run) — full output
5. 5 specific TUI search queries (same queries at T=0 and T+24h for comparison)
6. Timestamp of checkpoint execution

The **same 5 TUI queries** must be used across all checkpoints for comparison.

---

### ⚠️ 6. Bidirectional Cross-Verification Algorithm (SC2)

**What needs to be decided:**
The exact algorithm for bidirectional verification that 50 DB records and 50 store documents are in 1:1 correspondence.

**Why it's ambiguous:**
"Cross-verify" is vague. What does "bidirectional" mean in practice given the APIs available?

**Proposed implementation decision:**
```
Step A (DB → Store): For each of 50 files with gemini_state='indexed':
  - Read gemini_store_doc_id from DB
  - Call documents.get(name=gemini_store_doc_id)
  - Confirm document exists (no 404)
  - Record any missing documents (DB has it, Store doesn't)

Step B (Store → DB): Call list_store_documents()
  - Count total documents
  - For each document, check if its name matches any DB gemini_store_doc_id
  - Record any orphans (Store has it, DB doesn't)

Pass condition:
  - Step A: 0 missing (all 50 DB records confirmed in Store)
  - Step B: Count = 50 (no orphans beyond the 50)
```

This maps exactly to SC2 ("every store document matches a DB record, and every DB record's `gemini_store_doc_id` points to an existing store document").

---

### ⚠️ 7. Partial Upload Failure Gate Policy

**What needs to be decided:**
If some files fail during the 50-file upload, does the SC1 phase gate fail? Is there a threshold?

**Why it's ambiguous:**
SC1 says "all 50 files have `gemini_state='indexed'`... zero gaps." This implies zero-failure. But transient API errors may cause 1-2 failures.

**Provider synthesis:**
- **Gemini:** Tests the machinery; test should succeed cleanly.
- **Perplexity:** 90% success threshold (45/50) with failure categorization.

**Proposed implementation decision:**
**Zero-failure policy for the gate.** SC1 explicitly says "zero gaps." However, FAILED files should be **retryable** via `retry_failed_file()` (FAILED → UNTRACKED → re-run). Before assessing the gate, run `retry_failed_file()` for any FAILED files and re-upload them. The gate assessment happens AFTER retry, not after the first upload pass.

**If after retry some files remain FAILED:** Phase 12 gate does not pass. Investigate the FAILED files specifically. Gate is blocked for Phase 13.

---

## Summary: Decision Checklist

**Tier 1 (Blocking):**
- [ ] FSM wiring: FSM callbacks as sole trigger for `gemini_state` mutations
- [ ] `_reset_existing_files()`: Use `gemini_store_doc_id` from DB directly (not list+lookup)
- [ ] RecoveryCrawler: Raise `OCCConflictError` on False return from `finalize_reset()`

**Tier 2 (Important):**
- [ ] 50-file selection: First 50 alphabetically by file_path (deterministic)
- [ ] SUMMARY.md: Verbatim raw output for all 5 data points at each checkpoint
- [ ] SC2 algorithm: Two-step bidirectional verification via documents.get() + list

**Tier 3 (Process):**
- [ ] Gate policy: Zero-failure after retry (not after first pass)

---

## Phase 12 Plan Structure

Per ROADMAP, Phase 12 has 5 plans:

1. **12-01:** FSM integration into upload pipeline (AsyncUploadStateManager FSM methods, `_reset_existing_files()` fix, `display_name.strip()`, Document.display_name audit, SC6 production RecoveryCrawler fix)
2. **12-02:** 50-file upload + T=0 baseline [FRESH SESSION REQUIRED] — record check_stability, DB counts, store-sync dry-run, 5 TUI queries verbatim in SUMMARY.md
3. **12-03:** T+4h drift check [FRESH SESSION REQUIRED] — check_stability, orphan count vs T=0 SUMMARY.md
4. **12-04:** T+24h gate [FRESH SESSION REQUIRED] — check_stability, same 5 TUI queries, full bidirectional cross-check of all 50 files — BLOCKING for Phase 13
5. **12-05:** T+36h confirmation [FRESH SESSION REQUIRED] — check_stability exit 0 only

---

*Multi-provider synthesis by: Gemini Pro, Perplexity Sonar Deep Research*
*OpenAI query initiated but output not captured (model detection only)*
*Generated: 2026-02-20*
