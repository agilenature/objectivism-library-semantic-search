# CLARIFICATIONS-NEEDED.md

## Phase 8: Store Migration Precondition — Decisions Required

**Generated:** 2026-02-19
**Mode:** Multi-provider synthesis (Gemini Pro, Perplexity Sonar Deep Research)
**Source:** 2/3 AI providers analyzed Phase 8 requirements

---

## Decision Summary

**Total questions:** 10
**Tier 1 (Blocking):** 4 questions — Must decide before 08-01/08-02 implementation
**Tier 2 (Important):** 4 questions — Must decide before 08-03 (check_stability.py)
**Tier 3 (Polish):** 2 questions — Can refine during implementation

---

## Tier 1: Blocking Decisions

### Q1: How Should Assertion 5 ("Search Returns Results") Behave on an Empty Store?

**Question:** After Phase 8, the store is empty. Assertion 5 (STAB-01) requires "search returns results." Should this assertion fail (exit 1 = UNSTABLE) when the store is empty, or be treated as N/A?

**Why it matters:** If assertion 5 always requires actual results, check_stability.py will report UNSTABLE immediately after a successful Phase 8 migration, breaking the gate instrument before it's even useful.

**Options:**

**A. Vacuous pass when store is empty** _(Proposed by: Perplexity)_
- If count invariant shows 0 indexed files, assertions 5 and 6 skip the result check and return PASS with note "store empty — N/A"
- No mode flags needed; empty-store is a valid STABLE state

**B. Require a smoke-test document** _(Proposed by: Gemini, implicit)_
- Upload one test document immediately after store creation
- Assertion 5 always has something to search against
- Extra complexity; smoke document must be tracked or purged before Phase 12

**C. Separate `--mode=empty-check` flag** _(Proposed by: Gemini)_
- Run `check_stability.py --mode=empty-check` after Phase 8
- Standard mode asserts results exist; empty-check mode asserts 0 results
- Extra flag complexity; two modes to maintain

**Synthesis recommendation:** ✅ **Option A (vacuous pass)** — cleanest approach, no extra infrastructure, consistent with count invariant driving assertion 5 semantics.

---

### Q2: Migration Operation Order — Create First or Delete First?

**Question:** MIGR-02 says "single confirmed operation." At the API level, should the script (a) delete old store then create new, or (b) create new store first, verify, then delete old?

**Why it matters:** If deletion succeeds but creation fails, there is no store at all. The pre-flight check itself will then fail on retry because the old store is gone. Recovery becomes manual.

**Options:**

**A. Create-then-delete (reverse order)** _(Proposed by: Both providers)_
- Create `objectivism-library`, verify `name` field non-empty
- Only then delete `objectivism-library-test`
- If creation fails: old store still exists, clean recovery
- If deletion fails after successful creation: both stores exist briefly; just retry deletion

