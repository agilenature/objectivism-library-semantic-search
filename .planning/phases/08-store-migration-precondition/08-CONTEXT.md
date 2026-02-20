# CONTEXT.md — Phase 8: Store Migration Precondition

**Generated:** 2026-02-19
**Phase Goal:** The system starts from a clean, known baseline — old store deleted, permanent store created, DB schema extended, stability instrument operational.
**Synthesis Source:** Multi-provider AI analysis (Gemini Pro, Perplexity Sonar Deep Research)
**Note:** OpenAI timed out during model detection; 2/3 providers responded.

---

## Overview

Phase 8 is a precondition phase — it has no predecessor in v2.0 and every subsequent phase depends on it. It touches three distinct system boundaries simultaneously: the Gemini File Search API (external managed service), the SQLite database (local file), and the Python application tier. The irreversibility of the store deletion makes this phase uniquely high-stakes: once `objectivism-library-test` is deleted, search is offline until Phase 12 proves the FSM upload works.

Both AI providers identified many of the same gray areas independently, giving high confidence in the synthesis below.

**Confidence markers:**
- ✅ **Consensus** — Both providers identified this as critical
- ⚠️ **Recommended** — Strong single-provider finding or implicit in both
- 🔍 **Needs Clarification** — One provider identified, potentially blocking

---

## Gray Areas Identified

### ✅ 1. Assertion 5 "Search Returns Results" on Empty Store (Consensus)

**What needs to be decided:**
STAB-01 requires assertion 5: "search returns results." But after Phase 8, the store is empty and will have zero documents until Phase 12. Assertion 5 would fail on an empty store, incorrectly reporting UNSTABLE after a successful migration.

**Why it's ambiguous:**
There's a tension between "system is functioning" and "system has reached desired state." An empty store correctly returns zero search results — that's not instability. But if the assertion hard-codes "must return results," it will always fail immediately post-migration.

**Provider synthesis:**
- **Gemini:** Suggests a `--mode=empty-check` flag. Alternatively, "does the spec imply uploading a smoke-test document?"
- **Perplexity:** Implement a multi-part check: (a) search invocable without exceptions, (b) response object has correct structure, (c) IF store has documents, verify results are returned.

**Decision (YOLO):** Assertion 5 is **vacuously passing when store is empty** (0 indexed documents = assertion skips result check, returns PASS with note "store empty — N/A"). The assertion only enforces "search returns results" when the count invariant (assertion 1) shows indexed documents > 0. Same logic applies to assertion 6 (citation resolution). No mode flags needed — the count invariant drives the skip.

**Open questions resolved:** None — this decision is self-consistent.

---

### ✅ 2. Migration Atomicity: "Limbo" State Recovery (Consensus)

