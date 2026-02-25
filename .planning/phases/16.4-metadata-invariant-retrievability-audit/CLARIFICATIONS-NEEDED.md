# CLARIFICATIONS-NEEDED.md

## Phase 16.4: Metadata Pipeline Invariant + Comprehensive Retrievability Audit

**Generated:** 2026-02-25
**Mode:** Multi-provider synthesis (OpenAI gpt-5.2, Gemini Pro)
**Source:** 2 AI providers analyzed Phase 16.4 requirements

---

## Decision Summary

**Total questions:** 7
**Tier 1 (Blocking):** 2 questions — Must answer before planning
**Tier 2 (Important):** 3 questions — Should answer for quality
**Tier 3 (Polish):** 2 questions — Can defer to implementation

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: Corpus Count — 1,749 or 1,809?

**Question:** Phase 16.4 SC3 and SC4 reference "1,809 indexed files," but Phase 16.3 ended with DB=1749, Store=1749, Orphans=0. What are the extra 60 files? Are they: (a) scanner-approved non-book files that will be re-extracted and uploaded after the routing fix, or (b) a documentation error?

**Why it matters:** The retrievability audit (Plan 16.4-03) runs against all indexed files. If the denominator is wrong, "zero exclusions" is meaningless. Plans 16.4-02 and 16.4-03 depend on knowing the expected final count before they begin.

**Options identified by providers:**

**A. The 60 are currently scanner-approved non-book files** _(Proposed by: Synthesis)_
- After Plan 16.4-01 routing fix, these files get re-extracted + uploaded, bringing total to 1,809
- Consistent with Phase 16.4 goal (routing fix finds hidden non-compliant files)
- Plans 16.4-01 must confirm the exact count before 16.4-02 begins

**B. 1,809 is a documentation error; true count is 1,749** _(Proposed by: Gemini)_
- The 60 were the ITOE OH files that were already part of the 1,749 and just re-uploaded with better metadata
- Plans run against 1,749 files

**Synthesis recommendation:** ✅ **Option A — confirm via DB query in Plan 16.4-01 before proceeding**
- Run: `SELECT COUNT(*) FROM files WHERE ai_metadata_status='approved' AND primary_topics IS NULL` — this gives the exact delta
- If result is ~60, Option A is confirmed; if 0, Option B is confirmed

**Sub-questions:**
- What is the current DB count of `gemini_state='indexed'` files?
- What is the current count of `ai_metadata_status='approved'` files lacking `primary_topics`?

---

### Q2: Is max_misses=0 Achievable for Episode Files?

**Question:** The 333 Episode files were previously excluded from A7 due to semantic homogeneity. Phase 16.4 SC5 requires max_misses=0 with no exclusions. Can identity headers (Title/Course/Topic/Tags added in Phase 16.3) make Episodes retrievable with zero misses? Or will this require concluding that Episodes have an irreducible floor?

**Why it matters:** If Episodes structurally cannot achieve zero misses (due to generic titles, no class numbers, similar topics), then SC5 is not achievable as written — requiring either a project decision to accept an "affirmative evidence of floor" outcome, or a change to the indexing approach for Episodes.

**Options identified by providers:**

**A. Plan 16.4-03 retrieves Episodes using Episode number in title** _(Proposed by: Synthesis)_
- Query: `"{Episode title}" {top-3 topics}` — discriminates by unique episode number
- If identity headers include episode number in Title field, should work
- Risk: episode numbers may not be unique enough if topics overlap

**B. Accept affirmative floor: Episodes cannot achieve zero misses** _(Proposed by: Gemini)_
- Document what discriminating factor would be needed (e.g., unique per-episode keyword)
- SC4 explicitly allows this: "the residual failure cases are documented with affirmative evidence"
- SC5 max_misses=0 would then be applied only to non-Episode files — but this conflicts with "no exclusion filters"

**C. Episode-specific indexing strategy needed** _(Proposed by: OpenAI)_
- Use a different query approach for Episodes in A7 (series-specific logic)
- Conflicts with goal of keeping A7 simple and universal

**Synthesis recommendation:** ⚠️ **Let Plan 16.4-03 data decide** — attempt Options A and B empirically first; document findings before Plan 16.4-04 begins. Do not pre-decide this.

**Sub-questions:**
- Do Episode identity headers include a unique episode number in the Title field?
- Are the ITOE OH files (60, also excluded) expected to behave similarly to Episodes?

---

## Tier 2: Important Decisions (⚠️ Recommended)

### Q3: Book-Size Threshold Value and Units

**Question:** What byte count should `BOOK_SIZE_BYTES` (or equivalent constant) be set to for routing files between "AI-extract" and "scanner-only"? And what measurement: raw file bytes, header+transcript bytes, or character count?

**Why it matters:** SC1 requires a named constant used by all routing code. The constant must correctly classify all current `ai_metadata_status='skipped'` files as books and all non-skipped files as non-books.

