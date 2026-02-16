"""Search subpackage for querying Gemini File Search stores."""

from objlib.search.citations import enrich_citations, extract_citations
from objlib.search.client import GeminiSearchClient
from objlib.search.formatter import (
    display_detailed_view,
    display_search_results,
    score_bar,
)

__all__ = [
    "GeminiSearchClient",
    "extract_citations",
    "enrich_citations",
    "score_bar",
    "display_search_results",
    "display_detailed_view",
]
