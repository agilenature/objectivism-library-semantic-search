"""Prompt templates for AI metadata extraction using Mistral magistral model.

Provides system prompts for 3 competitive strategy lanes (Minimalist, Teacher,
Reasoner), user prompt framing, and JSON schema injection with controlled
vocabulary and category enumeration.

Also provides production prompt builder and config hashing for Wave 2
batch processing with versioned metadata persistence.

Prompt version tracks breaking changes for reproducibility.
See DECISION-HYBRID-TAXONOMY.md for the 4-tier metadata structure.
"""

from __future__ import annotations

import hashlib
import json

from objlib.extraction.schemas import CONTROLLED_VOCABULARY, Category, Difficulty, ExtractedMetadata

PROMPT_VERSION = "1.0.0"

# Pre-sorted for deterministic prompt generation
_SORTED_VOCABULARY = sorted(CONTROLLED_VOCABULARY)
_CATEGORIES = [c.value for c in Category]
_DIFFICULTIES = [d.value for d in Difficulty]


def get_schema_for_prompt() -> str:
    """Return a compact JSON schema string for prompt injection.

    Includes the Pydantic-generated JSON schema from ExtractedMetadata,
    the 40-tag controlled vocabulary as a numbered list, and the 7
    category options explicitly listed.

    Returns:
        Formatted schema string ready for insertion into system prompts.
    """
    json_schema = ExtractedMetadata.model_json_schema()

    # Build category list
    category_list = "\n".join(
        f"  {i + 1}. {cat}" for i, cat in enumerate(_CATEGORIES)
    )

    # Build difficulty list
    difficulty_list = "\n".join(
        f"  {i + 1}. {d}" for i, d in enumerate(_DIFFICULTIES)
    )

    # Build controlled vocabulary list
    vocab_list = "\n".join(
        f"  {i + 1}. {tag}" for i, tag in enumerate(_SORTED_VOCABULARY)
    )

    return f"""JSON Schema:
{json_schema}

CATEGORY (select exactly 1):
{category_list}

DIFFICULTY (select exactly 1):
{difficulty_list}

PRIMARY TOPICS - Controlled Vocabulary (select 3-8 ONLY from this list):
{vocab_list}

TOPIC ASPECTS (generate 3-10 freeform):
  Specific philosophical concepts, arguments, named principles found in the text.
  These are NOT from the controlled vocabulary. Extract novel, specific phrases.

SEMANTIC DESCRIPTION (structured freeform):
  - summary: 1-2 sentence overview of the content (minimum 50 characters)
  - key_arguments: Main claims, theses, and reasoning (at least 1)
  - philosophical_positions: Specific positions discussed and contrasted frameworks

CONFIDENCE SCORE:
  Float 0.0-1.0 rating your certainty based on source text clarity and ambiguity."""


# Few-shot example from DECISION-HYBRID-TAXONOMY.md (OPAR example)
_FEW_SHOT_EXAMPLE = """\
Example input: A lecture transcript about concept formation from an Objectivist epistemology course.

Example output:
{
  "category": "course_transcript",
  "difficulty": "intermediate",
  "primary_topics": ["epistemology", "concept_formation", "reason"],
  "topic_aspects": [
    "measurement omission principle",
    "unit-economy in concept formation",
    "hierarchical concept organization",
    "concepts of consciousness vs concepts of entities"
  ],
  "semantic_description": {
    "summary": "Lecture on how humans form concepts through measurement-omission, focusing on the unit-economy principle and hierarchical concept organization.",
    "key_arguments": [
      "Concepts formed by measuring similarities and omitting measurements",
      "Unit-economy: cognitive efficiency through hierarchical concepts",
      "Difference between concepts of entities vs concepts of consciousness"
    ],
    "philosophical_positions": [
      "Rand's epistemology vs Plato's theory of forms",
      "Rejection of rationalism's innate ideas"
    ]
  },
  "confidence_score": 0.89
}"""


_BASE_PERSONA = (
    "You are an Objectivist philosophy archivist. "
    "Return ONLY valid JSON matching the schema below."
)


def build_system_prompt(strategy: str) -> str:
    """Build the system prompt tailored to a strategy archetype.

    Args:
        strategy: One of 'minimalist', 'teacher', or 'reasoner'.

    Returns:
        System prompt string with schema, vocabulary, and strategy-specific
        instructions.

    Raises:
        ValueError: If strategy is not one of the three valid options.
    """
    schema = get_schema_for_prompt()

    if strategy == "minimalist":
        return f"""{_BASE_PERSONA}

Classify this philosophical text. Return JSON only.

{schema}"""

    elif strategy == "teacher":
        return f"""{_BASE_PERSONA}

Follow the example format exactly.

{_FEW_SHOT_EXAMPLE}

{schema}"""

    elif strategy == "reasoner":
        return f"""{_BASE_PERSONA}

First analyze the philosophical content: identify the main topic, determine if it's a lecture/Q&A/essay, assess difficulty. Then generate the JSON output.

{schema}"""

    else:
        raise ValueError(
            f"Unknown strategy: {strategy!r}. "
            f"Must be 'minimalist', 'teacher', or 'reasoner'."
        )


def build_user_prompt(transcript_text: str, strategy: str) -> str:
    """Wrap transcript text with strategy-appropriate framing.

    Args:
        transcript_text: The raw transcript content to classify.
        strategy: One of 'minimalist', 'teacher', or 'reasoner'.

    Returns:
        User prompt string with transcript and framing.

    Raises:
        ValueError: If strategy is not one of the three valid options.
    """
    if strategy == "minimalist":
        return transcript_text

    elif strategy == "teacher":
        return f"Here is the text to classify:\n\n{transcript_text}"

    elif strategy == "reasoner":
        return f"Analyze and classify:\n\n{transcript_text}"

    else:
        raise ValueError(
            f"Unknown strategy: {strategy!r}. "
            f"Must be 'minimalist', 'teacher', or 'reasoner'."
        )


def build_production_prompt(strategy: str, schema: str) -> str:
    """Build the production system prompt for Wave 2 batch processing.

    Uses the winning strategy template with the provided schema.
    Production always uses temperature=1.0 (magistral requirement).

    Args:
        strategy: Winning strategy name ('minimalist', 'teacher', or 'reasoner').
        schema: JSON schema string for prompt injection.

    Returns:
        Complete system prompt string for production use.
    """
    return build_system_prompt(strategy)


def hash_extraction_config(
    temperature: float,
    timeout: int,
    schema_version: str,
    vocab_hash: str,
) -> str:
    """Create a deterministic hash of the extraction configuration.

    Used for prompt versioning (W2.A10 decision) to track which
    configuration produced each extraction result.

    Args:
        temperature: Sampling temperature used.
        timeout: API timeout in seconds.
        schema_version: Schema version string (e.g., '1.0').
        vocab_hash: Hash of the controlled vocabulary.

    Returns:
        SHA256 hexdigest truncated to 16 characters.
    """
    config = {
        "temperature": temperature,
        "timeout": timeout,
        "schema_version": schema_version,
        "vocab_hash": vocab_hash,
    }
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
