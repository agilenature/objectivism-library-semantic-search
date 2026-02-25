# CLARIFICATIONS-NEEDED.md

## Phase 16.3: Gemini File Search Retrievability Research — Stakeholder Decisions Required

**Generated:** 2026-02-24
**Mode:** Multi-provider synthesis (Gemini Pro + Perplexity Sonar Deep Research)
**Source:** 2 AI providers analyzed Phase 16.3 requirements

---

## Decision Summary

**Total questions:** 7
**Tier 1 (Blocking):** 2 questions — Must decide before planning 16.3-01 spike
**Tier 2 (Important):** 3 questions — Should decide before 16.3-02 intervention
**Tier 3 (Polish):** 2 questions — Can decide during implementation

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: Primary Fix Target — H1 (Content Injection) vs H4 (Assertion Redesign)

**Question:** If the diagnosis spike confirms H1 (metadata not in indexed content), should we fix the upload pipeline to inject metadata headers (better UX, more work, ~454 re-uploads) OR redesign A7 to use `document_name` exact-match (fixes test only, zero re-uploads)?

**Why it matters:** This determines the entire scope of 16.3-02 and 16.3-03. H1 fixes real user retrievability. H4 only fixes the instrument. But H4 is zero-risk to the sacred corpus.

**Options:**

**A. H1 — Metadata header injection (Fix real retrievability)**
- Prepend structured header with class identifier, topic, primary_topics to each affected file before upload
- Re-upload ~454 Category A+B files through the existing FSM pipeline
- A7 assertion continues to test semantic query retrievability (correct)
- _(Proposed by: Gemini Pro, Perplexity)_

**B. H4 — A7 assertion redesign (Fix the test only)**
- Use `retrieved_context.document_name` exact-match instead of semantic query in A7
- Zero re-uploads, zero changes to upload pipeline
- A7 assertion no longer tests semantic retrievability — tests existence only
- _(Proposed by: neither provider as primary — raised as contingency only)_

**C. Both — H1 + H4 layered approach**
- Implement H1 fix for Category A (class-number files) where semantic content is the issue
- Use H4 for Category B (generic MOTM files) where semantic discrimination may be impossible even with headers
- _(Proposed by: Perplexity as composite recommendation)_

**Synthesis recommendation:** ✅ **Option A (H1 primary) with Option C as fallback for Category B if H1 insufficient**

**Sub-questions:**
- If H1 confirmation requires 1-2 week re-upload time, is that acceptable? Or should H4 serve as an interim fix while H1 deployment proceeds?
- Should the 16.3-01 spike explicitly test H4 as part of its falsification protocol?

---

### Q2: Test Isolation — Ephemeral Test Store vs Upload to Production with Unique Markers

**Question:** SC2 requires testing the fix on 6 known-failing files "in isolated test context, not the production store." Should this use a separate ephemeral Gemini store, or upload test files to the production store with a unique naming prefix?

**Why it matters:** A separate store adds complexity (dynamic store switching in CLI) but guarantees zero contamination of the 1,749 sacred files. Test files in production pollute the store with test content.

**Options:**

**A. Ephemeral test store (`objectivism-library-retrieval-test`)**
- Create new store, upload 6 files with headers, run A7 queries, delete store
- Clean isolation; confirms dynamic store switching works
- Minor cost for indexing ~6-22 files
- _(Proposed by: Gemini Pro, Perplexity)_

**B. Test files in production store with unique prefix**
- Upload 6 test files as "TEST-Class-09-02.txt" to production store
- Run queries, verify, delete test files + store documents after
- Avoids creating additional stores; simpler setup
- Risk: may interfere with real user searches during test window
- _(Not recommended by either provider)_

**Synthesis recommendation:** ✅ **Option A — ephemeral test store**

---

## Tier 2: Important Decisions (⚠️ Recommended)

### Q3: Metadata Header Format — Structured vs Narrative vs Hybrid

**Question:** What exact format should the metadata header use to maximize Gemini embedding quality?

**Why it matters:** Gemini uses semantic embeddings. JSON/CSV formats may be tokenized as syntax rather than semantic content. The header format determines whether the class number and topic actually participate in the embedding space.

**Options:**

**A. Structured header**
```
--- DOCUMENT METADATA ---
Title: Objectivist Logic - Class 09-02
Course: Objectivist Logic
Class: 09-02
Topic: epistemology
Tags: concept_formation induction logic objective_reality
--- TRANSCRIPT ---
[transcript]
```

**B. Narrative sentence**
```
This is a recording of Objectivist Logic, Class 09-02, on the topic of epistemology
covering concept formation, induction, logic, and objective reality.

[transcript]
```

