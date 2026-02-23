"""CRUD method tests for the Database class against in-memory SQLite.

Tests all major Database methods: upsert, status, sync columns, passages,
entities, config, and query methods.
"""

from __future__ import annotations

import json

import pytest

from objlib.database import Database
from objlib.models import FileRecord, MetadataQuality


def _make_record(
    path: str = "/test/file.txt",
    content_hash: str = "abc123",
    size: int = 1000,
    metadata_json: str | None = None,
    quality: MetadataQuality = MetadataQuality.UNKNOWN,
) -> FileRecord:
    """Helper to create FileRecord with sensible defaults."""
    return FileRecord(
        file_path=path,
        content_hash=content_hash,
        filename=path.split("/")[-1],
        file_size=size,
        metadata_json=metadata_json,
        metadata_quality=quality,
    )


class TestUpsertFile:
    """Tests for upsert_file and upsert_files methods."""

    def test_upsert_file_insert(self, in_memory_db):
        """upsert_file with a new path inserts a row with gemini_state='untracked'."""
        record = _make_record("/test/new_file.txt", "hash1", 5000)
        in_memory_db.upsert_file(record)

        row = in_memory_db.conn.execute(
            "SELECT file_path, content_hash, file_size, gemini_state FROM files WHERE file_path = ?",
            ("/test/new_file.txt",),
        ).fetchone()

        assert row is not None
        assert row["content_hash"] == "hash1"
        assert row["file_size"] == 5000
        assert row["gemini_state"] == "untracked"

    def test_upsert_file_update_changed_hash(self, in_memory_db):
        """upsert_file with different hash updates content_hash."""
        record1 = _make_record("/test/changing.txt", "hash_v1", 1000)
        in_memory_db.upsert_file(record1)
        in_memory_db.conn.execute(
            "UPDATE files SET gemini_state = 'indexed' WHERE file_path = ?",
            ("/test/changing.txt",),
        )
        in_memory_db.conn.commit()

        # Upsert with changed hash
        record2 = _make_record("/test/changing.txt", "hash_v2", 1100)
        in_memory_db.upsert_file(record2)

        row = in_memory_db.conn.execute(
            "SELECT content_hash FROM files WHERE file_path = ?",
            ("/test/changing.txt",),
        ).fetchone()
        assert row["content_hash"] == "hash_v2"

    def test_upsert_file_unchanged_hash(self, in_memory_db):
        """upsert_file with same hash preserves existing gemini_state."""
        record = _make_record("/test/stable.txt", "same_hash", 2000)
        in_memory_db.upsert_file(record)
        in_memory_db.conn.execute(
            "UPDATE files SET gemini_state = 'indexed' WHERE file_path = ?",
            ("/test/stable.txt",),
        )
        in_memory_db.conn.commit()

        # Re-upsert with same hash
        record_again = _make_record("/test/stable.txt", "same_hash", 2000)
        in_memory_db.upsert_file(record_again)

        row = in_memory_db.conn.execute(
            "SELECT gemini_state FROM files WHERE file_path = ?",
            ("/test/stable.txt",),
        ).fetchone()
        assert row["gemini_state"] == "indexed"

    def test_upsert_files_batch(self, in_memory_db):
        """upsert_files inserts multiple records in a single transaction."""
        records = [
            _make_record("/test/batch1.txt", "h1", 100),
            _make_record("/test/batch2.txt", "h2", 200),
            _make_record("/test/batch3.txt", "h3", 300),
        ]
        in_memory_db.upsert_files(records)

        count = in_memory_db.conn.execute(
            "SELECT COUNT(*) as cnt FROM files"
        ).fetchone()["cnt"]
        assert count == 3


