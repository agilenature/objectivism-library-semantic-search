"""Search bar widget with reactive Subject-based input and history navigation.

Extends Textual's Input widget with RxPY Subject streams for keystroke
and Enter events. The ObjlibApp assembles the debounce/combine_latest
pipeline from these Subjects in on_mount. Up/down arrow history navigation
is handled locally.
"""

from __future__ import annotations

from reactivex.subject import Subject
from textual import events
from textual.widgets import Input

from objlib.tui.telemetry import get_telemetry


class SearchBar(Input):
    """Search input with reactive Subjects, history, and clear support.

    Keystroke events emit to input_subject. Enter fires to enter_subject.
    The debounce pipeline is assembled by ObjlibApp in on_mount using
    these Subjects. Up/Down arrows navigate search history.
    """

    DEFAULT_CSS = """
    SearchBar {
        dock: top;
        height: 3;
        padding: 0 1;
        border-bottom: solid $primary;
    }
    """

    # Debounce duration is now configured in ObjlibApp.on_mount pipeline assembly
    DEBOUNCE_SECONDS: float = 0.3

    def __init__(self) -> None:
        super().__init__(
            placeholder="Search the library... (Ctrl+F to focus)",
            id="search-bar",
        )
        self._input_subject = Subject()
        self._enter_subject = Subject()
        self._history: list[str] = []
        self._history_index: int = -1

    @property
    def input_subject(self) -> Subject:
        """Observable stream of input values (emits on every keystroke)."""
        return self._input_subject

    @property
    def enter_subject(self) -> Subject:
        """Observable stream of Enter key submissions."""
        return self._enter_subject

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes -- emit to input_subject for pipeline processing."""
        # Only process events from this input (not bubbled from children)
        if event.input is not self:
            return
        query = event.value.strip()
        self._input_subject.on_next(query)

    def on_key(self, event: events.Key) -> None:
        """Handle history navigation and immediate Enter.

        Up arrow: navigate backward through search history.
        Down arrow: navigate forward through search history.
        Enter: emit to enter_subject for immediate search.
        """
        if event.key == "up" and self._history:
            # Navigate backward in history
            if self._history_index == -1:
                self._history_index = len(self._history) - 1
            elif self._history_index > 0:
                self._history_index -= 1
            self.value = self._history[self._history_index]
            get_telemetry().log.info(
                f"history navigate direction=up index={self._history_index} "
                f"query={self.value!r}"
            )
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
            get_telemetry().log.info(
                f"history navigate direction=down index={self._history_index} "
                f"query={self.value!r}"
            )
            event.prevent_default()

        elif event.key == "enter":
            query = self.value.strip()
            if query:
                self._enter_subject.on_next(query)
                if not self._history or self._history[-1] != query:
                    self._history.append(query)
                self._history_index = -1
                get_telemetry().log.info(
                    f"search fired query={query!r} history_size={len(self._history)}"
                )

    def clear_and_reset(self) -> None:
        """Clear the search bar and reset history navigation."""
        self.value = ""
        self._history_index = -1
        get_telemetry().log.info("search bar cleared")
