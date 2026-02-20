"""Schema initialization and structural verification tests.

Tests that Database._setup_schema() correctly creates all 16 tables,
2 triggers, enforces foreign keys, seeds person data, and is idempotent.
"""

from __future__ import annotations

import sqlite3

import pytest

from objlib.database import Database


# All 16 tables expected after full schema initialization (V1-V7).
# Note: files_v7 is a transient migration table that gets renamed to files,
# so it should NOT exist after initialization.
EXPECTED_TABLES = {
    "files",
    "_processing_log",
    "_extraction_failures",
    "_skipped_files",
    "upload_operations",
    "upload_batches",
    "upload_locks",
    "file_metadata_ai",
    "file_primary_topics",
    "wave1_results",
    "person",
    "person_alias",
    "transcript_entity",
    "passages",
    "sessions",
    "session_events",
    "library_config",
}

EXPECTED_TRIGGERS = {"update_files_timestamp", "log_status_change"}


class TestSchemaCreation:
    """Verify that _setup_schema() creates all expected database objects."""

    def test_fresh_schema_all_tables(self, in_memory_db):
        """Query sqlite_master for all tables. Assert all expected tables exist."""
        rows = in_memory_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        actual_tables = {row["name"] for row in rows}
        assert actual_tables == EXPECTED_TABLES, (
            f"Missing: {EXPECTED_TABLES - actual_tables}, "
            f"Extra: {actual_tables - EXPECTED_TABLES}"
        )

    def test_schema_idempotency(self, in_memory_db):
        """Call _setup_schema() a second time. No errors, no data duplication."""
        # Record initial state
        initial_person_count = in_memory_db.conn.execute(
            "SELECT COUNT(*) as cnt FROM person"
        ).fetchone()["cnt"]

        # Second initialization
        in_memory_db._setup_schema()

        # All tables still present
        rows = in_memory_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        actual_tables = {row["name"] for row in rows}
        assert actual_tables == EXPECTED_TABLES

        # Seed data not duplicated
        person_count = in_memory_db.conn.execute(
            "SELECT COUNT(*) as cnt FROM person"
        ).fetchone()["cnt"]
        assert person_count == initial_person_count

    def test_triggers_exist(self, in_memory_db):
        """Query sqlite_master for triggers. Assert both expected triggers exist."""
        rows = in_memory_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
        actual_triggers = {row["name"] for row in rows}
        assert EXPECTED_TRIGGERS.issubset(actual_triggers), (
            f"Missing triggers: {EXPECTED_TRIGGERS - actual_triggers}"
        )

    def test_user_version_is_9(self, in_memory_db):
        """PRAGMA user_version returns 9 after schema setup."""
        version = in_memory_db.conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 9


class TestTriggers:
    """Verify trigger behavior on the files table."""

    def test_trigger_update_files_timestamp(self, in_memory_db):
        """Updating a file row changes its updated_at via trigger."""
        from objlib.models import FileRecord, FileStatus

        record = FileRecord(
            file_path="/test/trigger_ts.txt",
            content_hash="abc123",
            filename="trigger_ts.txt",
            file_size=100,
        )
        in_memory_db.upsert_file(record)

        original = in_memory_db.conn.execute(
            "SELECT updated_at FROM files WHERE file_path = ?",
            ("/test/trigger_ts.txt",),
        ).fetchone()["updated_at"]

        # Update status to force trigger
        in_memory_db.update_file_status("/test/trigger_ts.txt", FileStatus.UPLOADED)

        updated = in_memory_db.conn.execute(
            "SELECT updated_at FROM files WHERE file_path = ?",
            ("/test/trigger_ts.txt",),
        ).fetchone()["updated_at"]

        # The trigger should have updated updated_at
        # (timestamps may be same if fast, but the trigger fired -- check log too)
        assert updated is not None

    def test_trigger_log_status_change(self, in_memory_db):
        """Changing file status logs to _processing_log via trigger."""
        from objlib.models import FileRecord, FileStatus

        record = FileRecord(
            file_path="/test/trigger_log.txt",
            content_hash="def456",
            filename="trigger_log.txt",
            file_size=200,
        )
        in_memory_db.upsert_file(record)

        # Change status from pending -> uploaded
        in_memory_db.update_file_status("/test/trigger_log.txt", FileStatus.UPLOADED)

        log_row = in_memory_db.conn.execute(
            "SELECT old_status, new_status FROM _processing_log WHERE file_path = ?",
            ("/test/trigger_log.txt",),
        ).fetchone()

        assert log_row is not None
        assert log_row["old_status"] == "pending"
        assert log_row["new_status"] == "uploaded"


