# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-15)

**Core value:** Three equally critical pillars -- semantic search quality, metadata preservation, incremental updates
**Current focus:** Phase 3: Search & CLI -- In Progress

## Current Position

Phase: 3 of 5 (Search & CLI)
Plan: 2 of 4 in current phase
Status: In progress
Last activity: 2026-02-16 -- Completed 03-02 (Rich Display Layer)

Progress: [########░░] ~60% (9 plans of ~15 estimated total)

Phase 1 Progress: [##########] 3/3 plans -- COMPLETE
Phase 2 Progress: [##########] 4/4 plans -- COMPLETE
Phase 3 Progress: [#####.....] 2/4 plans

## Performance Metrics

**Velocity:**
- Total plans completed: 9
- Average duration: 4.0 min
- Total execution time: 36 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 3/3 | 10 min | 3.3 min |
| 02-upload-pipeline | 4/4 | 17 min | 4.3 min |
| 03-search-and-cli | 2/4 | 9 min | 4.5 min |

**Recent Trend:**
- Last 5 plans: 02-03 (3 min), 02-04 (4 min), 03-01 (5 min), 03-02 (4 min)
- Trend: Stable at 3-5 min per plan

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: 5 phases derived from 6 requirement categories (SRCH + INTF merged into Phase 3 as they deliver one user capability)
- [Roadmap]: Phase ordering follows scan-upload-query pipeline with zero-API-dependency foundation first
- [01-01]: content_hash indexed but NOT UNIQUE (corrects CLARIFICATIONS-ANSWERED.md; allows same content at different paths)
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
- [03-01]: AppState callback skips init for scan/status/purge/upload/config and --help requests
- [03-01]: get_api_key() adds GEMINI_API_KEY env var fallback (per locked decision #6) alongside keyring
- [03-01]: GeminiSearchClient uses synchronous client.models.generate_content() (not aio)
- [03-01]: Citation confidence aggregated by averaging GroundingSupport scores per chunk
- [03-01]: Renamed CLI get_api_key function to show_api_key to avoid collision with config.get_api_key()
- [03-02]: view command in _SKIP_INIT_COMMANDS -- Gemini init only when --show-related used
- [03-02]: Console injection pattern for testable Rich output (all display functions accept optional Console)
- [03-02]: Tier 1 appends citation references after response text (inline insertion requires segment offsets not always available)

### Pending Todos

None.

### Blockers/Concerns

- Phase 4 research flag: Cross-encoder model selection for philosophy domain, citation prompt engineering, Objectivist terminology mapping need research during planning

## Session Continuity

Last session: 2026-02-16
Stopped at: Phase 3, Plan 2 COMPLETE. Ready for Plan 03 (browse/filter commands).
Resume file: .planning/phases/03-search-and-cli/03-02-SUMMARY.md
