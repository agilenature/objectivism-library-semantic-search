# CLARIFICATIONS-NEEDED.md

## Phase 2: Upload Pipeline — Stakeholder Decisions Required

**Generated:** 2026-02-15
**Mode:** Multi-provider synthesis (OpenAI, Gemini, Perplexity)
**Source:** 3 AI providers analyzed Phase 2 requirements

---

## Decision Summary

**Total questions:** 10 gray areas identified
**Tier 1 (Blocking):** 6 questions — Must answer before planning (✅ Consensus)
**Tier 2 (Important):** 3 questions — Should answer for quality (⚠️ Recommended)
**Tier 3 (Polish):** 1 question — Can defer to implementation (🔍 Needs Clarification)

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: 48-Hour File Retention Window — Architecture Assumption

**Question:** The Gemini File API deletes raw uploaded files after 48 hours, but indexed data in File Search stores persists indefinitely. Should the system treat this as a one-time indexing operation (files upload → index → raw files expire), or does the system need to keep raw files alive beyond 48 hours?

**Why it matters:** This determines crash recovery constraints and whether the system needs TTL refresh logic. If raw files must persist, the architecture requires a file retention strategy. If ephemeral files are acceptable, crash recovery must complete within 48 hours.

**Options identified by providers:**

**A. One-time indexing (ephemeral files acceptable)**
- Raw files upload → get indexed → expire after 48 hours (expected behavior)
- Indexed data in File Search store persists indefinitely
- System focuses on completing indexing within 48-hour window
- Crash recovery must complete within 4 hours (44-hour safety buffer)
- _(Proposed by: Gemini, Perplexity)_
- **Pros:** Matches Gemini API design, no ongoing file maintenance
- **Cons:** Tight crash recovery deadline

**B. Context Caching model (persistent files required)**
- Raw files must remain accessible beyond 48 hours
- System must refresh/re-upload files before expiration
- Requires TTL tracking and scheduled re-upload jobs
- _(Proposed by: Gemini as alternative)_
- **Pros:** Files always available for re-indexing
- **Cons:** Ongoing cost, complex TTL management

**Synthesis recommendation:** ✅ **Option A** (One-time indexing)
- Matches the described use case (one-time library indexing, not ongoing context caching)
- Aligns with Gemini File Search API design (indexed data persists, raw files are temporary)
- Simplifies architecture (no TTL refresh logic needed)

**Sub-questions:**
- If crash recovery takes longer than 48 hours, is data loss acceptable, or should manual intervention re-upload affected files?
- Does the success criterion "fully indexed and queryable store" mean forever, or just immediately after upload completes?

---

### Q2: Metadata Attachment — Storage Strategy

**Question:** UPLD-08 requires "attach rich metadata to each uploaded file (20-30 fields)," but the Gemini API has limited native metadata support. Where should metadata be stored: in Gemini (if supported), injected into file content, or only in SQLite?

**Why it matters:** Determines whether metadata is searchable via Gemini's semantic search, affects payload size, and impacts query performance. Wrong choice could make metadata filtering impossible or require expensive client-side post-processing.

**Options identified by providers:**

**A. Two-tier metadata (searchable + archive)**
- Tier 1: 5-8 searchable fields attached via `custom_metadata` parameter (if SDK supports)
- Tier 2: 15-25 archive fields stored in SQLite for tracking and audit
- Examples: Searchable = category, course, difficulty, quality_score; Archive = file_hash, processing_duration, compliance_tags
- _(Proposed by: Perplexity)_
- **Pros:** Balances Gemini searchability with rich local tracking, minimal payload size
- **Cons:** Requires verifying SDK version supports `custom_metadata`

**B. Content injection (all metadata in file)**
- Inject all 20-30 metadata fields into file content as YAML/JSON header before upload
- Metadata becomes part of searchable document text
- _(Proposed by: Gemini)_
- **Pros:** No dependency on SDK metadata support, metadata is definitely searchable
- **Cons:** Increases file size, metadata mixed with content, harder to update

