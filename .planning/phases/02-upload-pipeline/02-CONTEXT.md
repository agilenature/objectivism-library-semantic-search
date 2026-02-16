# CONTEXT.md — Phase 2: Upload Pipeline

**Generated:** 2026-02-15
**Phase Goal:** User can upload the entire library to Gemini File Search reliably -- with rate limiting, resume from interruption, and progress visibility -- resulting in a fully indexed and queryable store
**Synthesis Source:** Multi-provider AI analysis (OpenAI gpt-5.2-2025-12-11, Gemini Pro, Perplexity Sonar Deep Research)

---

## Overview

Phase 2 implements the reliable upload pipeline that moves 1,884 files from local SQLite state (built in Phase 1) into Google's Gemini File Search store. The challenge spans multiple systems: the Gemini File Search API with undocumented rate limits, async Python concurrency patterns, SQLite durability guarantees, and resilience patterns—all constrained by a 48-hour file retention window and a 36-hour processing deadline.

Three AI providers analyzed the requirements and identified 9 critical gray areas where specifications lack sufficient detail for production implementation. These ambiguities exist primarily at the intersection of Google's managed infrastructure, operational resilience, and state synchronization across distributed components.

**Confidence markers:**
- ✅ **Consensus** — Both Gemini and Perplexity identified this as critical
- ⚠️ **Recommended** — One provider identified with strong rationale and industry citations
- 🔍 **Needs Clarification** — Mentioned by one provider, potentially important

---

## Gray Areas Identified

### ✅ 1. 48-Hour File Retention Constraint and Architecture Risk (Consensus)

**What needs to be decided:**
How the system handles the Gemini File API's ephemeral nature (raw files auto-delete after 48 hours) against the requirement for a "fully indexed and queryable store."

**Why it's ambiguous:**
The Google Gemini File API treats uploaded files as temporary resources with a 48-hour TTL, meant for immediate context caching. However, data imported into a File Search store persists indefinitely. The requirements mention "raw files delete after 48 hours" but don't clarify whether:
- This is acceptable (files are indexed, deletion is expected)
- The system must refresh/re-upload files before the 48-hour deadline
- Crash recovery must complete within 48 hours to avoid data loss

**Provider synthesis:**
- **Gemini:** Emphasized this as a "Critical Architecture Risk." Noted that if files auto-delete after 48 hours, the "fully indexed store" ceases to exist unless the system uses Context Caching (paid per hour) or treats this as a one-time indexing operation where ephemeral files are acceptable.
- **Perplexity:** Confirmed the 48-hour File API behavior and noted that indexed data in File Search stores persists indefinitely. The critical window is between upload and indexing completion—if the system crashes and takes >48 hours to resume, temporary File objects are deleted, breaking the pipeline.

**Proposed implementation decision:**
Treat this as a **one-time indexing operation with TTL tracking**:
1. Acknowledge that raw File API objects are ephemeral (48-hour TTL)
2. Once files are indexed into the File Search store, they persist indefinitely (this is the "fully indexed store")
3. Add `upload_timestamp` and `expiration_timestamp` fields to SQLite to track TTL
4. Flag operations nearing the 48-hour deadline as critical priority during crash recovery
5. Establish a **4-hour crash recovery timeout**: system must complete resume operations within 4 hours of crash, leaving a 44-hour buffer before the 48-hour deadline

**Open questions:**
- Is the user explicitly using Gemini Context Caching (paid per hour), or is this a one-time indexing operation?
- Does "fully indexed and queryable store" imply the system must be queryable forever, or just immediately after upload completes?
- If a file's temporary File object is deleted (after 48 hours) but SQLite shows it as "in progress," should the system retry, mark as failed, or require manual intervention?

---

### ✅ 2. Metadata Attachment Implementation (Consensus)

**What needs to be decided:**
Where and how to attach 20-30 metadata fields to each uploaded file, given that the Gemini File API has limited native metadata support.

**Why it's ambiguous:**
UPLD-08 requires "attach rich metadata to each uploaded file (20-30 fields)," but the standard Gemini `files.create` API accepts only `display_name` and MIME type. It generally does not support attaching arbitrary, searchable key-value pairs (like "author," "publication_year," "concept_tags") to the file object itself in the way an S3 Object Tag or Vector DB entry does.

**Provider synthesis:**
- **Gemini:** Recommended **content injection**—inject metadata into the text content of the file before uploading (e.g., prepend a YAML or JSON header with the 30 metadata fields). This ensures metadata is searchable as part of the document content.
- **Perplexity:** Proposed a **two-tier approach**: (1) Searchable metadata (5-8 fields) attached via the `custom_metadata` parameter if supported by the SDK version, and (2) Archive metadata (12-22 fields) stored in SQLite for internal tracking and audit. Noted that `metadata_filter` parameter may not be fully supported in current API versions.

