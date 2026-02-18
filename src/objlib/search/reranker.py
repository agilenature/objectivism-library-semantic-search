"""Gemini Flash LLM-based reranker with difficulty-aware ordering.

Reranks search passages using Gemini Flash structured output to score
philosophical relevance, then optionally reorders by difficulty level
for learn mode (introductory content first).

Usage::

    from objlib.search.reranker import rerank_passages, apply_difficulty_ordering

    # Rerank by philosophical relevance
    reranked = rerank_passages(client, "What is rights?", citations)

    # Then apply difficulty ordering for learn mode
    ordered = apply_difficulty_ordering(reranked, mode="learn")
"""

from __future__ import annotations

import logging

from google.genai import types

from objlib.models import Citation
from objlib.search.models import RankedResults

logger = logging.getLogger(__name__)

RERANK_SYSTEM_INSTRUCTION = (
    "You are a philosophical research assistant specializing in Objectivism. "
    "Given a query and a list of passages, score each passage's relevance "
    "to the query on a scale of 0-10. Consider: (1) direct relevance to "
    "the query topic, (2) depth and specificity of the philosophical "
    "content, (3) whether the passage provides substantive explanation "
    "versus merely mentioning the topic. Return scores as JSON."
)

MAX_PASSAGE_CHARS = 500


def rerank_passages(
    client,  # genai.Client (untyped to avoid import dependency)
    query: str,
    citations: list[Citation],
    model: str = "gemini-2.0-flash",
) -> list[Citation]:
    """Rerank citations using Gemini Flash structured output.

    Sends passages to Gemini Flash for relevance scoring against the
    query, then reorders citations by score descending.

    Args:
        client: Authenticated genai.Client instance.
        query: The user's search query.
        citations: List of Citation objects from initial search.
        model: Gemini model to use for reranking.

    Returns:
        Citations reordered by relevance score (highest first).
        On any failure, returns the original list unchanged.
    """
    if len(citations) <= 1:
        return citations

    try:
        prompt = _build_rerank_prompt(query, citations)

        config = types.GenerateContentConfig(
            system_instruction=RERANK_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=RankedResults,
            temperature=0.0,
        )

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )

        ranked = RankedResults.model_validate_json(response.text)
        return _apply_rankings(citations, ranked)

    except Exception:
        logger.warning(
            "Reranking failed, returning original order",
            exc_info=True,
        )
        return citations


def _build_rerank_prompt(query: str, citations: list[Citation]) -> str:
    """Build the reranking prompt with numbered passages.

    Each passage includes its index, truncated text, and available
    metadata context (difficulty, course).
    """
    lines = [f"Query: {query}\n", "Passages:\n"]

    for i, citation in enumerate(citations):
        text = citation.text[:MAX_PASSAGE_CHARS]
        if len(citation.text) > MAX_PASSAGE_CHARS:
            text += "..."

        metadata_parts: list[str] = []
        if citation.metadata:
            difficulty = citation.metadata.get("difficulty", "")
            if difficulty:
                metadata_parts.append(f"difficulty={difficulty}")
            course = citation.metadata.get("course", "")
            if course:
                metadata_parts.append(f"course={course}")

        metadata_str = f" [{', '.join(metadata_parts)}]" if metadata_parts else ""

        lines.append(f"[{i}]{metadata_str} {text}\n")

    return "\n".join(lines)


def _apply_rankings(
    citations: list[Citation], ranked: RankedResults
) -> list[Citation]:
    """Apply ranking scores to reorder citations.

    Maps passage_index from rankings back to citations and sorts
    by score descending. Citations not present in rankings keep
    their original position at the end with score -1.
    """
    score_map: dict[int, float] = {}
    for rp in ranked.rankings:
        if 0 <= rp.passage_index < len(citations):
            score_map[rp.passage_index] = rp.score

    indexed: list[tuple[int, Citation, float]] = []
    for i, citation in enumerate(citations):
        score = score_map.get(i, -1.0)
        indexed.append((i, citation, score))

    # Sort by score descending, then original index for ties
    indexed.sort(key=lambda x: (-x[2], x[0]))

    return [citation for _, citation, _ in indexed]
