# Architecture Research

**Domain:** Semantic Search / RAG Pipeline (Python, Gemini File Search API, SQLite)
**Researched:** 2026-02-15
**Confidence:** HIGH

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLI / Query Interface                        │
│  ┌───────────────┐  ┌──────────────────┐  ┌──────────────────────┐ │
│  │ Search CLI    │  │ Filter Builder   │  │ Synthesis Engine     │ │
│  └───────┬───────┘  └────────┬─────────┘  └──────────┬───────────┘ │
│          │                   │                       │             │
├──────────┴───────────────────┴───────────────────────┴─────────────┤
│                        Orchestration Layer                          │
│  ┌───────────────┐  ┌──────────────────┐  ┌──────────────────────┐ │
│  │ Pipeline      │  │ Rate Limiter     │  │ State Manager        │ │
│  │ Coordinator   │  │ + Batcher        │  │ (SQLite)             │ │
│  └───────┬───────┘  └────────┬─────────┘  └──────────┬───────────┘ │
│          │                   │                       │             │
├──────────┴───────────────────┴───────────────────────┴─────────────┤
│                        Processing Layer                             │
│  ┌───────────────┐  ┌──────────────────┐  ┌──────────────────────┐ │
│  │ Library       │  │ Metadata         │  │ Upload              │ │
│  │ Scanner       │  │ Extractor        │  │ Pipeline            │ │
│  └───────────────┘  └──────────────────┘  └──────────────────────┘ │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                        External Services                            │
│  ┌──────────────────────────┐  ┌──────────────────────────────────┐ │
│  │ Gemini File Search API   │  │ Gemini generateContent API      │ │
│  │ (Upload, Index, Store)   │  │ (Query, Synthesize)             │ │
│  └──────────────────────────┘  └──────────────────────────────────┘ │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                        Persistence Layer                            │
│  ┌──────────────────────────┐  ┌──────────────────────────────────┐ │
│  │ SQLite State DB          │  │ Local File System               │ │
│  │ (WAL mode)               │  │ (Objectivism Library)           │ │
│  └──────────────────────────┘  └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| Library Scanner | Recursively discover files, detect changes via hash/mtime comparison against SQLite state | Python `pathlib` + `hashlib`, directory walker with configurable root |
| Metadata Extractor | Parse hierarchical folder structure into semantic metadata (author, work, section, edition) | Path parsing rules specific to library's naming conventions |
| State Manager | Track file discovery, upload status, change detection, resume points | SQLite with WAL mode, ACID transactions for atomic status updates |
| Rate Limiter + Batcher | Enforce API rate limits, batch uploads, exponential backoff with jitter | `asyncio.Semaphore`, `tenacity` for retry, token-aware batching |
| Upload Pipeline | Coordinate file upload to Gemini File Search stores, poll for completion, record results | Async upload with completion polling, idempotent upsert semantics |
| Pipeline Coordinator | Orchestrate scan-then-upload-then-verify workflow, handle interruptions | Sequential phase execution with checkpoint-based resume |
| Search CLI | Accept queries, apply metadata filters, display results with citations | `argparse` or `click`, formatted output with source attribution |
| Filter Builder | Translate user filter intent into Gemini File Search store selection + query constraints | Map metadata dimensions to store organization |
| Synthesis Engine | Combine retrieved passages with query for Gemini generateContent, format response | Prompt engineering with context window management |

## Recommended Project Structure

```
src/
├── scanner/                # Phase 1: Library scanning
│   ├── __init__.py
│   ├── discovery.py        # Recursive file discovery
│   ├── metadata.py         # Hierarchical path -> metadata extraction
│   └── change_detector.py  # Hash/mtime comparison against state DB
├── uploader/               # Phase 2: Upload pipeline
│   ├── __init__.py
│   ├── pipeline.py         # Upload orchestration and batching
│   ├── rate_limiter.py     # Rate limiting and backoff logic
│   └── gemini_client.py    # Gemini File Search API wrapper
├── query/                  # Phase 3: Query interface
│   ├── __init__.py
│   ├── search.py           # Semantic search with filters
│   ├── filters.py          # Metadata filter construction
│   └── synthesis.py        # Response synthesis via generateContent
├── state/                  # Shared: State management
│   ├── __init__.py
│   ├── db.py               # SQLite connection, schema, migrations
│   └── models.py           # Data classes for files, chunks, batches
├── common/                 # Shared utilities
│   ├── __init__.py
│   ├── config.py           # Configuration loading
│   └── logging.py          # Structured logging setup
├── cli.py                  # CLI entry points
└── config.yaml             # Runtime configuration
```

