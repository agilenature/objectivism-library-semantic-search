"""SQLite database layer for the Objectivism Library scanner.

Manages schema initialization, WAL mode pragmas, UPSERT operations,
change detection queries, and audit logging.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from objlib.models import FileRecord, FileStatus, MetadataQuality

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
-- Core files table
CREATE TABLE IF NOT EXISTS files (
    file_path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_size INTEGER NOT NULL,

    -- Metadata (JSON blob for flexibility)
    metadata_json TEXT,
    metadata_quality TEXT DEFAULT 'unknown'
        CHECK(metadata_quality IN ('complete', 'partial', 'minimal', 'none', 'unknown')),

    -- State management
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'uploading', 'uploaded', 'failed', 'LOCAL_DELETE')),
    error_message TEXT,

    -- API integration (null in Phase 1)
    gemini_file_uri TEXT,
    gemini_file_id TEXT,
    upload_timestamp TEXT,
    remote_expiration_ts TEXT,
    embedding_model_version TEXT,

    -- Timestamps (ISO 8601 with milliseconds)
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

-- Indexes (content_hash is NOT UNIQUE - allows duplicate content at different paths)
CREATE INDEX IF NOT EXISTS idx_content_hash ON files(content_hash);
CREATE INDEX IF NOT EXISTS idx_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_metadata_quality ON files(metadata_quality);

-- Auto-update updated_at on any change
CREATE TRIGGER IF NOT EXISTS update_files_timestamp
    AFTER UPDATE ON files
    FOR EACH ROW
    BEGIN
        UPDATE files SET updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')
        WHERE file_path = NEW.file_path;
    END;

-- Status transition audit log
CREATE TABLE IF NOT EXISTS _processing_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT,
    timestamp TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    error_details TEXT,
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);

-- Auto-log status transitions
CREATE TRIGGER IF NOT EXISTS log_status_change
    AFTER UPDATE OF status ON files
    FOR EACH ROW
    WHEN OLD.status != NEW.status
    BEGIN
        INSERT INTO _processing_log(file_path, old_status, new_status)
        VALUES (NEW.file_path, OLD.status, NEW.status);
    END;

-- Extraction failures for pattern discovery
CREATE TABLE IF NOT EXISTS _extraction_failures (
    failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    unparsed_folder_name TEXT,
    unparsed_filename TEXT,
    timestamp TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);

-- Skipped files log
CREATE TABLE IF NOT EXISTS _skipped_files (
    skip_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    reason TEXT NOT NULL,
    file_size INTEGER,
    timestamp TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

-- Upload operations tracking (Phase 2)
CREATE TABLE IF NOT EXISTS upload_operations (
    operation_name TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    gemini_file_name TEXT,
    operation_state TEXT NOT NULL DEFAULT 'pending'
        CHECK(operation_state IN ('pending', 'in_progress', 'succeeded', 'failed', 'timeout')),
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    last_polled_at TEXT,
    completed_at TEXT,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);

CREATE INDEX IF NOT EXISTS idx_upload_ops_state ON upload_operations(operation_state);
CREATE INDEX IF NOT EXISTS idx_upload_ops_file ON upload_operations(file_path);

-- Logical batch tracking
CREATE TABLE IF NOT EXISTS upload_batches (
    batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_number INTEGER NOT NULL,
    file_count INTEGER NOT NULL,
    succeeded_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending', 'in_progress', 'completed', 'failed')),
    started_at TEXT,
    completed_at TEXT
);

-- Single-writer lock (max one row enforced by CHECK)
CREATE TABLE IF NOT EXISTS upload_locks (
    lock_id INTEGER PRIMARY KEY CHECK(lock_id = 1),
    instance_id TEXT NOT NULL,
    acquired_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    last_heartbeat TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
"""

UPSERT_SQL = """
INSERT INTO files(file_path, content_hash, filename, file_size,
                  metadata_json, metadata_quality, status)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(file_path) DO UPDATE SET
    content_hash = excluded.content_hash,
    file_size = excluded.file_size,
    metadata_json = excluded.metadata_json,
    metadata_quality = excluded.metadata_quality,
    status = CASE
        WHEN files.content_hash != excluded.content_hash THEN 'pending'
        ELSE files.status
    END
"""


