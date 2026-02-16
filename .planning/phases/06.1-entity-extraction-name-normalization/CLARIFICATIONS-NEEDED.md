# CLARIFICATIONS-NEEDED.md

## Phase 6.1: Entity Extraction & Name Normalization — Stakeholder Decisions Required

**Generated:** 2026-02-16
**Mode:** Multi-provider synthesis (OpenAI gpt-5.2, Gemini Pro)
**Source:** 2 AI providers analyzed Phase 6.1 requirements

---

## Decision Summary

**Total questions:** 15
**Tier 1 (Blocking):** 5 questions — Must answer before planning
**Tier 2 (Important):** 5 questions — Should answer for quality
**Tier 3 (Polish):** 5 questions — Can defer to implementation

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: Disambiguation Rules for Shared Surnames

**Question:** How should the system handle ambiguous surname mentions like "Smith" when multiple canonical people share that surname (Tara Smith, Aaron Smith)?

**Why it matters:** False attributions degrade search reliability and user trust. Mapping "Smith" to the wrong person is worse than missing the mention entirely.

**Options identified by providers:**

**A. Conservative Disambiguation (Recommended)**
- Block single-token surnames by default ("Smith" alone is rejected)
- Require full name OR instructor metadata match OR title+initial pattern
- Unresolved mentions logged as "ambiguous" for review
- Maintain explicit `blocked_alias` list for too-generic tokens
- _(Proposed by: OpenAI, Gemini)_

**B. Aggressive Matching with Post-Hoc Review**
- Accept single-token surnames with lower confidence (0.4)
- Use statistical corpus analysis to guess most likely person
- Flag low-confidence matches for manual review
- _(No provider recommended this)_

**C. Always Require Full Name**
- Never accept partial surnames, even with context
- Strictest approach, lowest false positives, highest false negatives
- _(No provider recommended this)_

**Synthesis recommendation:** ✅ **Option A (Conservative)**
- Prevents high-impact false positives that poison search facets
- Balances precision (no wrong attributions) with recall (catch most mentions)
- Aligns with user expectation: "Smith" is too generic without context

**Sub-questions:**
- Should "Tara" alone map to Tara Smith if no other Tara exists in corpus?
- Are there known non-canonical "Smith" references (e.g., Adam Smith in philosophy comparisons)?
- What's the tolerance for false positives vs false negatives in search UX?

---

### Q2: Extraction Engine Architecture

**Question:** Should entity extraction use deterministic fuzzy matching (Python libraries) or LLM-based extraction (Mistral API)?

**Why it matters:** Affects cost, speed, accuracy, and reproducibility. Running 1,600+ transcripts through LLMs is expensive and slow; deterministic matching is 100x faster but may miss context-dependent mentions.

**Options identified by providers:**

**A. Deterministic-First with Controlled LLM Fallback (Recommended)**
- Stage A: Exact match → Alias match → RapidFuzz fuzzy (≥92 threshold)
- Stage B: LLM fallback only for 80-91 fuzzy range with context validation
- Minimizes cost while handling tricky edge cases
- _(Proposed by: OpenAI, Gemini)_

**B. Pure Deterministic (No LLM)**
- RapidFuzz only, no LLM calls ever
- Fastest, cheapest, most reproducible
- May miss subtle context-dependent mentions
- _(Proposed by: Gemini as alternative)_

**C. LLM-First**
- Run all transcripts through Mistral for entity extraction
- Most accurate context understanding
- Expensive, slow, rate-limited, less reproducible
- _(No provider recommended this)_

**Synthesis recommendation:** ✅ **Option A (Deterministic-First)**
- Canonical list is small (15 names) and highly unique (Peikoff, Ghate, Binswanger)
- Most mentions will match deterministically (fast, free, reproducible)
- LLM fallback handles edge cases without blanket cost
- Temperature 0.1 for LLM ensures deterministic outputs

**Sub-questions:**
- What fuzzy matching threshold is acceptable? (92 vs 85 vs 80)
- Are LLM calls permitted given cost/privacy constraints?
- Should we use temperature 0.0 or 0.1 for LLM fallback?

---

### Q3: Output Data Model Structure

**Question:** What entity metadata should be stored in SQLite vs sent to Gemini File Search? Should we track mention counts, offsets, confidence, evidence samples?

**Why it matters:** Determines what search filters and analytics are possible. Gemini metadata has structure constraints (flat key-value, limited size); SQLite is flexible but only searchable locally.

