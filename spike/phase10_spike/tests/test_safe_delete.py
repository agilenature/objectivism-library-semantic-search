"""Tests for safe_delete wrappers (GA-2: 404 = success, other errors propagate)."""

import pytest
from unittest.mock import AsyncMock

from google.genai import errors as genai_errors

from spike.phase10_spike.safe_delete import safe_delete_file, safe_delete_store_document


@pytest.mark.asyncio
async def test_safe_delete_store_doc_success():
    """Normal deletion returns True."""
    delete_fn = AsyncMock(return_value=None)
    result = await safe_delete_store_document(delete_fn, "stores/s1/documents/d1")
    assert result is True
    delete_fn.assert_awaited_once_with("stores/s1/documents/d1")


@pytest.mark.asyncio
async def test_safe_delete_store_doc_404_is_success():
    """404 ClientError is treated as success (resource already gone)."""
    exc = genai_errors.ClientError(404, {}, None)
    delete_fn = AsyncMock(side_effect=exc)
    result = await safe_delete_store_document(delete_fn, "stores/s1/documents/d1")
    assert result is True


@pytest.mark.asyncio
async def test_safe_delete_store_doc_other_error_propagates():
    """Non-404 ClientError (e.g., 403 Forbidden) propagates to caller."""
    exc = genai_errors.ClientError(403, {}, None)
    delete_fn = AsyncMock(side_effect=exc)
    with pytest.raises(genai_errors.ClientError) as exc_info:
        await safe_delete_store_document(delete_fn, "stores/s1/documents/d1")
    assert exc_info.value.code == 403


@pytest.mark.asyncio
async def test_safe_delete_file_404_is_success():
    """404 ClientError on file deletion is treated as success."""
    exc = genai_errors.ClientError(404, {}, None)
    delete_fn = AsyncMock(side_effect=exc)
    result = await safe_delete_file(delete_fn, "files/test123")
    assert result is True
