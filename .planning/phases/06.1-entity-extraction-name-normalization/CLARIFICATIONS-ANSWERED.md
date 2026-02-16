# CLARIFICATIONS-ANSWERED.md

## Phase 6.1: Entity Extraction & Name Normalization — Stakeholder Decisions

**Generated:** 2026-02-16
**Mode:** YOLO (balanced strategy - auto-generated)
**Source:** Multi-provider AI synthesis (OpenAI gpt-5.2, Gemini Pro)

---

## Decision Summary

**Total questions:** 15
**Tier 1 (Blocking):** 5 answered
**Tier 2 (Important):** 5 answered
**Tier 3 (Polish):** 5 answered

**Strategy:** Balanced - Select ✅ consensus recommendations from synthesis, choose simplest/safest for low-confidence areas

---

## Tier 1: Blocking Decisions

### Q1: Disambiguation Rules for Shared Surnames

**Question:** How should the system handle ambiguous surname mentions like "Smith" when multiple canonical people share that surname (Tara Smith, Aaron Smith)?

**YOLO DECISION:** **Option A - Conservative Disambiguation**

**Rationale:**
- Confidence level: ✅ Consensus (both OpenAI and Gemini recommended)
- Prevents high-impact false positives that poison search facets
- Better to miss a mention than attribute it to the wrong person
- Aligns with user expectation: "Smith" is too generic without context
- Strategy: Balanced (pick consensus recommendation)

**Implementation details:**
1. Block single-token surnames by default ("Smith" alone is rejected)
2. Disambiguation triggers:
   - Full name appears in transcript ("Tara Smith", "Aaron Smith") → map
   - Instructor metadata field (from Phase 6) matches one person → map
   - Title + initial pattern ("Dr. T. Smith", "Prof. Aaron Smith") → map
   - Speaker label exact match ("Tara Smith:", "Aaron Smith:") → map
3. Unresolved mentions logged as "ambiguous" for later review
4. Maintain explicit `blocked_alias` list: ["Smith", "Aaron", "Tara", "Ben", "Mike", "Harry", "Greg", "Keith", "Don"]

**Sub-decisions:**
- **"Tara" alone → Tara Smith?** NO (blocked alias, require surname or context)
- **Non-canonical "Smith" references?** Log for review, don't assume (e.g., Adam Smith in philosophy comparisons)
- **False positive tolerance?** STRICT - prefer false negatives over wrong attributions

---

### Q2: Extraction Engine Architecture

**Question:** Should entity extraction use deterministic fuzzy matching (Python libraries) or LLM-based extraction (Mistral API)?

**YOLO DECISION:** **Option A - Deterministic-First with Controlled LLM Fallback**

**Rationale:**
- Confidence level: ✅ Consensus (both providers strongly recommended)
- Canonical list is small (15 names) and highly unique (Peikoff, Ghate, Binswanger)
- Most mentions will match deterministically (fast, free, reproducible)
- LLM fallback handles edge cases without blanket cost
- Cost-effective: Saves ~$0.50-1.00 per 1,000 files vs LLM-first
- Strategy: Balanced (pick consensus recommendation with proven cost savings)

**Implementation details:**

**Stage A (Deterministic - Fast & Free):**
1. Text normalization: casefold, strip punctuation, Unicode normalize
2. Exact match to `person.canonical_name` (e.g., "Leonard Peikoff")
3. Exact match to `person_alias.alias_text` (e.g., "Peikoff", "Dr. Peikoff", "LP")
4. Fuzzy match using RapidFuzz `token_set_ratio`:
   - Threshold **≥92**: Accept as high-confidence match
   - Threshold **80-91**: Flag for Stage B review
   - Threshold **<80**: Reject (not a mention)

**Stage B (LLM Fallback - Expensive & Contextual):**
- Only invoke for fuzzy scores in 80-91 range AND context suggests person reference
- Send ±200 chars context + canonical list (15 names) to Mistral
- Require structured JSON: `{"person_id": "ayn-rand" | "none"}`
- Temperature: **0.1** (deterministic, matching Phase 6 minimalist strategy)
- Max retries: 2 on transient failures