**Options identified by providers:**

**A. Two-Tier Storage: SQLite Rich, Gemini Simplified (Recommended)**
- SQLite: `transcript_entity` table with counts, confidence, offsets, evidence samples
- Gemini: `mentioned_entities` as List[str] of canonical names only
- Enables Boolean search filtering (Gemini) + analytics (SQLite)
- _(Proposed by: OpenAI, Gemini)_

**B. Gemini-First with Counts**
- Store mention counts in Gemini metadata: `{"Ayn Rand": 15, "Peikoff": 2}`
- May complicate search filtering (how to query "mentions Peikoff"?)
- _(No provider recommended this)_

**C. SQLite-Only (No Gemini Metadata)**
- Store all entity metadata in SQLite
- Search filtering happens entirely in local DB, not Gemini
- Requires dual-query architecture (Gemini for semantic search, SQLite for entity filtering)
- _(No provider recommended this)_

**Synthesis recommendation:** ✅ **Option A (Two-Tier)**
- Gemini gets simple List[str] for clean filtering: `metadata.mentioned_entities: "Onkar Ghate"`
- SQLite stores counts/confidence for analytics and future features (highlighting, frequency analysis)
- Separation of concerns: Gemini for search, SQLite for rich metadata

**Sub-questions:**
- Do users need highlighted mentions in UI soon (requires offsets in SQLite)?
- Should we store confidence per transcript-person or per individual mention span?
- What's Gemini's character limit for metadata values? (If transcript mentions all 11, does it truncate?)

---

### Q4: Workflow Integration Point

**Question:** Where does entity extraction run in the pipeline? Is it a hard gate (fail upload if extraction fails) or graceful degradation (upload anyway with missing entities)?

**Why it matters:** Determines pipeline reliability and error handling. Hard gate ensures metadata consistency but may block uploads on transient failures. Graceful degradation keeps pipeline flowing but creates incomplete metadata.

**Options identified by providers:**

**A. Mandatory Pre-Upload Gate with Fail-One-Continue-Batch (Recommended)**
- Pipeline: Parse → Phase 6 metadata → **Phase 6.1 entities** → Validate → Upload
- If extraction fails: Mark `blocked_entity_extraction`, log error, skip file, continue batch
- If no entities found: Valid case (no canonical people mentioned), proceed
- _(Proposed by: OpenAI, Gemini)_

**B. Graceful Degradation (Upload Anyway)**
- Run extraction, but upload even if it fails
- Missing entity metadata better than no upload
- Risk: inconsistent search experience (some files filterable, others not)
- _(No provider recommended this)_

**C. Post-Upload Backfill Only**
- Don't block uploads, run entity extraction separately after
- Decouples pipelines but requires re-upload logic for Phase 6.2
- _(No provider recommended this)_

**Synthesis recommendation:** ✅ **Option A (Hard Gate)**
- Ensures metadata consistency: all uploaded files have entity metadata (or explicitly marked "none found")
- Fail-one-continue-batch prevents single bad file from blocking entire pipeline
- Clear error states for debugging and retry

**Sub-questions:**
- Should uploads proceed if entity extraction fails (degraded mode)?
- Do we re-run entity extraction when canonical aliases are updated?
- What retry policy for transient failures (disk unavailable, API timeout)?

---

### Q5: Backfill Strategy for Existing Files

**Question:** Should we retroactively extract entities for the 281+ files already processed in Phase 6, and if so, do we re-upload them to Gemini?

**Why it matters:** Phase 6 is complete for 281+ files. Adding Phase 6.1 creates a metadata gap: new uploads will have entity metadata, but existing uploads won't. This creates inconsistent search UX where only new uploads have entity filters.

**Options identified by providers:**

**A. Backfill SQLite Now, Re-Upload in Phase 6.2 if Needed (Recommended)**
- Run separate backfill job: `objlib extract entities --backfill`
- Extract entities from local files, write to SQLite
- Decision on re-upload deferred to Phase 6.2 based on Gemini indexing needs
- _(Proposed by: OpenAI, Gemini)_

**B. Backfill + Immediate Re-Upload**
- Extract entities AND re-upload all 281+ files to Gemini
- Ensures immediate consistency
- Expensive (time, API quota), may break existing file references
- _(No provider recommended this)_

