# Client Interface

This document defines the **public interface** of the objlib system — what external clients (the TUI and future integrations) may import and depend on, and what is internal and must not be accessed directly.

The guiding principle: **clients are consumers of the system, not participants in its implementation.** Access the system through the documented service layer, the same way an external application would.

---

## The Boundary Rule

```
┌──────────────────────────────────────────────────────────┐
│  CLIENT (TUI, scripts, future integrations)              │
│                                                          │
│  ✅ May import from:                                     │
│     objlib.services.*     ← service layer               │
│     objlib.models         ← core dataclasses             │
│     objlib.search.models  ← Pydantic result types        │
│                                                          │
│  ❌ Must never import from:                              │
│     objlib.cli            ← CLI command definitions      │
│     objlib.upload.*       ← Gemini upload pipeline       │
│     objlib.extraction.*   ← Mistral batch extraction     │
│     objlib.entities.*     ← entity extraction pipeline   │
│     objlib.sync.*         ← incremental sync pipeline    │
│     objlib.database       ← raw SQLite access            │
│     objlib.scanner        ← file scanner                 │
└──────────────────────────────────────────────────────────┘
```

The `objlib.services` module is the **only supported entrypoint** for client code. It wraps all underlying pipeline modules with clean, stable, async-friendly interfaces.

---

## Public Data Types

These types cross the service boundary and are safe to use in client code.

### From `objlib.models`

| Type | Fields | Purpose |
|------|--------|---------|
| `Citation` | `index`, `title`, `uri`, `text`, `document_name`, `confidence`, `file_path`, `metadata` | A single search result with passage text and source attribution |
| `FileRecord` | `file_path`, `content_hash`, `filename`, `file_size`, `metadata`, `status` | Metadata record for a library file |
| `AppState` | `gemini_client`, `store_resource_name`, `db_path`, `terminal_width` | Initialized application context |
| `FileStatus` | enum: `pending`, `uploaded`, `missing`, `error`, … | Upload/sync state of a file |
| `MetadataQuality` | enum: `complete`, `partial`, `minimal`, `none`, `unknown` | Confidence in extracted metadata |

### From `objlib.search.models`

| Type | Fields | Purpose |
|------|--------|---------|
| `RankedResult` | `index`, `score` | Reranker score for a citation |
| `SynthesisClaim` | `claim`, `quote`, `citation_index` | A single validated claim from synthesis |
| `SynthesisOutput` | `summary`, `claims`, `citations` | Full synthesis response |

---

## Service Layer

Implemented in `src/objlib/services/`. Each service wraps one or more internal pipeline modules.

### `SearchService`

Wraps: `search/client.py`, `search/citations.py`, `search/reranker.py`, `search/synthesizer.py`, `search/expansion.py`

```python
class SearchService:
    def __init__(
        self,
        api_key: str,
        store_resource_name: str,
        db_path: str = "data/library.db",
    ) -> None: ...

    async def search(
        self,
        query: str,
        filters: list[str] = [],
        limit: int = 10,
        mode: str = "learn",
        expand: bool = True,
        rerank: bool = True,
    ) -> list[Citation]:
        """Semantic search. Applies query expansion, calls Gemini File Search,
        enriches citations from SQLite, and reranks. 300ms–2s latency."""

    async def synthesize(
        self,
        query: str,
        citations: list[Citation],
    ) -> SynthesisOutput | None:
        """Multi-document synthesis with MMR diversity and citation validation.
        Returns None if fewer than 5 citations or if synthesis fails."""
```

**Key constraint:** `search()` and `synthesize()` are async. Always await them or dispatch to a background worker — never call blocking from a TUI main thread. The Gemini client is created lazily on first call (`_ensure_client()`), so constructing `SearchService` is cheap.

---

### `LibraryService`

Wraps: `database.py` (read-only query methods)

