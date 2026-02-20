# CLARIFICATIONS-NEEDED.md

## Phase 12: 50-File FSM-Managed Upload — Stakeholder Decisions Required

**Generated:** 2026-02-20
**Mode:** Multi-provider AI synthesis (Gemini Pro, Perplexity Sonar Deep Research)
**Source:** 2 AI providers analyzed Phase 12 requirements

---

## Decision Summary

**Total questions:** 7
**Tier 1 (Blocking):** 3 questions — Must answer before planning
**Tier 2 (Important):** 3 questions — Should answer for quality
**Tier 3 (Process):** 1 question — Can defer to implementation

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: FSM-AsyncUploadStateManager Integration Architecture

**Question:** Should the FSM be wired as the sole trigger for `gemini_state` mutations by (A) adding new FSM-aware write methods to `AsyncUploadStateManager` that the FSM callbacks call, or (B) something else?

**Why it matters:** SC4 requires that no `gemini_state` / `gemini_store_doc_id` mutation occurs outside an FSM transition. The current `AsyncUploadStateManager` has direct-write methods (`record_upload_intent`, `record_import_success`) that bypass the FSM. If we don't establish a clear integration pattern, SC4 is unverifiable.

**Options:**

**A. FSM Wraps State Manager (Wrapper-Based)** _(Recommended by both providers)_
- Add new methods to `AsyncUploadStateManager`: `transition_to_uploading()`, `transition_to_processing()`, `transition_to_indexed(gemini_store_doc_id)`, `transition_to_failed(reason)` — each writes only `gemini_state` (and `gemini_store_doc_id` where relevant)
- FSM `on_enter_*` callbacks call these methods
- Legacy methods (`record_upload_intent`, `record_import_success`) preserved but not called in new FSM path
- SC4 audit = grep confirming no new call sites to legacy methods in the FSM upload path
- Dual-write `status` column in these same new methods for backward compat (Phase 13 removes dual-write)

**B. Monolith Rewrite**
- Refactor all of `AsyncUploadStateManager` to route through FSM internally
- Higher risk, more invasive, harder to test incrementally
- Not recommended

**Synthesis recommendation:** ✅ **Option A — Wrapper-Based**
- Minimum-invasive, testable, backward-compatible, satisfies SC4

**Sub-questions:**
- FSM instance: per-file (ephemeral, instantiated with `current_state=row['gemini_state']`) or per-orchestrator?
  - **Recommendation: per-file.** Each concurrent upload task owns its FSM instance.
- Where does the FSM instance live during async execution?
  - **Recommendation:** Instantiated in `_upload_single_file()` for each file. Passed down to transition calls.

---

### Q2: `_reset_existing_files()` Store Document Lookup Fix

**Question:** After the FSM-managed upload stores `gemini_store_doc_id` in the DB, should `_reset_existing_files()` use `gemini_store_doc_id` directly for deletion (Option A) or continue using the `list_store_documents()` map approach (Option B)?

**Why it matters:** SC3 requires that resets delete store documents (not just raw files). The current code already does a `list_store_documents()` map using Document.display_name = file resource ID, which happens to work for the current setup. But with FSM tracking `gemini_store_doc_id` explicitly, Option A is simpler and eliminates the list call.

**Options:**

**A. Direct DB Lookup (Simpler, FSM-native)** _(Recommended)_
- `_reset_existing_files()` reads `gemini_store_doc_id` from DB
- Calls `delete_store_document(gemini_store_doc_id)` directly — no list call needed
- Write-ahead intent: set `gemini_state='uploading'` (reset intent) BEFORE delete API call
- Fallback: if `gemini_store_doc_id IS NULL`, fall back to list+map for legacy files

**B. Keep Existing `list_store_documents()` Map Approach**
- Continues to work (Document.display_name = file resource ID = gemini_file_id suffix)
- More API calls but no schema dependency
- Doesn't leverage the new `gemini_store_doc_id` column

**Synthesis recommendation:** ✅ **Option A for Phase 12 files, Option B as fallback**

---

### Q3: RecoveryCrawler SC6 Fix — Behavior on `finalize_reset()` Returning False

**Question:** When production `RecoveryCrawler._recover_file()` detects a False return from `finalize_reset()` (OCC conflict), should it: (A) raise an exception that the outer loop catches per-file, logging the error and continuing recovery of remaining files, or (B) abort the entire batch recovery?

