"""Idempotent delete wrappers for Gemini API resources.

Both wrappers treat HTTP 404 as success (resource already gone = idempotent
delete). All other errors propagate to the caller.

GA-2: safe_delete wrappers catch ClientError with code==404 as success.
"""

from collections.abc import Callable

from google.genai import errors as genai_errors


async def safe_delete_store_document(
    delete_fn: Callable, document_name: str
) -> bool:
    """Safely delete a store document. 404 = success (already gone).

    Args:
        delete_fn: Async callable that deletes the store document.
        document_name: Store document resource name.

    Returns:
        True on success (including 404).

    Raises:
        google.genai.errors.ClientError: For non-404 errors (e.g., 403).
    """
    try:
        await delete_fn(document_name)
        return True
    except genai_errors.ClientError as exc:
        if exc.code == 404:
            return True
        raise


async def safe_delete_file(
    delete_fn: Callable, file_name: str
) -> bool:
    """Safely delete a raw Gemini file. 404 = success (already gone).

    Args:
        delete_fn: Async callable that deletes the file.
        file_name: File resource name (e.g., "files/abc123").

    Returns:
        True on success (including 404).

    Raises:
        google.genai.errors.ClientError: For non-404 errors (e.g., 403).
    """
    try:
        await delete_fn(file_name)
        return True
    except genai_errors.ClientError as exc:
        if exc.code == 404:
            return True
        raise
