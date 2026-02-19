"""Search service facade wrapping Gemini File Search internals.

Provides async methods for search and synthesis. All Gemini API
and SQLite calls are wrapped in asyncio.to_thread() to avoid
blocking the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from objlib.models import Citation, SearchResult
from objlib.search.citations import (
    build_metadata_filter,
    enrich_citations,
    extract_citations,
)
from objlib.search.expansion import expand_query
from objlib.search.reranker import apply_difficulty_ordering, rerank_passages
from objlib.search.synthesizer import apply_mmr_diversity, synthesize_answer

if TYPE_CHECKING:
    from objlib.search.models import SynthesisOutput

logger = logging.getLogger(__name__)


class SearchService:
    """Async facade for Gemini File Search queries and synthesis.

    Wraps GeminiSearchClient, citation extraction/enrichment,
    reranking, and synthesis into async methods suitable for
    the Textual TUI event loop.

    Usage::

        svc = SearchService(api_key="...", store_resource_name="...", db_path="data/library.db")
        result = await svc.search("What is the nature of rights?")
        synthesis = await svc.synthesize(result.query, result.citations)
    """

    def __init__(
        self,
        api_key: str,
        store_resource_name: str,
        db_path: str,
    ) -> None:
        self._api_key = api_key
        self._store_resource_name = store_resource_name
        self._db_path = db_path
        self._client = None  # genai.Client, lazily initialized
        self._search_client = None  # GeminiSearchClient, lazily initialized

    def _ensure_client(self) -> None:
        """Lazily initialize genai.Client and GeminiSearchClient."""
        if self._client is not None:
            return

        from google import genai

        from objlib.search.client import GeminiSearchClient

        self._client = genai.Client(api_key=self._api_key)
        self._search_client = GeminiSearchClient(
            self._client, self._store_resource_name
        )

    async def search(
        self,
        query: str,
        filters: list[str] | None = None,
        expand: bool = True,
        rerank: bool = True,
        mode: str = "learn",
    ) -> SearchResult:
        """Execute a search query against the Gemini File Search store.

        Args:
            query: Natural language search query.
            filters: Optional list of "field:value" filter strings.
            expand: Whether to expand the query with glossary synonyms.
            rerank: Whether to rerank results with Gemini Flash.
            mode: "learn" for difficulty ordering, "research" for pure relevance.

        Returns:
            SearchResult with response text, enriched citations, query, and filter.
        """
        self._ensure_client()

        # Expand query (CPU-only, fast, run inline)
        search_query = query
        if expand:
            search_query, _ = expand_query(query)

        # Build metadata filter
        metadata_filter = build_metadata_filter(filters) if filters else None

        # Query Gemini (blocking I/O -> thread)
        response = await asyncio.to_thread(
            self._search_client.query_with_retry,
            search_query,
            metadata_filter=metadata_filter,
        )

        # Extract citations from grounding metadata
        grounding_metadata = None
        if response.candidates:
            grounding_metadata = getattr(
                response.candidates[0], "grounding_metadata", None
            )
        citations = extract_citations(grounding_metadata)

        # Enrich citations with local SQLite metadata (blocking I/O -> thread)
        if citations:

            def _enrich(cites: list[Citation]) -> list[Citation]:
                from objlib.database import Database

                with Database(self._db_path) as db:
                    return enrich_citations(cites, db)

            citations = await asyncio.to_thread(_enrich, citations)

        # Rerank (Gemini API call -> thread)
        if rerank and len(citations) > 1:
            citations = await asyncio.to_thread(
                rerank_passages, self._client, query, citations
            )

        # Apply difficulty ordering (CPU-only, inline)
        citations = apply_difficulty_ordering(citations, mode=mode)

        # Extract response text
        response_text = ""
        if response.candidates and response.candidates[0].content:
            parts = response.candidates[0].content.parts
            if parts:
                response_text = parts[0].text or ""

        return SearchResult(
            response_text=response_text,
            citations=citations,
            query=query,
            metadata_filter=metadata_filter,
        )

    async def synthesize(
        self,
        query: str,
        citations: list[Citation],
    ) -> SynthesisOutput | None:
        """Synthesize a structured answer from search citations.

        Args:
            query: The original search query.
            citations: List of Citation objects from search results.

        Returns:
            SynthesisOutput with cited claims, or None on failure
            (too few citations, API error, validation failure).
        """
        self._ensure_client()

        # Apply MMR diversity (CPU-only, inline)
        diverse_citations = apply_mmr_diversity(citations)

        # Synthesize (Gemini API call -> thread)
        result = await asyncio.to_thread(
            synthesize_answer, self._client, query, diverse_citations
        )

        return result
