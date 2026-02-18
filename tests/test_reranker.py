"""Tests for LLM reranker with difficulty-aware ordering.

Verifies passage scoring via mocked Gemini client, difficulty bucket
ordering for learn/research modes, missing difficulty defaults, and
window-size mechanics.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from objlib.models import Citation
from objlib.search.models import RankedPassage, RankedResults
from objlib.search.reranker import (
    apply_difficulty_ordering,
    rerank_passages,
)


def _make_citation(
    index: int = 1,
    title: str = "test.txt",
    text: str = "Test passage content.",
    difficulty: str | None = None,
    course: str | None = None,
    file_path: str | None = None,
) -> Citation:
    """Helper to build Citation objects with optional metadata."""
    metadata = {}
    if difficulty:
        metadata["difficulty"] = difficulty
    if course:
        metadata["course"] = course
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


def _mock_rerank_response(passages: list[dict]) -> MagicMock:
    """Build a mock generate_content response with RankedResults JSON."""
    ranked = RankedResults(
        rankings=[
            RankedPassage(
                passage_index=p["index"],
                score=p["score"],
                reason=p.get("reason", "relevant"),
            )
            for p in passages
        ]
    )
    mock_response = MagicMock()
    mock_response.text = ranked.model_dump_json()
    return mock_response


class TestRerankerScoring:
    """Tests for passage scoring and reordering."""

    def test_rerank_applies_scores(self, mock_gemini_client):
        """Reranked output is ordered by relevance_score descending."""
        citations = [
            _make_citation(index=1, title="a.txt", text="First passage about metaphysics."),
            _make_citation(index=2, title="b.txt", text="Second passage about epistemology."),
            _make_citation(index=3, title="c.txt", text="Third passage about ethics."),
        ]

        mock_gemini_client.models.generate_content.return_value = _mock_rerank_response([
            {"index": 0, "score": 6.0},
            {"index": 1, "score": 9.5},
            {"index": 2, "score": 8.0},
        ])

        result = rerank_passages(mock_gemini_client, "What is ethics?", citations)

        assert len(result) == 3
        # Highest score first: index 1 (9.5), then index 2 (8.0), then index 0 (6.0)
        assert result[0].title == "b.txt"
        assert result[1].title == "c.txt"
        assert result[2].title == "a.txt"

    def test_rerank_handles_empty_passages(self, mock_gemini_client):
        """Empty rankings returned by API handled gracefully."""
        citations = [
            _make_citation(index=1, title="a.txt", text="Some passage content here."),
            _make_citation(index=2, title="b.txt", text="Another passage content here."),
        ]

        mock_gemini_client.models.generate_content.return_value = _mock_rerank_response([])

        result = rerank_passages(mock_gemini_client, "test query", citations)
        # With empty rankings, all citations get score -1 and maintain original order
        assert len(result) == 2

    def test_rerank_single_citation_passthrough(self, mock_gemini_client):
        """Single citation is returned as-is without API call."""
        citations = [_make_citation(index=1, title="a.txt", text="Only passage.")]

        result = rerank_passages(mock_gemini_client, "test", citations)
        assert len(result) == 1
        assert result[0].title == "a.txt"
        # Should not call the API for a single citation
        mock_gemini_client.models.generate_content.assert_not_called()

    def test_rerank_prompt_includes_query(self, mock_gemini_client):
        """The prompt passed to generate_content includes the original query."""
        citations = [
            _make_citation(index=1, title="a.txt", text="Passage about individual rights and freedom."),
            _make_citation(index=2, title="b.txt", text="Passage about property rights and ownership."),
        ]

        mock_gemini_client.models.generate_content.return_value = _mock_rerank_response([
            {"index": 0, "score": 7.0},
            {"index": 1, "score": 8.0},
        ])

        rerank_passages(mock_gemini_client, "What are individual rights?", citations)

        call_args = mock_gemini_client.models.generate_content.call_args
        prompt = call_args.kwargs.get("contents") or call_args.args[0]
        # If contents was passed as a keyword arg
        if isinstance(prompt, str):
            assert "What are individual rights?" in prompt
        else:
            # Check the contents keyword
            prompt_str = str(prompt)
            assert "What are individual rights?" in prompt_str

    def test_rerank_api_failure_returns_original(self, mock_gemini_client):
        """On API failure, original citation order is preserved."""
        citations = [
            _make_citation(index=1, title="a.txt", text="First passage in original order."),
            _make_citation(index=2, title="b.txt", text="Second passage in original order."),
        ]

        mock_gemini_client.models.generate_content.side_effect = Exception("API error")

        result = rerank_passages(mock_gemini_client, "test query", citations)
        assert len(result) == 2
        assert result[0].title == "a.txt"
        assert result[1].title == "b.txt"


class TestDifficultyOrdering:
    """Tests for difficulty-aware reordering."""

    def test_difficulty_ordering_learn_mode(self):
        """Learn mode sorts introductory first, then intermediate, then advanced."""
        citations = [
            _make_citation(index=1, title="adv.txt", difficulty="advanced"),
            _make_citation(index=2, title="intro.txt", difficulty="introductory"),
            _make_citation(index=3, title="mid.txt", difficulty="intermediate"),
        ]

        result = apply_difficulty_ordering(citations, mode="learn")
        assert result[0].title == "intro.txt"
        assert result[1].title == "mid.txt"
        assert result[2].title == "adv.txt"

    def test_difficulty_ordering_research_mode(self):
        """Research mode returns citations in original (relevance) order."""
        citations = [
            _make_citation(index=1, title="adv.txt", difficulty="advanced"),
            _make_citation(index=2, title="intro.txt", difficulty="introductory"),
            _make_citation(index=3, title="mid.txt", difficulty="intermediate"),
        ]

        result = apply_difficulty_ordering(citations, mode="research")
        # Research mode preserves original order
        assert result[0].title == "adv.txt"
        assert result[1].title == "intro.txt"
        assert result[2].title == "mid.txt"

    def test_difficulty_ordering_missing_difficulty(self):
        """Citations without difficulty metadata default to 'intermediate' bucket."""
        citations = [
            _make_citation(index=1, title="adv.txt", difficulty="advanced"),
            _make_citation(index=2, title="none.txt"),  # No difficulty metadata
            _make_citation(index=3, title="intro.txt", difficulty="introductory"),
        ]

        result = apply_difficulty_ordering(citations, mode="learn")
        # introductory (0) < intermediate-default (1) < advanced (2)
        assert result[0].title == "intro.txt"
        assert result[1].title == "none.txt"  # defaults to intermediate
        assert result[2].title == "adv.txt"

    def test_difficulty_window_size(self):
        """Only the top window_size results are reordered; the rest stay in place."""
        citations = [
            _make_citation(index=1, title="adv.txt", difficulty="advanced"),
            _make_citation(index=2, title="intro.txt", difficulty="introductory"),
            _make_citation(index=3, title="mid.txt", difficulty="intermediate"),
            _make_citation(index=4, title="tail.txt", difficulty="introductory"),
        ]

        result = apply_difficulty_ordering(citations, mode="learn", window=2)
        # Only first 2 reordered: intro before adv
        assert result[0].title == "intro.txt"
        assert result[1].title == "adv.txt"
        # Remaining stay in original order
        assert result[2].title == "mid.txt"
        assert result[3].title == "tail.txt"

    def test_difficulty_preserves_relevance_within_bucket(self):
        """Within the same difficulty bucket, original relevance order is preserved."""
        citations = [
            _make_citation(index=1, title="intro1.txt", difficulty="introductory"),
            _make_citation(index=2, title="adv.txt", difficulty="advanced"),
            _make_citation(index=3, title="intro2.txt", difficulty="introductory"),
        ]

        result = apply_difficulty_ordering(citations, mode="learn")
        # Both intros come first, in their original order
        assert result[0].title == "intro1.txt"
        assert result[1].title == "intro2.txt"
        assert result[2].title == "adv.txt"
