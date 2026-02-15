"""Database layer tests.

Validates:
  FOUN-01: WAL mode enabled
  FOUN-06: Idempotent UPSERT
  FOUN-09: Status transitions and audit logging
"""

from __future__ import annotations

import json

from objlib.database import Database
from objlib.models import FileRecord, FileStatus, MetadataQuality


def _make_record(
    path: str = "/test/file.txt",
    content_hash: str = "abc123",
    file_size: int = 2048,
    quality: MetadataQuality = MetadataQuality.COMPLETE,
    status: FileStatus = FileStatus.PENDING,
) -> FileRecord:
    """Helper to create a FileRecord with defaults."""
    return FileRecord(
        file_path=path,
        content_hash=content_hash,
        filename=path.split("/")[-1],
        file_size=file_size,
        metadata_json=json.dumps({"course": "Test"}),
        metadata_quality=quality,
        status=status,
    )


def test_wal_mode_enabled(tmp_db: Database) -> None:
    """FOUN-01: WAL journal mode must be enabled."""
    result = tmp_db.conn.execute("PRAGMA journal_mode").fetchone()
    assert result[0] == "wal"


def test_tables_exist(tmp_db: Database) -> None:
    """All 4 tables must exist after schema init."""
    rows = tmp_db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {row["name"] for row in rows}

    assert "files" in table_names
    assert "_processing_log" in table_names
    assert "_extraction_failures" in table_names
    assert "_skipped_files" in table_names


def test_insert_and_retrieve(tmp_db: Database) -> None:
    """Insert a FileRecord and verify all fields are retrievable."""
    record = _make_record()
    tmp_db.upsert_file(record)

    row = tmp_db.conn.execute(
        "SELECT * FROM files WHERE file_path = ?", (record.file_path,)
    ).fetchone()

    assert row is not None
    assert row["file_path"] == record.file_path
    assert row["content_hash"] == record.content_hash
    assert row["filename"] == record.filename
    assert row["file_size"] == record.file_size
    assert row["metadata_quality"] == "complete"
    assert row["status"] == "pending"


def test_upsert_idempotent(tmp_db: Database) -> None:
    """FOUN-06: Inserting the same record twice keeps count at 1."""
    record = _make_record()
    tmp_db.upsert_file(record)
    tmp_db.upsert_file(record)

    count = tmp_db.conn.execute("SELECT COUNT(*) as cnt FROM files").fetchone()["cnt"]
    assert count == 1


def test_upsert_updates_on_hash_change(tmp_db: Database) -> None:
    """When content_hash changes, UPSERT updates hash and resets status to pending."""
    record = _make_record(status=FileStatus.UPLOADED)
    tmp_db.upsert_file(record)

    # Change the hash
    modified = _make_record(content_hash="new_hash_456")
    tmp_db.upsert_file(modified)

    row = tmp_db.conn.execute(
        "SELECT content_hash, status FROM files WHERE file_path = ?",
        (record.file_path,),
    ).fetchone()

    assert row["content_hash"] == "new_hash_456"
    assert row["status"] == "pending"  # Reset due to hash change


def test_upsert_preserves_status_on_same_hash(tmp_db: Database) -> None:
    """When content_hash is unchanged, UPSERT preserves existing status."""
    record = _make_record()
    tmp_db.upsert_file(record)

    # Manually update status to 'uploaded'
    with tmp_db.conn:
        tmp_db.conn.execute(
            "UPDATE files SET status = ? WHERE file_path = ?",
            (FileStatus.UPLOADED.value, record.file_path),
        )

    # Re-upsert with same hash
    tmp_db.upsert_file(record)

    row = tmp_db.conn.execute(
        "SELECT status FROM files WHERE file_path = ?",
        (record.file_path,),
    ).fetchone()

    assert row["status"] == "uploaded"  # Preserved


def test_mark_deleted(tmp_db: Database) -> None:
    """mark_deleted sets status to LOCAL_DELETE."""
    record = _make_record()
    tmp_db.upsert_file(record)

    tmp_db.mark_deleted({record.file_path})

    row = tmp_db.conn.execute(
        "SELECT status FROM files WHERE file_path = ?",
        (record.file_path,),
    ).fetchone()

    assert row["status"] == "LOCAL_DELETE"


def test_status_transition_logged(tmp_db: Database) -> None:
    """FOUN-09: Status changes are logged to _processing_log via trigger."""
    record = _make_record()
    tmp_db.upsert_file(record)

    # Change status
    with tmp_db.conn:
        tmp_db.conn.execute(
            "UPDATE files SET status = ? WHERE file_path = ?",
            (FileStatus.UPLOADED.value, record.file_path),
        )

    logs = tmp_db.conn.execute(
        "SELECT * FROM _processing_log WHERE file_path = ?",
        (record.file_path,),
    ).fetchall()

    assert len(logs) >= 1
    assert logs[0]["old_status"] == "pending"
    assert logs[0]["new_status"] == "uploaded"


def test_batch_upsert(tmp_db: Database) -> None:
    """Batch insert of 100 records should all be persisted."""
    records = [
        _make_record(path=f"/test/file_{i:03d}.txt", content_hash=f"hash_{i}")
        for i in range(100)
    ]
    tmp_db.upsert_files(records)

    count = tmp_db.conn.execute("SELECT COUNT(*) as cnt FROM files").fetchone()["cnt"]
    assert count == 100


def test_content_hash_not_unique(tmp_db: Database) -> None:
    """CRITICAL: Two files with same content_hash but different paths must both exist.

    This validates the research correction: content_hash is indexed but NOT UNIQUE.
    """
    record1 = _make_record(path="/path/a/file.txt", content_hash="same_hash")
    record2 = _make_record(path="/path/b/file.txt", content_hash="same_hash")

    tmp_db.upsert_file(record1)
    tmp_db.upsert_file(record2)

    count = tmp_db.conn.execute("SELECT COUNT(*) as cnt FROM files").fetchone()["cnt"]
    assert count == 2


def test_status_counts(tmp_db: Database) -> None:
    """get_status_counts returns correct counts for each status."""
    records = [
        _make_record(path="/pending/1.txt", content_hash="h1"),
        _make_record(path="/pending/2.txt", content_hash="h2"),
        _make_record(path="/pending/3.txt", content_hash="h3"),
    ]
    tmp_db.upsert_files(records)

    # Mark one as uploaded
    with tmp_db.conn:
        tmp_db.conn.execute(
            "UPDATE files SET status = ? WHERE file_path = ?",
            (FileStatus.UPLOADED.value, "/pending/1.txt"),
        )

    counts = tmp_db.get_status_counts()
    assert counts.get("pending") == 2
    assert counts.get("uploaded") == 1


def test_get_all_active_files_excludes_deleted(tmp_db: Database) -> None:
    """get_all_active_files must exclude LOCAL_DELETE records."""
    records = [
        _make_record(path="/active/a.txt", content_hash="h1"),
        _make_record(path="/active/b.txt", content_hash="h2"),
        _make_record(path="/deleted/c.txt", content_hash="h3"),
    ]
    tmp_db.upsert_files(records)
    tmp_db.mark_deleted({"/deleted/c.txt"})

    active = tmp_db.get_all_active_files()
    assert "/active/a.txt" in active
    assert "/active/b.txt" in active
    assert "/deleted/c.txt" not in active
