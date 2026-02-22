"""Unit tests for the upload pipeline infrastructure.

Tests cover the circuit breaker, rate limiter, metadata builder,
async state manager, and recovery manager -- all without hitting the
real Gemini API.

Groups:
  - Circuit Breaker (6 tests)
  - Rate Limiter (3 tests)
  - Metadata Builder (5 tests)
  - Async State Manager (5 tests)
  - Recovery Manager (3 tests -- mocked client)
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from objlib.database import Database
from objlib.models import MetadataQuality, UploadConfig
from objlib.upload.circuit_breaker import CircuitState, RollingWindowCircuitBreaker
from objlib.upload.client import GeminiFileSearchClient
from objlib.upload.rate_limiter import AdaptiveRateLimiter, RateLimiterConfig
from objlib.upload.recovery import RecoveryManager, RecoveryResult, RecoveryTimeoutError
from objlib.upload.state import AsyncUploadStateManager


# ======================================================================
# Circuit Breaker Tests
# ======================================================================


class TestCircuitBreaker:
    """Tests for RollingWindowCircuitBreaker state transitions."""

    def test_circuit_starts_closed(self):
        """A newly created breaker is in CLOSED state."""
        cb = RollingWindowCircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_circuit_trips_on_error_rate(self):
        """Breaker trips to OPEN when 429 rate exceeds 5% threshold."""
        cb = RollingWindowCircuitBreaker(window_size=20, error_threshold=0.05)

        # Record 19 successes + 2 429s => 2/21 > 5% rate
        for _ in range(19):
            cb.record_success()
        cb.record_429()
        cb.record_429()

        assert cb.state == CircuitState.OPEN

    def test_circuit_trips_on_consecutive_429s(self):
        """Breaker trips after 3 consecutive 429s regardless of overall rate."""
        cb = RollingWindowCircuitBreaker(
            window_size=100, error_threshold=0.5, consecutive_threshold=3
        )

        # Even with a low overall rate, 3 consecutive 429s trips
        for _ in range(50):
            cb.record_success()
        cb.record_429()
        cb.record_429()
        cb.record_429()

        assert cb.state == CircuitState.OPEN

    def test_circuit_recovers_after_cooldown(self):
        """After cooldown_seconds, breaker transitions OPEN -> HALF_OPEN."""
        cb = RollingWindowCircuitBreaker(cooldown_seconds=0.1)

        # Trip the breaker
        cb.record_429()
        cb.record_429()
        cb.record_429()
        assert cb.state == CircuitState.OPEN

        # Wait for cooldown
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_circuit_closes_on_half_open_success(self):
        """A success in HALF_OPEN transitions the breaker to CLOSED."""
        cb = RollingWindowCircuitBreaker(cooldown_seconds=0.05)

        # Trip -> wait for HALF_OPEN
        cb.record_429()
        cb.record_429()
        cb.record_429()
        time.sleep(0.1)
        assert cb.state == CircuitState.HALF_OPEN

        # Record success in HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_recommended_concurrency_reduces_when_open(self):
        """get_recommended_concurrency returns reduced value when OPEN."""
        cb = RollingWindowCircuitBreaker()

        # CLOSED: full concurrency
        assert cb.get_recommended_concurrency(10) == 10

        # Trip to OPEN
        cb.record_429()
        cb.record_429()
        cb.record_429()

        # OPEN: halved (max(3, 10//2) = 5)
        assert cb.get_recommended_concurrency(10) == 5


# ======================================================================
# Rate Limiter Tests
# ======================================================================


class TestRateLimiter:
    """Tests for AdaptiveRateLimiter tier configuration."""

    def test_tier1_config(self):
        """Tier 1 has rpm=20 and interval of 3.0 seconds."""
        config = RateLimiterConfig(tier="tier1")
        assert config.rpm == 20
        assert config.min_request_interval == pytest.approx(3.0)

    def test_free_tier_config(self):
        """Free tier has rpm=5 and interval of 12.0 seconds."""
        config = RateLimiterConfig(tier="free")
        assert config.rpm == 5
        assert config.min_request_interval == pytest.approx(12.0)

    def test_unknown_tier_raises(self):
        """An invalid tier name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown rate limit tier"):
            RateLimiterConfig(tier="nonexistent")


# ======================================================================
# Metadata Builder Tests
# ======================================================================


