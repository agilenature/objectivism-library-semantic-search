# CONTEXT.md — Phase 4: Quality Enhancements

**Generated:** 2026-02-17
**Phase Goal:** Search results are sharper (reranked for precision), answers synthesize across sources (with inline citations), and queries understand philosophical terminology — transforming raw search into a research tool
**Requirements:** ADVN-01, ADVN-02, ADVN-03, ADVN-04, ADVN-05, ADVN-06, ADVN-07
**Synthesis Source:** Multi-provider AI analysis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research)

---

## Overview

Phase 4 adds four major capabilities on top of the working Phase 3 search pipeline: (1) reranking for precision, (2) multi-document synthesis with inline citations, (3) query expansion for philosophical terminology, and (4) concept evolution tracking plus saved sessions. The providers identified significant ambiguity in architecture decisions, citation enforcement strategy, and data model design. All blocking decisions are surfaced below.

**Confidence markers:**
- ✅ **Consensus** — All 3 providers identified this as critical
- ⚠️ **Recommended** — 2 providers identified this as important
- 🔍 **Needs Clarification** — 1 provider identified, potentially important

---

## Gray Areas Identified

---

### ✅ 1. Reranking Model & Hosting Strategy (ADVN-02) — Consensus

**What needs to be decided:**
Which reranker to use (local cross-encoder vs LLM-based), where it runs, and what latency/cost budget is acceptable.

**Why it's ambiguous:**
Gemini File Search has no built-in reranking. ADVN-02 says "cross-encoder reranking" but doesn't specify model, deployment constraints, or acceptable latency. Two valid approaches exist: (a) local sentence-transformers (PyTorch) or (b) LLM-based listwise reranking using existing Gemini access.

**Provider synthesis:**
- **OpenAI:** Use local `cross-encoder/ms-marco-MiniLM-L-6-v2` on CPU, rerank top-50 → top-10, cache scores in SQLite. Prefers zero external API cost and single-user predictability.
- **Gemini:** Avoid PyTorch dependency entirely. Use LLM-based listwise reranking (Gemini Flash) to score and reorder passages. Lighter deployment, consistent with existing stack.
- **Perplexity:** Comprehensive analysis of MS-MARCO vs domain-fine-tuned vs LLM-based. Recommends LLM-based for philosophical domain (domain-specific terminology not well captured by generic cross-encoders trained on web data).

**Proposed implementation decision:**
Use **Gemini Flash as LLM-based reranker**. Send top-50 passages in a structured prompt asking Flash to rank them 1–10 for the query. Avoids adding PyTorch/sentence-transformers as a heavyweight dependency. Consistent with existing Gemini stack. Add `--rerank` flag (default: on). Cache reranked order in session events.

**Open questions:**
1. Is offline/local-only operation required, or is Gemini Flash API call acceptable per rerank?
2. Maximum acceptable latency for reranking step (before result display)?
3. Should reranking consider passage text only, or also metadata (difficulty, course)?

**Confidence:** ✅ All 3 providers agreed this is blocking

---

### ✅ 2. Multi-Document Synthesis Architecture (ADVN-03) — Consensus

**What needs to be decided:**
How to select 5–10 passages for synthesis, how to structure the prompt, whether synthesis is opt-in or default, and what to do when sources conflict or are insufficient.

**Why it's ambiguous:**
"Synthesized answers from 5–10 passages" doesn't define passage selection rules, output format, length, contradiction handling, or whether synthesis replaces or supplements the current excerpt display.

**Provider synthesis:**
- **OpenAI:** Deterministic pipeline: Gemini retrieval (top-50) → rerank → top-10 → MMR-style diversity (max 2 passages per file, prefer distinct weeks/lectures). Synthesis as structured JSON with `answer` + `claims[]`. Falls back to excerpts if fewer than 5 usable passages.
- **Gemini:** Synthesis should be opt-in via `--synthesize` flag. Recommends generate-then-cite approach where answer is generated holistically, then passages are matched to claims post-hoc.
- **Perplexity:** Structured extraction preferred over generate-then-cite for citation integrity. Recommends generation-with-citation-guidance where model is constrained to reference specific passage IDs inline.

**Proposed implementation decision:**
`--synthesize` is opt-in flag on `search` command. Pipeline: retrieve top-50 → rerank → apply MMR-style diversity filter (max 2 per file) → submit top 5–10 to Gemini Flash for claim-level synthesis. If fewer than 5 passages available, return "insufficient sources" and fall back to excerpt display. Answer length target: 150–300 words.