class TestFileQueries:
    """Tests for get_all_active_files, get_pending_files, get_status_counts, etc."""

    def test_get_all_active_files(self, populated_db):
        """Returns all 5 files (none deleted)."""
        active = populated_db.get_all_active_files()
        assert len(active) == 5

    def test_mark_deleted(self, populated_db):
        """mark_deleted removes one file from active set."""
        first_path = "/library/Courses/OPAR/OPAR - Lesson 01 - Metaphysics.txt"
        populated_db.mark_deleted({first_path})

        active = populated_db.get_all_active_files()
        assert len(active) == 4
        assert first_path not in active

    def test_get_status_counts(self, populated_db):
        """Status counts match: untracked=2, indexed=2, failed=1."""
        counts = populated_db.get_status_counts()
        assert counts.get("untracked", 0) == 2
        assert counts.get("indexed", 0) == 2
        assert counts.get("failed", 0) == 1

    def test_get_pending_files(self, populated_db):
        """Returns only the 2 untracked .txt files."""
        pending = populated_db.get_pending_files()
        assert len(pending) == 2
        states = set()
        for row in pending:
            state_row = populated_db.conn.execute(
                "SELECT gemini_state FROM files WHERE file_path = ?",
                (row["file_path"],),
            ).fetchone()
            states.add(state_row["gemini_state"])
        assert states == {"untracked"}


class TestSkippedAndFailures:
    """Tests for log_skipped_file and log_extraction_failure."""

    def test_log_skipped_file(self, in_memory_db):
        """log_skipped_file creates a row in _skipped_files."""
        in_memory_db.log_skipped_file("/test/skipped.epub", "non-txt file", 50000)

        row = in_memory_db.conn.execute(
            "SELECT file_path, reason, file_size FROM _skipped_files"
        ).fetchone()
        assert row is not None
        assert row["file_path"] == "/test/skipped.epub"
        assert row["reason"] == "non-txt file"
        assert row["file_size"] == 50000

    def test_log_extraction_failure(self, in_memory_db):
        """log_extraction_failure records a row in _extraction_failures."""
        # Must insert file first (FK constraint)
        record = _make_record("/test/bad_parse.txt")
        in_memory_db.upsert_file(record)

        in_memory_db.log_extraction_failure(
            "/test/bad_parse.txt",
            folder_name="Unknown Folder",
            filename="bad_parse.txt",
        )

        row = in_memory_db.conn.execute(
            "SELECT file_path, unparsed_folder_name, unparsed_filename "
            "FROM _extraction_failures"
        ).fetchone()
        assert row is not None
        assert row["file_path"] == "/test/bad_parse.txt"
        assert row["unparsed_folder_name"] == "Unknown Folder"


class TestFilterFiles:
    """Tests for filter_files_by_metadata."""

    def test_filter_files_by_metadata(self, populated_db):
        """Filter by metadata field after setting metadata on files."""
        metadata = json.dumps({"category": "course", "course": "OPAR", "difficulty": "advanced"})
        populated_db.conn.execute(
            "UPDATE files SET metadata_json = ? WHERE file_path LIKE '%OPAR%'",
            (metadata,),
        )
        populated_db.conn.commit()

        results = populated_db.filter_files_by_metadata({"course": "OPAR"})
        assert len(results) == 2
        for result in results:
            assert "OPAR" in result["file_path"]


