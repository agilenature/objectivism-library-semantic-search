# CLARIFICATIONS-ANSWERED.md

## Phase 2: Upload Pipeline — Stakeholder Decisions

**Generated:** 2026-02-15
**Mode:** YOLO (balanced strategy — auto-generated based on synthesis recommendations)
**Source:** Multi-provider AI analysis (OpenAI, Gemini, Perplexity)

---

## Decision Summary

**Total questions:** 10 gray areas addressed
**Tier 1 (Blocking):** 6 answered (✅ Consensus)
**Tier 2 (Important):** 3 answered (⚠️ Recommended)
**Tier 3 (Polish):** 1 answered (🔍 Needs Clarification)

---

## Tier 1: Blocking Decisions

### Q1: 48-Hour File Retention Window — Architecture Assumption

**Question:** Should the system treat file retention as one-time indexing (ephemeral files) or persistent files requiring TTL refresh?

**YOLO DECISION:** ✅ **Option A — One-time indexing (ephemeral files acceptable)**

**Rationale:**
- Confidence level: ✅ Consensus (both Gemini and Perplexity agreed)
- Matches the described use case: one-time library indexing for semantic search, not ongoing context caching
- Aligns with Gemini File Search API design: indexed data in File Search stores persists indefinitely, raw File API objects are temporary
- Simplifies architecture: no TTL refresh logic, no ongoing file maintenance costs
- Strategy: Crash recovery must complete within 4 hours (leaves 44-hour buffer before 48-hour deadline)

**Implementation decisions:**
- Accept that raw File API objects expire after 48 hours (expected behavior)
- Indexed data in File Search store persists indefinitely (this is the "fully indexed and queryable store")
- Add `upload_timestamp` and `expiration_timestamp` fields to SQLite to track TTL
- Flag operations nearing 48-hour deadline as critical priority during crash recovery
- Establish 4-hour crash recovery timeout: if system doesn't resume within 4 hours of crash, manual intervention required

**Sub-decisions:**
- **If crash recovery takes >48 hours:** Manual intervention required to re-upload affected files. Data loss is acceptable edge case (rare failure scenario).
- **"Fully indexed and queryable store" means:** Queryable immediately after upload completes and indefinitely thereafter (indexed data persists). Raw files are temporary scaffolding.

---

### Q2: Metadata Attachment — Storage Strategy

**Question:** Where should the 20-30 metadata fields be stored: in Gemini, injected into file content, or only in SQLite?

**YOLO DECISION:** ✅ **Option A — Two-tier metadata (searchable + archive) with fallback to content injection**

**Rationale:**
- Confidence level: ✅ Consensus (both providers agreed on two-tier approach)
- Balances Gemini searchability with rich local tracking
- Minimizes payload size sent to Gemini (only searchable fields)
- Preserves full metadata in SQLite for audit, compliance, tracking
- Strategy: Try `custom_metadata` parameter first (SDK v1.63.0+), fall back to content injection if not supported

**Implementation decisions:**

**Tier 1: Searchable Metadata (5-8 fields) — Attached to Gemini**
Fields that must be searchable/filterable in semantic queries:
- `category` (e.g., "course", "book", "motm", "podcast")
- `course` (e.g., "OPAR", "History of Philosophy")
- `difficulty` (e.g., "introductory", "intermediate", "advanced")
- `quality_score` (0-100 percentile from Phase 1 scanner)
- `year`, `quarter`, `week` (hierarchical structure fields)
- `date` (for MOTM and Podcast content)

Attachment method:
- First attempt: `custom_metadata` parameter in `uploadToFileSearchStore` config
- Fallback: Inject as YAML header at top of file content if SDK doesn't support `custom_metadata`

**Tier 2: Archive Metadata (15-25 fields) — Stored in SQLite only**
Fields for internal tracking, audit, compliance:
- `file_hash` (SHA-256 from Phase 1 scanner)
- `original_size_bytes`, `file_path`, `scanned_at`
- `extraction_quality` (COMPLETE/PARTIAL/MINIMAL/NONE from Phase 1)
- `_unparsed_filename`, `_unparsed_folder` (Phase 1 flags)
- `upload_timestamp`, `expiration_timestamp`, `operation_name`, `operation_state`
- `retry_count`, `error_message`, `last_polled_at`, `completed_at`
- `batch_id`, `processing_duration_ms`

