---
phase: 14-batch-performance
generated: 2026-02-22
mode: yolo
---

# CLARIFICATIONS-NEEDED.md

## Phase 14: Batch Performance Benchmark — Decisions Required

**Generated:** 2026-02-22
**Mode:** Multi-provider synthesis (OpenAI, Gemini, Perplexity)
**Source:** 3 AI providers analyzed Phase 14 requirements

---

## Decision Summary

**Total questions:** 9
**Tier 1 (Blocking):** 5 questions — must define benchmark validity
**Tier 2 (Important):** 2 questions — affect measurement quality
**Tier 3 (Polish):** 2 questions — can be decided during implementation

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: How do we define and label the "transition latency" metric?

**Question:** What exactly is measured as one "transition": end-to-end wall time (includes mock sleep), net FSM+DB time (wall time minus mock sleep), or both?

**Why it matters:** If mock latency (2s per API call) dominates the measurement, the FSM overhead (<50ms) becomes invisible noise. The benchmark can only identify a bottleneck if it can see past the mock sleep.

**Options:**

**A. End-to-end only (wall clock)**
- Pro: simple, one number
- Con: 97%+ will be `asyncio.sleep`, bottleneck identification impossible
- _(Proposed by: none — rejected by all providers)_

**B. Net overhead only (wall clock minus mock sleep)**
- Pro: directly shows FSM+DB overhead
- Con: requires tracking mock sleep separately
- _(Proposed by: Gemini)_

**C. Both, with explicit labels — `mock_api_ms`, `db_total_ms`, `fsm_net_ms`** ✅
- Pro: complete picture; both VLID-06 criteria satisfy (throughput = end-to-end; bottleneck = net)
- _(Proposed by: OpenAI, refined by synthesis)_

**Synthesis recommendation:** ✅ **Option C**

---

### Q2: What concurrency level should the primary benchmark run use?

**Question:** How many files processed in parallel for the VLID-06 primary measurement? Semaphore limit?

**Why it matters:** `asyncio.gather(*all_818)` will crash SQLite with concurrent writes; `concurrency=1` hides contention. Wrong choice means benchmark doesn't represent production conditions.

**Options:**

**A. Single concurrency level (e.g., 10)** ⚠️
- Run 818 files with Semaphore(10), report those numbers as primary
- _(Proposed by: Gemini with N=50)_

**B. Three-configuration matrix (=1, =10, =50)** ✅
- Sequential baseline + target production + stress test
- Identifies bottleneck at different contention levels
- _(Proposed by: OpenAI + Perplexity, refined by synthesis)_

**Synthesis recommendation:** ✅ **Option B** — three configs, primary metric from concurrency=10

---

### Q3: What mock latency profile should the benchmark use?

**Question:** Constant 2s? Random? Zero? What distribution?

**Why it matters:** Randomly seeded mocks make before/after mitigation comparisons noisy. Zero-latency profile is needed to stress FSM+DB; realistic profile is needed to validate throughput threshold.

**Options:**

**A. Single realistic profile (constant 2s)**
- Represents production conditions but hides FSM overhead
- _(Proposed by: Perplexity Tier 1)_

**B. Zero-latency only**
- Stresses FSM+DB but doesn't validate realistic throughput
- _(Proposed by: Gemini for bottleneck run)_

**C. Two named profiles: `zero` and `realistic` (2.0s constant, seed=42)** ✅
- `zero` for bottleneck identification; `realistic` for throughput validation
- Fixed seed ensures reproducible before/after comparison
- _(Proposed by: OpenAI named profiles, refined by synthesis)_

**Synthesis recommendation:** ✅ **Option C**

---

### Q4: What is the explicit acceptable throughput threshold?

**Question:** What numbers define success for VLID-06 Criterion 3? Currently there is no concrete number.

**Why it matters:** Without a pre-committed threshold, any result can be declared acceptable post-hoc. VLID-06 requires "defined explicitly."

**Options:**

**A. Single wall-clock threshold (e.g., "818 files in ≤6 hours")**
- Simple, user-visible metric
- _(Proposed by: Perplexity "Acceptable" tier)_

**B. Dual thresholds: FSM overhead + realistic throughput** ✅
- FSM+DB overhead (zero profile): 818 files × 4 transitions ≤5 min
- Realistic throughput (realistic profile, concurrency=10): 818 files ≤6 hours
- _(Synthesized from OpenAI + Gemini + Perplexity)_