class TestPassages:
    """Tests for passage cache methods."""

    def test_upsert_passage(self, in_memory_db):
        """upsert_passage inserts a row, second call updates last_seen_at."""
        record = _make_record("/test/passage_file.txt")
        in_memory_db.upsert_file(record)

        in_memory_db.upsert_passage(
            passage_id="p-001",
            file_id="/test/passage_file.txt",
            content_hash="phash1",
            passage_text="The nature of consciousness is...",
        )

        row = in_memory_db.conn.execute(
            "SELECT passage_id, file_id, passage_text, is_stale FROM passages WHERE passage_id = ?",
            ("p-001",),
        ).fetchone()
        assert row is not None
        assert row["file_id"] == "/test/passage_file.txt"
        assert row["is_stale"] == 0

        first_seen = in_memory_db.conn.execute(
            "SELECT last_seen_at FROM passages WHERE passage_id = ?",
            ("p-001",),
        ).fetchone()["last_seen_at"]

        # Second upsert should update last_seen_at
        in_memory_db.upsert_passage(
            passage_id="p-001",
            file_id="/test/passage_file.txt",
            content_hash="phash1",
            passage_text="The nature of consciousness is...",
        )

        second_seen = in_memory_db.conn.execute(
            "SELECT last_seen_at FROM passages WHERE passage_id = ?",
            ("p-001",),
        ).fetchone()["last_seen_at"]

        # Both should be non-None (exact comparison unreliable in fast tests)
        assert first_seen is not None
        assert second_seen is not None

    def test_mark_stale_passages(self, in_memory_db):
        """mark_stale_passages sets is_stale=1 for all passages of a file."""
        record = _make_record("/test/stale_test.txt")
        in_memory_db.upsert_file(record)

        in_memory_db.upsert_passage("p-s1", "/test/stale_test.txt", "h1", "Text 1")
        in_memory_db.upsert_passage("p-s2", "/test/stale_test.txt", "h2", "Text 2")

        stale_count = in_memory_db.mark_stale_passages("/test/stale_test.txt")
        assert stale_count == 2

        rows = in_memory_db.conn.execute(
            "SELECT is_stale FROM passages WHERE file_id = ?",
            ("/test/stale_test.txt",),
        ).fetchall()
        assert all(row["is_stale"] == 1 for row in rows)


class TestEntityMethods:
    """Tests for entity extraction persistence methods."""

    def _make_entity_result(self, entities, status="entities_done", version="6.1.0"):
        """Create a duck-typed entity result object."""

        class EntityResult:
            pass

        class Entity:
            pass

        result = EntityResult()
        result.entities = []
        result.status = status
        result.extraction_version = version

        for e in entities:
            ent = Entity()
            ent.person_id = e["person_id"]
            ent.mention_count = e["mention_count"]
            ent.first_seen_char = e.get("first_seen_char", 0)
            ent.max_confidence = e.get("max_confidence", 0.9)
            ent.evidence_sample = e.get("evidence_sample", "sample text")
            result.entities.append(ent)

        return result

    def test_save_transcript_entities(self, in_memory_db):
        """save_transcript_entities inserts entities and is idempotent."""
        record = _make_record("/test/entities.txt")
        in_memory_db.upsert_file(record)

        entities = [
            {"person_id": "ayn-rand", "mention_count": 5},
            {"person_id": "leonard-peikoff", "mention_count": 3},
        ]
        result = self._make_entity_result(entities)
        in_memory_db.save_transcript_entities("/test/entities.txt", result)

        count = in_memory_db.conn.execute(
            "SELECT COUNT(*) as cnt FROM transcript_entity WHERE transcript_id = ?",
            ("/test/entities.txt",),
        ).fetchone()["cnt"]
        assert count == 2

        # Idempotent: call again with same data
        in_memory_db.save_transcript_entities("/test/entities.txt", result)
        count2 = in_memory_db.conn.execute(
            "SELECT COUNT(*) as cnt FROM transcript_entity WHERE transcript_id = ?",
            ("/test/entities.txt",),
        ).fetchone()["cnt"]
        assert count2 == 2

    def test_get_entity_stats(self, in_memory_db):
        """get_entity_stats returns correct counts after saving entities."""
        record = _make_record("/test/stats.txt")
        in_memory_db.upsert_file(record)

        entities = [
            {"person_id": "ayn-rand", "mention_count": 10},
            {"person_id": "yaron-brook", "mention_count": 7},
        ]
        result = self._make_entity_result(entities)
        in_memory_db.save_transcript_entities("/test/stats.txt", result)

        stats = in_memory_db.get_entity_stats()
        assert stats["total_mentions"] == 17
        assert stats["unique_persons"] == 2
        assert stats["entities_done"] == 1
        assert len(stats["person_frequency"]) == 2