**Sub-decisions:**
- **Which fields searchable vs. archive:** Searchable = pedagogical dimensions users will filter on (course, difficulty, date, structure). Archive = technical tracking (hashes, timestamps, errors).
- **Metadata updateability:** Immutable. If metadata needs update, re-upload file (Phase 5 incremental updates will handle this).
- **Compliance requirements:** Archive metadata in SQLite serves audit trail requirements. All state transitions logged in `_processing_log` table (from Phase 1).

---

### Q3: Batch Processing — Orchestration Strategy

**Question:** Should batching use strict batches (wait for all 100 to finish) or sliding window (refill as they complete)?

**YOLO DECISION:** ✅ **Option A — Three-tier batching (micro + logical + lifecycle)**

**Rationale:**
- Confidence level: ✅ Consensus (Perplexity's comprehensive approach endorsed by Gemini's timeout principle)
- Maximizes throughput: no idle workers waiting for stragglers
- Provides clear resume points: logical batch boundaries in SQLite
- Matches Gemini API design: async operations complete independently
- Critical for 36-hour deadline: continuous progress vs. batch blocking

**Implementation decisions:**

**Tier 1: Micro-batches for concurrency control**
- `asyncio.Semaphore(7)` to limit concurrent `uploadToFileSearchStore` calls
- Start conservatively at 7 concurrent, adjust based on circuit breaker (reduce to 3 on backoff, increase to 10 on recovery)
- Each file uploaded individually in parallel within semaphore limit

**Tier 2: Logical batches for state management**
- Group files into cohorts of 100-200 files for progress tracking and checkpointing
- At 1,884 files with batch_size=150: creates ~13 logical batches
- Each logical batch tracked in SQLite with `batch_id`
- Checkpoint after each batch completes (write batch summary to SQLite)
- Resume starts at last incomplete batch boundary

**Tier 3: Upload operation lifecycle**
- Each `uploadToFileSearchStore` returns a long-running operation name
- Operations transition: PENDING → IN_PROGRESS → SUCCEEDED/FAILED
- Polling occurs independently (up to 20 operations polled concurrently)
- Operations may complete in different order than upload order (async nature)

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY,
    batch_number INTEGER NOT NULL,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    file_count INTEGER,
    succeeded_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending'  -- pending, in_progress, completed, failed
);

ALTER TABLE files ADD COLUMN batch_id INTEGER REFERENCES batches(id);
```

**Sub-decisions:**
- **Batch size tuning:** Fixed at 150 files for v1. Can make tunable in Phase 5 based on performance metrics.
- **Partial batch failure handling:** Retry individual failed files within the batch (don't retry entire batch). Failed files marked for manual review after 3 retry attempts.
- **36-hour deadline scope:** Applies to end-to-end process (upload + operation polling/indexing). Deadline starts when `upload` command runs, ends when all operations reach SUCCEEDED/FAILED state.

---

### Q4: Operation Polling — Frequency and Timeout

**Question:** How frequently should operations be polled, and what timeout should be used?

**YOLO DECISION:** ✅ **Option A — Exponential backoff polling (5s → 60s, 1-hour timeout)**

**Rationale:**
- Confidence level: ✅ Consensus (both providers agreed on exponential backoff)
- Balances responsiveness (detect completion quickly) with rate limit conservation (don't exhaust polling quota)
- Standard retry pattern: `tenacity` library with `wait_exponential`
- Timeout prevents indefinite polling on stalled operations

**Implementation decisions:**

**Polling strategy:**
```python
from tenacity import retry, wait_exponential, stop_after_delay, retry_if_result

@retry(
    wait=wait_exponential(multiplier=1, min=5, max=60),
    stop=stop_after_delay(3600),  # 1-hour timeout
    retry=retry_if_result=lambda op: not op.done
)
async def poll_operation(operation_name: str):
    operation = await client.operations.get(operation=operation_name)
    if operation.done:
        return operation
    raise OperationPending()  # Triggers retry with increased backoff
