"""Tests for search result display formatting: score bars, truncation, and Rich output."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from objlib.models import Citation
from objlib.search.formatter import (
    display_detailed_view,
    display_full_document,
    display_no_results,
    display_search_results,
    score_bar,
    truncate_text,
)


# ---------------------------------------------------------------------------
# score_bar tests
# ---------------------------------------------------------------------------


class TestScoreBar:
    def test_score_bar_zero(self):
        assert score_bar(0.0) == "○○○○○○○○○○ 0%"

    def test_score_bar_full(self):
        assert score_bar(1.0) == "━━━━━━━━━━ 100%"

    def test_score_bar_partial(self):
        result = score_bar(0.73)
        assert result == "━━━━━━━○○○ 73%"

    def test_score_bar_custom_width(self):
        result = score_bar(0.5, width=20)
        # 10 filled, 10 empty
        assert result.count("━") == 10
        assert result.count("○") == 10
        assert "50%" in result

    def test_score_bar_clamps_above_one(self):
        result = score_bar(1.5)
        assert result == "━━━━━━━━━━ 100%"

    def test_score_bar_clamps_below_zero(self):
        result = score_bar(-0.5)
        assert result == "○○○○○○○○○○ 0%"

    def test_score_bar_rounding(self):
        # 0.87 * 10 = 8.7, rounds to 9
        result = score_bar(0.87)
        assert result == "━━━━━━━━━○ 87%"

    def test_score_bar_small_width(self):
        result = score_bar(0.5, width=4)
        assert result == "━━○○ 50%"


# ---------------------------------------------------------------------------
# truncate_text tests
# ---------------------------------------------------------------------------


class TestTruncateText:
    def test_truncate_text_short(self):
        """Text under max_len returns unchanged."""
        text = "Hello world"
        assert truncate_text(text, 50) == "Hello world"

    def test_truncate_text_long(self):
        """Text over max_len truncates at word boundary with '...'."""
        text = "The quick brown fox jumps over the lazy dog"
        result = truncate_text(text, 25)
        assert result.endswith("...")
        assert len(result) <= 25
        # Should truncate at a word boundary
        assert result == "The quick brown fox..."

    def test_truncate_text_exact(self):
        """Text at exactly max_len returns unchanged."""
        text = "Exact length"
        assert truncate_text(text, len(text)) == text

    def test_truncate_text_no_spaces(self):
        """Text without spaces hard truncates."""
        text = "abcdefghijklmnopqrstuvwxyz"
        result = truncate_text(text, 10)
        assert result == "abcdefg..."
        assert len(result) == 10

    def test_truncate_text_custom_suffix(self):
        text = "The quick brown fox"
        result = truncate_text(text, 15, suffix="~")
        assert result.endswith("~")
        assert len(result) <= 15

    def test_truncate_text_very_short_max(self):
        """Very short max_len returns truncated suffix."""
        text = "Hello world"
        result = truncate_text(text, 3)
        assert len(result) <= 3


# ---------------------------------------------------------------------------
# display_search_results tests
# ---------------------------------------------------------------------------


def _make_test_console() -> tuple[Console, StringIO]:
    """Create a Console that captures output to a StringIO buffer."""
    buf = StringIO()
    con = Console(file=buf, force_terminal=True, width=100)
    return con, buf


def _make_citation(
    index: int = 1,
    title: str = "Test Document.txt",
    text: str = "This is a test passage with relevant content.",
    confidence: float = 0.87,
    course: str = "OPAR",
    year: int = 2023,
    difficulty: str = "intermediate",
    file_path: str = "/lib/test.txt",
) -> Citation:
    """Create a test Citation with metadata."""
    return Citation(
        index=index,
        title=title,
        uri="files/abc",
        text=text,
        document_name="files/abc123",
        confidence=confidence,
        file_path=file_path,
        metadata={"course": course, "year": year, "difficulty": difficulty},
    )


class TestDisplaySearchResults:
    def test_display_search_results_no_citations(self):
        """With no citations, shows 'No sources cited' message."""
        con, buf = _make_test_console()
        display_search_results(
            "Some response text", [], terminal_width=100, console=con
        )
        output = buf.getvalue()
        assert "No sources cited" in output

    def test_display_search_results_with_citations(self):
        """With citations, shows tier 2 panel (titles/excerpts) and tier 3 table."""
        citations = [
            _make_citation(index=1, title="OPAR Lecture 1.txt", confidence=0.9, course="OPAR"),
            _make_citation(index=2, title="Virtue of Selfishness.txt", confidence=0.75, course="Ethics"),
        ]
        con, buf = _make_test_console()
        display_search_results(
            "Objectivism is a philosophy of rational self-interest.",
            citations,
            terminal_width=100,
            console=con,
        )
        output = buf.getvalue()

        # Tier 1: response text present
        assert "Objectivism is a philosophy" in output

        # Tier 2: citation titles and excerpts
        assert "OPAR Lecture 1.txt" in output
        assert "Virtue of Selfishness.txt" in output
        assert "test passage" in output  # from default text

        # Tier 2: metadata
        assert "OPAR" in output
        assert "Ethics" in output

        # Tier 3: Sources table
        assert "Sources" in output

    def test_display_search_results_respects_limit(self):
        """Only shows up to `limit` citations."""
        citations = [_make_citation(index=i, title=f"Doc{i}.txt") for i in range(1, 6)]
        con, buf = _make_test_console()
        display_search_results(
            "Response text", citations, terminal_width=100, limit=2, console=con
        )
        output = buf.getvalue()
        assert "Doc1.txt" in output
        assert "Doc2.txt" in output
        # Doc3 should NOT be in tier 2 or tier 3
        assert "Doc3.txt" not in output

    def test_display_search_results_score_bars(self):
        """Score bars appear in the output."""
        citations = [_make_citation(confidence=0.87)]
        con, buf = _make_test_console()
        display_search_results("Response", citations, terminal_width=100, console=con)
        output = buf.getvalue()
        assert "87%" in output


# ---------------------------------------------------------------------------
# display_detailed_view tests
# ---------------------------------------------------------------------------


class TestDisplayDetailedView:
    def test_display_detailed_view(self):
        """Verify Panel contains course, year, difficulty, passage text."""
        citation = _make_citation(
            title="OPAR Lecture 5.txt",
            text="The concept of rights is derived from the nature of man.",
            confidence=0.92,
            course="OPAR",
            year=2023,
            difficulty="advanced",
            file_path="/lib/OPAR/OPAR Lecture 5.txt",
        )
        con, buf = _make_test_console()
        display_detailed_view(citation, terminal_width=100, console=con)
        output = buf.getvalue()

        assert "OPAR Lecture 5.txt" in output
        assert "OPAR" in output
        assert "2023" in output
        assert "advanced" in output
        assert "concept of rights" in output
        assert "92%" in output

    def test_display_detailed_view_minimal_metadata(self):
        """Works with minimal metadata (no course, year, etc.)."""
        citation = Citation(
            index=1,
            title="Unknown.txt",
            uri=None,
            text="Some text.",
            document_name=None,
            confidence=0.5,
            metadata={},
        )
        con, buf = _make_test_console()
        display_detailed_view(citation, terminal_width=80, console=con)
        output = buf.getvalue()
        assert "Unknown.txt" in output
        assert "50%" in output


# ---------------------------------------------------------------------------
# display_full_document tests
# ---------------------------------------------------------------------------


class TestDisplayFullDocument:
    def test_display_full_document(self):
        """Shows full content in a panel."""
        con, buf = _make_test_console()
        display_full_document("Test.txt", "Full document content here.", terminal_width=100, console=con)
        output = buf.getvalue()
        assert "Full document content here" in output
        assert "Test.txt" in output

    def test_display_full_document_truncation(self):
        """Long content gets truncated with a note."""
        long_text = "word " * 5000  # 25000 chars
        con, buf = _make_test_console()
        display_full_document("Long.txt", long_text, terminal_width=100, console=con, max_chars=100)
        output = buf.getvalue()
        assert "truncated" in output


# ---------------------------------------------------------------------------
# display_no_results tests
# ---------------------------------------------------------------------------


class TestDisplayNoResults:
    def test_display_no_results(self):
        con, buf = _make_test_console()
        display_no_results(console=con)
        output = buf.getvalue()
        assert "No results found" in output