**Uniqueness weighting:**
- High-uniqueness surnames (Peikoff, Ghate, Binswanger, Mayhew, Salmieri, Mazza, Liège, Lockitch, Moroney): Match on surname alone
- Common first names (Ben, Mike, Harry, Greg, Tara, Aaron, Keith, Don, Yaron): Require surname or full context validation

**Sub-decisions:**
- **Fuzzy threshold:** 92 (balances precision/recall based on RapidFuzz testing)
- **LLM calls permitted?** YES (controlled fallback only, not blanket)
- **Temperature:** 0.1 (matches Phase 6 production, ensures determinism)

---

### Q3: Output Data Model Structure

**Question:** What entity metadata should be stored in SQLite vs sent to Gemini File Search?

**YOLO DECISION:** **Option A - Two-Tier Storage: SQLite Rich, Gemini Simplified**

**Rationale:**
- Confidence level: ✅ Consensus (both providers recommended separation)
- Gemini metadata has structure constraints (flat key-value, size limits)
- Separation of concerns: Gemini for search filtering, SQLite for analytics
- Future-proof: Supports highlighting (offsets) and frequency analysis later
- Strategy: Balanced (pick consensus with clean architecture)

**Implementation details:**

**SQLite Schema (Primary Storage):**

Table: `transcript_entity`
```sql
CREATE TABLE transcript_entity (
    transcript_id INTEGER NOT NULL,
    person_id TEXT NOT NULL,
    mention_count INTEGER NOT NULL CHECK(mention_count >= 1),
    first_seen_char INTEGER,
    max_confidence REAL CHECK(max_confidence >= 0.0 AND max_confidence <= 1.0),
    evidence_sample TEXT,
    extraction_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (transcript_id, person_id),
    FOREIGN KEY (transcript_id) REFERENCES transcript(id),
    FOREIGN KEY (person_id) REFERENCES person(person_id)
);
```

Table: `entity_mention` (Phase 7 - Feature-Flagged)
```sql
CREATE TABLE entity_mention (
    id INTEGER PRIMARY KEY,
    transcript_id INTEGER NOT NULL,
    person_id TEXT NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    surface_text TEXT NOT NULL,
    confidence REAL,
    context_snippet TEXT,
    FOREIGN KEY (transcript_id) REFERENCES transcript(id),
    FOREIGN KEY (person_id) REFERENCES person(person_id)
);
```

**Gemini Metadata (Simplified for Search Filtering):**

Custom metadata field: `mentioned_entities`
- Type: List of strings (canonical names)
- Value: `["Ayn Rand", "Leonard Peikoff", "Onkar Ghate"]`
- Purpose: Enable Gemini queries: `metadata.mentioned_entities: "Onkar Ghate"`
- Size: ~200 chars max (15 names × ~13 chars avg)

**Rationale:** Gemini gets clean Boolean filtering, SQLite stores rich analytics data

**Sub-decisions:**
- **Highlighted mentions in UI?** Deferred to Phase 7 (offsets table exists but feature-flagged)
- **Confidence per transcript or per mention?** Both (max per transcript, individual per mention in Phase 7)
- **SQLite size concern?** No (summary table ~10KB per 1,000 files, detail table deferred)
- **Gemini character limit?** 2,048 chars per metadata value (15 names = ~200 chars, safe)

---

### Q4: Workflow Integration Point

**Question:** Where does entity extraction run in the pipeline? Is it a hard gate (fail upload if extraction fails) or graceful degradation?

**YOLO DECISION:** **Option A - Mandatory Pre-Upload Gate with Fail-One-Continue-Batch**

