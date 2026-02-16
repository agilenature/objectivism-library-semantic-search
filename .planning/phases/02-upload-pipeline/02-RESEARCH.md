# Phase 2: Upload Pipeline - Research

**Researched:** 2026-02-16
**Domain:** Gemini File Search API batch upload with async Python concurrency, resilience patterns, and SQLite state management
**Confidence:** MEDIUM-HIGH (API surface verified via official docs; some rate limit details undocumented)

## Summary

Phase 2 implements a reliable batch upload pipeline that moves ~1,884 text files from local SQLite state (Phase 1) into a Google Gemini File Search store. The core technical challenge is orchestrating async file uploads through a rate-limited API with crash recovery, progress visibility, and metadata attachment -- all constrained by a 48-hour file retention window on temporary File API objects.

The google-genai SDK (v1.63.0, released 2026-02-11) provides both sync and async clients. A critical architectural finding is that **metadata attachment requires a two-step upload pattern**: first `client.files.upload()` to create a temporary File object, then `client.file_search_stores.import_file()` with `custom_metadata` to import into the store. The single-step `upload_to_file_search_store()` method does not support custom_metadata in its documented config. This two-step pattern also provides better control over error handling (separate upload failures from import failures) and aligns naturally with the state tracking requirements.

The supporting stack is well-established: tenacity 9.1.4 for retry/backoff, aiosqlite 0.22.1 for async database access, Rich 13.x (already in project) for progress bars, and a custom circuit breaker built on top of pybreaker 1.4.1 or hand-rolled with rolling window metrics. Python 3.12+ asyncio.Semaphore provides the concurrency control primitive.

**Primary recommendation:** Use the two-step upload pattern (files.upload + import_file) with aiosqlite for async state management, tenacity for retry logic, and a custom circuit breaker with rolling-window 429 tracking. Structure the pipeline as three layers: upload orchestrator (semaphore-limited), operation poller (separate concurrency), and batch coordinator (logical grouping for state/progress).

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **48-Hour File Retention (Consensus):** One-time indexing operation. Raw File API objects expire after 48 hours (acceptable). Indexed data in File Search store persists indefinitely. Crash recovery must complete within 4 hours (44-hour buffer).

2. **Metadata Attachment (Consensus):** Two-tier approach:
   - Tier 1 (Searchable): 5-8 fields in Gemini via `custom_metadata` (or content injection fallback)
   - Tier 2 (Archive): 15-25 fields in SQLite only

3. **Batch Processing (Consensus):** Three-tier batching:
   - Tier 1: Micro-batches (`Semaphore(5-10)`) for concurrency control
   - Tier 2: Logical batches (100-200 files) for state management
   - Tier 3: Async operation lifecycle (operations complete independently)

4. **Operation Polling (Consensus):** Exponential backoff (5s to 60s), concurrent polling (20 operations), 1-hour timeout per operation.

5. **Circuit Breaker (Consensus):** Rolling window (last 100 requests), 5% 429 threshold, reduce concurrency 50% (7 to 3), 5-minute cool-down, gradual recovery.

6. **State Synchronization (Consensus):** SQLite-as-source-of-truth. Write intent before API call, idempotent retries, reconciliation on resume.

7. **Rate Limit Tier Detection (Recommended):** Hybrid approach - manual tier config (Tier 1 assumed: 20 RPM) + runtime header observation.

8. **Progress Tracking (Recommended):** Three-tier hierarchy (file/batch/pipeline), Rich progress bars, ETA estimates.

9. **Crash Recovery (Recommended):** Automatic recovery on startup, 4-hour timeout, prioritize deadline-critical files.

10. **Concurrency Model (Needs Clarification):** Single-writer architecture (one primary process), max 10 concurrent uploads.

### Claude's Discretion

No explicit Claude's Discretion section was defined in CONTEXT.md. The following areas are implicitly discretionary based on "Recommended" and "Needs Clarification" markers:
- Specific library choices for circuit breaker (pybreaker vs custom)
- aiosqlite vs sync sqlite3 with thread pool
- Exact schema design for upload tracking tables
- File content injection format (YAML vs JSON) for metadata fallback
- Specific Rich progress bar column configuration

### Deferred Ideas (OUT OF SCOPE)

- Multi-process distributed upload (deferred unless performance testing shows single-process is insufficient)
- Web dashboard for progress monitoring (terminal-only for Phase 2)
- Automatic tier detection from Google AI Studio API (manual config sufficient)

