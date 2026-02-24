---
phase: 14-batch-performance
verified: 2026-02-22T11:57:11Z
status: passed
score: 3/3 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 2/3
  gaps_closed:
    - "At least one mitigation is tested with before/after measurements (SC2)"
  gaps_remaining: []
  regressions: []
human_verification: []
---

# Phase 14: Batch Performance Benchmark Verification Report

**Phase Goal:** FSM transition overhead is measured (not estimated) under realistic batch conditions, the bottleneck is identified, and an acceptable throughput is defined with a tested mitigation
**Verified:** 2026-02-22T11:57:11Z
**Status:** passed
**Re-verification:** Yes -- after gap closure via 14-03 plan (SC2 gap closed by --shared-connection mitigation)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 818 simulated files complete full UNTRACKED->UPLOADING->PROCESSING->INDEXED cycle at concurrency=1, =10, =50 with P50/P95/P99 per segment reported | VERIFIED | benchmarks/results-20260222-112001.json: file_count=818, total_transitions=3272, 6 configurations (c=1/10/50 x zero/realistic), all 818 files indexed per config, segment stats present for mock_api_ms, db_total_ms, lock_wait_ms, fsm_dispatch_ms, fsm_net_ms, total_wall_ms |
| 2 | Bottleneck identified by highest P95 in fsm_net breakdown at c=10 zero profile; Threshold 1 (zero/c=10 <=5min) and Threshold 2 (realistic/c=10 <=6h) evaluated as PASS or FAIL | VERIFIED | JSON bottleneck: db_total_ms (P95=50.41ms, evidence string present). Threshold 1: 1.03s vs 300s = PASS. Threshold 2: 9.03s vs 21600s = PASS. lock_wait_ms P95=49.90ms confirms WAL contention as root cause. |
| 3 | At least one mitigation is tested (batch DB writes, async state writes, or reduced guard checks) with before/after measurements in a Rich table AND results saved to JSON | VERIFIED | --shared-connection flag added to bench_fsm.py (line 517). run_benchmark() accepts shared_conn parameter (line 273). Mitigation run at c=10 zero: indexed_count=818, trans/s=28637 vs 3287 baseline (8.7x). Rich comparison table (lines 781-803) prints before/after P95 for 4 segments. JSON saved to results-mitigation-20260222-114707.json with baseline, mitigation_run, comparison keys. lock_wait P95: 40.65ms -> 0.77ms (-98.1%). |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `benchmarks/bench_fsm.py` | Standalone benchmark harness with --shared-connection flag | VERIFIED | 846 lines (was 707; 139 lines added for mitigation). --shared-connection at line 517. shared_conn parameter at line 273. Rich comparison table at lines 781-803. Mitigation run block at lines 708-824. |
| `benchmarks/results-20260222-112001.json` | Baseline benchmark results with all required fields | VERIFIED | file_count=818, total_transitions=3272, 6 configurations, bottleneck dict, P50/P95/P99 per segment per config, threshold_1_verdict in c=10 zero config |
| `benchmarks/results-mitigation-20260222-114707.json` | Mitigation benchmark results with before/after comparison | VERIFIED | 3,592 bytes. Keys: timestamp, mitigation, description, baseline, mitigation_run, comparison. comparison contains 4 segments each with baseline_p95, mitigation_p95, delta_ms, delta_pct. |
| `benchmarks/yappi-20260222-112001.txt` | yappi wall-clock profile data | VERIFIED | 59-line pstat file exists |
| `.gitignore` | Excludes benchmark output files | VERIFIED | Contains `benchmarks/results-*.json` and `benchmarks/yappi-*.txt` |
| `pyproject.toml` | yappi in dev dependencies | VERIFIED | `yappi>=1.6` at line 33 in optional-dependencies dev list |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `bench_fsm.py` | `src/objlib/upload/fsm.py` | `from objlib.upload.fsm import create_fsm` (line 36), used at line 167 | WIRED | create_fsm("untracked") called per file, fsm.start_upload()/complete_upload()/complete_processing() called for FSM validation |
| `bench_fsm.py` | aiosqlite (temp DB) | Raw SQL UPDATE with OCC guard (version=? AND gemini_state=?) per transition | WIRED | Matches production OCC pattern from AsyncUploadStateManager, lock_wait_ms timed separately from db_write total |
| `bench_fsm.py` --shared-connection | Mitigation run block | `if args.shared_connection:` at line 711, `async with aiosqlite.connect(db_path) as shared_db:` at line 721, `shared_conn=shared_db` passed at line 732 | WIRED | Single shared connection opened before run, passed to all workers, Rich table printed at console.print(compare_table), JSON written to results-mitigation-{timestamp}.json |
| `14-03-SUMMARY.md` | `benchmarks/results-mitigation-20260222-114707.json` | Commit 4a9ac75 referenced; before/after table in SUMMARY matches JSON comparison values | WIRED | SUMMARY shows db_total_ms: 40.95->1.27ms (-96.9%), lock_wait_ms: 40.65->0.77ms (-98.1%); JSON comparison.lock_wait_ms.delta_pct = -98.1 -- exact match |

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| SC1: FSM throughput measured (transitions/sec, elapsed, P95 per segment) under 818-file batch across >= 3 concurrency levels | SATISFIED | 6 configs (c=1/10/50 x zero/realistic), all 818 files reach indexed state, all segment stats recorded |
| SC2: Bottleneck identified AND at least one mitigation tested with before/after measurements in Rich table AND results saved to JSON | SATISFIED | Bottleneck: db_total_ms (WAL contention via lock_wait_ms). Mitigation: --shared-connection, lock_wait P95 -98.1%. Rich table at lines 781-803. JSON at results-mitigation-20260222-114707.json. |
| SC3: Explicit threshold defined (Threshold 1: zero/c=10 <=5min, Threshold 2: realistic/c=10 <=6h) and throughput meets it | SATISFIED | Threshold 1: 1.03s vs 300s (PASS, 291x margin). Threshold 2: 9.03s vs 21600s (PASS, 2393x margin). Both thresholds printed in harness output and recorded in JSON. |

