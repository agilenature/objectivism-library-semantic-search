---
phase: 04-quality-enhancements
plan: 01
subsystem: database, search
tags: [sqlite, pydantic, yaml, query-expansion, schema-migration, structured-output]

# Dependency graph
requires:
  - phase: 06.2-metadata-enriched-upload
    provides: Schema V5 with upload tracking columns
provides:
  - Schema V6 with passages cache, sessions, and session_events tables
  - Pydantic v2 models for Gemini Flash reranking and synthesis structured output
  - Query expansion engine with 46-term curated Objectivist glossary
affects: [04-02, 04-03, 04-04, 04-05]

# Tech tracking
tech-stack:
  added: [pydantic v2 BaseModel for structured output, PyYAML for glossary loading]
  patterns: [passage upsert with last_seen_at tracking, module-level glossary caching, multi-word phrase priority matching]

key-files:
  created:
    - src/objlib/search/models.py
    - src/objlib/search/expansion.py
    - src/objlib/search/synonyms.yml
  modified:
    - src/objlib/database.py

key-decisions:
  - "Passage upsert uses INSERT OR IGNORE + UPDATE pattern (not ON CONFLICT) for clarity"
  - "Glossary cached at module level for performance across repeated search calls"
  - "Multi-word phrases matched longest-first with span overlap prevention"
  - "Original matched term boosted (appears twice in expanded query) per locked decision Q4c"
  - "Pydantic models in search/models.py separate from top-level models.py (dataclasses)"

patterns-established:
  - "Schema migration V6: CREATE TABLE IF NOT EXISTS for new tables (no ALTER TABLE needed)"
  - "Query expansion: case-insensitive word boundary matching with re.escape"
  - "Structured output models: Pydantic BaseModel with Field validators for Gemini response_schema"

# Metrics
duration: 3min
completed: 2026-02-18
---

# Phase 4 Plan 1: Data Layer Foundation Summary

**Schema V6 migration with passages/sessions tables, Pydantic v2 reranking/synthesis models, and 46-term Objectivist query expansion glossary**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-18T05:48:27Z
- **Completed:** 2026-02-18T05:51:43Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Database migrated to schema V6 with passages cache (citation stability), sessions, and session_events (research persistence) tables
- Six Pydantic v2 models created for Gemini Flash structured output: RankedPassage, RankedResults, CitationRef, Claim, SynthesisOutput, TierSynthesis
- Query expansion engine with 46-term curated Objectivist glossary covering metaphysics, epistemology, ethics, politics, aesthetics, errors/fallacies, and key works

## Task Commits

Each task was committed atomically:

1. **Task 1: Schema V6 migration** - `414f8e4` (feat)
2. **Task 2: Pydantic v2 structured output models** - `52a6634` (feat)
3. **Task 3: Query expansion engine** - `88fb84e` (feat)

## Files Created/Modified
- `src/objlib/database.py` - Schema V6 migration with passages, sessions, session_events tables; upsert_passage() and mark_stale_passages() methods
- `src/objlib/search/models.py` - Pydantic v2 models for Gemini Flash reranking and synthesis structured output
- `src/objlib/search/expansion.py` - Query expansion engine with glossary loading, expansion, and term addition
- `src/objlib/search/synonyms.yml` - 46-term curated Objectivist philosophy glossary

## Decisions Made
- Passage upsert uses INSERT OR IGNORE + UPDATE last_seen_at (not ON CONFLICT DO UPDATE) for explicitness
- Glossary cached at module level (_glossary_cache) to avoid re-reading YAML on every search
- Multi-word phrases matched longest-first with overlap span tracking to prevent double-matching
- Pydantic models kept in search/models.py separate from objlib/models.py (which uses dataclasses)
- CitationRef quote field has min_length=20, max_length=300 constraints for quality control

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Pre-existing test failure in test_formatter.py (test_display_search_results_score_bars) unrelated to this plan's changes. Confidence score bars were removed from display in Phase 3 but test was not updated. No regression from Phase 4 work.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All foundational artifacts ready for Phase 4 Plans 2-5:
  - Passages table ready for citation caching pipeline (Plan 2)
  - Sessions/session_events tables ready for research session tracking (Plan 5)
  - Pydantic models ready for Gemini Flash reranking (Plan 2) and synthesis (Plan 3)
  - Query expansion ready for search pipeline integration (Plan 2)
- No blockers

## Self-Check: PASSED

- [x] src/objlib/database.py exists
- [x] src/objlib/search/models.py exists
- [x] src/objlib/search/expansion.py exists
- [x] src/objlib/search/synonyms.yml exists
- [x] Commit 414f8e4 exists (Task 1: Schema V6)
- [x] Commit 52a6634 exists (Task 2: Pydantic models)
- [x] Commit 88fb84e exists (Task 3: Query expansion)
- [x] Schema version is 6
- [x] All Pydantic models importable
- [x] Query expansion works for known and unknown terms
- [x] Glossary has 46 terms (>= 40 required)
- [x] No test regressions (1 pre-existing failure in test_formatter.py)

---
*Phase: 04-quality-enhancements*
*Completed: 2026-02-18*
