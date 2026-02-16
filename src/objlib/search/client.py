"""Gemini File Search query client with retry logic.

Provides a synchronous client for querying Gemini File Search stores
via ``generate_content()`` with the ``FileSearch`` tool. Includes
automatic retry with exponential backoff and jitter.
"""

from __future__ import annotations

import logging
from typing import Any

from google import genai
from google.genai import types
from rich.console import Console
from tenacity import (
    RetryCallState,
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger(__name__)
console = Console()


def _log_retry(retry_state: RetryCallState) -> None:
    """Display retry status via Rich console."""
    attempt = retry_state.attempt_number
    console.print(f"[yellow]Retrying search ({attempt}/3)...[/yellow]")


class GeminiSearchClient:
    """Client for querying Gemini File Search stores.

    Wraps ``client.models.generate_content()`` with a ``FileSearch`` tool
    and provides retry logic with exponential backoff + jitter.

    Usage::

        client = genai.Client(api_key="...")
        store_name = GeminiSearchClient.resolve_store_name(client, "my-store")
        search = GeminiSearchClient(client, store_name)
        response = search.query_with_retry("What is the nature of rights?")
    """

    def __init__(self, client: genai.Client, store_resource_name: str) -> None:
        self._client = client
        self._store_resource_name = store_resource_name

    def query(
        self,
        query: str,
        metadata_filter: str | None = None,
        model: str = "gemini-2.5-flash",
    ) -> Any:
        """Query the File Search store via generate_content.

        Args:
            query: Natural language search query.
            metadata_filter: Optional AIP-160 filter string.
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
                    )
                )
            ],
        )

        return self._client.models.generate_content(
            model=model,
            contents=query,
            config=config,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=0.5, max=2.0, jitter=0.5),
        before_sleep=_log_retry,
        reraise=True,
    )
    def query_with_retry(
        self,
        query: str,
        metadata_filter: str | None = None,
        model: str = "gemini-2.5-flash",
    ) -> Any:
        """Query with automatic retry (3 attempts, exponential backoff + jitter).

        Uses tenacity with ``wait_exponential_jitter(initial=0.5, max=2.0, jitter=0.5)``
        giving waits around 0.5s, 1s, 2s with +/-50% jitter.

        Args:
            query: Natural language search query.
            metadata_filter: Optional AIP-160 filter string.
            model: Gemini model to use.

        Returns:
            GenerateContentResponse from Gemini.

        Raises:
            Exception: After 3 failed attempts, the last exception is reraised.
        """
        return self.query(query, metadata_filter=metadata_filter, model=model)

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