</user_constraints>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| google-genai | 1.63.0 | Gemini File Search API client (files, stores, operations) | Official Google SDK; provides sync + async via `client.aio`; released 2026-02-11 |
| tenacity | 9.1.4 | Exponential backoff with jitter for retries | De facto Python retry library; supports async; rich wait/stop/retry combinators |
| aiosqlite | 0.22.1 | Async SQLite wrapper for non-blocking DB ops in event loop | Only mature async sqlite3 wrapper; uses shared thread per connection |
| rich | 13.x | Progress bars, console output, hierarchical tracking | Already in project (Phase 1); native progress bar with multiple tasks |
| asyncio (stdlib) | 3.12+ | Event loop, Semaphore, gather, wait_for | Python standard library; Semaphore is the primitive for concurrency limiting |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pybreaker | 1.4.1 | Circuit breaker pattern base | Optional: use if its state machine fits; otherwise hand-roll with rolling window |
| collections.deque (stdlib) | 3.12+ | Rolling window for rate limit metrics | Fixed-size window tracking for 429 error rate calculation |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| aiosqlite | sync sqlite3 + `asyncio.to_thread()` | aiosqlite is cleaner API; to_thread works but is more boilerplate |
| pybreaker | Custom circuit breaker class | pybreaker doesn't natively support rolling-window 429 tracking or async; custom is likely better fit |
| tenacity | Custom retry loop | tenacity saves significant code; async-native; well-tested edge cases |

**Installation:**
```bash
pip install "google-genai>=1.63.0" "tenacity>=9.1" "aiosqlite>=0.22" "pybreaker>=1.4"
```

**Recommendation on pybreaker:** After research, pybreaker's model (fail_max consecutive failures) does not directly match the requirement (5% 429 rate over rolling window of 100 requests). **Recommend a custom circuit breaker** that wraps a `collections.deque(maxlen=100)` for the rolling window, with state machine (CLOSED/OPEN/HALF_OPEN) hand-rolled. This is ~80 lines of code and perfectly fits the requirements. pybreaker can be dropped from dependencies.

## Architecture Patterns

### Recommended Project Structure
```
src/objlib/
    __init__.py           # existing
    models.py             # existing (add upload-related models)
    database.py           # existing (extend with upload tables)
    config.py             # existing (extend with upload config)
    cli.py                # existing (add upload command)
    scanner.py            # existing (Phase 1)
    metadata.py           # existing (Phase 1)
    upload/
        __init__.py       # export public API
        client.py         # Gemini API client wrapper (files + stores + operations)
        orchestrator.py   # Batch orchestrator (3-tier: upload, poll, coordinate)
        circuit_breaker.py # Rolling-window circuit breaker with state machine
        rate_limiter.py   # Rate limit tier config + adaptive throttling
        state.py          # Upload state manager (aiosqlite, intent logging, reconciliation)
        progress.py       # Rich progress tracking (file/batch/pipeline hierarchy)
        recovery.py       # Crash recovery protocol
```

### Pattern 1: Two-Step Upload with Metadata
**What:** Upload file to Files API first, then import into File Search store with custom_metadata.
**When to use:** Always -- this is the only way to attach searchable metadata fields.
**Why:** The `upload_to_file_search_store()` single-step method does not support `custom_metadata` in its documented config. Only `import_file()` accepts custom_metadata.

```python
# Source: https://ai.google.dev/gemini-api/docs/file-search (official docs)
from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)

# Step 1: Upload file to Files API (creates temporary File object, 48hr TTL)
uploaded_file = await client.aio.files.upload(
    file=str(file_path),
    config={"display_name": display_name}
)

# Step 2: Import into File Search store WITH metadata
operation = await client.aio.file_search_stores.import_file(
    file_search_store_name=store_name,
    file_name=uploaded_file.name,
    config={
        "custom_metadata": [
            {"key": "category", "string_value": "course"},
            {"key": "course", "string_value": "OPAR"},
            {"key": "difficulty", "string_value": "introductory"},
            {"key": "year", "numeric_value": 2019},
            {"key": "quarter", "string_value": "Q1"},
            {"key": "quality_score", "numeric_value": 85},
        ]
    }
)

# Step 3: Poll operation until done
while not operation.done:
    await asyncio.sleep(5)
    operation = await client.aio.operations.get(operation)
```

### Pattern 2: Semaphore-Limited Concurrent Upload
**What:** Use asyncio.Semaphore to limit concurrent API calls.
**When to use:** For all upload and polling operations.

```python
# Source: Python 3.12 asyncio docs
import asyncio

class UploadOrchestrator:
    def __init__(self, max_concurrent: int = 7):
        self._upload_semaphore = asyncio.Semaphore(max_concurrent)
        self._poll_semaphore = asyncio.Semaphore(20)

    async def upload_file(self, file_path: str, metadata: dict):
        async with self._upload_semaphore:
            # Rate-limited upload
            return await self._do_upload(file_path, metadata)

    async def poll_operation(self, operation):
        async with self._poll_semaphore:
            return await self._do_poll(operation)

    async def process_batch(self, files: list):
        """Process a logical batch of files concurrently within semaphore limits."""
        tasks = [self.upload_file(f.path, f.metadata) for f in files]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
```