```

**Backoff progression:**
- Initial: 5 seconds
- After 1st retry: 10 seconds (5 × 2^1)
- After 2nd retry: 20 seconds (5 × 2^2)
- After 3rd retry: 40 seconds (5 × 2^3)
- After 4th retry: 60 seconds (cap reached, stays at 60s)
- Timeout: 3600 seconds (1 hour total)

**Concurrent polling:**
- Poll up to 20 operations concurrently (separate `Semaphore(20)` from upload concurrency)
- Polling is lighter-weight than uploads, can handle more concurrency
- If polling rate limit (429) errors occur, apply same circuit breaker logic (reduce polling concurrency)

**Priority queue for deadline-critical files:**
- Track `upload_timestamp` for each operation
- If `datetime.now() - upload_timestamp > 40 hours`: flag as deadline-critical
- Poll deadline-critical operations every 30 seconds (ignore backoff) to ensure completion before 48-hour window

**Sub-decisions:**
- **Expected operation latency:** 30 seconds to 5 minutes under normal conditions (based on Gemini API documentation stating "indexing may take a few minutes"). 1-hour timeout accommodates outliers.
- **Polling priority:** Yes, operations within 8 hours of 48-hour deadline get priority polling (every 30s regardless of backoff).
- **Timeout handling:** If operation times out after 1 hour, mark as `TIMEOUT_FAILED` in SQLite, log error, continue with other files. Manual review required for timeout failures. Don't retry automatically (may be systemic issue).
- **Polling rate limits:** Assume polling RPM is higher than upload RPM (Google APIs typically have higher read limits than write limits). If 429 errors occur during polling, apply circuit breaker (reduce polling concurrency 50%).

---

### Q5: Circuit Breaker — Threshold and Recovery Strategy

**Question:** How should the 5% 429 threshold be measured, and how should the system recover?

**YOLO DECISION:** ✅ **Option A — Rolling window (last 100 requests) with gradual recovery**

**Rationale:**
- Confidence level: ✅ Consensus (both providers agreed on rolling window + gradual recovery)
- Rolling window more stable than time-based windows (no boundary effects)
- Gradual recovery prevents oscillation (avoid thrashing between open/closed states)
- Industry best practice: `pybreaker` library pattern

**Implementation decisions:**

**Circuit breaker state machine:**

**1. Closed State (Normal operation):**
- Accept all upload requests at normal rate
- Concurrency: `Semaphore(7)`
- No additional delays between requests

**2. Trip Condition (transition to Open):**
- **Trigger A:** 429 error rate >5% over rolling window of last 100 requests
- **Trigger B:** 3 consecutive 429 errors (immediate trip)
- When triggered: log warning, transition to Open state

**3. Open State (Backoff mode):**
- Reduce concurrency: `Semaphore(7)` → `Semaphore(3)` (57% reduction ≈ 50% target)
- Add 5-second delay between each request
- Reject new uploads for 5 minutes (return to queue)
- Log all rejected requests for retry after cool-down

**4. Half-Open State (Testing recovery):**
- After 5 minutes in Open state, attempt single test request
- If test request succeeds: transition to Closed state, begin gradual concurrency increase
- If test request fails (429): return to Open state, extend cool-down to 10 minutes

**5. Gradual Concurrency Recovery (after successful Half-Open test):**
- Start at `Semaphore(3)` (reduced rate)
- After 20 consecutive successful uploads: increment to `Semaphore(4)`
- After another 20 consecutive successes: increment to `Semaphore(5)`
- Continue until reaching `Semaphore(10)` (max normal rate)
- If 429 error occurs during ramp-up: reset to `Semaphore(3)`

**Error tracking:**
```python
import collections

class RateLimitMetrics:
    def __init__(self, window_size: int = 100):
        self.request_states = collections.deque(maxlen=100)

    def record_request(self, success: bool, error_code: int = None):
        self.request_states.append({
            'success': success,
            'error_code': error_code,
            'timestamp': time.time()
        })

    def get_429_error_rate(self) -> float:
        if not self.request_states:
            return 0.0
        errors_429 = sum(1 for r in self.request_states if r['error_code'] == 429)
        return errors_429 / len(self.request_states)
