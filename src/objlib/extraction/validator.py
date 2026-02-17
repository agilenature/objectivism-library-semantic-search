"""Two-level validation engine for AI-extracted metadata.

Distinguishes hard failures (reject + retry) from soft warnings
(accept + flag as needs_review). Includes repair logic for common
LLM hallucinations (near-miss category names, out-of-range scores,
invalid vocabulary tags).

Hard rules enforce structural correctness (category/difficulty enum,
primary_topics from vocabulary, confidence range). Soft rules flag
quality concerns (aspect count, summary length, key_arguments presence).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from objlib.extraction.schemas import (
    CONTROLLED_VOCABULARY,
    Category,
    Difficulty,
    MetadataStatus,
)

# Mapping of common near-miss category strings to valid Category values.
# Used by repair logic to auto-fix LLM hallucinations.
_CATEGORY_ALIASES: dict[str, str] = {
    "course": "course_transcript",
    "transcript": "course_transcript",
    "lecture": "course_transcript",
    "book": "book_excerpt",
    "excerpt": "book_excerpt",
    "qa": "qa_session",
    "q&a": "qa_session",
    "question": "qa_session",
    "comparison": "philosophy_comparison",
    "concept": "concept_exploration",
    "exploration": "concept_exploration",
    "cultural": "cultural_commentary",
    "commentary": "cultural_commentary",
    "essay": "article",
}

_VALID_CATEGORIES: set[str] = {c.value for c in Category}
_VALID_DIFFICULTIES: set[str] = {d.value for d in Difficulty}


@dataclass
class ValidationResult:
    """Result of validating an extracted metadata dict.

    Attributes:
        status: Final metadata status after validation.
        hard_failures: List of hard rule violation descriptions (reject + retry).
        soft_warnings: List of soft rule warning descriptions (accept + flag).
        repaired_fields: List of fields that were auto-repaired before validation.
    """

    status: MetadataStatus
    hard_failures: list[str] = field(default_factory=list)
    soft_warnings: list[str] = field(default_factory=list)
    repaired_fields: list[str] = field(default_factory=list)


def _repair_category(raw_data: dict, repaired: list[str]) -> None:
    """Attempt to repair an invalid category value.

    Checks if the raw category is a substring match or alias of a valid
    category. If repairable, mutates raw_data in place and records the
    repair.

    Args:
        raw_data: Mutable extraction dict.
        repaired: List to append repair descriptions to.
    """
    category = raw_data.get("category", "")
    if category in _VALID_CATEGORIES:
        return

    # Try alias lookup (case-insensitive)
    lower = category.lower().strip()
    if lower in _CATEGORY_ALIASES:
        raw_data["category"] = _CATEGORY_ALIASES[lower]
        repaired.append(f"category: '{category}' -> '{raw_data['category']}' (alias)")
        return

    # Try substring match against valid categories
    for valid in _VALID_CATEGORIES:
        if lower in valid or valid in lower:
            raw_data["category"] = valid
            repaired.append(f"category: '{category}' -> '{valid}' (substring)")
            return


def _repair_confidence(raw_data: dict, repaired: list[str]) -> None:
    """Clamp confidence_score to [0.0, 1.0] if outside range.

    Args:
        raw_data: Mutable extraction dict.
        repaired: List to append repair descriptions to.
    """
    score = raw_data.get("confidence_score")
    if score is None:
        return
    try:
        score = float(score)
    except (TypeError, ValueError):
        return

    if score < 0.0:
        raw_data["confidence_score"] = 0.0
        repaired.append(f"confidence_score: {score} clamped to 0.0")
    elif score > 1.0:
        raw_data["confidence_score"] = 1.0
        repaired.append(f"confidence_score: {score} clamped to 1.0")


def _filter_primary_topics(raw_data: dict, repaired: list[str], document_text: str | None = None) -> None:
    """Filter primary_topics to only CONTROLLED_VOCABULARY members and normalize to exactly 8.

    Uses intelligent semantic selection when document_text is available to:
    - Reduce >8 topics to exactly 8 (intelligent reduction)
    - Expand <8 topics to exactly 8 (intelligent suggestion)

    Mutates raw_data in place. Records the count of filtered/adjusted topics.

    Args:
        raw_data: Mutable extraction dict.
        repaired: List to append repair descriptions to.
        document_text: Optional source document for semantic topic selection.
    """
    topics = raw_data.get("primary_topics")
    if not isinstance(topics, list):
        return

    valid = [t for t in topics if t in CONTROLLED_VOCABULARY]
    filtered_count = len(topics) - len(valid)
    if filtered_count > 0:
        removed = [t for t in topics if t not in CONTROLLED_VOCABULARY]
        raw_data["primary_topics"] = valid
        repaired.append(
            f"primary_topics: filtered {filtered_count} invalid tags: {removed}"
        )

    # Normalize to exactly 8 topics
    if len(valid) != 8:
        if document_text:
            try:
                if len(valid) > 8:
                    # Use semantic selection (intelligent reduction)
                    from objlib.extraction.topic_selector import select_top_topics
                    selected = select_top_topics(valid, document_text, max_topics=8)
                    removed = [t for t in valid if t not in selected]
                    raw_data["primary_topics"] = selected
                    repaired.append(
                        f"primary_topics: semantic selection reduced {len(valid)} → 8 topics (removed: {removed})"
                    )
                else:
                    # Use semantic suggestion (intelligent expansion)
                    from objlib.extraction.topic_selector import suggest_topics_from_vocabulary
                    expanded = suggest_topics_from_vocabulary(
                        document_text=document_text,
                        existing_topics=valid,
                        vocabulary=list(CONTROLLED_VOCABULARY),
                        min_topics=8,
                        max_topics=8,
                    )
                    added = [t for t in expanded if t not in valid]
                    raw_data["primary_topics"] = expanded
                    repaired.append(
                        f"primary_topics: semantic suggestion expanded {len(valid)} → 8 topics (added: {added})"
                    )
            except Exception as e:
                # Fallback: don't repair if semantic selection fails
                import logging
                logger = logging.getLogger(__name__)
                logger.warning("Semantic topic normalization failed: %s", e)
        # If no document_text or semantic selection failed, leave as-is
        # Validation will handle it in the hard rules section


def validate_extraction(raw_data: dict, document_text: str | None = None) -> ValidationResult:
    """Validate and optionally repair an extracted metadata dict.

    Applies repair logic first (category alias, confidence clamping,
    topic filtering), then checks hard rules and soft rules.

    Hard rules (failure = rejected, retry with schema reminder):
    - category must be in Category enum values
    - difficulty must be in Difficulty enum values
    - primary_topics must have 3-8 items from CONTROLLED_VOCABULARY
      (after filtering; <3 remaining = hard fail)
    - confidence_score must be float 0.0-1.0

    Soft rules (warning = needs_review, still accepted):
    - topic_aspects should have 3-10 items
    - semantic_description.summary should be >= 50 chars
    - semantic_description.key_arguments should have >= 1 item

    Args:
        raw_data: Dict from parsed API response (will be mutated by repairs).
        document_text: Optional source document text for semantic topic selection.

    Returns:
        ValidationResult with status, failures, warnings, and repairs.
    """
    hard_failures: list[str] = []
    soft_warnings: list[str] = []
    repaired_fields: list[str] = []

    # --- Repair phase ---
    _repair_category(raw_data, repaired_fields)
    _repair_confidence(raw_data, repaired_fields)
    _filter_primary_topics(raw_data, repaired_fields, document_text)

    # --- Hard rules ---

    # Category must be valid enum value
    category = raw_data.get("category", "")
    if category not in _VALID_CATEGORIES:
        hard_failures.append(
            f"Invalid category: '{category}'. Must be one of: {sorted(_VALID_CATEGORIES)}"
        )

    # Difficulty must be valid enum value
    difficulty = raw_data.get("difficulty", "")
    if difficulty not in _VALID_DIFFICULTIES:
        hard_failures.append(
            f"Invalid difficulty: '{difficulty}'. Must be one of: {sorted(_VALID_DIFFICULTIES)}"
        )

    # Primary topics: MUST be exactly 8 items from controlled vocabulary
    # Note: Semantic normalization to 8 topics happens in repair phase when document_text available
    topics = raw_data.get("primary_topics", [])
    if not isinstance(topics, list):
        hard_failures.append("primary_topics must be a list")
    else:
        valid_topics = [t for t in topics if t in CONTROLLED_VOCABULARY]
        if len(valid_topics) != 8:
            hard_failures.append(
                f"primary_topics: must be exactly 8 topics (found {len(valid_topics)}). "
                f"Semantic normalization should have corrected this. Valid: {valid_topics}"
            )

    # Confidence score must be float 0.0-1.0
    confidence = raw_data.get("confidence_score")
    try:
        conf_val = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        conf_val = None

    if conf_val is None:
        hard_failures.append("confidence_score is missing or not a number")
    elif conf_val < 0.0 or conf_val > 1.0:
        hard_failures.append(
            f"confidence_score {conf_val} outside range [0.0, 1.0]"
        )

    # --- Soft rules ---

    # Topic aspects: No count limit (thorough extraction is good)

    # Semantic description checks
    sem_desc = raw_data.get("semantic_description", {})
    if isinstance(sem_desc, dict):
        summary = sem_desc.get("summary", "")
        if isinstance(summary, str) and len(summary) < 50:
            soft_warnings.append(
                f"semantic_description.summary: {len(summary)} chars "
                f"(recommended >= 50)"
            )

        key_args = sem_desc.get("key_arguments", [])
        if isinstance(key_args, list) and len(key_args) < 1:
            soft_warnings.append(
                "semantic_description.key_arguments: empty "
                "(recommended >= 1 item)"
            )

    # --- Determine status ---
    if hard_failures:
        status = MetadataStatus.FAILED_VALIDATION
    elif soft_warnings:
        status = MetadataStatus.NEEDS_REVIEW
    else:
        status = MetadataStatus.EXTRACTED

    return ValidationResult(
        status=status,
        hard_failures=hard_failures,
        soft_warnings=soft_warnings,
        repaired_fields=repaired_fields,
    )


def build_retry_prompt(failures: list[str]) -> str:
    """Build a schema reminder prompt fragment for retry after hard failure.

    Args:
        failures: List of hard failure descriptions from ValidationResult.

    Returns:
        Prompt string asking the model to fix the specific issues.
    """
    issues = "\n".join(f"  - {f}" for f in failures)
    return (
        "\n\n[VALIDATION ERROR] Your previous response had these issues:\n"
        f"{issues}\n\n"
        "Please fix these issues and return valid JSON matching the schema. "
        "Use ONLY values from the controlled vocabulary for primary_topics, "
        "and ONLY valid category/difficulty enum values."
    )
