"""Tests for FSM transitions, OCC guards, RecoveryCrawler SC6, and SC3 delete order.

Covers:
  - Test 1: FSM transition validation (legal + illegal transitions)
  - Test 2: transition_to_uploading OCC guard
  - Test 3: Full FSM lifecycle (untracked -> uploading -> processing -> indexed)
  - Test 4: SC6 -- RecoveryCrawler raises on OCC conflict
  - Test 5: SC3 -- _reset_existing_files_fsm deletes store doc before raw file
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from objlib.database import Database
from objlib.upload.exceptions import OCCConflictError
from objlib.upload.fsm import FileLifecycleSM, create_fsm
from objlib.upload.recovery import RecoveryCrawler, retry_failed_file
from objlib.upload.state import AsyncUploadStateManager


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
async def fsm_state(tmp_path: Path):
    """Create a temp database with V10 schema and return an async state manager."""
    db_path = tmp_path / "test_fsm.db"
    # Initialize schema synchronously (creates all tables + V10 columns)
    db = Database(db_path)
    db.conn.close()

    state = AsyncUploadStateManager(str(db_path))
    await state.connect()
    yield state
    await state.close()


async def _insert_test_file(
    state: AsyncUploadStateManager,
    file_path: str = "/test/file.txt",
    gemini_state: str = "untracked",
    version: int = 0,
    gemini_file_id: str | None = None,
    gemini_store_doc_id: str | None = None,
    intent_type: str | None = None,
    intent_api_calls_completed: int | None = None,
    status: str = "pending",
) -> None:
    """Insert a test file row into the database."""
    db = state._ensure_connected()
    await db.execute(
        """INSERT INTO files (
               file_path, content_hash, filename, file_size,
               status, gemini_state, version,
               gemini_file_id, gemini_store_doc_id,
               intent_type, intent_api_calls_completed
           ) VALUES (?, 'hash123', 'file.txt', 1000,
                     ?, ?, ?,
                     ?, ?,
                     ?, ?)""",
        (
            file_path, status, gemini_state, version,
            gemini_file_id, gemini_store_doc_id,
            intent_type, intent_api_calls_completed,
        ),
    )
    await db.commit()


# ======================================================================
# Test 1: FSM transition validation
# ======================================================================


class TestFSMTransitions:
    """Test all 8 legal transitions succeed and illegal ones raise."""

    def test_untracked_to_uploading(self):
        """Legal: untracked -> uploading via start_upload."""
        fsm = create_fsm("untracked")
        fsm.start_upload()
        assert fsm.current_state.value == "uploading"

    def test_uploading_to_processing(self):
        """Legal: uploading -> processing via complete_upload."""
        fsm = create_fsm("uploading")
        fsm.complete_upload()
        assert fsm.current_state.value == "processing"

    def test_processing_to_indexed(self):
        """Legal: processing -> indexed via complete_processing."""
        fsm = create_fsm("processing")
        fsm.complete_processing()
        assert fsm.current_state.value == "indexed"

    def test_uploading_to_failed(self):
        """Legal: uploading -> failed via fail_upload."""
        fsm = create_fsm("uploading")
        fsm.fail_upload()
        assert fsm.current_state.value == "failed"

    def test_processing_to_failed(self):
        """Legal: processing -> failed via fail_processing."""
        fsm = create_fsm("processing")
        fsm.fail_processing()
        assert fsm.current_state.value == "failed"

    def test_indexed_to_untracked(self):
        """Legal: indexed -> untracked via reset."""
        fsm = create_fsm("indexed")
        fsm.reset()
        assert fsm.current_state.value == "untracked"

    def test_failed_to_untracked(self):
        """Legal: failed -> untracked via retry."""
        fsm = create_fsm("failed")
        fsm.retry()
        assert fsm.current_state.value == "untracked"

    def test_indexed_to_failed(self):
        """Legal: indexed -> failed via fail_reset."""
        fsm = create_fsm("indexed")
        fsm.fail_reset()
        assert fsm.current_state.value == "failed"

    def test_illegal_untracked_to_indexed(self):
        """Illegal: cannot jump from untracked to indexed."""
        fsm = create_fsm("untracked")
        with pytest.raises(Exception):
            fsm.complete_processing()

    def test_illegal_indexed_to_uploading(self):
        """Illegal: cannot go from indexed to uploading."""
        fsm = create_fsm("indexed")
        with pytest.raises(Exception):
            fsm.start_upload()

    def test_illegal_failed_to_indexed(self):
        """Illegal: cannot go from failed to indexed."""
        fsm = create_fsm("failed")
        with pytest.raises(Exception):
            fsm.complete_processing()


# ======================================================================
# Test 2: transition_to_uploading OCC guard
# ======================================================================


class TestOCCGuard:
    """Test that OCC version checks work correctly."""

    @pytest.mark.asyncio
    async def test_transition_succeeds_with_correct_version(self, fsm_state):
        """transition_to_uploading succeeds with matching version."""
        await _insert_test_file(fsm_state, version=0)

        new_version = await fsm_state.transition_to_uploading("/test/file.txt", 0)
        assert new_version == 1

    @pytest.mark.asyncio
    async def test_transition_fails_with_stale_version(self, fsm_state):
        """transition_to_uploading raises OCCConflictError with wrong version."""
        await _insert_test_file(fsm_state, version=0)

        # First call succeeds, version is now 1
        await fsm_state.transition_to_uploading("/test/file.txt", 0)

        # Second call with expected_version=0 must fail (version is now 1)
        with pytest.raises(OCCConflictError):
            await fsm_state.transition_to_uploading("/test/file.txt", 0)


# ======================================================================
# Test 3: Full FSM lifecycle
# ======================================================================


class TestFSMLifecycle:
    """Test a complete file lifecycle through transition_to_*() methods."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, fsm_state):
        """Take a file through untracked -> uploading -> processing -> indexed."""
        await _insert_test_file(fsm_state, version=0)

        # untracked -> uploading
        v1 = await fsm_state.transition_to_uploading("/test/file.txt", 0)
        assert v1 == 1
        state, version = await fsm_state.get_file_version("/test/file.txt")
        assert state == "uploading"
        assert version == 1

        # uploading -> processing
        v2 = await fsm_state.transition_to_processing(
            "/test/file.txt", 1, "files/abc123", "gs://bucket/abc123"
        )
        assert v2 == 2
        state, version = await fsm_state.get_file_version("/test/file.txt")
        assert state == "processing"
        assert version == 2

        # processing -> indexed
        v3 = await fsm_state.transition_to_indexed(
            "/test/file.txt", 2, "fileSearchStores/store1/documents/doc1"
        )
        assert v3 == 3
        state, version = await fsm_state.get_file_version("/test/file.txt")
        assert state == "indexed"
        assert version == 3

    @pytest.mark.asyncio
    async def test_failure_from_uploading(self, fsm_state):
        """Transition to failed from uploading state."""
        await _insert_test_file(fsm_state, version=0)

        v1 = await fsm_state.transition_to_uploading("/test/file.txt", 0)
        v2 = await fsm_state.transition_to_failed(
            "/test/file.txt", v1, "Upload error"
        )
        assert v2 == 2
        state, version = await fsm_state.get_file_version("/test/file.txt")
        assert state == "failed"
        assert version == 2


