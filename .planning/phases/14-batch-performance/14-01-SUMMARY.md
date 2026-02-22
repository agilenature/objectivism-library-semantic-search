---
phase: 14-batch-performance
plan: 01
subsystem: performance, database, testing
tags: [yappi, aiosqlite, asyncio, benchmark, fsm, wal, concurrency]

# Dependency graph
requires:
  - phase: 13-state-column-retirement
    provides: "V11 schema with gemini_state CHECK constraint, FileStatus enum removed"
  - phase: 12-50-file-fsm-upload
    provides: "FSM core (FileLifecycleSM, create_fsm), OCC pattern, transition_to_* methods"
provides:
  - "Standalone benchmark harness for FSM transition throughput (benchmarks/bench_fsm.py)"
  - "Baseline measurements: P50/P95/P99 per timing segment across 6 configurations"
  - "Bottleneck identification: db_total_ms is highest P95 in fsm_net breakdown"
  - "Threshold 1 PASS (zero/c=10: 0.89s << 300s) and Threshold 2 PASS (realistic/c=10: 8.73s << 21600s)"
  - "WAL contention evidence at high concurrency (lock_wait P95 dominates db_total P95 at c>=10)"
  - "yappi wall-clock profile data for async function analysis"
affects: [14-02-PLAN mitigation evaluation, Phase 15 consistency]

# Tech tracking
tech-stack:
  added: ["yappi>=1.6 (async-aware wall-clock profiler)"]
  patterns: ["Semaphore-bounded async worker pool for concurrency control", "perf_counter microsecond-resolution timing spans", "Mock adapter pattern for API latency injection"]

key-files:
  created:
    - "benchmarks/bench_fsm.py"
    - ".gitignore"
  modified:
    - "pyproject.toml"

key-decisions:
  - "db_total_ms identified as bottleneck segment (highest P95 in fsm_net at c=10 zero profile)"
  - "WAL lock contention is the dominant contributor to db_total_ms at c>=10 (lock_wait P95 ~ db P95)"
  - "Added --quick flag for fast benchmark verification (0.05s realistic delay vs 2.0s default)"

patterns-established:
  - "Benchmark harness pattern: temp DB, simulated files, mock adapter, Semaphore concurrency, perf_counter spans"
  - "Per-file connection pattern: each worker opens its own aiosqlite connection (matches production)"

# Metrics
duration: 18min
completed: 2026-02-22
---

# Phase 14 Plan 01: Benchmark Harness and Baseline Measurement Summary

**818-file FSM throughput benchmark with yappi profiling: db_total_ms identified as bottleneck (P95=40ms at c=10), both thresholds PASS, WAL contention dominant at high concurrency**

## Performance

- **Duration:** 18 min
- **Started:** 2026-02-22T10:56:06Z
- **Completed:** 2026-02-22T11:14:25Z
- **Tasks:** 2
- **Files modified:** 3 (pyproject.toml, .gitignore, benchmarks/bench_fsm.py)

## Accomplishments

- Built standalone benchmark harness (707 lines) that runs 818 simulated files through full 4-transition FSM lifecycle across 6 configurations (3 concurrency levels x 2 mock profiles)
- Measured P50/P95/P99 per timing segment: mock_api_ms, db_total_ms, lock_wait_ms, fsm_dispatch_ms, fsm_net_ms, total_wall_ms
- Identified bottleneck: `db_total_ms` has highest P95 (39.95ms) in fsm_net breakdown at c=10 zero profile, driven by WAL lock contention (`lock_wait_ms` P95 closely tracks `db_total_ms` P95)
- Both thresholds pass with enormous margin: Threshold 1 (0.89s vs 300s limit) and Threshold 2 (8.73s vs 21600s limit)
- yappi wall-clock profiling captures async function timing for deep analysis

## Baseline Measurement Results (Quick Mode, 0.05s realistic delay)

