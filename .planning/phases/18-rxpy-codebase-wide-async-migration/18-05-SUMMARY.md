---
phase: 18-rxpy-codebase-wide-async-migration
plan: 05
subsystem: validation
tags: [rxpy, asyncio, migration, validation, gate, regression, canon]

requires:
  - phase: 18-04
    provides: "Tier 1 upload pipeline fully migrated; 5 custom operators; 0 tenacity imports"
  - phase: 18-03
    provides: "Tier 2 extraction pipeline migrated"
  - phase: 18-02
    provides: "Tier 3 services/search migrated"
  - phase: 18-01
    provides: "Spike-validated operator contracts (Q2-Q4)"
provides:
  - "Phase 18 gate PASSED -- all 7 verification criteria met"
  - "Canon.json updated with all 10 migrated modules and 5 custom operators"
  - "CLI bug fix: asyncio.run() wrapper for async query_with_retry"
  - "Phase 18 completion record with full evidence"
affects: [phase-19-planning, canon-updates]

tech-stack:
  added: []
  patterns: ["asyncio.run() bridge for sync CLI calling async RxPY-based methods"]

key-files:
  created:
    - .planning/phases/18-rxpy-codebase-wide-async-migration/18-05-SUMMARY.md
  modified:
    - Canon.json
    - src/objlib/cli.py
    - .planning/STATE.md
    - .planning/ROADMAP.md

key-decisions:
  - "CLI search/view commands use asyncio.run() to bridge sync Typer callback to async query_with_retry"
  - "tenacity remains in pyproject.toml dependencies (zero imports in src/ but removal is out of scope for validation plan)"
  - "No new-lecture upload possible (all 136 UNTRACKED files are non-.txt); check_stability STABLE used as alternative gate"
  - "Canon.json modules section added to document Phase 18 migration at module granularity"

patterns-established:
  - "sync CLI -> async RxPY: use asyncio.run(coroutine) at CLI boundary"

duration: 14min
completed: 2026-02-27
---

# Phase 18 Plan 05: Post-Migration Validation Summary

**Phase 18 gate PASSED: 476 tests green, 0 asyncio primitives outside tui/, check_stability 7/7 STABLE, store-sync 0 orphans, 5 search queries 0 unresolved citations, 7/7 TUI invariants hold, Canon.json updated with 10 migrated modules + 5 custom operators**

## Performance

- **Duration:** 14 min
- **Started:** 2026-02-27T18:22:25Z
- **Completed:** 2026-02-27T18:36:36Z
- **Tasks:** 7
- **Files modified:** 3 (cli.py, Canon.json, ROADMAP.md)

## Accomplishments

- All 7 Phase 18 gate criteria passed with positive evidence
- Found and fixed CLI regression: async query_with_retry called without await (Rule 1 bug)
- Canon.json updated with full module-level documentation of all 10 migrated modules and 5 custom operators
- Phase 18 is now complete -- all async code outside tui/ uses RxPY observables

## Phase 18 Completion Summary

### Verification Results

| Verification | Result | Evidence |
|---|---|---|
| Full pytest suite (SC3) | PASS (476 tests, 37 warnings) | `476 passed, 37 warnings in 44.63s` -- all DeprecationWarnings from RxPY internals |
| Asyncio primitives audit (SC1) | PASS (0 primitives remain) | grep for Semaphore/gather/Event/wait_for/AsyncRetrying/tenacity: 4 matches, all in docstrings/comments describing replacements |
| New-lecture upload (SC4/SC5) | PASS (check_stability alternative) | No uploadable (.txt) UNTRACKED files available (136 untracked are .pdf/.html/.epub/.docx); check_stability 7/7 STABLE, 20/20 files retrievable |
| Pre-existing corpus untouched | PASS (1749 indexed unchanged) | DB state before: indexed=1749, untracked=136; DB state after: identical |
| store-sync 0 new orphans (SC5) | PASS (0 orphans) | `Canonical: 1749, Store: 1749, Orphaned: 0 -- Store is clean` |
| Semantic search citations (SC6) | PASS (5 queries, 0 unresolved) | 5 diverse queries, all return rich results, 0 `[Unresolved file #N]` |
| TUI behavioral invariants (SC7) | PASS (7/7) | `7 passed in 12.13s` -- debounce, enter, stale cancel, filter, history, empty, error |
| Canon.json updated (SC8) | COMPLETE | 10 migrated modules + 5 custom operators + 3 new rules |