# ======================================================================
# Test 4: SC6 -- RecoveryCrawler raises on OCC conflict
# ======================================================================


class TestRecoveryCrawlerSC6:
    """SC6: RecoveryCrawler._recover_file() raises OCCConflictError on
    finalize_reset() failure. recover_all() catches per-file and continues."""

    @pytest.mark.asyncio
    async def test_recover_file_raises_on_occ_conflict(self, fsm_state):
        """_recover_file raises OCCConflictError when finalize_reset fails."""
        await _insert_test_file(
            fsm_state,
            file_path="/test/crash.txt",
            gemini_state="indexed",
            version=5,
            gemini_file_id="files/abc123",
            gemini_store_doc_id="fileSearchStores/s1/documents/d1",
            intent_type="reset",
            intent_api_calls_completed=0,
            status="uploaded",
        )

        mock_client = MagicMock()
        mock_client.delete_store_document = AsyncMock(return_value=True)
        mock_client.delete_file = AsyncMock(return_value=None)

        crawler = RecoveryCrawler(state=fsm_state, client=mock_client)

        # Simulate concurrent modification: bump version before recovery runs
        db = fsm_state._ensure_connected()
        await db.execute(
            "UPDATE files SET version = 999 WHERE file_path = '/test/crash.txt'"
        )
        await db.commit()

        row = {
            "file_path": "/test/crash.txt",
            "intent_type": "reset",
            "intent_api_calls_completed": 0,
            "gemini_store_doc_id": "fileSearchStores/s1/documents/d1",
            "gemini_file_id": "files/abc123",
            "version": 5,  # stale -- DB now has 999
        }

        with pytest.raises(OCCConflictError):
            await crawler._recover_file(row)

    @pytest.mark.asyncio
    async def test_recover_all_catches_occ_and_continues(self, fsm_state):
        """recover_all catches OCCConflictError per-file and processes next file."""
        # File 1: will have OCC conflict (simulated by concurrent version bump)
        await _insert_test_file(
            fsm_state,
            file_path="/test/file1.txt",
            gemini_state="indexed",
            version=5,
            gemini_file_id="files/abc1",
            gemini_store_doc_id="fileSearchStores/s1/documents/d1",
            intent_type="reset",
            intent_api_calls_completed=0,
            status="uploaded",
        )
        # File 2: will recover successfully
        await _insert_test_file(
            fsm_state,
            file_path="/test/file2.txt",
            gemini_state="indexed",
            version=3,
            gemini_file_id="files/abc2",
            gemini_store_doc_id="fileSearchStores/s1/documents/d2",
            intent_type="reset",
            intent_api_calls_completed=0,
            status="uploaded",
        )

        mock_client = MagicMock()
        mock_client.delete_store_document = AsyncMock(return_value=True)
        mock_client.delete_file = AsyncMock(return_value=None)

        crawler = RecoveryCrawler(state=fsm_state, client=mock_client)

        # Intercept update_intent_progress to bump file1's version mid-recovery,
        # simulating a concurrent writer modifying the row between the initial
        # query and the finalize_reset call.
        original_update = fsm_state.update_intent_progress
        bumped = False

        async def intercepting_update(file_path, api_calls_completed):
            nonlocal bumped
            await original_update(file_path, api_calls_completed)
            if file_path == "/test/file1.txt" and not bumped:
                bumped = True
                db = fsm_state._ensure_connected()
                await db.execute(
                    "UPDATE files SET version = 999 WHERE file_path = '/test/file1.txt'"
                )
                await db.commit()

        fsm_state.update_intent_progress = intercepting_update

        recovered, occ_failures = await crawler.recover_all()

        # File 1 should be in occ_failures, file 2 should be recovered
        assert "/test/file1.txt" in occ_failures
        assert "/test/file2.txt" in recovered

        # Verify file2 is now untracked
        state, version = await fsm_state.get_file_version("/test/file2.txt")
        assert state == "untracked"