**C. API saturation rate (e.g., ≥60 transitions/minute)**
- Ties threshold to Gemini API rate limit
- _(Proposed by: Gemini)_

**Synthesis recommendation:** ✅ **Option B** — dual thresholds, one per profile

---

### Q5: How do we identify which segment is the bottleneck?

**Question:** What profiling approach isolates guard check vs. state write vs. WAL lock wait vs. mock sleep vs. FSM dispatch?

**Why it matters:** cProfile is not async-aware and will attribute time to `asyncio.sleep` rather than the actual bottleneck. Without async-aware profiling, bottleneck identification is unreliable.

**Options:**

**A. cProfile only**
- Fast to set up, built-in
- Con: will blame `asyncio.sleep`, no coroutine awareness
- _(Rejected by all providers)_

**B. yappi only (asyncio-aware profiler)**
- Correctly separates wall time from CPU time, I/O wait from computation
- _(Proposed by: Perplexity as primary tool)_

**C. yappi + explicit timing spans** ✅
- yappi for function-level profile
- Explicit `time.perf_counter()` spans for `mock_api_ms`, `db_write_ms`, `lock_wait_ms`, `fsm_dispatch_ms`
- P50/P95/P99 per segment reported in output
- _(Synthesized from OpenAI + Gemini + Perplexity)_

**Synthesis recommendation:** ✅ **Option C**

---

## Tier 2: Important Decisions (⚠️ Recommended)

### Q6: How do we specifically measure WAL serialization (not just general DB time)?

**Question:** How to distinguish WAL write lock contention from general database operation latency?

**Why it matters:** VLID-06 explicitly lists "WAL serialization" as a potential bottleneck. If we lump it into `db_total_ms`, we can't identify it specifically.

**Options:**

**A. Measure `BEGIN IMMEDIATE` acquisition time separately** ✅
- `lock_wait_ms` = time from BEGIN IMMEDIATE statement to success
- WAL contention signal: `lock_wait_ms > 5%` of `db_total_ms`
- Also record WAL file size delta (via `os.path.getsize(db_path + "-wal")`)
- _(Proposed by: OpenAI + Perplexity)_

**Synthesis recommendation:** ✅ **Option A** — cheap to implement, directly measures the right thing

---

### Q7: Which mitigation should be tested first?

**Question:** VLID-06 says "at least one mitigation tested." Should we test batch DB writes, async state writes, or reduced guard checks first?

**Why it matters:** "Batch DB writes" require architectural changes (grouping OCC transactions) that are risky and complex. Testing simpler mitigations first avoids unnecessary complexity.

**Options:**

**A. Batch DB writes (group N transitions per commit)**
- High complexity, OCC risk
- _(Listed first in VLID-06 but not necessarily first to try)_

**B. Prioritized by complexity: guard checks → connection reuse → batch writes** ✅
- Step 1: Remove any guard that reads the DB (in-memory guards only)
- Step 2: Use a single persistent aiosqlite connection throughout the batch
- Step 3: Batch DB writes only if steps 1+2 don't meet threshold
- Stop at first step that meets the threshold
- _(Proposed by: Gemini explicitly, aligned with OpenAI's complexity analysis)_

**Synthesis recommendation:** ✅ **Option B** — stop at first mitigation that works

---

## Tier 3: Polish Decisions (🔍 Implementation Detail)

### Q8: Should FSM be hydrated per file (one object per file) or kept in memory?

**Question:** Does the benchmark instantiate one `FileLifecycleSM` per file from a DB read (production-realistic), or maintain 818 objects in memory (faster)?

**Synthesis recommendation:** 🔍 **Hydration** — one FSM per file per cycle, reads file_record from DB first. This is what production (Phase 16) will do and must be measured, not optimized away.

---

### Q9: Where do benchmark results go?

**Question:** Machine-readable output for before/after comparison?

**Synthesis recommendation:** 🔍 JSON files in `benchmarks/results-YYYYMMDD-HHMMSS.json` (gitignored) + Rich table to stdout. Two runs compared manually in the plan SUMMARY.md.

---

## Next Steps (YOLO Mode)

YOLO mode is active — auto-answers are generated in `CLARIFICATIONS-ANSWERED.md`.

Proceed to `/gsd:plan-phase 14` when ready.

---

*Multi-provider synthesis: OpenAI gpt-5.2 + Gemini Pro + Perplexity Sonar Deep Research*
*Generated: 2026-02-22*
