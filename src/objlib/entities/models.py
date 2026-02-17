"""Pydantic models for entity extraction validation.

Defines the data structures for entity extraction output,
person records, and alias records used throughout the
entity extraction pipeline.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TranscriptEntityOutput(BaseModel):
    """Validated output for a single person entity extracted from a transcript."""

    person_id: str
    canonical_name: str
    mention_count: int = Field(ge=1)
    max_confidence: float = Field(ge=0.0, le=1.0)
    evidence_sample: str = Field(max_length=200)
    first_seen_char: int | None = None


class EntityExtractionResult(BaseModel):
    """Complete extraction result for a single transcript file."""

    file_path: str
    entities: list[TranscriptEntityOutput]
    extraction_version: str = "6.1.0"
    status: str = "entities_done"  # entities_done | error | blocked_entity_extraction


class PersonRecord(BaseModel):
    """A canonical person in the registry."""

    person_id: str
    canonical_name: str
    type: str  # philosopher | ari_instructor


class AliasRecord(BaseModel):
    """An alias mapping to a canonical person."""

    alias_text: str
    person_id: str
    alias_type: str
    is_blocked: bool = False
