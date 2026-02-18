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

from google.genai import types

from objlib.search.models import Claim, CitationRef, SynthesisOutput

logger = logging.getLogger(__name__)

MIN_CITATIONS_FOR_SYNTHESIS = 5
MAX_PASSAGE_CHARS = 600

SYNTHESIS_SYSTEM_INSTRUCTION = (
    "You are a scholarly synthesizer specializing in Objectivist philosophy. "
    "Given a query and numbered source passages, produce a synthesis structured "
    "as factual claims. Each claim must be a single sentence making one factual "
    "assertion, supported by a verbatim quote (20-60 words) copied EXACTLY from "
    "one of the passages. Use the passage index number as the passage_id. "
    "You may include optional bridging_intro and bridging_conclusion sentences "
    "(uncited, no factual assertions). When sources disagree, attribute explicitly."
)


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


def synthesize_answer(
    client,  # genai.Client (untyped to avoid import dependency)
    query: str,
    citations: list[Citation],
    model: str = "gemini-2.0-flash",
) -> SynthesisOutput | None:
    """Synthesize a structured answer from diverse source passages.

    Builds a passage context from citations, sends to Gemini Flash for
    structured synthesis, validates all quotes against source text, and
    re-prompts once on validation failure.

    Args:
        client: Authenticated genai.Client instance.
        query: The user's search query.
        citations: List of Citation objects (already diversified).
        model: Gemini model to use for synthesis.

    Returns:
        SynthesisOutput with validated claims, or None on failure
        (fewer than 5 citations, API error, or validation failure
        after re-prompt).
    """
    if len(citations) < MIN_CITATIONS_FOR_SYNTHESIS:
        logger.info(
            "Skipping synthesis: %d citations (minimum %d)",
            len(citations),
            MIN_CITATIONS_FOR_SYNTHESIS,
        )
        return None

    passage_map = _build_passage_map(citations)
    passage_context = _build_passage_context(citations)
    prompt = f"Query: {query}\n\nSources:\n{passage_context}"

    config = types.GenerateContentConfig(
        system_instruction=SYNTHESIS_SYSTEM_INSTRUCTION,
        response_mime_type="application/json",
        response_schema=SynthesisOutput,
        temperature=0.0,
    )

    # First attempt
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        output = SynthesisOutput.model_validate_json(response.text)
    except Exception:
        logger.warning("Synthesis API call failed", exc_info=True)
        return None

    valid_claims, errors = validate_citations(output.claims, passage_map)

    if not errors:
        return output

    # Re-prompt once with error feedback
    logger.info(
        "Synthesis validation failed (%d errors), re-prompting",
        len(errors),
    )

    error_feedback = "\n".join(f"- {e}" for e in errors)
    retry_prompt = (
        f"{prompt}\n\n"
        f"IMPORTANT: Your previous response had citation errors:\n"
        f"{error_feedback}\n\n"
        f"Please fix: ensure every quote is copied EXACTLY (verbatim) "
        f"from the passage text. Use the passage index as passage_id."
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=retry_prompt,
            config=config,
        )
        output = SynthesisOutput.model_validate_json(response.text)
    except Exception:
        logger.warning("Synthesis re-prompt failed", exc_info=True)
        return None

    valid_claims, errors = validate_citations(output.claims, passage_map)

    if errors:
        logger.warning(
            "Synthesis still has %d validation errors after re-prompt, "
            "returning partial results",
            len(errors),
        )

    if not valid_claims:
        return None

    # Return output with only validated claims
    return SynthesisOutput(
        claims=valid_claims,
        bridging_intro=output.bridging_intro,
        bridging_conclusion=output.bridging_conclusion,
    )


def _build_passage_context(citations: list[Citation]) -> str:
    """Build formatted passage context for the synthesis prompt.

    Each passage includes its index, file metadata, and truncated text.
    """
    lines: list[str] = []

    for i, citation in enumerate(citations):
        text = citation.text[:MAX_PASSAGE_CHARS]
        if len(citation.text) > MAX_PASSAGE_CHARS:
            text += "..."

        metadata_parts: list[str] = [f'file: "{citation.title}"']
        if citation.metadata:
            course = citation.metadata.get("course", "")
            if course:
                metadata_parts.append(f'course: "{course}"')
            difficulty = citation.metadata.get("difficulty", "")
            if difficulty:
                metadata_parts.append(f'difficulty: "{difficulty}"')

        metadata_str = ", ".join(metadata_parts)
        lines.append(f'Passage {i} [{metadata_str}]:\n"{text}"')

    return "\n\n".join(lines)


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