### Migration Summary (Phases 18-01 through 18-04)

| Module | Tier | Lines | Patterns Replaced |
|---|---|---|---|
| services/search.py | 3 | 196 | to_thread -> Future-based rx.from_callable |
| services/library.py | 3 | 179 | to_thread -> Future-based rx.from_callable |
| search/client.py | 3 | 146 | @retry -> make_retrying_observable |
| sync/orchestrator.py | 3 | 657 | light async -> observable pipeline |
| extraction/batch_client.py | 2 | 446 | Semaphore/gather/polling -> ops.map+ops.merge/interval |
| extraction/orchestrator.py | 2 | 793 | Semaphore/wave logic -> ops.map+ops.merge/flat_map |
| upload/state.py | 1 | 862 | OCC retry -> occ_transition_async (pure SQL, no asyncio primitives) |
| upload/client.py | 1 | 566 | AsyncRetrying -> make_retrying_observable + Future-based subscription |
| upload/recovery.py | 1 | 1041 | asyncio.wait_for -> ops.timeout |
| upload/orchestrator.py | 1 | 1754 | all asyncio patterns -> full RxPY pipeline |
| upload/_operators.py | -- | 377 | NEW: 5 custom operators |
| **Total** | | **7,017** | |

### Custom Operators (src/objlib/upload/_operators.py)

| Operator | Contract | Replaces |
|----------|----------|----------|
| `occ_transition(fn, max_attempts, base_delay)` | Q3: internal retry on OCCConflictError, NOT outer re-subscribe | Manual OCC retry loops |
| `occ_transition_async(fn, max_attempts, base_delay)` | Async wrapper via Future-based subscription | `.run()` in async context |
| `upload_with_retry(file_record, upload_fn, max_attempts)` | 429-specific retry, full-jitter exponential backoff | In-place for-loop retry |
| `shutdown_gate(source, stop_accepting, force_kill)` | Q4: two-signal system, stop_accepting gates input, force_kill terminates | `asyncio.Event.is_set()` polling |
| `dynamic_semaphore(limit_subject)` | Q2: BehaviorSubject-driven concurrency, in-flight items complete on decrease | `asyncio.Semaphore._value` mutation |

### Key API Decisions (for future reference)

- `asyncio.run(coro)` is NEVER used inside RxPY pipelines -- replaced by `asyncio.create_task(coro)` + `rx.from_future()`
- `Observable.run()` is NEVER used in async contexts -- replaced by Future-based subscription (loop.create_future + subscribe + await)
- Bounded concurrency uses `ops.map(factory).pipe(ops.merge(max_concurrent=N))` -- NOT `ops.flat_map(mapper, max_concurrent=N)` (does not exist in RxPY 3.x)
- Sync CLI commands use `asyncio.run()` to call async RxPY-based methods (search, view)

### Tenacity Dependency Status

- **Imports:** Zero tenacity imports remain across entire `src/`
- **pyproject.toml:** `tenacity>=9.1` still listed as dependency
- **Recommendation:** Can be removed from pyproject.toml in a future cleanup commit; no code references it

### Verbatim Gate Evidence

**check_stability output:**
```
PASS  Assertion 1 -- Count invariant: DB indexed=1749, store docs=1749
PASS  Assertion 2 -- DB->Store (no ghosts): all 1749 indexed files present in store
PASS  Assertion 3 -- Store->DB (no orphans): all 1749 store docs match DB records
PASS  Assertion 4 -- No stuck transitions: 0 files in 'uploading' state
PASS  Assertion 5 -- Search returns results: 5 citations returned
PASS  Assertion 6 -- Citation resolution: all 5 citations resolve to DB records
PASS  Assertion 7 -- Per-file searchability: 20/20 sampled files retrievable
VERDICT: STABLE
```

**store-sync output:**
```
Canonical uploaded file IDs in DB: 1749
Canonical store doc IDs in DB: 1749
Total store documents: 1749
Canonical documents: 1749
Orphaned documents: 0
Store is clean -- nothing to purge.
```

**DB state (unchanged throughout):**
```
indexed|1749
untracked|136
```

**TUI invariant test output:**
```
test_uat_debounce_fires_once PASSED
test_uat_enter_fires_immediately PASSED
test_uat_stale_cancellation PASSED
test_uat_filter_triggers_search PASSED
test_uat_history_navigation PASSED
test_uat_empty_query_clears_immediately PASSED
test_uat_error_containment PASSED
7 passed in 12.13s
```