**Open questions:**
1. Should synthesis be the default output of `search`, or always opt-in via `--synthesize`?
2. How should contradictions between sources be presented: merged narrative, "Source A vs B", or by recency?
3. What is the target answer length (150–300 words, or long-form)?

**Confidence:** ✅ All 3 providers agreed this is blocking

---

### ✅ 3. Inline Citation Enforcement (ADVN-04) — Consensus

**What needs to be decided:**
What counts as a "claim," what "with quote" means (verbatim length?), how strictly to validate citations, and how to handle LLM-generated connective text.

**Why it's ambiguous:**
ADVN-04 says "every claim traces to source passage with quote" — this is strict but LLMs naturally produce uncited bridging sentences. Needs enforcement strategy and fallback.

**Provider synthesis:**
- **OpenAI:** Force bullet-claims only, each with: `claim_text` (1 sentence) + `citation` (file_id, passage_id, quote 20–60 words). Python post-validation: verify quote is substring of passage text (normalized). Re-prompt once on failure; if still failing, return excerpts only. Prevents silent hallucinations.
- **Gemini:** Verify-quote prompt strategy: prompt instructs model to include exact quoted evidence in each claim. Validation layer in Python checks quotes against source texts. Anti-hallucination approach.
- **Perplexity:** Structured extraction is more reliable than generation-with-citation-guidance. Recommends a two-pass approach: generate synthesis, then extract and verify citation evidence separately.

**Proposed implementation decision:**
Claim-level structured output enforced via Pydantic model. Each claim: `{claim_text: str, citation: {file_id, passage_id, quote: str (20–60 words)}}`. Python post-validation: quote must be exact substring of stored passage text (after whitespace normalization). On validation failure: re-prompt once with error list. If still failing: return labeled excerpts with source attribution (no synthesized claims). Short "bridging" sentences (transitions) are allowed uncited if they contain no factual assertions.

**Open questions:**
1. Should bridging/transition sentences be allowed uncited, or must everything be claim bullets?
2. Is exact-quote substring matching acceptable, or should fuzzy/approximate match be allowed?
3. Should citations reference stable `passage_id`s or `file_id + quote` (less infrastructure)?

**Confidence:** ✅ All 3 providers agreed this is blocking

---

### ✅ 4. Query Expansion Source of Truth (ADVN-05) — Consensus

**What needs to be decided:**
Where synonym mappings come from (manual glossary vs LLM-generated vs corpus-derived), how to prevent expansion from harming precision, and whether expansion is opt-in or default.

**Why it's ambiguous:**
Expanding philosophical terms risks introducing wrong equivalences (e.g., "reason" ≠ "rationalism"). No source of truth is specified. The project already has a rich controlled vocabulary from Phase 6 metadata.

**Provider synthesis:**
- **OpenAI:** Curated, versioned local glossary (`synonyms.yml`). Expand top 1–3 synonyms per term. Show expanded query in CLI. `--no-expand` to disable. `glossary suggest <term>` uses LLM to propose synonyms, requires manual acceptance. Avoids silent semantic drift.
- **Gemini:** LLM-based query pre-processing (Gemini Flash) over static dictionary. More flexible, can handle novel phrasings. Expansion done before the main search.
- **Perplexity:** Ontology-based expansion using established philosophical ontologies (SEP, PhilPapers taxonomy) vs embedding-based expansion. Recommends hybrid: static Objectivist glossary + embedding similarity for discovery.

**Proposed implementation decision:**
Curated `synonyms.yml` glossary shipped with the project. Seed with ~50 core Objectivist terms (altruism → selflessness/sacrifice; epistemology → theory of knowledge/cognition; rational self-interest → egoism/selfishness/prudence; etc.). Expansion automatic by default, `--no-expand` to disable. Show expanded terms in CLI output (transparent). Add `glossary suggest <term>` command for LLM-assisted discovery requiring user acceptance before writing to YAML. Limit expansion to top 2 synonyms per term.

**Open questions:**
1. Should expansion be automatic by default or opt-in?
2. Should single terms expand (e.g., "reason"), or only multi-word phrases?
3. Should expanded terms be weighted lower than the original (boost original)?

**Confidence:** ✅ All 3 providers agreed this is blocking

---

### ✅ 5. Session Data Model & Semantics (ADVN-07) — Consensus

