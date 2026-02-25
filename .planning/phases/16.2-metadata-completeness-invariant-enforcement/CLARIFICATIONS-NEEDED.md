# CLARIFICATIONS-NEEDED.md

## Phase 16.2: Metadata Completeness Invariant Enforcement — Stakeholder Decisions

**Generated:** 2026-02-24
**Mode:** Multi-provider synthesis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research) + live DB queries
**Total questions:** 6
**Tier 1 (Blocking):** 4 questions
**Tier 2 (Important):** 2 questions

---

## Tier 1: Blocking Decisions

### Q1: What is the authoritative source for "primary_topics populated"?

**Question:** The system stores primary_topics in TWO places: `file_primary_topics` junction table AND `metadata_json` in `file_metadata_ai`. The 21 silent-pending .txt books have `file_metadata_ai` rows but ZERO `file_primary_topics` rows. Which table does the audit use as the pass/fail criterion?

**Why it matters:** If the audit checks `metadata_json`, it could falsely pass the 21 .txt books (they have metadata, just not topics). If it checks `file_primary_topics`, it correctly catches them as violations. The remediation path differs entirely between the two interpretations.

**Options:**

**A. file_primary_topics table (junction table)**
- Audit SQL: `EXISTS (SELECT 1 FROM file_primary_topics WHERE file_path = f.file_path)`
- Catches the 21 .txt books as violations
- Aligns with how search uses topics (via the join table)
- Requires fixing the 21 books before audit can pass
- _(All 3 providers either endorsed this or identified it as the cleaner approach)_

**B. metadata_json in file_metadata_ai**
- Audit SQL: `json_array_length(json_extract(m.metadata_json, '$.primary_topics')) > 0`
- Would NOT catch the 21 .txt books (they have metadata_json)
- Weaker invariant; doesn't detect silent insertion failures
- _(No provider recommended this; included for completeness)_

**Synthesis recommendation:** ✅ **Option A — file_primary_topics table**
- Rationale: Stronger invariant, catches real failures, aligns with search usage pattern

---

### Q2: What is the scope of the audit — 1885 DB files or 1748 .txt files only?

**Question:** The DB tracks 1885 files total (1748 .txt + 59 .pdf + 51 .other/docx + 26 .epub + 1 .md). The Gemini store has 1749 entries. Does the invariant apply to ALL 1885 DB-tracked files, or only to the 1748 Gemini-indexed .txt files?

**Why it matters:** The 110 pending non-txt files (.pdf, .docx) are currently silently excluded by `LIKE '%.txt'`. If scope is .txt-only, those files are permanently invisible to the audit (the silent bypass problem is not fixed). If scope is all-1885, the audit correctly flags them as needing classification.

**Options:**

**A. All 1885 DB-tracked files**
- Every file in the DB must satisfy the invariant
- Forces explicit classification of all 110 pending non-txt files
- True elimination of silent bypass
- _(All 3 providers recommended this approach)_