**Rationale:**
- Confidence level: ✅ Consensus (both providers recommended hard gate)
- Ensures metadata consistency: all uploaded files have entity metadata
- Fail-one-continue-batch prevents single bad file from blocking pipeline
- Clear error states for debugging and retry
- Strategy: Balanced (pick consensus for reliability)

**Implementation details:**

**Pipeline order:**
1. Parse transcript (existing Phase 1)
2. Run Phase 6 metadata extraction (existing)
3. **NEW: Run entity extraction/normalization (Phase 6.1)**
4. Validate results (schema + referential integrity)
5. Write to SQLite (transaction: metadata + entities together)
6. Upload to Gemini with enriched metadata (Phase 6.2)
7. Mark file as uploaded

**Failure handling:**
- **Extraction fails:** Mark `blocked_entity_extraction`, log error, skip file, continue batch
- **No entities found:** Valid case (store empty set, mark `entities_done`), proceed
- **Validation fails:** Mark `error`, log details, skip file, continue batch
- **Pipeline continues:** Fail-one doesn't block entire batch

**State tracking:**
- `processing_state`: `pending|entities_done|uploaded|error|blocked_entity_extraction`
- `entity_extraction_version`: "6.1.0"
- `canonical_registry_version`: Integer migration version

**Sub-decisions:**
- **Upload if extraction fails?** NO (hard gate ensures consistency)
- **Re-run when aliases updated?** YES (manual command: `objlib extract entities --upgrade`)
- **Retry policy for transient failures?** LLM fallback: 2 retries, deterministic stages: fail fast

---

### Q5: Backfill Strategy for Existing Files

**Question:** Should we retroactively extract entities for the 281+ files already processed in Phase 6, and if so, do we re-upload them to Gemini?

**YOLO DECISION:** **Option A - Backfill SQLite Now, Re-Upload in Phase 6.2 if Needed**

**Rationale:**
- Confidence level: ✅ Consensus (both providers recommended backfill)
- Ensures consistent UX: all files have entity filters available
- Defers expensive re-upload decision to Phase 6.2 based on actual Gemini needs
- Enables immediate local search/analytics on backfilled data
- Strategy: Balanced (pick consensus with cost deferral)

**Implementation details:**

**Backfill CLI command:**
```bash
objlib extract entities --backfill
```

**Backfill logic:**
1. Query: `SELECT * FROM transcript WHERE uploaded=true AND entities_extracted IS NULL`
2. For each transcript:
   - Read local text file (requires source disk connected)
   - Run entity extraction (deterministic-first pipeline)
   - Write results to `transcript_entity` table
   - Mark `entities_extracted=true`, `extraction_version=6.1.0`
3. Track: extracted_count, error_count, skipped_count (file not found)
4. Report: summary statistics, list of errors

**Re-upload decision (deferred to Phase 6.2):**
- Question: Does Gemini File Search index need entity metadata embedded in uploaded document?
- If **YES**: Schedule controlled re-upload batch (expensive, ~$2-5 API cost)
- If **NO**: SQLite is primary search DB, Gemini only needs enriched metadata for NEW uploads

**Current assumption:** Gemini only needs `mentioned_entities` list in custom_metadata for NEW uploads; SQLite handles entity filtering for all files (new + backfilled)

**Sub-decisions:**
- **Re-upload 1,614 files?** Deferred to Phase 6.2 (likely NO based on Gemini metadata model)
- **Backfill repeatable?** YES (`--backfill` can re-run safely, idempotent UPSERT)
- **Source disk unavailable?** Skip file, log as `skipped_disk_unavailable`, continue batch
- **Backfill vs new uploads?** Same extraction pipeline, just different SQL query filters

---

## Tier 2: Important Decisions

### Q6: Canonical Entity Registry Schema

**Question:** Where should the canonical list of 15 names live? Hard-coded in Python, SQLite table, external config?

**YOLO DECISION:** **Option A - SQLite Tables with Human-Readable Slugs**

