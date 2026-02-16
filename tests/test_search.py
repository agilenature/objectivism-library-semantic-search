"""Tests for the search subpackage: filter builder, citation extraction, enrichment, and API key loading."""

from __future__ import annotations

import json
import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest
import typer

from objlib.config import get_api_key
from objlib.models import Citation
from objlib.search.citations import build_metadata_filter, enrich_citations, extract_citations


# ---------------------------------------------------------------------------
# build_metadata_filter tests
# ---------------------------------------------------------------------------


class TestBuildMetadataFilter:
    def test_single_string(self):
        result = build_metadata_filter(["course:OPAR"])
        assert result == 'course="OPAR"'

    def test_single_numeric(self):
        result = build_metadata_filter(["year:2023"])
        assert result == "year=2023"

    def test_combined(self):
        result = build_metadata_filter(["course:OPAR", "year:2023"])
        assert result == 'course="OPAR" AND year=2023'

    def test_comparison_gte(self):
        result = build_metadata_filter(["year:>=2020"])
        assert result == "year>=2020"

    def test_comparison_gt(self):
        result = build_metadata_filter(["year:>2020"])
        assert result == "year>2020"

    def test_comparison_lt(self):
        result = build_metadata_filter(["year:<2025"])
        assert result == "year<2025"

    def test_comparison_lte(self):
        result = build_metadata_filter(["year:<=2025"])
        assert result == "year<=2025"

    def test_empty_list(self):
        result = build_metadata_filter([])
        assert result is None

    def test_invalid_field(self):
        with pytest.raises(typer.BadParameter, match="Unknown filter field 'bogus'"):
            build_metadata_filter(["bogus:value"])


# ---------------------------------------------------------------------------
# extract_citations tests
# ---------------------------------------------------------------------------


def _make_chunk(title="test.txt", uri="files/abc", text="Some passage", document_name="files/abc123"):
    """Create a mock GroundingChunk with retrieved_context."""
    ctx = MagicMock()
    ctx.title = title
    ctx.uri = uri
    ctx.text = text
    ctx.document_name = document_name
    chunk = MagicMock()
    chunk.retrieved_context = ctx
    return chunk


def _make_support(indices, scores):
    """Create a mock GroundingSupport."""
    support = MagicMock()
    support.grounding_chunk_indices = indices
    support.confidence_scores = scores
    return support


class TestExtractCitations:
    def test_none_metadata(self):
        assert extract_citations(None) == []

    def test_no_chunks(self):
        metadata = MagicMock()
        metadata.grounding_chunks = None
        assert extract_citations(metadata) == []

    def test_empty_chunks(self):
        metadata = MagicMock()
        metadata.grounding_chunks = []
        assert extract_citations(metadata) == []

    def test_with_chunks_and_supports(self):
        chunk1 = _make_chunk(title="file1.txt", text="Passage 1")
        chunk2 = _make_chunk(title="file2.txt", text="Passage 2")

        # Support 1 references chunk 0 with 0.9, chunk 1 with 0.7
        support1 = _make_support([0, 1], [0.9, 0.7])
        # Support 2 references chunk 0 with 0.8
        support2 = _make_support([0], [0.8])

        metadata = MagicMock()
        metadata.grounding_chunks = [chunk1, chunk2]
        metadata.grounding_supports = [support1, support2]

        citations = extract_citations(metadata)

        assert len(citations) == 2

        # Chunk 0: avg(0.9, 0.8) = 0.85
        assert citations[0].index == 1
        assert citations[0].title == "file1.txt"
        assert citations[0].text == "Passage 1"
        assert abs(citations[0].confidence - 0.85) < 0.001

        # Chunk 1: avg(0.7) = 0.7
        assert citations[1].index == 2
        assert citations[1].title == "file2.txt"
        assert abs(citations[1].confidence - 0.7) < 0.001

    def test_chunk_without_retrieved_context(self):
        chunk = MagicMock()
        chunk.retrieved_context = None
        metadata = MagicMock()
        metadata.grounding_chunks = [chunk]
        metadata.grounding_supports = []

        citations = extract_citations(metadata)
        assert citations == []

    def test_no_supports(self):
        """Chunks without any supports should get confidence 0.0."""
        chunk = _make_chunk(title="orphan.txt")
        metadata = MagicMock()
        metadata.grounding_chunks = [chunk]
        metadata.grounding_supports = None

        citations = extract_citations(metadata)
        assert len(citations) == 1
        assert citations[0].confidence == 0.0