### Pattern 3: Write-Ahead State Tracking
**What:** Write intent to SQLite before making API call; update after API response.
**When to use:** Every upload and import operation, for crash recovery.

```python
# Ensures crash at any point leaves recoverable state
async def upload_with_state(self, file_path: str, metadata: dict):
    file_id = self._get_file_id(file_path)

    # BEFORE API call: record intent
    await self.db.execute(
        "UPDATE files SET status = 'uploading', updated_at = ? WHERE file_path = ?",
        (now_iso(), file_path)
    )
    await self.db.commit()

    try:
        # API call (may crash here)
        uploaded_file = await self.client.aio.files.upload(file=str(file_path))
        operation = await self.client.aio.file_search_stores.import_file(
            file_search_store_name=self.store_name,
            file_name=uploaded_file.name,
            config={"custom_metadata": self._build_metadata(metadata)}
        )

        # AFTER API call: record operation details
        await self.db.execute(
            """UPDATE files SET
                gemini_file_uri = ?, gemini_file_id = ?,
                upload_timestamp = ?, remote_expiration_ts = ?
            WHERE file_path = ?""",
            (uploaded_file.uri, uploaded_file.name,
             now_iso(), expiration_iso(hours=48), file_path)
        )
        await self.db.commit()
        return operation

    except Exception as e:
        await self.db.execute(
            "UPDATE files SET status = 'failed', error_message = ? WHERE file_path = ?",
            (str(e), file_path)
        )
        await self.db.commit()
        raise
```

### Pattern 4: Tenacity Async Retry with Operation Polling
**What:** Use tenacity for exponential backoff polling of long-running operations.
**When to use:** Polling indexing completion for each uploaded file.

```python
# Source: tenacity 9.1.4 docs (https://tenacity.readthedocs.io)
from tenacity import (
    AsyncRetrying, retry_if_result, stop_after_delay,
    wait_exponential, before_sleep_log
)
import logging

logger = logging.getLogger(__name__)

async def poll_until_done(self, operation, timeout_seconds: int = 3600):
    """Poll operation with exponential backoff: 5s -> 10s -> 20s -> 40s -> 60s (cap)."""
    async for attempt in AsyncRetrying(
        wait=wait_exponential(multiplier=1, min=5, max=60),
        stop=stop_after_delay(timeout_seconds),
        retry=retry_if_result(lambda op: not op.done),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
        reraise=True,
    ):
        with attempt:
            operation = await self.client.aio.operations.get(operation)
            if not operation.done:
                # Return the not-done operation; tenacity will retry
                return operation
    return operation
```

### Pattern 5: Rolling-Window Circuit Breaker
**What:** Custom circuit breaker tracking 429 error rate over last 100 requests.
**When to use:** Wraps all API calls to detect rate limiting and reduce concurrency.

```python
import collections
import time
from enum import Enum

class CircuitState(str, Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Backing off
    HALF_OPEN = "half_open" # Testing recovery

class RollingWindowCircuitBreaker:
    def __init__(
        self,
        window_size: int = 100,
        error_threshold: float = 0.05,  # 5%
        consecutive_threshold: int = 3,
        cooldown_seconds: float = 300,  # 5 minutes
    ):
        self._window = collections.deque(maxlen=window_size)
        self._error_threshold = error_threshold
        self._consecutive_threshold = consecutive_threshold
        self._cooldown_seconds = cooldown_seconds
        self._state = CircuitState.CLOSED
        self._opened_at: float | None = None
        self._consecutive_429s = 0

    def record_success(self):
        self._window.append(True)
        self._consecutive_429s = 0
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED

    def record_429(self):
        self._window.append(False)
        self._consecutive_429s += 1
        if self._should_trip():
            self._trip()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._opened_at >= self._cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
        return self._state

    @property
    def error_rate(self) -> float:
        if not self._window:
            return 0.0
        return sum(1 for x in self._window if not x) / len(self._window)

    def _should_trip(self) -> bool:
        return (
            self.error_rate > self._error_threshold
            or self._consecutive_429s >= self._consecutive_threshold
        )

    def _trip(self):
        self._state = CircuitState.OPEN
        self._opened_at = time.time()
```