**What needs to be decided:**
The Gemini API provides no atomic multi-step transaction. If `delete(objectivism-library-test)` succeeds but `create(objectivism-library)` fails, the system is left with no store at all. The pre-flight check (which reads the old store's doc count) will then also fail, creating a recovery deadlock.

**Why it's ambiguous:**
MIGR-02 says "single confirmed operation" but does not define what "single" means at the API level. The implementation must pick an ordering and define recovery semantics.

**Provider synthesis:**
- **Gemini:** Implement a "Resurrect/Retry" check at startup — if old store absent AND new store absent → skip pre-flight, go straight to creation.
- **Perplexity:** **Reverse the operation order: create new store FIRST, verify it's ready, THEN delete old store.** This way, if creation fails, old store still exists — no limbo. Also: implement a local "intent" lockfile recording the target state.

**Decision (YOLO):** **Reverse order: create `objectivism-library` first, verify response (non-empty `name` field), then delete `objectivism-library-test`.** The pre-flight check (MIGR-01) runs before BOTH operations. Limbo recovery: if old absent AND new absent → print clear message "migration appears partially failed" with instructions; if old absent AND new present → migration already complete, skip.

**Confidence:** ✅ Both providers converged on "don't delete before creating"

---

### ✅ 3. SQLite Schema Migration Approach (Consensus)

**What needs to be decided:**
How to add the 3 new columns to the `files` table — ALTER TABLE ADD COLUMN vs. create-insert-drop.

**Why it's ambiguous:**
SQLite's ALTER TABLE is limited vs. other databases. Using an ORM migration tool might silently attempt table recreation (create-insert-drop), risking the sacred `metadata_json` column if the column mapping is wrong.

**Provider synthesis:**
- **Gemini:** Use raw SQL `ALTER TABLE files ADD COLUMN ...` (3 statements). Do NOT use ORM auto-generation. Backup DB file first with `shutil.copy()`.
- **Perplexity:** Confirms ALTER TABLE ADD COLUMN is safe for columns with DEFAULT values in SQLite. Wrap in transaction. Run `PRAGMA integrity_check` before and after.

**Decision (YOLO):** **Use explicit raw SQL with 3 separate `ALTER TABLE` statements wrapped in a single transaction.** Run `PRAGMA integrity_check` before execution. Take a file-level backup of `data/library.db` to `data/library.db.bak-phase8` before any schema changes. After migration, verify the 3 columns exist with a `PRAGMA table_info(files)` check.

**Confidence:** ✅ Consensus — explicit raw SQL is clearly safer for sacred metadata preservation

---

### ✅ 4. Legacy gemini_file_id Column Must Also Be Nulled (Consensus)

**What needs to be decided:**
MIGR-04 specifies resetting `gemini_store_doc_id = NULL` and `gemini_state = 'untracked'` for uploaded files. It does NOT explicitly mention the existing `gemini_file_id` column. But `gemini_file_id` holds references to Gemini File API resources that are either expired (48hr) or stale (old store context).

**Why it's ambiguous:**
The requirement is silent on `gemini_file_id`. If left populated, the DB contains dead pointers to non-existent or orphaned file resources.

**Provider synthesis:**
- **Gemini:** "Update the schema migration (Plan 08-01) to also set `gemini_file_id = NULL` for records with `status='uploaded'`. State should fully revert to 'ready to upload'."
- **Perplexity:** Confirms that leaving stale `gemini_file_id` values creates invalid state when the FSM checks this column during Phase 12.

**Decision (YOLO):** **Also set `gemini_file_id = NULL` for all files being reset.** Reset scope for MIGR-04: `UPDATE files SET gemini_state='untracked', gemini_store_doc_id=NULL, gemini_file_id=NULL, gemini_state_updated_at=<migration_ts> WHERE status='uploaded'`. This is a complete state wipe for Gemini columns while leaving all AI metadata untouched.

---

### ✅ 5. gemini_state_updated_at Timestamp Semantics During Reset (Consensus)

**What needs to be decided:**
What value goes into `gemini_state_updated_at` when files are bulk-reset to `'untracked'` during migration? NULL? Migration start timestamp? Per-row timestamp?

**Why it's ambiguous:**
This column is meant to track when the FSM last transitioned a file's state. During migration, all files are being reset simultaneously — not through normal FSM transitions. NULL would break stuck-transition detection (can't calculate how long a file has been in a state).

**Provider synthesis:**
- **Perplexity:** Set to migration start timestamp (captured once before the UPDATE loop). Use ISO 8601 with microseconds. This is accurate: the reset *is* a state transition (to `untracked`) that happened at migration time.
- **Gemini:** Does not explicitly address timestamp semantics, but the logic follows from the FSM design.

**Decision (YOLO):** **Set `gemini_state_updated_at` to the migration start timestamp** (single Python `datetime.now(UTC).isoformat()` captured before the batch UPDATE). ISO 8601 format with timezone. This correctly records when the state last changed and enables stuck-transition detection from Phase 9 onward.

---

### ⚠️ 6. Underlying Gemini File API Resources (Gemini-Primary)

**What needs to be decided:**
The Gemini File Search API has two separate resource types: (a) **File resources** (raw uploaded content, 48hr TTL) and (b) **Store documents** (indexed vectors, permanent). Deleting the store deletes the indexed documents but does NOT automatically delete the raw File resources. The old store has ~2,038 store documents. Do we need to explicitly delete the underlying File resources?

**Why it's ambiguous:**
If 2,038 raw files are still consuming quota after store deletion, Phase 12+ uploads might hit quota limits. But raw files expire after 48hr anyway, so they may already be gone (the files from Feb 17 uploads are over 48hr old as of Phase 8).

**Provider synthesis:**
- **Gemini:** "The migration script MUST iterate through old store documents, retrieve their file_id, and issue deletion commands for Files before/after deleting the Store."
- **Perplexity:** (Less explicit on this point; focuses on store-level operations)

**Decision (YOLO):** **No explicit raw file deletion needed.** The Feb 17 uploads are 48hr+ old — all raw files have auto-expired. The store documents (indexed content) are deleted when the store is deleted. The migration only needs to `delete_store()` for `objectivism-library-test`. Verify this assumption in the pre-flight: check if `list_files()` returns anything; if so, log a warning but don't block migration.

---

### ⚠️ 7. Pre-flight Check: Count Acquisition Strategy (Recommended)

**What needs to be decided:**
How does the pre-flight check (MIGR-01) enumerate the ~2,038 store documents? Using `list_store_documents()` (paginated iteration) vs. a metadata API call that returns a count field directly.

**Why it's ambiguous:**
The Gemini File Search store API may expose a document count in the store metadata without requiring full pagination. If it does, that's much faster. If not, iterating 2,038 documents takes time and looks like a hang.