**What needs to be decided:**
What a "session" contains, whether snapshots or live reruns are used on resume, storage location, and the session lifecycle (start/stop/name/export).

**Why it's ambiguous:**
"Saved searches and research sessions with resume capability" doesn't specify granularity (query log vs full result snapshot), mutability (append-only vs editable), or behavior when library index changes between save and resume.

**Provider synthesis:**
- **OpenAI:** SQLite-backed append-only event log. Tables: `sessions(session_id, name, created_at, last_opened_at)` + `session_events(event_id, session_id, type, payload_json, created_at)`. Event types: search, open_result, synthesize, note. Snapshot semantics (store doc_ids + passage_ids). Resume = timeline replay; explicit "rerun" creates a new event.
- **Gemini:** sessions + session_items tables with snapshot strategy. Separate metadata from content (passage cache).
- **Perplexity:** Recommends SQLite over file-based. Hybrid approach where queries are stored but results can be re-run. Redis considered for performance but unnecessary for single-user CLI.

**Proposed implementation decision:**
SQLite-backed in existing `library.db`. Tables: `sessions` (id, name, created_at, updated_at) + `session_events` (id, session_id, event_type, payload_json, created_at). Event types: `search`, `view`, `synthesize`, `note`. Snapshot semantics: store query text, expanded query, result doc_ids, passage_ids, synthesis output. `resume` replays timeline display; user can explicitly trigger rerun. Append-only (no editing). Export to Markdown via `session export <id>`. Commands: `session start [name]`, `session list`, `session resume <id>`, `session note <text>`, `session export <id>`.

**Open questions:**
1. Should sessions be append-only or allow item deletion?
2. Should `session resume` automatically rerun searches, or just display the saved timeline?
3. Is Markdown export required, or is read-only replay sufficient?

**Confidence:** ✅ All 3 providers agreed this is blocking

---

### ⚠️ 6. Concept Evolution Definition & UX (ADVN-01) — Recommended

**What needs to be decided:**
What "concept evolution" means operationally and how to present it in the CLI.

**Why it's ambiguous:**
"Show how concepts develop from intro to advanced" could mean pedagogical progression (difficulty ladder), chronological (year/week), conceptual dependency graph, or semantic drift across texts. The `--track-evolution` flag UX is undefined.

**Provider synthesis:**
- **OpenAI:** Pedagogical progression view using existing metadata. Group by: difficulty (intro/intermediate/advanced), then year/quarter/week within each. Display 3 key passages per difficulty level. New `concept_track <term>` command.
- **Perplexity:** Concept evolution via topological sorting on prerequisite DAG (more sophisticated, requires inferring prerequisite relationships). Potentially built on top of Phase 6 topic metadata.
- **Gemini:** Not explicitly addressed.

**Proposed implementation decision:**
Pedagogical progression using existing metadata — no new prerequisite graph inference needed. `--track-evolution` flag on `search` command groups results by `difficulty` → `year/week`. Display format: difficulty tiers (Introductory / Intermediate / Advanced) each showing top 3 passages with metadata. Single synthesized sentence per tier (via Gemini Flash, opt-out with `--no-synthesis`).

**Open questions:**
1. Is "evolution" primarily pedagogical (difficulty tiers) or chronological (year order)?
2. Should track-evolution generate a synthesis per tier, or just curated excerpts?
3. Do users want a standalone `concept_track` command, or is `search --track-evolution` sufficient?

**Confidence:** ⚠️ 2 providers identified this as important

---

### ⚠️ 7. Difficulty-Aware Ordering Precedence (ADVN-06) — Recommended

**What needs to be decided:**
How to combine difficulty ordering with semantic relevance when they conflict, and what the default user experience should be.

**Why it's ambiguous:**
"Surface introductory explanations first for learning" (ADVN-06) conflicts with "sharper results via reranking" (ADVN-02). Pure difficulty-first can bury the best semantic match; pure relevance-first ignores learning intent.

**Provider synthesis:**
- **OpenAI:** Two-stage: compute relevance rank, then apply difficulty boost within top-20 relevance window. `--mode learn` (default, intro-first) vs `--mode research` (pure relevance). Preserves precision while meeting learning UX.
- **Gemini:** Tiered bucketing: sort results into difficulty-relevance buckets (intro-high, intro-medium, intermediate-high, etc.) and display bucket by bucket.
- **Perplexity:** (Addressed implicitly in reranking discussion.)