### Anti-Patterns to Avoid
- **Single-step upload for metadata:** Using `upload_to_file_search_store()` when metadata is needed. It does not support `custom_metadata`. Always use the two-step pattern.
- **Sync sqlite3 in async code:** Calling `sqlite3.connect()` directly in async context blocks the event loop. Use aiosqlite.
- **Polling without backoff:** Polling operations every 1 second wastes API quota and risks 429 errors. Use exponential backoff starting at 5 seconds.
- **Global asyncio.gather without return_exceptions:** If one upload fails, it cancels all others. Always use `return_exceptions=True` in gather calls.
- **Committing after every row:** SQLite commits are expensive with WAL mode fsync. Batch commits at logical boundaries (per-file state is fine, not per-SQL-statement).
- **Ignoring File.state after upload:** After `files.upload()`, the File transitions through PROCESSING -> ACTIVE. Must wait for ACTIVE before calling `import_file()`. Attempting to import a PROCESSING file may fail.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exponential backoff with jitter | Custom sleep loops with manual delay calculation | tenacity `wait_exponential` + `wait_random` | Edge cases (overflow, jitter distribution, stop conditions) are subtle; tenacity handles them all |
| Async SQLite access | `asyncio.to_thread(sqlite3.execute, ...)` wrappers | aiosqlite | Dedicated thread per connection, proper cursor management, context managers |
| Progress bars with ETA | Custom print statements with elapsed/remaining math | Rich `Progress` with `TimeRemainingColumn` | Rich handles terminal width, refresh rates, multiple concurrent tasks, and smooth ETA calculation |
| HTTP retry logic | try/except loops with manual sleep | tenacity with `retry_if_exception_type` | Tenacity tracks attempt count, supports callbacks, handles async natively |
| File state machine | Manual if/elif chains for status transitions | Enum-based states with explicit transition validation | Existing `FileStatus` enum from Phase 1 can be extended |

**Key insight:** The upload pipeline's complexity is in orchestration (concurrency, state, retries, circuit breaking), not in any single operation. Use proven libraries for each primitive and focus implementation effort on the orchestration layer that connects them.

## Common Pitfalls

### Pitfall 1: File.state Not Checked Before Import
**What goes wrong:** After `files.upload()`, calling `import_file()` immediately while the File is still in PROCESSING state causes the import to fail or produce corrupt indexing.
**Why it happens:** `files.upload()` returns immediately with a File object, but the file may still be processing (especially for larger files).
**How to avoid:** Check `uploaded_file.state` after upload. If `state.name == "PROCESSING"`, poll with `files.get()` until `state.name == "ACTIVE"` before calling `import_file()`. For small text files (<1MB), this is usually instant, but always check.
**Warning signs:** Import operations failing with errors about invalid/unavailable files.

### Pitfall 2: 48-Hour TTL Race Condition
**What goes wrong:** File uploaded to Files API, but import_file not called within 48 hours (e.g., crash + long recovery). The temporary File object is deleted, import fails.
**Why it happens:** Files API objects have a hard 48-hour TTL. If the system is down for extended periods, uploaded-but-not-imported files are lost.
**How to avoid:** Track `upload_timestamp` and `remote_expiration_ts` in SQLite. During crash recovery, check if any uploaded files are approaching 48-hour deadline. Re-upload if expired. The 4-hour recovery window decision provides a 44-hour buffer.
**Warning signs:** `remote_expiration_ts` timestamps less than 8 hours in the future.

### Pitfall 3: Blocking the Event Loop with Sync SQLite
**What goes wrong:** Using sync `sqlite3` calls directly in async coroutines blocks the entire event loop, stopping all concurrent uploads.
**Why it happens:** The existing Phase 1 `Database` class uses sync `sqlite3.connect()`. Calling these methods from async code will block.
**How to avoid:** Either wrap the existing Database class with aiosqlite, or create a new async database layer specifically for upload state management. The Phase 1 Database class should remain sync for CLI commands that don't need async.
**Warning signs:** Uploads seem to run sequentially despite Semaphore allowing 7 concurrent.

### Pitfall 4: Circuit Breaker Oscillation
**What goes wrong:** Circuit breaker trips (OPEN), recovers (HALF_OPEN -> CLOSED), immediately trips again because the rate limit window hasn't fully reset.
**Why it happens:** After 5-minute cooldown, concurrency jumps back to full speed. The rolling window still has old 429 errors, and new burst of requests triggers more 429s.
**How to avoid:** Implement gradual recovery: start at Semaphore(3) after half-open success, increment by +1 every 20 consecutive successes, up to max(10). Reset the rolling window on successful transition to CLOSED.
**Warning signs:** Rapid state oscillation in circuit breaker logs (CLOSED -> OPEN -> HALF_OPEN -> CLOSED -> OPEN in quick succession).