### Structure Rationale

- **scanner/:** Isolated because it has zero API dependencies. Can run offline. Produces metadata + file inventory stored in SQLite. Build and test first without any API key.
- **uploader/:** Separated from scanner because it is the most complex component (API interaction, rate limiting, async operations, error recovery). Has its own retry/resume logic distinct from scanning.
- **query/:** Separated because it is the consumer-facing interface. Different error handling profile (user-facing errors vs. batch processing errors). Can evolve independently.
- **state/:** Shared across all phases because scanner writes state, uploader reads and updates state, query reads state. Single source of truth via SQLite.
- **common/:** Thin shared utilities. Config and logging are cross-cutting. Keep this minimal to avoid a "utils junk drawer."

## Architectural Patterns

### Pattern 1: Three-Phase Pipeline with SQLite Checkpoints

**What:** The system operates in three distinct phases (scan, upload, query) connected through a shared SQLite state database. Each phase reads the state left by the previous phase and writes its own state. Phases can run independently and resume from interruption.

**When to use:** When the pipeline stages have different runtime characteristics (scan is fast and local, upload is slow and API-bound, query is interactive) and must be independently restartable.

**Trade-offs:**
- PRO: Each phase is independently testable and restartable
- PRO: SQLite provides ACID guarantees for state transitions
- PRO: No message queue infrastructure needed
- CON: Sequential phase execution (not a problem for this use case)
- CON: SQLite single-writer constraint (mitigated by WAL mode)

**Example:**
```python
# Each phase reads from and writes to shared state
class ScanPhase:
    def __init__(self, state_db: StateManager, library_root: Path):
        self.state = state_db
        self.root = library_root

    def run(self):
        """Scan library, record new/changed files in state DB."""
        for file_path in self.root.rglob("*"):
            if file_path.is_file():
                file_hash = compute_hash(file_path)
                status = self.state.record_file(file_path, file_hash)
                # status: 'new', 'changed', or 'unchanged'

class UploadPhase:
    def __init__(self, state_db: StateManager, gemini_client: GeminiClient):
        self.state = state_db
        self.client = gemini_client

    async def run(self):
        """Upload pending files to Gemini, update state on completion."""
        pending = self.state.get_files_by_status('pending')
        for batch in self.create_batches(pending):
            results = await self.client.upload_batch(batch)
            for file_path, result in results:
                self.state.mark_uploaded(file_path, result.store_id)
```

### Pattern 2: Idempotent Processing with Content Hashing

**What:** Every file is identified by its content hash. Reprocessing a file that has not changed is a no-op. Reprocessing a file that has changed replaces the old version cleanly. The system never creates duplicates.

**When to use:** Always, for any pipeline that may be interrupted and restarted.