```

**Sub-decisions:**
- **Circuit breaker scope:** Global (applies to entire upload pipeline). Don't allow per-batch partial failures—if one batch hits rate limits, the entire system should back off to avoid cascading failures.
- **Half-open success criteria:** Initial API call success (returns operation name). Don't wait for operation completion (would take minutes/hours).
- **In-flight operations during open state:** Allow in-flight operations to complete. Don't cancel. Circuit breaker only affects new upload requests.

---

### Q6: State Synchronization — SQLite vs. Gemini Truth

**Question:** Which is the source of truth: SQLite or Gemini API? How to handle inconsistencies?

**YOLO DECISION:** ✅ **Option A — SQLite-as-source-of-truth with idempotent retries and reconciliation**

**Rationale:**
- Confidence level: ✅ Consensus (both providers agreed)
- SQLite provides durability guarantees with WAL mode
- Idempotent retries prevent duplicates (Gemini deduplicates same file+metadata)
- Reconciliation on resume verifies consistency
- Clear transaction boundaries prevent lost state

**Implementation decisions:**

**Transaction protocol (pre-flight write):**
```python
async def upload_file_with_state_tracking(file_path: str, metadata: dict):
    """Upload with crash-safe state tracking"""
    file_id = get_or_create_file_id(file_path)

    # STEP 1: Write intent to SQLite BEFORE API call, then commit
    state_manager.begin_transaction()
    try:
        state_manager.record_upload_intent(
            file_id=file_id,
            file_path=file_path,
            state='UPLOAD_INITIATED',
            timestamp=datetime.now()
        )
        state_manager.commit()  # EXPLICIT commit before API call
    except Exception as e:
        state_manager.rollback()
        raise

    # STEP 2: Perform Gemini API call (may crash here)
    try:
        operation = client.file_search_stores.upload_to_file_search_store(
            file=file_path,
            file_search_store_name=store_id,
            config={'display_name': metadata.get('display_name')}
        )
    except Exception as e:
        # API call failed, record failure
        state_manager.record_upload_failure(file_id, str(e))
        raise

    # STEP 3: Update SQLite with operation name, then commit
    state_manager.begin_transaction()
    try:
        state_manager.record_upload_success(
            file_id=file_id,
            operation_name=operation.name,
            state='UPLOAD_IN_PROGRESS'
        )
        state_manager.commit()  # Commit operation details
    except Exception as e:
        state_manager.rollback()
        # Note: operation succeeded in Gemini but we couldn't record it
        # Reconciliation will detect this on resume
        raise

    return operation
```

**Reconciliation on resume:**
```python
async def verify_and_reconcile_state():
    """Run on startup after crash"""
    logger.info("Starting state reconciliation")

    # Get files SQLite thinks are uploaded
    uploaded_files = state_manager.get_files_marked_as_succeeded()

    # Query Gemini for actual document list
    store_docs = client.file_search_stores.documents.list(store_id)
    store_doc_names = {doc.name for doc in store_docs}

    # Identify discrepancies
    discrepancies = []
    for file_record in uploaded_files:
        expected_name = f"fileSearchStores/{store_id}/documents/{file_record.gemini_file_id}"
        if expected_name not in store_doc_names:
            logger.warning(f"File {file_record.file_path} marked succeeded but not in Gemini")
            discrepancies.append(file_record)

    # Handle discrepancies: mark for retry
    if discrepancies:
        logger.warning(f"Found {len(discrepancies)} state mismatches, marking for retry")
        for file_record in discrepancies:
            state_manager.mark_file_as_pending_retry(file_record.file_id)

    # Inverse check: files in Gemini but not in SQLite
    sqlite_file_ids = {f.gemini_file_id for f in uploaded_files}
    orphaned_in_gemini = [doc for doc in store_docs if doc.id not in sqlite_file_ids]
    if orphaned_in_gemini:
        logger.info(f"Found {len(orphaned_in_gemini)} files in Gemini not tracked in SQLite")
        # Adopt them into tracking (assume they're from previous interrupted run)
        for doc in orphaned_in_gemini:
            state_manager.adopt_orphaned_file(doc)

    return len(discrepancies) == 0