### Pitfall 5: aiosqlite Connection Sharing
**What goes wrong:** Multiple coroutines sharing a single aiosqlite connection cause database locked errors or data corruption.
**Why it happens:** SQLite has limited concurrency even with WAL mode. aiosqlite uses a single thread per connection, serializing operations. But if BEGIN TRANSACTION is used across coroutine boundaries, interleaved operations break transaction isolation.
**How to avoid:** Use autocommit mode for simple reads/writes. For transactional operations (write intent -> API call -> record result), use explicit `async with db.execute("BEGIN IMMEDIATE")` and commit within the same coroutine. Do not hold transactions across `await` boundaries that invoke API calls.
**Warning signs:** `sqlite3.OperationalError: database is locked` errors during concurrent uploads.

### Pitfall 6: Operation Polling Quota Exhaustion
**What goes wrong:** Polling 200+ operations concurrently at 5-second intervals consumes significant API quota, triggering 429 errors on the polling endpoint.
**Why it happens:** Each `operations.get()` counts against RPM quota. With 200 pending operations polled every 5s = 40 RPM just for polling.
**How to avoid:** Use separate Semaphore(20) for polling concurrency. Apply exponential backoff (5s -> 60s). Batch polling: don't start polling immediately after upload; wait until a batch of uploads completes, then poll all at once with staggered intervals.
**Warning signs:** 429 errors from `operations.get()` calls, not from upload calls.

### Pitfall 7: Metadata Key Naming Conflicts
**What goes wrong:** Using metadata keys that conflict with Gemini internal fields, or using unsupported characters in key names.
**Why it happens:** The `custom_metadata` key naming rules are not fully documented.
**How to avoid:** Use lowercase alphanumeric keys with underscores only (e.g., `course`, `difficulty`, `year`). Test with a small batch of files before running full upload. Keep to 5-8 metadata fields as decided.
**Warning signs:** `INVALID_ARGUMENT` errors when calling `import_file()` with custom_metadata.

## Code Examples

Verified patterns from official sources:

### Creating a File Search Store
```python
# Source: https://ai.google.dev/gemini-api/docs/file-search
from google import genai

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Create store
file_search_store = client.file_search_stores.create(
    config={"display_name": "objectivism-library-v1"}
)
store_name = file_search_store.name  # e.g., "fileSearchStores/abc123"
```

### Two-Step Upload with Metadata (Async)
```python
# Source: https://ai.google.dev/gemini-api/docs/file-search
async def upload_and_import(
    client: genai.Client,
    store_name: str,
    file_path: str,
    display_name: str,
    metadata: list[dict],
) -> object:
    """Upload file and import with metadata. Returns operation."""
    # Step 1: Upload to Files API
    uploaded_file = await client.aio.files.upload(
        file=file_path,
        config={"display_name": display_name[:512]}  # 512 char limit
    )

    # Step 2: Wait for ACTIVE state (usually instant for small text files)
    while uploaded_file.state.name == "PROCESSING":
        await asyncio.sleep(2)
        uploaded_file = await client.aio.files.get(name=uploaded_file.name)

    if uploaded_file.state.name == "FAILED":
        raise RuntimeError(f"File processing failed: {uploaded_file.name}")

    # Step 3: Import into store with metadata
    operation = await client.aio.file_search_stores.import_file(
        file_search_store_name=store_name,
        file_name=uploaded_file.name,
        config={
            "custom_metadata": metadata
        }
    )

    return operation, uploaded_file
```

### Tenacity Async Retry for API Calls
```python
# Source: tenacity docs (https://tenacity.readthedocs.io/en/latest/)
from google.genai import errors
from tenacity import (
    AsyncRetrying, retry_if_exception_type, stop_after_attempt,
    wait_exponential, wait_random, before_sleep_log
)
import logging

logger = logging.getLogger(__name__)

async def upload_with_retry(client, file_path: str, max_attempts: int = 3):
    """Upload file with exponential backoff on transient errors."""
    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type((errors.APIError, ConnectionError, TimeoutError)),
        wait=wait_exponential(multiplier=1, min=2, max=30) + wait_random(0, 2),
        stop=stop_after_attempt(max_attempts),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    ):
        with attempt:
            result = await client.aio.files.upload(file=file_path)
            return result
```

### Rich Hierarchical Progress Bars
```python
# Source: Rich docs (https://rich.readthedocs.io/en/latest/progress.html)
from rich.progress import (
    Progress, BarColumn, TextColumn, TimeRemainingColumn,
    SpinnerColumn, MofNCompleteColumn
)

def create_upload_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
    )

# Usage in async context:
async def run_upload_with_progress(files, batch_size=150):
    progress = create_upload_progress()
    with progress:
        overall = progress.add_task("[green]Pipeline", total=len(files))

        for batch_num, batch in enumerate(chunk_list(files, batch_size)):
            batch_task = progress.add_task(
                f"[blue]Batch {batch_num + 1}",
                total=len(batch)
            )

            for file in batch:
                await upload_file(file)
                progress.update(batch_task, advance=1)
                progress.update(overall, advance=1)

            # Mark batch as complete (removes from display)
            progress.update(batch_task, visible=False)
```

