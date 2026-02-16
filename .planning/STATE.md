# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-15)

**Core value:** Three equally critical pillars -- semantic search quality, metadata preservation, incremental updates
**Current focus:** Phase 6: AI-Powered Metadata -- Next (Metadata-First Strategy)
**Execution strategy:** Phase 6 before full upload (1,721 files) to enrich metadata first

## Current Position

Phase: 6 of 7 (AI-Powered Metadata - executing out of order)
Plan: Not started
Status: Planning next
Last activity: 2026-02-16 -- Adopted Metadata-First Strategy, will do Phase 6 before full upload

Progress: [#######...] ~60% (10 plans of ~17 estimated total)
**Note:** Executing Phase 6 next (not Phase 4) to enrich metadata before uploading 1,721 files

Phase 1 Progress: [##########] 3/3 plans -- COMPLETE
Phase 2 Progress: [##########] 4/4 plans -- COMPLETE
Phase 3 Progress: [##########] 3/3 plans -- COMPLETE

## Performance Metrics

**Velocity:**
- Total plans completed: 10
- Average duration: 4.2 min
- Total execution time: 42 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 3/3 | 10 min | 3.3 min |
| 02-upload-pipeline | 4/4 | 17 min | 4.3 min |
| 03-search-and-cli | 3/3 | 13 min | 4.3 min |

**Recent Trend:**
- Last 5 plans: 02-03 (3 min), 02-04 (4 min), 03-01 (5 min), 03-02 (4 min), 03-03 (4 min)
- Trend: Stable at 3-5 min per plan

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: 6 phases total (added Phase 6: AI-Powered Metadata Enhancement)
- [Roadmap]: Phase ordering follows scan-upload-query pipeline with zero-API-dependency foundation first
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
- [03-phase]: Fixed Gemini citation display - added two-pass lookup (filename → Gemini ID fallback) to show actual filenames instead of file IDs
- [Phase 6]: Added AI-powered metadata enhancement to roadmap (LLM-based category inference)
- [Phase 7]: Added Interactive TUI to roadmap (Textual-based terminal UI with live search, visual browsing, split-pane views)
- [Phase 5]: Added offline query mode to Phase 5 (query operations work without source disk connected)
- [Execution Order]: Adopted Metadata-First Strategy - executing Phase 6 before Phase 4/5 to enrich metadata (496 unknown files) before full library upload (1,721 files)

### Pending Todos

None.

### Blockers/Concerns

- Phase 4 research flag: Cross-encoder model selection for philosophy domain, citation prompt engineering, Objectivist terminology mapping need research during planning
- Display issues noted in Phase 3: confidence scores showing 0%, metadata enrichment showing Gemini IDs instead of filenames (can be addressed in Phase 4)

## Session Continuity

Last session: 2026-02-16
Stopped at: Phase 3 COMPLETE. Ready for Phase 4 planning or next milestone planning.
Resume file: N/A