```

**Idempotency for retries:**
- Gemini File Search API is idempotent: uploading the same file with same metadata returns existing operation/document
- Retry logic: if upload fails, retry up to 3 times with exponential backoff (2^attempt seconds delay)
- SQLite idempotency: UPSERT pattern ensures retrying same file doesn't create duplicates

**Sub-decisions:**
- **Files in Gemini not in SQLite:** Adopt them into tracking (assume they're from interrupted previous run). Create SQLite records for them.
- **Distributed environment:** Not supported in Phase 2 (see Q10). Single-writer architecture prevents race conditions.
- **Acceptable lag:** Up to 5 minutes lag between Gemini showing "indexed" and SQLite reflecting it (polling delay). Not a consistency issue—eventual consistency is acceptable for operation completion status.

---

## Tier 2: Important Decisions

### Q7: Rate Limit Tier Detection

**Question:** How should the system detect the current Gemini API rate limit tier?

**YOLO DECISION:** ⚠️ **Option C — Hybrid (manual config + runtime observation)**

**Rationale:**
- Confidence level: ⚠️ Recommended (Perplexity's detailed analysis)
- Explicit configuration is more reliable than inference
- Runtime observation provides validation and adaptation
- Best of both worlds: deterministic starting point + adaptive refinement

**Implementation decisions:**

**Configuration (explicit tier):**
```python
# Environment variable or config file
GEMINI_API_TIER = os.getenv('GEMINI_API_TIER', 'free')  # Default: free tier

RATE_LIMIT_TIERS = {
    'free': {'rpm': 5, 'tpm': 125000, 'rpd': 100},
    'tier1': {'rpm': 20, 'tpm': 500000, 'rpd': None},
    'tier2': {'rpm': 200, 'tpm': 5000000, 'rpd': None},
    'tier3': {'rpm': 2000, 'tpm': 50000000, 'rpd': None},
}

rate_limits = RATE_LIMIT_TIERS[GEMINI_API_TIER]
logger.info(f"Configured rate limits for tier '{GEMINI_API_TIER}': {rate_limits}")
```

**Runtime observation (header parsing):**
```python
async def make_api_call_with_rate_observation(func):
    """Decorator to observe rate limit headers"""
    async def wrapper(*args, **kwargs):
        try:
            response = await func(*args, **kwargs)

            # Parse rate limit headers if present
            if hasattr(response, 'headers'):
                remaining = response.headers.get('x-ratelimit-remaining')
                reset = response.headers.get('x-ratelimit-reset')
                if remaining:
                    observed_limits.update(int(remaining), reset)

            return response
        except Exception as e:
            if hasattr(e, 'status_code') and e.status_code == 429:
                metrics.record_429_error()
            raise
    return wrapper
```

**Validation:**
- On startup, log configured tier and expected limits
- During runtime, log observed limits from response headers
- If observed limits differ significantly from configured (>20% deviation), log warning:
  ```
  WARNING: Observed rate limits differ from configured tier.
  Configured: tier1 (20 RPM), Observed: ~50 RPM remaining
  Consider updating GEMINI_API_TIER configuration.
  ```

**Sub-decisions:**
- **Current tier:** **Tier 1** (assumed based on project context: personal use, active development, likely upgraded from free tier). User should verify via Google AI Studio and set `GEMINI_API_TIER` environment variable.
- **Acceptable 429 rate:** 5% is a reasonable threshold. Can be increased to 8% during initial upload (system learning phase), then tightened to 3% for steady-state operation.
- **Failure mode:** Graceful degradation (slow down and retry). Circuit breaker ensures system eventually completes within 36-hour window. Fail-fast would be inappropriate for one-time upload—better to complete slowly than abort.

---

### Q8: Progress Tracking Granularity

**Question:** What progress metrics should be tracked and displayed?

**YOLO DECISION:** ⚠️ **Option A — Hierarchical tracking (file + batch + pipeline levels)**

**Rationale:**
- Confidence level: ⚠️ Recommended (Perplexity's comprehensive approach)
- Serves multiple audiences: end users (ETAs), developers (error rates), operations (throughput)
- Rich library supports hierarchical displays natively
- Critical for 36-hour deadline visibility: need ETAs to know if on track

**Implementation decisions:**

**Three-tier tracking:**

**Tier 1: File-level**
```python
class FileProgress:
    file_id: int
    file_name: str
    file_size_bytes: int
    state: str  # PENDING, UPLOADING, OPERATION_PENDING, INDEXED, FAILED
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
```

**Tier 2: Batch-level**
```python
class BatchProgress:
    batch_id: int
    batch_number: int
    files: List[FileProgress]
    total_bytes: int
    uploaded_bytes: int
    succeeded_count: int
    failed_count: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    @property
    def progress_pct(self) -> float:
        return (succeeded_count / len(files) * 100) if files else 0

    @property
    def eta_seconds(self) -> Optional[float]:
        if not started_at or succeeded_count == 0:
            return None
        elapsed = (datetime.now() - started_at).total_seconds()
        rate = succeeded_count / elapsed  # files per second
        remaining = len(files) - succeeded_count
        return remaining / rate