class TestMetadataBuilder:
    """Tests for GeminiFileSearchClient.build_custom_metadata."""

    def test_build_metadata_full(self):
        """All fields present produces correct Gemini metadata format."""
        meta = {
            "category": "lecture",
            "course": "OPAR",
            "difficulty": "advanced",
            "year": "2005",
            "quarter": "Q1",
            "quality_score": "complete",
            "date": "2005-01-15",
            "week": "3",
        }
        result = GeminiFileSearchClient.build_custom_metadata(meta)

        # Should have 8 entries
        assert len(result) == 8

        keys = {item["key"] for item in result}
        assert keys == {
            "category", "course", "difficulty", "year",
            "quarter", "quality_score", "date", "week",
        }

    def test_build_metadata_partial(self):
        """Missing optional fields are excluded."""
        meta = {"course": "OPAR"}
        result = GeminiFileSearchClient.build_custom_metadata(meta)

        assert len(result) == 1
        assert result[0] == {"key": "course", "string_value": "OPAR"}

    def test_build_metadata_numeric_year(self):
        """Year value becomes numeric_value."""
        meta = {"year": "2005"}
        result = GeminiFileSearchClient.build_custom_metadata(meta)

        assert len(result) == 1
        assert result[0] == {"key": "year", "numeric_value": 2005}

    def test_build_metadata_quality_mapping(self):
        """MetadataQuality grades map to numeric scores."""
        for quality, expected_score in [
            ("complete", 100),
            ("partial", 75),
            ("minimal", 50),
            ("none", 25),
            ("unknown", 0),
        ]:
            meta = {"quality_score": quality}
            result = GeminiFileSearchClient.build_custom_metadata(meta)
            assert len(result) == 1
            assert result[0]["numeric_value"] == expected_score, (
                f"Expected {expected_score} for {quality}"
            )

    def test_build_metadata_empty(self):
        """Empty dict produces empty list."""
        result = GeminiFileSearchClient.build_custom_metadata({})
        assert result == []


# ======================================================================
# Async State Manager Tests
# ======================================================================


@pytest.fixture
async def async_state(tmp_path: Path):
    """Create a temp database with full schema and return an async state manager."""
    db_path = tmp_path / "test_upload.db"
    # Initialize schema synchronously
    db = Database(db_path)
    # Insert a test file
    db.conn.execute(
        """INSERT INTO files (file_path, content_hash, filename, file_size,
                              metadata_json, metadata_quality)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("/test/file1.txt", "abc123", "file1.txt", 1024, '{"course": "OPAR"}', "complete"),
    )
    db.conn.execute(
        """INSERT INTO files (file_path, content_hash, filename, file_size,
                              metadata_json, metadata_quality)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("/test/file2.txt", "def456", "file2.txt", 2048, '{"course": "HWK"}', "partial"),
    )
    db.conn.commit()
    db.close()

    state = AsyncUploadStateManager(str(db_path))
    await state.connect()
    yield state
    await state.close()


class TestAsyncStateManager:
    """Tests for AsyncUploadStateManager async CRUD operations."""

    async def test_pending_files_query(self, async_state: AsyncUploadStateManager):
        """Files with pending status are returned."""
        pending = await async_state.get_pending_files()
        assert len(pending) == 2
        paths = {f["file_path"] for f in pending}
        assert "/test/file1.txt" in paths
        assert "/test/file2.txt" in paths

    async def test_record_upload_intent_changes_status(
        self, async_state: AsyncUploadStateManager
    ):
        """After recording intent, file status is 'uploading'."""
        await async_state.record_upload_intent("/test/file1.txt")

        # file1 should no longer be pending
        pending = await async_state.get_pending_files()
        paths = {f["file_path"] for f in pending}
        assert "/test/file1.txt" not in paths

        # It should appear in uploading files
        uploading = await async_state.get_uploading_files()
        assert len(uploading) == 1
        assert uploading[0]["file_path"] == "/test/file1.txt"

    async def test_record_upload_success(
        self, async_state: AsyncUploadStateManager
    ):
        """After success, gemini_file_uri and operation are recorded."""
        await async_state.record_upload_intent("/test/file1.txt")
        await async_state.record_upload_success(
            "/test/file1.txt",
            gemini_file_uri="gs://bucket/file1",
            gemini_file_id="files/abc123",
            operation_name="operations/xyz",
        )

        # File should still be in uploading (import not yet complete)
        # but upload metadata should be recorded
        db = async_state._ensure_connected()
        cursor = await db.execute(
            "SELECT gemini_file_uri, gemini_file_id FROM files WHERE file_path = ?",
            ("/test/file1.txt",),
        )
        row = await cursor.fetchone()
        assert row["gemini_file_uri"] == "gs://bucket/file1"
        assert row["gemini_file_id"] == "files/abc123"

        # Operation should exist
        ops = await async_state.get_pending_operations()
        assert len(ops) == 1
        assert ops[0]["operation_name"] == "operations/xyz"

    async def test_record_failure(
        self, async_state: AsyncUploadStateManager
    ):
        """After failure, error_message is stored."""
        await async_state.record_upload_intent("/test/file1.txt")
        await async_state.record_upload_failure(
            "/test/file1.txt", "Connection timeout"
        )

        db = async_state._ensure_connected()
        cursor = await db.execute(
            "SELECT gemini_state, error_message FROM files WHERE file_path = ?",
            ("/test/file1.txt",),
        )
        row = await cursor.fetchone()
        assert row["gemini_state"] == "failed"
        assert row["error_message"] == "Connection timeout"

    async def test_lock_acquire_and_release(
        self, async_state: AsyncUploadStateManager
    ):
        """Lock can be acquired, released, and re-acquired."""
        assert await async_state.acquire_lock("instance-1") is True

        # Release
        await async_state.release_lock()

        # Re-acquire
        assert await async_state.acquire_lock("instance-2") is True