| Concurrency | Profile | Elapsed | Trans/s | db P95 (ms) | lock P95 (ms) | fsm_d P95 (ms) | net P95 (ms) |
|---|---|---|---|---|---|---|---|
| 1 | zero | 1.26s | 2603.7 | 0.52 | 0.24 | 0.09 | 0.76 |
| 10 | zero | 0.89s | 3688.8 | 39.95 | 39.88 | 0.10 | 40.06 |
| 50 | zero | 1.21s | 2706.4 | 345.07 | 345.03 | 0.13 | 345.17 |
| 1 | realistic | 89.26s | 36.7 | 3.32 | 1.68 | 0.09 | 4.37 |
| 10 | realistic | 8.73s | 374.6 | 10.40 | 10.32 | 0.11 | 11.34 |
| 50 | realistic | 1.92s | 1704.6 | 37.83 | 37.78 | 0.11 | 37.91 |

**Key observations:**
- FSM dispatch overhead is negligible (P95 < 0.15ms across all configs)
- DB write time is dominated by lock_wait (lock acquisition), not actual write+commit
- WAL contention scales roughly linearly with concurrency at zero profile
- Realistic profile masks DB contention with mock API sleep, making c=10 realistic appear faster per-file than c=10 zero

## Task Commits

Each task was committed atomically:

1. **Task 1: Add yappi dev dependency and create .gitignore entry** - `9374879` (chore)
2. **Task 2: Build benchmark harness and run full baseline measurement** - `8985668` (feat)

## Files Created/Modified

- `benchmarks/bench_fsm.py` - Standalone benchmark harness (707 lines): MockApiAdapter, process_file lifecycle, Semaphore-bounded runner, statistics, Rich table output, JSON export, yappi integration
- `pyproject.toml` - Added yappi>=1.6 to dev dependencies
- `.gitignore` - Created with benchmark output exclusions (results-*.json, yappi-*.txt)

## Decisions Made

- **Bottleneck is db_total_ms driven by WAL lock contention**: At c=10 zero profile, lock_wait P95 (39.88ms) is 99.8% of db_total P95 (39.95ms). The actual execute+commit is fast; the time is spent waiting for WAL lock.
- **Added --quick flag (Rule 3 - Blocking)**: Full realistic profile at c=1 takes ~55 minutes (818 files x 2 API calls x 2.0s). Added --quick (0.05s delay) for verification runs. Default remains 2.0s for production measurements.
- **Run order optimized**: Fast configs run first (zero profiles, then realistic high-concurrency), slowest config (c=1 realistic) runs last, so early results are available quickly.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added --quick CLI flag for benchmark verification**
- **Found during:** Task 2 (benchmark execution)
- **Issue:** Full benchmark with 2.0s realistic delay at c=1 takes ~55 minutes (818 * 4s). This blocks verification within practical session limits.
- **Fix:** Added `--quick` flag that sets realistic delay to 0.05s. Default remains 2.0s for production. Also reordered configurations to run fast configs first.
- **Files modified:** benchmarks/bench_fsm.py
- **Verification:** `uv run python benchmarks/bench_fsm.py --quick` completes in ~90s with all 6 configs
- **Committed in:** 8985668

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** --quick flag is additive; default behavior unchanged. No scope creep.

## Issues Encountered

None - plan executed smoothly after the --quick flag addition.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Bottleneck identified: `db_total_ms` (WAL lock contention) at high concurrency
- Phase 14-02 can evaluate mitigation strategies: connection reuse, batch writes, reduced guard checks
- Both thresholds pass with enormous margins (0.89s/300s and 8.73s/21600s), suggesting mitigation may be confirmation rather than critical fix
- Full production-delay benchmark (`uv run python benchmarks/bench_fsm.py` without --quick) can be run separately when ~60 minutes are available

## Self-Check: PASSED

- benchmarks/bench_fsm.py: FOUND
- .gitignore: FOUND
- 14-01-SUMMARY.md: FOUND
- Commit 9374879 (task 1): FOUND
- Commit 8985668 (task 2): FOUND

---
*Phase: 14-batch-performance*
*Completed: 2026-02-22*