**C. No Backfill (New Files Only)**
- Only apply entity extraction to new uploads going forward
- Leaves 281+ files without entity metadata
- Inconsistent UX: filters work on some files but not others
- _(No provider recommended this)_

**Synthesis recommendation:** ✅ **Option A (Backfill SQLite, Defer Re-Upload)**
- Backfill enables consistent local search/analytics immediately
- Re-upload decision based on: Does Gemini need entity metadata embedded in document?
- If Gemini only needs enriched metadata in Phase 6.2 for new uploads, backfill alone is sufficient
- Avoids expensive re-upload unless truly necessary

**Sub-questions:**
- Does Gemini File Search index need entity metadata embedded in uploaded document, or is SQLite the primary search DB?
- Is re-uploading 1,614 files acceptable (cost/time)?
- Should backfill be one-time migration or repeatable command?
- How to handle files where source disk is unavailable during backfill?

---

## Tier 2: Important Decisions (⚠️ Recommended)

### Q6: Canonical Entity Registry Schema

**Question:** Where should the canonical list of 15 names live? Hard-coded in Python, SQLite table, external YAML/JSON config? What identifiers (UUIDs vs human-readable slugs)?

**Why it matters:** Without stable IDs and versioned registry, normalized mentions can't be reliably stored, searched, or migrated. Alias management (nicknames, misspellings) requires structured storage.

**Options:**

**A. SQLite Tables with Human-Readable Slugs (Recommended)**
- Table `person`: `person_id` (slug: "ayn-rand"), `canonical_name` ("Ayn Rand"), `type`, notes, timestamps
- Table `person_alias`: `alias_text`, `person_id`, `alias_type`, `confidence_hint`
- Seed migration with 15 names + known aliases
- _(Proposed by: OpenAI)_

**B. Hard-Coded Python Dict**
- Simple, no migration needed
- Adding aliases requires code change + deployment
- _(Not recommended by providers)_

**Synthesis recommendation:** ⚠️ **Option A (SQLite Registry)**

**Sub-questions:**
- Use UUIDs or human-readable slugs (e.g., "ayn-rand") for person_id?
- Will canonical list expand beyond 15 names soon? Who approves changes?
- Need extra attributes (birth/death years, ARI role, external URLs)?

---

### Q7: "Mention" Definition Rules

**Question:** What text patterns count as valid mentions? Include speaker labels, possessives ("Rand's"), titles ("Dr. Peikoff"), initials ("LP")? Exclude pronouns?

**Why it matters:** Without clear rules, extraction may over-count (pronouns) or under-count (speaker labels, possessives). Affects mention frequency accuracy and user trust.

**Options:**

**A. Explicit Name/Alias Only (Recommended)**
- Include: Full names, surnames (when unambiguous), possessives, titles, speaker labels
- Exclude: Pronouns, generic references ("the philosopher")
- _(Proposed by: OpenAI)_

**Synthesis recommendation:** ⚠️ **Option A (Explicit Only)**

**Sub-questions:**
- Treat "Rand" alone as sufficient, or require "Ayn Rand"?
- Extract mentions from titles/headers if present?
- Handle references inside quoted text differently?

---

### Q8: State Management & Versioning

**Question:** How to track which extraction logic version was used per transcript? When to trigger reprocessing (alias updates, threshold changes)?

**Why it matters:** Updates to alias lists or matching thresholds produce inconsistent metadata across corpus without versioning. Need idempotency for safe retries.

**Options:**

**A. Extraction Version + Registry Version Fields (Recommended)**
- `entity_extraction_version` (semantic version: "6.1.0")
- `canonical_registry_version` (integer migration version)
- Idempotent UPSERT on `transcript_entity` table
- _(Proposed by: OpenAI)_

**Synthesis recommendation:** ⚠️ **Option A (Version Tracking)**

**Sub-questions:**
- What triggers reprocessing: code change, alias update, manual command?
- Keep historical entity results for audit, or only latest?
- Should reprocessing auto-re-upload to Gemini?

---

### Q9: Validation Rules

**Question:** What validation gates before persisting entity metadata? Minimum confidence threshold? How to handle empty results (valid or error)?

**Why it matters:** Prevents corrupted references (invalid person_ids), low-confidence garbage, and confusing empty result handling.

**Options:**