class Database:
    """SQLite database wrapper for the Objectivism Library scanner.

    Manages connection lifecycle, schema initialization, and provides
    CRUD operations for file records with UPSERT support.

    Usage:
        with Database("data/library.db") as db:
            db.upsert_file(record)
            counts = db.get_status_counts()
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(
            self.db_path,
            autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
        )
        self.conn.row_factory = sqlite3.Row
        self._setup_pragmas()
        self._setup_schema()

    def _setup_pragmas(self) -> None:
        """Configure SQLite pragmas for performance and reliability."""
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=-10000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA temp_store=MEMORY")

        # Verify WAL mode
        result = self.conn.execute("PRAGMA journal_mode").fetchone()[0]
        if result != "wal":
            logger.warning("WAL mode not enabled, got: %s", result)

    def _setup_schema(self) -> None:
        """Create tables, indexes, and triggers if they don't exist."""
        self.conn.executescript(SCHEMA_SQL)
        self.conn.execute("PRAGMA user_version = 2")

    def upsert_file(self, record: FileRecord) -> None:
        """Insert or update a single file record.

        On conflict (same file_path):
        - Updates content_hash, file_size, metadata_json, metadata_quality
        - Resets status to 'pending' ONLY if content_hash changed
        - Preserves created_at (updated_at handled by trigger)

        Args:
            record: FileRecord to insert or update.
        """
        with self.conn:
            self.conn.execute(
                UPSERT_SQL,
                (
                    record.file_path,
                    record.content_hash,
                    record.filename,
                    record.file_size,
                    record.metadata_json,
                    record.metadata_quality.value,
                    record.status.value,
                ),
            )

    def upsert_files(self, records: list[FileRecord]) -> None:
        """Batch UPSERT file records in a single transaction.

        Args:
            records: List of FileRecord objects to insert or update.
        """
        with self.conn:
            self.conn.executemany(
                UPSERT_SQL,
                [
                    (
                        r.file_path,
                        r.content_hash,
                        r.filename,
                        r.file_size,
                        r.metadata_json,
                        r.metadata_quality.value,
                        r.status.value,
                    )
                    for r in records
                ],
            )

    def get_all_active_files(self) -> dict[str, tuple[str, int]]:
        """Return all non-deleted files as {file_path: (content_hash, file_size)}.

        Used by the change detection algorithm to compare current scan
        results against database state.
        """
        rows = self.conn.execute(
            "SELECT file_path, content_hash, file_size FROM files WHERE status != ?",
            (FileStatus.LOCAL_DELETE.value,),
        ).fetchall()
        return {row["file_path"]: (row["content_hash"], row["file_size"]) for row in rows}

    def mark_deleted(self, file_paths: set[str]) -> None:
        """Mark files as locally deleted.

        Sets status to LOCAL_DELETE for the given paths. The status change
        trigger automatically logs this transition to _processing_log.

        Args:
            file_paths: Set of file paths to mark as deleted.
        """
        if not file_paths:
            return
        with self.conn:
            for path in file_paths:
                self.conn.execute(
                    "UPDATE files SET status = ? WHERE file_path = ?",
                    (FileStatus.LOCAL_DELETE.value, path),
                )

    def get_status_counts(self) -> dict[str, int]:
        """Return count of files grouped by status.

        Returns:
            Dictionary mapping status string to count.
        """
        rows = self.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM files GROUP BY status"
        ).fetchall()
        return {row["status"]: row["cnt"] for row in rows}

    def get_quality_counts(self) -> dict[str, int]:
        """Return count of files grouped by metadata quality.

        Returns:
            Dictionary mapping quality string to count.
        """
        rows = self.conn.execute(
            "SELECT metadata_quality, COUNT(*) as cnt FROM files GROUP BY metadata_quality"
        ).fetchall()
        return {row["metadata_quality"]: row["cnt"] for row in rows}

    def log_skipped_file(
        self, file_path: str, reason: str, file_size: int | None = None
    ) -> None:
        """Log a skipped file with reason.

        Args:
            file_path: Path of the skipped file.
            reason: Why the file was skipped.
            file_size: Optional file size in bytes.
        """
        with self.conn:
            self.conn.execute(
                "INSERT INTO _skipped_files(file_path, reason, file_size) VALUES (?, ?, ?)",
                (file_path, reason, file_size),
            )

    def log_extraction_failure(
        self,
        file_path: str,
        folder_name: str | None = None,
        filename: str | None = None,
    ) -> None:
        """Log a metadata extraction failure for later review.

        Args:
            file_path: Path of the file with extraction failure.
            folder_name: Unparsed folder name, if available.
            filename: Unparsed filename, if available.
        """
        with self.conn:
            self.conn.execute(
                "INSERT INTO _extraction_failures(file_path, unparsed_folder_name, unparsed_filename) VALUES (?, ?, ?)",
                (file_path, folder_name, filename),
            )

    def get_pending_files(self, limit: int = 200) -> list[sqlite3.Row]:
        """Return files with status='pending' for upload processing.

        Args:
            limit: Maximum number of rows to return.

        Returns:
            List of sqlite3.Row with file_path, content_hash, filename,
            file_size, and metadata_json columns.
        """
        return self.conn.execute(
            """SELECT file_path, content_hash, filename, file_size, metadata_json
               FROM files
               WHERE status = ?
               ORDER BY file_path
               LIMIT ?""",
            (FileStatus.PENDING.value, limit),
        ).fetchall()

    def update_file_status(self, file_path: str, status: FileStatus, **kwargs: object) -> None:
        """Update a file's status and optional additional columns.

        Args:
            file_path: Primary key of the file to update.
            status: New FileStatus value.
            **kwargs: Additional column=value pairs to set (e.g.,
                gemini_file_uri, gemini_file_id, upload_timestamp,
                error_message).
        """
        set_parts = ["status = ?"]
        params: list[object] = [status.value]

        for col, val in kwargs.items():
            set_parts.append(f"{col} = ?")
            params.append(val)

        params.append(file_path)
        sql = f"UPDATE files SET {', '.join(set_parts)} WHERE file_path = ?"

        with self.conn:
            self.conn.execute(sql, params)

    def get_file_count(self) -> int:
        """Return total count of files (all statuses).

        Returns:
            Integer count of all file records.
        """
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM files").fetchone()
        return row["cnt"]

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: object) -> None:
        self.close()
