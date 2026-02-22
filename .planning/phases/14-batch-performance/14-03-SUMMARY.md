---
phase: 14-batch-performance
plan: 03
subsystem: benchmarking
tags: [aiosqlite, WAL, shared-connection, performance, mitigation]

# Dependency graph
requires:
  - phase: 14-batch-performance (14-01)
    provides: bench_fsm.py benchmark harness with 6-config baseline measurements
provides:
  - "--shared-connection flag in bench_fsm.py for WAL lock contention mitigation"
  - "results-mitigation-*.json with before/after P95 comparison data"
  - "SC2 gap closure: at least one mitigation tested with before/after measurements"
affects: [15-consistency-store-sync, 16-full-library-upload]

# Tech tracking
tech-stack:
  added: []
  patterns: [shared-aiosqlite-connection-mitigation]

key-files:
  modified:
    - benchmarks/bench_fsm.py
  created:
    - benchmarks/results-mitigation-20260222-114707.json

key-decisions:
  - "Shared connection mitigation eliminates 98% of WAL lock contention at c=10 -- available as production option if needed"
  - "Mitigation runs as 7th config after standard 6 configs, reusing same temp DB"

patterns-established:
  - "Before/after mitigation measurement pattern: run baseline configs, then re-run target config with mitigation, compare P95 deltas"

# Metrics
duration: 6min
completed: 2026-02-22
---

# Phase 14 Plan 03: SC2 Gap Closure Summary

**Shared-connection mitigation reduces WAL lock contention P95 by 98.1% (40.65ms to 0.77ms) at c=10 zero profile -- SC2 gap closed**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-22T11:45:52Z
- **Completed:** 2026-02-22T11:52:00Z
- **Tasks:** 1
- **Files modified:** 1 modified, 1 created

## Accomplishments
- Added `--shared-connection` CLI flag to bench_fsm.py enabling shared aiosqlite connection mitigation
- Modified `run_benchmark()` to accept optional `shared_conn` parameter, routing workers through a single connection
- Mitigation run at c=10 zero profile: all 818 files indexed, 28,638 trans/s (vs 3,287 baseline) -- 8.7x throughput improvement
- Before/after Rich table and JSON artifact produced with P95 comparisons across 4 segments
- SC2 ("at least one mitigation tested with before/after measurements") fully satisfied

## Benchmark Results: Before vs After

| Segment | Baseline P95 | Mitigation P95 | Delta |
|---------|-------------|----------------|-------|
| db_total_ms | 40.95 ms | 1.27 ms | -96.9% (-39.68ms) |
| lock_wait_ms | 40.65 ms | 0.77 ms | -98.1% (-39.88ms) |
| fsm_dispatch_ms | 0.09 ms | 0.03 ms | -70.4% (-0.06ms) |
| fsm_net_ms | 41.17 ms | 1.34 ms | -96.8% (-39.83ms) |

**Key insight:** Shared connection eliminates cross-connection WAL lock contention entirely. All 10 concurrent workers queue through one connection's internal serialization instead of fighting for the WAL write lock across 10 separate connections. This confirms the Phase 14-01 bottleneck identification (lock_wait = 99% of db_total at c=10 zero) was correct, and the mitigation directly addresses it.

**Production relevance:** With realistic API latency (2.0s per call), WAL contention is already negligible (API calls distribute DB writes in time). The shared connection is available as a safety valve if future workloads increase DB write density.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add --shared-connection flag and shared connection code path** - `4a9ac75` (perf)

## Files Created/Modified
- `benchmarks/bench_fsm.py` - Added --shared-connection flag, shared_conn parameter to run_benchmark(), mitigation run block with comparison table and JSON output
- `benchmarks/results-mitigation-20260222-114707.json` - Mitigation benchmark results with baseline, mitigation_run, and comparison data

## Decisions Made
- Shared connection mitigation chosen as simplest possible intervention: single aiosqlite.connect() opened before workers, passed to all via shared_conn parameter
- Mitigation runs after yappi stats section but before cleanup, reusing same temp DB (just needs a reset_files() call)
- Results JSON force-added despite gitignore pattern (benchmarks/results-*.json) since it is a required plan artifact for SC2 evidence

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 14 fully complete (all 3 plans done, including gap closure)
- SC2 ("at least one mitigation tested with before/after measurements") satisfied
- Phase 15 remains unblocked (was already unblocked after 14-02 VLID-06 gate PASS)
- All 459 tests passing, no regression

## Self-Check: PASSED

- [x] `benchmarks/bench_fsm.py` contains "shared_connection" (4 occurrences)
- [x] `benchmarks/results-mitigation-20260222-114707.json` exists (3,592 bytes)
- [x] Commit `4a9ac75` found in git log

---
*Phase: 14-batch-performance*
*Completed: 2026-02-22*