**Trade-offs:**
- PRO: Safe to rerun at any time without side effects
- PRO: Change detection is automatic via hash comparison
- PRO: No "cleanup on restart" logic needed
- CON: Must compute file hashes (fast for text, acceptable for the library's file sizes)

**Example:**
```python
def should_process(file_path: Path, state: StateManager) -> bool:
    """Determine if file needs processing based on content hash."""
    current_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
    existing = state.get_file_record(file_path)

    if existing is None:
        return True  # New file
    if existing.content_hash != current_hash:
        return True  # Changed file
    if existing.upload_status == 'failed':
        return True  # Previously failed, retry
    return False      # Unchanged and successfully processed
```

### Pattern 3: Managed RAG via Gemini File Search (Delegation Pattern)

**What:** Instead of building a custom chunking + embedding + vector store pipeline, delegate chunking, embedding, and indexing entirely to the Gemini File Search API. The system uploads whole files and Gemini handles the rest internally. Our pipeline's job is to manage *what* gets uploaded, track state, and provide the query interface.

**When to use:** When using Gemini File Search as the backend. This dramatically simplifies the architecture because Gemini handles chunking, embedding, vector storage, and retrieval internally.

**Trade-offs:**
- PRO: Eliminates need for local chunking logic, embedding API calls, and vector store management
- PRO: Gemini handles optimal chunking strategy, embedding model selection, and index optimization
- PRO: Reduces pipeline complexity from 7 stages to 3 (scan, upload, query)
- CON: Less control over chunking strategy (but configurable via `chunking_config`)
- CON: Vendor lock-in to Gemini ecosystem
- CON: Storage tier limits (1GB free, up to 1TB at tier 3)
- CON: 100MB per-file limit

**How it simplifies the architecture:**
```
Traditional RAG:  Scan -> Parse -> Chunk -> Embed -> Store -> Index -> Query
Gemini File Search: Scan -> Upload (Gemini handles chunk/embed/store/index) -> Query
```

**Example:**
```python
# Upload to Gemini File Search -- Gemini handles chunking and embedding
operation = client.file_search_stores.upload_to_file_search_store(
    file=str(file_path),
    file_search_store_name=store.name,
    config={"display_name": file_path.stem}
)

# Poll for completion (async indexing)
while not operation.done:
    await asyncio.sleep(5)
    operation = client.operations.get(name=operation.name)

# Query -- Gemini handles retrieval and synthesis
response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="What is Rand's view on the relationship between reason and emotion?",
    config={
        "tools": [{
            "file_search": {
                "file_search_store_names": [store.name]
            }
        }]
    }
)
```

## Data Flow

### Ingestion Flow (Phases 1 + 2)

```
Local File System (Objectivism Library)
    │
    ▼
[Library Scanner]
    │  Recursively walk directory tree
    │  For each file: compute hash, extract path metadata
    │
    ▼
[State Manager (SQLite)]
    │  Compare hash against stored state
    │  Result: 'new' | 'changed' | 'unchanged'
    │  Record file metadata: path, hash, mtime, hierarchy metadata
    │
    ▼
[Upload Pipeline]
    │  Read pending files from state DB
    │  Batch by size constraints (100MB per file limit)
    │  For each batch:
    │    ├── Rate limit check (semaphore + backoff)
    │    ├── Upload to Gemini File Search store
    │    ├── Poll for indexing completion
    │    ├── On success: update state → 'uploaded'
    │    └── On failure: update state → 'failed' + error detail
    │
    ▼
[Gemini File Search Store]
    Gemini handles: chunking → embedding → vector indexing
    Data persists until manual deletion (no TTL)
```

### Query Flow (Phase 3)

```
[User Query + Filters]
    │
    ▼
[Filter Builder]
    │  Map user filters (author, work, topic) to
    │  appropriate File Search store(s) and query constraints
    │
    ▼
[Gemini generateContent API]
    │  tools: [file_search with store reference]
    │  Gemini internally:
    │    ├── Embed query with gemini-embedding-001
    │    ├── Vector search against File Search store
    │    ├── Retrieve top-k relevant chunks
    │    └── Synthesize response with citations
    │
    ▼
[Response Formatter]
    │  Map Gemini file references → human-readable source names
    │  (using metadata from SQLite state DB)
    │  Format citations, highlight key passages
    │
    ▼
[CLI Output]
    Display answer + attributed sources
```

### State Management Flow

```
[SQLite State DB (WAL Mode)]
    │
    ├── files table
    │   file_path (PK) | content_hash | mtime | scan_status | upload_status
    │   hierarchy_metadata (JSON) | gemini_file_id | gemini_store_name
    │   error_message | last_scanned | last_uploaded
    │
    ├── upload_batches table
    │   batch_id (PK) | file_count | completed_count | failed_count
    │   status | started_at | completed_at
    │
    └── stores table
        store_name (PK) | store_id | display_name | file_count
        created_at | last_synced
```

### Key Data Flows

1. **Scan flow:** File system -> Scanner -> SQLite (record inventory + metadata). No API calls. Fast, local-only.
2. **Upload flow:** SQLite (read pending) -> Rate Limiter -> Gemini API -> SQLite (update status). API-bound, async, resumable.
3. **Query flow:** User input -> Filter Builder -> Gemini generateContent (with file_search tool) -> Response Formatter -> CLI output. Interactive, low-latency.
4. **Resume flow:** On restart, read SQLite state. Files marked 'pending' or 'failed' are candidates for upload. Files marked 'uploaded' are skipped. No duplicate uploads.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Small library (<100 files, <1GB) | Single File Search store. Sequential uploads. No batching needed. Simple CLI. |
| Medium library (100-1000 files, 1-10GB) | Batched async uploads. Rate limiting becomes important. Multiple stores possible for organization. WAL mode for concurrent scan+query. |
| Large library (1000+ files, 10-100GB) | Multiple File Search stores by category. Parallel upload workers. Progress reporting. Possible tier upgrade. Checkpoint-based resume critical. |

### Scaling Priorities

1. **First bottleneck: Upload throughput.** Gemini File Search uploads are async and involve server-side indexing. With rate limits and per-file processing time, uploading 1000 files can take hours. Batch wisely, parallelize within rate limits, and ensure resume works perfectly.
2. **Second bottleneck: File Search store size.** Gemini recommends keeping stores under 20GB for optimal retrieval latency. For large libraries, partition into multiple stores by logical category (author, work type, time period) and select the appropriate store at query time.

## Anti-Patterns

### Anti-Pattern 1: Building Custom Chunking/Embedding When Using Gemini File Search

**What people do:** Implement local chunking with LangChain, generate embeddings via a separate API, store in a local vector DB, then also upload to Gemini.
**Why it's wrong:** Gemini File Search handles chunking, embedding, and indexing internally. Doing it yourself duplicates work, introduces inconsistency between local and remote representations, and adds maintenance burden.
**Do this instead:** Upload whole files to Gemini File Search. Configure `chunking_config` if you need control over chunk size/overlap. Trust Gemini's internal pipeline.

### Anti-Pattern 2: Stateless Pipeline (No SQLite Tracking)

**What people do:** Scan the file system and upload everything on every run. "It's simpler."
**Why it's wrong:** Re-uploading unchanged files wastes API quota, costs money, and takes hours for large libraries. No way to know what succeeded or failed. No resume capability.
**Do this instead:** Track every file's hash and upload status in SQLite. Only process new or changed files. Mark failures for retry. This is the core value of the state layer.

### Anti-Pattern 3: Synchronous Sequential Uploads Without Rate Limiting

**What people do:** Upload files one at a time in a for-loop with `time.sleep(1)` between calls.
**Why it's wrong:** Either too slow (conservative sleep) or will hit rate limits (aggressive sleep). No backoff on errors. Cannot recover from partial failures gracefully.
**Do this instead:** Use `asyncio` with semaphore-based concurrency control. Implement exponential backoff with jitter via `tenacity`. Batch uploads within rate limit windows. Track each upload's status independently.

### Anti-Pattern 4: One Giant File Search Store

**What people do:** Upload every file in the library to a single store.
**Why it's wrong:** Gemini recommends <20GB per store for optimal latency. A single store prevents targeted filtering (searching only Rand's novels vs. all 500 files). Retrieval quality degrades as corpus grows without filtering.
**Do this instead:** Organize stores by logical category. At query time, select the relevant store(s) based on user filters. This improves both latency and retrieval relevance.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Gemini File Search API | REST via `google-genai` SDK. Upload files, poll for completion, query with `file_search` tool. | Async indexing: poll `operation.done`. Files persist until deleted. 100MB per-file limit. Stores: 1GB free / 10GB tier 1 / 100GB tier 2 / 1TB tier 3. |
| Gemini generateContent API | REST via `google-genai` SDK. Pass query + file_search tool config. Returns synthesized answer with citations. | Context window management is handled by Gemini internally. Map returned file references to human-readable names via SQLite metadata. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Scanner <-> State DB | Direct SQLite calls via state module | Scanner writes file records; never calls any API |
| Uploader <-> State DB | Direct SQLite calls via state module | Reads pending files, writes upload results. Transactions ensure atomicity. |
| Uploader <-> Gemini API | Async HTTP via `google-genai` SDK | Rate limiter sits between uploader and API. All API calls go through rate limiter. |
| Query <-> State DB | Read-only SQLite queries | Reads metadata for display names, source attribution. WAL mode allows concurrent reads during uploads. |
| Query <-> Gemini API | Sync HTTP via `google-genai` SDK | Query-time calls are interactive and low-latency. Different rate limit profile than batch uploads. |

