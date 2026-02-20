"""Tests for RecoveryCrawler startup recovery (GA-3).

Proves that files left in partial-intent state from any of the 3 crash points
are automatically recovered to 'untracked' by the RecoveryCrawler.

Test matrix:
  1. Crash point 1 (api_calls_completed=1): needs delete_file + finalize
  2. Crash point 2 (api_calls_completed=2): needs finalize only
  3. Crash point 3 (identical to CP2): confirms equivalent recovery path
  4. Empty DB: recover_all returns empty list, no errors
"""

from unittest.mock import AsyncMock

import aiosqlite
import pytest

from spike.phase10_spike.db import read_file_full
from spike.phase10_spike.recovery_crawler import RecoveryCrawler
from spike.phase10_spike.transition_reset import ResetTransitionManager


@pytest.mark.asyncio
async def test_recovery_crash_point_1(spike_db, seed_indexed_file):
    """Recovery after crash point 1: delete_store_doc succeeded, delete_file crashed.

    ResetTransitionManager leaves DB with api_calls_completed=1.
    RecoveryCrawler should complete the remaining steps (delete_file + finalize).
    """
    file_path = await seed_indexed_file()

    # Simulate crash at point 1: store doc delete succeeds, file delete crashes
    manager = ResetTransitionManager(
        db_path=spike_db,
        delete_store_doc_fn=AsyncMock(return_value=None),
        delete_file_fn=AsyncMock(side_effect=RuntimeError("crash at CP1")),
    )
    with pytest.raises(RuntimeError, match="crash at CP1"):
        await manager.execute_reset(file_path)

    # Verify partial state before recovery
    row = await read_file_full(spike_db, file_path)
    assert row["intent_api_calls_completed"] == 1
    assert row["gemini_state"] == "indexed"

    # Run recovery
    mock_delete_store = AsyncMock(return_value=None)
    mock_delete_file = AsyncMock(return_value=None)
    crawler = RecoveryCrawler(
        db_path=spike_db,
        delete_store_doc_fn=mock_delete_store,
        delete_file_fn=mock_delete_file,
    )
    recovered = await crawler.recover_all()

    # Verify recovery results
    assert file_path in recovered
    row = await read_file_full(spike_db, file_path)
    assert row["gemini_state"] == "untracked"
    assert row["version"] == 6  # Was 5, incremented by finalize_reset
    assert row["intent_type"] is None
    assert row["intent_started_at"] is None
    assert row["intent_api_calls_completed"] is None
    assert row["gemini_file_id"] is None
    assert row["gemini_store_doc_id"] is None

    # delete_store_doc should NOT be called (api_calls_completed was already 1)
    mock_delete_store.assert_not_awaited()
    # delete_file SHOULD be called (api_calls_completed < 2)
    mock_delete_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_recovery_crash_point_2(spike_db):
    """Recovery after crash point 2: both API calls done, finalize never ran.

    Directly seed partial state (api_calls_completed=2). RecoveryCrawler should
    only finalize, without calling any delete functions.
    """
    file_path = "test/cp2_recovery.txt"

    # Seed partial state directly (both API calls completed, no finalize)
    async with aiosqlite.connect(spike_db) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(
            """INSERT INTO files
               (file_path, gemini_state, version, gemini_file_id,
                gemini_store_doc_id, intent_type, intent_started_at,
                intent_api_calls_completed)
               VALUES (?, 'indexed', 5, 'files/test123',
                       'fileSearchStores/store1/documents/doc1',
                       'reset_intent', '2026-02-20T10:00:00Z', 2)""",
            (file_path,),
        )
        await db.commit()

    # Run recovery
    mock_delete_store = AsyncMock(return_value=None)
    mock_delete_file = AsyncMock(return_value=None)
    crawler = RecoveryCrawler(
        db_path=spike_db,
        delete_store_doc_fn=mock_delete_store,
        delete_file_fn=mock_delete_file,
    )
    recovered = await crawler.recover_all()

    # Verify recovery results
    assert file_path in recovered
    row = await read_file_full(spike_db, file_path)
    assert row["gemini_state"] == "untracked"
    assert row["version"] == 6  # Was 5, incremented by finalize_reset
    assert row["intent_type"] is None
    assert row["intent_started_at"] is None
    assert row["intent_api_calls_completed"] is None

    # Neither delete fn should be called (both api calls already completed)
    mock_delete_store.assert_not_awaited()
    mock_delete_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_crash_point_3(spike_db):
    """Recovery after crash point 3: identical DB state to crash point 2.

    CP3 (Txn B failure) leaves the same DB state as CP2 (crash before Txn B).
    This test confirms the recovery path is identical.
    """
    file_path = "test/cp3_recovery.txt"

    # Seed identical partial state as CP2 (api_calls_completed=2)
    async with aiosqlite.connect(spike_db) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(
            """INSERT INTO files
               (file_path, gemini_state, version, gemini_file_id,
                gemini_store_doc_id, intent_type, intent_started_at,
                intent_api_calls_completed)
               VALUES (?, 'indexed', 5, 'files/test456',
                       'fileSearchStores/store1/documents/doc2',
                       'reset_intent', '2026-02-20T10:05:00Z', 2)""",
            (file_path,),
        )
        await db.commit()

    # Run recovery
    mock_delete_store = AsyncMock(return_value=None)
    mock_delete_file = AsyncMock(return_value=None)
    crawler = RecoveryCrawler(
        db_path=spike_db,
        delete_store_doc_fn=mock_delete_store,
        delete_file_fn=mock_delete_file,
    )
    recovered = await crawler.recover_all()

    # Verify identical recovery result to CP2
    assert file_path in recovered
    row = await read_file_full(spike_db, file_path)
    assert row["gemini_state"] == "untracked"
    assert row["version"] == 6
    assert row["intent_type"] is None

    # Neither delete fn called (identical to CP2)
    mock_delete_store.assert_not_awaited()
    mock_delete_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_empty_db(spike_db):
    """Recovery on empty DB: no files with pending intents.

    recover_all() should return empty list without errors.
    """
    crawler = RecoveryCrawler(
        db_path=spike_db,
        delete_store_doc_fn=AsyncMock(),
        delete_file_fn=AsyncMock(),
    )
    recovered = await crawler.recover_all()
    assert recovered == []
