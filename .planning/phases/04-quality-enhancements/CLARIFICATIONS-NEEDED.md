# CLARIFICATIONS-NEEDED.md

## Phase 4: Quality Enhancements — Stakeholder Decisions Required

**Generated:** 2026-02-17
**Mode:** Multi-provider synthesis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research)
**Source:** 3 AI providers analyzed Phase 4 requirements

---

## Decision Summary

**Total questions:** 9 gray areas → 27 sub-questions
**Tier 1 (Blocking):** 5 gray areas — Must answer before planning
**Tier 2 (Important):** 2 gray areas — Should answer for quality
**Tier 3 (Polish):** 2 gray areas — Can defer to implementation

---

## Tier 1: Blocking Decisions (✅ Consensus)

---

### Q1: Reranking Model & Hosting (ADVN-02)

**Question:** Should reranking use Gemini Flash (LLM-based, no new deps) or a local cross-encoder (PyTorch, offline)?

**Why it matters:** Every search result order depends on this. Adds latency and cost per query. Determines whether PyTorch/sentence-transformers enters the dependency tree.

**Options identified by providers:**

**A. Gemini Flash LLM-based reranking**
- Send top-50 passages to Gemini Flash in a single structured prompt; Flash ranks them 1–10
- No new dependencies; consistent with existing stack; domain-aware (LLM understands philosophical terminology)
- Costs ~1 additional Gemini Flash call per search; ~0.5–2s latency
- _(Proposed by: Gemini Pro, Perplexity)_

**B. Local cross-encoder (sentence-transformers ms-marco-MiniLM-L-6-v2)**
- Runs entirely on CPU, zero API cost, no external calls
- Adds ~150MB PyTorch/sentence-transformers dependency
- Generic (trained on web QA, not philosophy) — may miss philosophical nuance
- _(Proposed by: OpenAI)_

**Synthesis recommendation:** ✅ **Option A — Gemini Flash**
- Rationale: project already uses Gemini exclusively; no new heavy deps; LLM reranker understands Objectivist terminology better than generic cross-encoder

**Sub-questions:**
- Q1a: Is offline-only operation a hard requirement, or is a Gemini API call per rerank acceptable?
- Q1b: Maximum acceptable latency for reranking step before results display? (1s? 3s? 5s?)
- Q1c: Should reranking consider metadata (difficulty, course) alongside passage text?

---

### Q2: Multi-Document Synthesis Architecture (ADVN-03)

**Question:** Should synthesis be opt-in (--synthesize flag) or the default output of `search`?

**Why it matters:** Default vs opt-in determines the UX contract for every search. Synthesis adds latency and cost; making it default changes the core search experience.

**Options identified by providers:**

**A. Opt-in via `--synthesize` flag**
- Default search returns the current excerpt display; `--synthesize` triggers the synthesis pipeline
- Users who want raw results get them; power users get synthesis on demand
- Lower default latency and cost
- _(Proposed by: Gemini Pro)_

**B. Synthesis as default output**
- Every search produces a synthesized answer with citations
- Simpler UX (one output format)
- Higher latency and cost per query
- _(Proposed by: OpenAI, implicitly)_

**Synthesis recommendation:** ✅ **Option A — opt-in `--synthesize`**
- Rationale: current excerpt display is already useful; synthesis should be a power feature

**Sub-questions:**
- Q2a: When synthesizing, should contradictions between sources be: (1) merged narrative, (2) "Source A says X, Source B says Y", or (3) most recent/advanced source wins?
- Q2b: Target answer length: 150–300 words, or long-form (no cap)?
- Q2c: Minimum passages required before synthesis triggers (proposed: 5)?

---

### Q3: Inline Citation Enforcement (ADVN-04)

**Question:** How strictly should every claim be enforced to trace to a quoted source?

**Why it matters:** Strict enforcement (exact-quote validation) prevents hallucinations but increases complexity and may reject valid paraphrases. Loose enforcement risks uncited claims.

**Options identified by providers:**

