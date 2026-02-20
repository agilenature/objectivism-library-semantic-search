"""Tests for 3 crash points in the reset transition (GA-5).

Each test proves that if the process crashes at a specific point during
the INDEXED -> UNTRACKED reset, the DB records exactly which step
completed, enabling deterministic recovery (Plan 10-02).

Crash points:
  1. After delete_store_document, before delete_file
  2. After both API calls, before Txn B finalizes
  3. Txn B itself fails (identical to crash point 2 from recovery perspective)

All 3 tests verify:
  (a) gemini_state is still 'indexed' (not stuck in some intermediate)
  (b) intent columns record exactly which step completed
  (c) version has NOT incremented (Txn B never ran)
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from spike.phase10_spike.db import read_file_full
from spike.phase10_spike.transition_reset import ResetTransitionManager


@pytest.mark.asyncio
async def test_crash_point_1_after_store_doc_delete(spike_db, seed_indexed_file):
    """Crash after delete_store_document but before delete_file.

    DB should show: gemini_state='indexed', intent_type='reset_intent',
    intent_api_calls_completed=1. Version unchanged.
    """
    file_path = await seed_indexed_file()

    # delete_store_doc succeeds, but delete_file crashes
    manager = ResetTransitionManager(
        db_path=spike_db,
        delete_store_doc_fn=AsyncMock(return_value=None),
        delete_file_fn=AsyncMock(side_effect=RuntimeError("crash after API call 1")),
    )

    with pytest.raises(RuntimeError, match="crash after API call 1"):
        await manager.execute_reset(file_path)

    # Verify DB state
    row = await read_file_full(spike_db, file_path)
    assert row["gemini_state"] == "indexed", "State should still be 'indexed'"
    assert row["intent_type"] == "reset_intent", "Intent should be recorded"
    assert row["intent_api_calls_completed"] == 1, "Only API call 1 completed"
    assert row["version"] == 5, "Version should NOT have incremented"
    # Gemini IDs still present (not cleared until Txn B)
    assert row["gemini_file_id"] == "files/test123"
    assert row["gemini_store_doc_id"] == "fileSearchStores/store1/documents/doc1"


@pytest.mark.asyncio
async def test_crash_point_2_after_both_apis_before_txn_b(spike_db, seed_indexed_file):
    """Crash after both API calls succeed but before Txn B finalizes.

    DB should show: gemini_state='indexed', intent_type='reset_intent',
    intent_api_calls_completed=2. Version unchanged.
    """
    file_path = await seed_indexed_file()

    manager = ResetTransitionManager(
        db_path=spike_db,
        delete_store_doc_fn=AsyncMock(return_value=None),
        delete_file_fn=AsyncMock(return_value=None),
    )

    # Mock finalize_reset to raise CancelledError (simulating crash before Txn B)
    # CancelledError is a BaseException, not Exception
    with patch(
        "spike.phase10_spike.transition_reset.finalize_reset",
        side_effect=asyncio.CancelledError("crash before Txn B"),
    ):
        with pytest.raises(BaseException):
            await manager.execute_reset(file_path)

    # Verify DB state
    row = await read_file_full(spike_db, file_path)
    assert row["gemini_state"] == "indexed", "State should still be 'indexed'"
    assert row["intent_type"] == "reset_intent", "Intent should be recorded"
    assert row["intent_api_calls_completed"] == 2, "Both API calls completed"
    assert row["version"] == 5, "Version should NOT have incremented"


@pytest.mark.asyncio
async def test_crash_point_3_txn_b_fails(spike_db, seed_indexed_file):
    """Txn B itself fails (DB error during finalize).

    DB state should be identical to crash point 2: gemini_state='indexed',
    intent_type='reset_intent', intent_api_calls_completed=2. Version unchanged.
    This proves crash point 3 is equivalent to crash point 2 from a recovery
    perspective.
    """
    file_path = await seed_indexed_file()

    manager = ResetTransitionManager(
        db_path=spike_db,
        delete_store_doc_fn=AsyncMock(return_value=None),
        delete_file_fn=AsyncMock(return_value=None),
    )

    # Mock finalize_reset to raise RuntimeError (simulating DB crash during Txn B)
    with patch(
        "spike.phase10_spike.transition_reset.finalize_reset",
        side_effect=RuntimeError("DB crash during Txn B"),
    ):
        with pytest.raises(RuntimeError, match="DB crash during Txn B"):
            await manager.execute_reset(file_path)

    # Verify DB state
    row = await read_file_full(spike_db, file_path)
    assert row["gemini_state"] == "indexed", "State should still be 'indexed'"
    assert row["intent_type"] == "reset_intent", "Intent should be recorded"
    assert row["intent_api_calls_completed"] == 2, "Both API calls completed"
    assert row["version"] == 5, "Version should NOT have incremented"
    # Gemini IDs still present (not cleared)
    assert row["gemini_file_id"] == "files/test123"
    assert row["gemini_store_doc_id"] == "fileSearchStores/store1/documents/doc1"
