"""Search bar widget with debounced input and history navigation.

Extends Textual's Input widget with 300ms debounce to avoid firing
a search on every keystroke, up/down arrow history navigation, and
Enter to fire immediately. Posts SearchRequested messages for the
App to handle.
"""

from __future__ import annotations

from textual import events
from textual.widgets import Input

from objlib.tui.messages import SearchRequested


class SearchBar(Input):
    """Search input with debounce, history, and clear support.

    Typing triggers a 300ms debounce before posting SearchRequested.
    Enter fires immediately. Up/Down arrows navigate search history.
    Empty input posts SearchRequested(query="") to clear results.

    The widget manages its own debounce timer and history state.
    """

    DEFAULT_CSS = """
    SearchBar {
        dock: top;
        height: 3;
        padding: 0 1;
        border-bottom: solid $primary;
    }
    """

    DEBOUNCE_SECONDS: float = 0.3

    def __init__(self) -> None:
        super().__init__(
            placeholder="Search the library... (Ctrl+F to focus)",
            id="search-bar",
        )
        self._debounce_timer = None
        self._history: list[str] = []
        self._history_index: int = -1

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes with debounce.

        Cancels any pending debounce timer and starts a new one.
        Empty input fires immediately to clear results.
        """
        # Only process events from this input (not bubbled from children)
        if event.input is not self:
            return

        # Cancel previous debounce timer
        if self._debounce_timer is not None:
            self._debounce_timer.stop()
            self._debounce_timer = None

        query = event.value.strip()

        if not query:
            # Empty query: fire immediately to clear results
            self.post_message(SearchRequested(query=""))
            return

        # Start debounce timer
        self._debounce_timer = self.set_timer(
            self.DEBOUNCE_SECONDS,
            lambda: self._fire_search(query),
        )

    def _fire_search(self, query: str) -> None:
        """Post SearchRequested and record in history."""
        self._debounce_timer = None
        self.post_message(SearchRequested(query=query))

        # Add to history if different from last entry
        if not self._history or self._history[-1] != query:
            self._history.append(query)

        # Reset history navigation position
        self._history_index = -1

    def on_key(self, event: events.Key) -> None:
        """Handle history navigation and immediate Enter.

        Up arrow: navigate backward through search history.
        Down arrow: navigate forward through search history.
        Enter: cancel debounce and fire search immediately.
        """
        if event.key == "up" and self._history:
            # Navigate backward in history
            if self._history_index == -1:
                self._history_index = len(self._history) - 1
            elif self._history_index > 0:
                self._history_index -= 1
            self.value = self._history[self._history_index]
            event.prevent_default()

        elif event.key == "down" and self._history_index >= 0:
            # Navigate forward in history
            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                self.value = self._history[self._history_index]
            else:
                # Past the end: clear to empty
                self._history_index = -1
                self.value = ""
            event.prevent_default()

        elif event.key == "enter":
            # Fire immediately, bypassing debounce
            if self._debounce_timer is not None:
                self._debounce_timer.stop()
                self._debounce_timer = None

            query = self.value.strip()
            if query:
                self._fire_search(query)

    def clear_and_reset(self) -> None:
        """Clear the search bar and reset history navigation."""
        self.value = ""
        self._history_index = -1
        self.post_message(SearchRequested(query=""))
