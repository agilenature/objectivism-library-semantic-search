"""Objectivism Library TUI Application.

Main Textual App subclass with three-pane layout, centralized reactive
state, key bindings, and message handlers. Wires all widgets together
and delegates search/browse to service facades.
"""

from __future__ import annotations

import asyncio

import reactivex as rx
from reactivex import operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from reactivex.subject import BehaviorSubject
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
from objlib.tui.rx_pipeline import defer_task
from objlib.tui.state import Bookmark, FilterSet
from objlib.tui.telemetry import Telemetry, set_telemetry
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
        telemetry: Telemetry | None = None,
    ) -> None:
        """Initialize the app with service dependencies.

        Services are stored as opaque attributes -- the App does not
        import service classes directly. They are passed in by run_tui().

        Args:
            search_service: Search facade (may be None in tests).
            library_service: Library data facade (may be None in tests).
            session_service: Session management facade (may be None in tests).
            telemetry: OTel tracing facade. Defaults to no-op if not provided.
        """
        super().__init__()
        self.search_service = search_service
        self.library_service = library_service
        self.session_service = session_service
        self.telemetry = telemetry if telemetry is not None else Telemetry.noop()
        set_telemetry(self.telemetry)
        self._filter_subject = BehaviorSubject(FilterSet())
        self._rx_subscription = None
        self._rx_clear_subscription = None

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
        with self.telemetry.span("app.mount") as span:
            span.set_attribute("mount.has_library_service", self.library_service is not None)
            span.set_attribute("mount.has_search_service", self.search_service is not None)
            if self.library_service is not None:
                try:
                    await self.query_one(NavTree).populate(self.library_service)
                    span.set_attribute("mount.nav_populated", True)
                except Exception as e:
                    self.log.error(f"Failed to populate nav tree: {e}")
                    span.set_attribute("mount.nav_populated", False)
                    span.record_exception(e)
            else:
                span.set_attribute("mount.nav_populated", False)
            self.query_one(PreviewPane).show_placeholder()
            self.telemetry.log.info("app mounted")

        # Wire RxPY observable pipeline for search
        if self.search_service is not None:
            loop = asyncio.get_running_loop()
            scheduler = AsyncIOScheduler(loop)
            search_bar = self.query_one(SearchBar)

            # Two-stream merge: debounced typing + immediate Enter
            query_stream = rx.merge(
                search_bar.input_subject.pipe(
                    ops.filter(lambda q: q != ""),
                    ops.debounce(0.3, scheduler=scheduler),
                ),
                search_bar.enter_subject,
            ).pipe(ops.distinct_until_changed())

            # Combine with filter stream (BehaviorSubject provides initial value)
            pipeline = rx.combine_latest(
                query_stream,
                self._filter_subject,
            ).pipe(
                ops.switch_map(lambda pair: self._search_observable(pair[0], pair[1]))
            )

            self._rx_subscription = pipeline.subscribe(
                on_next=self._on_search_result,
            )

            # Empty-query immediate clearing (no debounce)
            self._rx_clear_subscription = search_bar.input_subject.pipe(
                ops.filter(lambda q: q == ""),
            ).subscribe(
                on_next=lambda _: self._clear_results(),
            )

    # ------------------------------------------------------------------
    # RxPY pipeline methods
    # ------------------------------------------------------------------

    def _search_observable(self, query: str, filter_set):
        """Create an observable for a single search with error handling."""
        self.is_searching = True
        self.query = query
        self.query_one(ResultsList).update_status("Searching...")

        filters = None
        if hasattr(filter_set, "is_empty") and not filter_set.is_empty():
            filters = filter_set.to_filter_strings()

        return defer_task(
            lambda: self.search_service.search(query, filters=filters, top_k=20)
        ).pipe(
            ops.catch(lambda err, source: self._handle_search_error(err, query))
        )

    def _on_search_result(self, result) -> None:
        """Handle a successful search result from the pipeline."""
        self.results = result.citations if hasattr(result, "citations") else []
        results_widget = self.query_one(ResultsList)
        results_widget.update_results(self.results)
        self.query_one(SearchBar).focus()
        count = len(self.results)
        truncated_query = self.query[:30]
        self.query_one("#status-bar", Static).update(
            f"{count} citations retrieved | {truncated_query} | Ctrl+P: Commands"
        )
        self.telemetry.log.info(
            f"search completed query={self.query!r} result_count={count}"
        )
        self.is_searching = False
        if self.active_session_id and self.session_service:
            asyncio.get_running_loop().create_task(
                self._log_search_event(self.query, count)
            )

    async def _log_search_event(self, query: str, count: int) -> None:
        """Log search event to session (fire-and-forget)."""
        try:
            await self.session_service.add_event(
                self.active_session_id,
                "search",
                {"query": query, "result_count": count},
            )
        except Exception:
            pass

    def _handle_search_error(self, error: Exception, query: str):
        """Handle search error: show notification, reset state, return empty observable."""
        self.query_one(ResultsList).update_status(f"Search error: {error}")
        self.notify("Search error", severity="error")
        self.is_searching = False
        self.telemetry.log.error(f"search error query={query!r} error={error!r}")
        return rx.empty()

    def _clear_results(self) -> None:
        """Clear search results and reset UI state."""
        self.telemetry.log.info("search cleared")
        self.query = ""
        self.results = []
        self.selected_index = None
        self.query_one(ResultsList).update_status("Enter a search query")
        self.query_one(PreviewPane).show_placeholder()
        self.query_one("#status-bar", Static).update(
            "Ready | 0 results | Ctrl+P: Commands"
        )
        self.is_searching = False

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

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

        with self.telemetry.span("tui.result_selected") as span:
            span.set_attribute("result.index", event.index)
            file_path = getattr(event.citation, "file_path", None)
            span.set_attribute("result.has_file_path", file_path is not None)

            if file_path and self.library_service is not None:
                try:
                    content = await self.library_service.get_file_content(file_path)
                    span.set_attribute("result.content_loaded", content is not None)
                    if content:
                        highlight = [self.query] if self.query else None
                        preview.show_document(content, file_path, highlight_terms=highlight)
                    else:
                        preview.show_unavailable()
                except Exception as e:
                    span.record_exception(e)
                    span.set_attribute("result.content_loaded", False)
                    self.telemetry.log.error(
                        f"failed to load document file={file_path!r} error={e!r}"
                    )
                    preview.show_unavailable()
            else:
                span.set_attribute("result.content_loaded", False)
                # No file path -- show citation detail panel instead
                preview.show_citation_detail(event.citation)

    async def on_file_selected(self, event: FileSelected) -> None:
        """Handle file selection from nav tree -- show document preview."""
        preview = self.query_one(PreviewPane)
        if self.library_service is None:
            preview.show_unavailable()
            return

        with self.telemetry.span("tui.file_selected") as span:
            span.set_attribute("file.path", event.file_path)
            content = await self.library_service.get_file_content(event.file_path)
            span.set_attribute("file.content_loaded", content is not None)
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
                nav_type, nav_value = "course", event.course
            elif event.category:
                nav_type, nav_value = "category", event.category
            else:
                return

            with self.telemetry.span("tui.navigation_requested") as span:
                span.set_attribute("nav.type", nav_type)
                span.set_attribute("nav.value", nav_value)

                if event.course:
                    files = await self.library_service.get_files_by_course(event.course)
                    label = f"Course: {event.course}"
                else:
                    files = await self.library_service.get_items_by_category(event.category)
                    label = f"Category: {event.category}"

                count = len(files)
                span.set_attribute("nav.result_count", count)
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
        """Handle filter changes -- feed the filter Subject to re-trigger pipeline."""
        self.active_filters = event.filters
        self.telemetry.log.info(f"filter changed filters={event.filters}")
        self._filter_subject.on_next(event.filters)

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
        self._clear_results()

    def on_unmount(self) -> None:
        """Dispose RxPY subscriptions on app shutdown."""
        if self._rx_subscription is not None:
            self._rx_subscription.dispose()
            self._rx_subscription = None
        if self._rx_clear_subscription is not None:
            self._rx_clear_subscription.dispose()
            self._rx_clear_subscription = None

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

        with self.telemetry.span("tui.bookmark_toggled") as span:
            span.set_attribute("bookmark.file_path", file_path)

            # Check if already bookmarked
            existing = next(
                (b for b in self.bookmarks if b.file_path == file_path), None
            )
            if existing:
                self.bookmarks = [b for b in self.bookmarks if b.file_path != file_path]
                span.set_attribute("bookmark.action", "removed")
                self.notify("Bookmark removed")
            else:
                self.bookmarks = list(self.bookmarks) + [
                    Bookmark(file_path=file_path, filename=filename)
                ]
                span.set_attribute("bookmark.action", "added")
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
        with self.telemetry.span("tui.session_new") as span:
            session_id = await self.session_service.create_session()
            self.active_session_id = session_id
            span.set_attribute("session.id", session_id)
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

            with self.telemetry.span("tui.session_save") as span:
                span.set_attribute("session.id", self.active_session_id)
                span.set_attribute("session.bookmark_count", len(self.bookmarks))

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

            with self.telemetry.span("tui.session_load") as span:
                span.set_attribute("session.id", session_id)
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
                span.set_attribute("session.search_history_count", len(self.search_history))
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
        with self.telemetry.span("tui.synthesize") as span:
            span.set_attribute("synthesize.result_count", len(self.results))
            span.set_attribute("synthesize.query", self.query)
            try:
                output = await self.search_service.synthesize(
                    self.query, self.results
                )
                span.set_attribute("synthesize.has_output", output is not None)
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
                    self.telemetry.log.info(
                        f"synthesis completed query={self.query!r} result_count={len(self.results)}"
                    )
                else:
                    self.notify(
                        "Synthesis not available (need 5+ results)",
                        severity="warning",
                    )
            except Exception as e:
                span.record_exception(e)
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