**C. SQLite-only metadata (no Gemini metadata)**
- Store all metadata in SQLite, upload files without metadata to Gemini
- Client-side filtering on metadata, Gemini handles semantic search only
- **Pros:** Simple, no SDK dependency, flexible metadata schema
- **Cons:** Can't filter files before querying Gemini, client-side post-processing expensive

**Synthesis recommendation:** ✅ **Option A** (Two-tier) with fallback to B
- Try `custom_metadata` parameter first (verify in SDK v1.63.0+)
- If not supported, fall back to content injection for searchable fields
- Always store archive metadata in SQLite

**Sub-questions:**
- Which specific fields should be searchable in Gemini vs. archive-only in SQLite?
- Should metadata be updateable after upload (re-upload file), or immutable?
- Are there compliance requirements (audit trails, retention policies) that affect metadata storage?

---

### Q3: Batch Processing — Orchestration Strategy

**Question:** UPLD-07 specifies "batch processing (100-200 files per batch)," but doesn't clarify whether batching means "process 100, wait for all 100 to finish, then start next 100" (strict batches) or "maintain a queue of 100, refill as they complete" (sliding window).

**Why it matters:** Affects throughput (strict batches may have idle workers), affects resume logic (sliding window scatters state), and affects 36-hour deadline achievability (strict batches with stragglers risk timeout).

**Options identified by providers:**

**A. Three-tier batching (micro + logical + lifecycle)**
- Tier 1: Micro-batches via `Semaphore(5-10)` for concurrency control
- Tier 2: Logical batches (100-200 files) for state management and progress tracking
- Tier 3: Async operation lifecycle (operations complete independently)
- _(Proposed by: Perplexity)_
- **Pros:** High throughput (no idle workers), clear resume points (batch boundaries), flexible
- **Cons:** More complex state management

**B. Strict batches with timeouts**
- Process files in groups of 100-200, wait for batch to complete before starting next
- If a file hangs (>5 minutes), mark as timeout and close batch
- _(Proposed by: Gemini)_
- **Pros:** Simple reasoning ("Batch 1 done, Batch 2 in progress"), easy progress reporting
- **Cons:** Risk of idle workers if stragglers block batch completion

**Synthesis recommendation:** ✅ **Option A** (Three-tier batching)
- Maximizes throughput (critical for 36-hour deadline)
- Logical batches provide clear checkpoints for resume
- Async operations match Gemini API design

**Sub-questions:**
- Should batch size (100-200) be tunable at runtime based on performance, or fixed?
- If a logical batch partially fails (e.g., 150/200 succeed), retry entire batch or individual files?
- Does the 36-hour deadline apply to uploads only, or end-to-end including operation polling/indexing?

---

### Q4: Operation Polling — Frequency and Timeout

**Question:** UPLD-04 requires "operation polling for indexing completion status," but doesn't specify polling frequency, timeout duration, or concurrency strategy. How should the system balance polling responsiveness vs. rate limit consumption?

**Why it matters:** Polling too frequently exhausts rate limits and wastes resources. Polling too slowly misses completion windows and delays progress. Wrong timeout settings cause false failures or indefinite hangs.

**Options identified by providers:**

**A. Exponential backoff polling (5s → 60s, 1-hour timeout)**
- Start at 5-second interval, increase exponentially to 60-second max
- Stop after 1 hour if operation doesn't complete
- Poll up to 20 operations concurrently (separate from upload concurrency)
- _(Proposed by: Perplexity)_
- **Pros:** Balances responsiveness and rate limits, standard retry pattern
- **Cons:** Fixed 1-hour timeout may be too short for large files

**B. Adaptive polling with per-file backoff (no global cap)**
- Each file has independent polling schedule (T, T×1.5, T×1.5², ..., max 30s)
- No fixed timeout—poll until operation completes or 48-hour deadline
- _(Proposed by: Gemini)_
- **Pros:** Flexible, no artificial timeout failures
- **Cons:** May poll indefinitely if operation stalls