# ======================================================================
# Test 5: SC3 -- _reset_existing_files_fsm deletes store doc before raw file
# ======================================================================


class TestSC3DeleteOrder:
    """Verify _reset_existing_files_fsm calls delete_store_document
    BEFORE delete_file (SC3 compliance)."""

    @pytest.mark.asyncio
    async def test_store_doc_deleted_before_raw_file(self, fsm_state):
        """delete_store_document is called before delete_file."""
        await _insert_test_file(
            fsm_state,
            file_path="/test/indexed.txt",
            gemini_state="indexed",
            version=2,
            gemini_file_id="files/xyz789",
            gemini_store_doc_id="fileSearchStores/s1/documents/doc1",
            status="uploaded",
        )

        # Track call order
        call_order = []

        mock_client = MagicMock()

        async def mock_delete_store_doc(name):
            call_order.append(("delete_store_document", name))
            return True

        async def mock_delete_file(name):
            call_order.append(("delete_file", name))
            return None

        mock_client.delete_store_document = mock_delete_store_doc
        mock_client.delete_file = mock_delete_file
        mock_client.get_or_create_store = AsyncMock(return_value="fileSearchStores/s1")
        mock_client.list_store_documents = AsyncMock(return_value=[])
        mock_client.find_store_document_name = AsyncMock(return_value=None)

        from objlib.models import UploadConfig
        from objlib.upload.circuit_breaker import RollingWindowCircuitBreaker
        from objlib.upload.orchestrator import FSMUploadOrchestrator

        config = UploadConfig(store_name="test-store")
        cb = RollingWindowCircuitBreaker()
        orchestrator = FSMUploadOrchestrator(
            client=mock_client,
            state=fsm_state,
            circuit_breaker=cb,
            config=config,
            reset_existing=True,
            file_limit=0,
        )

        await orchestrator._reset_existing_files_fsm(limit=0)

        # Verify call order: store doc deleted BEFORE raw file
        assert len(call_order) == 2, f"Expected 2 delete calls, got {call_order}"
        assert call_order[0][0] == "delete_store_document", (
            f"Expected delete_store_document first, got {call_order[0][0]}"
        )
        assert call_order[1][0] == "delete_file", (
            f"Expected delete_file second, got {call_order[1][0]}"
        )

        # Verify the arguments
        assert call_order[0][1] == "fileSearchStores/s1/documents/doc1"
        assert call_order[1][1] == "files/xyz789"


