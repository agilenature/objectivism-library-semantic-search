"""Objectivism Library TUI Application.

Main Textual App subclass with three-pane layout, centralized reactive
state, key bindings, and message handlers. Wires all widgets together
and delegates search/browse to service facades.
"""

from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static

from objlib.tui.messages import (
    FileSelected,
    FilterChanged,
    NavigationRequested,
    ResultSelected,
    SearchRequested,
)
from objlib.tui.state import FilterSet
from objlib.tui.widgets import FilterPanel, NavTree, PreviewPane, ResultsList, SearchBar


class ObjlibApp(App):
    """Objectivism Library interactive terminal application.

    Three-pane layout: navigation tree (left), search results (center),
    content preview (right). Responsive breakpoints adjust layout for
    different terminal widths.
    """

    TITLE = "Objectivism Library"
    SUB_TITLE = "Semantic Search & Browse"

    CSS = """
    #main {
        layout: horizontal;
        height: 1fr;
    }

    #nav-pane {
        width: 1fr;
        min-width: 25;
        max-width: 40;
        border-right: solid $primary;
        overflow-y: auto;
    }

    #results-pane {
        width: 2fr;
        min-width: 30;
        border-right: solid $accent;
        overflow-y: auto;
    }

    #preview-pane {
        width: 3fr;
        min-width: 40;
        overflow-y: auto;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary-background;
        color: $text;
        padding: 0 1;
    }

    /* Medium layout: hide nav, 2-pane */
    .layout-medium #nav-pane {
        display: none;
    }

    .layout-medium #results-pane {
        width: 2fr;
    }

    .layout-medium #preview-pane {
        width: 3fr;
    }

    /* Narrow layout: stacked single-pane */
    .layout-narrow #main {
        layout: vertical;
    }

    .layout-narrow #nav-pane {
        display: none;
    }

    .layout-narrow #results-pane {
        width: 100%;
        height: 1fr;
    }

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
        ("ctrl+s", "save_session", "Save Session"),
        ("escape", "clear_search", "Clear"),
    ]

    # Reactive state -- widgets observe these for re-renders
    query: reactive[str] = reactive("")
    results: reactive[list] = reactive(list)
    selected_index: reactive[int | None] = reactive(None)
    search_history: reactive[list] = reactive(list)
    active_filters: reactive[FilterSet] = reactive(FilterSet)
    bookmarks: reactive[list] = reactive(list)
    is_searching: reactive[bool] = reactive(False)
    active_session_id: reactive[str | None] = reactive(None)

    def __init__(
        self,
        search_service: object | None = None,
        library_service: object | None = None,
        session_service: object | None = None,
    ) -> None:
        """Initialize the app with service dependencies.

        Services are stored as opaque attributes -- the App does not
        import service classes directly. They are passed in by run_tui().

        Args:
            search_service: Search facade (may be None in tests).
            library_service: Library data facade (may be None in tests).
            session_service: Session management facade (may be None in tests).
        """
        super().__init__()
        self.search_service = search_service
        self.library_service = library_service
        self.session_service = session_service

    def compose(self) -> ComposeResult:
        """Compose the three-pane layout with real widgets."""
        yield Header(show_clock=True)
        yield SearchBar()
        with Horizontal(id="main"):
            with Vertical(id="nav-pane"):
                yield FilterPanel()
                yield NavTree()
            with Vertical(id="results-pane"):
                yield ResultsList()
            with Vertical(id="preview-pane"):
                yield PreviewPane()
        yield Static(
            "Ready | 0 results | Ctrl+P: Commands",
            id="status-bar",
        )
        yield Footer()

    async def on_mount(self) -> None:
        """Populate nav tree and show preview placeholder on startup."""
        if self.library_service is not None:
            try:
                await self.query_one(NavTree).populate(self.library_service)
            except Exception as e:
                self.log.error(f"Failed to populate nav tree: {e}")
        self.query_one(PreviewPane).show_placeholder()

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def on_search_requested(self, event: SearchRequested) -> None:
        """Handle search requests from the SearchBar widget."""
        self.query = event.query
        if not event.query:
            self.results = []
            self.selected_index = None
            self.query_one(ResultsList).update_status("Enter a search query")
            self.query_one(PreviewPane).show_placeholder()
            self.query_one("#status-bar", Static).update(
                "Ready | 0 results | Ctrl+P: Commands"
            )
            return
        self._run_search(event.query)

    @work(exclusive=True)
    async def _run_search(self, query: str) -> None:
        """Execute search via service (auto-cancels stale searches).

        The @work(exclusive=True) decorator ensures only the latest
        search runs -- previous searches are automatically cancelled.
        """
        if self.search_service is None:
            return

        self.is_searching = True
        try:
            results_widget = self.query_one(ResultsList)
            results_widget.update_status("Searching...")

            # Build filter strings if any active filters
            filters = None
            if not self.active_filters.is_empty():
                filters = self.active_filters.to_filter_strings()

            result = await self.search_service.search(query, filters=filters)
            self.results = result.citations if hasattr(result, "citations") else []
            results_widget.update_results(self.results)

            # Update status bar
            count = len(self.results)
            truncated_query = query[:30]
            self.query_one("#status-bar", Static).update(
                f"{count} results | {truncated_query} | Ctrl+P: Commands"
            )

            # Log to session if active
            if self.active_session_id and self.session_service:
                try:
                    await self.session_service.add_event(
                        self.active_session_id,
                        "search",
                        {"query": query, "result_count": count},
                    )
                except Exception:
                    pass
        except Exception as e:
            self.query_one(ResultsList).update_status(f"Search error: {e}")
            self.notify("Search error", severity="error")
        finally:
            self.is_searching = False

    async def on_result_selected(self, event: ResultSelected) -> None:
        """Handle result selection -- update highlight and show preview."""
        self.selected_index = event.index
        results_widget = self.query_one(ResultsList)
        try:
            results_widget.select_index(event.index)
        except Exception:
            pass  # Index may not exist if results were cleared

        preview = self.query_one(PreviewPane)
        if event.citation is None:
            return

        # Try to load full document content
        file_path = getattr(event.citation, "file_path", None)
        if file_path and self.library_service is not None:
            content = await self.library_service.get_file_content(file_path)
            if content:
                highlight = [self.query] if self.query else None
                preview.show_document(content, file_path, highlight_terms=highlight)
            else:
                preview.show_unavailable()
        else:
            # No file path -- show citation detail panel instead
            preview.show_citation_detail(event.citation)

    async def on_file_selected(self, event: FileSelected) -> None:
        """Handle file selection from nav tree -- show document preview."""
        preview = self.query_one(PreviewPane)
        if self.library_service is None:
            preview.show_unavailable()
            return

        content = await self.library_service.get_file_content(event.file_path)
        if content:
            preview.show_document(content, event.file_path)
        else:
            preview.show_unavailable()

    async def on_navigation_requested(self, event: NavigationRequested) -> None:
        """Handle nav tree category/course selection -- show file listing."""
        if self.library_service is None:
            return

        results_widget = self.query_one(ResultsList)
        try:
            if event.course:
                files = await self.library_service.get_files_by_course(event.course)
                label = f"Course: {event.course}"
            elif event.category:
                files = await self.library_service.get_items_by_category(event.category)
                label = f"Category: {event.category}"
            else:
                return

            count = len(files)
            self.query_one("#status-bar", Static).update(
                f"{count} files | {label} | Ctrl+P: Commands"
            )
            # Show a status message since navigation results are not Citation objects
            results_widget.update_status(
                f"{count} files in {label}\n\nSelect files from the navigation tree to preview."
            )
        except Exception as e:
            results_widget.update_status(f"Navigation error: {e}")

    def on_filter_changed(self, event: FilterChanged) -> None:
        """Handle filter changes -- re-run search with new filters."""
        self.active_filters = event.filters
        if self.query:
            self._run_search(self.query)

    def watch_is_searching(self, searching: bool) -> None:
        """Update status bar when search state changes."""
        if searching:
            self.query_one("#status-bar", Static).update("Searching...")

    # ------------------------------------------------------------------
    # Key binding actions
    # ------------------------------------------------------------------

    def on_resize(self) -> None:
        """Adjust layout classes based on terminal width."""
        width = self.size.width
        self.remove_class("layout-medium", "layout-narrow")
        if width < 80:
            self.add_class("layout-narrow")
        elif width < 140:
            self.add_class("layout-medium")

    def action_focus_search(self) -> None:
        """Focus the search input bar."""
        self.query_one(SearchBar).focus()

    def action_toggle_nav(self) -> None:
        """Toggle navigation pane visibility."""
        nav = self.query_one("#nav-pane")
        nav.toggle_class("hidden")

    def action_clear_search(self) -> None:
        """Clear search input and results."""
        self.query_one(SearchBar).clear_and_reset()
        self.query = ""
        self.results = []
        self.selected_index = None

    def action_save_session(self) -> None:
        """Save current session state."""
        if self.session_service is None:
            return
        # Session save implementation will be added in Wave 4