**Synthesis recommendation:** ✅ **Option A** (Exponential backoff with timeout)
- Matches `tenacity` library best practices
- 1-hour timeout is reasonable default (can be configured)
- Prevents indefinite polling on stalled operations

**Sub-questions:**
- What is the expected operation completion latency under normal conditions?
- Should operations nearing the 48-hour file retention deadline get polling priority?
- If an operation times out after 1 hour, should it be retried, or escalated to manual review?
- What is the Gemini API rate limit for `operations.get()`? (RPM for polling vs. uploads)

---

### Q5: Circuit Breaker — Threshold and Recovery Strategy

**Question:** UPLD-06 specifies "circuit breaker to reduce rate 50% after 5% 429 errors," but doesn't define the measurement window (5% over what period?), recovery strategy (when to ramp back up?), or concurrency reduction mechanics (semaphore? delays?).

**Why it matters:** Wrong threshold triggers false backoffs (wasted time) or fails to prevent rate limit cascades (429 errors compound). Poor recovery logic means the system never returns to full speed, risking 36-hour deadline.

**Options identified by providers:**

**A. Rolling window (last 100 requests) with gradual recovery**
- Track 429 errors over rolling window of last 100 requests
- Open circuit when 429 rate >5% OR 3 consecutive 429s
- Reduce concurrency 50% (7→3), add 5s delays
- Cool down 5 minutes, then test with single request (half-open)
- Gradually increment concurrency (+1 per 20 successes) until max
- _(Proposed by: Gemini, Perplexity)_
- **Pros:** Stable (not sensitive to time), gradual recovery prevents oscillation
- **Cons:** Requires tracking last 100 requests in memory

**B. Time-based window (5 minutes) with binary recovery**
- Track 429 errors over fixed 5-minute window
- Open circuit when 429 rate >5%
- Reduce concurrency 50%, wait 5 minutes, then fully restore
- _(Alternative not explicitly proposed)_
- **Pros:** Simpler implementation
- **Cons:** Window boundary effects, abrupt recovery may re-trigger

**Synthesis recommendation:** ✅ **Option A** (Rolling window with gradual recovery)
- Industry best practice (pybreaker library pattern)
- Rolling window more stable than time windows
- Gradual recovery prevents thrashing

**Sub-questions:**
- Should circuit breaker apply globally (all uploads) or per-batch (allow partial failures)?
- What defines "success" for half-open test: initial API call success, or operation completion?
- Should in-flight operations be cancelled when circuit opens, or allowed to complete?

---

### Q6: State Synchronization — SQLite vs. Gemini Truth

**Question:** UPLD-10 requires "resume capability from any interruption point using SQLite state," but doesn't specify how to handle consistency between local SQLite state and remote Gemini API state. If the system crashes after uploading a file but before writing to SQLite, which is the source of truth?

**Why it matters:** Wrong consistency model leads to duplicate uploads (wasted cost), skipped files (data loss), or inconsistent state that requires manual reconciliation. Crash recovery depends on knowing which files are truly uploaded vs. pending.

**Options identified by providers:**

**A. SQLite-as-source-of-truth with idempotent retries**
- Write upload intent to SQLite BEFORE API call
- If API succeeds, update SQLite with operation name
- On crash resume: reconcile SQLite state with Gemini (query Gemini for actual files)
- Retry logic is idempotent (same file + metadata → Gemini deduplicates)
- _(Proposed by: Gemini, Perplexity)_
- **Pros:** Clear source of truth, survives crashes, idempotent retries prevent duplicates
- **Cons:** Requires reconciliation on resume (extra API calls)

**B. Gemini-as-source-of-truth**
- Query Gemini File Search store for document count/list
- Compare with SQLite, identify discrepancies
- **Pros:** Gemini state is guaranteed correct
- **Cons:** Expensive (API calls), slower resume

**C. Dual-write with best-effort consistency**
- Write to SQLite after Gemini succeeds, accept risk of inconsistency
- **Pros:** Simple
- **Cons:** Can't recover from crashes reliably