**A. Strict Pydantic Validation (Recommended)**
- `person_id` must exist in `person` table (FK)
- `mention_count >= 1`
- `confidence >= 0.5` (below 50% too uncertain)
- Empty results valid (transcript mentions no canonical people)
- _(Proposed by: OpenAI)_

**Synthesis recommendation:** ⚠️ **Option A (Strict Validation)**

**Sub-questions:**
- Minimum confidence threshold to store entity (0.5? 0.7?)?
- Show "no entities found" as warning in dashboards?
- Store "unknown person" mentions for later review?

---

### Q10: Library Choices & Determinism

**Question:** Which fuzzy matching library (RapidFuzz vs fuzzywuzzy vs difflib)? How to ensure reproducible results across environments?

**Why it matters:** Without pinned versions and deterministic settings, extraction results vary across environments, breaking regression tests and user trust.

**Options:**

**A. RapidFuzz Pinned Version + Deterministic Settings (Recommended)**
- Pin `rapidfuzz==3.6.1` in requirements.txt
- Use `token_set_ratio` scorer (order-independent)
- LLM temperature 0.1 (minimal randomness)
- Store `prompt_version` in results
- Regression test suite with gold set
- _(Proposed by: OpenAI, Gemini)_

**Synthesis recommendation:** ⚠️ **Option A (RapidFuzz + Determinism)**

**Sub-questions:**
- Strict reproducibility required, or "generally correct" acceptable?
- Automated regression tests with gold set of transcripts?
- Forbid LLM usage entirely to maximize determinism?

---

## Tier 3: Polish Decisions (🔍 Can Defer)

### Q11: Error Handling + Retries

**Question:** Retry policy for transient failures (API timeouts, rate limits) vs permanent failures (invalid transcript format)?

**Options:**
- Deterministic stages (file read, parsing, fuzzy matching): Never retry (local, fail fast)
- LLM fallback: Retry 2x with exponential backoff on 429/5xx/timeout
- Log errors to `error_log` table with full context

**Defer to implementation:** Can tune retry policy based on observed failure rates.

---

### Q12: Observability + Visibility

**Question:** What reporting for extraction results? CLI commands for review? Evidence samples stored?

**Options:**
- CLI reports: top persons, high entity counts, low-confidence matches
- Store `evidence_sample` (100-char snippet) in `transcript_entity`
- Export to CSV for manual audit

**Defer to implementation:** Add reporting when extraction running in production.

---

### Q13: Security + Authentication

**Question:** How to minimize data exposure when sending transcript snippets to LLM for disambiguation?

**Options:**
- Send only ±200 char context window (not full transcript)
- Redact emails/phone numbers with regex
- Store API keys in environment variables/keyring (already implemented)

**Defer to implementation:** Apply data minimization practices as standard.

---

### Q14: Search UX Semantics

**Question:** How to query entities in search? Filter by canonical name or alias? Show mention counts? Boost by frequency?

**Options:**
- Filter by person_id, auto-expand aliases to canonical
- Boost transcripts by mention_count when filtering by person
- Display canonical names + counts in results

**Defer to implementation:** Refine UX based on user feedback in Phase 5.

---

### Q15: Non-Canonical Entities

**Question:** Should we expand to philosophers mentioned in discussions (Kant, Aristotle, Plato, Nathaniel Branden)?

**Options:**
- Strict adherence to 15 names for Phase 6.1
- Architecture supports expansion via config file
- Plan Phase 6.3 for "Referenced Philosophers" category

**Defer to future:** Focus on canonical list now, expand later if valuable.

---

## Next Steps (Non-YOLO Mode)

**✋ PAUSED — Awaiting Your Decisions**

1. **Review these 15 questions** (5 blocking, 5 important, 5 polish)
2. **Provide answers** (create CLARIFICATIONS-ANSWERED.md manually, or tell Claude your decisions)
3. **Then run:** `/gsd:plan-phase 6.1` to create execution plan

---

## Alternative: YOLO Mode

If you want Claude to auto-generate reasonable answers:

```bash
/gsd:discuss-phase-ai 6.1 --yolo
```

This will:
- Auto-select recommended options (marked ✅ ⚠️ above)
- Generate CLARIFICATIONS-ANSWERED.md automatically
- Proceed to planning without pause

---

*Multi-provider synthesis: OpenAI gpt-5.2 + Gemini Pro*
*Generated: 2026-02-16*
*Non-YOLO mode: Human input required*
*Note: Perplexity provider unavailable (502 error)*
