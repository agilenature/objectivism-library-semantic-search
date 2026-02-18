# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-15)

**Core value:** Three equally critical pillars -- semantic search quality, metadata preservation, incremental updates
**Current focus:** Phase 4: Quality Enhancements -- In Progress
**Execution strategy:** Phase 6 before full upload (1,721 files) to enrich metadata first

## Current Position

Phase: 4 of 7+ (Quality Enhancements)
Plan: 3 of 5
Status: In progress
Last activity: 2026-02-18 - Completed 04-03-PLAN.md (multi-document synthesis)

Progress: [##################] ~96% (22 plans of ~24 estimated total)

Phase 1 Progress: [##########] 3/3 plans -- COMPLETE
Phase 2 Progress: [##########] 4/4 plans -- COMPLETE
Phase 3 Progress: [##########] 3/3 plans -- COMPLETE
Phase 4 Progress: [######....] 3/5 plans -- IN PROGRESS
Phase 6 Progress: [##########] 5/5 plans -- COMPLETE
Phase 6.1 Progress: [##########] 2/2 plans -- COMPLETE
Phase 6.2 Progress: [##########] 2/2 plans -- COMPLETE

## Performance Metrics

**Velocity:**
- Total plans completed: 22
- Average duration: 4.0 min
- Total execution time: 88 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 3/3 | 10 min | 3.3 min |
| 02-upload-pipeline | 4/4 | 17 min | 4.3 min |
| 03-search-and-cli | 3/3 | 13 min | 4.3 min |
| 06-ai-powered-metadata | 5/5 | 24 min | 4.8 min |
| 06.1-entity-extraction | 2/2 | 9 min | 4.5 min |
| 06.2-metadata-enriched-upload | 2/2 | 6 min | 3.0 min |

| 04-quality-enhancements | 3/5 | 7 min | 2.3 min |

**Recent Trend:**
- Last 5 plans: 06.2-02 (3 min), 04-01 (3 min), 04-02 (2 min), 04-03 (2 min)
- Trend: Stable at 2-3 min per plan

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: 6 phases total (added Phase 6: AI-Powered Metadata Enhancement)
- [Roadmap]: Phase ordering follows scan-upload-query pipeline with zero-API-dependency foundation first
- [Roadmap]: Phase 6.1 inserted after Phase 6: Entity Extraction & Name Normalization (URGENT - canonical philosopher name matching)
- [Roadmap]: Phase 6.2 inserted after Phase 6.1: Metadata-Enriched Gemini Upload (URGENT - upload with 4-tier metadata)
- [01-01]: content_hash indexed but NOT UNIQUE (allows same content at different paths)
- [01-01]: Timestamps use strftime('%Y-%m-%dT%H:%M:%f', 'now') for ISO 8601 with milliseconds
- [01-01]: content_hash stored as TEXT hexdigest (readable in DB browsers)
- [01-01]: UPSERT resets status to pending only when content_hash changes (CASE expression)
- [01-01]: Used hatchling as build backend with src layout
- [01-02]: Try COMPLEX_PATTERN before SIMPLE_PATTERN (more specific first avoids false matches)
- [01-02]: Folder metadata merged with filename metadata; filename takes precedence on overlap
- [01-02]: ChangeSet uses set[str] not set[Path] to match database file_path TEXT column
- [01-02]: Extraction failures tracked by _unparsed_filename and _unparsed_folder flags in metadata
- [01-03]: Graceful degradation: unrecognized filenames get MINIMAL quality (topic from stem), not NONE
- [01-03]: pythonpath added to pyproject.toml for pytest to find src layout
- [02-01]: Hand-rolled circuit breaker instead of pybreaker (fail_max model doesn't fit rolling-window 429 tracking)
- [02-01]: Circuit breaker trips on EITHER 5% rate threshold OR 3 consecutive 429s (whichever first)
- [02-01]: Rate limiter defaults to Tier 1 (20 RPM, 3s interval) with 3x delay multiplier when OPEN
- [02-01]: MetadataQuality to numeric mapping: complete=100, partial=75, minimal=50, none=25, unknown=0
- [02-01]: Schema v2 backward compatible via CREATE TABLE IF NOT EXISTS
- [02-02]: State writes commit immediately -- no transactions held across await boundaries (aiosqlite pitfall)
- [02-02]: Upload intent recorded BEFORE API call, result AFTER -- crash recovery anchor
- [02-02]: Semaphore wraps only API call section, not DB writes
- [02-02]: Heavy upload imports deferred to upload() command function for fast CLI startup
- [02-02]: Circuit breaker OPEN skips files rather than blocking pipeline
- [02-03]: Keyring service name: objlib-gemini, key name: api_key
- [02-03]: API keys read exclusively from system keyring, never env vars or CLI flags
- [02-03]: load_upload_config() also migrated to keyring for consistency
- [02-04]: Upload pipeline restricted to .txt files only via database query filter
- [02-04]: Added 'skipped' status for non-.txt files (135 .epub/.pdf files marked)
- [02-04]: File type filtering at database layer (get_pending_files) not orchestrator
- [03-01]: AppState callback uses allowlist for Gemini commands (search, view); all others skip initialization
- [03-01]: Added --help to callback skip list to prevent API calls during help display
- [03-01]: Fixed bug - removed invalid request_options parameter from GenerateContentConfig
- [03-phase]: Added metadata command group (show, update, batch-update) for progressive metadata improvement
- [03-phase]: Filter comparison operators use CAST(json_extract() AS INTEGER) for numeric fields (year, week, quality_score) to enable proper >= <= > < comparisons
- [03-phase]: Fixed Gemini citation display - added two-pass lookup (filename -> Gemini ID fallback) to show actual filenames instead of file IDs
- [Phase 6]: Added AI-powered metadata enhancement to roadmap (LLM-based category inference)
- [Phase 7]: Added Interactive TUI to roadmap (Textual-based terminal UI with live search, visual browsing, split-pane views)
- [Phase 5]: Added offline query mode to Phase 5 (query operations work without source disk connected)
- [Execution Order]: Adopted Metadata-First Strategy - executing Phase 6 before Phase 4/5 to enrich metadata (496 unknown files) before full library upload (1,721 files)
- [06-01]: SDKError.status_code used for Mistral 402/429 detection (MistralError base provides it)
- [06-01]: Regex JSON extraction supports 2 levels of brace nesting for semantic_description
- [06-01]: Schema v3 migration uses try/except for ALTER TABLE (SQLite lacks IF NOT EXISTS for columns)
- [06-01]: Mistral keyring service name: objlib-mistral, key name: api_key
- [06-02]: Temperature experiments: Minimalist=0.1, Teacher=0.3, Reasoner=0.5 (magistral requires 1.0 for production)
- [06-02]: Size buckets adjusted: <10KB small (only 2 files <5KB), 10-30KB medium, 30-100KB large, >100KB very large
- [06-02]: Checkpoint uses write-to-tmp-then-rename for atomic state persistence
- [06-02]: Wave 1 results saved to DB per-file per-strategy immediately (not batched)
- [06-03]: Minimalist strategy selected for Wave 2 production processing (all quality gates passed)
- [06-03]: Composite score = validation_pass_rate * avg_confidence for strategy ranking
- [06-03]: Hybrid detection threshold: 10% confidence gap between validation and confidence winners
- [06-03]: Quality gate thresholds: accuracy>=0.90, cost<=$0.30, confidence>=0.70, validation>=0.85
- [06-04]: Category alias repair via substring/alias matching before hard validation
- [06-04]: Confidence tier weights: category 0.30, topics 0.40, aspects 0.15, description 0.15
- [06-04]: Hallucination penalty: -0.15 for short transcripts (<800 chars) with high tier4 confidence
- [06-04]: Head-tail chunking threshold: max_tokens * 1.5 boundary between head-tail and windowed
- [06-04]: Production always uses temperature=1.0 regardless of Wave 1 strategy temperature
- [06-05]: Interactive review uses $EDITOR (fallback vi) to edit metadata JSON via temp file
- [06-05]: Auto-approve default threshold: 0.85 (85% confidence)
- [06-05]: Stats coverage = (extracted+approved+needs_review) / total_unknown_txt
- [06-05]: Extract command loads winning strategy from data/wave1_selection.json
- [06.1-01]: transcript_id uses TEXT type to match existing files.file_path pattern (not INTEGER)
- [06.1-01]: Blocked aliases stored in person_alias with is_blocked=1 flag
- [06.1-01]: Fuzzy match threshold: >= 92 accept, 80-91 LLM fallback, < 80 reject
- [06.1-01]: Canonical name without accent: "Tristan de Liege"
- [06.1-01]: Confidence threshold 0.5 for entity inclusion in output
- [06.1-02]: save_transcript_entities uses delete-then-insert for clean re-extraction idempotency
- [06.1-02]: get_person_by_name_or_alias tries exact canonical, then exact alias, then LIKE partial
- [06.1-02]: entities extract marks missing files as status='error' and continues batch
- [06.1-02]: Report confidence coloring: green >= 0.9, yellow >= 0.7, red < 0.7
- [06.2-01]: Schema v5 adds only upload_attempt_count and last_upload_hash (avoids collision with existing upload columns)
- [06.2-01]: build_enriched_metadata uses AI metadata with Phase 1 fallback for category/difficulty
- [06.2-01]: prepare_enriched_content returns None when no Tier 4 content (skip injection, use original file)
- [06.2-01]: get_enriched_pending_files includes needs_review files by default (configurable)
- [06.2-02]: Conservative concurrency Semaphore(2) with 1-second stagger (not parent default 7)
- [06.2-02]: Store name default objectivism-library-test for enriched uploads
- [06.2-02]: Reset flow handles already-expired 48hr TTL files gracefully via try/except on delete_file
- [06.2-02]: Upload hash idempotency via SHA-256 of (phase1 + ai + entities + content_hash)
- [06.2-fix]: get_files_to_reset_for_enriched_upload checks upload hash - only reset if changed or NULL (prevents unnecessary re-uploads)
- [06.2-fix]: Failed files (status='failed') always retry regardless of hash (handles polling timeouts)
- [06.2-fix]: Post-batch retry pass with 30s cooldown - one retry per failed file per batch (Option 3)
- [04-01]: Passage upsert uses INSERT OR IGNORE + UPDATE pattern (not ON CONFLICT) for clarity
- [04-01]: Glossary cached at module level for performance across repeated search calls
- [04-01]: Multi-word phrases matched longest-first with span overlap prevention
- [04-01]: Original matched term boosted (appears twice in expanded query) per locked decision Q4c
- [04-01]: Pydantic models in search/models.py separate from top-level models.py (dataclasses)
- [04-01]: Schema V6 adds passages, sessions, session_events tables (all CREATE TABLE, no ALTER TABLE)
- [04-02]: Gemini Flash with structured JSON output (RankedResults schema) for passage scoring
- [04-02]: Temperature 0.0 for deterministic reranking scores
- [04-02]: Passage truncation at 500 chars to save tokens
- [04-02]: Default difficulty bucket = intermediate (1) for missing/unknown metadata
- [04-02]: Window size 20 for difficulty reordering (top results only)
- [04-03]: MMR first pass prefers unseen files with unseen courses for maximum diversity
- [04-03]: Re-prompt includes specific error messages to guide Gemini citation correction
- [04-03]: Returns partial results (only validated claims) after second validation attempt
- [04-03]: Returns None for <5 citations (graceful degradation threshold)
- [04-03]: Passage truncation at 600 chars for synthesis context (vs 500 for reranking)

### Pending Todos

Phase 4 Plans 4-5 remaining (CLI integration, session tracking).

### Blockers/Concerns

- Phase 4 research flag: Cross-encoder model selection for philosophy domain, citation prompt engineering, Objectivist terminology mapping need research during planning
- Display issues noted in Phase 3: confidence scores showing 0%, metadata enrichment showing Gemini IDs instead of filenames (can be addressed in Phase 4)

## Session Continuity

Last session: 2026-02-18
Stopped at: Phase 4 Plan 3 COMPLETE (multi-document synthesis). MMR diversity filter, Gemini Flash structured synthesis with claim-level citations, exact-substring quote validation with single re-prompt. Next: Phase 4 Plan 4 (CLI integration) or remaining Phase 4 plans.
Resume file: .planning/phases/04-quality-enhancements/04-03-SUMMARY.md
