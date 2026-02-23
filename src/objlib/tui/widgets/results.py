"""Results list widget for displaying search citation cards.

ResultItem renders a single citation as a styled card with metadata.
ResultsList is a scrollable container that manages result items,
selection state, and status messages.
"""

from __future__ import annotations

from textual import events
from textual.containers import VerticalScroll
from textual.widgets import Static

from rich.text import Text

from objlib.models import Citation
from objlib.tui.messages import ResultSelected
from objlib.tui.telemetry import get_telemetry


class ResultItem(Static):
    """A single search result card displaying citation metadata.

    Shows filename, course/difficulty/year metadata (when available),
    and a passage excerpt. Posts ResultSelected on click or Enter.
    """

    DEFAULT_CSS = """
    ResultItem {
        padding: 1 2;
        margin: 0 0 1 0;
        background: $surface;
        border: solid $primary-background;
        height: auto;
    }
    ResultItem:hover {
        background: $primary-background;
    }
    ResultItem.-selected {
        border: solid $accent;
        background: $primary-background-darken-1;
    }
    """

    can_focus = True

    def __init__(
        self,
        citation: Citation,
        result_index: int,
        rank: int | None = None,
        total: int | None = None,
    ) -> None:
        """Initialize a result card from a Citation.

        Args:
            citation: The Citation dataclass with title, text, metadata.
            result_index: Zero-based position in the results list.
            rank: 1-based rank position (chunk index + 1). None to omit.
            total: Total number of citations in the result set. None to omit.
        """
        self.citation = citation
        self.result_index = result_index
        self.rank = rank
        self.total = total

        # Guard: a valid title looks like a filename (has an extension).
        # A raw Gemini file ID (e.g. "l38iajfzqsjq") has no "." — log an
        # error and substitute a safe display title so it never reaches the user.
        display_title = citation.title
        if "." not in citation.title:
            get_telemetry().log.error(
                f"unresolved gemini file id in result index={result_index} "
                f"raw_id={citation.title!r} — enrichment lookup missed this file"
            )
            display_title = f"[Unresolved file #{result_index + 1}]"

        # Build Rich Text display
        display = Text()

        # Line 1: rank + filename (bold)
        if rank is not None and total is not None:
            display.append(f"[{rank} / {total}] ", style="bold cyan")
        display.append(display_title, style="bold")
        display.append("\n")

        # Line 2: metadata summary (course | difficulty | year) if available
        meta_parts: list[str] = []
        if citation.metadata:
            course = citation.metadata.get("course")
            if course:
                meta_parts.append(str(course))
            difficulty = citation.metadata.get("difficulty")
            if difficulty:
                meta_parts.append(str(difficulty))
            year = citation.metadata.get("year")
            if year:
                meta_parts.append(str(year))
        if meta_parts:
            display.append(" | ".join(meta_parts), style="italic cyan")
            display.append("\n")

        # Line 3: passage excerpt (first 150 chars, dimmed)
        excerpt = citation.text[:150].strip()
        if len(citation.text) > 150:
            excerpt += "..."
        display.append(excerpt, style="dim")

        super().__init__(display, id=f"result-{result_index}")

    def on_click(self, event: events.Click) -> None:
        """Post ResultSelected when the card is clicked."""
        event.stop()  # Prevent click from bubbling to parent scroll container
        get_telemetry().log.info(
            f"result item clicked index={self.result_index} title={self.citation.title!r}"
        )
        self.post_message(ResultSelected(index=self.result_index, citation=self.citation))

    def on_key(self, event: events.Key) -> None:
        """Post ResultSelected when Enter is pressed on a focused card."""
        if event.key == "enter":
            get_telemetry().log.info(
                f"result item enter index={self.result_index} title={self.citation.title!r}"
            )
            self.post_message(ResultSelected(index=self.result_index, citation=self.citation))


class ResultsList(VerticalScroll):
    """Scrollable container for search result citation cards.

    Manages a list of ResultItem widgets, selection highlighting,
    and status messages (searching, no results, errors).
    """

    DEFAULT_CSS = """
    ResultsList {
        width: 100%;
        height: 1fr;
    }
    ResultsList .scroll-hint {
        text-align: center;
        color: $text-muted;
        text-style: italic;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        """Initialize an empty results list."""
        super().__init__(id="results-list")

    def update_results(self, citations: list[Citation]) -> None:
        """Replace current results with new citation cards.

        Shows a "N citations retrieved" banner, per-citation rank display,
        and scroll hints when results exceed 3 items.

        Args:
            citations: List of Citation objects to display. Empty list
                shows a 'No results found' message.
        """
        self.remove_children()
        if not citations:
            self.mount(Static("No results found"))
        else:
            total = len(citations)
            self.mount(Static(f"{total} citations retrieved"))
            for i, citation in enumerate(citations):
                self.mount(ResultItem(citation, i, rank=i + 1, total=total))
            if total > 3:
                self.mount(
                    Static(
                        "\u2191/\u2193 to scroll, PgUp/PgDn for pages",
                        classes="scroll-hint",
                    )
                )

    def update_status(self, text: str) -> None:
        """Show a status message, replacing all result cards.

        Used for 'Searching...', 'Error: ...', and other transient states.

        Args:
            text: Status message to display.
        """
        self.remove_children()
        self.mount(Static(text))

    def select_index(self, index: int) -> None:
        """Highlight the result card at the given index.

        Removes -selected class from all items, adds it to the
        target item, and scrolls to make it visible.

        Args:
            index: Zero-based index of the result to select.
        """
        for item in self.query(ResultItem):
            item.remove_class("-selected")

        target = self.query_one(f"#result-{index}", ResultItem)
        target.add_class("-selected")
        target.scroll_visible(animate=True)
