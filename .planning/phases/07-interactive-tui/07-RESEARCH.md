# Phase 7: Interactive TUI - Research

**Researched:** 2026-02-18
**Domain:** Python TUI application with Textual framework, services facade layer, async integration
**Confidence:** HIGH (core framework patterns verified via Context7 + official docs)

## Summary

Phase 7 transforms the existing CLI into an interactive terminal application using **Textual** (v5.3.0, latest stable). The architecture has three layers: (1) a `src/objlib/services/` facade that wraps existing internal modules into clean `SearchService`, `LibraryService`, and `SessionService` classes per the Canon.json contract, (2) a centralized `AppState` using Textual's `Reactive` properties for uni-directional data flow, and (3) widget-based panes (navigation tree, results list, document preview) composed in a three-pane layout using Textual's CSS grid system with inline `CSS` class variable (no `.tcss` files).

The critical integration point is async: `SearchService.search()` wraps the existing synchronous `GeminiSearchClient.query_with_retry()` with `asyncio.to_thread()` so the TUI can call it via `@work(exclusive=True)` workers. The `exclusive=True` flag provides automatic cancellation of stale searches -- when a new keystroke triggers a search, Textual cancels the previous worker, eliminating race conditions without manual UUID tracking. SQLite operations via `LibraryService` and `SessionService` also use `asyncio.to_thread()` since the `Database` context manager holds a synchronous `sqlite3.Connection`.