**C. Hybrid (structured + narrative)**
```
--- DOCUMENT METADATA ---
Title: Objectivist Logic - Class 09-02
Topic: epistemology — concept_formation, induction, logic, objective_reality
--- TRANSCRIPT ---
[transcript]
```
- _(Proposed by: Perplexity as optimal balance)_

**Synthesis recommendation:** ⚠️ **Option A for testability; switch to C if A underperforms in SC2 testing.** SC2 will compare formats empirically.

**Sub-questions:**
- Should `primary_topics` from SQLite (8 tags) or `scanner topic` (1 tag) drive the header? (Use both: scanner topic as "Topic:", primary_topics as "Tags:")
- Max header length: ~200 tokens (Perplexity) or ~100 tokens (keep it minimal)?

---

### Q4: A7 Success Threshold — Top-5 vs Top-10

**Question:** After the H1 fix, what rank position should A7 require for a file to be considered "retrieved"?

**Why it matters:** Top-1 is fragile (Gemini ranking has documented volatility). Top-10 is too permissive. The existing A7 uses `top_k=20` sampling. The threshold should balance reliability with genuine retrievability.

**Options:**

**A. Top-5 threshold**
- File must appear in positions 1-5 of search results
- Stricter, closer to real user experience (users read first results)
- _(Proposed by: Gemini Pro)_

**B. Top-10 threshold**
- File must appear in positions 1-10 of search results
- More forgiving of ranking noise; top_k=20 requests are already made
- _(Proposed by: Perplexity implicitly via "not top-ranked" fallback)_

**C. Top-1 with retry logic (3 attempts)**
- Retry if file not in top-1 on first query, up to 3 attempts with 5s delay
- Tests ideal behavior; retry absorbs transient noise
- _(Neither provider; synthesis option)_

**Synthesis recommendation:** ⚠️ **Option B (Top-10) for A7 assertion; it aligns with existing top_k=20 and allows for ranking volatility documented in Phase 15**

---

### Q5: Production Re-upload Batch Size and Sequence

**Question:** For the 16.3-03 production remediation pass, what batch size and deletion sequence should be used to re-upload ~454 Category A+B files safely?

**Why it matters:** Previous uploads accumulated 2,038 orphaned store documents (see MEMORY.md). The root cause was `delete_file()` called without `delete_store_document()`. This must not recur.

**Options:**

**A. Delete-first sequence: Delete store doc → Upload new → Add to store → Update SQLite**
- Simpler; no temporary duplicates in store
- If upload fails after delete, file is gone from store (data loss risk)

**B. Upload-first sequence: Upload new → Add to store → Verify → Delete old store doc → Delete old file → Update SQLite**
- No data loss risk (old file remains until new is verified)
- Temporary duplicate in store during operation window
- _(Proposed by: Gemini Pro as preferred)_

**Synthesis recommendation:** ⚠️ **Option B (Upload-first) — consistent with write-ahead intent pattern already proven in Phases 10-12; batch size 10 files with 3-second delays between batches**

---

## Tier 3: Polish Decisions (🔍 Can defer to implementation)

### Q6: Header Scope — Category A+B Only vs All 1,749 Files

**Question:** Should metadata headers be applied only to the ~454 failing Category A+B files, or standardized across all 1,749 files?

**Synthesis recommendation:** 🔍 **Category A+B only (surgical).** Modifying all 1,749 files risks changing chunk boundaries for the 1,295 files that currently work. The upside (standardization) is insufficient to justify the risk at this stage. Can be revisited in a future "standardize pipeline" phase if desired.

---

### Q7: SC4 Freshness Gap — 1 Hour vs 24 Hours

**Question:** SC4 requires two consecutive fresh-session A7=0 runs "separated by at least 1 hour." Should the gap be 1 hour (current protocol) or 24 hours (Perplexity recommendation)?

**Synthesis recommendation:** 🔍 **1 hour is sufficient for this check.** The SC4 gap tests ranking stability after re-upload, not temporal drift like Phases 12/15 temporal stability protocol. 1 hour clears any transient caching; 24 hours adds unnecessary latency to the phase gate. The `--sample-count 20` run takes ~5 minutes, so two runs with a 1-hour gap completes in ~70 minutes.

---

## Next Steps (YOLO Mode — Auto-generating Answers)

Since `--yolo` flag was passed, proceeding to auto-generate CLARIFICATIONS-ANSWERED.md using synthesis recommendations.

---

*Multi-provider synthesis: Gemini Pro + Perplexity Sonar Deep Research*
*Generated: 2026-02-24*
*OpenAI gpt-5.2: query timed out — 2-provider synthesis applied*
