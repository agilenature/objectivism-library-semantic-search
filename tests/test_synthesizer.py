"""Tests for synthesis pipeline: MMR diversity, citation validation,
metadata filters, citation extraction, enrichment, and normalization.

Pure logic functions are tested without mocking. API-dependent functions
use mocked Gemini client and in-memory database.
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from objlib.models import Citation
from objlib.search.citations import (
    build_metadata_filter,
    enrich_citations,
    extract_citations,
)
from objlib.search.models import Claim, CitationRef, SynthesisOutput
from objlib.search.synthesizer import (
    _normalize,
    apply_mmr_diversity,
    validate_citations,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_citation(
    index: int = 1,
    title: str = "test.txt",
    text: str = "Test passage content.",
    file_path: str | None = None,
    course: str | None = None,
    difficulty: str | None = None,
) -> Citation:
    """Build a Citation with optional metadata."""
    metadata = {}
    if course:
        metadata["course"] = course
    if difficulty:
        metadata["difficulty"] = difficulty
    return Citation(
        index=index,
        title=title,
        uri=None,
        text=text,
        document_name=None,
        confidence=0.8,
        file_path=file_path or f"/library/{title}",
        metadata=metadata if metadata else None,
    )


def _make_claim(
    claim_text: str = "Objectivism holds that reality exists.",
    quote: str = "reality exists independently of consciousness",
    passage_id: str = "0",
    file_id: str = "test.txt",
) -> Claim:
    """Build a Claim with a CitationRef."""
    return Claim(
        claim_text=claim_text,
        citation=CitationRef(
            file_id=file_id,
            passage_id=passage_id,
            quote=quote,
        ),
    )


# ---------------------------------------------------------------------------
# Citation Validation (pure logic)
# ---------------------------------------------------------------------------

class TestValidateCitationsExact:
    """Tests for exact-match citation validation."""

    def test_validate_citations_exact_match(self):
        """Verbatim quote found in passage text passes validation."""
        passage_texts = {"0": "Reality exists independently of consciousness and perception."}
        claims = [_make_claim(quote="Reality exists independently of consciousness")]

        valid, errors = validate_citations(claims, passage_texts)
        assert len(valid) == 1
        assert errors == []

    def test_validate_citations_whitespace_normalization(self):
        """Quote with extra whitespace matches passage with normal whitespace."""
        passage_texts = {"0": "Reality exists independently of consciousness."}
        claims = [_make_claim(quote="Reality   exists   independently   of   consciousness")]

        valid, errors = validate_citations(claims, passage_texts)
        assert len(valid) == 1
        assert errors == []

    def test_validate_citations_case_insensitive(self):
        """Quote differing only in case passes validation."""
        passage_texts = {"0": "Reality Exists Independently of Consciousness."}
        claims = [_make_claim(quote="reality exists independently of consciousness")]

        valid, errors = validate_citations(claims, passage_texts)
        assert len(valid) == 1
        assert errors == []

    def test_validate_citations_fabricated_quote(self):
        """Quote not found in any passage fails validation."""
        passage_texts = {"0": "Reason is man's only means of gaining knowledge."}
        claims = [_make_claim(quote="Feelings are the primary tool of cognition")]

        valid, errors = validate_citations(claims, passage_texts)
        assert len(valid) == 0
        assert len(errors) == 1
        assert "not found" in errors[0].lower() or "Quote" in errors[0]

    def test_validate_citations_empty_claims(self):
        """Empty claims list returns empty valid and errors."""
        passage_texts = {"0": "Some passage text here."}

        valid, errors = validate_citations([], passage_texts)
        assert valid == []
        assert errors == []

    def test_validate_citations_missing_passage_id(self):
        """Claim referencing nonexistent passage_id produces error."""
        passage_texts = {"0": "Some passage text here."}
        claims = [_make_claim(passage_id="99")]

        valid, errors = validate_citations(claims, passage_texts)
        assert len(valid) == 0
        assert len(errors) == 1
        assert "not found" in errors[0].lower()


# ---------------------------------------------------------------------------
# MMR Diversity (pure logic)
# ---------------------------------------------------------------------------

class TestMMRDiversity:
    """Tests for Maximal Marginal Relevance diversity filtering."""

    def test_mmr_removes_same_file_duplicates(self):
        """MMR limits citations per file (default max_per_file=2)."""
        citations = [
            _make_citation(index=1, title="a.txt", file_path="/lib/a.txt", text="Passage one from a."),
            _make_citation(index=2, title="a.txt", file_path="/lib/a.txt", text="Passage two from a."),
            _make_citation(index=3, title="a.txt", file_path="/lib/a.txt", text="Passage three from a."),
            _make_citation(index=4, title="b.txt", file_path="/lib/b.txt", text="Passage from b."),
        ]

        result = apply_mmr_diversity(citations, max_per_file=2)
        a_count = sum(1 for c in result if c.file_path == "/lib/a.txt")
        assert a_count <= 2, f"Expected max 2 from a.txt, got {a_count}"
        assert len(result) == 3  # 2 from a + 1 from b

    def test_mmr_preserves_different_files(self):
        """Citations from 4 different files are all preserved."""
        citations = [
            _make_citation(index=1, title="a.txt", file_path="/lib/a.txt", text="Passage a."),
            _make_citation(index=2, title="b.txt", file_path="/lib/b.txt", text="Passage b."),
            _make_citation(index=3, title="c.txt", file_path="/lib/c.txt", text="Passage c."),
            _make_citation(index=4, title="d.txt", file_path="/lib/d.txt", text="Passage d."),
        ]

        result = apply_mmr_diversity(citations)
        assert len(result) == 4

    def test_mmr_prefers_unseen_courses(self):
        """First pass prefers citations from unseen courses."""
        citations = [
            _make_citation(index=1, title="a.txt", file_path="/lib/a.txt", course="OPAR", text="Passage a."),
            _make_citation(index=2, title="b.txt", file_path="/lib/b.txt", course="OPAR", text="Passage b."),
            _make_citation(index=3, title="c.txt", file_path="/lib/c.txt", course="Ethics", text="Passage c."),
            _make_citation(index=4, title="d.txt", file_path="/lib/d.txt", course="HOP", text="Passage d."),
        ]

        result = apply_mmr_diversity(citations, max_per_file=1, max_results=3)
        courses_in_result = [c.metadata.get("course") for c in result if c.metadata]
        # Should prefer unique courses: OPAR, Ethics, HOP (not 2 from OPAR)
        assert len(set(courses_in_result)) == 3

    def test_mmr_empty_citations(self):
        """Empty input returns empty output."""
        result = apply_mmr_diversity([])
        assert result == []

    def test_mmr_max_results_limit(self):
        """max_results caps the output size."""
        citations = [
            _make_citation(index=i, title=f"f{i}.txt", file_path=f"/lib/f{i}.txt", text=f"Passage {i}.")
            for i in range(20)
        ]

        result = apply_mmr_diversity(citations, max_results=5)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Metadata Filter Syntax
# ---------------------------------------------------------------------------

class TestBuildMetadataFilter:
    """Tests for AIP-160 metadata filter string generation."""

    def test_build_metadata_filter_single_string_field(self):
        """Single string field generates correct AIP-160 filter."""
        result = build_metadata_filter(["course:OPAR"])
        assert result == 'course="OPAR"'

    def test_build_metadata_filter_multiple_fields(self):
        """Multiple fields joined with AND."""
        result = build_metadata_filter(["course:OPAR", "difficulty:introductory"])
        assert "AND" in result
        assert 'course="OPAR"' in result
        assert 'difficulty="introductory"' in result

    def test_build_metadata_filter_numeric_field(self):
        """Numeric field generates numeric equality (no quotes)."""
        result = build_metadata_filter(["year:2023"])
        assert result == "year=2023"

    def test_build_metadata_filter_numeric_comparison(self):
        """Numeric field with comparison operator."""
        result = build_metadata_filter(["year:>=2020"])
        assert result == "year>=2020"

    def test_build_metadata_filter_less_than(self):
        """Less-than operator generates correct syntax."""
        result = build_metadata_filter(["week:<10"])
        assert result == "week<10"

    def test_build_metadata_filter_empty(self):
        """Empty list returns None."""
        result = build_metadata_filter([])
        assert result is None

    def test_build_metadata_filter_unknown_field_raises(self):
        """Unknown field name raises BadParameter."""
        import typer

        with pytest.raises(typer.BadParameter, match="Unknown filter field"):
            build_metadata_filter(["bogus:value"])


# ---------------------------------------------------------------------------
# Citation Extraction (mocked grounding metadata)
# ---------------------------------------------------------------------------

class TestExtractCitations:
    """Tests for extracting citations from Gemini grounding metadata."""

    def test_extract_citations_from_grounding(self):
        """Citations extracted with correct file references and text."""
        chunk1 = SimpleNamespace(
            retrieved_context=SimpleNamespace(
                title="OPAR - Lesson 01.txt",
                uri="gs://bucket/file1",
                text="Existence exists as an axiom.",
                document_name="corpora/abc/documents/doc1",
            )
        )
        chunk2 = SimpleNamespace(
            retrieved_context=SimpleNamespace(
                title="Ethics - Lesson 02.txt",
                uri="gs://bucket/file2",
                text="Man must choose his values and actions by reason.",
                document_name="corpora/abc/documents/doc2",
            )
        )

        grounding_metadata = SimpleNamespace(
            grounding_chunks=[chunk1, chunk2],
            grounding_supports=[
                SimpleNamespace(
                    grounding_chunk_indices=[0, 1],
                    confidence_scores=[0.9, 0.85],
                )
            ],
        )

        citations = extract_citations(grounding_metadata)
        assert len(citations) == 2
        assert citations[0].title == "OPAR - Lesson 01.txt"
        assert citations[0].text == "Existence exists as an axiom."
        assert citations[0].confidence == 0.9
        assert citations[1].title == "Ethics - Lesson 02.txt"
        assert citations[1].confidence == 0.85

    def test_extract_citations_none_metadata(self):
        """None grounding metadata returns empty list."""
        assert extract_citations(None) == []

    def test_extract_citations_no_chunks(self):
        """Grounding metadata with no chunks returns empty list."""
        gm = SimpleNamespace(grounding_chunks=None)
        assert extract_citations(gm) == []

    def test_extract_citations_no_confidence(self):
        """Citations without confidence scores default to 0.0."""
        chunk = SimpleNamespace(
            retrieved_context=SimpleNamespace(
                title="test.txt",
                uri=None,
                text="Some text content here.",
                document_name=None,
            )
        )
        gm = SimpleNamespace(
            grounding_chunks=[chunk],
            grounding_supports=[],
        )

        citations = extract_citations(gm)
        assert len(citations) == 1
        assert citations[0].confidence == 0.0


# ---------------------------------------------------------------------------
# Citation Enrichment (needs in-memory DB)
# ---------------------------------------------------------------------------

class TestEnrichCitations:
    """Tests for enriching citations with SQLite metadata."""

    def test_enrich_citations_maps_gemini_ids(self, in_memory_db):
        """Citations with Gemini file IDs get enriched via ID lookup."""
        # Insert a file with gemini_file_id
        from objlib.models import FileRecord
        record = FileRecord(
            file_path="/lib/Courses/OPAR/OPAR - Lesson 01.txt",
            content_hash="abc123",
            filename="OPAR - Lesson 01.txt",
            file_size=5000,
            metadata_json=json.dumps({"course": "OPAR", "difficulty": "introductory"}),
        )
        in_memory_db.upsert_file(record)
        # Set gemini_file_id
        in_memory_db.conn.execute(
            "UPDATE files SET gemini_file_id = ? WHERE file_path = ?",
            ("files/e0x3xq9wtglq", "/lib/Courses/OPAR/OPAR - Lesson 01.txt"),
        )
        in_memory_db.conn.commit()

        # Citation has Gemini ID as title (not display_name)
        citation = Citation(
            index=1,
            title="e0x3xq9wtglq",
            uri=None,
            text="Existence exists.",
            document_name=None,
            confidence=0.9,
        )

        result = enrich_citations([citation], in_memory_db)
        assert len(result) == 1
        assert result[0].file_path == "/lib/Courses/OPAR/OPAR - Lesson 01.txt"
        assert result[0].metadata["course"] == "OPAR"
        # Title should be updated to actual filename
        assert result[0].title == "OPAR - Lesson 01.txt"

    def test_enrich_citations_fallback_to_filename(self, in_memory_db):
        """Citation with display_name as title uses filename lookup."""
        from objlib.models import FileRecord
        record = FileRecord(
            file_path="/lib/Courses/OPAR/OPAR - Lesson 02.txt",
            content_hash="def456",
            filename="OPAR - Lesson 02.txt",
            file_size=6000,
            metadata_json=json.dumps({"course": "OPAR", "difficulty": "intermediate"}),
        )
        in_memory_db.upsert_file(record)

        citation = Citation(
            index=1,
            title="OPAR - Lesson 02.txt",
            uri=None,
            text="Reason is man's basic means of survival.",
            document_name=None,
            confidence=0.8,
        )

        result = enrich_citations([citation], in_memory_db)
        assert len(result) == 1
        assert result[0].file_path == "/lib/Courses/OPAR/OPAR - Lesson 02.txt"
        assert result[0].metadata["difficulty"] == "intermediate"

    def test_enrich_citations_empty(self, in_memory_db):
        """Empty citations list returns empty."""
        result = enrich_citations([], in_memory_db)
        assert result == []


# ---------------------------------------------------------------------------
# Normalization (pure logic)
# ---------------------------------------------------------------------------

class TestNormalize:
    """Tests for text normalization helper."""

    def test_normalize_collapses_whitespace(self):
        """Multiple spaces, tabs, newlines collapse to single space."""
        assert _normalize("hello   world") == "hello world"
        assert _normalize("hello\t\tworld") == "hello world"
        assert _normalize("hello\n\nworld") == "hello world"
        assert _normalize("  leading  and  trailing  ") == "leading and trailing"

    def test_normalize_lowercases(self):
        """Mixed case text becomes all lowercase."""
        assert _normalize("Hello World") == "hello world"
        assert _normalize("SHOUTING TEXT") == "shouting text"

    def test_normalize_combined(self):
        """Whitespace collapsing and lowercasing applied together."""
        assert _normalize("  Reality   EXISTS  ") == "reality exists"