```

**Tier 3: Pipeline-level**
```python
class PipelineProgress:
    batches: List[BatchProgress]
    total_files: int
    total_bytes: int
    started_at: datetime

    @property
    def overall_progress_pct(self) -> float:
        completed = sum(b.succeeded_count for b in batches)
        return (completed / total_files * 100) if total_files > 0 else 0

    @property
    def eta_seconds(self) -> Optional[float]:
        completed_batches = [b for b in batches if b.completed_at]
        if len(completed_batches) < 2:
            return None  # Need at least 2 batches for reliable estimate

        # Calculate average rate from completed batches
        rates = [
            len(b.files) / (b.completed_at - b.started_at).total_seconds()
            for b in completed_batches
        ]
        avg_rate = sum(rates) / len(rates)  # files per second

        # Estimate remaining time
        remaining_files = total_files - sum(b.succeeded_count for b in batches)
        return remaining_files / avg_rate if avg_rate > 0 else None
```

**Display with Rich:**
```python
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
from rich.console import Console

console = Console()

with Progress(
    TextColumn("[progress.description]{task.description}"),
    BarColumn(),
    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    TimeRemainingColumn(),
    console=console
) as progress:
    # Overall pipeline progress
    overall_task = progress.add_task(
        "[green]Overall Upload (1,884 files)",
        total=pipeline.total_files
    )

    # Per-batch progress (13 batches)
    batch_tasks = {}
    for batch in pipeline.batches:
        task_id = progress.add_task(
            f"[blue]Batch {batch.batch_number} ({len(batch.files)} files)",
            total=len(batch.files)
        )
        batch_tasks[batch.batch_id] = task_id

    # Update loop
    while not pipeline.is_complete():
        # Update overall progress
        progress.update(
            overall_task,
            completed=sum(b.succeeded_count for b in pipeline.batches)
        )

        # Update per-batch progress
        for batch in pipeline.batches:
            progress.update(
                batch_tasks[batch.batch_id],
                completed=batch.succeeded_count
            )

        # Display ETA
        eta = pipeline.eta_seconds
        if eta:
            hours, remainder = divmod(int(eta), 3600)
            minutes, seconds = divmod(remainder, 60)
            console.print(f"Estimated time remaining: {hours}h {minutes}m {seconds}s")

        await asyncio.sleep(1)  # Update every second
```

**Metrics storage:**
```sql
CREATE TABLE IF NOT EXISTS progress_snapshots (
    id INTEGER PRIMARY KEY,
    snapshot_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    files_succeeded INTEGER,
    files_failed INTEGER,
    files_pending INTEGER,
    bytes_uploaded INTEGER,
    api_calls_total INTEGER,
    api_calls_429_errors INTEGER,
    current_concurrency INTEGER,
    circuit_breaker_state TEXT,
    estimated_eta_seconds INTEGER
);

-- Snapshot every 60 seconds for historical analysis
```

**Sub-decisions:**
- **Reporting channels:** Terminal only (Rich progress bars) for Phase 2. Web dashboard deferred to Phase 3. Log file includes snapshot data every 60 seconds for post-analysis.
- **Throughput metrics:** Track and display: files/minute, MB/second, operations/minute, 429 error rate %. Log to `progress_snapshots` table.
- **Progress scope:** Include operation completion (indexing). Overall progress = files with `state='INDEXED'` (not just uploaded). ETA accounts for both upload time and polling time.

---

### Q9: Crash Recovery Semantics

**Question:** How long does the system have to resume, and should recovery be automatic or manual?

**YOLO DECISION:** ⚠️ **Option A — Automatic recovery with 4-hour timeout**

**Rationale:**
- Confidence level: ⚠️ Recommended (Perplexity's detailed crash recovery protocol)
- Automatic recovery minimizes time-to-resume (critical for 48-hour window)
- 4-hour timeout is generous for recovery tasks, leaves 44-hour buffer
- Escalation path handles edge cases requiring manual intervention

**Implementation decisions:**

**Crash recovery protocol (automatic on startup):**
```python
CRASH_RECOVERY_TIMEOUT_SECONDS = 4 * 3600  # 4 hours