**Proposed implementation decision:**
Implement a **hybrid two-tier strategy**:

**Tier 1: Searchable Metadata (5-8 fields)** — Attach via `custom_metadata` if SDK supports it:
- `category`, `source_system`, `date_added`, `priority`, `quality_score`, `access_level`, `version`, `language`
- If `custom_metadata` is not supported, inject these into file content as a header (YAML or JSON format)

**Tier 2: Archive Metadata (15-25 fields)** — Store in SQLite for internal tracking:
- `file_hash`, `original_size_bytes`, `extracted_keywords`, `extracted_summary`, `processing_duration_ms`, `scanner_quality_issues`, `last_modified_timestamp`, `owner_email`, `department`, `retention_policy`, `compliance_tags`, `data_classification`

**Implementation approach:**
```python
# Extract searchable fields
searchable_meta = {
    'category': metadata.get('category'),
    'quality_score': metadata.get('quality_score'),
    'difficulty': metadata.get('difficulty'),
    'course': metadata.get('course'),
    'year': metadata.get('year')
}

# Store archive metadata in SQLite
state_manager.save_file_metadata(file_path, full_metadata)

# Upload with searchable metadata only
operation = client.file_search_stores.upload_to_file_search_store(
    file=file_path,
    file_search_store_name=store_id,
    config={
        'display_name': metadata.get('display_name'),
        'custom_metadata': searchable_meta  # If supported by SDK
    }
)
```

**Open questions:**
- Does the `google-genai` SDK v1.63.0+ support the `custom_metadata` parameter? (Must verify during implementation)
- Of the 20-30 fields, how many are for real-time search filtering vs. archival and audit?
- Should metadata be updateable after upload, or is it immutable?
- Will metadata filtering be performed at query time (Gemini API), or pre-filtered using SQLite (client-side)?

---

### ✅ 3. Batch Processing Strategy: Sliding Window vs. Strict Batches (Consensus)

**What needs to be decided:**
Whether "batch" (UPLD-07: 100-200 files per batch) means "upload 100, wait for all 100 to finish, then start next 100" (strict batches) or "maintain a queue of 100, refilling as they finish" (sliding window).

**Why it's ambiguous:**
The requirement specifies batch size but not batch semantics:
- **Strict Batches:** Easier to reason about ("Batch 1 Complete"), but if 1 file hangs (polling for index), the other 99 workers sit idle, wasting the 36-hour window.
- **Sliding Window:** More efficient (continuous throughput), but makes "Resume from Interruption" harder because state is scattered across batch boundaries.

**Provider synthesis:**
- **Gemini:** Recommended **strict batches with timeouts**—process files in logical groups of 100-200, but don't let stragglers block the pipeline. If a file stays in "processing" state for >5 minutes, mark it as "Failed/Timeout" and allow the batch to close.
- **Perplexity:** Proposed a **three-tier batching strategy**: (1) Micro-batches for concurrency control (Semaphore), (2) Logical batches (100-200 files) for state management and progress tracking, (3) Upload operation lifecycle (recognizing that operations complete asynchronously).

