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
from objlib.tui.providers import ObjlibCommands
from objlib.tui.state import Bookmark, FilterSet
from objlib.tui.widgets import FilterPanel, NavTree, PreviewPane, ResultsList, SearchBar


class ObjlibApp(App):
    """Objectivism Library interactive terminal application.

    Three-pane layout: navigation tree (left), search results (center),
    content preview (right). Responsive breakpoints adjust layout for
    different terminal widths.
    """

    TITLE = "Objectivism Library"
    SUB_TITLE = "Semantic Search & Browse"
    COMMANDS = App.COMMANDS | {ObjlibCommands}

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

    /* Fullscreen preview: hide nav + results panes */
    .fullscreen-preview #nav-pane {
        display: none;
    }

    .fullscreen-preview #results-pane {
        display: none;
    }

    .fullscreen-preview #preview-pane {
        width: 100%;
    }
    """

    BINDINGS = [
        ("ctrl+p", "command_palette", "Commands"),
        ("ctrl+f", "focus_search", "Search"),
        ("tab", "focus_next", "Next Pane"),
        ("shift+tab", "focus_previous", "Previous Pane"),
        ("ctrl+b", "toggle_nav", "Toggle Nav"),
        ("ctrl+d", "toggle_bookmark", "Bookmark"),
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

    def on_resize(self, event=None) -> None:
        """Adjust layout classes based on terminal width.

        Three breakpoints:
        - Wide (>= 140): full three-pane layout
        - Medium (80-139): two-pane, nav hidden
        - Narrow (< 80): stacked single-column
        """
        width = self.size.width
        self.remove_class("layout-wide", "layout-medium", "layout-narrow")
        if width >= 140:
            self.add_class("layout-wide")
        elif width >= 80:
            self.add_class("layout-medium")
        else:
            self.add_class("layout-narrow")

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

    # ------------------------------------------------------------------
    # Bookmark actions
    # ------------------------------------------------------------------

    def action_toggle_bookmark(self) -> None:
        """Toggle a bookmark on the currently previewed document."""
        preview = self.query_one(PreviewPane)
        file_path = preview._current_file_path
        if not file_path:
            self.notify("No document to bookmark", severity="warning")
            return

        import os

        filename = os.path.basename(file_path)

        # Check if already bookmarked
        existing = next(
            (b for b in self.bookmarks if b.file_path == file_path), None
        )
        if existing:
            self.bookmarks = [b for b in self.bookmarks if b.file_path != file_path]
            self.notify("Bookmark removed")
        else:
            self.bookmarks = list(self.bookmarks) + [
                Bookmark(file_path=file_path, filename=filename)
            ]
            self.notify(f"Bookmarked: {filename}")

    def action_show_bookmarks(self) -> None:
        """Display bookmarked files in the results list."""
        results = self.query_one(ResultsList)
        if not self.bookmarks:
            results.update_status("No bookmarks yet (use Ctrl+D to bookmark)")
            return

        from objlib.models import Citation

        citations = [
            Citation(
                index=i + 1,
                title=b.filename,
                uri=None,
                text=b.note or "Bookmarked document",
                document_name=None,
                confidence=1.0,
                file_path=b.file_path,
            )
            for i, b in enumerate(self.bookmarks)
        ]
        results.update_results(citations)

    def watch_bookmarks(self, bookmarks: list) -> None:
        """Update status bar when bookmarks change."""
        count = len(bookmarks)
        if count > 0:
            try:
                self.query_one("#status-bar", Static).update(
                    f"{count} bookmark{'s' if count != 1 else ''} | "
                    f"{len(self.results)} results | Ctrl+P: Commands"
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Session actions
    # ------------------------------------------------------------------

    async def action_new_session(self) -> None:
        """Create a new research session."""
        if self.session_service is None:
            self.notify("Session service not available", severity="warning")
            return
        session_id = await self.session_service.create_session()
        self.active_session_id = session_id
        self.notify(f"New session: {session_id[:8]}")

    async def action_save_session(self) -> None:
        """Save current state (filters, bookmarks) to the active session."""
        if self.session_service is None:
            self.notify("Session service not available", severity="warning")
            return
        if self.active_session_id is None:
            await self.action_new_session()
        if self.active_session_id is None:
            return
        try:
            from dataclasses import asdict

            # Save filter state
            await self.session_service.add_event(
                self.active_session_id,
                "note",
                {
                    "type": "filter_state",
                    "filters": {
                        "category": self.active_filters.category,
                        "course": self.active_filters.course,
                        "difficulty": self.active_filters.difficulty,
                    },
                },
            )
            # Save bookmarks
            await self.session_service.add_event(
                self.active_session_id,
                "note",
                {
                    "type": "bookmarks",
                    "bookmarks": [asdict(b) for b in self.bookmarks],
                },
            )
            self.notify("Session saved")
        except Exception as e:
            self.notify(f"Save failed: {e}", severity="error")

    async def action_load_session(self) -> None:
        """Load the most recent session, restoring bookmarks and filters."""
        if self.session_service is None:
            self.notify("Session service not available", severity="warning")
            return
        try:
            sessions = await self.session_service.list_sessions()
            if not sessions:
                self.notify("No sessions found", severity="warning")
                return

            # Load most recent session
            session = sessions[0]
            session_id = session["id"]
            events = await self.session_service.get_events(session_id)

            # Restore from events (scan in reverse to find latest state)
            for event in reversed(events):
                if event["event_type"] == "note":
                    payload = event["payload"]
                    if payload.get("type") == "bookmarks" and not self.bookmarks:
                        bm_data = payload.get("bookmarks", [])
                        self.bookmarks = [Bookmark(**b) for b in bm_data]
                    elif payload.get("type") == "filter_state":
                        f = payload.get("filters", {})
                        self.active_filters = FilterSet(
                            category=f.get("category"),
                            course=f.get("course"),
                            difficulty=f.get("difficulty"),
                        )

            # Restore search history from search events
            search_events = [e for e in events if e["event_type"] == "search"]
            self.search_history = [
                e["payload"]["query"]
                for e in search_events
                if "query" in e["payload"]
            ]

            self.active_session_id = session_id
            self.notify(f"Session loaded: {session['name']}")
        except Exception as e:
            self.notify(f"Load failed: {e}", severity="error")

    async def action_export_session(self) -> None:
        """Export active session (placeholder -- use CLI for full export)."""
        if not self.active_session_id or not self.session_service:
            self.notify("No active session to export", severity="warning")
            return
        self.notify("Session export: use objlib session commands in CLI")

    # ------------------------------------------------------------------
    # Synthesis action
    # ------------------------------------------------------------------

    async def action_synthesize_results(self) -> None:
        """Synthesize a structured answer from current search results."""
        if not self.results or len(self.results) < 2:
            self.notify(
                "Need at least 2 results to synthesize", severity="warning"
            )
            return
        if not self.search_service:
            self.notify("Search service not available", severity="warning")
            return

        self.notify("Synthesizing...")
        try:
            output = await self.search_service.synthesize(
                self.query, self.results
            )
            if output:
                preview = self.query_one(PreviewPane)
                from rich.text import Text

                text = Text()
                if output.bridging_intro:
                    text.append(output.bridging_intro + "\n\n")
                for claim in output.claims:
                    text.append(f"  {claim.claim_text}\n")
                    text.append(
                        f'  "{claim.citation.quote}"\n', style="italic dim"
                    )
                if output.bridging_conclusion:
                    text.append("\n" + output.bridging_conclusion)
                preview.clear()
                preview.write(text)
            else:
                self.notify(
                    "Synthesis not available (need 5+ results)",
                    severity="warning",
                )
        except Exception as e:
            self.notify(f"Synthesis failed: {e}", severity="error")

    # ------------------------------------------------------------------
    # Navigation / UI toggle actions
    # ------------------------------------------------------------------

    def action_browse_categories(self) -> None:
        """Focus the navigation tree for category browsing."""
        nav = self.query_one(NavTree)
        nav.focus()

    def action_browse_courses(self) -> None:
        """Focus the navigation tree for course browsing."""
        nav = self.query_one(NavTree)
        nav.focus()

    def action_reset_filters(self) -> None:
        """Reset all filter dropdowns to their default (blank) state."""
        try:
            fp = self.query_one(FilterPanel)
            fp.reset_filters()
        except Exception:
            pass

    def action_toggle_fullscreen_preview(self) -> None:
        """Toggle fullscreen preview mode (hides nav and results panes)."""
        self.toggle_class("fullscreen-preview")

    def action_show_shortcuts(self) -> None:
        """Display keyboard shortcut reference in the preview pane."""
        try:
            preview = self.query_one(PreviewPane)
            from rich.text import Text

            text = Text("Keyboard Shortcuts\n\n", style="bold")
            for binding in self.BINDINGS:
                keys = binding[0]
                desc = binding[2] if len(binding) > 2 else binding[1]
                text.append(f"  {keys:<15} {desc}\n")
            preview.clear()
            preview.write(text)
        except Exception:
            self.notify(
                "Ctrl+F: Search | Tab: Panes | Ctrl+P: Commands | "
                "Ctrl+D: Bookmark | Ctrl+S: Save Session"
            )
