"""Search subpackage for querying Gemini File Search stores."""

from objlib.search.citations import enrich_citations, extract_citations
from objlib.search.client import GeminiSearchClient
from objlib.search.expansion import expand_query, load_glossary
from objlib.search.formatter import (
    display_concept_evolution,
    display_detailed_view,
    display_search_results,
    display_synthesis,
    score_bar,
)
from objlib.search.reranker import apply_difficulty_ordering, rerank_passages
from objlib.search.synthesizer import apply_mmr_diversity, synthesize_answer, validate_citations

__all__ = [
    "GeminiSearchClient",
    "extract_citations",
    "enrich_citations",
    "score_bar",
    "display_search_results",
    "display_detailed_view",
    "display_synthesis",
    "display_concept_evolution",
    "expand_query",
    "load_glossary",
    "rerank_passages",
    "apply_difficulty_ordering",
    "synthesize_answer",
    "apply_mmr_diversity",
    "validate_citations",
]