**A. Strict: exact-quote substring validation**
- Each claim must include a 20–60 word verbatim excerpt from the passage
- Python validates the quote is an exact substring of stored passage text (after whitespace normalization)
- Re-prompt once on failure; fall back to excerpts if still failing
- _(Proposed by: OpenAI)_

**B. Structured output with post-hoc citation matching**
- Generate synthesis holistically, then match claims to source passages in a second LLM pass
- More flexible for paraphrases; slightly less strict on verbatim quotes
- _(Proposed by: Gemini Pro)_

**Synthesis recommendation:** ✅ **Option A — exact-quote validation**
- Rationale: strict enforcement aligns with ADVN-04's "every claim traces to quoted source"; prevents hallucinations in philosophical attribution

**Sub-questions:**
- Q3a: Should "bridging sentences" (transitions between claims) be allowed uncited?
- Q3b: If exact-quote validation fails after one re-prompt, should the command fail with error or silently fall back to excerpts?
- Q3c: Should citations reference stable `passage_id` (requires passages table) or just `file_id + quote`?

---

### Q4: Query Expansion Source of Truth (ADVN-05)

**Question:** Should query expansion use a curated static glossary or LLM-based dynamic expansion?

**Why it matters:** Wrong synonym expansion silently degrades precision (e.g., "reason" → "rationalism" is philosophically wrong in Objectivist context). Source of truth determines who controls expansion quality.

**Options identified by providers:**

**A. Curated `synonyms.yml` glossary (versioned, in-repo)**
- Ship with ~50 core Objectivist terms seeded (altruism, rational self-interest, epistemology, etc.)
- Expansion automatic by default; `--no-expand` to disable
- `glossary suggest <term>` uses LLM to propose additions, requires manual acceptance to write to YAML
- _(Proposed by: OpenAI)_

**B. LLM-based dynamic expansion (Gemini Flash)**
- Gemini Flash generates synonyms at query time
- More flexible, handles novel phrasings
- Risk: LLM may suggest philosophically inaccurate equivalences for Objectivist terms
- _(Proposed by: Gemini Pro)_

**Synthesis recommendation:** ✅ **Option A — curated `synonyms.yml`**
- Rationale: philosophical terminology precision is critical; human-controlled glossary prevents LLM from conflating Objectivist terms with their common usages

**Sub-questions:**
- Q4a: Should expansion be automatic by default, or opt-in?
- Q4b: Should single terms expand (e.g., "pride"), or only multi-word phrases?
- Q4c: Should original query term be weighted higher than synonyms in Gemini query?

---

### Q5: Session Data Model & Resume Semantics (ADVN-07)

**Question:** Should session resume replay a saved timeline (snapshot) or automatically rerun searches against the live index?

**Why it matters:** Snapshot semantics preserve original results even if library changes; live rerun always shows current results but may change what the user remembers seeing.

**Options identified by providers:**

**A. Snapshot semantics (append-only event log)**
- Store all queries, result doc_ids, passage_ids, synthesis output at search time
- Resume displays the saved timeline; rerun is an explicit user action creating a new event
- Results are reproducible even if library changes
- _(Proposed by: OpenAI, Gemini Pro)_

**B. Live rerun on resume**
- Store queries only; re-execute against live Gemini index on resume
- Always shows current results; simpler storage (no passage snapshots)
- Results may change between save and resume
- _(Proposed by: implicitly, simpler approach)_

**Synthesis recommendation:** ✅ **Option A — snapshot semantics**
- Rationale: research continuity depends on seeing what you saw before; live rerun breaks that

**Sub-questions:**
- Q5a: Should sessions be append-only, or allow item deletion?
- Q5b: Should `session resume` auto-rerun searches, or only display the saved timeline?
- Q5c: Is Markdown export required (`session export`), or is on-screen replay sufficient?

---

## Tier 2: Important Decisions (⚠️ Recommended)

---

### Q6: Concept Evolution Definition (ADVN-01)

