"""Preview pane widget for document display with highlighting.

PreviewPane extends RichLog to show full document text with keyword
highlighting, citation detail panels, and text-search-based citation
jump. Gracefully degrades when source files are unavailable.
"""

from __future__ import annotations

from textual.widgets import RichLog

from rich.panel import Panel
from rich.text import Text

from objlib.models import Citation
from objlib.tui.telemetry import get_telemetry


class PreviewPane(RichLog):
    """Document preview with highlighting and citation navigation.

    Displays full document text with search term highlighting,
    citation detail panels with metadata, and text-search-based
    scrolling to citation passages.
    """

    DEFAULT_CSS = """
    PreviewPane {
        width: 100%;
        height: 1fr;
        background: $surface;
        scrollbar-gutter: stable;
    }
    """

    def __init__(self) -> None:
        """Initialize an empty preview pane."""
        super().__init__(id="preview", highlight=True, markup=True, wrap=True)
        self._current_content: str | None = None
        self._current_file_path: str | None = None

    def show_document(
        self,
        content: str,
        file_path: str,
        highlight_terms: list[str] | None = None,
    ) -> None:
        """Display full document text with optional keyword highlighting.

        Args:
            content: Full text content of the document.
            file_path: Path to the source file on disk.
            highlight_terms: Optional list of search terms to highlight
                in the document text.
        """
        with get_telemetry().span("widget.preview_document") as span:
            span.set_attribute("preview.file_path", file_path)
            span.set_attribute("preview.content_length", len(content))
            span.set_attribute("preview.highlight_count", len(highlight_terms) if highlight_terms else 0)

            self.clear()
            self._current_content = content
            self._current_file_path = file_path

            text = Text(content)
            if highlight_terms:
                for term in highlight_terms:
                    text.highlight_words(
                        [term], style="bold yellow on dark_green", case_sensitive=False
                    )

            self.write(text)
            get_telemetry().log.info(
                f"preview document file={file_path!r} "
                f"length={len(content)} highlights={len(highlight_terms) if highlight_terms else 0}"
            )

    def show_citation_detail(self, citation: Citation) -> None:
        """Display a citation as a detailed panel with metadata.

        Shows the citation passage in a bordered panel with title,
        and any available metadata (course, year, difficulty) as
        simple lines below the passage text.

        Args:
            citation: Citation to display in detail view.
        """
        self.clear()

        # Build body content
        body = Text()
        body.append(citation.text)

        # Add metadata lines if available
        if citation.metadata:
            body.append("\n\n")
            meta_lines: list[str] = []
            course = citation.metadata.get("course")
            if course:
                meta_lines.append(f"Course: {course}")
            year = citation.metadata.get("year")
            if year:
                meta_lines.append(f"Year: {year}")
            difficulty = citation.metadata.get("difficulty")
            if difficulty:
                meta_lines.append(f"Difficulty: {difficulty}")
            category = citation.metadata.get("category")
            if category:
                meta_lines.append(f"Category: {category}")
            if meta_lines:
                body.append("\n".join(meta_lines), style="dim cyan")

        panel = Panel(
            body,
            title=citation.title,
            border_style="blue",
            padding=(1, 2),
        )
        self.write(panel)
        self._current_content = None
        get_telemetry().log.info(f"preview citation title={citation.title!r}")

    def scroll_to_citation(self, citation_text: str) -> None:
        """Scroll to the location of a citation passage in the document.

        Uses text-search fallback: finds the citation excerpt in the
        current document content and scrolls to the matching line.

        Args:
            citation_text: Passage text to search for in the document.
        """
        if self._current_content is None:
            return

        # Use first 100 chars for fuzzy matching
        search_fragment = citation_text[:100].lower()
        pos = self._current_content.lower().find(search_fragment)

        if pos >= 0:
            line_number = self._current_content[:pos].count("\n")
            self.scroll_to(y=line_number, animate=True)
            get_telemetry().log.info(
                f"preview scroll found=True line={line_number}"
            )
        else:
            self.write(
                Text(
                    "[Citation excerpt not found in document]",
                    style="dim italic",
                )
            )
            get_telemetry().log.info("preview scroll found=False")

    def show_placeholder(self, message: str = "Select a result to preview") -> None:
        """Show a placeholder message when no document is loaded.

        Args:
            message: Placeholder text to display.
        """
        self.clear()
        self.write(Text(message, style="dim italic"))
        self._current_content = None

    def show_unavailable(self) -> None:
        """Show a graceful degradation message for unavailable documents.

        Displayed when the source file cannot be read (e.g., external
        disk not mounted). Metadata and search results remain accessible.
        """
        self.clear()
        self.write(
            Text(
                "Document not available (disk not mounted?)\n\n"
                "Metadata and search results are still accessible.",
                style="dim italic",
            )
        )
        self._current_content = None
        get_telemetry().log.warning(
            f"preview unavailable file={self._current_file_path!r}"
        )