**Search citation queries (0 unresolved across all 5):**
1. "Rand's theory of knowledge" -- results returned, 0 unresolved
2. "capitalism and individual rights" -- results returned, 0 unresolved
3. "Objectivist ethics egoism" -- results returned, 0 unresolved
4. "induction and concept formation" -- results returned, 0 unresolved
5. "art and aesthetic theory" -- results returned, 0 unresolved

## Task Commits

1. **Tasks 1-4: Regression baseline + audit + upload + search validation** - `93cfffa` (fix: asyncio.run wrapper for CLI async calls)
2. **Task 5: TUI behavioral invariants** - validation only, no files changed
3. **Task 6: Canon.json update** - `ea5f20c` (chore: update Canon.json with Phase 18 migration)

## Decisions Made

1. **CLI asyncio.run() bridge** -- search and view commands call `asyncio.run(query_with_retry(...))` to bridge sync Typer callbacks to async RxPY-based methods. This is the standard pattern for sync-to-async bridges at CLI boundaries.
2. **check_stability as upload alternative** -- all 136 UNTRACKED files are non-.txt formats (.pdf, .epub, .html, .docx). Since the upload pipeline restricts to .txt files, no new-lecture upload was possible. check_stability STABLE (7/7, 20/20) validates the migrated pipeline through the search path instead.
3. **tenacity dependency retained** -- zero imports remain but removing from pyproject.toml is a separate cleanup task, not part of this validation plan.
4. **Canon.json modules section** -- added a structured `modules` section at the JSON level to document each migrated module with tier, patterns replaced, and interface descriptions. This provides machine-readable documentation of the migration.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] CLI search/view commands call async query_with_retry without await**
- **Found during:** Task 4 (search citation validation)
- **Issue:** Phase 18-02 made `GeminiSearchClient.query_with_retry()` async (returns coroutine), but the CLI's `search` command and `view --show-related` command called it synchronously without `await`. This caused `AttributeError: 'coroutine' object has no attribute 'candidates'`.
- **Fix:** Wrapped both call sites in `asyncio.run()`. Added `import asyncio` to both function bodies (matching the existing pattern used by 9 other CLI commands).
- **Files modified:** `src/objlib/cli.py` (2 call sites + 2 imports)
- **Verification:** All 476 tests pass; 5 search queries return results successfully
- **Committed in:** `93cfffa`

---

**Total deviations:** 1 auto-fixed (Rule 1 bug -- CLI async bridge missing)
**Impact on plan:** Essential fix for CLI search functionality. The RxPY migration of search/client.py (Plan 18-02) changed the interface but the CLI caller was not updated. This is exactly the kind of regression the validation plan exists to catch.

## Issues Encountered

None beyond the CLI async bridge bug documented above.

## User Setup Required

None -- no external service configuration required.

## Phase 18 Gate Status

**COMPLETE** -- All 7 verification criteria passed. Codebase-wide RxPY migration is done.

| Gate Criterion | Status |
|---|---|
| Full pytest suite passes | PASS (476 tests) |
| grep audit: 0 asyncio primitives outside tui/ | PASS |
| New-lecture upload OR check_stability STABLE | PASS (STABLE 7/7) |
| store-sync: 0 new orphans | PASS (0 orphans) |
| 5 search queries: 0 unresolved citations | PASS |
| 7 TUI behavioral invariants hold | PASS (7/7) |
| Canon.json updated | COMPLETE |

## Next Phase Readiness

- Phase 18 complete. All async code outside `tui/` now uses RxPY observables.
- 476 tests pass across the entire test suite.
- 1749 indexed files confirmed stable; 0 orphaned store documents.
- tenacity can be removed from pyproject.toml in a future cleanup.
- Phase 17 Plans 17-02 through 17-04 remain for TUI-layer RxPY pipeline (TUI uses its own reactive patterns via Textual's event system + RxPY integration from the Phase 17 spike).

## Self-Check: PASSED

- 18-05-SUMMARY.md: FOUND
- Canon.json: FOUND, VALID JSON
- STATE.md: FOUND, updated
- ROADMAP.md: FOUND, updated
- Commit 93cfffa: FOUND (CLI async bridge fix)
- Commit ea5f20c: FOUND (Canon.json update)
- Tests: 476 passed, 37 warnings

---
*Phase: 18-rxpy-codebase-wide-async-migration*
*Completed: 2026-02-27*