**Why it matters:** SC6 requires "raises rather than silently succeeds." But if we abort the entire recovery batch on one OCC conflict, it defeats the purpose of batch recovery (all other stuck files remain unrecovered).

**Options:**

**A. Raise per-file, continue batch** _(Recommended by both providers)_
```python
# In _recover_file():
result = await finalize_reset(self._db_path, file_path, row["version"])
if not result:
    raise OCCConflictError(f"OCC conflict: {file_path}")

# In recover_all():
for row in rows:
    try:
        await self._recover_file(row)
        recovered.append(row["file_path"])
    except OCCConflictError as e:
        logger.error("Recovery OCC conflict: %s", e)
        occ_failures.append(row["file_path"])
        # Continue to next file
```

**B. Raise and abort entire batch**
- Simpler but breaks batch recovery
- Not recommended

**Synthesis recommendation:** ✅ **Option A — per-file raise, batch continues**

---

## Tier 2: Important Decisions (⚠️ Recommended)

### Q4: 50-File Test Corpus Selection

**Question:** Which 50 files should be used for the Phase 12 upload test?

**Options:**

**A. First 50 alphabetically** _(Recommended for reproducibility)_
```sql
SELECT file_path FROM files
WHERE gemini_state = 'untracked' AND filename LIKE '%.txt'
ORDER BY file_path LIMIT 50
```

**B. Stratified random sampling** (20% across 5 size buckets)
- More representative but requires pre-classification
- Less reproducible without fixed seed

**Synthesis recommendation:** ⚠️ **Option A** — deterministic, reproducible, tests the machinery not content variety

---

### Q5: SUMMARY.md Verbatim Content Requirements

**Question:** What data must be captured verbatim in each T=N SUMMARY.md for the next fresh session to independently verify?

**Required verbatim captures per checkpoint:**
1. Full output of `check_stability.py --store objectivism-library` (including exit code)
2. `SELECT COUNT(*) FROM files WHERE gemini_state='indexed'` result
3. `SELECT COUNT(*) FROM files WHERE gemini_store_doc_id IS NOT NULL` result
4. Full output of `python -m objlib store-sync --store objectivism-library` (dry-run)
5. Results of 5 specific TUI search queries (same queries across all checkpoints)
6. Exact timestamp of checkpoint

**The 5 TUI queries to standardize:** Decided during 12-02 execution and documented in T=0 SUMMARY.md.

---

### Q6: Bidirectional Cross-Verification Algorithm (SC2)

**Question:** What is the exact pass/fail algorithm for SC2 bidirectional verification?

**Proposed algorithm:**
```
Step A — DB → Store (50 checks):
  For each of 50 files with gemini_state='indexed':
    - Read gemini_store_doc_id from DB
    - Call documents.get(name=gemini_store_doc_id)
    - PASS if document exists, FAIL if 404
    - Record: missing_from_store = [file_paths with 404]

Step B — Store → DB (1 list call):
  - Call list_store_documents() → store_docs
  - For each store_doc: check if store_doc.name in DB.gemini_store_doc_id values
  - Record: orphaned_in_store = [doc names without DB match]

Gate PASS: missing_from_store is empty AND len(orphaned_in_store) == 0
```

---

## Tier 3: Process Decision (🔍 Needs Clarification)

### Q7: Partial Upload Failure Gate Policy

**Question:** If some files FAIL during the 50-file upload (after retry), does the Phase 12 gate fail entirely, or is there a threshold?

**Options:**

**A. Zero-failure after retry (strict)** _(Recommended, matches SC1 "zero gaps")_
- Run `retry_failed_file()` on any FAILED files before gate assessment
- Gate assessment happens AFTER retry
- If any file remains FAILED after retry: gate FAILS

**B. 90% success threshold**
- 45/50 files indexed = gate passes
- Contradicts SC1 which says "zero gaps"

**Synthesis recommendation:** ✅ **Option A** — SC1 is explicit: "zero gaps." Retry is the mechanism to handle transient failures before gate assessment.

---

## Next Steps (YOLO Mode)

Auto-generated answers will be produced in CLARIFICATIONS-ANSWERED.md, then planning proceeds automatically.

---

*Multi-provider synthesis: Gemini Pro + Perplexity Sonar Deep Research*
*Generated: 2026-02-20*
