"""Gemini File Search API client wrapper.

Implements the two-step upload pattern:
  1. ``client.aio.files.upload()`` -- creates a temporary File (48hr TTL)
  2. Poll ``client.aio.files.get()`` until ``state.name == "ACTIVE"``
  3. ``client.aio.file_search_stores.import_file()`` with ``custom_metadata``

This is the **only** way to attach searchable metadata to indexed files.
The single-step ``upload_to_file_search_store()`` method does not support
``custom_metadata`` in its documented config.
"""

from __future__ import annotations

import logging
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from tenacity import (
    AsyncRetrying,
    retry_if_result,
    stop_after_delay,
    wait_exponential,
)

from objlib.models import MetadataQuality
from objlib.upload.circuit_breaker import RollingWindowCircuitBreaker
from objlib.upload.rate_limiter import AdaptiveRateLimiter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class RateLimitError(Exception):
    """Raised when the Gemini API returns a 429 rate-limit response."""


class TransientError(Exception):
    """Raised on transient server errors (5xx) that may succeed on retry."""


class PermanentError(Exception):
    """Raised on permanent client errors (4xx except 429) that should not be retried."""


# ---------------------------------------------------------------------------
# Quality score mapping
# ---------------------------------------------------------------------------

_QUALITY_SCORE_MAP: dict[str, int] = {
    MetadataQuality.COMPLETE.value: 100,
    MetadataQuality.PARTIAL.value: 75,
    MetadataQuality.MINIMAL.value: 50,
    MetadataQuality.NONE.value: 25,
    MetadataQuality.UNKNOWN.value: 0,
    # Also accept enum members directly
    "COMPLETE": 100,
    "PARTIAL": 75,
    "MINIMAL": 50,
    "NONE": 25,
    "UNKNOWN": 0,
}


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GeminiFileSearchClient:
    """Wrapper around the google-genai SDK for File Search operations.

    Integrates with a :class:`RollingWindowCircuitBreaker` and
    :class:`AdaptiveRateLimiter` to provide resilient API access.

    Usage::

        cb = RollingWindowCircuitBreaker()
        rl = AdaptiveRateLimiter(RateLimiterConfig(), cb)
        client = GeminiFileSearchClient(api_key="...", circuit_breaker=cb, rate_limiter=rl)
        await client.get_or_create_store("objectivism-library-v1")
        file_obj, operation = await client.upload_and_import(
            file_path="/path/to/file.txt",
            display_name="My File",
            metadata=[{"key": "course", "string_value": "OPAR"}],
        )
    """

    def __init__(
        self,
        api_key: str,
        circuit_breaker: RollingWindowCircuitBreaker,
        rate_limiter: AdaptiveRateLimiter,
        store_name: str | None = None,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._circuit_breaker = circuit_breaker
        self._rate_limiter = rate_limiter
        self.store_name = store_name

    # ------------------------------------------------------------------
    # Store management
    # ------------------------------------------------------------------

    async def create_store(self, display_name: str) -> str:
        """Create a new File Search store.

        Args:
            display_name: Human-readable store name.

        Returns:
            The Gemini store resource name (e.g. ``fileSearchStores/abc123``).
        """
        store = await self._safe_call(
            self._client.aio.file_search_stores.create,
            config={"display_name": display_name},
        )
        logger.info("Created store %s (%s)", store.name, display_name)
        return store.name

    async def get_or_create_store(self, display_name: str) -> str:
        """Find an existing store by display name or create one.

        Saves the resolved store name on ``self.store_name``.

        Args:
            display_name: The display name to search for.

        Returns:
            The Gemini store resource name.
        """
        try:
            stores = await self._client.aio.file_search_stores.list()
            async for store in stores:
                if getattr(store, "display_name", None) == display_name:
                    self.store_name = store.name
                    logger.info("Found existing store %s (%s)", store.name, display_name)
                    return store.name
        except Exception:
            logger.debug("Could not list stores, will create new", exc_info=True)

        name = await self.create_store(display_name)
        self.store_name = name
        return name

    # ------------------------------------------------------------------
    # Two-step upload pattern
    # ------------------------------------------------------------------

    async def upload_file(self, file_path: str, display_name: str) -> Any:
        """Step 1: Upload a file to the Files API (temporary, 48hr TTL).

        Args:
            file_path: Local path to the file.
            display_name: Display name (max 512 chars).

        Returns:
            The Gemini File object.
        """
        await self._rate_limiter.wait_if_needed()
        result = await self._safe_call(
            self._client.aio.files.upload,
            file=file_path,
            config={"display_name": display_name[:512]},
        )
        logger.debug("Uploaded file %s -> %s", file_path, result.name)
        return result

    async def wait_for_active(self, file_obj: Any, timeout: int = 300) -> Any:
        """Step 2: Poll until the uploaded file reaches ACTIVE state.

        Args:
            file_obj: File object returned by :meth:`upload_file`.
            timeout: Maximum seconds to wait.

        Returns:
            The active File object.

        Raises:
            RuntimeError: If the file transitions to FAILED state.
        """
        async for attempt in AsyncRetrying(
            wait=wait_exponential(min=2, max=30),
            stop=stop_after_delay(timeout),
            retry=retry_if_result(lambda f: getattr(f, "state", None) and f.state.name == "PROCESSING"),
            reraise=True,
        ):
            with attempt:
                file_obj = await self._client.aio.files.get(name=file_obj.name)
                if hasattr(file_obj, "state"):
                    if file_obj.state.name == "FAILED":
                        raise RuntimeError(
                            f"File processing failed: {file_obj.name}"
                        )
                    if file_obj.state.name == "PROCESSING":
                        return file_obj  # tenacity retries
                return file_obj  # ACTIVE or no state attribute

        return file_obj

    async def import_to_store(
        self, file_name: str, metadata: list[dict[str, Any]]
    ) -> Any:
        """Step 3: Import a file into the File Search store with metadata.

        Args:
            file_name: The Gemini file resource name from step 1.
            metadata: Custom metadata list in Gemini format (see
                :meth:`build_custom_metadata`).

        Returns:
            The Operation object.

        Raises:
            RuntimeError: If ``store_name`` has not been set.
        """
        if not self.store_name:
            raise RuntimeError(
                "store_name not set -- call get_or_create_store() first"
            )

        await self._rate_limiter.wait_if_needed()
        operation = await self._safe_call(
            self._client.aio.file_search_stores.import_file,
            file_search_store_name=self.store_name,
            file_name=file_name,
            config={"custom_metadata": metadata},
        )
        logger.debug("Imported %s into store %s", file_name, self.store_name)
        return operation

    async def upload_and_import(
        self,
        file_path: str,
        display_name: str,
        metadata: list[dict[str, Any]],
    ) -> tuple[Any, Any]:
        """Full two-step upload: upload -> wait ACTIVE -> import with metadata.

        Args:
            file_path: Local file path.
            display_name: Display name for the file.
            metadata: Custom metadata list.

        Returns:
            Tuple of ``(file_obj, operation)``.
        """
        file_obj = await self.upload_file(file_path, display_name)
        file_obj = await self.wait_for_active(file_obj)
        operation = await self.import_to_store(file_obj.name, metadata)
        return file_obj, operation

    # ------------------------------------------------------------------
    # Operation polling
    # ------------------------------------------------------------------

    async def poll_operation(self, operation: Any, timeout: int = 3600) -> Any:
        """Poll a long-running operation until done.

        Uses exponential backoff: 5s -> 10s -> 20s -> 40s -> 60s (cap).

        Args:
            operation: Operation object from :meth:`import_to_store`.
            timeout: Maximum seconds to wait.

        Returns:
            Completed operation.
        """
        async for attempt in AsyncRetrying(
            wait=wait_exponential(multiplier=1, min=5, max=60),
            stop=stop_after_delay(timeout),
            retry=retry_if_result(lambda op: not getattr(op, "done", True)),
            reraise=True,
        ):
            with attempt:
                operation = await self._client.aio.operations.get(operation)
                if not getattr(operation, "done", True):
                    return operation  # tenacity retries
                return operation

        return operation

    async def delete_file(self, file_name: str) -> None:
        """Delete a raw file from the Gemini Files API (temporary, 48hr TTL).

        .. warning::

            This only removes the temporary uploaded File object, **not** the
            indexed store document.  To remove an entry from the search index
            use :meth:`delete_store_document` instead.

        Args:
            file_name: The Gemini file resource name (e.g., 'files/xyz123').

        Raises:
            RateLimitError: If the API returns a 429 response.
            TransientError: On 5xx server errors.
            PermanentError: On 4xx client errors (except 429).
        """
        await self._safe_call(
            self._client.aio.files.delete,
            name=file_name,
        )
        logger.info("Deleted file %s from Gemini", file_name)

    # ------------------------------------------------------------------
    # Store document management
    # ------------------------------------------------------------------

    async def delete_store_document(self, document_name: str) -> bool:
        """Delete an indexed document from the File Search store.

        Unlike :meth:`delete_file` which deletes the temporary raw File
        (48hr TTL), this removes the **indexed** content that persists
        indefinitely in the search store.  Per locked decision #6,
        404 = success (document already gone).

        Args:
            document_name: Full resource name, e.g.
                ``'fileSearchStores/abc123/documents/doc456'``

        Returns:
            ``True`` if deleted (or already gone), ``False`` on unexpected
            error.
        """
        try:
            await self._safe_call(
                self._client.aio.file_search_stores.documents.delete,
                name=document_name,
                config=genai_types.DeleteDocumentConfig(force=True),
            )
            logger.info("Deleted store document: %s", document_name)
            return True
        except Exception as exc:
            # 404 = document already gone (TTL expiry or prior cleanup)
            exc_str = str(exc)
            if (
                "404" in exc_str
                or "NOT_FOUND" in exc_str
                or "not found" in exc_str.lower()
            ):
                logger.info(
                    "Store document already deleted (404): %s", document_name
                )
                return True
            logger.error(
                "Failed to delete store document %s: %s", document_name, exc
            )
            return False

    async def list_store_documents(
        self, store_name: str | None = None
    ) -> list[Any]:
        """List all documents in a File Search store.

        Used to discover document resource names for deletion, since
        :meth:`import_to_store` does not return the document resource name.

        Args:
            store_name: Store resource name (e.g. ``'fileSearchStores/abc123'``).
                Uses ``self.store_name`` if not provided.

        Returns:
            List of :class:`~google.genai.types.Document` objects.

        Raises:
            RuntimeError: If no ``store_name`` is available.
        """
        parent = store_name or self.store_name
        if not parent:
            raise RuntimeError(
                "store_name not set -- call get_or_create_store() first"
            )

        documents: list[Any] = []
        try:
            pager = await self._safe_call(
                self._client.aio.file_search_stores.documents.list,
                parent=parent,
            )
            async for doc in pager:
                documents.append(doc)
        except Exception as exc:
            logger.error(
                "Failed to list store documents for %s: %s", parent, exc
            )
            raise
        logger.info(
            "Listed %d documents in store %s", len(documents), parent
        )
        return documents

    async def find_store_document_name(
        self, gemini_file_id: str, store_name: str | None = None
    ) -> str | None:
        """Find the store document resource name for a given file ID.

        The Gemini API does not directly map file IDs to document names.
        This method lists all documents and finds the one whose
        ``display_name`` matches the file's display name.

        Args:
            gemini_file_id: Gemini file resource name (e.g. ``'files/xyz789'``).
            store_name: Optional override for store resource name.

        Returns:
            Full document resource name
            (e.g. ``'fileSearchStores/abc/documents/def'``)
            or ``None`` if not found.
        """
        documents = await self.list_store_documents(store_name)

        # Normalize the file ID for comparison
        normalized_id = gemini_file_id
        if not normalized_id.startswith("files/"):
            normalized_id = f"files/{normalized_id}"

        for doc in documents:
            # Check display_name, name, and other attributes for the file reference
            for attr in ("display_name", "name"):
                val = getattr(doc, attr, None)
                if val and normalized_id in str(val):
                    return doc.name if hasattr(doc, "name") else str(doc)

            # Also check if the document name contains the file ID suffix
            doc_name = getattr(doc, "name", "")
            file_id_suffix = normalized_id.replace("files/", "")
            if file_id_suffix and file_id_suffix in doc_name:
                return doc_name

        logger.warning(
            "Could not find store document for file %s in store %s",
            gemini_file_id,
            store_name or self.store_name,
        )
        return None

    # ------------------------------------------------------------------
    # Metadata helper
    # ------------------------------------------------------------------

    @staticmethod
    def build_custom_metadata(metadata_dict: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert a flat metadata dict to Gemini ``custom_metadata`` format.

        Maps to Tier 1 searchable fields only:

        * ``category`` -> string_value
        * ``course`` -> string_value
        * ``difficulty`` -> string_value
        * ``year`` -> numeric_value (if numeric)
        * ``quarter`` -> string_value
        * ``quality_score`` -> numeric_value (mapped from MetadataQuality)
        * ``date`` -> string_value
        * ``week`` -> numeric_value (if numeric)

        Only keys with non-``None`` values are included.

        Args:
            metadata_dict: Flat dictionary of metadata fields.

        Returns:
            List of ``{"key": ..., "string_value"|"numeric_value": ...}``
            dicts suitable for the Gemini ``custom_metadata`` parameter.
        """
        result: list[dict[str, Any]] = []

        string_fields = ("category", "course", "difficulty", "quarter", "date")
        for key in string_fields:
            val = metadata_dict.get(key)
            if val is not None:
                result.append({"key": key, "string_value": str(val)})

        # Numeric fields
        for key in ("year", "week"):
            val = metadata_dict.get(key)
            if val is not None:
                try:
                    result.append({"key": key, "numeric_value": int(val)})
                except (ValueError, TypeError):
                    pass

        # quality_score: map from MetadataQuality string to numeric score
        qs = metadata_dict.get("quality_score")
        if qs is not None:
            score = _QUALITY_SCORE_MAP.get(str(qs))
            if score is not None:
                result.append({"key": "quality_score", "numeric_value": score})

        return result

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying genai client if it supports closing."""
        if hasattr(self._client, "close") and callable(self._client.close):
            result = self._client.close()
            # Only await if it returns a coroutine
            if result is not None and hasattr(result, "__await__"):
                await result
        elif hasattr(self._client, "aclose") and callable(self._client.aclose):
            result = self._client.aclose()
            if result is not None and hasattr(result, "__await__"):
                await result

    # ------------------------------------------------------------------
    # Internal: safe API call with circuit breaker integration
    # ------------------------------------------------------------------

    async def _safe_call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Call *func* and record success/failure on the circuit breaker.

        On 429 errors: records on circuit breaker and raises
        :class:`RateLimitError`.  On other API errors: records and
        re-raises.  On success: records success.
        """
        try:
            result = await func(*args, **kwargs)
            self._circuit_breaker.record_success()
            return result
        except genai_errors.APIError as exc:
            if exc.code == 429:
                self._circuit_breaker.record_429()
                raise RateLimitError(
                    f"429 rate limit: {exc.message}"
                ) from exc
            else:
                self._circuit_breaker.record_error()
                raise
        except Exception:
            self._circuit_breaker.record_error()
            raise
