"""Rich display formatting for search results and document views.

Provides the three-tier citation display (inline markers, details panel,
source table), score bar visualization, compact result lists, and
detailed/full document views. All output adapts to terminal width.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from objlib.models import Citation


def score_bar(score: float, width: int = 10) -> str:
    """Render a visual relevance bar from a 0.0-1.0 score.

    Args:
        score: Confidence/relevance score between 0.0 and 1.0.
        width: Total number of bar characters (filled + empty).

    Returns:
        Formatted string like ``"━━━━━━━━○○ 87%"``.
    """
    score = max(0.0, min(1.0, score))  # clamp
    filled = round(score * width)
    empty = width - filled
    return f"{'━' * filled}{'○' * empty} {int(score * 100)}%"


def truncate_text(text: str, max_len: int, suffix: str = "...") -> str:
    """Truncate text at a word boundary.

    If ``len(text) <= max_len``, returns text unchanged.
    Otherwise, truncates at the last space before ``max_len - len(suffix)``
    and appends the suffix.

    Args:
        text: Input text to potentially truncate.
        max_len: Maximum allowed length of the result.
        suffix: String to append when truncating.

    Returns:
        Original or truncated text.
    """
    if len(text) <= max_len:
        return text

    cutoff = max_len - len(suffix)
    if cutoff <= 0:
        return suffix[:max_len]

    # Find last space before cutoff
    space_idx = text.rfind(" ", 0, cutoff)
    if space_idx > 0:
        return text[:space_idx] + suffix
    # No space found -- hard truncate
    return text[:cutoff] + suffix


def display_search_results(
    response_text: str,
    citations: list[Citation],
    terminal_width: int,
    limit: int = 10,
    console: Console | None = None,
) -> None:
    """Display search results with three-tier citation formatting.

    **Tier 1:** Response text with inline ``[N]`` citation markers.
    **Tier 2:** Citation details panel with excerpts and metadata.
    **Tier 3:** Source listing table with score bars.

    Args:
        response_text: Gemini's generated response text.
        citations: List of enriched Citation objects.
        terminal_width: Current terminal width for adaptive layout.
        limit: Maximum citations to display.
        console: Optional Console for testing (defaults to module console).
    """
    con = console or Console()

    if not citations:
        # Tier 1: Show response even without citations
        con.print()
        con.print(Panel(response_text, title="Answer", border_style="cyan"))
        con.print("[dim]No sources cited.[/dim]")
        return

    display_citations = citations[:limit]

    # --- Tier 1: Response with inline citation markers ---
    # Append citation indices to response text. Full inline insertion
    # would require segment offsets from grounding_supports, which are
    # not always available. Instead, add a reference note after the text.
    refs = " ".join(f"[{c.index}]" for c in display_citations)
    annotated = f"{response_text}\n\n[dim]Sources: {refs}[/dim]"
    con.print()
    con.print(Panel(annotated, title="Answer", border_style="cyan"))

    # --- Tier 2: Citation details panel ---
    con.print()
    excerpt_max = min(150, terminal_width - 20)

    for cite in display_citations:
        meta = cite.metadata or {}
        course = meta.get("course", "")
        year = meta.get("year", "")
        difficulty = meta.get("difficulty", "")

        # Title line
        con.print(
            f"  [yellow]\\[{cite.index}][/yellow] "
            f"[bold]\"{cite.title}\"[/bold]"
        )

        # Metadata line
        meta_parts = []
        if course:
            meta_parts.append(f"Course: {course}")
        if year:
            meta_parts.append(f"Year: {year}")
        if difficulty:
            meta_parts.append(f"Difficulty: {difficulty}")
        if meta_parts:
            con.print(f"      [dim]{' | '.join(meta_parts)}[/dim]")

        # Excerpt
        if cite.text:
            excerpt = truncate_text(cite.text, excerpt_max)
            con.print(f'      [dim]"{excerpt}"[/dim]')

        con.print()

    # --- Tier 3: Source listing table ---
    table = Table(title="Sources", show_header=True, expand=False)
    table.add_column("Ref", style="yellow", justify="center", width=5)
    table.add_column("File", style="cyan", no_wrap=True, max_width=max(30, terminal_width - 50))
    table.add_column("Course", style="green")
    table.add_column("Year", justify="right")

    for cite in display_citations:
        meta = cite.metadata or {}
        file_display = cite.title or "(unknown)"
        # Truncate file column for very long names
        if len(file_display) > terminal_width - 50:
            file_display = truncate_text(file_display, terminal_width - 50)

        table.add_row(
            f"[{cite.index}]",
            file_display,
            str(meta.get("course", "")),
            str(meta.get("year", "")),
        )

    con.print(table)


def display_detailed_view(
    citation: Citation,
    terminal_width: int,
    console: Console | None = None,
) -> None:
    """Display a detailed metadata panel for a single document.

    Shows all available metadata fields and the full passage text
    (not truncated) inside a Rich Panel.

    Args:
        citation: Citation object with metadata.
        terminal_width: Current terminal width for adaptive layout.
        console: Optional Console for testing.
    """
    con = console or Console()
    meta = citation.metadata or {}

    lines = []

    if citation.file_path:
        lines.append(f"[bold]File:[/bold]       {citation.file_path}")
    elif citation.title:
        lines.append(f"[bold]File:[/bold]       {citation.title}")

    course = meta.get("course", "")
    if course:
        lines.append(f"[bold]Course:[/bold]     {course}")

    year = meta.get("year", "")
    quarter = meta.get("quarter", "")
    year_line = ""
    if year:
        year_line = f"[bold]Year:[/bold]       {year}"
        if quarter:
            year_line += f" | Quarter: {quarter}"
        lines.append(year_line)
    elif quarter:
        lines.append(f"[bold]Quarter:[/bold]    {quarter}")

    difficulty = meta.get("difficulty", "")
    if difficulty:
        lines.append(f"[bold]Difficulty:[/bold] {difficulty}")

    # Additional metadata
    for key in sorted(meta.keys()):
        if key not in {"course", "year", "quarter", "difficulty", "quality_score"}:
            lines.append(f"[bold]{key.title()}:[/bold]  {meta[key]}")

    quality_score = meta.get("quality_score")
    if quality_score is not None:
        lines.append(f"[bold]Quality:[/bold]    {quality_score}")

    lines.append(f"[bold]Relevance:[/bold] {score_bar(citation.confidence)}")

    # Separator and passage text
    lines.append("─" * min(60, terminal_width - 10))
    if citation.text:
        lines.append(citation.text)
    else:
        lines.append("[dim]No passage text available.[/dim]")

    content = "\n".join(lines)
    title = citation.title or "Document"

    con.print()
    con.print(Panel(content, title=title, border_style="green", width=min(terminal_width, 100)))


def display_full_document(
    title: str,
    content: str,
    terminal_width: int,
    console: Console | None = None,
    max_chars: int = 10000,
) -> None:
    """Display the full document text in a panel.

    Args:
        title: Document title for the panel header.
        content: Full document text.
        terminal_width: Current terminal width.
        console: Optional Console for testing.
        max_chars: Maximum characters to display before truncation.
    """
    con = console or Console()

    if len(content) > max_chars:
        display_text = content[:max_chars] + f"\n\n[dim]... truncated ({len(content):,} chars total, showing first {max_chars:,})[/dim]"
    else:
        display_text = content

    con.print()
    con.print(Panel(display_text, title=f"Full Document: {title}", border_style="blue", width=min(terminal_width, 120)))


def display_no_results(console: Console | None = None) -> None:
    """Display a message when no results are found.

    Args:
        console: Optional Console for testing.
    """
    con = console or Console()
    con.print("[dim]No results found. Try a broader query.[/dim]")