```python
class LibraryService:
    def __init__(self, db_path: str = "data/library.db") -> None: ...

    async def get_categories(self) -> list[tuple[str, int]]:
        """Returns [(category_name, count), ...]. No disk access."""

    async def get_courses(self) -> list[tuple[str, int]]:
        """Returns [(course_name, count), ...]. No disk access."""

    async def get_files_by_course(
        self, course: str, limit: int = 200
    ) -> list[dict]:
        """Files in a course with metadata. No disk access."""

    async def get_items_by_category(self, category: str) -> list[dict]:
        """Files in a category. No disk access."""

    async def filter_files(
        self, filters: list[str], limit: int = 50
    ) -> list[dict]:
        """Filter by metadata fields. Supports field:value, field:>=value, etc."""

    async def get_file_content(self, file_path: str) -> str | None:
        """Read full document text from disk. Returns None if disk unavailable."""

    async def get_file_count(self) -> int:
        """Total number of files in the database."""
```

**Key constraint:** All methods are async (run database queries in a thread pool via `asyncio.to_thread`). All except `get_file_content()` are disk-independent. `get_file_content()` requires the library volume to be mounted.

---

### `SessionService`

Wraps: `session/manager.py`

```python
class SessionService:
    def __init__(self, db_path: str = "data/library.db") -> None: ...

    async def create_session(self, name: str | None = None) -> str:
        """Creates a new session. Returns UUID."""

    async def add_event(
        self,
        session_id: str,
        event_type: Literal["search", "view", "synthesize", "note", "error", "bookmark"],
        payload: dict,
    ) -> str:
        """Append-only. No update or delete methods exist. Returns event ID."""

    async def list_sessions(self) -> list[dict]:
        """All sessions with event counts."""

    async def get_session(self, session_id: str) -> dict | None:
        """Fetch by exact UUID. Returns None if not found."""

    async def get_events(self, session_id: str) -> list[dict]:
        """All events for a session in chronological order."""
```

**Key constraint:** Events are append-only. There are no update or delete methods — this is by design for research session integrity. The `bookmark` event type (added in schema V8) records TUI bookmark actions.

---

## Dependency Injection Pattern

Services are constructed at startup with path arguments — no explicit database connection needed:

```python
from objlib.services import SearchService, LibraryService, SessionService

api_key = keyring.get_password("objlib-gemini", "api_key")
db_path = "data/library.db"
store_name = "objectivism-library-test"

search_service  = SearchService(api_key=api_key, store_resource_name=store_name, db_path=db_path)
library_service = LibraryService(db_path=db_path)
session_service = SessionService(db_path=db_path)
```

Services are not singletons — construct them once at startup and pass them to the TUI or other client.

**TUI:** `run_tui()` in `src/objlib/tui/__init__.py` handles this setup automatically, including Gemini store name resolution via `GeminiSearchClient.resolve_store_name()` and file logging via `configure_file_logging()`.

---

## What Clients Must Not Do

| Pattern | Why prohibited |
|---------|---------------|
| `from objlib.cli import app` | CLI is Typer wiring, not a service API |
| `from objlib.upload import ...` | Upload pipeline is operational, not a query interface |
| `from objlib.extraction import ...` | Mistral batch extraction is a background pipeline |
| `from objlib.sync import SyncOrchestrator` | Sync is triggered by user via CLI, not embedded in clients |
| `sqlite3.connect("data/library.db")` | Use services with db_path; never open raw connections |
| Calling Gemini API directly | Always go through `SearchService`; it handles retries, circuit breaking, citation enrichment |
| Writing to `session_events` directly | Always use `SessionService.add_event()` to preserve append-only semantics |

---

## Async Contract

All service methods are async. They run blocking SQLite/disk operations in a thread pool via `asyncio.to_thread`.

| Method | Notes |
|--------|-------|
| `SearchService.search()` | 300ms–2s; always run in `@work` / background worker |
| `SearchService.synthesize()` | Up to 5s; always background |
| `LibraryService.*` (except `get_file_content`) | Fast DB reads; safe to await directly in handlers |
| `LibraryService.get_file_content()` | Disk I/O; run in worker if latency matters |
| `SessionService.*` | Fast SQLite writes; safe to await directly |

In Textual: use `@work(exclusive=True)` for search/synthesize; other service calls can be awaited directly from `async def on_*` handlers.

---

## Versioning This Interface

This interface is versioned informally at **v1**, matching the project milestone. Breaking changes to the service layer API require:

1. A version bump in `Canon.json` → `previousVersions`
2. An updated section in this document
3. A migration note in `CHANGELOG.md`

---

_Last updated: Phase 7 — actual service implementations (SearchService, LibraryService, SessionService), bookmark event type, TUI DI pattern_