**Provider synthesis:**
- **Gemini:** "Use `get_store` API method which typically returns `file_count` property." If iteration is required, show Rich progress bar.
- **Perplexity:** Similar; emphasizes user visibility.

**Decision (YOLO):** **Inspect the `GeminiFileSearchClient.get_store()` method output first.** If the store object has a `document_count` or `active_documents_count` field, use that. If not, use paginated `list_store_documents()` with a Rich spinner. Either way, also query the DB for `SELECT COUNT(*) WHERE status='uploaded'` to show files-losing-state count. Pre-flight output format:
```
Store 'objectivism-library-test': 2,038 documents
DB: 818 files with status='uploaded' will be reset to 'untracked'
All AI metadata (metadata_json, entities) will be preserved.
Proceed? (yes/no)
```

---

### ⚠️ 8. Exit Code Semantics: ERROR vs UNSTABLE Boundary (Recommended)

**What needs to be decided:**
The distinction between exit 1 (UNSTABLE) and exit 2 (ERROR) must be precise for every assertion. STAB-03 provides one example: wrong store name → exit 2. But what about assertions that encounter API errors mid-check?

**Provider synthesis:**
- **Perplexity:** Formal definition: "EXIT 2 = prerequisites failed (can't connect, wrong store, missing API key). EXIT 1 = prerequisites pass but invariants fail."

**Decision (YOLO):** Formal boundary:
- **EXIT 2 (ERROR):** Store name doesn't exist, missing API key, DB file not found, DB schema missing expected columns, any error that prevents running assertions at all.
- **EXIT 1 (UNSTABLE):** All prerequisites pass (can connect, schema present) but at least one assertion fails (count mismatch, ghost detected, orphan detected, file stuck in uploading, citation resolves to nothing).
- **EXIT 0 (STABLE):** All prerequisites pass AND all applicable assertions pass.
- **N/A assertions** (empty store): Counted as PASS for exit code calculation.

---

### ⚠️ 9. check_stability.py Architecture: Standalone vs. CLI Subcommand (Recommended)

**What needs to be decided:**
Should `check_stability.py` live in `scripts/` as a standalone executable, or be integrated as a `objlib check-stability` Typer subcommand? The requirement calls it `scripts/check_stability.py`, suggesting standalone.

**Provider synthesis:**
- **Perplexity:** "Standalone module importable as library AND executable as script via `if __name__ == '__main__'`. Supports external monitoring, cron jobs, CI/CD without requiring main app."
- **Gemini:** Implicitly standalone (references the script path directly).

**Decision (YOLO):** **Standalone script at `scripts/check_stability.py`** with `if __name__ == '__main__'` pattern. Arguments: `--store <name>`, `--db <path>`, `--verbose`. Uses `python -m objlib` internal modules for DB access and Gemini client. Does NOT integrate into the Typer CLI as a subcommand (keeps it independent of app lifecycle for use as external gate instrument).

---

### ⚠️ 10. Store Creation API Parameters (Recommended)

**What needs to be decided:**
What parameters beyond `display_name` are needed when creating the permanent `objectivism-library` store? Is chunking strategy or model specification required?

**Provider synthesis:**
- **Gemini:** "Hardcode chunking strategy and model compatibility NOW or risk recreating the store later when Phase 12 behavior doesn't match."
- **Perplexity:** "Minimum is just `display_name`. API defaults handle chunking automatically."

**Decision (YOLO):** **Use `display_name` only** — Gemini File Search API manages chunking/embedding internally for File Search stores. Do NOT specify chunking strategy (it's not user-configurable in the File Search API, unlike vector stores). Verify the created store's `name` field is non-empty; store this as the canonical store name for all subsequent phases.

---

## Summary: Decision Checklist

**Tier 1 (Blocking — must be correct in 08-01 and 08-02):**
- [x] Assertion 5/6: vacuously pass when store is empty
- [x] Migration order: create new store BEFORE deleting old store
- [x] Schema migration: raw SQL ALTER TABLE, not ORM
- [x] MIGR-04 scope: also null gemini_file_id during reset

**Tier 2 (Important — must be correct for gate instrument to work):**
- [x] gemini_state_updated_at: set to migration timestamp (not NULL)
- [x] Exit codes: formally defined ERROR vs UNSTABLE boundary
- [x] check_stability.py: standalone script, not CLI subcommand
- [x] Pre-flight: show store doc count + DB files-losing-state count

**Tier 3 (Polish — can refine during implementation):**
- [x] Raw file cleanup: not needed (48hr TTL already expired)
- [x] Store creation parameters: display_name only

---

*Multi-provider synthesis by: Gemini Pro (high thinking), Perplexity Sonar Deep Research*
*OpenAI: unavailable (timeout during model detection)*
*Generated: 2026-02-19*
*Mode: YOLO*