**Question:** Is "concept evolution" pedagogical (difficulty tiers) or chronological (year/week)?

**Why it matters:** Determines what `--track-evolution` shows. Pedagogical grouping uses existing difficulty metadata. Chronological requires consistent year/week metadata (may have gaps).

**Options identified by providers:**

**A. Pedagogical progression (difficulty tiers)**
- Group results: Introductory → Intermediate → Advanced
- Uses existing difficulty metadata (already extracted in Phase 6)
- `--track-evolution` reorders the standard result set into three labeled tiers
- _(Proposed by: OpenAI)_

**B. Chronological progression (year → quarter → week)**
- Order by actual lecture timeline across the curriculum
- More historically accurate; useful for tracing how Peikoff's teaching evolved
- Requires consistent year/week metadata (some files may lack it)
- _(Proposed by: implicitly)_

**Synthesis recommendation:** ⚠️ **Option A — pedagogical progression**
- Rationale: difficulty metadata is richer and more consistent; chronological order is secondary for a learning tool

**Sub-questions:**
- Q6a: Should `--track-evolution` produce synthesized summaries per tier, or just curated excerpts?
- Q6b: Should there be a standalone `concept_track` command, or is `search --track-evolution` sufficient?

---

### Q7: Difficulty-Aware Ordering Precedence (ADVN-06)

**Question:** When difficulty ordering and semantic relevance conflict, which wins?

**Why it matters:** If intro results rank 15th by relevance but must appear first, the user may see lower-quality introductory excerpts before higher-quality advanced ones.

**Options identified by providers:**

**A. Two-stage: relevance window + difficulty boost**
- Compute full relevance rank; then within top-20 window, reorder by (difficulty_bucket, rerank_score)
- `--mode learn` (default) vs `--mode research` (pure relevance)
- _(Proposed by: OpenAI)_

**B. Tiered bucketing**
- Group results into difficulty-relevance buckets (intro-high, intro-medium, etc.); display tier by tier
- More predictable UX; shows intro-high before intro-medium before intermediate-high, etc.
- _(Proposed by: Gemini Pro)_

**Synthesis recommendation:** ⚠️ **Option A — two-stage ordering**
- Rationale: preserves precision while adding learning UX; --mode flags provide user control

**Sub-questions:**
- Q7a: Should `--mode learn` or `--mode research` be the default?
- Q7b: Should the mode be inferred from query phrasing ("what is X" → learn)?

---

## Tier 3: Polish Decisions (🔍 Needs Clarification)

---

### Q8: Passage Identity & Stable IDs

**Question:** Should passage text be persisted in a local SQLite cache with stable UUIDs?

**Why it matters:** Inline citations (Q3) and session resume (Q5) need stable passage references. Without persistence, passage IDs from one query may not match another query.

**Synthesis recommendation:** 🔍 **Yes — add `passages` table to library.db**
- passage_id (UUID), file_id, content_hash, passage_text, created_at, is_stale
- Upsert on each search; mark stale on content_hash mismatch, preserve for session replay

**Sub-questions:**
- Q8a: Should stale passages be garbage-collected (e.g., older than 90 days with no session references)?

---

### Q9: Error Handling & Graceful Degradation

**Question:** When pipeline stages fail (reranker, synthesis, validation), should the command fail loudly or degrade gracefully?

**Synthesis recommendation:** 🔍 **Graceful degradation**
- Reranker failure: warn and show Gemini ranking
- Synthesis validation failure: show labeled excerpts
- `--debug` flag for structured logs

**Sub-questions:**
- Q9a: Should degradation be noisy (prominent warning) or quiet (footnote)?

---

## Next Steps (YOLO Mode Active)

YOLO mode is enabled — auto-answers generated in CLARIFICATIONS-ANSWERED.md using synthesis recommendations.

---

*Multi-provider synthesis: OpenAI gpt-5.2 + Gemini Pro + Perplexity Sonar Deep Research*
*Generated: 2026-02-17*
*YOLO mode: Auto-answers will be generated*
