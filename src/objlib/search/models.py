"""Pydantic v2 models for Gemini Flash structured output.

Used as response_schema in GenerateContentConfig for reranking
and synthesis pipelines. Separate from objlib.models (dataclasses).
"""

from pydantic import BaseModel, Field


class RankedPassage(BaseModel):
    """A single passage with its reranking score."""

    passage_index: int = Field(description="0-based index of the passage in the input list")
    score: float = Field(ge=0, le=10, description="Relevance score 0-10")
    reason: str = Field(description="Brief reason for the score")


class RankedResults(BaseModel):
    """Complete reranking output from Gemini Flash."""

    rankings: list[RankedPassage]


class CitationRef(BaseModel):
    """Reference to a specific passage as evidence for a claim."""

    file_id: str = Field(description="File identifier from the source")
    passage_id: str = Field(description="Passage identifier")
    quote: str = Field(
        min_length=20, max_length=300,
        description="Verbatim quote from the passage, 20-60 words",
    )


class Claim(BaseModel):
    """A single factual claim with its citation."""

    claim_text: str = Field(description="One sentence factual assertion")
    citation: CitationRef


class SynthesisOutput(BaseModel):
    """Complete synthesis output with cited claims."""

    claims: list[Claim]
    bridging_intro: str | None = Field(
        default=None, description="Optional uncited introductory sentence"
    )
    bridging_conclusion: str | None = Field(
        default=None, description="Optional uncited concluding sentence"
    )


class TierSynthesis(BaseModel):
    """Single-sentence synthesis for one difficulty tier in concept evolution."""

    tier: str = Field(
        description="Difficulty tier: introductory, intermediate, or advanced"
    )
    summary: str = Field(description="One-sentence synthesis of this tier's content")
