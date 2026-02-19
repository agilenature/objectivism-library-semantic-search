"""Objectivism Library TUI Application.

Main Textual App subclass with three-pane layout, centralized reactive
state, key bindings, and message handlers. Pane widgets (Wave 2) will
replace the placeholder Static widgets in compose().
"""

from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Static

from objlib.tui.state import FilterSet


class ObjlibApp(App):
    """Objectivism Library interactive terminal application.

    Three-pane layout: navigation tree (left), search results (center),
    content preview (right). Responsive breakpoints adjust layout for
    different terminal widths.
    """

    TITLE = "Objectivism Library"
    SUB_TITLE = "Semantic Search & Browse"

    CSS = """
    #search-bar {
        dock: top;
        height: 3;
        padding: 0 1;
    }

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
        self._search_timer = None

    def compose(self) -> ComposeResult:
        """Compose the three-pane layout with placeholder widgets.

        Wave 2 plans will replace Static placeholders with full
        NavigationTree, ResultsList, and PreviewPane widgets.
        """
        yield Header(show_clock=True)
        yield Input(placeholder="Search the library... (Ctrl+F)", id="search-bar")
        with Horizontal(id="main"):
            yield Static("Navigation", id="nav-pane")
            yield Static("Results", id="results-pane")
            yield Static("Preview", id="preview-pane")
        yield Static(
            "Ready | Ctrl+P: Commands | Tab: Switch Pane",
            id="status-bar",
        )
        yield Footer()

    def on_resize(self) -> None:
        """Adjust layout classes based on terminal width."""
        width = self.size.width
        self.remove_class("layout-medium", "layout-narrow")
        if width < 80:
            self.add_class("layout-narrow")
        elif width < 140:
            self.add_class("layout-medium")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes with 300ms debounce."""
        if event.input.id != "search-bar":
            return

        # Cancel previous debounce timer
        if self._search_timer is not None:
            self._search_timer.stop()

        query = event.value.strip()
        if not query:
            self.query = ""
            self.results = []
            return

        # Set 300ms debounce timer
        self._search_timer = self.set_timer(
            0.3,
            lambda: self._fire_search(query),
        )

    def _fire_search(self, query: str) -> None:
        """Initiate search after debounce expires."""
        self.query = query
        self._run_search(query)

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
            result = await self.search_service.search(query)
            if result is not None:
                self.results = result.citations if hasattr(result, "citations") else []
            else:
                self.results = []
        except Exception:
            self.results = []
        finally:
            self.is_searching = False

    def action_focus_search(self) -> None:
        """Focus the search input bar."""
        search_input = self.query_one("#search-bar", Input)
        search_input.focus()

    def action_toggle_nav(self) -> None:
        """Toggle navigation pane visibility."""
        nav = self.query_one("#nav-pane")
        nav.toggle_class("hidden")

    def action_clear_search(self) -> None:
        """Clear search input and results."""
        search_input = self.query_one("#search-bar", Input)
        search_input.value = ""
        self.query = ""
        self.results = []
        self.selected_index = None

    def action_save_session(self) -> None:
        """Save current session state."""
        if self.session_service is None:
            return
        # Session save implementation will be added in Wave 3