**Proposed implementation decision:**
Two-stage ordering: (1) full semantic relevance rank, (2) difficulty-aware reorder within top-20 window by `(difficulty_bucket, rerank_score)`. Default mode: `--mode learn` (intro-first boost active). Alternative: `--mode research` (pure relevance). Mode is per-command, no session-level memory in Phase 4.

**Open questions:**
1. Should `--mode learn` be the default, or should pure relevance be default?
2. Should the system infer mode from query phrasing ("what is X" → learn; "compare X and Y" → research)?
3. Is 3-level difficulty (intro/intermediate/advanced) granular enough?

**Confidence:** ⚠️ 2 providers identified this as important

---

### 🔍 8. Passage Identity & Stable IDs — Needs Clarification

**What needs to be decided:**
How passages returned by Gemini grounding are identified, persisted, and referenced stably across reindexing.

**Why it's ambiguous:**
Inline citations (ADVN-04) and session resume (ADVN-07) both need stable passage references. Gemini returns `grounding_chunks` per query but doesn't provide stable passage IDs across queries. No persistence strategy is defined.

**Provider synthesis:**
- **OpenAI:** New `passages` table in SQLite. UUID-based `passage_id`. Columns: `passage_id`, `file_id`, `content_hash`, `passage_text`, `created_at`, `is_stale`. Upsert on each search response. If file changes (content_hash mismatch), mark old passage stale but preserve for session replay.
- **Gemini/Perplexity:** Not explicitly addressed (addressed implicitly through citation architecture).

**Proposed implementation decision:**
Add `passages` table to existing `library.db`. When search returns grounding chunks, normalize and upsert into `passages`. UUID-based `passage_id` stable across queries for same content. Content-hash change marks existing passage `is_stale=True` but preserves it for session replay. Citations store `passage_id` references.

**Open questions:**
1. How much storage growth is acceptable for a cumulative passage cache over time?
2. Should stale passages be garbage-collected (e.g., after 30 days)?

**Confidence:** 🔍 1 provider explicitly identified this

---

### 🔍 9. Error Handling & Graceful Degradation — Needs Clarification

**What needs to be decided:**
What happens when individual pipeline stages fail (reranker, synthesis, citation validation) and how failures propagate to the user.

**Why it's ambiguous:**
Phase 4 adds multiple dependent steps (search → rerank → select → synthesize → validate). Without defined failure policy, UX becomes unpredictable.

**Provider synthesis:**
- **OpenAI:** Consistent degradation: reranker failure → skip to Gemini order; synthesis validation failure → fall back to excerpts; store failures in session events; `--debug` for structured logs.
- **Gemini/Perplexity:** Not explicitly addressed.

**Proposed implementation decision:**
Graceful degradation at each stage. Gemini search failure: retry 3× with exponential backoff (2s, 4s, 8s), then fail with actionable message. Reranker failure: warn user ("Reranking unavailable, showing Gemini ranking") and continue. Synthesis failure/validation failure: show labeled excerpts with clear attribution. All failures logged in session event if a session is active.

**Confidence:** 🔍 1 provider explicitly identified this

---

## Summary: Decision Checklist

Before planning, confirm:

**Tier 1 (Blocking — must decide):**
- [x] Reranking model: Gemini Flash LLM-based (no PyTorch)
- [x] Synthesis: opt-in `--synthesize` flag, MMR diversity, structured claim output
- [x] Citations: claim-level with Python post-validation (exact quote substring)
- [x] Query expansion: `synonyms.yml` glossary, automatic, `--no-expand` opt-out
- [x] Session model: SQLite event log, snapshot semantics, append-only

**Tier 2 (Important — shapes UX):**
- [x] Concept evolution: pedagogical progression by difficulty tier + year/week
- [x] Difficulty ordering: two-stage with relevance window + difficulty boost, `--mode learn/research`

**Tier 3 (Infrastructure):**
- [x] Passage cache: `passages` table in library.db, UUID-based stable IDs
- [x] Error handling: graceful degradation at each stage, `--debug` flag

---

## Next Steps (YOLO Mode)

YOLO mode active — auto-answers generated in CLARIFICATIONS-ANSWERED.md.
Proceeding to `/gsd:plan-phase 4`.

---

*Multi-provider synthesis by: OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research*
*Generated: 2026-02-17*
*YOLO mode: Auto-answers generated*