# ======================================================================
# Test 6: retry_failed_file standalone function
# ======================================================================


class TestRetryFailedFile:
    """Test the FAILED -> UNTRACKED escape path."""

    @pytest.mark.asyncio
    async def test_retry_resets_failed_to_untracked(self, fsm_state):
        """retry_failed_file transitions a failed file to untracked."""
        await _insert_test_file(
            fsm_state,
            file_path="/test/failed.txt",
            gemini_state="failed",
            version=3,
            status="failed",
        )

        result = await retry_failed_file(fsm_state, "/test/failed.txt")
        assert result is True

        state, version = await fsm_state.get_file_version("/test/failed.txt")
        assert state == "untracked"
        assert version == 4  # version incremented

    @pytest.mark.asyncio
    async def test_retry_noop_for_non_failed(self, fsm_state):
        """retry_failed_file returns False for files not in failed state."""
        await _insert_test_file(
            fsm_state,
            file_path="/test/indexed.txt",
            gemini_state="indexed",
            version=3,
            status="uploaded",
        )

        result = await retry_failed_file(fsm_state, "/test/indexed.txt")
        assert result is False


# ======================================================================
# Test 7: write_reset_intent and finalize_reset
# ======================================================================


class TestResetIntentMethods:
    """Test the write-ahead intent methods on state manager."""

    @pytest.mark.asyncio
    async def test_write_reset_intent_sets_intent_columns(self, fsm_state):
        """write_reset_intent sets intent_type and api_calls_completed=0."""
        await _insert_test_file(
            fsm_state,
            file_path="/test/intent.txt",
            gemini_state="indexed",
            version=2,
            status="uploaded",
        )

        result_version = await fsm_state.write_reset_intent("/test/intent.txt", 2)
        assert result_version == 2  # No version increment on intent write

        db = fsm_state._ensure_connected()
        cursor = await db.execute(
            "SELECT intent_type, intent_api_calls_completed FROM files WHERE file_path = ?",
            ("/test/intent.txt",),
        )
        row = await cursor.fetchone()
        assert row["intent_type"] == "reset"
        assert row["intent_api_calls_completed"] == 0

    @pytest.mark.asyncio
    async def test_finalize_reset_clears_all_gemini_state(self, fsm_state):
        """finalize_reset clears IDs, intent, and sets untracked."""
        await _insert_test_file(
            fsm_state,
            file_path="/test/finalize.txt",
            gemini_state="indexed",
            version=2,
            gemini_file_id="files/abc",
            gemini_store_doc_id="store/doc1",
            intent_type="reset",
            intent_api_calls_completed=2,
            status="uploaded",
        )

        success = await fsm_state.finalize_reset("/test/finalize.txt", 2)
        assert success is True

        state, version = await fsm_state.get_file_version("/test/finalize.txt")
        assert state == "untracked"
        assert version == 3

        db = fsm_state._ensure_connected()
        cursor = await db.execute(
            """SELECT gemini_file_id, gemini_store_doc_id,
                      intent_type, intent_api_calls_completed
               FROM files WHERE file_path = ?""",
            ("/test/finalize.txt",),
        )
        row = await cursor.fetchone()
        assert row["gemini_file_id"] is None
        assert row["gemini_store_doc_id"] is None
        assert row["intent_type"] is None
        assert row["intent_api_calls_completed"] is None

    @pytest.mark.asyncio
    async def test_finalize_reset_returns_false_on_occ_conflict(self, fsm_state):
        """finalize_reset returns False (not raises) on OCC conflict."""
        await _insert_test_file(
            fsm_state,
            file_path="/test/conflict.txt",
            gemini_state="indexed",
            version=2,
            status="uploaded",
        )

        # Pass wrong expected_version
        result = await fsm_state.finalize_reset("/test/conflict.txt", 99)
        assert result is False