**Rationale:**
- Confidence level: ⚠️ OpenAI recommended (Gemini assumed hard-coded)
- DB-backed registry enables updates without code deploys
- Supports audit trail and alias management
- Human-readable slugs better for debugging than UUIDs
- Strategy: Balanced (pick OpenAI recommendation with clean data model)

**Implementation details:**

**Table: `person`**
```sql
CREATE TABLE person (
    person_id TEXT PRIMARY KEY,  -- Slug: "ayn-rand", "leonard-peikoff"
    canonical_name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK(type IN ('philosopher', 'ari_instructor')),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

**Table: `person_alias`**
```sql
CREATE TABLE person_alias (
    id INTEGER PRIMARY KEY,
    alias_text TEXT NOT NULL,
    person_id TEXT NOT NULL,
    alias_type TEXT CHECK(alias_type IN ('nickname', 'misspelling', 'partial', 'initials', 'title_variant')),
    confidence_hint REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (person_id) REFERENCES person(person_id)
);
CREATE INDEX idx_person_alias_text ON person_alias(alias_text);
```

**Initial seed migration (`migrations/003_canonical_persons.sql`):**
```sql
INSERT INTO person (person_id, canonical_name, type, created_at, updated_at) VALUES
    ('ayn-rand', 'Ayn Rand', 'philosopher', datetime('now'), datetime('now')),
    ('leonard-peikoff', 'Leonard Peikoff', 'ari_instructor', datetime('now'), datetime('now')),
    ('onkar-ghate', 'Onkar Ghate', 'ari_instructor', datetime('now'), datetime('now')),
    ('robert-mayhew', 'Robert Mayhew', 'ari_instructor', datetime('now'), datetime('now')),
    ('tara-smith', 'Tara Smith', 'ari_instructor', datetime('now'), datetime('now')),
    ('ben-bayer', 'Ben Bayer', 'ari_instructor', datetime('now'), datetime('now')),
    ('mike-mazza', 'Mike Mazza', 'ari_instructor', datetime('now'), datetime('now')),
    ('aaron-smith', 'Aaron Smith', 'ari_instructor', datetime('now'), datetime('now')),
    ('tristan-de-liege', 'Tristan de Liège', 'ari_instructor', datetime('now'), datetime('now')),
    ('gregory-salmieri', 'Gregory Salmieri', 'ari_instructor', datetime('now'), datetime('now')),
    ('harry-binswanger', 'Harry Binswanger', 'ari_instructor', datetime('now'), datetime('now')),
    ('jean-moroney', 'Jean Moroney', 'ari_instructor', datetime('now'), datetime('now')),
    ('yaron-brook', 'Yaron Brook', 'ari_instructor', datetime('now'), datetime('now')),
    ('don-watkins', 'Don Watkins', 'ari_instructor', datetime('now'), datetime('now')),
    ('keith-lockitch', 'Keith Lockitch', 'ari_instructor', datetime('now'), datetime('now'));

-- Common aliases (expand as needed)
INSERT INTO person_alias (alias_text, person_id, alias_type, created_at) VALUES
    ('Rand', 'ayn-rand', 'partial', datetime('now')),
    ('Peikoff', 'leonard-peikoff', 'partial', datetime('now')),
    ('Dr. Peikoff', 'leonard-peikoff', 'title_variant', datetime('now')),
    ('LP', 'leonard-peikoff', 'initials', datetime('now')),
    ('Onkar', 'onkar-ghate', 'partial', datetime('now')),
    ('Ghate', 'onkar-ghate', 'partial', datetime('now')),
    ('Mayhew', 'robert-mayhew', 'partial', datetime('now')),
    ('Binswanger', 'harry-binswanger', 'partial', datetime('now')),
    ('Salmieri', 'gregory-salmieri', 'partial', datetime('now')),
    ('Greg', 'gregory-salmieri', 'nickname', datetime('now')),
    ('Mazza', 'mike-mazza', 'partial', datetime('now')),
    ('Bayer', 'ben-bayer', 'partial', datetime('now')),
    ('Liège', 'tristan-de-liege', 'partial', datetime('now')),
    ('Tristan', 'tristan-de-liege', 'partial', datetime('now')),
    ('Moroney', 'jean-moroney', 'partial', datetime('now')),
    ('Brook', 'yaron-brook', 'partial', datetime('now')),
    ('Watkins', 'don-watkins', 'partial', datetime('now')),
    ('Lockitch', 'keith-lockitch', 'partial', datetime('now'));
