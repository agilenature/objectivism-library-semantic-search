---
phase: 14-batch-performance
generated: 2026-02-22
mode: yolo
synthesis: multi-provider (OpenAI gpt-5.2-2025-12-11, Gemini Pro, Perplexity Sonar Deep Research)
---

# CONTEXT.md — Phase 14: Wave 6 — Batch Performance Benchmark

**Generated:** 2026-02-22
**Phase Goal:** FSM transition overhead is measured (not estimated) under realistic batch conditions, the bottleneck is identified, and an acceptable throughput is defined with a tested mitigation.
**Requirements:** VLID-06
**Synthesis Source:** Multi-provider AI analysis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research)

---

## Overview

Phase 14 is a measurement phase, not a feature phase. It benchmarks the async FSM pipeline (python-statemachine 2.6.0 + aiosqlite WAL) under a simulated 818-file batch using mocked API latencies. The core challenge is that mocked API latencies (~2s per call) dwarf all other overhead — unless the benchmark carefully isolates FSM+DB overhead from mock sleep time, it will measure `asyncio.sleep` rather than the actual bottleneck.

All 3 providers converged on 5 consensus areas, each of which would block valid measurement if left undefined.

**Confidence markers:**
- ✅ **Consensus** — All 3 providers identified this as critical
- ⚠️ **Recommended** — 2 providers identified this as important
- 🔍 **Needs Clarification** — 1 provider identified, potentially important

---

## Gray Areas Identified

### ✅ 1. Benchmark Metric Definition (Consensus)

**What needs to be decided:**
What exactly counts as one "transition" for timing purposes? Is the measured unit:
- (A) End-to-end from `await fsm.trigger()` to DB commit (includes mock sleep)
- (B) Net FSM+DB overhead only (wall time minus mock sleep duration)
- (C) Both, with separate labels

**Why it's ambiguous:**
VLID-06 lists mock latency as a potential bottleneck alongside guard check, state write, and WAL serialization — but if mock sleep dominates (2s per call vs. <50ms overhead), measuring combined time renders the FSM contributions invisible. Different timing boundaries produce incomparable metrics.

**Provider synthesis:**
- **OpenAI:** Measure both — primary "end-to-end transition latency" (trigger→DB commit) and secondary "pure FSM overhead" (excluding DB + mock sleep).
- **Gemini:** Record two distinct durations: wall clock time and compute/IO time (wall clock minus mock sleep duration). Use compute/IO time for bottleneck identification.
- **Perplexity:** Benchmark must separate FSM transition overhead (milliseconds) from API latency (seconds); propose explicit span timing per stage.

**Proposed decision:**
Record **three labeled timings per file**:
1. `mock_api_ms` — cumulative time spent in `asyncio.sleep()` mock calls
2. `db_total_ms` — total time in aiosqlite transactions (includes lock waits)
3. `fsm_net_ms` = total_ms − mock_api_ms (i.e., "overhead excluding API")

The VLID-06 bottleneck report compares `db_total_ms` vs `fsm_net_ms` to identify where FSM overhead lives.

**Confidence:** ✅ All 3 providers agreed this is the critical measurement validity issue.

---

### ✅ 2. Concurrency Model (Consensus)

**What needs to be decided:**
How many files are processed concurrently? Is there a semaphore/bounded worker pool? Sequential (=1) or uncapped (`gather(*all_818)`)?

**Why it's ambiguous:**
Running 818 uncapped tasks will overwhelm SQLite WAL with simultaneous write attempts, causing `database is locked` errors. Running strictly sequential hides all contention effects. The "realistic batch" concurrency is not specified anywhere.

**Provider synthesis:**
- **OpenAI:** Bounded `asyncio.TaskGroup` + Semaphore (default 32), per-file sequential transitions, CLI flags for `--concurrency`.
- **Gemini:** `asyncio.Semaphore(50)` default; don't run 818 tasks uncapped.
- **Perplexity:** Three-configuration matrix — sequential (=1), target production (=4), stress (=16).

**Proposed decision:**
Run **three concurrency configurations** in sequence: `concurrency=1` (sequential baseline), `concurrency=10` (primary target), `concurrency=50` (stress test). Use `asyncio.Semaphore(N)` for all. The primary VLID-06 metric uses `concurrency=10` as the representative batch run. Results report all three.

**Confidence:** ✅ All 3 providers agreed an explicit semaphore is required; bounded pool is not optional.

---

### ✅ 3. Mocked API Latency Modeling (Consensus)

**What needs to be decided:**
How do mocked Gemini calls behave? Constant, random, or seeded? Where is the delay injected? What latency values represent reality?

**Why it's ambiguous:**
The benchmark requires "no real API calls" but must produce meaningful throughput numbers. If mock latency is random without a seed, before/after mitigation comparisons are noisy. If latency is zero, the benchmark measures raw Python speed, not realistic pressure on the async event loop.

