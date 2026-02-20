"""Tests for FAILED -> UNTRACKED retry escape path (GA-4).

Proves that files stuck in 'failed' state can be transitioned back to
'untracked' via retry_failed_file() without manual SQL. Also proves
that calling retry on a non-failed file is a safe no-op.
"""

import pytest

from spike.phase10_spike.db import read_file_full
from spike.phase10_spike.recovery_crawler import retry_failed_file


@pytest.mark.asyncio
async def test_failed_to_untracked(spike_db, seed_failed_file):
    """A failed file transitions to untracked via retry_failed_file().

    Verifies: returns True, gemini_state='untracked', version incremented
    (was 3, now 4), all intent/Gemini ID columns cleared.
    """
    file_path = await seed_failed_file()

    result = await retry_failed_file(spike_db, file_path)

    assert result is True
    row = await read_file_full(spike_db, file_path)
    assert row["gemini_state"] == "untracked"
    assert row["version"] == 4  # Was 3, incremented by retry
    assert row["gemini_file_id"] is None
    assert row["gemini_store_doc_id"] is None
    assert row["intent_type"] is None
    assert row["intent_started_at"] is None
    assert row["intent_api_calls_completed"] is None


@pytest.mark.asyncio
async def test_retry_wrong_state_noop(spike_db, seed_indexed_file):
    """Calling retry_failed_file on a non-failed file returns False (no-op).

    The file's state and version remain unchanged.
    """
    file_path = await seed_indexed_file()

    result = await retry_failed_file(spike_db, file_path)

    assert result is False
    row = await read_file_full(spike_db, file_path)
    assert row["gemini_state"] == "indexed"  # Unchanged
    assert row["version"] == 5  # Unchanged