## Build Order (Dependency Chain)

The three phases have a natural dependency order that dictates build sequence:

```
Phase 1: Scanner + State DB
    │  (no API dependency -- can build and test offline)
    │
    ▼
Phase 2: Upload Pipeline + Rate Limiter
    │  (depends on State DB schema from Phase 1)
    │  (requires API key for testing)
    │
    ▼
Phase 3: Query Interface + Synthesis
    │  (depends on uploaded data from Phase 2)
    │  (requires populated File Search store)
```

**Build order rationale:**
1. **State DB + Scanner first** because they have zero external dependencies. You can build, test, and validate the entire file inventory and metadata extraction against the real library without an API key. This de-risks the project -- if the metadata extraction is wrong, you find out before spending API quota.
2. **Upload Pipeline second** because it depends on the state schema and file inventory from Phase 1. Test with a small subset of files first. Get rate limiting and resume working correctly before processing the full library.
3. **Query Interface last** because it requires populated File Search stores from Phase 2. Building it earlier means testing against empty or stub data, which is less useful for a search system where retrieval quality is the primary concern.

## State Management Approach

### Why SQLite (not Postgres, not JSON files, not Redis)

- **Zero infrastructure:** SQLite is a file. No server process, no configuration, no network. Matches the CLI-tool nature of this project.
- **ACID transactions:** Atomic state transitions (pending -> uploading -> uploaded) prevent corruption on crash.
- **WAL mode:** Enables concurrent reads during writes. Scanner can query state while uploader writes. Query interface can read while uploads proceed.
- **Query capability:** SQL allows flexible state queries (all failed uploads, all files in a category, upload progress stats).
- **Python built-in:** `sqlite3` is in the standard library. No pip install needed for the core state layer.