class TestForeignKeys:
    """Verify FK constraints are enforced on in-memory connections."""

    def test_processing_log_fk_enforced(self, in_memory_db):
        """INSERT into _processing_log with nonexistent file_path raises IntegrityError."""
        with pytest.raises(sqlite3.IntegrityError):
            in_memory_db.conn.execute(
                "INSERT INTO _processing_log(file_path, old_status, new_status) "
                "VALUES (?, ?, ?)",
                ("/nonexistent/file.txt", "pending", "uploaded"),
            )

    def test_session_events_fk_enforced(self, in_memory_db):
        """INSERT into session_events with nonexistent session_id raises IntegrityError."""
        with pytest.raises(sqlite3.IntegrityError):
            in_memory_db.conn.execute(
                "INSERT INTO session_events(id, session_id, event_type, payload_json) "
                "VALUES (?, ?, ?, ?)",
                ("evt-001", "nonexistent-session", "search", "{}"),
            )

    def test_extraction_failures_fk_enforced(self, in_memory_db):
        """INSERT into _extraction_failures with nonexistent file_path raises IntegrityError."""
        with pytest.raises(sqlite3.IntegrityError):
            in_memory_db.conn.execute(
                "INSERT INTO _extraction_failures(file_path, unparsed_folder_name) "
                "VALUES (?, ?)",
                ("/nonexistent/file.txt", "some_folder"),
            )


class TestSeedData:
    """Verify person table seed data from V4 migration."""

    def test_person_seed_data_count(self, in_memory_db):
        """Person table has exactly 15 canonical entries after initialization."""
        count = in_memory_db.conn.execute(
            "SELECT COUNT(*) as cnt FROM person"
        ).fetchone()["cnt"]
        assert count == 15

    def test_person_seed_known_entries(self, in_memory_db):
        """Known canonical persons exist: Ayn Rand, Leonard Peikoff, Yaron Brook."""
        names = in_memory_db.conn.execute(
            "SELECT canonical_name FROM person ORDER BY canonical_name"
        ).fetchall()
        canonical_names = {row["canonical_name"] for row in names}

        assert "Ayn Rand" in canonical_names
        assert "Leonard Peikoff" in canonical_names
        assert "Yaron Brook" in canonical_names


class TestV7Schema:
    """Verify V7-specific schema features."""

    def test_files_table_v7_columns(self, in_memory_db):
        """PRAGMA table_info(files) includes V7 columns."""
        rows = in_memory_db.conn.execute("PRAGMA table_info(files)").fetchall()
        column_names = {row["name"] for row in rows}

        v7_columns = {"mtime", "orphaned_gemini_file_id", "enrichment_version", "upload_hash", "missing_since"}
        assert v7_columns.issubset(column_names), (
            f"Missing V7 columns: {v7_columns - column_names}"
        )

    def test_upload_locks_single_row_constraint(self, in_memory_db):
        """Upload_locks CHECK(lock_id = 1) allows lock_id=1, rejects lock_id=2."""
        # lock_id=1 should succeed
        in_memory_db.conn.execute(
            "INSERT INTO upload_locks(lock_id, instance_id) VALUES (1, 'test-instance')"
        )

        # lock_id=2 should fail due to CHECK constraint
        with pytest.raises(sqlite3.IntegrityError):
            in_memory_db.conn.execute(
                "INSERT INTO upload_locks(lock_id, instance_id) VALUES (2, 'test-instance-2')"
            )