**Proposed implementation decision:**
Implement **three-tier batching** (Perplexity's approach):

**Tier 1: Micro-batches for concurrency control**
- Use `Semaphore(5)` to `Semaphore(10)` to limit concurrent `uploadToFileSearchStore` calls
- Each file uploaded individually in parallel, but with controlled concurrency
- Respects rate limits without requiring explicit grouping

**Tier 2: Logical batches for state management**
- Group files into 100-200 file cohorts for progress tracking, checkpointing, and reporting
- At 1,884 files, this creates approximately 9-19 batches
- Each logical batch tracked as a unit in SQLite with a `batch_id`, allowing resumption at batch level

**Tier 3: Upload operation lifecycle**
- Each `uploadToFileSearchStore` call initiates a long-running operation that transitions through states: PENDING → IN_PROGRESS → SUCCEEDED/FAILED
- Polling for completion (UPLD-04) occurs independently of batching decisions; operations may complete asynchronously relative to logical batch boundaries

**Implementation structure:**
```python
class FileSearchBatchOrchestrator:
    def __init__(self, client, store_id, batch_size=100, max_concurrent=7):
        self.client = client
        self.store_id = store_id
        self.batch_size = batch_size
        self.semaphore = asyncio.Semaphore(max_concurrent)  # Tier 1: Concurrency
        self.state_manager = SQLiteStateManager()

    async def process_logical_batch(self, files: List[FileMetadata]):
        """Tier 2: Process 100-200 files in parallel, respecting concurrency limit"""
        tasks = [self.upload_file(f.path, f.metadata) for f in files]
        operations = await asyncio.gather(*tasks, return_exceptions=True)
        self.state_manager.save_batch_checkpoint(operations)
        return BatchResult(operations)
```

**Open questions:**
- Should batch size (100-200) be adjustable based on real-world performance metrics, or is this a fixed architectural constraint?
- Does the 36-hour completion deadline apply to uploading all 1,884 files, or to the end-to-end process including indexing completion?
- If a logical batch partially completes (e.g., 150 of 200 files succeed), should retry logic attempt to reprocess the entire batch, or individual failed files?

---

### ✅ 4. Operation Polling Strategy and Quota Management (Consensus)

**What needs to be decided:**
How frequently to poll long-running operations for indexing completion status, and how to avoid exhausting rate limits on the `operations.get()` endpoint.

**Why it's ambiguous:**
UPLD-04 specifies "operation polling for indexing completion status," but does not address:
- Polling frequency (1 second? 10 seconds? 60 seconds?)
- Timeout duration (how long to wait before assuming an operation has stalled?)
- Whether to poll all pending operations simultaneously or sequentially
- How polling requests count against rate limits

Google's documentation recommends polling "at intervals as recommended by the API service," but the Gemini API does not provide explicit retry-after headers or polling frequency guidance. Polling too frequently wastes resources and may exceed rate limits; polling too slowly risks missing completion windows.

**Provider synthesis:**
- **Gemini:** Recommended **exponential backoff polling per file**—do not poll all 200 files in a loop. After upload, wait $T$ seconds, check status. If still PROCESSING, wait $T \times 1.5$ seconds. Cap polling interval at 30 seconds. Crucial: polling requests must count towards Circuit Breaker logic.
- **Perplexity:** Proposed **adaptive polling with exponential backoff**—start with 5-second polling interval, increasing exponentially up to 60 seconds using the `tenacity` library's `wait_exponential` pattern. Stop after 1 hour if operation doesn't complete. Poll up to 20 operations concurrently (different from upload concurrency).

**Proposed implementation decision:**
Implement **adaptive polling with exponential backoff and state tracking**:

**Polling strategy:**
```python
from tenacity import retry, wait_exponential, stop_after_delay, retry_if_result

class OperationPoller:
    async def poll_operation(self, operation_name: str) -> Operation:
        """Poll operation with exponential backoff"""
        @retry(
            wait=wait_exponential(multiplier=1, min=5, max=60),
            stop=stop_after_delay(3600),  # Stop after 1 hour
            retry=retry_if_result(lambda op: not op.done),
            reraise=True
        )
        async def get_operation():
            operation = await self.client.operations.get(operation=operation_name)
            if operation.done:
                return operation
            raise OperationPending()  # Will retry with increased backoff

        return await get_operation()
```

**State tracking schema:**
```sql
CREATE TABLE IF NOT EXISTS file_upload_operations (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL UNIQUE,
    operation_name TEXT NOT NULL,
    operation_state TEXT NOT NULL,  -- PENDING, IN_PROGRESS, SUCCEEDED, FAILED
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_polled_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    FOREIGN KEY(file_id) REFERENCES files(id)
);

CREATE TABLE IF NOT EXISTS operation_polls (
    id INTEGER PRIMARY KEY,
    operation_id INTEGER NOT NULL,
    polled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    state_before TEXT,
    state_after TEXT,
    poll_duration_ms INTEGER,
    FOREIGN KEY(operation_id) REFERENCES file_upload_operations(id)
);
```

**Concurrent polling with semaphore:**
```python
async def poll_all_pending_operations(self, max_concurrent: int = 20):
    """Poll all pending operations with controlled concurrency"""
    pending_ops = self.state_manager.get_pending_operations()
    semaphore = asyncio.Semaphore(max_concurrent)

    async def poll_with_limit(op_name: str):
        async with semaphore:
            return await self.poll_operation(op_name)

    results = await asyncio.gather(
        *[poll_with_limit(op.operation_name) for op in pending_ops],
        return_exceptions=True
    )
    return results
```

**Open questions:**
- What is the expected operation completion latency under normal conditions? (seconds, minutes, hours?)
- Should the system maintain a priority queue for operations nearing the 48-hour file retention deadline?
- If an operation fails to complete within 1 hour, should it be retried, or escalated to manual intervention?
- What is the specific Gemini API rate limit (RPM) for `operations.get()`? (Usually higher than `files.create`, but must be verified)

---

### ✅ 5. Circuit Breaker Threshold Tuning and Recovery (Consensus)

**What needs to be decided:**
Precise definition of "5% 429 errors" (5% over what time window?), how quickly the circuit should recover, and what happens to in-flight requests when the circuit opens.

**Why it's ambiguous:**
UPLD-06 specifies a circuit breaker that "reduce[s] rate 50% after 5% 429 errors," but:
- What is the measurement window? (last 100 requests? last 5 minutes? cumulative?)
- How does "50% rate reduction" translate to implementation? (reduce concurrency from 7 to 3? add delays?)
- How does the system transition from "open" (backoff) to "closed" (normal operation)?

**Provider synthesis:**
- **Gemini:** Recommended **step-up probing**—if circuit breaker trips, enter "cool-down" mode for 5 minutes. After 5 minutes of clean operation (error rate <1%), increment concurrency by +1 every 20 successful uploads until reaching max (10).
- **Perplexity:** Proposed **multi-level circuit breaker with separate thresholds**—use a rolling window (last 100 requests) rather than fixed time window. Distinguish between 429 (rate limit) and other errors. Circuit states: Closed (normal) → Open (backoff after 5% 429 errors or 3 consecutive 429s) → Half-Open (test recovery after 5 minutes) → Closed (success) or Open (failure).

**Proposed implementation decision:**
Implement a **multi-level circuit breaker with rolling window**:

```python
import collections
from pybreaker import CircuitBreaker

class ResilientCircuitBreaker:
    def __init__(self):
        self.upload_breaker = CircuitBreaker(
            fail_max=10,           # Open after 10 failures
            reset_timeout=300,     # Try recovery after 5 minutes
            expected_exception=RateLimitError,
            listeners=[BackoffListener()]
        )
        self.metrics = RateLimitMetrics(window_size=100)

    class RateLimitMetrics:
        def __init__(self, window_size: int = 100):
            self.request_states = collections.deque(maxlen=window_size)

        def record_request(self, success: bool, error_code: int = None):
            self.request_states.append({
                'success': success,
                'error_code': error_code,
                'timestamp': time.time()
            })

        def get_429_error_rate(self) -> float:
            """Calculate 429-specific error rate over rolling window"""
            if not self.request_states:
                return 0.0
            rate_limit_errors = sum(
                1 for r in self.request_states if r['error_code'] == 429
            )
            return rate_limit_errors / len(self.request_states)
```

**Circuit breaker state machine:**
1. **Closed State (Normal):** Accept all requests at normal rate (concurrency 7, minimal delays)
2. **Trip Condition:** When 429 error rate >5% over last 100 requests OR >3 consecutive 429 errors, transition to Open
3. **Open State (Backoff):** Reduce concurrency to 3, add 5-second delay between requests, reject new uploads for 5 minutes
4. **Half-Open State (Testing):** After 5 minutes, attempt single request with normal rate
5. **Close Condition:** If half-open request succeeds, reset to Closed; if fails, return to Open

**Recovery strategy:**
- Reset error window on successful transitions to Closed state
- Increment concurrency gradually: +1 every 20 successful uploads until reaching max (10)
- Log all state transitions for observability

**Open questions:**
- Should the circuit breaker apply globally to all uploads, or per-batch to allow partial batch failures?
- What constitutes "success" for a half-open test—does the operation need to complete (potentially hours), or just the initial API call?
- Should in-flight operations be cancelled when the circuit opens, or allowed to complete?

---

### ✅ 6. State Synchronization Between SQLite and Gemini API (Consensus)

**What needs to be decided:**
How to maintain consistency between local SQLite state and remote Gemini API state, especially when the system crashes after uploading a file but before writing to SQLite.

**Why it's ambiguous:**
UPLD-10 requires "resume capability from any interruption point using SQLite state," but synchronization semantics are undefined:
- If system crashes after uploading a file but before writing to SQLite → file is indexed in Gemini but local state shows "not uploaded"
- If SQLite shows file as uploaded but Gemini has no record → resumption would skip the file
- What is the source of truth? SQLite or Gemini?

Three possible consistency models, each with tradeoffs:
1. **SQLite-as-Source-of-Truth:** Local SQLite is authoritative. On resumption, verify that files marked "uploaded" in SQLite actually exist in Gemini, retry any that don't.
2. **Gemini-as-Source-of-Truth:** Query Gemini for actual document count and reconcile with SQLite. Expensive (API calls).
3. **Dual-Write with Verification:** Write to SQLite after Gemini succeeds, verify state on resumption.

**Provider synthesis:**
- **Gemini:** Identified this as the "Orphaned File Risk." Recommended **pre-flight check**—before uploading, check if file hash/name exists in Gemini (if List API allows filtering). Update SQLite immediately after receiving API response ID, before polling for indexing. Split status into `UPLOADED` and `INDEXED`.
- **Perplexity:** Proposed **SQLite-as-Source-of-Truth with periodic Gemini verification**—write intent to SQLite before API call, then call Gemini API. If Gemini succeeds but SQLite write fails, the API call is idempotent (retry produces same result). On resume, run a verification pass to reconcile state.

**Proposed implementation decision:**
Implement **SQLite-as-Source-of-Truth with idempotent retries and reconciliation**:

**Core strategy:**
```python
class StateManager:
    async def upload_file_with_state_tracking(self, file_path: str, metadata: dict):
        """Upload with transactional state tracking"""
        file_id = self._get_or_create_file_id(file_path)

        # Step 1: Write intent to SQLite before attempting upload
        self.state_manager.mark_file_as_uploading(
            file_id,
            state='UPLOAD_INITIATED',
            operation_name=None
        )

        try:
            # Step 2: Perform Gemini API call
            operation = await self.client.file_search_stores.upload_to_file_search_store(
                file=file_path,
                file_search_store_name=self.store_id,
                config={'display_name': metadata.get('display_name')}
            )

            # Step 3: Update SQLite with operation details
            self.state_manager.mark_file_as_uploading(
                file_id,
                state='UPLOAD_IN_PROGRESS',
                operation_name=operation.name
            )
            return operation

        except Exception as e:
            # Step 4: Mark failure in SQLite for retry logic
            self.state_manager.mark_file_upload_failed(file_id, str(e))
            raise
```

**Reconciliation logic on resume:**
```python
async def verify_and_reconcile_state(self):
    """Check SQLite against Gemini state on resume"""
    uploaded_files = self.state_manager.get_files_marked_as_succeeded()
    store_docs = self.client.file_search_stores.documents.list(self.store_id)
    store_doc_names = {doc.name for doc in store_docs}

    discrepancies = []
    for file_record in uploaded_files:
        expected_doc_name = f"fileSearchStores/{self.store_id}/documents/{file_record.file_id}"
        if expected_doc_name not in store_doc_names:
            discrepancies.append(file_record)

    if discrepancies:
        logger.warning(f"Found {len(discrepancies)} state mismatches during reconciliation")
        for file_record in discrepancies:
            self.state_manager.mark_file_as_pending_retry(file_record.file_id)

    return len(discrepancies) == 0
```

**Idempotency for retries (UPLD-05):**
```python
async def safe_retry_file_upload(self, file_id: int, max_retries: int = 3):
    """Retry upload with idempotency guarantee"""
    file_record = self.state_manager.get_file(file_id)

    for attempt in range(max_retries):
        try:
            # Re-upload with same metadata—Gemini recognizes as duplicate
            operation = await self.upload_file_with_state_tracking(
                file_record.path,
                file_record.metadata
            )
            return operation
        except Exception as e:
            if attempt < max_retries - 1:
                delay = 2 ** attempt  # Exponential backoff
                await asyncio.sleep(delay)
            else:
                raise
```

**Open questions:**
- In a distributed environment (multiple worker processes), how should state be synchronized to avoid race conditions?
- What is the acceptable time lag between Gemini showing a file as indexed and SQLite reflecting this state?
- If reconciliation reveals files in Gemini not in SQLite, should they be deleted, or adopted into the state tracking?

---

### ⚠️ 7. Rate Limit Tier Detection and Dynamic Awareness (Recommended)

**What needs to be decided:**
How to detect the current Gemini API rate limit tier (Free, Tier 1, 2, 3) and dynamically adjust upload behavior based on tier capacity.

**Why it's ambiguous:**
The circuit breaker (UPLD-06) requires knowing the current rate limit tier to calculate what "50% reduction" means numerically. Gemini API rate limits vary significantly by tier: Free tier allows 5 RPM, Tier 1 allows higher limits, Tier 2/3 scale much higher. However, the rate limits are "not guaranteed and actual capacity may vary," and the google-genai SDK does not provide a runtime method to query current rate limits or tier status.

**Provider synthesis:**
- **Perplexity (only provider that covered this):** Proposed a **three-component rate limit management system**: (1) Tier detection at startup (query Google AI Studio or require explicit tier specification), (2) Runtime observation and header parsing (capture rate limit info from response headers), (3) Circuit breaker with adaptive rate limiting (track 429 errors, reduce concurrency, test recovery).

**Proposed implementation decision:**
Implement **three-component rate limit management**:

**Component 1: Tier detection at startup**
```python
RATE_LIMIT_TIERS = {
    'free': {'rpm': 5, 'tpm': 125000, 'rpd': 100},
    'tier1': {'rpm': 20, 'tpm': 500000, 'rpd': None},
    'tier2': {'rpm': 200, 'tpm': 5000000, 'rpd': None},
    'tier3': {'rpm': 2000, 'tpm': 50000000, 'rpd': None},
}

# Load from environment or config file
CURRENT_TIER = os.getenv('GEMINI_API_TIER', 'free')
rate_limits = RATE_LIMIT_TIERS[CURRENT_TIER]
```

**Component 2: Runtime observation**
```python
async def make_api_call_with_rate_observation(func):
    """Decorator that observes rate limit state from responses"""
    async def wrapper(*args, **kwargs):
        try:
            response = await func(*args, **kwargs)
            if hasattr(response, 'headers'):
                remaining = response.headers.get('x-ratelimit-remaining')
                if remaining:
                    state.update_rate_limit_state(remaining)
            return response
        except Exception as e:
            if e.status_code == 429:
                state.record_429_error()
            raise
    return wrapper
```

**Component 3: Adaptive rate limiting**
- Embed rate limit awareness in retry logic
- Each retry attempt checks current rate limit state and adjusts delays
- Circuit breaker thresholds scaled based on tier capacity

**Open questions:**
- Is the system operating on a Free, Tier 1, 2, or 3 account? Can this be determined dynamically, or must it be configured?
- What is the acceptable error rate for 429 responses? Is 5% a hard limit, or can this be higher during expected peak periods?
- Should the system implement "graceful degradation" (slow down and retry) or "fail-fast" (report error and halt)?

---

### ⚠️ 8. Progress Tracking Granularity and Reporting (Recommended)

**What needs to be decided:**
What progress metrics to track and display, and at what granularity (file count, byte count, time estimates, API calls, error rates).

**Why it's ambiguous:**
UPLD-09 specifies "progress tracking and reporting with Rich progress bars," but does not define:
- Should progress be reported as percentage of files uploaded, bytes uploaded, operations completed, or estimated time?
- What level of detail? (per-file, per-batch, pipeline-level?)
- Who is the audience? (end users want ETAs, developers want API call counts, operations want resource utilization)

**Provider synthesis:**
- **Perplexity (only provider that covered this):** Proposed **hierarchical progress tracking with multiple levels**: (1) File-level progress (finest granularity), (2) Batch-level aggregation (logical batch of 100-200 files), (3) Pipeline-level aggregation (entire 1,884-file upload). Display with Rich progress bars showing overall task, per-batch tasks, and ETAs.

**Proposed implementation decision:**
Implement **three-tier hierarchical progress tracking**:

**Tier 1: File-level progress**
```python
class FileProgress:
    def __init__(self, file_id: int, file_name: str, file_size_bytes: int):
        self.file_id = file_id
        self.name = file_name
        self.size = file_size_bytes
        self.state = 'PENDING'  # PENDING, UPLOADING, OPERATION_PENDING, SUCCEEDED, FAILED
        self.started_at = None
        self.completed_at = None
```

**Tier 2: Batch-level aggregation**
```python
class BatchProgress:
    def __init__(self, batch_id: int, files: List[FileProgress]):
        self.batch_id = batch_id
        self.files = files
        self.total_bytes = sum(f.size for f in files)
        self.uploaded_bytes = 0
        self.succeeded_count = 0
        self.failed_count = 0

    @property
    def progress_pct(self) -> float:
        total = len(self.files)
        return (self.succeeded_count / total * 100) if total > 0 else 0
```

**Tier 3: Pipeline-level aggregation**
```python
class PipelineProgress:
    def __init__(self, total_files: int):
        self.batches = []
        self.total_files = total_files

    @property
    def overall_progress_pct(self) -> float:
        completed = sum(b.succeeded_count for b in self.batches)
        return (completed / self.total_files * 100) if self.total_files > 0 else 0

    @property
    def eta_seconds(self) -> Optional[float]:
        """Estimate completion time based on historical rate"""
        completed_batches = [b for b in self.batches if b.completed_at]
        if len(completed_batches) < 2:
            return None

        rates = [b.file_count / (b.completed_at - b.started_at).total_seconds()
                 for b in completed_batches]
        avg_rate = sum(rates) / len(rates)
        remaining = self.total_files - sum(b.succeeded_count for b in self.batches)
        return remaining / avg_rate if avg_rate > 0 else None
```

**Display with Rich:**
```python
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn

with Progress(
    TextColumn("[progress.description]{task.description}"),
    BarColumn(),
    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    TimeRemainingColumn(),
) as progress:
    overall_task = progress.add_task("[green]Overall Upload", total=total_files)

    for batch in batches:
        batch_task = progress.add_task(f"[blue]Batch {batch.id}", total=len(batch.files))
        # Update tasks as upload progresses
```

**Open questions:**
- Should progress be reported in real-time to a web dashboard, written to logs, or both?
- Are there specific metrics (e.g., throughput in files/minute, bytes/second) that operations teams need?
- Should progress include estimates for operation completion (indexing), or only upload completion?

---

### ⚠️ 9. Crash Recovery Semantics and Resume Window (Recommended)

**What needs to be decided:**
How long the system has to resume after a crash before data loss becomes likely, and what the recovery protocol should be.

**Why it's ambiguous:**
UPLD-10 requires resumption from "any interruption point," but:
- If system crashes while uploading batch 3, which files were successfully uploaded vs. in-flight vs. need retry?
- If system crashes during the 48-hour window before operations complete, resumption is time-critical
- How long is the system allowed to take to recover?

SQLite WAL mode provides durability guarantees, but writes are only durable if explicitly committed. The system must define a crash recovery protocol specifying: minimum commit frequency, what state must be written before API calls, how to handle inconsistencies, and recovery timeout.

**Provider synthesis:**
- **Perplexity (only provider that covered this):** Proposed a **write-ahead crash recovery model** with explicit WAL checkpoints: (1) Write upload intent to SQLite before API call and commit, (2) Perform API call (may crash), (3) Record API success/failure with operation name. On startup, execute recovery protocol: identify incomplete operations, check operation status with Gemini, identify pending uploads, prioritize deadline-critical files, verify consistency. Establish 4-hour resume window (44-hour buffer before 48-hour deadline).

**Proposed implementation decision:**
Implement **write-ahead crash recovery with WAL checkpoints**:

**Step 1: Pre-API-call state write**
```python
async def upload_file_crash_safe(self, file_path: str, metadata: dict):
    """Upload with crash recovery—write intent before API call"""
    file_id = self._get_or_create_file_id(file_path)

    # STEP 1: Write upload intent and commit before API call
    self.state_manager.begin_transaction()
    try:
        self.state_manager.record_upload_intent(
            file_id=file_id,
            state='INTENT_RECORDED'
        )
        self.state_manager.commit()  # Explicit commit
    except Exception as e:
        self.state_manager.rollback()
        raise

    # STEP 2: Perform API call (may crash)
    operation = self.client.file_search_stores.upload_to_file_search_store(...)

    # STEP 3: Record success with operation name
    self.state_manager.record_upload_success(file_id, operation.name)
    self.state_manager.commit()
```

**Step 2: Crash recovery protocol**
```python
async def recover_from_crash(self):
    """Execute crash recovery on startup"""
    logger.info("Starting crash recovery")

    # Identify incomplete operations
    incomplete_ops = self.state_manager.get_incomplete_operations()

    # Check operation status with Gemini
    for op_record in incomplete_ops:
        operation = self.client.operations.get(operation=op_record.operation_name)
        if operation.done:
            self.state_manager.mark_file_as_succeeded(op_record.file_id)

    # Check for files near 48-hour deadline
    deadline_critical = [
        f for f in incomplete_ops
        if (datetime.now() - f.created_at).total_seconds() > 172800
    ]
    if deadline_critical:
        logger.critical(f"CRITICAL: {len(deadline_critical)} files near 48-hour deadline")

    # Verify consistency
    await self.verify_and_reconcile_state()
```

**Step 3: 4-hour recovery timeout**
```python
CRASH_RECOVERY_TIMEOUT_SECONDS = 4 * 3600  # 4 hours

async def run_with_recovery_timeout():
    try:
        await asyncio.wait_for(
            recover_from_crash(),
            timeout=CRASH_RECOVERY_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        logger.critical("Recovery exceeded 4-hour timeout. Manual intervention required.")
        raise
```

**Open questions:**
- If a file's temporary File object is deleted (after 48 hours) but SQLite shows "in progress," how should the system respond?
- Should crash recovery run automatically on startup, or require manual intervention?
- What is the acceptable data loss window if the system is down longer than 48 hours?

---

### 🔍 10. Concurrency Control and Multi-Process Coordination (Needs Clarification)

**What needs to be decided:**
Whether multiple Python processes should be supported (distributed upload), and how to prevent race conditions if multiple workers run simultaneously.

**Why it's ambiguous:**
UPLD-02 specifies Semaphore-based concurrency (5-10 concurrent) for async operations within one process. However, there's no specification of:
- Whether multiple processes should be supported
- How to prevent the same file from being uploaded twice if multiple workers run
- How to coordinate circuit breaker state across workers

Python's `asyncio` is single-threaded event-loop concurrency, so `Semaphore` prevents concurrent execution within one process. But if multiple Python processes are started, they would simultaneously upload files from SQLite, potentially duplicating work. SQLite WAL mode supports multi-process access, but doesn't provide application-level locks.

**Provider synthesis:**
- **Perplexity (only provider that covered this):** Proposed a **single-writer architecture** with distributed-ready design: designate one process as primary uploader via exclusive lock in SQLite. Other processes (if any) are read-only for monitoring. Use unique constraints to prevent duplicate uploads. Share circuit breaker state via SQLite if multi-process support is needed.

**Proposed implementation decision:**
Implement **single-writer architecture** (simplest, meets requirements):

```python
class UploaderInstance:
    async def acquire_primary_lock(self, lock_timeout: int = 300):
        """Acquire exclusive primary lock via SQLite"""
        self.state_manager.begin_transaction()
        try:
            existing_lock = self.state_manager.get_primary_lock()
            if existing_lock and (datetime.now() - existing_lock.acquired_at).total_seconds() < lock_timeout:
                raise AlreadyLockedError(f"Lock held by {existing_lock.instance_id}")

            self.state_manager.record_primary_lock(self.instance_id)
            self.state_manager.commit()
            self.is_primary = True
        except Exception:
            self.state_manager.rollback()
            raise
```

**Lock schema:**
```sql
CREATE TABLE IF NOT EXISTS primary_locks (
    instance_id TEXT PRIMARY KEY,
    acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);
```

**Idempotent file deduplication:**
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_file_upload_uniqueness
ON file_uploads(file_path, operation_name)
WHERE operation_name IS NOT NULL;
```

**Open questions:**
- Is the system expected to support multiple concurrent uploader instances, or is single-instance operation acceptable?
- Should the primary lock be held indefinitely, or released periodically to allow failover?

---

## Summary: Decision Checklist

Before planning Phase 2, confirm these decisions:

**Tier 1 (Blocking — ✅ Consensus):**
- [ ] **48-Hour TTL Constraint:** Accept that raw files delete after 48 hours (indexed data persists). Crash recovery must complete within 4 hours.
- [ ] **Metadata Strategy:** Two-tier approach (searchable fields in Gemini, archive fields in SQLite). Verify if SDK supports `custom_metadata`.
- [ ] **Batching Strategy:** Three-tier batching (micro-batches for concurrency, logical batches for state, async operation lifecycle).
- [ ] **Polling Strategy:** Exponential backoff (5s → 60s), concurrent polling (20 operations), timeout after 1 hour.
- [ ] **Circuit Breaker:** Rolling window (last 100 requests), 5% 429 threshold, 50% rate reduction, 5-minute cool-down with gradual recovery.
- [ ] **State Synchronization:** SQLite-as-source-of-truth, write intent before API call, reconciliation on resume, idempotent retries.

**Tier 2 (Important — ⚠️ Recommended):**
- [ ] **Rate Limit Tier:** Specify tier (free/tier1/tier2/tier3) in configuration. Runtime header parsing for dynamic awareness.
- [ ] **Progress Tracking:** Three-tier hierarchy (file/batch/pipeline), Rich progress bars, ETA estimates based on historical rate.
- [ ] **Crash Recovery:** Write-ahead logging, explicit commits, 4-hour recovery timeout, prioritize deadline-critical files.

**Tier 3 (Polish — 🔍 Needs Clarification):**
- [ ] **Concurrency Model:** Single-writer architecture (one primary process). Multi-process support deferred unless explicitly needed.

---

## Next Steps

**YOLO Mode (current):**
1. ✅ CONTEXT.md generated with multi-provider synthesis
2. ⏭ Generate CLARIFICATIONS-NEEDED.md with tiered questions
3. ⏭ Auto-generate CLARIFICATIONS-ANSWERED.md using synthesis recommendations (YOLO mode)
4. ⏭ Ask user if they want to proceed to `/gsd:plan-phase 2`

---

*Multi-provider synthesis by: OpenAI gpt-5.2-2025-12-11, Gemini Pro, Perplexity Sonar Deep Research*
*Generated: 2026-02-15*
*YOLO Mode: Enabled (auto-answers will be generated)*