### aiosqlite State Management
```python
# Source: aiosqlite docs (https://github.com/omnilib/aiosqlite)
import aiosqlite

class AsyncUploadStateManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self):
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA foreign_keys=ON")

    async def record_upload_intent(self, file_path: str):
        """Write intent BEFORE API call."""
        await self._db.execute(
            """UPDATE files SET status = 'uploading',
               updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')
               WHERE file_path = ?""",
            (file_path,)
        )
        await self._db.commit()

    async def record_upload_success(
        self, file_path: str, gemini_uri: str, gemini_id: str, operation_name: str
    ):
        """Record successful upload AFTER API response."""
        await self._db.execute(
            """UPDATE files SET
                gemini_file_uri = ?, gemini_file_id = ?,
                upload_timestamp = strftime('%Y-%m-%dT%H:%M:%f', 'now'),
                remote_expiration_ts = strftime('%Y-%m-%dT%H:%M:%f', 'now', '+48 hours')
               WHERE file_path = ?""",
            (gemini_uri, gemini_id, file_path)
        )
        await self._db.commit()

    async def record_upload_failure(self, file_path: str, error_msg: str):
        await self._db.execute(
            """UPDATE files SET status = 'failed', error_message = ?
               WHERE file_path = ?""",
            (error_msg, file_path)
        )
        await self._db.commit()

    async def get_pending_files(self, limit: int = 200) -> list:
        """Get files ready for upload."""
        async with self._db.execute(
            """SELECT file_path, content_hash, filename, file_size, metadata_json
               FROM files WHERE status = 'pending'
               ORDER BY file_path LIMIT ?""",
            (limit,)
        ) as cursor:
            return await cursor.fetchall()

    async def close(self):
        if self._db:
            await self._db.close()
```

### Error Handling with google.genai.errors
```python
# Source: google-genai SDK README
from google.genai import errors

async def safe_api_call(client, file_path: str):
    try:
        return await client.aio.files.upload(file=file_path)
    except errors.APIError as e:
        if e.code == 429:
            # Rate limited -- signal circuit breaker
            raise RateLimitError(f"429 rate limit: {e.message}") from e
        elif e.code == 503:
            # Service unavailable -- transient, retry
            raise TransientError(f"503 service unavailable: {e.message}") from e
        elif e.code == 400:
            # Bad request -- permanent, don't retry
            raise PermanentError(f"400 bad request: {e.message}") from e
        else:
            raise
```

### Metadata Filter Syntax (for Phase 3 queries, but important to validate in Phase 2)
```python
# Source: https://ai.google.dev/gemini-api/docs/file-search + AIP-160 (google.aip.dev/160)
# Filters use AIP-160 syntax: key=value, AND, OR, comparison operators

# String comparison
metadata_filter = 'course = "OPAR"'

# Numeric comparison
metadata_filter = 'year >= 2019'

# Combined with AND
metadata_filter = 'course = "OPAR" AND difficulty = "introductory"'

# Combined with OR
metadata_filter = 'category = "course" OR category = "book"'

# Used in query config:
config = types.GenerateContentConfig(
    tools=[types.Tool(
        file_search=types.FileSearch(
            file_search_store_names=[store_name],
            metadata_filter='course = "OPAR" AND difficulty = "introductory"'
        )
    )]
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `google-generativeai` (old SDK) | `google-genai` (new SDK) | 2025 | Completely different API surface; `genai.Client()` replaces `genai.configure()` |
| `genai.upload_file()` (old) | `client.files.upload()` (new) | 2025 | New SDK uses client instance pattern, not module-level functions |
| Corpus API (old) | File Search Store API (new) | 2025 | `create_corpus()` replaced by `file_search_stores.create()`; documents model changed |
| tqdm for progress | Rich Progress | 2024+ | Rich provides hierarchical tasks, better terminal rendering, already in project |
| sync-only upload | `client.aio.*` async pattern | 2025-2026 | google-genai SDK natively supports async via `.aio` accessor |

**Deprecated/outdated:**
- **google-generativeai package:** The old package used `genai.configure(api_key=...)` and `genai.upload_file()`. The reference script `02_upload_to_gemini.py` in the project uses this old SDK. The new `google-genai` SDK (v1.63.0) uses `genai.Client()` with a completely different API surface.
- **Corpus API:** The old `genai.create_corpus()` / `corpus.create_document()` / `corpus.query()` pattern from the reference script is deprecated. File Search Stores replace Corpora entirely.
- **tqdm:** The reference script uses tqdm. Phase 1 already uses Rich, so Phase 2 should use Rich progress bars for consistency.

## Schema Extensions for Phase 2

The existing Phase 1 `files` table already has the columns needed for basic upload tracking (`status`, `gemini_file_uri`, `gemini_file_id`, `upload_timestamp`, `remote_expiration_ts`, `embedding_model_version`). Phase 2 needs additional tables:

```sql
-- Track upload operations (long-running async operations from import_file)
CREATE TABLE IF NOT EXISTS upload_operations (
    operation_name TEXT PRIMARY KEY,        -- Gemini operation ID
    file_path TEXT NOT NULL,                -- FK to files.file_path
    operation_state TEXT NOT NULL DEFAULT 'pending',
        -- pending, in_progress, succeeded, failed, timeout
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    last_polled_at TEXT,
    completed_at TEXT,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);

