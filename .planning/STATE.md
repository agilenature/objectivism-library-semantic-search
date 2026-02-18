# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-15)

**Core value:** Three equally critical pillars -- semantic search quality, metadata preservation, incremental updates
**Current focus:** Phase 6.3 complete. Ready for Phase 7: Interactive TUI
**Execution strategy:** Phase 6 before full upload (1,721 files) to enrich metadata first

## Current Position

Phase: 6.3 of 7+ (Test Foundation & Canon Governance) -- COMPLETE
Plan: 8 of 8 (ALL COMPLETE)
Status: Phase 6.3 complete. Ready for Phase 7.
Last activity: 2026-02-18 - Completed 06.3-08-PLAN.md (Canon audit + full test suite)

Progress: [#####################] ~100% (34 plans of ~36 estimated total)

Phase 1 Progress: [##########] 3/3 plans -- COMPLETE
Phase 2 Progress: [##########] 4/4 plans -- COMPLETE
Phase 3 Progress: [##########] 3/3 plans -- COMPLETE
Phase 4 Progress: [##########] 5/5 plans -- COMPLETE
Phase 5 Progress: [##########] 4/4 plans -- COMPLETE
Phase 6 Progress: [##########] 5/5 plans -- COMPLETE
Phase 6.1 Progress: [##########] 2/2 plans -- COMPLETE
Phase 6.2 Progress: [##########] 2/2 plans -- COMPLETE
Phase 6.3 Progress: [##########] 8/8 plans -- COMPLETE

## Performance Metrics

**Velocity:**
- Total plans completed: 34
- Average duration: 3.5 min
- Total execution time: 110 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 3/3 | 10 min | 3.3 min |
| 02-upload-pipeline | 4/4 | 17 min | 4.3 min |
| 03-search-and-cli | 3/3 | 13 min | 4.3 min |
| 06-ai-powered-metadata | 5/5 | 24 min | 4.8 min |
| 06.1-entity-extraction | 2/2 | 9 min | 4.5 min |
| 06.2-metadata-enriched-upload | 2/2 | 6 min | 3.0 min |
| 04-quality-enhancements | 5/5 | 24 min | 4.8 min |
| 05-incremental-updates | 4/4 | ~12 min | ~3.0 min |
| 06.3-test-foundation | 8/8 | ~20 min | ~2.5 min |

**Recent Trend:**
- Last 5 plans: 06.3-05 (5 min), 06.3-06 (3 min), 06.3-07 (2 min), 06.3-08 (2 min)
- Trend: Stable at 2-5 min per plan

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

- [04-04]: Append-only event semantics: no update/modify methods, events can only be added
- [04-04]: Session lookup by UUID prefix with ambiguity detection (returns None if 0 or 2+ matches)
- [04-04]: Active session detection via OBJLIB_SESSION env var (static method, no DB needed)
- [04-04]: SessionManager takes sqlite3.Connection directly (not Database wrapper)
- [05-02]: list_store_documents wraps initial list() in _safe_call; pagination fetches bypass circuit breaker
- [05-02]: find_store_document_name checks display_name and name attributes (actual SDK Document schema)
- [05-02]: delete_store_document catches exceptions broadly then inspects string for 404/NOT_FOUND patterns
- [05-03]: Store display name (not Gemini resource name) in library_config for store verification
- [05-03]: Gemini client set to None in dry-run mode to avoid API key requirement
- [05-03]: SyncOrchestrator accepts optional client (None for dry-run)
- [05-03]: Enrichment version computed from sha256 of version string at import time
- [05-03]: mtime epsilon of 1e-6 for float comparison per research pitfall guidance
- [05-04]: Removed exists=True from scan --library to allow custom disk-disconnection error messages
- [05-04]: Mount point derived from library path for accurate disk detection on any external drive
- [05-04]: Upload/enriched-upload check DEFAULT_LIBRARY_ROOT; scan derives mount from user-provided path
- [06.3-01]: Database.__new__(Database) + db.conn + _setup_schema() for in-memory test fixture (bypasses __init__ path validation)
- [06.3-01]: Schema has 17 tables (not 16) -- V7 migration adds library_config table
- [06.3-01]: Duck-typed entity results for save_transcript_entities tests (avoids import cycle)
- [06.3-02]: pyfakefs + in-memory SQLite coexistence pattern: fs patches filesystem, :memory: SQLite avoids C-level open() conflicts
- [06.3-02]: TestClass grouping by concern for readable test output (TestDiscovery, TestHashing, TestChangeDetection, etc.)
- [06.3-03]: build_metadata_filter takes list[str] not dict -- tests adapted to match actual CLI-style "field:value" API
- [06.3-03]: Reranker mock uses model_dump_json() on RankedResults for response.text (matching actual model_validate_json code path)
- [06.3-03]: Two pre-existing test failures noted: test_formatter score bars, test_search _FakeDB missing method
- [06.3-04]: SyncDetector tests use min_file_size=100 for small pyfakefs test files
- [06.3-04]: Safety guard tests need 100+ DB files to exceed max(50, ...) floor threshold
- [06.3-04]: Session ambiguous prefix test creates 50 sessions to guarantee first-char UUID collision
- [06.3-05]: Workflow files placed in ~/.claude/skills/ (global, not project-specific) for reuse across projects
- [06.3-05]: Detection uses mutual exclusion: presence of one workflow's control files rules out others
- [06.3-05]: Ralph detection: .ralph/ + .ralph/PROMPT.md + .ralph/fix_plan.md
- [06.3-05]: BMAD detection: _bmad/ + _bmad/core/ directory
- [06.3-05]: Generic fallback: pyproject.toml / package.json / Cargo.toml / go.mod / README.md
- [06.3-06]: canon-init detection priority: existing _canon_workflow > BMAD > GSD > Ralph > Generic
- [06.3-06]: Ambiguity outputs WARNING listing detected workflows and asks user -- does NOT silently pick one
- [06.3-06]: Generic auto-defaults without asking when no workflow signals found
- [06.3-06]: Canon.json template has 8 placeholders: PROJECT_TITLE, PROJECT_DESCRIPTION, BRANCH, PUBLIC_FOLDERS, EXCLUDE_FOLDERS, EXCLUDE_FILES, RULES, WORKFLOW
- [06.3-06]: SKILL.md is 5-step executable prompt: Detect Workflow, Read Context, Analyze Codebase, Fill Templates, Report
- [06.3-06]: Rules files: GSD 15 rules, Ralph 13 rules, BMAD 14 rules -- curated prose for JSON array insertion
- [06.3-07]: canon-update SKILL.md is 6-step audit: Detect Workflow, Read Canon.json, Scan Codebase, Layer 1 Drift Detection, Update/Report, Layer 2 Advisory
- [06.3-07]: update-docs Canon audit step is read-only -- reports drift but never modifies Canon.json
- [06.3-07]: Layer 2 version check is advisory only -- no auto-update of previousVersions
- [06.3-08]: src/objlib/search and src/objlib/session added to excludeFolders (implementation modules, not public API)
- [06.3-08]: src/objlib/services/ kept in folders despite not existing (aspirational Phase 7 target)
- [06.3-08]: 2 pre-existing test failures confirmed: test_formatter score bars, test_search _FakeDB (not regressions)
- [06.3-08]: Coverage 38% overall; core modules 78-95%; extraction/upload untested (API-dependent)

### Pending Todos

Phase 6.3 complete. Ready for Phase 7 planning.

### Blockers/Concerns

- 2 pre-existing test failures to fix early in Phase 7 (low priority)
- Coverage at 38% overall (extraction/ and upload/ modules need API mocking for meaningful coverage)

## Session Continuity

Last session: 2026-02-18
Stopped at: Completed 06.3-08. Phase 6.3 fully complete. Canon.json audited. Full test suite verified.
Resume file: Phase 7 planning (Interactive TUI)