### SQLite Configuration

```python
import sqlite3

def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")       # Concurrent reads during writes
    conn.execute("PRAGMA synchronous=NORMAL")      # Good durability without FULL overhead
    conn.execute("PRAGMA foreign_keys=ON")         # Enforce referential integrity
    conn.execute("PRAGMA busy_timeout=5000")       # Wait up to 5s on lock contention
    conn.row_factory = sqlite3.Row                 # Dict-like row access
    return conn
```

### Error Handling and Retry Strategy

| Error Type | Detection | Response | State Transition |
|------------|-----------|----------|------------------|
| File not found | `FileNotFoundError` during scan | Log warning, skip file, mark 'missing' in DB | `pending` -> `missing` |
| File parse error | Exception during metadata extraction | Log error with details, mark 'parse_error' | `pending` -> `parse_error` |
| API rate limit (429) | HTTP 429 response | Exponential backoff with jitter, respect `Retry-After` header | Stays `uploading` |
| API transient error (5xx) | HTTP 500-599 | Retry up to 5 times with exponential backoff | Stays `uploading`, then `failed` |
| API permanent error (4xx) | HTTP 400-499 (not 429) | Log error, do not retry, mark failed | `uploading` -> `failed` |
| Upload timeout | Polling exceeds max wait time | Mark as `timeout`, retry on next run | `uploading` -> `timeout` |
| Process interrupted (SIGINT) | Signal handler or KeyboardInterrupt | Commit current transaction, exit cleanly | Current file stays `uploading`, retried on restart |
| Network failure | `ConnectionError`, `Timeout` | Retry with backoff, then mark failed | Stays `uploading`, then `failed` |

## Sources

- Gemini File Search official documentation: https://ai.google.dev/gemini-api/docs/file-search (HIGH confidence)
- Databricks RAG chunking strategies guide: https://community.databricks.com/t5/technical-blog/the-ultimate-guide-to-chunking-strategies-for-rag-applications/ba-p/113089 (HIGH confidence)
- Databricks RAG data foundation guide: https://community.databricks.com/t5/technical-blog/six-steps-to-improve-your-rag-application-s-data-foundation/ba-p/97700 (HIGH confidence)
- Microsoft RAG architecture overview: https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview (HIGH confidence)
- OpenAI rate limiting cookbook: https://developers.openai.com/cookbook/examples/how_to_handle_rate_limits/ (HIGH confidence)
- SQLite WAL mode documentation: https://sqlite.org/wal.html (HIGH confidence)
- LlamaIndex ingestion pipeline docs: https://developers.llamaindex.ai/python/framework/module_guides/loading/ingestion_pipeline/ (HIGH confidence)
- Pinecone metadata filtering: https://docs.pinecone.io/guides/search/filter-by-metadata (MEDIUM confidence)
- Databricks vector search best practices: https://docs.databricks.com/aws/en/vector-search/vector-search-best-practices (MEDIUM confidence)

---
*Architecture research for: Objectivism Library Semantic Search*
*Researched: 2026-02-15*