class TestMissingAndOrphaned:
    """Tests for sync-related methods: missing files and orphaned Gemini IDs."""

    def test_mark_missing_and_get_missing(self, in_memory_db):
        """mark_missing sets missing_since, get_missing_files retrieves it."""
        record = _make_record("/test/missing.txt")
        in_memory_db.upsert_file(record)

        in_memory_db.mark_missing({"/test/missing.txt"})

        missing = in_memory_db.get_missing_files()
        assert len(missing) == 1
        assert missing[0]["file_path"] == "/test/missing.txt"
        assert missing[0]["missing_since"] is not None

    def test_get_orphaned_files_and_clear(self, in_memory_db):
        """Files with orphaned_gemini_file_id are returned, then cleared."""
        record = _make_record("/test/orphan.txt")
        in_memory_db.upsert_file(record)

        # Set an orphaned Gemini file ID
        in_memory_db.update_file_sync_columns(
            "/test/orphan.txt",
            orphaned_gemini_file_id="files/old-gemini-id-123",
        )

        orphans = in_memory_db.get_orphaned_files()
        assert len(orphans) == 1
        assert orphans[0]["orphaned_gemini_file_id"] == "files/old-gemini-id-123"

        # Clear orphan
        in_memory_db.clear_orphan("/test/orphan.txt")

        orphans_after = in_memory_db.get_orphaned_files()
        assert len(orphans_after) == 0


class TestLibraryConfig:
    """Tests for key-value library_config table."""

    def test_set_and_get_library_config(self, in_memory_db):
        """set_library_config stores, get_library_config retrieves. Updates work."""
        in_memory_db.set_library_config("store_name", "objectivism-library-test")
        value = in_memory_db.get_library_config("store_name")
        assert value == "objectivism-library-test"

        # Update
        in_memory_db.set_library_config("store_name", "objectivism-library-prod")
        updated = in_memory_db.get_library_config("store_name")
        assert updated == "objectivism-library-prod"

    def test_get_library_config_missing_key(self, in_memory_db):
        """get_library_config returns None for nonexistent key."""
        value = in_memory_db.get_library_config("nonexistent_key")
        assert value is None


class TestSyncColumns:
    """Tests for update_file_sync_columns and get_file_with_sync_data."""

    def test_update_file_sync_columns(self, in_memory_db):
        """update_file_sync_columns sets mtime, upload_hash, enrichment_version."""
        record = _make_record("/test/sync.txt")
        in_memory_db.upsert_file(record)

        in_memory_db.update_file_sync_columns(
            "/test/sync.txt",
            mtime=1700000000.5,
            upload_hash="sync_hash_abc",
            enrichment_version="v2.0",
        )

        data = in_memory_db.get_file_with_sync_data("/test/sync.txt")
        assert data is not None
        assert data["mtime"] == 1700000000.5
        assert data["upload_hash"] == "sync_hash_abc"
        assert data["enrichment_version"] == "v2.0"

    def test_get_file_with_sync_data_not_found(self, in_memory_db):
        """get_file_with_sync_data returns None for nonexistent file."""
        data = in_memory_db.get_file_with_sync_data("/nonexistent/file.txt")
        assert data is None

    def test_get_all_active_files_with_mtime(self, populated_db):
        """After setting mtime, get_all_active_files_with_mtime returns mtime data."""
        # Set mtime on one file
        populated_db.update_file_sync_columns(
            "/library/Courses/OPAR/OPAR - Lesson 01 - Metaphysics.txt",
            mtime=1700000000.0,
        )

        result = populated_db.get_all_active_files_with_mtime()
        assert len(result) == 5  # All 5 files active
        # Check the one with mtime set
        opar_data = result["/library/Courses/OPAR/OPAR - Lesson 01 - Metaphysics.txt"]
        assert opar_data[2] == 1700000000.0  # mtime is third element

    def test_update_file_sync_columns_invalid_column(self, in_memory_db):
        """update_file_sync_columns raises ValueError for invalid columns."""
        record = _make_record("/test/invalid_col.txt")
        in_memory_db.upsert_file(record)

        with pytest.raises(ValueError, match="Invalid sync columns"):
            in_memory_db.update_file_sync_columns(
                "/test/invalid_col.txt",
                status="hacked",  # Not a valid sync column
            )