**Synthesis recommendation:** ✅ **Option A** (SQLite-as-source-of-truth)
- Write intent before API call (pre-flight commit)
- Idempotent retries handle duplicates
- Reconciliation on resume verifies consistency

**Sub-questions:**
- If reconciliation finds files in Gemini not in SQLite, should they be adopted into tracking, or deleted?
- In a distributed environment (multiple worker processes), how should state be synchronized?
- What is the acceptable lag between Gemini indexing completion and SQLite reflecting "indexed" status?

---

## Tier 2: Important Decisions (⚠️ Recommended)

### Q7: Rate Limit Tier Detection

**Question:** The circuit breaker and upload strategy depend on knowing the current Gemini API rate limit tier (Free: 5 RPM, Tier 1: 20 RPM, Tier 2: 200 RPM, Tier 3: 2000 RPM). How should the system detect and adapt to the current tier?

**Why it matters:** "50% rate reduction" means different things at different tiers (10→5 at Tier 1 vs. 1000→500 at Tier 3). Without tier awareness, the system may be overly conservative (wasted time) or overly aggressive (429 cascades).

**Options identified by providers:**

**A. Manual configuration (explicit tier in config)**
- User specifies tier in environment variable or config file
- System uses predefined limits for that tier
- **Pros:** Simple, reliable
- **Cons:** Requires user knowledge of tier, doesn't adapt if tier changes

**B. Runtime detection (parse API response headers)**
- Attempt to parse `x-ratelimit-remaining`, `x-ratelimit-reset` from responses
- Infer tier from observed limits
- **Pros:** Automatic, adapts to tier changes
- **Cons:** Headers may not be present, inference is heuristic

**C. Hybrid (manual config + runtime observation)**
- Start with configured tier, refine with runtime observations
- _(Proposed by: Perplexity)_
- **Pros:** Best of both worlds
- **Cons:** More complex

**Synthesis recommendation:** ⚠️ **Option C** (Hybrid)
- Require tier in configuration (explicit is better)
- Observe response headers opportunistically
- Log warnings if observed limits differ from configured

**Sub-questions:**
- Is the system operating on Free, Tier 1, 2, or 3 account?
- What is the acceptable 429 error rate? Is 5% a hard limit, or higher during peak?
- Should the system "fail-fast" (halt on rate limit) or "graceful degradation" (slow down and retry)?

---

### Q8: Progress Tracking Granularity

**Question:** UPLD-09 requires "progress tracking and reporting with Rich progress bars," but doesn't specify which metrics to track: file count, byte count, time estimates, API calls, error rates, or all of the above?

**Why it matters:** End users want file counts and ETAs. Developers want API call counts and error rates. Operations teams want throughput metrics. Different audiences need different views, but tracking everything adds overhead.

**Options identified by providers:**

**A. Hierarchical tracking (file + batch + pipeline levels)**
- Track file-level progress (per-file state: pending/uploading/succeeded/failed)
- Aggregate to batch-level (100-200 files, progress %, ETA)
- Aggregate to pipeline-level (1,884 files, overall progress, total ETA)
- Display with Rich: overall progress bar + per-batch progress bars
- _(Proposed by: Perplexity)_
- **Pros:** Comprehensive, serves all audiences, clear hierarchy
- **Cons:** More state to track, more complex display

**B. Simple file count tracking**
- Track only: files uploaded, files pending, files failed
- Display single progress bar: "185 of 1,884 files (9.8%)"
- **Pros:** Simple, easy to understand
- **Cons:** Misleading if files vary in size, no ETA

**Synthesis recommendation:** ⚠️ **Option A** (Hierarchical tracking)
- Matches UPLD-09 "progress visibility" requirement
- Provides ETA estimates (important for 36-hour deadline)
- Rich library supports hierarchical displays well

**Sub-questions:**
- Should progress be reported to a web dashboard, logs, or terminal only?
- Are there specific throughput metrics (files/minute, MB/second) needed for operations?
- Should progress include operation completion (indexing), or just upload completion?

---

### Q9: Crash Recovery Semantics

