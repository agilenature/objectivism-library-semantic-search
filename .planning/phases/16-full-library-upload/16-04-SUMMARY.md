---
phase: 16-full-library-upload
plan: 04
subsystem: search, tui
tags: [gemini-file-search, top_k, textual, tui, citation-ranking, scroll-hints]

# Dependency graph
requires:
  - phase: 03-search-and-cli
    provides: GeminiSearchClient, search CLI command, citation extraction pipeline
  - phase: 07-interactive-tui
    provides: ResultItem, ResultsList, ObjlibApp TUI framework
provides:
  - top_k=20 default in GeminiSearchClient.query() for 4x more retrieval
  - --top-k N CLI flag on search command
  - Per-citation rank display "[N / total]" in TUI results
  - "N citations retrieved" banner in TUI results and status bar
  - Scroll hints for large result sets (>3 citations)
affects: [16-03, 17-rxpy-tui-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "top_k parameter threading: client -> service -> TUI/CLI"
    - "Rank display pattern: '[N / total]' prefix on citation cards"
    - "Scroll affordance: conditional hint widget when results > threshold"

key-files:
  created: []
  modified:
    - src/objlib/search/client.py
    - src/objlib/services/search.py
    - src/objlib/cli.py
    - src/objlib/tui/widgets/results.py
    - src/objlib/tui/app.py

key-decisions:
  - "top_k=20 default across entire pipeline (client, service, CLI, TUI)"
  - "Flat chunk list display (not grouped by file) per locked decision #3"
  - "Rank = chunk index + 1 (1-based), displayed as '[1 / 20]' in bold cyan"
  - "Scroll hints shown when result count > 3 (threshold for visible overflow)"

patterns-established:
  - "ResultItem accepts optional rank/total for backward-compatible rank display"
  - "Scroll hint widget mounted as last child with .scroll-hint CSS class"

# Metrics
duration: 6min
completed: 2026-02-23
---

# Phase 16 Plan 04: TUI-09 Search Quality Summary

**top_k=20 retrieval default threaded through search pipeline with per-citation rank display, citation count banner, and scroll hints in TUI**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-23T13:52:26Z
- **Completed:** 2026-02-23T13:58:27Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- GeminiSearchClient.query() and query_with_retry() now accept top_k=20 parameter, passed to types.FileSearch SDK constructor
- SearchService.search() threads top_k through to the Gemini SDK call via asyncio.to_thread
- CLI search command exposes --top-k N flag (default 20) for user override
- TUI ResultItem displays rank as "[1 / 20]" prefix before filename in bold cyan
- TUI ResultsList shows "N citations retrieved" banner at top of results
- Scroll hints appear when citations exceed 3 items: up/down arrows and PgUp/PgDn
- Status bar shows "N citations retrieved" consistent with results banner
- All 463 existing tests pass with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Thread top_k through search pipeline and add CLI flag** - `9a4a881` (feat)
2. **Task 2: TUI citation count, rank display, and scroll hints** - `cc55355` (feat)

Note: cli.py top_k changes were committed in parallel plan 16-01 commit `72d7aad` which executed concurrently in Wave 1.

## Files Created/Modified
- `src/objlib/search/client.py` - Added top_k: int = 20 to query() and query_with_retry(), passes to FileSearch constructor
- `src/objlib/services/search.py` - Added top_k parameter to search(), threads to query_with_retry call
- `src/objlib/cli.py` - Added --top-k CLI flag to search command (committed in parallel 16-01)
- `src/objlib/tui/widgets/results.py` - ResultItem rank display, ResultsList citation banner and scroll hints
- `src/objlib/tui/app.py` - TUI passes top_k=20 to search service, status bar shows citation count

## Decisions Made
- top_k=20 as default (matches TUI-09 requirement, 4x more results than server default of ~5)
- Flat chunk list (not grouped by file) per locked decision #3 from CONTEXT.md
- Rank = chunk index + 1, displayed as "[N / total]" in bold cyan before filename
- Scroll hint threshold set to >3 results (typical visible viewport fits ~3 cards)
- ResultItem rank/total parameters are optional (None) for backward compatibility with bookmark display

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- cli.py changes were committed by parallel plan 16-01 (also Wave 1, executing concurrently) -- no conflict, changes identical
- Git HEAD advanced between staging and commit for Task 1 due to parallel execution -- resolved by re-running commit

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- TUI-09 requirement fully implemented
- Phase 16 SC7 satisfied: citation count, rank position, and scroll hints
- Ready for 16-03 (TUI integration smoke test) after upload plans complete
- top_k parameter available for Phase 17 RxPY TUI pipeline

---
*Phase: 16-full-library-upload*
*Completed: 2026-02-23*