# ---------------------------------------------------------------------------
# enrich_citations tests
# ---------------------------------------------------------------------------


def _make_test_db():
    """Create an in-memory SQLite DB with test data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE files (
            file_path TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            metadata_json TEXT,
            metadata_quality TEXT DEFAULT 'unknown',
            status TEXT NOT NULL DEFAULT 'pending'
        )
    """)
    conn.execute(
        "INSERT INTO files (file_path, filename, content_hash, file_size, metadata_json, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "/lib/OPAR-Lecture-1.txt",
            "OPAR-Lecture-1.txt",
            "abc123",
            1024,
            json.dumps({"course": "OPAR", "year": 2023, "difficulty": "advanced"}),
            "uploaded",
        ),
    )
    conn.commit()
    return conn


class _FakeDB:
    """Minimal Database mock that uses an in-memory connection."""

    def __init__(self, conn):
        self.conn = conn

    def get_file_metadata_by_filenames(self, filenames):
        if not filenames:
            return {}
        placeholders = ",".join("?" * len(filenames))
        rows = self.conn.execute(
            f"SELECT filename, file_path, metadata_json FROM files "
            f"WHERE filename IN ({placeholders}) AND status != 'LOCAL_DELETE'",
            filenames,
        ).fetchall()
        result = {}
        for row in rows:
            meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            result[row["filename"]] = {
                "file_path": row["file_path"],
                "metadata": meta,
            }
        return result


class TestEnrichCitations:
    def test_matches_filename(self):
        conn = _make_test_db()
        db = _FakeDB(conn)
        citation = Citation(
            index=1,
            title="OPAR-Lecture-1.txt",
            uri="files/abc",
            text="Some text",
            document_name="files/abc123",
            confidence=0.9,
        )
        enrich_citations([citation], db)

        assert citation.file_path == "/lib/OPAR-Lecture-1.txt"
        assert citation.metadata is not None
        assert citation.metadata["course"] == "OPAR"
        assert citation.metadata["year"] == 2023
        conn.close()

    def test_unmatched(self):
        conn = _make_test_db()
        db = _FakeDB(conn)
        citation = Citation(
            index=1,
            title="nonexistent.txt",
            uri="files/xyz",
            text="Text",
            document_name="files/xyz456",
            confidence=0.5,
        )
        enrich_citations([citation], db)

        assert citation.file_path is None
        assert citation.metadata is None
        conn.close()

    def test_empty_citations(self):
        conn = _make_test_db()
        db = _FakeDB(conn)
        result = enrich_citations([], db)
        assert result == []
        conn.close()


# ---------------------------------------------------------------------------
# get_api_key tests
# ---------------------------------------------------------------------------


class TestGetApiKey:
    @patch("objlib.config.keyring.get_password", return_value="key-from-keyring")
    def test_from_keyring(self, mock_keyring):
        key = get_api_key()
        assert key == "key-from-keyring"
        mock_keyring.assert_called_once_with("objlib-gemini", "api_key")

    @patch("objlib.config.keyring.get_password", return_value=None)
    def test_from_env_var(self, mock_keyring):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "key-from-env"}):
            key = get_api_key()
            assert key == "key-from-env"

    @patch("objlib.config.keyring.get_password", return_value=None)
    def test_neither_raises(self, mock_keyring):
        with patch.dict(os.environ, {}, clear=True):
            # Ensure GEMINI_API_KEY is not set
            env = os.environ.copy()
            env.pop("GEMINI_API_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(RuntimeError, match="Gemini API key not found"):
                    get_api_key()