### Anti-Patterns Found

None.

### Human Verification Required

None -- all checks are automated (file structure, JSON content, code structure, test suite).

### Re-verification: Gap Closure Assessment

**Previous gap:** SC2 failed -- no coded mitigation, no before/after measurements, qualitative analysis only.

**Gap closure evidence (14-03):**

1. `--shared-connection` flag implemented at `bench_fsm.py` line 517 (CLI argument parser), confirmed by grep showing 8 occurrences of "shared_conn" and "shared_connection" in the file.

2. `run_benchmark()` accepts `shared_conn: "aiosqlite.Connection | None" = None` parameter (line 273), with conditional branching at line 286 that routes all workers through the shared connection when provided.

3. Mitigation benchmark executed at c=10 zero profile: all 818 files reached indexed state (indexed_count=818 confirmed in JSON), throughput 28,637 trans/s vs 3,287 baseline (8.7x improvement).

4. Rich comparison table (lines 781-803) prints "Before vs After: Shared Connection Mitigation (c=10, zero profile)" with 4 rows (db_total_ms, lock_wait_ms, fsm_dispatch_ms, fsm_net_ms), each showing baseline P95, mitigation P95, and colored delta string.

5. `results-mitigation-20260222-114707.json` exists (3,592 bytes) with keys: timestamp, mitigation ("shared_connection"), description, baseline (c=10 zero config with full segment stats), mitigation_run (mode="shared_connection", full segment stats), comparison (4 segments with delta_ms and delta_pct).

6. Comparison values cross-checked against SUMMARY table -- exact match on all 4 delta_pct values.

**Regressions:** None. All 459 tests pass (27.88s). SC1 and SC3 artifacts unchanged.

---

_Verified: 2026-02-22T11:57:11Z_
_Verifier: Claude (gsd-verifier)_