**Question:** UPLD-10 requires resumption "from any interruption point," but doesn't specify: (1) How long the system has to resume before data loss occurs, (2) What the recovery protocol should verify, (3) Whether recovery is automatic or manual.

**Why it matters:** If recovery takes >48 hours, temporary File API objects are deleted, breaking the pipeline. Recovery protocol determines whether the system can safely resume or needs manual intervention. Automatic recovery may mask underlying issues; manual recovery adds operational burden.

**Options identified by providers:**

**A. Automatic recovery with 4-hour timeout**
- On startup, automatically run recovery protocol:
  - Identify incomplete operations, check status with Gemini
  - Identify pending uploads, prioritize deadline-critical files
  - Verify SQLite-Gemini consistency
- Enforce 4-hour recovery timeout (leaves 44-hour buffer before 48-hour deadline)
- If recovery exceeds 4 hours, escalate to manual intervention
- _(Proposed by: Perplexity)_
- **Pros:** Automatic, fast, respects 48-hour constraint
- **Cons:** 4-hour timeout may be tight for large inconsistencies

**B. Manual recovery (operator-triggered)**
- System starts in "recovery needed" mode, requires operator to trigger recovery
- **Pros:** Operator validates state before resuming
- **Cons:** Adds operational burden, delays recovery

**Synthesis recommendation:** ⚠️ **Option A** (Automatic recovery with timeout)
- Automatic recovery reduces time-to-resume (critical for 48-hour window)
- 4-hour timeout is generous for expected recovery tasks
- Escalation path handles edge cases

**Sub-questions:**
- If a file's File API object is deleted (>48 hours) but SQLite shows "in progress," should the system retry, mark failed, or manual review?
- Should crash recovery run automatically on every startup, or only after detected crash?
- What is acceptable data loss if system is down >48 hours?

---

## Tier 3: Polish Decisions (🔍 Needs Clarification)

### Q10: Concurrency Model — Single vs. Multi-Process

**Question:** Should the system support multiple Python processes uploading concurrently (distributed workers), or is single-process operation sufficient?

**Why it matters:** Multi-process support enables parallelization across machines, but requires complex coordination (locks, circuit breaker state sharing, duplicate prevention). Single-process is simpler but limited to one machine's resources.

**Options identified by providers:**

**A. Single-writer architecture (one primary process)**
- One Python process is designated primary uploader via SQLite lock
- Other processes (if any) are read-only for monitoring
- _(Proposed by: Perplexity)_
- **Pros:** Simple, no race conditions, SQLite WAL handles multi-reader
- **Cons:** Limited to one machine's concurrency (10 workers max)

**B. Multi-process distributed workers**
- Multiple Python processes upload concurrently
- SQLite locks prevent duplicate uploads
- Circuit breaker state shared via SQLite
- **Pros:** Higher throughput (more than 10 concurrent)
- **Cons:** Complex coordination, race conditions, lock contention

**Synthesis recommendation:** 🔍 **Option A** (Single-writer)
- Requirements don't mention multi-machine parallelization
- 10 concurrent workers (Semaphore) should suffice for 1,884 files
- Can defer multi-process support to Phase 5 if needed

**Sub-questions:**
- Is single-process operation (max 10 concurrent uploads) acceptable for performance?
- Should the primary lock be held indefinitely, or released periodically for failover?
- If two processes somehow both acquire lock (clock skew), how should conflicts be resolved?

---

## Next Steps

**YOLO Mode (current):**
1. ✅ Review CLARIFICATIONS-NEEDED.md (this document)
2. ⏭ Auto-generate CLARIFICATIONS-ANSWERED.md using synthesis recommendations
3. ⏭ Proceed to `/gsd:plan-phase 2` to create execution plan

**Alternative (Manual Mode):**
If you want to override synthesis recommendations, create CLARIFICATIONS-ANSWERED.md manually with your decisions, then run `/gsd:plan-phase 2`.

---

*Multi-provider synthesis: OpenAI + Gemini + Perplexity (with industry citations)*
*Generated: 2026-02-15*
*Mode: YOLO (auto-answers will be generated based on synthesis recommendations)*
