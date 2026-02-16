"""Pydantic models and controlled vocabulary for 4-tier hybrid metadata.

Tier 1: Category (controlled enum, exactly 1)
Tier 2: Primary Topics (controlled vocabulary, 3-8 tags)
Tier 3: Topic Aspects (freeform, 3-10 phrases)
Tier 4: Semantic Description (structured freeform)

See DECISION-HYBRID-TAXONOMY.md for rationale.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Category(str, Enum):
    """Content type classification (Tier 1). Exactly 1 per file."""

    COURSE_TRANSCRIPT = "course_transcript"
    BOOK_EXCERPT = "book_excerpt"
    QA_SESSION = "qa_session"
    ARTICLE = "article"
    PHILOSOPHY_COMPARISON = "philosophy_comparison"
    CONCEPT_EXPLORATION = "concept_exploration"
    CULTURAL_COMMENTARY = "cultural_commentary"


class Difficulty(str, Enum):
    """Content difficulty level."""

    INTRO = "intro"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class MetadataStatus(str, Enum):
    """Status of AI metadata extraction for a file."""

    PENDING = "pending"
    EXTRACTED = "extracted"
    PARTIAL = "partial"
    NEEDS_REVIEW = "needs_review"
    FAILED_JSON = "failed_json"
    FAILED_VALIDATION = "failed_validation"
    RETRY_SCHEDULED = "retry_scheduled"
    APPROVED = "approved"


# 40-tag controlled vocabulary for Objectivist philosophy concepts (Tier 2).
# Tags selected from DECISION-HYBRID-TAXONOMY.md core branches, key concepts,
# contrasting concepts, and philosophical topics, plus essential additions.
CONTROLLED_VOCABULARY: frozenset[str] = frozenset({
    # Core branches (5)
    "epistemology",
    "metaphysics",
    "ethics",
    "politics",
    "aesthetics",
    # Key concepts (9)
    "reason",
    "volition",
    "rational_egoism",
    "individual_rights",
    "capitalism",
    "objective_reality",
    "consciousness",
    "existence",
    "identity",
    # Contrasting concepts (7)
    "altruism",
    "mysticism",
    "collectivism",
    "pragmatism",
    "intrinsicism",
    "subjectivism",
    "determinism",
    # Philosophical topics (6)
    "concept_formation",
    "free_will",
    "emotions",
    "rights_theory",
    "art_theory",
    "virtue_ethics",
    # Essential Objectivist additions (13)
    "productiveness",
    "honesty",
    "independence",
    "integrity",
    "justice",
    "benevolence",
    "causality",
    "logic",
    "induction",
    "values",
    "happiness",
    "self_interest",
    "government",
})


class SemanticDescription(BaseModel):
    """Structured freeform description of content (Tier 4).

    Enables semantic search on arguments and philosophical positions.
    """

    summary: str = Field(min_length=50, description="1-2 sentence overview of the content")
    key_arguments: list[str] = Field(
        min_length=1, description="Main claims, theses, and reasoning"
    )
    philosophical_positions: list[str] = Field(
        default_factory=list,
        description="Specific positions discussed and contrasted philosophical frameworks",
    )

    model_config = ConfigDict(extra="ignore")


class ExtractedMetadata(BaseModel):
    """Complete 4-tier hybrid metadata for a single file.

    Validates controlled vocabulary for Tiers 1-2, accepts freeform
    for Tiers 3-4. Invalid primary_topics are silently filtered
    (post-processing cleanup per W2.A2 decision).
    """

    category: Category
    difficulty: Difficulty
    primary_topics: list[str] = Field(
        min_length=3,
        max_length=8,
        description="3-8 tags from CONTROLLED_VOCABULARY",
    )
    topic_aspects: list[str] = Field(
        min_length=3,
        max_length=10,
        description="3-10 freeform specific philosophical concepts from the text",
    )
    semantic_description: SemanticDescription
    confidence_score: float = Field(
        ge=0.0, le=1.0, description="Model self-assessed extraction confidence"
    )

    model_config = ConfigDict(extra="ignore")

    @field_validator("primary_topics", mode="before")
    @classmethod
    def filter_controlled_vocabulary(cls, v: list[str]) -> list[str]:
        """Silently remove tags not in CONTROLLED_VOCABULARY.

        Per W2.A2 decision: post-processing cleanup rather than
        hard rejection, to handle LLM hallucination of similar tags.
        """
        if not isinstance(v, list):
            return v
        return [tag for tag in v if tag in CONTROLLED_VOCABULARY]