**Options:**

**A. Measure largest successfully-extracted file, set threshold to 1.5x** _(Proposed by: Synthesis)_
- Empirical: grounded in actual extraction successes
- Run: `SELECT MAX(LENGTH(metadata_json)) FROM files WHERE ai_metadata_status='approved'` (approximation)
- Or better: check the largest .txt file that completed batch-extract

**B. Use 80,000 bytes (~20-25k tokens)** _(Proposed by: Gemini)_
- Conservative for Mistral 7B-class models
- May be too conservative for `mistral-small-latest` (which has larger context)

**Synthesis recommendation:** ⚠️ **Option A** — derive empirically from the current corpus before setting the constant; commit the constant alongside a comment documenting why this value was chosen.

**Sub-questions:**
- Which Mistral model is used in the batch extraction jobs? (Check `batch_orchestrator.py`)
- What is the largest file in the `ai_metadata_status='skipped'` category (in bytes)?

---

### Q4: Retrievability Audit — Query Strategy Templates

**Question:** What are the exact 3 query string templates for the comprehensive retrievability audit in Plan 16.4-03? Specifically: how are topic_aspects joined? How many topics/aspects are used? Is there any quoting or special formatting?

**Why it matters:** The 3 strategies must be defined before the audit script can be built. The "minimum viable strategy" conclusion depends on having consistent, reproducible query formats.

**Proposed templates:**

**Strategy 1 (Stem-only):**
- Query: `{filename stem}` (e.g., "Objectivist Logic Class 09-02")
- Tests whether the unique filename alone is sufficient

**Strategy 2 (Stem + aspects):**
- Query: `{filename stem} {top-3 topic_aspects joined by space}`
- Example: "ITOE Class 03-01 consciousness perception concept formation"
- Tests whether adding semantic aspects improves discrimination

**Strategy 3 (Topics + course):**
- Query: `{course name} {top-3 primary_topics joined by space}`
- Example: "Introduction to Objectivist Epistemology epistemology perception consciousness"
- Tests course+topic as a semantic anchor

**Threshold:** File counted as "found" if it appears in **top-5 results** (not top-1; consistent with Phase 15 design philosophy for semantic search)

**Synthesis recommendation:** ⚠️ Use the proposed templates above — they cover the full spectrum from structural (stem-only) to semantic (topics+course)

**Sub-questions:**
- For files with NULL topic_aspects, should strategy 2 fall back to strategy 1?
- Should Episode files use a different stem format (they have no class number)?

---

### Q5: Routing Enforcement — Pre-Upload Check or FSM Guard?

**Question:** Where should the invariant "non-book files must have primary_topics before upload" be enforced? In `_get_pending_files()` (extraction gate), in `get_fsm_pending_files()` (upload gate), or in both?

**Why it matters:** The routing fix (Plan 16.4-01) will re-route some scanner-approved files back to pending. But the enforcement must prevent this situation from recurring. The question is whether to add a guard in the FSM or a pre-upload check.

**Options:**

**A. Fix `_get_pending_files()` + add pre-upload invariant check in `get_fsm_pending_files()`** _(Synthesis recommendation)_
- Double-gating: extraction gate ensures extraction runs, upload gate ensures completion
- Consistent with Phase 16.2 design (upload gate already enforces ordering)
- Safe: no FSM modification (avoids InvalidDefinition risk from Phase 12)

**B. Add FSM transition guard in python-statemachine** _(Proposed by: OpenAI)_
- Stronger enforcement at the FSM level
- Risk: python-statemachine guard modification may introduce InvalidDefinition errors
- Out of scope per locked decision from Phase 13

**Synthesis recommendation:** ⚠️ **Option A** — two-layer check without FSM modification

---

## Tier 3: Polish Decisions

### Q6: Retrievability Audit Script — Resumability Mechanism

**Question:** Should the audit script save progress per-file per-strategy to a JSON file or SQLite table, to allow resuming after interruption?

**Proposed answer:** JSON file keyed by `{file_id}_{strategy}` with run timestamps. Simpler than SQLite, sufficient for a one-time audit script.

---

### Q7: A7 Consecutive STABLE Runs — Time Gap

**Question:** What minimum time gap is required between the two consecutive A7 STABLE runs in Plan 16.4-04?

**Proposed answer:** At least 1 hour, consistent with Phase 16.3 (which used 4 minutes but still passed — however the ROADMAP says "at least 1 hour" for the gate). Fresh sessions required for both runs per Phase 12 temporal stability protocol.

---

## Next Steps (YOLO Mode)

YOLO mode is active. CLARIFICATIONS-ANSWERED.md will be auto-generated.

---

*Multi-provider synthesis: OpenAI gpt-5.2, Gemini Pro (Perplexity unavailable)*
*Generated: 2026-02-25*