# ======================================================================
# Recovery Manager Tests
# ======================================================================


@pytest.fixture
async def recovery_state(tmp_path: Path):
    """Create a temp database with files in various states for recovery testing."""
    db_path = tmp_path / "test_recovery.db"
    db = Database(db_path)

    # File stuck in 'uploading' with no gemini_file_id (interrupted upload)
    db.conn.execute(
        """INSERT INTO files (file_path, content_hash, filename, file_size,
                              gemini_state)
           VALUES (?, ?, ?, ?, ?)""",
        ("/test/interrupted.txt", "hash1", "interrupted.txt", 1024, "uploading"),
    )

    # File stuck in 'uploading' WITH a gemini_file_id (upload succeeded, import unknown)
    db.conn.execute(
        """INSERT INTO files (file_path, content_hash, filename, file_size,
                              gemini_state, gemini_file_id, gemini_file_uri,
                              remote_expiration_ts)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "/test/partial.txt", "hash2", "partial.txt", 2048, "uploading",
            "files/abc", "gs://bucket/partial",
            "2099-01-01T00:00:00.000000",  # far future -- not expired
        ),
    )

    # File with pending operation
    db.conn.execute(
        """INSERT INTO files (file_path, content_hash, filename, file_size,
                              gemini_state, gemini_file_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("/test/pending_op.txt", "hash3", "pending_op.txt", 3072, "uploading", "files/def"),
    )
    db.conn.execute(
        """INSERT INTO upload_operations
               (operation_name, file_path, gemini_file_name, operation_state)
           VALUES (?, ?, ?, ?)""",
        ("operations/op1", "/test/pending_op.txt", "files/def", "pending"),
    )

    db.conn.commit()
    db.close()

    state = AsyncUploadStateManager(str(db_path))
    await state.connect()
    yield state
    await state.close()


class TestRecoveryManager:
    """Tests for RecoveryManager crash recovery logic."""

    async def test_interrupted_upload_without_gemini_id_resets(
        self, recovery_state: AsyncUploadStateManager
    ):
        """A file in 'uploading' with no gemini_file_id is reset to untracked."""
        mock_client = MagicMock(spec=GeminiFileSearchClient)
        config = UploadConfig(store_name="test-store", recovery_timeout_seconds=30)

        recovery = RecoveryManager(mock_client, recovery_state, config)
        result = await recovery.run()

        # interrupted.txt should be reset to untracked (was pending)
        assert result.reset_to_pending >= 1

        db = recovery_state._ensure_connected()
        cursor = await db.execute(
            "SELECT gemini_state FROM files WHERE file_path = ?",
            ("/test/interrupted.txt",),
        )
        row = await cursor.fetchone()
        assert row["gemini_state"] == "untracked"

    async def test_interrupted_upload_with_valid_gemini_id_marked_uploaded(
        self, recovery_state: AsyncUploadStateManager
    ):
        """A file in 'uploading' with a valid (non-expired) gemini_file_id
        is marked as indexed."""
        mock_client = MagicMock(spec=GeminiFileSearchClient)
        config = UploadConfig(store_name="test-store", recovery_timeout_seconds=30)

        recovery = RecoveryManager(mock_client, recovery_state, config)
        result = await recovery.run()

        assert result.recovered_operations >= 1

        db = recovery_state._ensure_connected()
        cursor = await db.execute(
            "SELECT gemini_state FROM files WHERE file_path = ?",
            ("/test/partial.txt",),
        )
        row = await cursor.fetchone()
        assert row["gemini_state"] == "indexed"

    async def test_recovery_timeout_raises(
        self, recovery_state: AsyncUploadStateManager
    ):
        """Recovery exceeding the timeout raises RecoveryTimeoutError."""
        mock_client = MagicMock(spec=GeminiFileSearchClient)
        # Very short timeout to trigger the error
        config = UploadConfig(store_name="test-store", recovery_timeout_seconds=0)

        recovery = RecoveryManager(mock_client, recovery_state, config)

        # The wait_for with timeout=0 should immediately timeout
        # since _recover does actual async work
        with pytest.raises(RecoveryTimeoutError):
            await recovery.run()


# ======================================================================
# downgrade_to_failed() Tests (Phase 15 -- store-sync reconciliation)
# ======================================================================


@pytest.fixture
async def downgrade_db(tmp_path: Path):
    """Create a temp database with an INDEXED file for downgrade testing."""
    db_path = tmp_path / "test_downgrade.db"
    db = Database(db_path)

    # File in INDEXED state (normal successful upload)
    db.conn.execute(
        """INSERT INTO files (file_path, content_hash, filename, file_size,
                              gemini_state, gemini_store_doc_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("/test/indexed_file.txt", "hash_idx", "indexed_file.txt", 4096,
         "indexed", "doc_suffix_123"),
    )

    # File in UNTRACKED state (should not be affected by downgrade)
    db.conn.execute(
        """INSERT INTO files (file_path, content_hash, filename, file_size,
                              gemini_state)
           VALUES (?, ?, ?, ?, ?)""",
        ("/test/untracked_file.txt", "hash_unt", "untracked_file.txt", 2048,
         "untracked"),
    )

    # File in FAILED state (should not be affected by downgrade)
    db.conn.execute(
        """INSERT INTO files (file_path, content_hash, filename, file_size,
                              gemini_state, error_message)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("/test/failed_file.txt", "hash_fail", "failed_file.txt", 1024,
         "failed", "previous error"),
    )

    db.conn.commit()
    db.close()

    return str(db_path)


class TestDowngradeToFailed:
    """Tests for downgrade_to_failed() store-sync reconciliation function."""

    async def test_downgrade_transitions_indexed_file(self, downgrade_db: str):
        """An INDEXED file is downgraded to FAILED with reason and cleared store doc ID."""
        from objlib.upload.recovery import downgrade_to_failed
        import aiosqlite

        # Call downgrade using file_path (the primary key)
        result = await downgrade_to_failed(downgrade_db, "/test/indexed_file.txt")

        assert result is True

        # Verify state change
        async with aiosqlite.connect(downgrade_db) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT gemini_state, gemini_store_doc_id, error_message "
                "FROM files WHERE file_path = ?",
                ("/test/indexed_file.txt",),
            )
            row = await cursor.fetchone()
            assert row["gemini_state"] == "failed"
            assert row["gemini_store_doc_id"] is None
            assert "store-sync" in row["error_message"]

    async def test_downgrade_ignores_non_indexed_file(self, downgrade_db: str):
        """A file NOT in INDEXED state is not changed -- returns False."""
        from objlib.upload.recovery import downgrade_to_failed

        # Call downgrade on untracked file -- should return False
        result = await downgrade_to_failed(downgrade_db, "/test/untracked_file.txt")

        assert result is False

        # Verify state unchanged
        import aiosqlite
        async with aiosqlite.connect(downgrade_db) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT gemini_state FROM files WHERE file_path = ?",
                ("/test/untracked_file.txt",),
            )
            row = await cursor.fetchone()
            assert row["gemini_state"] == "untracked"

    async def test_downgrade_ignores_already_failed_file(self, downgrade_db: str):
        """A FAILED file is not double-downgraded -- returns False."""
        from objlib.upload.recovery import downgrade_to_failed

        # Call downgrade on already-failed file -- should return False
        result = await downgrade_to_failed(downgrade_db, "/test/failed_file.txt")

        assert result is False

        # Verify original error message preserved
        import aiosqlite
        async with aiosqlite.connect(downgrade_db) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT gemini_state, error_message FROM files WHERE file_path = ?",
                ("/test/failed_file.txt",),
            )
            row = await cursor.fetchone()
            assert row["gemini_state"] == "failed"
            assert row["error_message"] == "previous error"

    async def test_downgrade_custom_reason(self, downgrade_db: str):
        """Custom reason string is stored in error_message."""
        from objlib.upload.recovery import downgrade_to_failed

        result = await downgrade_to_failed(
            downgrade_db, "/test/indexed_file.txt",
            reason="targeted query timeout after 300s",
        )

        assert result is True

        import aiosqlite
        async with aiosqlite.connect(downgrade_db) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT error_message FROM files WHERE file_path = ?",
                ("/test/indexed_file.txt",),
            )
            row = await cursor.fetchone()
            assert row["error_message"] == "targeted query timeout after 300s"
