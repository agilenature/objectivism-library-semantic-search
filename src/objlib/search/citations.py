"""Citation extraction from Gemini GroundingMetadata and SQLite enrichment.

Handles the pipeline: GroundingMetadata -> Citation objects -> enriched
with local SQLite metadata (course, year, difficulty, etc).
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

import typer

from objlib.models import Citation

if TYPE_CHECKING:
    from objlib.database import Database

# Known filterable fields (must match Phase 2 upload metadata keys)
FILTERABLE_FIELDS = frozenset(
    {"category", "course", "difficulty", "quarter", "date", "year", "week", "quality_score"}
)

# Fields that are always numeric in Gemini custom_metadata
NUMERIC_FIELDS = frozenset({"year", "week", "quality_score"})


def extract_citations(grounding_metadata: Any | None) -> list[Citation]:
    """Extract structured citations from Gemini grounding metadata.

    Safely handles None at every level: grounding_metadata, grounding_chunks,
    retrieved_context, grounding_supports, confidence_scores.

    Args:
        grounding_metadata: The ``GroundingMetadata`` object from
            ``response.candidates[0].grounding_metadata``, or None.

    Returns:
        List of Citation objects with aggregated confidence scores.
        Returns empty list if no grounding metadata or chunks.
    """
    if grounding_metadata is None:
        return []

    chunks = getattr(grounding_metadata, "grounding_chunks", None)
    if not chunks:
        return []

    # Build per-chunk confidence scores by averaging across all supports
    chunk_scores: dict[int, list[float]] = defaultdict(list)
    supports = getattr(grounding_metadata, "grounding_supports", None) or []
    for support in supports:
        indices = getattr(support, "grounding_chunk_indices", None) or []
        scores = getattr(support, "confidence_scores", None) or []
        for idx, score in zip(indices, scores):
            chunk_scores[idx].append(score)

    citations: list[Citation] = []
    for i, chunk in enumerate(chunks):
        ctx = getattr(chunk, "retrieved_context", None)
        if ctx is None:
            continue

        # Aggregate confidence: average of all support scores referencing this chunk
        scores_for_chunk = chunk_scores.get(i, [])
        confidence = (
            sum(scores_for_chunk) / len(scores_for_chunk)
            if scores_for_chunk
            else 0.0
        )

        citations.append(
            Citation(
                index=i + 1,  # 1-based display index
                title=getattr(ctx, "title", "") or "",
                uri=getattr(ctx, "uri", None),
                text=getattr(ctx, "text", "") or "",
                document_name=getattr(ctx, "document_name", None),
                confidence=confidence,
            )
        )

    return citations


def enrich_citations(citations: list[Citation], db: Database) -> list[Citation]:
    """Enrich citations with local SQLite metadata.

    Collects all titles from citations, looks up matching filenames in
    SQLite, and populates ``file_path`` and ``metadata`` on each citation.

    Tries two lookup strategies:
    1. Lookup by filename (when Gemini returns display_name as title)
    2. Lookup by Gemini file ID (when Gemini returns file ID as title)

    Args:
        citations: List of Citation objects (mutated in place).
        db: Database instance for metadata lookup.

    Returns:
        The same list of citations (mutated in place).
    """
    if not citations:
        return citations

    titles = [c.title for c in citations if c.title]

    # First pass: lookup by filename
    filename_lookup = db.get_file_metadata_by_filenames(titles)

    # Second pass: for unmatched titles, try Gemini ID lookup
    unmatched_titles = [t for t in titles if t not in filename_lookup]
    gemini_id_lookup = db.get_file_metadata_by_gemini_ids(unmatched_titles) if unmatched_titles else {}

    for citation in citations:
        # Try filename lookup first
        match = filename_lookup.get(citation.title)
        if match:
            citation.file_path = match["file_path"]
            citation.metadata = match["metadata"]
        else:
            # Fall back to Gemini ID lookup
            gemini_match = gemini_id_lookup.get(citation.title)
            if gemini_match:
                # Update citation title to the actual filename
                citation.title = gemini_match["filename"]
                citation.file_path = gemini_match["file_path"]
                citation.metadata = gemini_match["metadata"]

    return citations


def build_metadata_filter(filters: list[str]) -> str | None:
    """Convert CLI ``--filter field:value`` pairs to AIP-160 syntax.

    Supports operators:
      - ``field:value`` -> ``field="value"`` (string) or ``field=value`` (numeric)
      - ``field:>value`` -> ``field>value``
      - ``field:>=value`` -> ``field>=value``
      - ``field:<value`` -> ``field<value``
      - ``field:<=value`` -> ``field<=value``

    Multiple filters are joined with `` AND ``.

    Args:
        filters: List of ``"field:value"`` strings from CLI.

    Returns:
        AIP-160 filter string, or None if filters is empty.

    Raises:
        typer.BadParameter: If an unknown field name is used.
    """
    if not filters:
        return None

    parts: list[str] = []
    for f in filters:
        key, _, value = f.partition(":")
        if not key or not value:
            continue

        # Validate field name
        if key not in FILTERABLE_FIELDS:
            raise typer.BadParameter(
                f"Unknown filter field '{key}'. "
                f"Valid fields: {', '.join(sorted(FILTERABLE_FIELDS))}"
            )

        # Detect comparison operators
        if value.startswith(">=") or value.startswith("<="):
            parts.append(f"{key}{value}")
        elif value.startswith(">") or value.startswith("<"):
            parts.append(f"{key}{value}")
        elif key in NUMERIC_FIELDS:
            # Numeric field: try numeric equality
            try:
                int(value)
                parts.append(f"{key}={value}")
            except ValueError:
                # Not numeric, treat as string
                parts.append(f'{key}="{value}"')
        else:
            # Try numeric first, fallback to string
            try:
                int(value)
                parts.append(f"{key}={value}")
            except ValueError:
                parts.append(f'{key}="{value}"')

    return " AND ".join(parts) if parts else None