-- Track logical batches
CREATE TABLE IF NOT EXISTS upload_batches (
    batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_number INTEGER NOT NULL,
    file_count INTEGER NOT NULL,
    succeeded_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
        -- pending, in_progress, completed, failed
    started_at TEXT,
    completed_at TEXT
);

-- Add batch_id to files (nullable, set when batch is created)
-- NOTE: ALTER TABLE to add column; or handle via migration
-- ALTER TABLE files ADD COLUMN batch_id INTEGER REFERENCES upload_batches(batch_id);

-- Single-writer lock
CREATE TABLE IF NOT EXISTS upload_locks (
    lock_id INTEGER PRIMARY KEY CHECK(lock_id = 1),  -- Only one row allowed
    instance_id TEXT NOT NULL,
    acquired_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    last_heartbeat TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

-- Progress snapshots (for historical analysis and ETA calculation)
CREATE TABLE IF NOT EXISTS progress_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_time TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    files_succeeded INTEGER,
    files_failed INTEGER,
    files_pending INTEGER,
    files_uploading INTEGER,
    api_calls_total INTEGER,
    api_errors_429 INTEGER,
    current_concurrency INTEGER,
    circuit_breaker_state TEXT
);
```

## Gemini File Search API Reference Summary

### Key API Methods (google-genai SDK v1.63.0)

| Method | Async Version | Returns | Purpose |
|--------|--------------|---------|---------|
| `client.file_search_stores.create(config)` | `client.aio.file_search_stores.create(config)` | `FileSearchStore` | Create a new store |
| `client.files.upload(file, config)` | `client.aio.files.upload(file, config)` | `File` | Upload file (48hr TTL) |
| `client.file_search_stores.import_file(...)` | `client.aio.file_search_stores.import_file(...)` | `ImportFileOperation` | Import file into store with metadata |
| `client.operations.get(operation)` | `client.aio.operations.get(operation)` | `Operation` | Poll operation status |
| `client.files.get(name)` | `client.aio.files.get(name)` | `File` | Get file info/state |
| `client.file_search_stores.get(name)` | `client.aio.file_search_stores.get(name)` | `FileSearchStore` | Get store info |

### Custom Metadata Types
- `string_value`: Text fields (category, course, difficulty, quarter)
- `numeric_value`: Numeric fields (year, week, quality_score)
- Filter syntax: AIP-160 (e.g., `'course = "OPAR" AND year >= 2019'`)

### File Object States
- `PROCESSING`: File uploaded, being processed (cannot import yet)
- `ACTIVE`: File ready for import into store
- `FAILED`: File processing failed

### Storage Limits (by tier)
| Tier | Storage | Typical RPM |
|------|---------|-------------|
| Free | 1 GB | ~5 RPM |
| Tier 1 | 10 GB | ~20 RPM |
| Tier 2 | 100 GB | ~200 RPM |
| Tier 3 | 1 TB | ~2000 RPM |

Project uses ~112 MB (11% of free tier, 1.1% of Tier 1).

### Important Constraints
- Per-file maximum: 100 MB
- Display name max: 512 characters
- File name: lowercase alphanumeric + dashes, max 40 chars
- Store recommendation: under 20 GB per store
- File TTL: 48 hours (temporary File API objects)
- Indexed data: persists indefinitely in File Search store

## Open Questions

1. **Does `upload_to_file_search_store()` support `custom_metadata` in its config?**
   - What we know: Official docs only show `custom_metadata` on `import_file()`. The `upload_to_file_search_store()` config shows `display_name` and `chunking_config` only.
   - What's unclear: The SDK types file may have additional parameters not shown in docs. The `UploadToFileSearchStoreConfig` type definition was not accessible.
   - Recommendation: **Use the two-step pattern (files.upload + import_file) to guarantee metadata support.** If during implementation we discover `upload_to_file_search_store()` also supports `custom_metadata`, we can simplify, but the two-step pattern is the safe default.

2. **Exact rate limits for Files API and File Search Store operations**
   - What we know: Limits depend on tier and are viewable in Google AI Studio. General guidance: Free ~5 RPM, Tier 1 ~20 RPM. Storage: Free 1GB, Tier 1 10GB.
   - What's unclear: Whether file upload RPM is separate from model generation RPM. Whether `operations.get()` has separate rate limits. Whether `import_file()` has separate limits from `files.upload()`.
   - Recommendation: Start conservative (Semaphore(5) for uploads, Semaphore(20) for polling). Use circuit breaker to detect and adapt. Log all 429 responses with full context for tuning.

3. **Does Gemini deduplicate identical file uploads?**
   - What we know: The CLARIFICATIONS-ANSWERED.md states "Gemini File Search API is idempotent: uploading the same file with same metadata returns existing operation/document."
   - What's unclear: This claim is not verified against official documentation. Deduplication behavior may depend on file content, name, or other factors.
   - Recommendation: Do not rely on server-side deduplication. Implement client-side deduplication via SQLite state tracking (check `gemini_file_id` before uploading). This is safer and reduces unnecessary API calls.

4. **Maximum number of custom_metadata keys per file**
   - What we know: Documentation does not specify a maximum.
   - What's unclear: Whether there's a hard limit on metadata keys or total metadata size.
   - Recommendation: Keep to 5-8 keys as decided (well within any reasonable limit). Test with a single file before batch upload.

5. **Async client lifecycle management**
   - What we know: `client.aio` provides async methods. `async with Client().aio as aclient` for context manager. `await aclient.aclose()` for explicit cleanup.
   - What's unclear: Whether a single client instance can be shared across all coroutines, or whether multiple clients are needed. Thread safety of the async client.
   - Recommendation: Create a single `genai.Client()` instance at startup, use `client.aio.*` for all async operations. The SDK is designed for this pattern. Wrap in async context manager for clean shutdown.

## Sources

### Primary (HIGH confidence)
- Google Gemini File Search API docs (https://ai.google.dev/gemini-api/docs/file-search) -- API methods, custom_metadata, operation polling, store management, chunking config, metadata_filter syntax
- google-genai SDK README (https://github.com/googleapis/python-genai) -- async client pattern, error handling, file upload API
- google-genai SDK source (https://github.com/googleapis/python-genai/blob/main/google/genai/file_search_stores.py) -- method signatures, parameter types, async versions
- PyPI google-genai v1.63.0 (https://pypi.org/project/google-genai/) -- version, release date, dependencies

### Secondary (MEDIUM confidence)
- tenacity docs (https://tenacity.readthedocs.io/en/latest/) -- async retry patterns, wait strategies, callback hooks
- aiosqlite docs (https://github.com/omnilib/aiosqlite) -- async SQLite wrapper, connection management
- Rich progress docs (https://rich.readthedocs.io/en/latest/progress.html) -- hierarchical progress bars, custom columns
- pybreaker docs (https://pypi.org/project/pybreaker/) -- circuit breaker pattern, state machine
- Python asyncio.Semaphore docs (https://docs.python.org/3/library/asyncio-sync.html) -- concurrency limiting
- AIP-160 filter syntax (https://google.aip.dev/160) -- metadata filter operators, string/numeric comparisons
- Google Files API reference (https://ai.google.dev/api/files) -- File object structure, state machine, MIME types

### Tertiary (LOW confidence)
- Gemini API rate limits page (https://ai.google.dev/gemini-api/docs/rate-limits) -- general rate limit dimensions; specific numbers for File API/File Search not documented (must check AI Studio)
- Claim that Gemini deduplicates identical uploads (from CLARIFICATIONS-ANSWERED.md, not verified against official docs)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - versions verified via PyPI, API patterns verified via official docs
- Architecture (two-step upload pattern): HIGH - verified that import_file supports custom_metadata while upload_to_file_search_store does not show it in docs
- Architecture (async patterns): MEDIUM-HIGH - client.aio pattern verified in SDK README; specific file_search_stores async methods confirmed in source
- Pitfalls: MEDIUM - based on API documentation constraints and general async Python knowledge; some specific failure modes are hypothetical
- Rate limits: LOW-MEDIUM - exact numbers not documented; tier structure verified but specific RPM for File API operations unknown
- Circuit breaker design: MEDIUM - pattern is well-established; specific tuning (5%, 100 window, 5min cooldown) is from CONTEXT.md decisions, not empirically validated

**Research date:** 2026-02-16
**Valid until:** 2026-03-16 (30 days -- google-genai SDK is actively updated but core File Search API is stable)