**Provider synthesis:**
- **OpenAI:** Named profiles: `zero`, `p50=200ms/p95=800ms`, `rate-limited`. Fixed RNG seed per run recorded in output. Delay injected inside mock adapter, not inside FSM core.
- **Gemini:** Run at mock latency=0s to stress FSM/DB specifically; also run at realistic latency to confirm concurrency model.
- **Perplexity:** Three-tier model: constant 2s (baseline), normal distribution mean=2s/σ=0.5s (realistic), concurrent load-dependent.

**Proposed decision:**
Two standard latency profiles for the benchmark:
- `--mock-profile=zero` — `asyncio.sleep(0)`, stress-tests pure FSM+DB overhead
- `--mock-profile=realistic` — `asyncio.sleep(2.0)` constant, models production API latency

Both use a fixed seed=42 for reproducibility. Bottleneck identification runs with `zero` profile. Throughput threshold validation runs with `realistic` profile. Results label which profile was used.

**Confidence:** ✅ All 3 providers agreed deterministic, configurable profiles are required.

---

### ✅ 4. Acceptable Throughput Threshold Definition (Consensus)

**What needs to be decided:**
What is the explicit "X hours" threshold that defines success for VLID-06? Currently undefined in the requirements.

**Why it's ambiguous:**
VLID-06 says "acceptable throughput threshold defined explicitly" but provides only an example. Without a pre-committed number, the benchmark has no pass/fail gate — any measured throughput could be declared acceptable post-hoc.

**Provider synthesis:**
- **OpenAI:** ≥15 transitions/sec under p50=200ms/p95=800ms profile; full 818-file cycle in ≤4 minutes on dev laptop (FSM+DB overhead only); extrapolated 1,748 files in ≤10 minutes.
- **Gemini:** "System must sustain 60 transitions/minute (simulating API rate limit) with CPU < 50% and P95 DB write latency < 100ms." Target: saturate API rate limit without DB becoming the bottleneck.
- **Perplexity:** Three-tier: Stretch=3h, Acceptable=6h, Fallback=12h for 818 files at realistic API latency.

**Proposed decision:**
Separate two thresholds:
1. **FSM+DB overhead threshold** (zero-latency profile): Full 818-file batch (3,272 transitions total) completes in ≤ 5 minutes. This is the gate for "FSM overhead does not impede the upload."
2. **Realistic throughput threshold** (realistic profile, concurrency=10): 818 files complete in ≤ 6 hours. This is the gate for "full library upload is feasible."

Both thresholds must be met for VLID-06 to pass.

**Confidence:** ✅ All 3 providers agreed explicit thresholds are blocking — without them the benchmark has no pass/fail.

---

### ✅ 5. Bottleneck Attribution Instrumentation (Consensus)

**What needs to be decided:**
How to identify which segment is the bottleneck: guard check DB read, FSM transition logic, mock API latency, DB write, or WAL lock wait?

**Why it's ambiguous:**
"Bottleneck identified" requires instrumenting the right points. Without segment-level timing, identifying the bottleneck is just an opinion. cProfile is not async-aware and will misattribute time.

**Provider synthesis:**
- **OpenAI:** Structured tracing spans: `guard_db_read_ms`, `fsm_transition_logic_ms`, `mock_api_ms`, `db_write_ms`, `wal_wait_ms`. Emit per-transition log + aggregated summary.
- **Gemini:** Measure net overhead = wall clock minus mock sleep; identify bottleneck in that residual.
- **Perplexity:** Three-tool strategy — cProfile (initial hot-spot), yappi (asyncio-aware coroutine profiling), py-spy (low-overhead validation). yappi correctly separates wall time from CPU time for coroutines.

**Proposed decision:**
Use **yappi** for the primary bottleneck identification (async-aware, separates CPU from I/O wait). Supplement with explicit timing spans in the harness:
- `mock_api_ms` (cumulative sleep time)
- `db_write_ms` (aiosqlite begin→commit)
- `lock_wait_ms` (BEGIN IMMEDIATE acquisition time)
- `fsm_dispatch_ms` (python-statemachine overhead only)

Print P50/P95/P99 per segment. The segment with the highest P95 is declared the bottleneck.

**Confidence:** ✅ All 3 providers agreed segment-level attribution is required; cProfile alone is insufficient for async code.

---

### ⚠️ 6. WAL Serialization Specific Measurement (Recommended)

**What needs to be decided:**
How to specifically measure WAL write lock contention (rather than lumping it into "DB write time").

**Why it's ambiguous:**
SQLite doesn't expose WAL serialization time directly. Without a specific measurement approach, WAL might be blamed or dismissed without evidence.

**Provider synthesis:**
- **OpenAI:** Use `BEGIN IMMEDIATE` timing — elapsed time from statement start to success measures lock acquisition; supplement with `PRAGMA busy_timeout` and record if any waits occurred.
- **Perplexity:** Tiered measurement — transaction latency profiling (lock acquisition vs. query execution vs. commit), contention factor (concurrent vs. sequential latency ratio), WAL file size monitoring.