async def recover_from_crash():
    """Execute on startup if previous run was interrupted"""
    logger.info("Starting crash recovery protocol")

    # Step 1: Identify incomplete operations
    incomplete_ops = state_manager.get_incomplete_operations()
    logger.info(f"Found {len(incomplete_ops)} incomplete operations from previous run")

    # Step 2: Check operation status with Gemini
    for op_record in incomplete_ops:
        try:
            operation = client.operations.get(operation=op_record.operation_name)
            if operation.done:
                if operation.succeeded:
                    logger.info(f"Operation {op_record.file_id} completed during downtime")
                    state_manager.mark_file_as_succeeded(op_record.file_id)
                else:
                    logger.warning(f"Operation {op_record.file_id} failed during downtime")
                    state_manager.mark_file_as_failed(op_record.file_id, operation.error)
            else:
                logger.info(f"Operation {op_record.file_id} still in progress, will resume polling")
        except Exception as e:
            logger.error(f"Failed to check operation {op_record.operation_name}: {e}")

    # Step 3: Identify files pending upload (intent recorded but not uploaded)
    pending_uploads = state_manager.get_pending_uploads()
    logger.info(f"Found {len(pending_uploads)} files pending upload")

    # Step 4: Check for deadline-critical files (>40 hours since upload)
    deadline_critical = [
        f for f in incomplete_ops
        if (datetime.now() - f.upload_timestamp).total_seconds() > 144000  # 40 hours
    ]
    if deadline_critical:
        logger.critical(
            f"CRITICAL: {len(deadline_critical)} files near 48-hour file retention deadline. "
            "Prioritizing polling for these operations immediately."
        )
        # Prioritize these in polling queue
        state_manager.mark_files_as_priority(deadline_critical)

    # Step 5: Verify SQLite-Gemini consistency
    reconciliation_ok = await verify_and_reconcile_state()
    if not reconciliation_ok:
        logger.warning("State reconciliation found discrepancies. See logs for details.")

    logger.info("Crash recovery protocol complete. Resuming normal operation.")
    return len(deadline_critical) == 0  # Return health status

async def run_with_recovery_timeout():
    """Wrapper with timeout enforcement"""
    try:
        health_ok = await asyncio.wait_for(
            recover_from_crash(),
            timeout=CRASH_RECOVERY_TIMEOUT_SECONDS
        )
        if not health_ok:
            logger.warning("Recovery completed but found deadline-critical files. Manual review recommended.")
    except asyncio.TimeoutError:
        logger.critical(
            "Crash recovery exceeded 4-hour timeout. Files may be lost due to 48-hour retention deadline. "
            "Manual intervention required. Check SQLite database for files with state='UPLOAD_INITIATED' "
            "or 'UPLOAD_IN_PROGRESS' and timestamps >48 hours old."
        )
        raise
```

**Automatic startup check:**
```python
async def main():
    """Main entry point for upload command"""
    # Check if previous run was interrupted
    if state_manager.has_incomplete_work():
        logger.info("Detected incomplete work from previous run. Starting crash recovery.")
        await run_with_recovery_timeout()

    # Proceed with normal upload
    await upload_pipeline.run()
