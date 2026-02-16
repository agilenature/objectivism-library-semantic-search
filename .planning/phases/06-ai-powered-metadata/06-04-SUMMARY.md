---
phase: 06-ai-powered-metadata
plan: 04
subsystem: extraction
tags: [mistral, validation, confidence-scoring, chunking, batch-processing, metadata-persistence]

# Dependency graph
requires:
  - phase: 06-ai-powered-metadata/03
    provides: "Winning strategy (minimalist) and quality gate validation from Wave 1"
provides:
  - "Two-level validation engine (hard reject+retry, soft accept+flag)"
  - "Multi-dimensional confidence scoring with tier-specific weighting"
  - "Adaptive chunker for 2KB-7MB transcripts"
  - "Production orchestrator with versioned metadata persistence"
  - "Config hashing for extraction reproducibility"
affects: [06-ai-powered-metadata/05, 03-search-and-cli]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-level validation: hard rules (reject+retry) vs soft rules (accept+flag)"
    - "Multi-dimensional confidence: weighted average across 4 tiers with penalties"
    - "Adaptive chunking: full-text / head-tail / windowed sampling"
    - "Versioned metadata: is_current flag with append-only file_metadata_ai"
    - "Config hashing: sha256 of canonical config for reproducibility"

key-files:
  created:
    - src/objlib/extraction/validator.py
    - src/objlib/extraction/confidence.py
    - src/objlib/extraction/chunker.py
  modified:
    - src/objlib/extraction/orchestrator.py
    - src/objlib/extraction/prompts.py

key-decisions:
  - "Category alias repair via substring/alias matching before hard validation"
  - "Confidence tier weights: category 0.30, topics 0.40, aspects 0.15, description 0.15"
  - "Hallucination penalty: -0.15 for short transcripts (<800 chars) with high tier4 confidence"
  - "Head-tail chunking threshold: max_tokens * 1.5 boundary between head-tail and windowed"
  - "Windowed sampling: 3000-token head + 3x600-token middle excerpts + 3000-token tail"
  - "Production always uses temperature=1.0 regardless of Wave 1 strategy temperature"

patterns-established:
  - "ValidationResult dataclass: status + hard_failures + soft_warnings + repaired_fields"
  - "Atomic per-file save: UPDATE files + UPDATE/INSERT file_metadata_ai + DELETE/INSERT file_primary_topics in single transaction"
  - "Checkpoint per-file for production: resume skips completed files"

# Metrics
duration: 6min
completed: 2026-02-16
---

# Phase 6 Plan 04: Production Pipeline Summary

**Two-level validation engine, multi-dimensional confidence scorer, adaptive chunker (2KB-7MB), and production orchestrator with versioned metadata persistence to file_metadata_ai and file_primary_topics tables**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-16T20:07:48Z
- **Completed:** 2026-02-16T20:14:15Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Two-level validation engine: hard rules (category/difficulty enum, topic vocabulary, confidence range) reject and trigger retry with schema reminder; soft rules (aspect count, summary length, key_arguments) accept but flag as needs_review
- Multi-dimensional confidence scoring: weighted average across 4 tiers (category 0.30, topics 0.40, aspects 0.15, description 0.15) with penalties for repairs (-0.25), soft warnings (-0.10 each, max -0.30), and hallucination risk on short transcripts (-0.15)
- Adaptive chunker handles full range of file sizes: full-text for files within budget, head-tail (70/30 split) for slightly over, windowed sampling (head + 3 middle excerpts + tail) for very long files
- Production orchestrator replaces NotImplementedError placeholder with complete batch processing: validated prompt, temperature=1.0, two-level validation with retry, confidence scoring, versioned metadata persistence, checkpoint/resume per file

## Task Commits

Each task was committed atomically:

1. **Task 1: Validation engine, confidence scorer, and adaptive chunker** - `66399a9` (feat)
2. **Task 2: Production orchestrator with versioned metadata persistence** - `6834851` (feat)

## Files Created/Modified

- `src/objlib/extraction/validator.py` - Two-level validation with hard rules (reject) and soft rules (warn), repair logic for category aliases, confidence clamping, topic filtering
- `src/objlib/extraction/confidence.py` - Multi-dimensional confidence scoring with tier-specific weighting and penalties
- `src/objlib/extraction/chunker.py` - Adaptive context window management: full-text, head-tail, windowed sampling
- `src/objlib/extraction/orchestrator.py` - Production run_production() method with validation, retry, confidence, and versioned persistence; helper methods _save_production_result() and _get_pending_extraction_files()
- `src/objlib/extraction/prompts.py` - Added build_production_prompt() and hash_extraction_config() for production prompt building and config versioning

## Decisions Made

- Category repair uses alias table and substring matching (e.g., "course" -> "course_transcript", "book" -> "book_excerpt") to handle common LLM hallucinations before hard validation
- Confidence tier weights prioritize primary_topics (0.40) as the most impactful tier for search quality, with category/difficulty (0.30) second
- Hallucination penalty applies when transcript is very short (<800 chars) but the model reports high description confidence, flagging potential fabricated content
- Head-tail vs windowed sampling threshold set at 1.5x the token budget -- slightly over uses head-tail, significantly over uses windowed sampling with 3 evenly-spaced middle excerpts
- Production always enforces temperature=1.0 regardless of the Wave 1 strategy's experimental temperature setting

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Complete extraction pipeline ready for CLI integration (Plan 05)
- All components (validator, confidence, chunker, orchestrator) are importable and tested
- Production orchestrator accepts file list and strategy name, returns summary dict
- Database persistence handles versioned metadata with is_current flag for historical tracking
- Checkpoint/resume handles credit exhaustion gracefully with per-file granularity

---
*Phase: 06-ai-powered-metadata*
*Completed: 2026-02-16*