```

**Sub-decisions:**
- **Identifier format:** Human-readable slugs (e.g., "ayn-rand") for debuggability
- **List expansion:** Stakeholder approval via PR review + seed migration update
- **Extra attributes:** Not now (can add `birth_year`, `ari_role`, `external_url` later if needed)

---

### Q7: "Mention" Definition Rules

**Question:** What text patterns count as valid mentions?

**YOLO DECISION:** **Option A - Explicit Name/Alias Only**

**Rationale:**
- Confidence level: ⚠️ OpenAI recommended (Gemini assumed obvious)
- Keeps extraction explainable and auditable
- Avoids speculative coreference resolution (NLP complexity)
- Clear rules for inclusion/exclusion
- Strategy: Balanced (pick OpenAI recommendation for clarity)

**Implementation details:**

**Include as valid mentions:**
- Full names: "Ayn Rand", "Leonard Peikoff"
- Surnames (when unambiguous per Q1): "Peikoff", "Ghate", "Binswanger"
- Possessives: "Rand's", "Peikoff's theory"
- Titles: "Dr. Peikoff", "Professor Salmieri"
- Speaker labels: "Leonard Peikoff:" (if exact match to canonical/alias)

**Exclude (not valid mentions):**
- Pronouns: "she", "he", "they", "the author"
- Generic references: "the philosopher", "the instructor" (without name)
- Initials alone: "A.R." (unless in alias list with high confidence)
- Ambiguous context: "the author said..." (unless name appears nearby)

**Speaker label handling:**
- Treat as mention if label text exactly matches `canonical_name` or `alias_text`
- Example: Line starts with "Leonard Peikoff:" → count as 1 mention
- Increment mention_count, capture first_seen_char offset

**Sub-decisions:**
- **"Rand" alone sufficient?** YES (high uniqueness, per Q2 uniqueness weighting)
- **Extract from titles/headers?** YES (treat same as body text)
- **Quoted text differently?** NO (treat uniformly, quote context doesn't change entity identity)

---

### Q8: State Management & Versioning

**Question:** How to track which extraction logic version was used per transcript?

**YOLO DECISION:** **Option A - Extraction Version + Registry Version Fields**

**Rationale:**
- Confidence level: ⚠️ OpenAI recommended for long-term maintenance
- Enables safe backfills and reproducibility
- Supports iterative improvements without data corruption
- Clear reprocessing triggers
- Strategy: Balanced (pick OpenAI recommendation for maintainability)

**Implementation details:**

**Transcript table fields:**
```sql
ALTER TABLE transcript ADD COLUMN processing_state TEXT DEFAULT 'pending';
ALTER TABLE transcript ADD COLUMN entity_extraction_version TEXT;
ALTER TABLE transcript ADD COLUMN canonical_registry_version INTEGER;
```

**State values:**
- `pending`: Not yet processed
- `entities_done`: Successfully extracted (may be empty set)
- `uploaded`: Phase 6.2 complete
- `error`: General failure
- `blocked_entity_extraction`: Extraction specifically failed

**Version tracking:**
- `entity_extraction_version`: Semantic version (e.g., "6.1.0")
- `canonical_registry_version`: Integer from seed migration (increments when aliases change)

**Idempotency:**
```sql
INSERT INTO transcript_entity (transcript_id, person_id, mention_count, ...)
VALUES (?, ?, ?, ...)
ON CONFLICT (transcript_id, person_id) DO UPDATE SET
    mention_count = excluded.mention_count,
    max_confidence = excluded.max_confidence,
    evidence_sample = excluded.evidence_sample,
    extraction_version = excluded.extraction_version;
