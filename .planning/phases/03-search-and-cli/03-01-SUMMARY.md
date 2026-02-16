---
phase: 03-search-and-cli
plan: 01
subsystem: search, api, cli
tags: [gemini, file-search, tenacity, typer, rich, citations, grounding-metadata, aip-160]

# Dependency graph
requires:
  - phase: 02-upload-pipeline
    provides: Gemini File Search store with uploaded files and custom_metadata
provides:
  - GeminiSearchClient with query_with_retry (exponential backoff + jitter)
  - Citation extraction from GroundingMetadata with confidence aggregation
  - Citation enrichment via SQLite filename-to-metadata lookup
  - AIP-160 metadata filter builder from CLI --filter syntax
  - AppState callback for Gemini client initialization
  - get_api_key() with keyring + GEMINI_API_KEY env var fallback
  - objlib search command with --filter, --limit, --model options
affects: [03-02 display formatting, 03-03 browse/filter commands, 04 ranking refinement]

# Tech tracking
tech-stack:
  added: []
  patterns: [AppState callback with lazy init, synchronous Gemini query via generate_content, AIP-160 filter builder, per-chunk confidence aggregation from GroundingSupport]

key-files:
  created:
    - src/objlib/search/__init__.py
    - src/objlib/search/client.py
    - src/objlib/search/citations.py
    - tests/test_search.py
  modified:
    - src/objlib/models.py
    - src/objlib/config.py
    - src/objlib/database.py
    - src/objlib/cli.py

key-decisions:
  - "AppState callback skips init for scan/status/purge/upload/config commands and --help requests"
  - "get_api_key() adds GEMINI_API_KEY env var fallback (per locked decision #6) alongside existing keyring"
  - "GeminiSearchClient uses synchronous client.models.generate_content() (not aio) for simpler Typer integration"
  - "resolve_store_name() uses synchronous client.file_search_stores.list() iterator"
  - "Citation confidence aggregated by averaging all GroundingSupport scores referencing each chunk"
  - "Renamed CLI get_api_key command function to show_api_key to avoid collision with config.get_api_key()"

patterns-established:
  - "AppState callback pattern: ctx.obj = AppState(...) with _SKIP_INIT_COMMANDS set"
  - "get_state(ctx) type-safe accessor for AppState with None check"
  - "extract_citations() uses getattr(..., None) at every level for safe None handling"
  - "build_metadata_filter() validates field names against FILTERABLE_FIELDS frozenset"

# Metrics
duration: 5min
completed: 2026-02-16
---

# Phase 3 Plan 01: Search Query Layer Summary

**Gemini File Search query client with citation extraction, metadata enrichment, AIP-160 filter builder, and `objlib search` CLI command backed by 21 unit tests**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-16T13:11:31Z
- **Completed:** 2026-02-16T13:16:17Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Built complete query pipeline: user query -> Gemini API -> grounding metadata -> enriched citations
- GeminiSearchClient with 3-attempt retry (exponential backoff + jitter via tenacity)
- Citation extraction safely handles all None cases in GroundingMetadata hierarchy
- AIP-160 filter builder converts CLI `--filter course:OPAR` to `course="OPAR"` with field validation
- AppState callback initializes Gemini client only for search commands, leaving existing commands unaffected
- 21 unit tests covering filter builder, citation extraction, enrichment, and API key loading

## Task Commits

Each task was committed atomically:

1. **Task 1: Create search subpackage with GeminiSearchClient, citation extraction, and data models** - `fb58ebd` (feat)
2. **Task 2: Wire search command into CLI with AppState callback and add tests** - `1b9ee7a` (feat)

## Files Created/Modified
- `src/objlib/search/__init__.py` - Search subpackage public API
- `src/objlib/search/client.py` - GeminiSearchClient with query_with_retry and store name resolution
- `src/objlib/search/citations.py` - Citation extraction, enrichment, and AIP-160 filter builder
- `src/objlib/models.py` - Citation, SearchResult, AppState dataclasses
- `src/objlib/config.py` - get_api_key() with keyring + env var fallback
- `src/objlib/database.py` - get_file_metadata_by_filenames() for citation enrichment
- `src/objlib/cli.py` - AppState callback, search command, get_state() helper
- `tests/test_search.py` - 21 unit tests for search functionality

## Decisions Made
- AppState callback skips initialization for existing commands and --help requests to avoid unnecessary API calls
- get_api_key() adds GEMINI_API_KEY env var fallback alongside existing keyring (per locked decision #6)
- Synchronous Gemini client methods used throughout (no asyncio.run wrapper needed for generate_content)
- Citation confidence aggregated by averaging GroundingSupport scores per chunk (not max)
- Renamed CLI `get_api_key` function to `show_api_key` to avoid name collision with new `config.get_api_key()`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added --help skip in AppState callback**
- **Found during:** Task 2 (CLI wiring)
- **Issue:** `objlib search --help` triggered the AppState callback, which attempted to resolve the Gemini store and failed with an API error
- **Fix:** Added `--help`/`-h` check in sys.argv to skip initialization when help is requested
- **Files modified:** src/objlib/cli.py
- **Verification:** `objlib search --help` now shows help text without API calls
- **Committed in:** 1b9ee7a (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential fix for CLI usability. No scope creep.

## Issues Encountered
None beyond the --help deviation documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Search query pipeline complete and ready for Plan 02 (three-tier display formatting)
- Basic citation display works; Plan 02 will add Rich formatting with score bars and panels
- All existing commands (scan, status, purge, upload, config) unaffected

## Self-Check: PASSED

All 8 files verified present. Both commits (fb58ebd, 1b9ee7a) verified in git log.

---
*Phase: 03-search-and-cli*
*Completed: 2026-02-16*
