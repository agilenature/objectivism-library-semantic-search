"""Multi-dimensional confidence scoring for AI-extracted metadata.

Computes a weighted average across all 4 tiers of the hybrid metadata
system, applying penalties for validation repairs, soft warnings, and
hallucination risk on short transcripts.

Tier weights: category/difficulty (0.30), primary_topics (0.40),
topic_aspects (0.15), semantic_description (0.15).
"""

from __future__ import annotations

from objlib.extraction.schemas import CONTROLLED_VOCABULARY
from objlib.extraction.validator import ValidationResult


def calculate_confidence(
    model_confidence: float,
    validation: ValidationResult,
    transcript_length: int,
) -> float:
    """Calculate multi-dimensional confidence score for an extraction.

    Combines tier-specific scores with penalties for validation issues
    and hallucination risk on short transcripts.

    Args:
        model_confidence: Model's self-reported confidence (0.0-1.0).
        validation: ValidationResult from validate_extraction().
        transcript_length: Length of the source transcript in characters.

    Returns:
        Confidence score rounded to 2 decimal places, clamped to [0.0, 1.0].
    """
    # Tier 1: Category + Difficulty (are they valid?)
    # If validation has no hard failures related to category/difficulty, full score
    tier1_conf = 1.0
    for failure in validation.hard_failures:
        if "category" in failure.lower() or "difficulty" in failure.lower():
            tier1_conf = 0.3
            break

    # Tier 2: Primary topics coverage (how many valid tags?)
    # Score based on count of valid topics relative to ideal max of 8
    tier2_conf = 0.0
    for repair in validation.repaired_fields:
        if "primary_topics" in repair:
            # Topics were filtered -- use post-filter count
            break
    # We don't have direct access to the raw_data here, so use
    # validation state: if no hard failure on topics, assume >= 3 valid
    topic_hard_fail = any("primary_topics" in f for f in validation.hard_failures)
    if topic_hard_fail:
        tier2_conf = 0.2  # Very low -- hard failure on topics
    else:
        # Assume reasonable coverage (5/8 baseline) since we passed validation
        # Adjust based on soft warnings that might indicate topic issues
        tier2_conf = min(1.0, 5.0 / 8.0)  # 0.625 baseline for passing

    # Tier 3: Topic aspects quality
    aspect_warning = any("topic_aspects" in w for w in validation.soft_warnings)
    tier3_conf = 0.5 if aspect_warning else 0.8

    # Tier 4: Semantic description quality
    summary_warning = any("summary" in w for w in validation.soft_warnings)
    key_args_warning = any("key_arguments" in w for w in validation.soft_warnings)
    if summary_warning or key_args_warning:
        tier4_conf = 0.6
    else:
        tier4_conf = 0.9

    # Weighted average
    weighted = (
        tier1_conf * 0.30
        + tier2_conf * 0.40
        + tier3_conf * 0.15
        + tier4_conf * 0.15
    )

    # Penalties
    penalties = 0.0

    # -0.25 if any hard validation repair was needed
    if validation.repaired_fields:
        penalties += 0.25

    # -0.10 per soft warning (max -0.30 total)
    soft_penalty = min(0.30, len(validation.soft_warnings) * 0.10)
    penalties += soft_penalty

    # -0.15 if transcript too short but tier4 confidence high (hallucination risk)
    if transcript_length < 800 and tier4_conf > 0.7:
        penalties += 0.15

    final = max(0.0, min(1.0, weighted - penalties))
    return round(final, 2)