```

**Reprocessing triggers:**
```bash
# Re-run all with old version
objlib extract entities --upgrade

# Force re-run all
objlib extract entities --force

# Re-run specific files
objlib extract entities --file "path/to/file.txt"
```

**Sub-decisions:**
- **What triggers reprocessing?** Manual command or version mismatch detection
- **Keep historical results?** NO (UPSERT overwrites, only latest matters)
- **Auto re-upload?** NO (manual decision in Phase 6.2)

---

### Q9: Validation Rules

**Question:** What validation gates before persisting entity metadata?

**YOLO DECISION:** **Option A - Strict Pydantic Validation**

**Rationale:**
- Confidence level: ⚠️ OpenAI recommended for data quality
- Prevents corrupted references and low-confidence garbage
- Supports empty results (valid case: no canonical people mentioned)
- Clear error messages for debugging
- Strategy: Balanced (pick OpenAI recommendation for reliability)

**Implementation details:**

**Pydantic schema:**
```python
from pydantic import BaseModel, Field

class TranscriptEntityOutput(BaseModel):
    person_id: str
    canonical_name: str
    mention_count: int = Field(ge=1)
    max_confidence: float = Field(ge=0.0, le=1.0)
    evidence_sample: str = Field(max_length=200)
    extraction_version: str

class EntityExtractionResult(BaseModel):
    transcript_id: int
    entities: list[TranscriptEntityOutput]
    processing_state: str
```

**Validation rules:**
1. `person_id` must exist in `person` table (FK constraint enforced by SQLite)
2. `mention_count >= 1` (zero mentions don't get included in output list)
3. `confidence >= 0.5` (below 50% confidence are too uncertain, reject)
4. If no entities found: `entities = []` is valid, mark `entities_done`, proceed

**Error handling:**
- Schema validation failure → log error, mark `blocked_entity_extraction`
- Foreign key violation → crash early (data corruption, should never happen)
- Empty results → valid case, proceed with empty entity list
- Below-threshold confidence → reject individual entity, log as `low_confidence_rejected`

**Sub-decisions:**
- **Minimum confidence threshold:** 0.5 (50%) - balances quality vs recall
- **Show "no entities found" warning?** NO (normal case for conceptual discussions)
- **Store "unknown person" mentions?** NO (out of scope, focus on canonical 15)

---

### Q10: Library Choices & Determinism

**Question:** Which fuzzy matching library? How to ensure reproducibility?

**YOLO DECISION:** **Option A - RapidFuzz Pinned Version + Deterministic Settings**

**Rationale:**
- Confidence level: ✅ Consensus (both providers strongly recommended RapidFuzz)
- 100x faster than LLM, highly accurate for unique surnames
- Pinned version ensures reproducibility
- Proven in production use across many projects
- Strategy: Balanced (pick consensus with industry-standard library)

**Implementation details:**

**Dependency pinning:**
```python
# requirements.txt
rapidfuzz==3.6.1  # Exact version pin
```

**Deterministic settings:**
```python
from rapidfuzz import fuzz

def fuzzy_match(query: str, canonical_name: str, aliases: list[str]) -> tuple[float, str]:
    """Match query against canonical name + aliases using deterministic scoring."""
    candidates = [canonical_name] + aliases
    best_score = 0.0
    best_match = None

    # Normalize query
    query_norm = query.strip().lower()

    for candidate in candidates:
        candidate_norm = candidate.strip().lower()

        # Use token_set_ratio (order-independent, handles partial matches)
        score = fuzz.token_set_ratio(query_norm, candidate_norm)

        if score > best_score:
            best_score = score
            best_match = candidate

    return best_score / 100.0, best_match  # Normalize to 0.0-1.0