**B. Delete-then-create (specified order)** _(Implied by MIGR-02 wording)_
- Delete old store first (matches user's mental model of "migration")
- If creation fails: manual recovery required

**Synthesis recommendation:** ✅ **Option A (create-then-delete)** — strictly safer. The "single confirmed operation" in MIGR-02 refers to user confirmation before any action, not API execution order.

---

### Q3: SQLite Schema Migration — ALTER TABLE or Create-Insert-Drop?

**Question:** How should the 3 new columns be added to the `files` table while ensuring `metadata_json` and entity tables are never touched?

**Options:**

**A. ALTER TABLE ADD COLUMN (3 raw SQL statements)** _(Proposed by: Both providers)_
- `ALTER TABLE files ADD COLUMN gemini_store_doc_id TEXT;`
- `ALTER TABLE files ADD COLUMN gemini_state TEXT DEFAULT 'untracked';`
- `ALTER TABLE files ADD COLUMN gemini_state_updated_at TEXT;`
- Wrapped in transaction; DB file backed up first
- Safe: doesn't touch existing columns

**B. Create-Insert-Drop (full table rebuild)** _(Mentioned as alternative)_
- Create `files_new` with target schema, INSERT SELECT from `files`, DROP old, RENAME
- More complex; risk of column mapping error touching sacred columns
- Overkill: SQLite supports ADD COLUMN with defaults natively

**Synthesis recommendation:** ✅ **Option A (ALTER TABLE)** — safe for columns with DEFAULT values in SQLite, doesn't touch existing data. Take `data/library.db.bak-phase8` backup first.

---

### Q4: Should gemini_file_id Also Be Nulled During the MIGR-04 Reset?

**Question:** MIGR-04 specifies resetting `gemini_store_doc_id = NULL` and `gemini_state = 'untracked'` but is silent on `gemini_file_id`. Should the existing `gemini_file_id` column also be set to NULL?

**Why it matters:** `gemini_file_id` holds references to Gemini File API resources that are either expired (48hr TTL) or stale (wrong store context). If left populated, the DB has dead pointers.

**Options:**

**A. Also null gemini_file_id** _(Proposed by: Both providers)_
- Complete state wipe for all Gemini columns
- `UPDATE files SET gemini_state='untracked', gemini_store_doc_id=NULL, gemini_file_id=NULL, gemini_state_updated_at=<ts> WHERE status='uploaded'`
- Clean baseline; no dead pointers

**B. Leave gemini_file_id populated** _(Strict reading of MIGR-04)_
- Only touch what MIGR-04 explicitly lists
- Risk: FSM code in Phase 12 may encounter stale IDs and behave unexpectedly

**Synthesis recommendation:** ✅ **Option A (also null gemini_file_id)** — "sacred metadata" rule protects AI metadata columns, not Gemini state columns. gemini_file_id is Gemini state.

---

## Tier 2: Important Decisions

### Q5: What Value Goes in gemini_state_updated_at During Migration?

**Question:** When bulk-resetting files to 'untracked', what timestamp goes in `gemini_state_updated_at`?

**Options:**

**A. Migration start timestamp** _(Proposed by: Perplexity)_
- Single datetime captured before the batch UPDATE; ISO 8601 with UTC timezone
- Enables stuck-transition detection from Phase 9 onward

**B. NULL** _(Conservative / literal)_
- "Never been through a real FSM transition"
- Breaks stuck-transition detection (can't compute time-in-state)

**C. Per-row timestamp** _(Precise but unnecessary)_
- Microsecond differences between rows; no analytical value

**Synthesis recommendation:** ⚠️ **Option A (migration start timestamp)**

---

### Q6: Exit Code 2 vs. Exit Code 1 — Precise Boundary?

**Question:** What exact conditions produce ERROR (exit 2) vs UNSTABLE (exit 1)?

**Options:**

**A. ERROR = prerequisite failures; UNSTABLE = invariant failures** _(Proposed by: Perplexity)_
- EXIT 2: store doesn't exist, wrong store name, missing API key, DB not found, schema missing columns
- EXIT 1: prerequisites pass, but assertions fail (count mismatch, ghost/orphan, stuck file, citation failure)
- EXIT 0: all prerequisites and assertions pass

**B. ERROR = API errors; UNSTABLE = any assertion fails** _(Simpler but less precise)_
- Conflates configuration errors with runtime errors

**Synthesis recommendation:** ⚠️ **Option A** — precise boundary makes the instrument useful as a gate.

---

### Q7: check_stability.py Architecture — Standalone or CLI Subcommand?

**Question:** Should the stability instrument live at `scripts/check_stability.py` (standalone) or be integrated as `objlib check-stability` (Typer subcommand)?

**Options:**

**A. Standalone script at scripts/check_stability.py** _(Proposed by: Both providers)_
- Independent of main app lifecycle
- Usable in cron jobs, CI/CD, external monitoring
- `if __name__ == '__main__'` pattern for reuse as imported module

**B. Typer CLI subcommand `objlib check-stability`** _(Integration option)_
- Shares config loading and DB connection logic
- Requires main app to be importable

**Synthesis recommendation:** ⚠️ **Option A (standalone)** — the requirement says `scripts/check_stability.py` explicitly. Independence from app lifecycle makes it a reliable gate instrument.

---

### Q8: Pre-flight Check — How to Count Store Documents?

**Question:** Should the pre-flight check use `list_store_documents()` (paginated iteration) or a store metadata API call that returns a document count field?

**Options:**

**A. Check store object metadata first (preferred)** _(Proposed by: Gemini)_
- Inspect `GeminiFileSearchClient` response for count fields (e.g., `active_documents_count`)
- Fall back to paginated `list_store_documents()` with Rich spinner if metadata count not available

**B. Always use paginated iteration** _(Simpler code)_
- Consistent behavior regardless of API support
- Slower; needs progress indicator to avoid appearing hung

**Synthesis recommendation:** ⚠️ **Option A (check metadata first)** — inspect the existing `get_store()` output to determine what count fields are available before committing to pagination.

---

## Tier 3: Polish Decisions

### Q9: Should the Migration Explicitly Delete Old Gemini File API Resources?

**Question:** Gemini File Search stores have two resource types: store documents (indexed content, permanent until deleted) and raw File API resources (48hr TTL). Store deletion deletes the store documents but may NOT delete raw file resources. Should Phase 8 iterate and delete raw files?

**Synthesis recommendation:** 🔍 **No explicit deletion.** Feb 17 uploads are 48hr+ expired. Verify in pre-flight by calling `list_files()` — if empty, skip. If any remain, log a warning; don't block migration.

---

### Q10: Store Creation Parameters Beyond display_name?

**Question:** Does the permanent `objectivism-library` store need explicit chunking strategy or model parameters?

**Synthesis recommendation:** 🔍 **display_name only.** Gemini File Search API manages chunking/embedding internally. Chunking is not user-configurable for File Search stores (unlike Vector Stores). Verify the created store's `name` field is non-empty.

---

## Next Steps

**YOLO Mode — proceeding to auto-generate answers.**

*Multi-provider synthesis: Gemini Pro + Perplexity Sonar Deep Research*
*Generated: 2026-02-19*
