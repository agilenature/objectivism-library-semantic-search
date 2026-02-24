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


def _apply_api_fallback(
    citations: list[Citation],
    db: Database,
    gemini_client: Any,
) -> None:
    """Resolve orphaned Gemini file IDs via the Files API.

    When a citation's title is an unresolved Gemini file ID (an old/duplicate
    upload whose ID is not tracked in the local DB), calls ``files.get()``
    synchronously to retrieve the ``display_name``, then looks up the file
    in the DB by filename.

    This handles the case where the File Search store has multiple copies of
    the same document (from multiple upload runs) and Gemini returns an older
    file ID that the DB doesn't recognize.

    Best-effort: API errors are silently ignored.

    Args:
        citations: Citations to resolve in place.
        db: Database instance for filename lookup.
        gemini_client: Synchronous ``genai.Client`` instance.
    """
    for citation in citations:
        # Skip already-resolved citations (filename contains ".")
        if not citation.title or "." in citation.title:
            continue
        # This looks like an unresolved Gemini file ID — try API fallback
        raw_id = citation.title
        full_id = raw_id if raw_id.startswith("files/") else f"files/{raw_id}"
        try:
            file_obj = gemini_client.files.get(name=full_id)
            display_name = getattr(file_obj, "display_name", None)
            if not display_name:
                continue
            match = db.get_file_metadata_by_filenames([display_name]).get(display_name)
            if match:
                citation.title = display_name
                citation.file_path = match["file_path"]
                citation.metadata = match["metadata"]
        except Exception:
            pass  # Best-effort: API errors silently ignored


def enrich_citations(
    citations: list[Citation],
    db: Database,
    gemini_client: Any | None = None,
) -> list[Citation]:
    """Enrich citations with local SQLite metadata and deduplicate.

    Collects all titles from citations, looks up matching filenames in
    SQLite, and populates ``file_path`` and ``metadata`` on each citation.

    Tries four lookup strategies in order:
    1. Lookup by filename (when Gemini returns display_name as title)
    2. Lookup by store doc prefix (SUBSTR extraction from gemini_store_doc_id;
       covers all 1,749 indexed files including 1,075 with NULL gemini_file_id)
    3. Lookup by Gemini file ID (when Gemini returns file ID as title)
    4. API fallback via ``files.get()`` for orphaned/duplicate file IDs not
       tracked in the local DB (only when ``gemini_client`` is provided)

    The store doc prefix lookup (pass 2) is the primary resolution path for
    Gemini File Search citations. The identity contract (Phase 11 spike,
    13/13 match): retrieved_context.title == 12-char prefix of
    gemini_store_doc_id == file resource ID.

    After enrichment, deduplicates: when two citations share the same
    passage text (first 100 chars), the enriched (filename-resolved)
    citation is kept and the unresolved (raw Gemini ID) duplicate is
    dropped. This handles the case where a file appears twice in Gemini
    results -- once with a known ID and once with an orphaned ID.

    Args:
        citations: List of Citation objects (mutated in place).
        db: Database instance for metadata lookup.
        gemini_client: Optional synchronous ``genai.Client`` for API fallback.
            When provided, unresolved Gemini file IDs are resolved via the
            Files API. Best-effort -- failures are silently ignored.

    Returns:
        Deduplicated list of enriched citations.
    """
    if not citations:
        return citations

    titles = [c.title for c in citations if c.title]

    # First pass: lookup by filename
    filename_lookup = db.get_file_metadata_by_filenames(titles)

    # Second pass: for unmatched titles, try store doc prefix lookup
    # (covers all indexed files including those with NULL gemini_file_id)
    unmatched_after_filename = [t for t in titles if t not in filename_lookup]
    store_prefix_lookup = (
        db.get_file_metadata_by_store_doc_prefix(unmatched_after_filename)
        if unmatched_after_filename
        else {}
    )

    # Third pass: for still-unmatched, try gemini_file_id lookup
    unmatched_after_prefix = [
        t for t in unmatched_after_filename if t not in store_prefix_lookup
    ]
    gemini_id_lookup = (
        db.get_file_metadata_by_gemini_ids(unmatched_after_prefix)
        if unmatched_after_prefix
        else {}
    )

    for citation in citations:
        # Try filename lookup first
        match = filename_lookup.get(citation.title)
        if match:
            citation.file_path = match["file_path"]
            citation.metadata = match["metadata"]
            continue

        # Try store doc prefix lookup
        prefix_match = store_prefix_lookup.get(citation.title)
        if prefix_match:
            citation.title = prefix_match["filename"]
            citation.file_path = prefix_match["file_path"]
            citation.metadata = prefix_match["metadata"]
            continue

        # Fall back to Gemini file ID lookup
        gemini_match = gemini_id_lookup.get(citation.title)
        if gemini_match:
            # Update citation title to the actual filename
            citation.title = gemini_match["filename"]
            citation.file_path = gemini_match["file_path"]
            citation.metadata = gemini_match["metadata"]

    # Fourth pass: API fallback for IDs still unresolved after DB lookups
    if gemini_client is not None:
        _apply_api_fallback(citations, db, gemini_client)

    # Deduplicate by passage text: keep enriched citations over raw-ID ones.
    # A citation is "resolved" when its title contains a "." (looks like a filename).
    seen_text: dict[str, Citation] = {}  # passage_key -> best citation so far
    for citation in citations:
        passage_key = citation.text[:100].strip().lower()
        existing = seen_text.get(passage_key)
        if existing is None:
            seen_text[passage_key] = citation
        else:
            # Prefer the one with a resolved filename (has "." in title)
            existing_resolved = "." in existing.title
            current_resolved = "." in citation.title
            if current_resolved and not existing_resolved:
                seen_text[passage_key] = citation

    # Rebuild list preserving original relative order
    kept = set(id(c) for c in seen_text.values())
    return [c for c in citations if id(c) in kept]


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