**Primary recommendation:** Build the services facade first (it is testable without Textual), then the Textual App shell with state management, then individual pane widgets, then inter-pane wiring. This dependency chain is strict -- widgets cannot be built without services, and wiring cannot be tested without widgets.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
1. **TUI Framework: Textual** -- asyncio-native, built by Rich author, CSS grid layout, Tree/Input widgets, renders Rich renderables natively. Existing `objlib tui` entry point calls `TextualApp.run()`. Prefer inline layout (no separate .css files).
2. **Async/Event-Loop Integration:** SearchService calls use `@work(exclusive=True)` Textual worker. LibraryService/SessionService wrap with `asyncio.to_thread()` for disk-touching calls. Import only from `objlib.services` (Canon.json rule #1).
3. **Centralized State Management:** `AppState` dataclass with Textual `Reactive` properties. Widgets post `Message` subclasses to App; App updates AppState; reactive re-renders. No widget-to-widget direct calls.
4. **Live Search Debounce:** 300ms + `exclusive=True` worker (auto-cancellation of stale searches).
5. **Session Scope:** Data-only (queries, filters, bookmarks; no widget state persistence).
6. **Search Hit Location:** Text-search fallback for citation jump (find Citation.text excerpt in loaded document).
7. **Responsive Layout:** Three breakpoints (140+ cols = 3-pane, 80-139 = 2-pane, <80 = single-pane stacked).
8. **Command Palette:** Ctrl+P with fuzzy search for TUI-08 (all CLI functionality accessible).

### Claude's Discretion
- Specific widget hierarchy and composition within each pane
- Internal service method signatures beyond what Canon.json prescribes
- Error display patterns (toast notifications vs. inline error panels)
- Keyboard shortcut mappings beyond Tab/Ctrl+P
- Loading/spinner UX patterns

### Deferred Ideas (OUT OF SCOPE)
- (None explicitly deferred in CONTEXT.md)
</user_constraints>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| textual | 5.3.0 | TUI framework -- App, Screen, Widget, Reactive, workers, CSS layout | Asyncio-native, Rich-compatible, CSS grid, built-in Tree/Input/DataTable widgets |
| rich | >=13.0 | Already in project -- Rich renderables displayed natively in Textual's `RichLog` and `Static.update()` | Textual renders any Rich renderable directly; existing `formatter.py` output reusable |
| asyncio | stdlib | Event loop integration for `to_thread()` wrapping sync services | Standard library; Textual runs on asyncio natively |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pyyaml | already dep | Glossary loading for query expansion in SearchService | Already imported by expansion.py |
| keyring | >=25.0 | API key retrieval for service initialization | Already in project dependencies |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Textual | urwid | More manual; no asyncio integration; no CSS layout; no Rich rendering |
| Textual | prompt_toolkit | Widget system is weaker; designed for prompts not full apps |
| RichLog for preview | MarkdownViewer | Would need markdown conversion; RichLog accepts any Rich renderable directly |

**Installation:**
```bash
pip install "textual>=5.0"
```

Add to `pyproject.toml` dependencies:
```toml
"textual>=5.0",
```

## Architecture Patterns

### Recommended Project Structure
```
src/objlib/
├── services/           # NEW: Public API facade (Canon.json contract)
│   ├── __init__.py     # Re-exports SearchService, LibraryService, SessionService
│   ├── search.py       # SearchService (wraps search/client.py + citations.py + reranker.py + expansion.py)
│   ├── library.py      # LibraryService (wraps database.py browse/filter/view methods)
│   └── session.py      # SessionService (wraps session/manager.py)
├── tui/                # NEW: Textual application
│   ├── __init__.py     # Entry point: ObjlibApp class
│   ├── app.py          # App subclass with CSS, compose(), state, message handlers
│   ├── state.py        # AppState dataclass with Reactive properties
│   ├── messages.py     # Custom Message subclasses for inter-widget communication
│   ├── widgets/        # Pane widgets
│   │   ├── __init__.py
│   │   ├── nav_tree.py     # Navigation tree (categories -> courses -> files)
│   │   ├── search_bar.py   # Input with debounce logic
│   │   ├── results.py      # Results list/DataTable
│   │   ├── preview.py      # Document preview (RichLog-based)
│   │   └── filter_panel.py # Interactive filter checkboxes/sliders
│   └── providers.py    # CommandPalette providers for Ctrl+P
├── search/             # EXISTING (internal, excluded from Canon imports)
├── session/            # EXISTING (internal, excluded from Canon imports)
├── database.py         # EXISTING (internal, used by services/)
└── models.py           # EXISTING (Citation, AppState, FileRecord)
```

### Pattern 1: Services Facade (Canon.json Contract)

**What:** Thin wrapper classes that expose a clean async API over existing synchronous internals. The TUI imports ONLY from `objlib.services`.

**When to use:** Always. Canon.json rule #1 mandates this boundary.

**Key insight:** The existing `GeminiSearchClient` is synchronous (uses `google.genai` sync API). `SearchService.search()` must wrap this with `asyncio.to_thread()` to make it awaitable for Textual workers.

**Example:**
```python
# src/objlib/services/search.py
import asyncio
from objlib.search.client import GeminiSearchClient
from objlib.search.citations import extract_citations, enrich_citations, build_metadata_filter
from objlib.search.reranker import rerank_passages, apply_difficulty_ordering
from objlib.search.expansion import expand_query
from objlib.search.synthesizer import synthesize_answer, apply_mmr_diversity
from objlib.database import Database
from objlib.models import Citation, SearchResult

class SearchService:
    """Async facade over Gemini File Search pipeline.

    Canon.json rule: SearchService.search() is async with 300ms-2s latency.
    """

    def __init__(self, api_key: str, store_resource_name: str, db_path: str):
        from google import genai
        self._client = genai.Client(api_key=api_key)
        self._search_client = GeminiSearchClient(self._client, store_resource_name)
        self._db_path = db_path

    async def search(
        self,
        query: str,
        filters: list[str] | None = None,
        expand: bool = True,
        rerank: bool = True,
        mode: str = "learn",
    ) -> SearchResult:
        """Full search pipeline: expand -> query -> extract -> enrich -> rerank.

        Runs synchronous Gemini API call in a thread to avoid blocking
        the Textual event loop.
        """
        # Query expansion (fast, CPU-only)
        search_query = query
        if expand:
            search_query, _ = expand_query(query)

        metadata_filter = build_metadata_filter(filters) if filters else None

        # Heavy I/O: run in thread
        response = await asyncio.to_thread(
            self._search_client.query_with_retry,
            search_query,
            metadata_filter=metadata_filter,
        )

        grounding = None
        if response.candidates:
            grounding = response.candidates[0].grounding_metadata
        citations = extract_citations(grounding)

        # Enrich from SQLite (short-lived connection per Canon rule #6)
        def _enrich(cites):
            with Database(self._db_path) as db:
                enrich_citations(cites, db)
            return cites

        citations = await asyncio.to_thread(_enrich, citations)

        # Rerank (another Gemini call)
        if rerank and len(citations) > 1:
            citations = await asyncio.to_thread(
                rerank_passages, self._client, query, citations
            )

        citations = apply_difficulty_ordering(citations, mode=mode)

        return SearchResult(
            response_text=response.text or "",
            citations=citations,
            query=query,
            metadata_filter=metadata_filter,
        )
```

```python
# src/objlib/services/library.py
import asyncio
from objlib.database import Database

class LibraryService:
    """Facade for browse/filter/view operations (no Gemini API needed).

    Canon.json rule #8: use LibraryService for browse/filter (no Gemini call).
    Canon.json rule #6: Database as context manager, never hold across await.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path

    async def get_categories(self) -> list[tuple[str, int]]:
        def _query():
            with Database(self._db_path) as db:
                return db.get_categories_with_counts()
        return await asyncio.to_thread(_query)

    async def get_courses(self) -> list[tuple[str, int]]:
        def _query():
            with Database(self._db_path) as db:
                return db.get_courses_with_counts()
        return await asyncio.to_thread(_query)

    async def get_files_by_course(self, course: str, year: str | None = None) -> list[dict]:
        def _query():
            with Database(self._db_path) as db:
                return db.get_files_by_course(course, year=year)
        return await asyncio.to_thread(_query)

    async def get_items_by_category(self, category: str) -> list[dict]:
        def _query():
            with Database(self._db_path) as db:
                return db.get_items_by_category(category)
        return await asyncio.to_thread(_query)

    async def filter_files(self, filters: dict[str, str], limit: int = 50) -> list[dict]:
        def _query():
            with Database(self._db_path) as db:
                return db.filter_files_by_metadata(filters, limit=limit)
        return await asyncio.to_thread(_query)

    async def enrich_citations(self, citations, db_instance=None):
        """Canon.json rule #4: always call after search."""
        from objlib.search.citations import enrich_citations
        def _enrich():
            with Database(self._db_path) as db:
                enrich_citations(citations, db)
            return citations
        return await asyncio.to_thread(_enrich)

    async def get_file_content(self, file_path: str) -> str | None:
        """Load document text for preview pane (text-search fallback for citation jump)."""
        def _read():
            try:
                with open(file_path, encoding="utf-8") as f:
                    return f.read()
            except (FileNotFoundError, PermissionError):
                return None
        return await asyncio.to_thread(_read)
```

```python
# src/objlib/services/session.py
import asyncio
from objlib.database import Database
from objlib.session.manager import SessionManager

class SessionService:
    """Facade for session management (append-only events).

    Canon.json rule #10: append-only, use add_event() only.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path

    async def create_session(self, name: str | None = None) -> str:
        def _create():
            with Database(self._db_path) as db:
                mgr = SessionManager(db.conn)
                return mgr.create(name)
        return await asyncio.to_thread(_create)

    async def add_event(self, session_id: str, event_type: str, payload: dict) -> str:
        def _add():
            with Database(self._db_path) as db:
                mgr = SessionManager(db.conn)
                return mgr.add_event(session_id, event_type, payload)
        return await asyncio.to_thread(_add)

    async def list_sessions(self) -> list[dict]:
        def _list():
            with Database(self._db_path) as db:
                mgr = SessionManager(db.conn)
                return mgr.list_sessions()
        return await asyncio.to_thread(_list)

    async def get_events(self, session_id: str) -> list[dict]:
        def _get():
            with Database(self._db_path) as db:
                mgr = SessionManager(db.conn)
                return mgr.get_events(session_id)
        return await asyncio.to_thread(_get)
```

```python
# src/objlib/services/__init__.py
from objlib.services.search import SearchService
from objlib.services.library import LibraryService
from objlib.services.session import SessionService

__all__ = ["SearchService", "LibraryService", "SessionService"]
```

### Pattern 2: Centralized AppState with Textual Reactive Properties

**What:** Single `AppState` lives on the App subclass. Widgets read from it; mutations flow through the App. Textual's `reactive` descriptor triggers `watch_*` methods automatically when values change.

**When to use:** For ALL cross-pane state (query, results, selected item, filters, session).

**Example:**
```python
# src/objlib/tui/state.py
from dataclasses import dataclass, field

@dataclass
class FilterSet:
    """Active metadata filters."""
    category: str | None = None
    course: str | None = None
    difficulty: str | None = None
    year_min: int | None = None
    year_max: int | None = None

@dataclass
class Bookmark:
    """A bookmarked file."""
    file_path: str
    filename: str
    note: str = ""
```

```python
# src/objlib/tui/app.py
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Input, Static
from objlib.services import SearchService, LibraryService, SessionService

class ObjlibApp(App):
    """Interactive TUI for the Objectivism Library."""

    CSS = """
    #main-container {
        layout: horizontal;
        height: 1fr;
    }
    #nav-pane {
        width: 20%;
        min-width: 20;
        border-right: solid $primary;
    }
    #results-pane {
        width: 33%;
        min-width: 30;
    }
    #preview-pane {
        width: 47%;
        min-width: 40;
    }
    /* Medium layout: hide nav, expand results */
    .layout-medium #nav-pane {
        display: none;
    }
    .layout-medium #results-pane {
        width: 45%;
    }
    .layout-medium #preview-pane {
        width: 55%;
    }
    /* Narrow layout: stack everything */
    .layout-narrow #main-container {
        layout: vertical;
    }
    .layout-narrow #nav-pane,
    .layout-narrow #results-pane,
    .layout-narrow #preview-pane {
        width: 100%;
        height: 1fr;
    }
    """

    BINDINGS = [
        ("ctrl+p", "command_palette", "Commands"),
        ("ctrl+f", "focus_search", "Search"),
        ("tab", "focus_next", "Next Pane"),
        ("shift+tab", "focus_previous", "Previous Pane"),
        ("ctrl+b", "toggle_nav", "Toggle Nav"),
    ]

    # Reactive state -- watchers auto-fire on change
    query = reactive("")
    results = reactive(list, recompose=False)
    selected_index = reactive(None)
    search_history = reactive(list)
    active_session_id = reactive(None)

    def __init__(self, search_service, library_service, session_service):
        super().__init__()
        self.search_service = search_service
        self.library_service = library_service
        self.session_service = session_service
```

### Pattern 3: @work(exclusive=True) for Search with Auto-Cancellation

**What:** The `@work(exclusive=True)` decorator creates a Textual worker that automatically cancels any previously-running worker with the same group name when invoked again. This eliminates stale result race conditions.

**When to use:** For SearchService.search() calls triggered by keystroke debounce.

**Verified behavior (Context7, HIGH confidence):**
- Decorated `async def` methods become callable without `await` -- the decorator handles worker creation
- `exclusive=True` cancels the previous worker before starting a new one
- Worker results are available via `on_worker_state_changed` event or the `Worker.result` attribute
- Worker errors surface via `WorkerState.FAILED` with `event.worker.error`

**Example:**
```python
# In app.py
from textual import work
from textual.worker import Worker, WorkerState

class ObjlibApp(App):

    @work(exclusive=True)
    async def _run_search(self, query: str) -> None:
        """Execute search in background worker. Exclusive=True cancels stale searches."""
        self.query_one("#results-status", Static).update("Searching...")

        try:
            result = await self.search_service.search(query)
            # Update reactive state -- triggers watch_results
            self.results = result.citations
            self.query_one("#results-status", Static).update(
                f"{len(result.citations)} results"
            )
        except Exception as e:
            self.query_one("#results-status", Static).update(f"Error: {e}")

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker completion/failure."""
        if event.state == WorkerState.SUCCESS:
            pass  # Results already set in _run_search
        elif event.state == WorkerState.FAILED:
            self.notify(f"Search failed: {event.worker.error}", severity="error")
```

### Pattern 4: Input Debounce (300ms + exclusive worker)

**What:** Textual's `Input.Changed` message fires on every keystroke. Use `set_timer` for debounce, then fire the exclusive worker.

**Example:**
```python
from textual.widgets import Input
from textual.timer import Timer

class ObjlibApp(App):
    _search_timer: Timer | None = None

    def on_input_changed(self, event: Input.Changed) -> None:
        """Debounce search input: wait 300ms after last keystroke."""
        if event.input.id == "search-input":
            # Cancel previous timer
            if self._search_timer is not None:
                self._search_timer.stop()
            # Set new 300ms timer
            self._search_timer = self.set_timer(
                0.3, lambda: self._run_search(event.value)
            )
```

### Pattern 5: Custom Messages for Widget-to-App Communication

**What:** Widgets define nested `Message` subclasses and `post_message()` them upward. The App handles them via `on_<widget>_<message>` naming convention.

**Verified (Context7, HIGH confidence):**
```python
from textual.message import Message
from textual.widgets import Static

class ResultItem(Static):
    """A single search result in the results list."""

    class Selected(Message):
        """Fired when user selects this result."""
        def __init__(self, index: int, citation) -> None:
            self.index = index
            self.citation = citation
            super().__init__()

    def on_click(self) -> None:
        self.post_message(self.Selected(self.index, self.citation))

# In App:
class ObjlibApp(App):
    def on_result_item_selected(self, message: ResultItem.Selected) -> None:
        """User selected a search result -- update preview pane."""
        self.selected_index = message.index
        self._load_preview(message.citation)
```

### Pattern 6: Tree Widget for Navigation

**What:** Textual's built-in `Tree` widget provides expandable/collapsible nodes with keyboard navigation (up/down/enter/space). Nodes can carry arbitrary `data` attributes.

**Verified (Context7, HIGH confidence):**
```python
from textual.widgets import Tree

class NavTree(Tree):
    """Library navigation: categories -> courses -> files."""

    def __init__(self):
        super().__init__("Library", id="nav-tree")

    async def populate(self, library_service):
        """Build tree from LibraryService data."""
        self.clear()
        categories = await library_service.get_categories()

        for cat_name, count in categories:
            cat_node = self.root.add(
                f"{cat_name} ({count})",
                data={"type": "category", "name": cat_name},
            )
            if cat_name == "course":
                courses = await library_service.get_courses()
                for course_name, course_count in courses:
                    cat_node.add(
                        f"{course_name} ({course_count})",
                        data={"type": "course", "name": course_name},
                    )
```

**Built-in keyboard bindings (verified):**
| Key | Action |
|-----|--------|
| `enter` | Select current item |
| `space` | Toggle expand/collapse |
| `up` / `down` | Move cursor |
| `shift+left` | Cursor to parent |
| `shift+space` | Expand/collapse all |

### Pattern 7: RichLog for Document Preview

**What:** `RichLog` widget accepts any Rich renderable via `.write()`, supports scrolling, and auto-scrolls to bottom on new content. Use `.clear()` before writing new document content.

**Verified (Context7, HIGH confidence):**
```python
from textual.widgets import RichLog
from rich.syntax import Syntax
from rich.text import Text

class PreviewPane(RichLog):
    """Document preview with search term highlighting."""

    def show_document(self, content: str, highlight_terms: list[str] | None = None):
        self.clear()

        if highlight_terms:
            text = Text(content)
            for term in highlight_terms:
                text.highlight_words([term], style="bold yellow on dark_green")
            self.write(text)
        else:
            self.write(content)

    def scroll_to_citation(self, citation_text: str, content: str):
        """Text-search fallback: find citation excerpt and scroll to it."""
        # Find the position of the citation text in the document
        pos = content.lower().find(citation_text.lower()[:100])
        if pos >= 0:
            # Estimate line number from character position
            line_number = content[:pos].count('\n')
            self.scroll_to(y=line_number, animate=True)
```

### Pattern 8: Inline CSS (No .tcss Files)

**What:** Use the `CSS` class variable on App or Widget subclasses. This is the standard approach when you want self-contained widgets without external files.

**Verified (Context7, HIGH confidence):**
```python
class ObjlibApp(App):
    CSS = """
    Screen {
        layout: horizontal;
    }
    #search-input {
        dock: top;
        height: 3;
        border-bottom: solid $primary;
    }
    """
    # NOT: CSS_PATH = "style.tcss"  -- we use inline CSS per user decision
```

Widgets can also have their own `DEFAULT_CSS`:
```python
class NavTree(Tree):
    DEFAULT_CSS = """
    NavTree {
        width: 100%;
        height: 1fr;
        background: $surface;
    }
    """
```

### Pattern 9: Responsive Layout with on_resize

**What:** Detect terminal width changes and apply CSS classes to switch layout modes.

**Example:**
```python
from textual import events

class ObjlibApp(App):
    WIDE_THRESHOLD = 140
    MEDIUM_THRESHOLD = 80

    def on_resize(self, event: events.Resize) -> None:
        """Switch layout mode based on terminal width."""
        width = event.size.width
        self.remove_class("layout-wide", "layout-medium", "layout-narrow")
        if width >= self.WIDE_THRESHOLD:
            self.add_class("layout-wide")
        elif width >= self.MEDIUM_THRESHOLD:
            self.add_class("layout-medium")
        else:
            self.add_class("layout-narrow")
```

### Pattern 10: CommandPalette with Custom Providers

**What:** Textual's built-in `CommandPalette` (Ctrl+P) accepts custom `Provider` subclasses that yield `Hit` objects with fuzzy-matched commands.

**Verified (Context7, HIGH confidence):**
```python
from textual.command import Provider, Hit, Hits
from functools import partial

class ObjlibCommands(Provider):
    """Command palette provider for all CLI-equivalent actions."""

    COMMANDS = {
        "Search Library": "action_focus_search",
        "Browse Categories": "action_browse_categories",
        "Filter by Course": "action_filter_course",
        "Toggle Navigation": "action_toggle_nav",
        "New Session": "action_new_session",
        "Load Session": "action_load_session",
        "Export Session": "action_export_session",
    }

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, action in self.COMMANDS.items():
            score = matcher.match(name)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(name),
                    partial(self.app.run_action, action),
                )

class ObjlibApp(App):
    COMMANDS = App.COMMANDS | {ObjlibCommands}
```

### Anti-Patterns to Avoid
- **Direct widget-to-widget calls:** Widget A should never call `self.app.query_one(WidgetB).update()`. Instead, post a Message that the App handles, and let the App update state which triggers reactive re-renders.
- **Holding Database connections across await:** Canon.json rule #6. Always `with Database(path) as db:` inside a sync function passed to `asyncio.to_thread()`.
- **Importing from internal modules in TUI code:** Canon.json rule #1. The TUI imports from `objlib.services` only. The services layer imports from internal modules.
- **Running sync Gemini API on the main thread:** Will freeze the TUI for 300ms-2s. Always use `@work` or `asyncio.to_thread()`.
- **Using `CSS_PATH`:** User decision locks inline CSS via `CSS` class variable. No `.tcss` files.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Debounce timer | Custom asyncio timer | `self.set_timer(0.3, callback)` | Textual's timer integrates with event loop; cancel with `timer.stop()` |
| Stale search cancellation | UUID tracking + manual cancel | `@work(exclusive=True)` | Textual automatically cancels previous worker; no race conditions |
| Keyboard navigation in tree | Custom key handlers | `Tree` widget built-in bindings | Already handles up/down/enter/space/expand/collapse |
| Fuzzy command search | Custom matching | `CommandPalette` + `Provider.matcher()` | Built-in fuzzy matching with highlighting |
| Scrollable document preview | Custom scroll logic | `RichLog` widget | Handles scrolling, Rich renderables, auto-scroll |
| Terminal resize detection | Manual ioctl | `on_resize` event | Textual fires this automatically on terminal resize |
| CSS layout | Manual width calculation | Textual CSS grid with `%`, `fr`, `1fr` units | Textual's CSS engine handles layout, responsive sizing |
| Focus cycling between panes | Manual focus management | `action_focus_next` / `action_focus_previous` + Tab/Shift+Tab | Built-in Textual focus system |

**Key insight:** Textual provides most UI primitives out of the box. The main engineering effort is (1) the services facade layer, (2) state management wiring, and (3) the three-pane layout composition. Widget behavior is largely built-in.

## Common Pitfalls

### Pitfall 1: Blocking the Event Loop with Sync I/O
**What goes wrong:** Calling `GeminiSearchClient.query_with_retry()` or `Database(path)` directly in an async handler freezes the TUI for the duration of the I/O call.
**Why it happens:** The existing codebase is synchronous. Developers forget to wrap in `asyncio.to_thread()`.
**How to avoid:** Every service method that touches disk or network MUST use `asyncio.to_thread()`. The services facade enforces this -- TUI code calls `await service.method()` and the facade wraps sync internals.
**Warning signs:** TUI becomes unresponsive during search; keystrokes buffer up and replay after search completes.

### Pitfall 2: Race Conditions in Live Search
**What goes wrong:** Fast typing sends multiple search requests; slow request returns after fast request, overwriting correct results with stale ones.
**Why it happens:** Without cancellation, all requests complete independently.
**How to avoid:** Use `@work(exclusive=True)` which auto-cancels previous workers. Combined with 300ms debounce timer, this ensures only one search runs at a time.
**Warning signs:** Results flicker or show results for a previous query.

### Pitfall 3: Holding SQLite Connections Across Await Boundaries
**What goes wrong:** A `Database` context manager is opened before an `await` and used after it. SQLite connections are not thread-safe; the connection could be used from the wrong thread.
**Why it happens:** Natural pattern: `with Database(path) as db: results = await self.search(db)`.
**How to avoid:** Canon.json rule #6: always open AND close the Database connection within the same synchronous function passed to `asyncio.to_thread()`. Never pass a `db` object across an await boundary.
**Warning signs:** `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread`.

### Pitfall 4: Widget State Mutation Outside the App Message Flow
**What goes wrong:** A widget directly modifies another widget's state, creating implicit coupling that's hard to debug.
**Why it happens:** Shortcut: `self.app.query_one("#preview").show_document(text)` from inside a results widget.
**How to avoid:** Post a `Message` upward. The App handles it, updates `AppState` reactive properties, and watchers on those properties update the relevant widgets.
**Warning signs:** State inconsistencies between panes; changes not reflected when expected.

### Pitfall 5: Forgetting to Enrich Citations After Search
**What goes wrong:** Citations display with `file_path=None` and `metadata=None`, making them useless for navigation and filtering.
**Why it happens:** Canon.json rule #4 is easy to forget.
**How to avoid:** The `SearchService.search()` facade method MUST call `enrich_citations()` internally before returning. This is baked into the service, not left to the TUI.
**Warning signs:** Results show Gemini file IDs instead of filenames; no course/year/difficulty metadata displayed.

### Pitfall 6: CSS Specificity Issues with Layout Classes
**What goes wrong:** Responsive layout classes (`.layout-wide`, `.layout-medium`, `.layout-narrow`) don't override base styles because of CSS specificity.
**Why it happens:** Textual CSS follows specificity rules similar to web CSS.
**How to avoid:** Use the `.layout-*` class selector with higher specificity than base widget selectors. Test all three breakpoints explicitly.
**Warning signs:** Layout doesn't change when terminal is resized.

### Pitfall 7: Textual Version Incompatibility
**What goes wrong:** Code uses API from a different Textual version than installed.
**Why it happens:** Textual is actively developed; API changes between major versions (v4 -> v5).
**How to avoid:** Pin `textual>=5.0` in dependencies. Verify API patterns against v5.x documentation. The `CommandPalette` class, `@work` decorator, `reactive`, and `Tree` widget are stable in v5.x.
**Warning signs:** `ImportError` or `AttributeError` on Textual classes.

## Code Examples

### Complete Three-Pane Layout Composition
```python
# Source: Verified patterns from Context7 (Textual official docs)
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Input, Static, Tree, RichLog

class ObjlibApp(App):
    CSS = """
    #search-bar {
        dock: top;
        height: 3;
        padding: 0 1;
    }
    #main {
        height: 1fr;
    }
    #nav-pane {
        width: 1fr;
        min-width: 25;
        max-width: 40;
        border-right: solid $primary;
    }
    #results-pane {
        width: 2fr;
        min-width: 30;
        border-right: solid $accent;
    }
    #preview-pane {
        width: 3fr;
        min-width: 40;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary-background;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Search the library...", id="search-bar")
        with Horizontal(id="main"):
            with Vertical(id="nav-pane"):
                yield Tree("Library", id="nav-tree")
            with Vertical(id="results-pane"):
                yield Static("Search results appear here", id="results-header")
                yield ScrollableContainer(id="results-list")
            with Vertical(id="preview-pane"):
                yield RichLog(id="preview", highlight=True, markup=True)
        yield Static("Ready", id="status-bar")
        yield Footer()
```

### Service Initialization Pattern (from Canon.json rule #2)
```python
# Entry point: src/objlib/tui/__init__.py
import keyring
from objlib.services import SearchService, LibraryService, SessionService

def run_tui():
    """Launch the interactive TUI."""
    api_key = keyring.get_password("objlib-gemini", "api_key")
    if not api_key:
        raise SystemExit("No API key found. Run: objlib config set-key")

    # Resolve store name
    from google import genai
    from objlib.search.client import GeminiSearchClient
    client = genai.Client(api_key=api_key)
    store_name = GeminiSearchClient.resolve_store_name(client, "objectivism-library-test")

    db_path = "data/library.db"

    search_svc = SearchService(api_key, store_name, db_path)
    library_svc = LibraryService(db_path)
    session_svc = SessionService(db_path)

    app = ObjlibApp(search_svc, library_svc, session_svc)
    app.run()
```

### Citation Jump with Text-Search Fallback
```python
# Pattern for TUI-06: click citation -> jump to source in preview
async def _jump_to_citation(self, citation):
    """Load document and scroll to citation excerpt."""
    content = await self.library_service.get_file_content(citation.file_path)
    if content is None:
        self.notify("Document not available (disk not mounted?)", severity="warning")
        return

    preview = self.query_one("#preview", RichLog)
    preview.clear()

    # Highlight citation text and query terms
    from rich.text import Text
    text = Text(content)
    if citation.text:
        # Find and highlight the citation excerpt
        text.highlight_words([citation.text[:80]], style="bold yellow on dark_green")
    preview.write(text)

    # Scroll to the citation text position
    pos = content.lower().find(citation.text.lower()[:100])
    if pos >= 0:
        line_number = content[:pos].count('\n')
        preview.scroll_to(y=line_number, animate=True)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| curses/ncurses | Textual CSS-based layouts | 2022-2023 | No manual coordinate math; responsive layouts for free |
| Sync TUI event loops | asyncio-native event loop | Textual 0.x -> 1.x | Workers, async handlers, no blocking |
| External .tcss files | Inline `CSS` class variable | Always supported | Self-contained widgets; no file management |
| `run_worker()` method | `@work` decorator | Textual 0.40+ | Cleaner syntax; automatic worker management |
| Manual worker cancellation | `exclusive=True` | Textual 0.40+ | Auto-cancels previous worker; eliminates race conditions |
| Textual v4 | Textual v5 (current) | July 2025 | Stable API; `CommandPalette` improvements |

**Deprecated/outdated:**
- `Placeholder` widget: was for development; use real widgets in production
- `CSS_PATH` for inline styles: still works but `CSS` class variable is preferred for inline
- `run_worker()` as primary API: `@work` decorator is now the idiomatic approach

## Open Questions

1. **Textual `RichLog.scroll_to()` line-level precision**
   - What we know: `RichLog` has a `scroll_to(y=...)` method inherited from `ScrollView`.
   - What's unclear: Whether `y` parameter maps to line numbers or pixel/cell offsets in RichLog specifically. May need `scroll_visible()` on a specific region instead.
   - Recommendation: Test empirically during implementation. If `scroll_to` doesn't give line-level precision, use `write()` with content split into chunks where each chunk is a Static, and scroll the parent container to the target Static.

2. **Store name resolution at TUI startup**
   - What we know: `GeminiSearchClient.resolve_store_name()` does a network call (lists all stores). This could take 1-2s at TUI launch.
   - What's unclear: Whether this should be cached or done lazily on first search.
   - Recommendation: Do it at startup with a loading screen/spinner. Cache the resolved name for the session lifetime.

3. **Session bookmark schema**
   - What we know: `SessionManager` supports `search`, `view`, `synthesize`, `note`, `error` event types. There is no `bookmark` event type.
   - What's unclear: Whether to add a new `bookmark` event type to the `VALID_EVENT_TYPES` frozenset in `session/manager.py`, or store bookmarks as `note` events with a specific payload structure.
   - Recommendation: Add `bookmark` to `VALID_EVENT_TYPES` and use payload `{"file_path": ..., "filename": ..., "note": ...}`. This is a minor schema change (no migration needed -- just expanding the CHECK constraint or the Python-side validation set).

4. **External disk dependency for document preview**
   - What we know: Canon.json rule #11 says disk commands require `/Volumes/U32 Shadow` mounted, but query commands work without it. Document preview reads `.txt` files from disk.
   - What's unclear: Whether `file_path` in the database points to the external volume path. If so, preview only works when disk is mounted.
   - Recommendation: Degrade gracefully -- show "Document not available (disk not mounted)" in preview pane when file cannot be read. Browse/filter/search results still work from SQLite.

## Sources

### Primary (HIGH confidence)
- `/websites/textual_textualize_io` via Context7 -- App subclass, compose(), CSS class variable, Tree widget, RichLog widget, CommandPalette, Provider
- `/textualize/textual` via Context7 -- @work decorator, exclusive=True, Worker.StateChanged, on_resize, DEFAULT_CSS, Input.Changed, set_timer
- Textual GitHub releases (via Perplexity) -- v5.3.0 latest stable (Aug 2025)

### Secondary (MEDIUM confidence)
- Existing codebase analysis (read all source files):
  - `src/objlib/search/client.py` -- GeminiSearchClient is synchronous, needs asyncio.to_thread() wrapping
  - `src/objlib/session/manager.py` -- SessionManager takes sqlite3.Connection, VALID_EVENT_TYPES frozenset
  - `src/objlib/database.py` -- Database context manager pattern, all query methods
  - `src/objlib/models.py` -- Citation, AppState, SearchResult dataclasses
  - `src/objlib/search/citations.py` -- extract_citations(), enrich_citations(), build_metadata_filter()
  - `src/objlib/search/formatter.py` -- Rich Panel/Table output (reusable in RichLog)
  - `src/objlib/cli.py` -- search(), browse(), filter_cmd(), session_*() implementations

### Tertiary (LOW confidence)
- RichLog.scroll_to() line-level behavior -- inferred from ScrollView docs, not tested empirically. Flagged in Open Questions.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- Textual v5.3.0 verified via Context7 + PyPI; all widget APIs confirmed
- Architecture: HIGH -- Services facade pattern verified against Canon.json rules; async patterns verified via Context7
- Pitfalls: HIGH -- All pitfalls derived from verified API behavior (exclusive workers, sqlite3 thread safety, Canon.json rules)
- Responsive layout: MEDIUM -- CSS class toggling pattern verified; exact breakpoint behavior needs testing
- Citation jump scrolling: LOW -- RichLog.scroll_to() precision unverified empirically

**Research date:** 2026-02-18
**Valid until:** 2026-03-18 (Textual v5.x API is stable; 30-day validity)