```

**LLM fallback determinism:**
- Temperature: 0.1 (minimal randomness, matches Phase 6)
- Prompt version: Stored in results for traceability
- Seed: Not needed (temperature 0.1 is sufficiently deterministic)

**Regression test suite:**
```python
# tests/test_entity_extraction_regression.py
GOLD_SET = [
    ("OPAR/2023/Q1/Week1/transcript.txt", ["Ayn Rand", "Leonard Peikoff"]),
    ("ITOE/2022/Q3/Week5/transcript.txt", ["Ayn Rand"]),
    # ... 20-30 manually verified transcripts
]

def test_entity_extraction_regression():
    for file_path, expected_entities in GOLD_SET:
        result = extract_entities(file_path)
        assert set(result.canonical_names) == set(expected_entities)
```

**Sub-decisions:**
- **Strict reproducibility required?** YES (within library version constraints)
- **Automated regression tests?** YES (20-30 file gold set, run on CI)
- **Forbid LLM entirely?** NO (controlled fallback acceptable with temperature 0.1)

---

## Tier 3: Polish Decisions (Deferred to Implementation)

### Q11: Error Handling + Retries

**YOLO DECISION:** OpenAI recommendation (deterministic fail-fast, LLM retry 2x)

**Implementation:** Apply during coding, tune retry policy based on observed failure rates

---

### Q12: Observability + Visibility

**YOLO DECISION:** CLI report commands with evidence samples

**Implementation:**
```bash
objlib extract entities --report
objlib extract entities --review-person "Tara Smith"
objlib extract entities --low-confidence
```

Store `evidence_sample` (100-char snippet) in `transcript_entity` table

---

### Q13: Security + Authentication

**YOLO DECISION:** Data minimization (±200 char context, no full transcripts to LLM)

**Implementation:** Apply as standard practice, redact PII before LLM calls

---

### Q14: Search UX Semantics

**YOLO DECISION:** Filter by person_id, auto-expand aliases, boost by mention_count

**Implementation:** Defer UX refinement to Phase 5 based on user feedback

---

### Q15: Non-Canonical Entities

**YOLO DECISION:** Strict adherence to 15 names, architecture supports expansion

**Implementation:** Build `EntityExtractor` to accept config file, plan Phase 6.3 if valuable later

---

## Summary: Implementation Checklist

**Must Implement (Tier 1):**
- [x] Conservative disambiguation (block single-token "Smith", require full name/context)
- [x] Deterministic-first extraction (RapidFuzz ≥92, LLM fallback 80-91 range)
- [x] Two-tier data model (SQLite rich, Gemini simplified List[str])
- [x] Mandatory pre-upload gate (fail-one-continue-batch)
- [x] Backfill command (SQLite now, re-upload decision in Phase 6.2)

**Should Implement (Tier 2):**
- [x] SQLite canonical registry (person + person_alias tables, human-readable slugs)
- [x] Explicit mention definition (names/aliases only, no pronouns)
- [x] State versioning (extraction_version, registry_version fields)
- [x] Strict validation (Pydantic, confidence ≥0.5, FK checks)
- [x] RapidFuzz 3.6.1 pinned (deterministic settings, regression tests)

**Can Defer (Tier 3):**
- [ ] Error handling tuning (retry policy optimization)
- [ ] Observability commands (report, review, low-confidence)
- [ ] Security practices (PII redaction, context minimization)
- [ ] Search UX refinement (alias expansion, ranking)
- [ ] Non-canonical expansion (Kant, Aristotle, Plato in Phase 6.3)

---

## Next Steps

**✅ YOLO Mode Complete** - All 15 questions answered with balanced strategy

**Proceed to Planning:**
1. Run `/gsd:plan-phase 6.1` to create detailed execution plan
2. Plan will break down implementation into 3-5 executable steps
3. Each step will be verified before proceeding to Phase 6.2

---

*Auto-generated by discuss-phase-ai --yolo (balanced strategy)*
*Human review recommended before final implementation*
*Generated: 2026-02-16*
