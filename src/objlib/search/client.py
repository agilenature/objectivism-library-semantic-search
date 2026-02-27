"""Gemini File Search query client with retry logic.

Provides a client for querying Gemini File Search stores via
``generate_content()`` with the ``FileSearch`` tool. Includes
automatic retry with exponential backoff via RxPY observable.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from google import genai
from google.genai import types
from rich.console import Console

from objlib.upload._operators import make_retrying_observable, subscribe_awaitable

logger = logging.getLogger(__name__)
console = Console()


class GeminiSearchClient:
    """Client for querying Gemini File Search stores.

    Wraps ``client.models.generate_content()`` with a ``FileSearch`` tool
    and provides retry logic with exponential backoff + jitter.

    Usage::

        client = genai.Client(api_key="...")
        store_name = GeminiSearchClient.resolve_store_name(client, "my-store")
        search = GeminiSearchClient(client, store_name)
        response = await search.query_with_retry("What is the nature of rights?")
    """

    def __init__(self, client: genai.Client, store_resource_name: str) -> None:
        self._client = client
        self._store_resource_name = store_resource_name

    def query(
        self,
        query: str,
        metadata_filter: str | None = None,
        top_k: int = 20,
        model: str = "gemini-2.5-flash",
    ) -> Any:
        """Query the File Search store via generate_content.

        Args:
            query: Natural language search query.
            metadata_filter: Optional AIP-160 filter string.
            top_k: Maximum number of citation chunks to retrieve (default 20).
            model: Gemini model to use.

        Returns:
            GenerateContentResponse from Gemini.
        """
        config = types.GenerateContentConfig(
            tools=[
                types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[self._store_resource_name],
                        metadata_filter=metadata_filter,
                        top_k=top_k,
                    )
                )
            ],
        )

        return self._client.models.generate_content(
            model=model,
            contents=query,
            config=config,
        )

    async def query_with_retry(
        self,
        query: str,
        metadata_filter: str | None = None,
        top_k: int = 20,
        model: str = "gemini-2.5-flash",
    ) -> Any:
        """Query with automatic retry (3 attempts, exponential backoff).

        Uses RxPY make_retrying_observable with exponential backoff
        (base_delay=0.5s, delays ~0.5s, 1s, 2s).

        The sync ``query()`` call is offloaded to a thread executor to
        avoid blocking the event loop.

        Args:
            query: Natural language search query.
            metadata_filter: Optional AIP-160 filter string.
            top_k: Maximum number of citation chunks to retrieve (default 20).
            model: Gemini model to use.

        Returns:
            GenerateContentResponse from Gemini.

        Raises:
            Exception: After 3 failed attempts, the last exception is reraised.
        """
        loop = asyncio.get_event_loop()

        async def _attempt() -> Any:
            result = await loop.run_in_executor(
                None,
                lambda: self.query(
                    query, metadata_filter=metadata_filter, top_k=top_k, model=model
                ),
            )
            return result

        obs = make_retrying_observable(_attempt, max_retries=2, base_delay=0.5)
        return await subscribe_awaitable(obs)

    @staticmethod
    def resolve_store_name(client: genai.Client, display_name: str) -> str:
        """Resolve a store display name to its Gemini resource name.

        Lists all File Search stores and finds the one matching
        ``display_name``.

        Args:
            client: Authenticated genai.Client.
            display_name: Human-readable store name (e.g. "objectivism-library-v1").

        Returns:
            The Gemini store resource name (e.g. "fileSearchStores/abc123").

        Raises:
            ValueError: If no store with the given display name is found.
        """
        for store in client.file_search_stores.list():
            if getattr(store, "display_name", None) == display_name:
                logger.info(
                    "Resolved store '%s' -> %s", display_name, store.name
                )
                return store.name

        raise ValueError(
            f"No File Search store found with display name '{display_name}'. "
            f"Run 'objlib upload' first to create the store."
        )