**Proposed decision:**
Measure `lock_wait_ms` separately by timing `BEGIN IMMEDIATE` acquisition. Record `wal_file_size_bytes` at benchmark start and end (via `os.path.getsize(db_path + "-wal")`). A `lock_wait_ms` > 5% of `db_write_ms` indicates WAL contention is a real contributor.

**Confidence:** ⚠️ Two providers; actionable and cheap to implement.

---

### ⚠️ 7. "Batch DB Writes" Mitigation Complexity (Recommended)

**What needs to be decided:**
Is "batch DB writes" (grouping multiple state updates in one transaction) the intended mitigation, or should the benchmark focus on lower-complexity mitigations first?

**Why it's ambiguous:**
VLID-06 lists "batch DB writes, async state writes, or reduced guard checks" as candidate mitigations. Batch DB writes require changing the OCC transaction pattern (one transaction per transition → one transaction per N transitions), which is architecturally significant and risks weakening atomicity guarantees.

**Provider synthesis:**
- **OpenAI:** Test batched commits (every N transitions); still use per-row OCC checks; keep WAL mode; record PRAGMAs in output.
- **Gemini:** AVOID batch write mitigation; choose "reduced guard checks" or "prepared statements / connection reuse" instead to avoid a complex architectural refactor.

**Proposed decision:**
Test mitigations in order of complexity (stop when threshold is met):
1. First: "reduced guard checks" — remove any guard that reads the DB (guards should use in-memory state only)
2. Second: "connection reuse" — use a single persistent aiosqlite connection rather than open/close per transition
3. Third: "batch DB writes" — only if (1) and (2) don't meet threshold; group N transitions per commit (document OCC risk)

**Confidence:** ⚠️ Two providers; important for plan scoping.

---

### 🔍 8. FSM Object Lifecycle Per File (Needs Clarification)

**What needs to be decided:**
Does the benchmark instantiate one `FileLifecycleSM` FSM object per file (hydration approach) or maintain a pool of FSM objects in memory?

**Why it's ambiguous:**
Keeping 818 FSM objects in memory is faster but doesn't reflect production behavior. Hydration (create FSM per file from DB state) accurately measures production overhead but adds per-file instantiation cost.

**Provider synthesis:**
- **Gemini:** Hydration approach — read file_record from DB → instantiate FSM(file_record) → trigger event → write to DB. This is what Phase 16 will actually do.

**Proposed decision (YOLO):**
Use hydration approach: one FSM object instantiated per file per transition cycle. This models the production code path accurately and measures what Phase 16 will actually experience.

**Confidence:** 🔍 One provider; but obviously correct given the measurement goal.

---

### 🔍 9. Benchmark Output Format and Persistence (Needs Clarification)

**What needs to be decided:**
Where do benchmark results go? JSON file? Rich table? Stored in DB? Required for comparing before/after mitigation.

**Provider synthesis:**
- **OpenAI:** Machine-readable JSON report + Rich summary table; `benchmarks/` directory in repo; simple comparator command `bench compare run1.json run2.json`.

**Proposed decision (YOLO):**
Emit JSON to `benchmarks/results-YYYYMMDD-HHMMSS.json` (gitignored) and print Rich table to stdout. Two runs are compared by running the harness twice (baseline, then mitigation) and manually noting the delta in the SUMMARY.md.

**Confidence:** 🔍 One provider; lightweight approach fits the phase goal.

---

## Summary: Decision Checklist

Before planning, confirm:

**Tier 1 (Blocking — needed to define benchmark validity):**
- [x] Metric definition: three labeled timings (mock_api_ms, db_total_ms, fsm_net_ms) ← YOLO: decided
- [x] Concurrency model: three configs (=1, =10, =50) with asyncio.Semaphore ← YOLO: decided
- [x] Mock latency profiles: `zero` and `realistic` (2.0s constant, seed=42) ← YOLO: decided
- [x] Acceptable throughput thresholds: FSM overhead ≤5min (zero profile), realistic ≤6h ← YOLO: decided
- [x] Bottleneck attribution: yappi + explicit span timing, P95 per segment ← YOLO: decided

**Tier 2 (Important — affects measurement quality):**
- [x] WAL measurement: `lock_wait_ms` via BEGIN IMMEDIATE timing, WAL file size delta ← YOLO: decided
- [x] Mitigation order: guard checks → connection reuse → batch writes (stop at first pass) ← YOLO: decided

**Tier 3 (Polish):**
- [x] FSM object lifecycle: hydration approach (one object per file per cycle) ← YOLO: decided
- [x] Output format: JSON to `benchmarks/`, Rich table to stdout ← YOLO: decided

---

*Multi-provider synthesis by: OpenAI gpt-5.2-2025-12-11, Gemini Pro, Perplexity Sonar Deep Research*
*Generated: 2026-02-22*
*Mode: YOLO (balanced auto-answer strategy)*