```

**Manual intervention path:**
- If crash recovery timeout exceeded (>4 hours), system logs critical error and exits
- Operator must manually inspect SQLite database:
  ```sql
  -- Find files that may have been lost
  SELECT file_path, upload_timestamp, operation_name, state
  FROM files
  WHERE state IN ('UPLOAD_INITIATED', 'UPLOAD_IN_PROGRESS')
    AND upload_timestamp < datetime('now', '-48 hours');
  ```
- Operator decisions: mark files as failed (re-upload later), or mark as lost (acceptable data loss)

**Sub-decisions:**
- **File objects deleted (>48 hours) but SQLite shows in progress:** Mark as `TIMEOUT_EXPIRED` in SQLite. Include in failed files count. Manual review to decide: re-upload (file still exists locally), or accept loss (rare failure case).
- **Automatic vs. manual trigger:** Automatic on every startup. System detects incomplete work via SQLite state and runs recovery automatically. No manual trigger needed.
- **Acceptable data loss:** If system is down >48 hours, expect data loss for files in the "uploaded but not yet indexed" window. This is acceptable edge case (<1% of files affected in worst-case 2-day outage). User can re-run upload command to retry failed files.

---

## Tier 3: Polish Decisions

### Q10: Concurrency Model — Single vs. Multi-Process

**Question:** Should the system support multiple Python processes uploading concurrently?

**YOLO DECISION:** 🔍 **Option A — Single-writer architecture (one primary process)**

**Rationale:**
- Confidence level: 🔍 Needs Clarification (Perplexity identified, but lower priority)
- Requirements don't mention multi-machine parallelization
- Single-process with `Semaphore(10)` concurrent uploads should suffice for 1,884 files
- Simplicity: no race conditions, no distributed locks, no circuit breaker state sharing
- Can defer multi-process support to Phase 5 if performance testing shows it's needed

**Implementation decisions:**

**Single-writer lock:**
```python
class UploaderInstance:
    def __init__(self, instance_id: str):
        self.instance_id = instance_id
        self.is_primary = False

    async def acquire_primary_lock(self, lock_timeout: int = 300):
        """Acquire exclusive primary lock via SQLite"""
        state_manager.begin_transaction()
        try:
            # Check for existing lock
            existing_lock = state_manager.get_primary_lock()
            if existing_lock:
                lock_age = (datetime.now() - existing_lock.acquired_at).total_seconds()
                if lock_age < lock_timeout:
                    raise AlreadyLockedError(
                        f"Primary lock held by instance {existing_lock.instance_id}. "
                        f"Age: {lock_age:.0f}s (timeout: {lock_timeout}s)"
                    )
                else:
                    # Lock expired (stale), can take over
                    logger.warning(f"Taking over expired lock from {existing_lock.instance_id}")

            # Acquire lock
            state_manager.record_primary_lock(
                instance_id=self.instance_id,
                acquired_at=datetime.now()
            )
            state_manager.commit()
            self.is_primary = True
            logger.info(f"Instance {self.instance_id} acquired primary lock")
        except Exception as e:
            state_manager.rollback()
            self.is_primary = False
            raise

    async def release_primary_lock(self):
        """Release primary lock (on shutdown)"""
        if not self.is_primary:
            return
        state_manager.delete_primary_lock(self.instance_id)
        self.is_primary = False
        logger.info(f"Instance {self.instance_id} released primary lock")

    async def heartbeat_loop(self):
        """Update lock timestamp every 60 seconds to prove liveness"""
        while self.is_primary:
            state_manager.update_primary_lock_timestamp(self.instance_id)
            await asyncio.sleep(60)
```

**Lock schema:**
```sql
CREATE TABLE IF NOT EXISTS primary_locks (
    instance_id TEXT PRIMARY KEY,
    acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Deduplication (idempotency):**
```sql
-- Prevent duplicate uploads if multiple processes somehow run
CREATE UNIQUE INDEX IF NOT EXISTS idx_file_upload_uniqueness
ON files(file_path, operation_name)
WHERE operation_name IS NOT NULL;
```

**Sub-decisions:**
- **Multi-process support:** Not supported in Phase 2. Single-instance operation only. If user needs higher throughput, they can increase `max_concurrent` in config (up to 15 concurrent uploads if rate limits allow).
- **Lock duration:** Primary lock held indefinitely while upload runs. Heartbeat updated every 60 seconds. Lock timeout: 5 minutes (if heartbeat hasn't updated in 5 minutes, lock is considered stale and can be taken over by new instance).
- **Lock conflict resolution:** If two instances somehow both acquire lock (unlikely with SQLite serializable transactions), the unique constraint on `files.operation_name` will cause one to fail on upload. Failed instance logs error and exits gracefully.

---

## Next Steps

1. ✅ Clarifications answered (YOLO mode with balanced strategy)
2. ⏭ Review answers if needed (all based on ✅ consensus or ⚠️ recommended synthesis)
3. ⏭ Proceed to `/gsd:plan-phase 2` to create execution plan

---

*Auto-generated by discuss-phase-ai --yolo (balanced strategy based on multi-provider synthesis)*
*Human review recommended before final implementation*
*Confidence markers: ✅ Consensus (both providers), ⚠️ Recommended (one provider with strong rationale), 🔍 Needs Clarification (lower priority)*
