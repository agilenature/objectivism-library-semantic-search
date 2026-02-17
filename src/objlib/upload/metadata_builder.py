"""Enriched metadata builder for Gemini File Search custom_metadata.

Transforms Phase 1 metadata, Phase 6 AI metadata, and Phase 6.1 entity
data into Gemini CustomMetadata format with proper string_value,
numeric_value, and string_list_value types.

The Gemini CustomMetadata API supports max 20 entries per document.
This builder produces 7-9 entries depending on data availability.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def build_enriched_metadata(
    phase1_metadata: dict[str, Any],
    ai_metadata: dict[str, Any],
    entity_names: list[str],
) -> list[dict[str, Any]]:
    """Build enriched CustomMetadata for Gemini import_file.

    Uses 7-9 metadata fields (max 20 allowed per document):
    - category (string_value) -- Tier 1, from AI or Phase 1 fallback
    - difficulty (string_value) -- Tier 1, from AI or Phase 1 fallback
    - topics (string_list_value) -- Tier 2 primary_topics
    - aspects (string_list_value) -- Tier 3 topic_aspects
    - entities (string_list_value) -- Phase 6.1 canonical names
    - key_themes (string_list_value) -- Tier 4 key_arguments
    - source_type (string_value) -- always "objectivism_library"
    - course (string_value) -- Phase 1 metadata (if present)
    - quality_score (numeric_value) -- AI confidence score

    Args:
        phase1_metadata: Parsed JSON from files.metadata_json.
        ai_metadata: Parsed JSON from file_metadata_ai.metadata_json.
        entity_names: Canonical person names from transcript_entity JOIN person.

    Returns:
        List of CustomMetadata dicts suitable for Gemini import_file
        config.custom_metadata parameter.
    """
    result: list[dict[str, Any]] = []

    # Tier 1: category (AI preferred, Phase 1 fallback)
    category = ai_metadata.get("category") or phase1_metadata.get("category")
    if category:
        result.append({"key": "category", "string_value": str(category)})

    # Tier 1: difficulty (AI preferred, Phase 1 fallback)
    difficulty = ai_metadata.get("difficulty") or phase1_metadata.get("difficulty")
    if difficulty:
        result.append({"key": "difficulty", "string_value": str(difficulty)})

    # Tier 2: primary_topics (string_list_value with values wrapper)
    topics = ai_metadata.get("primary_topics", [])
    if topics:
        result.append({
            "key": "topics",
            "string_list_value": {"values": topics[:8]},
        })

    # Tier 3: topic_aspects (string_list_value, max 10 items, max 100 chars each)
    aspects = ai_metadata.get("topic_aspects", [])
    if aspects:
        # Cap each aspect string at 100 chars to avoid Gemini rejection
        capped_aspects = [asp[:100] for asp in aspects[:10]]
        result.append({
            "key": "aspects",
            "string_list_value": {"values": capped_aspects},
        })

    # Phase 6.1: entity canonical names (string_list_value, max 10)
    if entity_names:
        result.append({
            "key": "entities",
            "string_list_value": {"values": list(entity_names)[:10]},
        })

    # Tier 4: key themes from key_arguments (string_list_value)
    semantic = ai_metadata.get("semantic_description", {})
    key_args = semantic.get("key_arguments", [])
    if key_args:
        themes = [arg[:200] for arg in key_args[:5]]
        result.append({
            "key": "key_themes",
            "string_list_value": {"values": themes},
        })

    # Static: source_type
    result.append({"key": "source_type", "string_value": "objectivism_library"})

    # Phase 1: course name (if present)
    course = phase1_metadata.get("course")
    if course:
        result.append({"key": "course", "string_value": str(course)})

    # AI confidence score as numeric
    confidence = ai_metadata.get("confidence_score")
    if confidence is not None:
        result.append({"key": "quality_score", "numeric_value": float(confidence)})

    return result


def compute_upload_hash(
    phase1_metadata: dict[str, Any],
    ai_metadata: dict[str, Any],
    entity_names: list[str],
    file_content_hash: str,
) -> str:
    """Compute a deterministic SHA-256 hash for idempotency detection.

    If the hash matches ``last_upload_hash`` in the database, the file
    can be skipped (no metadata or content changes since last upload).

    Args:
        phase1_metadata: Parsed JSON from files.metadata_json.
        ai_metadata: Parsed JSON from file_metadata_ai.metadata_json.
        entity_names: Canonical person names.
        file_content_hash: The content_hash from the files table.

    Returns:
        Hex-encoded SHA-256 digest string.
    """
    payload = json.dumps(
        {
            "phase1": phase1_metadata,
            "ai": ai_metadata,
            "entities": sorted(entity_names),
            "content_hash": file_content_hash,
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