**B. Only 1748 Gemini-indexed .txt files**
- Non-txt files are outside scope (they can't be searched anyway)
- Simpler audit; the invariant is about searchability, not completeness
- Leaves .pdf/.docx silently pending forever — contradicts the phase goal
- _(No provider recommended this)_

**Synthesis recommendation:** ✅ **Option A — all 1885 DB-tracked files**
- Rationale: Option B merely perpetuates the silent bypass in a different dimension

---

### Q3: How are the 21 approved .txt book files (has metadata, no primary_topics rows) remediated?

**Question:** 21 approved .txt files have `file_metadata_ai` entries but zero `file_primary_topics` rows. Examples: Atlas Shrugged.txt, Fountainhead.txt, Objectivism PAOR.txt, etc. Three remediation paths exist:

**Options:**

**A. Backfill from existing metadata_json (preferred if topics are in JSON)**
- If `metadata_json->>'primary_topics'` is non-empty: INSERT rows from JSON into `file_primary_topics`
- No API call needed; no re-extraction; respects sacred metadata rule perfectly
- Only valid if the JSON contains the topic array (must be verified per-file)
- _(Gemini and Perplexity both proposed this as primary path)_

**B. Full re-extraction via batch-extract**
- Reset these 21 files to `pending`, include in next `batch-extract` run
- Uses Mistral Batch API; costs money; extracts fresh topics
- Needed if Option A finds the JSON has no topics
- _(OpenAI and Perplexity proposed as fallback)_

**C. Manually skip these .txt books (treat like the epub duplicates)**
- Mark as skipped with reason "book-length content: extraction deferred"
- Loses AI enrichment for major canonical Objectivist texts
- Not recommended; these should have topics
- _(No provider recommended; included for completeness)_

**Synthesis recommendation:** ✅ **Option A first, then Option B for any file where Option A finds no topics in JSON**
- Implementation: check `json_array_length(metadata_json->'$.primary_topics') > 0` per file; backfill if yes; re-extract if no

---

### Q4: How are MOTM and Other-stem files identified for the Phase 16.3 readiness row?

**Question:** The audit must report primary_topics coverage for MOTM files and Other-stem files specifically. MOTM and Other-stem are not stored as `category` values in `metadata_json` (top categories are course_transcript, qa_session, cultural_commentary). How are they identified?

**Why it matters:** If the identification logic is wrong, the readiness row will show the wrong denominator, and Phase 16.3 could start with an incorrect picture of the problem.

**Options:**

**A. File path pattern matching**
- `MOTM`: `file_path LIKE '%/MOTM/%'` (or the actual folder name in library path)
- `Other-stem`: Non-MOTM files where `topic` field ≈ filename stem (computed at audit time)
- Requires confirming the exact MOTM folder name during implementation
- _(OpenAI and Perplexity both recommended this; Gemini agreed if category column isn't available)_

**B. metadata_json category field**
- `MOTM`: `json_extract(metadata_json, '$.category') = 'MOTM'`
- But live DB shows no 'MOTM' category value — top values are course_transcript, qa_session, etc.
- Would require a scanner re-run to add MOTM category, touching sacred metadata
- _(Gemini proposed this but DB data contradicts it)_

**C. Phase 16.1 pre-categorized data**
- Use the Phase 16.1 triage output which identified the 440 Other-stem and 468 MOTM files
- Store as a fixed reference set; audit queries against this set
- Brittle if the corpus changes; requires external state
- _(No provider proposed; noted here as alternative)_

**Synthesis recommendation:** ✅ **Option A — file path pattern matching** (confirmed against live DB)
- Rationale: The metadata_json category field doesn't contain MOTM (Option B ruled out by DB evidence)

---

## Tier 2: Important Decisions

### Q5: Should the 26 skipped .epub files be the full list of skipped files, or should .pdf and .docx also be marked skipped first?

**Question:** Currently 26 .epub files are `skipped` (missing reason). 59 .pdf files and 51 .docx/other files are `pending`. Should 16.2-01 include a single backfill that marks ALL non-enrichable formats (epub + pdf + docx) as skipped in one pass, or should epub/pdf/docx be handled separately?

**Synthesis recommendation:** ⚠️ **Single backfill pass covering all non-enrichable formats**
- Rationale: Simpler; fewer commands; the Bernstein .md is the only non-.txt file that gets extracted, not skipped

---

### Q6: Should audit output include a machine-readable mode (JSON) for Phase 16.3 automation?

**Question:** OpenAI proposed a `--format json` flag for CI integration. Is this needed for Phase 16.2, or is human-readable Rich output sufficient?

**Synthesis recommendation:** ⚠️ **Rich text only for Phase 16.2**
- Rationale: Phase 16.3 uses check_stability.py for gating, not the audit command. Human-readable is sufficient for now; can add JSON in Phase 16.3 if needed.

---

## APPENDED: MOTM Discriminating Subject Concern (2026-02-24)

*Appended after user clarification: the Phase 16.3 problem of MOTM generic topics should be addressed here in Phase 16.2.*

---

### Q7: MOTM files have primary_topics but they are all generic — how does Phase 16.2 ensure they are Phase-16.3-ready? (Tier 1 — Blocking)

**Question:** 469 MOTM files pass the completeness check (468 have 8 primary_topics). But all primary_topics are generic Objectivism concepts (`epistemology | ethics | metaphysics | reason | values`). The specific session subject ("Immigration", "Libertarianism", "Axioms") is **absent from primary_topics AND from metadata_json** (all `metadata_json->>'topic'` values are NULL). It exists only in the filename slug.

Phase 16.3 needs to inject a discriminating metadata header per file into Gemini content. With generic-only topics, all 469 MOTM headers would be functionally identical — zero help for retrieval. Should Phase 16.2 be responsible for populating the discriminating subject field so Phase 16.3 has something to inject?

**Why it matters:** If Phase 16.2 ships without the topic backfill, Phase 16.3 either (a) parses filenames at injection time without a DB gate, or (b) tries to inject generic-only headers and the retrievability problem persists. The readiness gate should verify data readiness, not defer the data problem to Phase 16.3.

**Live DB confirmation:**
```
MOTM total files: 469
metadata_json->>'topic' populated: 0 (ALL NULL)
Filename slug pattern: MOTM_YYYY-MM-DD_Subject.txt → "Subject"
```

**Options:**

**A. ~~Phase 16.2 backfills metadata_json->>'topic' from filename slug~~ (REJECTED)**
- ~~Append-only JSON update; no existing keys touched~~
- REJECTED: violates the extraction-provenance invariant — heuristic slug injection produces fields indistinguishable from Mistral-extracted content but substantively weaker; creates silent two-tier metadata quality

**B. Phase 16.2 implements structural quality check + triggers Mistral re-extraction (SELECTED)**
- Define quality failure: `topic` NULL OR all primary_topics are corpus-generic boilerplate
- Reset quality-failed files to `ai_metadata_status='pending'`
- Run `batch-extract` — Mistral extracts real topic from transcript content, not from filename
- Audit readiness row gates on `metadata_json->>'topic'` populated from Mistral
- Identical to how all other files are handled — no special-casing
- _(Consistent with MEMORY.md: "ALWAYS use Mistral Batch API for extraction"; extraction-provenance invariant)_

**C. Phase 16.2 leaves topic NULL; Phase 16.3 parses filename at injection time**
- REJECTED: audit readiness row cannot gate on this; problem is invisible to phase gate

**Decision:** ✅ **Option B — structural quality check + Mistral re-extraction**
- Rationale: MOTM files with NULL topic represent an extraction quality failure; the correct fix is re-extraction, not workaround. All enrichable files must receive metadata from Mistral, not from heuristics.

---

## Next Steps

In **YOLO mode**, Q7 has been auto-answered. See CLARIFICATIONS-ANSWERED.md.

---

*Multi-provider synthesis: OpenAI gpt-5.2 + Gemini Pro + Perplexity Sonar Deep Research*
*Generated: 2026-02-24; Q7 appended 2026-02-24*
