"""Multi-document synthesis pipeline with citation validation.

Synthesizes reranked search passages into a coherent, cited answer
using Gemini Flash structured output. Applies MMR diversity filtering
to ensure source variety, and validates every quote against source text.

Usage::

    from objlib.search.synthesizer import (
        synthesize_answer,
        apply_mmr_diversity,
        validate_citations,
    )

    # Diversify citations (max 2 per file, prefer distinct courses)
    diverse = apply_mmr_diversity(citations)

    # Synthesize with Gemini Flash
    output = synthesize_answer(client, "What is rights?", diverse)

    # Validate quotes against passage text
    valid, errors = validate_citations(output.claims, passage_map)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from objlib.models import Citation

from objlib.search.models import Claim, CitationRef, SynthesisOutput

logger = logging.getLogger(__name__)


def apply_mmr_diversity(
    citations: list[Citation],
    max_per_file: int = 2,
    max_results: int = 10,
) -> list[Citation]:
    """Apply Maximal Marginal Relevance diversity filtering.

    Limits passages to max_per_file per source file and prefers
    distinct courses to maximize topical diversity.

    Args:
        citations: Citations ordered by relevance (best first).
        max_per_file: Maximum passages from any single file.
        max_results: Maximum total results to return.

    Returns:
        Diversified subset of citations preserving relevance order.
    """
    if not citations:
        return []

    result: list[Citation] = []
    result_ids: set[int] = set()  # track by id() to avoid duplicates
    file_counts: dict[str, int] = {}
    course_seen: set[str] = set()

    def _file_key(c: Citation) -> str:
        return c.file_path or c.title

    def _course(c: Citation) -> str:
        return (c.metadata or {}).get("course", "")

    # First pass: prefer citations from unseen files AND unseen courses
    for citation in citations:
        if len(result) >= max_results:
            break
        fk = _file_key(citation)
        course = _course(citation)
        if file_counts.get(fk, 0) == 0 and course and course not in course_seen:
            result.append(citation)
            result_ids.add(id(citation))
            file_counts[fk] = file_counts.get(fk, 0) + 1
            course_seen.add(course)

    # Second pass: fill remaining slots respecting max_per_file
    for citation in citations:
        if len(result) >= max_results:
            break
        if id(citation) in result_ids:
            continue
        fk = _file_key(citation)
        if file_counts.get(fk, 0) < max_per_file:
            result.append(citation)
            result_ids.add(id(citation))
            file_counts[fk] = file_counts.get(fk, 0) + 1

    return result[:max_results]


def validate_citations(
    claims: list[Claim],
    passage_texts: dict[str, str],
) -> tuple[list[Claim], list[str]]:
    """Validate claim quotes against source passage text.

    Uses exact substring matching with whitespace normalization
    and case-insensitive comparison.

    Args:
        claims: List of Claim objects with citation quotes.
        passage_texts: Mapping of passage_id -> full passage text.

    Returns:
        Tuple of (valid_claims, error_messages).
    """
    valid: list[Claim] = []
    errors: list[str] = []

    for claim in claims:
        passage_id = claim.citation.passage_id
        passage_text = passage_texts.get(passage_id)

        if passage_text is None:
            errors.append(f"Passage {passage_id} not found")
            continue

        normalized_quote = _normalize(claim.citation.quote)
        normalized_passage = _normalize(passage_text)

        if normalized_quote in normalized_passage:
            valid.append(claim)
        else:
            errors.append(
                f"Quote not found in passage {passage_id}: "
                f"{claim.citation.quote[:80]}..."
            )

    return valid, errors


def _normalize(text: str) -> str:
    """Normalize text for substring comparison.

    Collapses all whitespace to single spaces and lowercases.
    """
    return " ".join(text.split()).lower()


def _build_passage_map(citations: list[Citation]) -> dict[str, str]:
    """Build a mapping from passage index to passage text.

    Args:
        citations: List of Citation objects.

    Returns:
        Dict mapping string index ("0", "1", ...) to citation text.
    """
    return {str(i): citation.text for i, citation in enumerate(citations)}
