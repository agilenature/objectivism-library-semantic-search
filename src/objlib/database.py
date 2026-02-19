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
        CHECK(status IN ('pending', 'uploading', 'uploaded', 'failed', 'skipped', 'LOCAL_DELETE')),
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

MIGRATION_V3_SQL = """
-- Versioned AI metadata storage (append-only with is_current flag)
CREATE TABLE IF NOT EXISTS file_metadata_ai (
    metadata_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    model TEXT NOT NULL,
    model_version TEXT,
    prompt_version TEXT NOT NULL,
    extraction_config_hash TEXT,
    is_current BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);

CREATE INDEX IF NOT EXISTS idx_metadata_ai_current
    ON file_metadata_ai(file_path, is_current);

-- Fast filtering on controlled vocabulary (Tier 2 primary topics)
CREATE TABLE IF NOT EXISTS file_primary_topics (
    file_path TEXT NOT NULL,
    topic_tag TEXT NOT NULL,
    PRIMARY KEY (file_path, topic_tag),
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);

CREATE INDEX IF NOT EXISTS idx_primary_topic_tag
    ON file_primary_topics(topic_tag);

-- Wave 1 competitive strategy comparison results
CREATE TABLE IF NOT EXISTS wave1_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    strategy TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    raw_response TEXT,
    token_count INTEGER,
    latency_ms INTEGER,
    confidence_score REAL,
    human_edit_distance REAL,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);
"""

MIGRATION_V4_SQL = """
-- Canonical person registry
CREATE TABLE IF NOT EXISTS person (
    person_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK(type IN ('philosopher', 'ari_instructor')),
    notes TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

-- Alias lookup table
CREATE TABLE IF NOT EXISTS person_alias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias_text TEXT NOT NULL,
    person_id TEXT NOT NULL,
    alias_type TEXT CHECK(alias_type IN ('nickname', 'misspelling', 'partial', 'initials', 'title_variant', 'full_name')),
    is_blocked BOOLEAN DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (person_id) REFERENCES person(person_id)
);

CREATE INDEX IF NOT EXISTS idx_person_alias_text ON person_alias(alias_text COLLATE NOCASE);

-- Transcript-level entity summary
CREATE TABLE IF NOT EXISTS transcript_entity (
    transcript_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    mention_count INTEGER NOT NULL CHECK(mention_count >= 1),
    first_seen_char INTEGER,
    max_confidence REAL CHECK(max_confidence >= 0.0 AND max_confidence <= 1.0),
    evidence_sample TEXT,
    extraction_version TEXT NOT NULL,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    PRIMARY KEY (transcript_id, person_id),
    FOREIGN KEY (person_id) REFERENCES person(person_id)
);

CREATE INDEX IF NOT EXISTS idx_transcript_entity_person ON transcript_entity(person_id);

-- Seed 15 canonical persons
INSERT OR IGNORE INTO person (person_id, canonical_name, type) VALUES
    ('ayn-rand', 'Ayn Rand', 'philosopher'),
    ('leonard-peikoff', 'Leonard Peikoff', 'ari_instructor'),
    ('onkar-ghate', 'Onkar Ghate', 'ari_instructor'),
    ('robert-mayhew', 'Robert Mayhew', 'ari_instructor'),
    ('tara-smith', 'Tara Smith', 'ari_instructor'),
    ('ben-bayer', 'Ben Bayer', 'ari_instructor'),
    ('mike-mazza', 'Mike Mazza', 'ari_instructor'),
    ('aaron-smith', 'Aaron Smith', 'ari_instructor'),
    ('tristan-de-liege', 'Tristan de Liege', 'ari_instructor'),
    ('gregory-salmieri', 'Gregory Salmieri', 'ari_instructor'),
    ('harry-binswanger', 'Harry Binswanger', 'ari_instructor'),
    ('jean-moroney', 'Jean Moroney', 'ari_instructor'),
    ('yaron-brook', 'Yaron Brook', 'ari_instructor'),
    ('don-watkins', 'Don Watkins', 'ari_instructor'),
    ('keith-lockitch', 'Keith Lockitch', 'ari_instructor');

-- Seed aliases: full names as alias_type='full_name'
INSERT OR IGNORE INTO person_alias (alias_text, person_id, alias_type) VALUES
    ('Ayn Rand', 'ayn-rand', 'full_name'),
    ('Leonard Peikoff', 'leonard-peikoff', 'full_name'),
    ('Onkar Ghate', 'onkar-ghate', 'full_name'),
    ('Robert Mayhew', 'robert-mayhew', 'full_name'),
    ('Tara Smith', 'tara-smith', 'full_name'),
    ('Ben Bayer', 'ben-bayer', 'full_name'),
    ('Mike Mazza', 'mike-mazza', 'full_name'),
    ('Aaron Smith', 'aaron-smith', 'full_name'),
    ('Tristan de Liege', 'tristan-de-liege', 'full_name'),
    ('Gregory Salmieri', 'gregory-salmieri', 'full_name'),
    ('Harry Binswanger', 'harry-binswanger', 'full_name'),
    ('Jean Moroney', 'jean-moroney', 'full_name'),
    ('Yaron Brook', 'yaron-brook', 'full_name'),
    ('Don Watkins', 'don-watkins', 'full_name'),
    ('Keith Lockitch', 'keith-lockitch', 'full_name');

-- Seed aliases: high-uniqueness surname partials
INSERT OR IGNORE INTO person_alias (alias_text, person_id, alias_type) VALUES
    ('Rand', 'ayn-rand', 'partial'),
    ('Peikoff', 'leonard-peikoff', 'partial'),
    ('Ghate', 'onkar-ghate', 'partial'),
    ('Mayhew', 'robert-mayhew', 'partial'),
    ('Salmieri', 'gregory-salmieri', 'partial'),
    ('Mazza', 'mike-mazza', 'partial'),
    ('Liege', 'tristan-de-liege', 'partial'),
    ('Lockitch', 'keith-lockitch', 'partial'),
    ('Moroney', 'jean-moroney', 'partial'),
    ('Brook', 'yaron-brook', 'partial'),
    ('Watkins', 'don-watkins', 'partial'),
    ('Bayer', 'ben-bayer', 'partial'),
    ('Binswanger', 'harry-binswanger', 'partial');

-- Seed aliases: title variants
INSERT OR IGNORE INTO person_alias (alias_text, person_id, alias_type) VALUES
    ('Dr. Peikoff', 'leonard-peikoff', 'title_variant'),
    ('Professor Salmieri', 'gregory-salmieri', 'title_variant'),
    ('Dr. Ghate', 'onkar-ghate', 'title_variant'),
    ('Dr. Binswanger', 'harry-binswanger', 'title_variant');

-- Seed aliases: nickname/partial first names (high-uniqueness only)
INSERT OR IGNORE INTO person_alias (alias_text, person_id, alias_type) VALUES
    ('Onkar', 'onkar-ghate', 'nickname'),
    ('Tristan', 'tristan-de-liege', 'nickname'),
    ('Yaron', 'yaron-brook', 'nickname');

-- Seed blocked aliases (ambiguous names requiring full name for resolution)
INSERT OR IGNORE INTO person_alias (alias_text, person_id, alias_type, is_blocked) VALUES
    ('Smith', 'tara-smith', 'partial', 1),
    ('Aaron', 'aaron-smith', 'nickname', 1),
    ('Tara', 'tara-smith', 'nickname', 1),
    ('Ben', 'ben-bayer', 'nickname', 1),
    ('Mike', 'mike-mazza', 'nickname', 1),
    ('Harry', 'harry-binswanger', 'nickname', 1),
    ('Greg', 'gregory-salmieri', 'nickname', 1),
    ('Keith', 'keith-lockitch', 'nickname', 1),
    ('Don', 'don-watkins', 'nickname', 1);
"""

MIGRATION_V6_SQL = """
-- Passages cache for citation stability
CREATE TABLE IF NOT EXISTS passages (
    passage_id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    content_hash TEXT,
    passage_text TEXT NOT NULL,
    source TEXT DEFAULT 'gemini_grounding',
    is_stale BOOLEAN DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    last_seen_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_passages_file ON passages(file_id);
CREATE INDEX IF NOT EXISTS idx_passages_hash ON passages(content_hash);

-- Research session tracking
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

-- Session event log
CREATE TABLE IF NOT EXISTS session_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('search', 'view', 'synthesize', 'note', 'error', 'bookmark')),
    payload_json TEXT NOT NULL,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_session_events_session ON session_events(session_id);
"""

MIGRATION_V7_SQL = """
-- V7: Table rebuild to expand CHECK constraint for 'missing' and 'error' statuses
-- plus 5 new sync columns (mtime, orphaned_gemini_file_id, missing_since, upload_hash, enrichment_version)

-- Safety: drop partial migration artifact if previous attempt failed
DROP TABLE IF EXISTS files_v7;

-- Step 1: Create new table with expanded schema
CREATE TABLE files_v7 (
    file_path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_size INTEGER NOT NULL,

    -- Metadata (JSON blob for flexibility)
    metadata_json TEXT,
    metadata_quality TEXT DEFAULT 'unknown'
        CHECK(metadata_quality IN ('complete', 'partial', 'minimal', 'none', 'unknown')),

    -- State management (expanded for sync)
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'uploading', 'uploaded', 'failed', 'skipped', 'LOCAL_DELETE', 'missing', 'error')),
    error_message TEXT,

    -- API integration
    gemini_file_uri TEXT,
    gemini_file_id TEXT,
    upload_timestamp TEXT,
    remote_expiration_ts TEXT,
    embedding_model_version TEXT,

    -- Timestamps (ISO 8601 with milliseconds)
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),

    -- AI metadata (V3)
    ai_metadata_status TEXT DEFAULT 'pending',
    ai_confidence_score REAL,

    -- Entity extraction (V4)
    entity_extraction_version TEXT,
    entity_extraction_status TEXT DEFAULT 'pending',

    -- Enriched upload (V5)
    upload_attempt_count INTEGER DEFAULT 0,
    last_upload_hash TEXT,

    -- Sync columns (V7)
    mtime REAL,
    orphaned_gemini_file_id TEXT,
    missing_since TEXT,
    upload_hash TEXT,
    enrichment_version TEXT
);

-- Step 2: Copy all existing data (21 existing columns + 5 NULLs for new V7 columns)
INSERT INTO files_v7 (
    file_path, content_hash, filename, file_size,
    metadata_json, metadata_quality, status, error_message,
    gemini_file_uri, gemini_file_id, upload_timestamp, remote_expiration_ts, embedding_model_version,
    created_at, updated_at,
    ai_metadata_status, ai_confidence_score,
    entity_extraction_version, entity_extraction_status,
    upload_attempt_count, last_upload_hash,
    mtime, orphaned_gemini_file_id, missing_since, upload_hash, enrichment_version
)
SELECT
    file_path, content_hash, filename, file_size,
    metadata_json, metadata_quality, status, error_message,
    gemini_file_uri, gemini_file_id, upload_timestamp, remote_expiration_ts, embedding_model_version,
    created_at, updated_at,
    ai_metadata_status, ai_confidence_score,
    entity_extraction_version, entity_extraction_status,
    upload_attempt_count, last_upload_hash,
    NULL, NULL, NULL, NULL, NULL
FROM files;

-- Step 3: Drop old table, rename new
DROP TABLE files;
ALTER TABLE files_v7 RENAME TO files;

-- Step 4: Recreate indexes
CREATE INDEX idx_content_hash ON files(content_hash);
CREATE INDEX idx_status ON files(status);
CREATE INDEX idx_metadata_quality ON files(metadata_quality);

-- Step 5: Recreate triggers
CREATE TRIGGER update_files_timestamp
    AFTER UPDATE ON files
    FOR EACH ROW
    BEGIN
        UPDATE files SET updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')
        WHERE file_path = NEW.file_path;
    END;

CREATE TRIGGER log_status_change
    AFTER UPDATE OF status ON files
    FOR EACH ROW
    WHEN OLD.status != NEW.status
    BEGIN
        INSERT INTO _processing_log(file_path, old_status, new_status)
        VALUES (NEW.file_path, OLD.status, NEW.status);
    END;

-- Step 6: Library config table for sync key-value pairs
CREATE TABLE IF NOT EXISTS library_config (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

"""

MIGRATION_V8_SQL = """
-- V8: Rebuild session_events to expand CHECK constraint for 'bookmark' event type

-- Safety: drop partial migration artifact if previous attempt failed
DROP TABLE IF EXISTS session_events_v8;

-- Step 1: Create new table with expanded CHECK
CREATE TABLE session_events_v8 (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('search', 'view', 'synthesize', 'note', 'error', 'bookmark')),
    payload_json TEXT NOT NULL,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- Step 2: Copy existing data
INSERT INTO session_events_v8 (id, session_id, event_type, payload_json, created_at)
SELECT id, session_id, event_type, payload_json, created_at
FROM session_events;

-- Step 3: Drop old table, rename new
DROP TABLE session_events;
ALTER TABLE session_events_v8 RENAME TO session_events;

-- Step 4: Recreate index
CREATE INDEX idx_session_events_session ON session_events(session_id);
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
        """Create tables, indexes, and triggers if they don't exist.

        Handles migrations:
        - v3: ai_metadata_status/ai_confidence_score columns, AI metadata tables
        - v4: Person registry, aliases, transcript entities
        - v5: upload_attempt_count, last_upload_hash columns
        - v6: passages cache, sessions, session_events tables
        - v7: Table rebuild for expanded CHECK constraint (missing/error),
              5 new sync columns, library_config table
        - v8: session_events table rebuild for 'bookmark' event type
        """
        self.conn.executescript(SCHEMA_SQL)

        version = self.conn.execute("PRAGMA user_version").fetchone()[0]

        if version < 3:
            # Add new columns to files table (use try/except because
            # ALTER TABLE ADD COLUMN fails if column already exists)
            for alter_sql in [
                "ALTER TABLE files ADD COLUMN ai_metadata_status TEXT DEFAULT 'pending'",
                "ALTER TABLE files ADD COLUMN ai_confidence_score REAL",
            ]:
                try:
                    self.conn.execute(alter_sql)
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # Create new tables (IF NOT EXISTS handles idempotency)
            self.conn.executescript(MIGRATION_V3_SQL)

        if version < 4:
            self.conn.executescript(MIGRATION_V4_SQL)
            # Add entity extraction columns to files table
            for alter_sql in [
                "ALTER TABLE files ADD COLUMN entity_extraction_version TEXT",
                "ALTER TABLE files ADD COLUMN entity_extraction_status TEXT DEFAULT 'pending'",
            ]:
                try:
                    self.conn.execute(alter_sql)
                except sqlite3.OperationalError:
                    pass  # Column already exists

        if version < 5:
            for alter_sql in [
                "ALTER TABLE files ADD COLUMN upload_attempt_count INTEGER DEFAULT 0",
                "ALTER TABLE files ADD COLUMN last_upload_hash TEXT",
            ]:
                try:
                    self.conn.execute(alter_sql)
                except sqlite3.OperationalError:
                    pass  # Column already exists

        if version < 6:
            self.conn.executescript(MIGRATION_V6_SQL)

        if version < 7:
            # Temporarily disable FK checks for table rebuild
            # (other tables have FK references to files)
            self.conn.execute("PRAGMA foreign_keys = OFF")
            self.conn.executescript(MIGRATION_V7_SQL)
            self.conn.execute("PRAGMA foreign_keys = ON")

        if version < 8:
            self.conn.executescript(MIGRATION_V8_SQL)

        self.conn.execute("PRAGMA user_version = 8")

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

    def get_file_metadata_by_filenames(self, filenames: list[str]) -> dict[str, dict]:
        """Return metadata for files matching the given filenames.

        Used to enrich Gemini citations (which provide display_name/title)
        with local metadata (course, year, difficulty, etc).

        Args:
            filenames: List of filename strings to look up.

        Returns:
            Dict mapping filename -> {"file_path": str, "metadata": dict}
        """
        if not filenames:
            return {}
        placeholders = ",".join("?" * len(filenames))
        rows = self.conn.execute(
            f"SELECT filename, file_path, metadata_json FROM files "
            f"WHERE filename IN ({placeholders}) AND status != 'LOCAL_DELETE'",
            filenames,
        ).fetchall()

        import json

        result = {}
        for row in rows:
            meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            result[row["filename"]] = {
                "file_path": row["file_path"],
                "metadata": meta,
            }
        return result

    def get_file_metadata_by_gemini_ids(self, gemini_ids: list[str]) -> dict[str, dict]:
        """Return metadata for files matching the given Gemini file IDs.

        Used to enrich Gemini citations when the title field contains
        the Gemini file ID instead of the display_name/filename.

        Handles both formats: "e0x3xq9wtglq" and "files/e0x3xq9wtglq".

        Args:
            gemini_ids: List of Gemini file ID strings (e.g., "e0x3xq9wtglq").

        Returns:
            Dict mapping gemini_file_id -> {"filename": str, "file_path": str, "metadata": dict}
        """
        if not gemini_ids:
            return {}

        # Normalize IDs: add "files/" prefix if not present
        normalized_ids = []
        original_to_normalized = {}
        for gid in gemini_ids:
            normalized = gid if gid.startswith("files/") else f"files/{gid}"
            normalized_ids.append(normalized)
            original_to_normalized[gid] = normalized

        placeholders = ",".join("?" * len(normalized_ids))
        rows = self.conn.execute(
            f"SELECT gemini_file_id, filename, file_path, metadata_json FROM files "
            f"WHERE gemini_file_id IN ({placeholders})",
            normalized_ids,
        ).fetchall()

        import json

        result = {}
        for row in rows:
            meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            # Map back to the original (un-normalized) ID that was passed in
            for original_id, normalized_id in original_to_normalized.items():
                if row["gemini_file_id"] == normalized_id:
                    result[original_id] = {
                        "filename": row["filename"],
                        "file_path": row["file_path"],
                        "metadata": meta,
                    }
        return result

    def get_pending_files(self, limit: int = 200) -> list[sqlite3.Row]:
        """Return files with status='pending' for upload processing.

        Filters to .txt files only -- other file types are skipped.

        Args:
            limit: Maximum number of rows to return.

        Returns:
            List of sqlite3.Row with file_path, content_hash, filename,
            file_size, and metadata_json columns (only .txt files).
        """
        return self.conn.execute(
            """SELECT file_path, content_hash, filename, file_size, metadata_json
               FROM files
               WHERE status = ? AND filename LIKE '%.txt'
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

    def get_categories_with_counts(self) -> list[tuple[str, int]]:
        """Return top-level categories with file counts.

        Categories are extracted from metadata_json '$.category'.
        NULL category values are mapped to 'uncategorized'.
        LOCAL_DELETE records are excluded.

        Returns:
            List of (category_name, count) tuples, ordered by count descending.
        """
        rows = self.conn.execute(
            """SELECT COALESCE(json_extract(metadata_json, '$.category'), 'uncategorized') as category,
                      COUNT(*) as count
               FROM files
               WHERE metadata_json IS NOT NULL AND status != 'LOCAL_DELETE'
               GROUP BY category
               ORDER BY count DESC"""
        ).fetchall()
        return [(row["category"], row["count"]) for row in rows]

    def get_courses_with_counts(self) -> list[tuple[str, int]]:
        """Return all courses with file counts.

        Filters to category='course' and groups by course name.
        LOCAL_DELETE records are excluded.

        Returns:
            List of (course_name, count) tuples, ordered by course name.
        """
        rows = self.conn.execute(
            """SELECT json_extract(metadata_json, '$.course') as course,
                      COUNT(*) as count
               FROM files
               WHERE json_extract(metadata_json, '$.category') = 'course'
                 AND status != 'LOCAL_DELETE'
               GROUP BY course
               ORDER BY course"""
        ).fetchall()
        return [(row["course"], row["count"]) for row in rows]

    def get_files_by_course(self, course: str, year: str | None = None) -> list[dict]:
        """Return files within a specific course, optionally filtered by year.

        Results are ordered by lesson_number, year, quarter, week, then filename.
        LOCAL_DELETE records are excluded.

        Args:
            course: Course name to filter by.
            year: Optional year string to further filter results.

        Returns:
            List of dicts with 'filename', 'file_path', 'metadata' keys.
        """
        import json as json_module

        params: list = [course]
        year_clause = ""
        if year is not None:
            year_clause = "AND json_extract(metadata_json, '$.year') = ? "
            try:
                params.append(int(year))
            except ValueError:
                params.append(year)

        sql = f"""
            SELECT filename, file_path, metadata_json FROM files
            WHERE json_extract(metadata_json, '$.course') = ?
              AND status != 'LOCAL_DELETE'
              {year_clause}
            ORDER BY json_extract(metadata_json, '$.lesson_number'),
                     json_extract(metadata_json, '$.year'),
                     json_extract(metadata_json, '$.quarter'),
                     json_extract(metadata_json, '$.week'),
                     filename
        """

        rows = self.conn.execute(sql, params).fetchall()
        results = []
        for row in rows:
            meta = json_module.loads(row["metadata_json"]) if row["metadata_json"] else {}
            results.append({
                "filename": row["filename"],
                "file_path": row["file_path"],
                "metadata": meta,
            })
        return results

    def get_items_by_category(self, category: str) -> list[dict]:
        """Return files within a non-course category, ordered by filename.

        LOCAL_DELETE records are excluded.

        Args:
            category: Category name to filter by (e.g., 'motm', 'book').

        Returns:
            List of dicts with 'filename', 'file_path', 'metadata' keys.
        """
        import json as json_module

        rows = self.conn.execute(
            """SELECT filename, file_path, metadata_json FROM files
               WHERE json_extract(metadata_json, '$.category') = ?
                 AND status != 'LOCAL_DELETE'
               ORDER BY filename""",
            (category,),
        ).fetchall()

        results = []
        for row in rows:
            meta = json_module.loads(row["metadata_json"]) if row["metadata_json"] else {}
            results.append({
                "filename": row["filename"],
                "file_path": row["file_path"],
                "metadata": meta,
            })
        return results

    def filter_files_by_metadata(self, filters: dict[str, str], limit: int = 50) -> list[dict]:
        """Query files by metadata field values.

        Supports the same fields as Gemini metadata_filter:
        category, course, difficulty, quarter, date, year, week, quality_score.

        Comparison operators in values: >=, <=, >, < are supported.

        Args:
            filters: Dict of {field_name: value_or_comparison}.
            limit: Maximum results.

        Returns:
            List of dicts with 'filename', 'file_path', 'metadata' keys.

        Raises:
            ValueError: If an unknown filter field is provided.
        """
        import json as json_module

        VALID_FIELDS = {"category", "course", "difficulty", "quarter", "date", "year", "week", "quality_score"}
        NUMERIC_FIELDS = {"year", "week", "quality_score"}

        where_parts: list[str] = ["status != 'LOCAL_DELETE'", "metadata_json IS NOT NULL"]
        params: list = []

        for field, value in filters.items():
            if field not in VALID_FIELDS:
                raise ValueError(f"Unknown filter field: {field}. Valid: {', '.join(sorted(VALID_FIELDS))}")

            json_path = f"$.{field}"
            is_numeric = field in NUMERIC_FIELDS

            def _coerce_numeric(val: str) -> int | str:
                """Try to convert to int for proper numeric comparison in SQLite."""
                try:
                    return int(val)
                except ValueError:
                    return val

            # Check for comparison operators
            if value.startswith(">="):
                if is_numeric:
                    where_parts.append("CAST(json_extract(metadata_json, ?) AS INTEGER) >= ?")
                    params.extend([json_path, int(value[2:])])
                else:
                    where_parts.append("json_extract(metadata_json, ?) >= ?")
                    params.extend([json_path, value[2:]])
            elif value.startswith("<="):
                if is_numeric:
                    where_parts.append("CAST(json_extract(metadata_json, ?) AS INTEGER) <= ?")
                    params.extend([json_path, int(value[2:])])
                else:
                    where_parts.append("json_extract(metadata_json, ?) <= ?")
                    params.extend([json_path, value[2:]])
            elif value.startswith(">"):
                if is_numeric:
                    where_parts.append("CAST(json_extract(metadata_json, ?) AS INTEGER) > ?")
                    params.extend([json_path, int(value[1:])])
                else:
                    where_parts.append("json_extract(metadata_json, ?) > ?")
                    params.extend([json_path, value[1:]])
            elif value.startswith("<"):
                if is_numeric:
                    where_parts.append("CAST(json_extract(metadata_json, ?) AS INTEGER) < ?")
                    params.extend([json_path, int(value[1:])])
                else:
                    where_parts.append("json_extract(metadata_json, ?) < ?")
                    params.extend([json_path, value[1:]])
            else:
                # Exact match (try numeric for year/week/quality_score)
                try:
                    numeric_val = int(value)
                    if is_numeric:
                        where_parts.append("CAST(json_extract(metadata_json, ?) AS INTEGER) = ?")
                    else:
                        where_parts.append("json_extract(metadata_json, ?) = ?")
                    params.extend([json_path, numeric_val])
                except ValueError:
                    where_parts.append("json_extract(metadata_json, ?) = ?")
                    params.extend([json_path, value])

        where_clause = " AND ".join(where_parts)
        sql = f"""
            SELECT filename, file_path, metadata_json
            FROM files
            WHERE {where_clause}
            ORDER BY filename
            LIMIT ?
        """
        params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        results = []
        for row in rows:
            meta = json_module.loads(row["metadata_json"]) if row["metadata_json"] else {}
            results.append({
                "filename": row["filename"],
                "file_path": row["file_path"],
                "metadata": meta,
            })
        return results

    def get_ai_metadata_stats(self) -> dict[str, int]:
        """Return count of files grouped by AI metadata status.

        Only counts files where ai_metadata_status is not NULL.

        Returns:
            Dictionary mapping ai_metadata_status -> count.
        """
        rows = self.conn.execute(
            "SELECT ai_metadata_status, COUNT(*) as cnt FROM files "
            "WHERE ai_metadata_status IS NOT NULL "
            "GROUP BY ai_metadata_status"
        ).fetchall()
        return {row["ai_metadata_status"]: row["cnt"] for row in rows}

    def get_files_by_ai_status(self, status: str, limit: int = 50) -> list[dict]:
        """Return files with a specific AI metadata status.

        Joins files with file_metadata_ai (where is_current=1) to include
        the parsed metadata from the AI extraction.

        Args:
            status: AI metadata status to filter by (e.g., 'extracted', 'needs_review').
            limit: Maximum number of results to return.

        Returns:
            List of dicts with file_path, filename, ai_metadata_status,
            ai_confidence_score, and metadata (parsed dict from file_metadata_ai).
        """
        import json as json_module

        rows = self.conn.execute(
            """SELECT f.file_path, f.filename, f.ai_metadata_status,
                      f.ai_confidence_score, m.metadata_json as ai_metadata_json
               FROM files f
               LEFT JOIN file_metadata_ai m
                   ON f.file_path = m.file_path AND m.is_current = 1
               WHERE f.ai_metadata_status = ?
               ORDER BY f.ai_confidence_score DESC
               LIMIT ?""",
            (status, limit),
        ).fetchall()

        results = []
        for row in rows:
            metadata = {}
            if row["ai_metadata_json"]:
                try:
                    metadata = json_module.loads(row["ai_metadata_json"])
                except (json_module.JSONDecodeError, TypeError):
                    pass
            results.append({
                "file_path": row["file_path"],
                "filename": row["filename"],
                "ai_metadata_status": row["ai_metadata_status"],
                "ai_confidence_score": row["ai_confidence_score"],
                "metadata": metadata,
            })
        return results

    def approve_files_by_confidence(self, min_confidence: float) -> int:
        """Bulk-approve files with confidence at or above the threshold.

        Updates ai_metadata_status to 'approved' for files currently
        in 'extracted' or 'needs_review' status with confidence >= threshold.

        Args:
            min_confidence: Minimum confidence score for approval.

        Returns:
            Count of files approved.
        """
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE files SET ai_metadata_status = 'approved' "
                "WHERE ai_metadata_status IN ('extracted', 'needs_review') "
                "AND ai_confidence_score >= ?",
                (min_confidence,),
            )
            return cursor.rowcount

    def set_ai_metadata_status(self, file_path: str, status: str) -> None:
        """Set the AI metadata status for a single file.

        Args:
            file_path: Primary key of the file to update.
            status: New ai_metadata_status value.
        """
        with self.conn:
            self.conn.execute(
                "UPDATE files SET ai_metadata_status = ? WHERE file_path = ?",
                (status, file_path),
            )

    def get_extraction_summary(self) -> dict:
        """Return comprehensive statistics about AI metadata extraction.

        Returns:
            Dict with keys: total_unknown_txt, extracted, approved,
            needs_review, failed, avg_confidence, min_confidence,
            max_confidence.
        """
        # Total unknown TXT files (extraction candidates)
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM files "
            "WHERE filename LIKE '%.txt' "
            "AND json_extract(metadata_json, '$.category') = 'unknown'"
        ).fetchone()
        total_unknown = row["cnt"] if row else 0

        # Counts by AI status
        stats = self.get_ai_metadata_stats()

        # Confidence stats for extracted/approved files
        conf_row = self.conn.execute(
            "SELECT AVG(ai_confidence_score) as avg_conf, "
            "MIN(ai_confidence_score) as min_conf, "
            "MAX(ai_confidence_score) as max_conf "
            "FROM files "
            "WHERE ai_metadata_status IN ('extracted', 'approved', 'needs_review') "
            "AND ai_confidence_score IS NOT NULL"
        ).fetchone()

        return {
            "total_unknown_txt": total_unknown,
            "extracted": stats.get("extracted", 0),
            "approved": stats.get("approved", 0),
            "needs_review": stats.get("needs_review", 0),
            "failed": stats.get("failed_validation", 0) + stats.get("failed_json", 0),
            "pending": stats.get("pending", 0),
            "avg_confidence": round(conf_row["avg_conf"], 2) if conf_row and conf_row["avg_conf"] else 0.0,
            "min_confidence": round(conf_row["min_conf"], 2) if conf_row and conf_row["min_conf"] else 0.0,
            "max_confidence": round(conf_row["max_conf"], 2) if conf_row and conf_row["max_conf"] else 0.0,
        }

    # ---- Passage cache methods (Phase 4) ----

    def upsert_passage(
        self, passage_id: str, file_id: str, content_hash: str, passage_text: str
    ) -> None:
        """Insert a new passage or update last_seen_at if it already exists.

        Uses INSERT OR IGNORE followed by UPDATE for idempotent upsert.

        Args:
            passage_id: Unique passage identifier.
            file_id: File this passage belongs to (references files.file_path).
            content_hash: Hash of the passage text for deduplication.
            passage_text: The actual passage content.
        """
        with self.conn:
            self.conn.execute(
                """INSERT OR IGNORE INTO passages
                   (passage_id, file_id, content_hash, passage_text)
                   VALUES (?, ?, ?, ?)""",
                (passage_id, file_id, content_hash, passage_text),
            )
            self.conn.execute(
                """UPDATE passages
                   SET last_seen_at = strftime('%Y-%m-%dT%H:%M:%f', 'now'),
                       is_stale = 0
                   WHERE passage_id = ?""",
                (passage_id,),
            )

    def mark_stale_passages(self, file_id: str) -> int:
        """Mark all non-stale passages for a file as stale.

        Called when a file is re-processed and previous passages may no
        longer be valid.

        Args:
            file_id: File identifier whose passages should be marked stale.

        Returns:
            Number of passages marked stale.
        """
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE passages SET is_stale = 1 WHERE file_id = ? AND is_stale = 0",
                (file_id,),
            )
            return cursor.rowcount

    # ---- Entity extraction persistence methods (Phase 6.1) ----

    def save_transcript_entities(self, file_path: str, result: object) -> None:
        """Save entity extraction results for a transcript.

        Uses delete-then-insert for idempotent re-extraction.
        Updates files.entity_extraction_status and entity_extraction_version.

        Args:
            file_path: Primary key matching files.file_path.
            result: EntityExtractionResult from the extractor (duck-typed
                    to avoid import cycle -- expects .entities, .status,
                    .extraction_version attributes).
        """
        with self.conn:
            # Clean slate for re-extraction
            self.conn.execute(
                "DELETE FROM transcript_entity WHERE transcript_id = ?",
                (file_path,),
            )
            # Insert each entity
            for entity in result.entities:
                self.conn.execute(
                    """INSERT INTO transcript_entity
                       (transcript_id, person_id, mention_count, first_seen_char,
                        max_confidence, evidence_sample, extraction_version)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        file_path,
                        entity.person_id,
                        entity.mention_count,
                        entity.first_seen_char,
                        entity.max_confidence,
                        entity.evidence_sample,
                        result.extraction_version,
                    ),
                )
            # Update files table status
            self.conn.execute(
                """UPDATE files
                   SET entity_extraction_status = ?,
                       entity_extraction_version = ?
                   WHERE file_path = ?""",
                (result.status, result.extraction_version, file_path),
            )

    def get_entity_stats(self) -> dict:
        """Return entity extraction statistics.

        Returns dict with:
            total_txt: total .txt files (excluding LOCAL_DELETE)
            entities_done: files with entity_extraction_status='entities_done'
            pending: files with entity_extraction_status='pending' or NULL
            errors: files with entity_extraction_status in ('error','blocked_entity_extraction')
            total_mentions: sum of all mention_count in transcript_entity
            unique_persons: count of distinct person_id in transcript_entity
            person_frequency: list of (canonical_name, transcript_count, total_mentions)
                ordered by transcript_count desc
        """
        # Total .txt files
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM files "
            "WHERE filename LIKE '%.txt' AND status != 'LOCAL_DELETE'"
        ).fetchone()
        total_txt = row["cnt"] if row else 0

        # Status counts
        done_row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM files "
            "WHERE entity_extraction_status = 'entities_done' "
            "AND filename LIKE '%.txt' AND status != 'LOCAL_DELETE'"
        ).fetchone()
        entities_done = done_row["cnt"] if done_row else 0

        pending_row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM files "
            "WHERE (entity_extraction_status IS NULL OR entity_extraction_status = 'pending') "
            "AND filename LIKE '%.txt' AND status != 'LOCAL_DELETE'"
        ).fetchone()
        pending = pending_row["cnt"] if pending_row else 0

        error_row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM files "
            "WHERE entity_extraction_status IN ('error', 'blocked_entity_extraction') "
            "AND filename LIKE '%.txt' AND status != 'LOCAL_DELETE'"
        ).fetchone()
        errors = error_row["cnt"] if error_row else 0

        # Aggregate entity stats
        mention_row = self.conn.execute(
            "SELECT COALESCE(SUM(mention_count), 0) as total, "
            "COUNT(DISTINCT person_id) as unique_persons "
            "FROM transcript_entity"
        ).fetchone()
        total_mentions = mention_row["total"] if mention_row else 0
        unique_persons = mention_row["unique_persons"] if mention_row else 0

        # Person frequency: join with person table for canonical name
        freq_rows = self.conn.execute(
            """SELECT p.canonical_name,
                      COUNT(DISTINCT te.transcript_id) as transcript_count,
                      SUM(te.mention_count) as total_mentions
               FROM transcript_entity te
               JOIN person p ON te.person_id = p.person_id
               GROUP BY te.person_id
               ORDER BY transcript_count DESC"""
        ).fetchall()
        person_frequency = [
            (row["canonical_name"], row["transcript_count"], row["total_mentions"])
            for row in freq_rows
        ]

        return {
            "total_txt": total_txt,
            "entities_done": entities_done,
            "pending": pending,
            "errors": errors,
            "total_mentions": total_mentions,
            "unique_persons": unique_persons,
            "person_frequency": person_frequency,
        }

    def get_files_needing_entity_extraction(
        self, mode: str = "pending", limit: int = 500
    ) -> list[dict]:
        """Return files that need entity extraction.

        Args:
            mode: "pending" (default), "backfill", "force", or "upgrade"
                - pending: entity_extraction_status IS NULL or 'pending', .txt files
                - backfill: status='uploaded' AND entity_extraction_status IS NULL/pending
                - force: all .txt files regardless of entity status
                - upgrade: entity_extraction_version != current version
            limit: Max files to return.

        Returns:
            List of dicts with file_path, filename, file_size keys.
        """
        if mode == "pending":
            sql = """SELECT file_path, filename, file_size FROM files
                     WHERE filename LIKE '%.txt'
                       AND (entity_extraction_status IS NULL OR entity_extraction_status = 'pending')
                       AND status != 'LOCAL_DELETE'
                     ORDER BY file_path LIMIT ?"""
        elif mode == "backfill":
            sql = """SELECT file_path, filename, file_size FROM files
                     WHERE filename LIKE '%.txt'
                       AND status = 'uploaded'
                       AND (entity_extraction_status IS NULL OR entity_extraction_status = 'pending')
                     ORDER BY file_path LIMIT ?"""
        elif mode == "force":
            sql = """SELECT file_path, filename, file_size FROM files
                     WHERE filename LIKE '%.txt'
                       AND status != 'LOCAL_DELETE'
                     ORDER BY file_path LIMIT ?"""
        elif mode == "upgrade":
            sql = """SELECT file_path, filename, file_size FROM files
                     WHERE filename LIKE '%.txt'
                       AND entity_extraction_version != '6.1.0'
                       AND entity_extraction_status = 'entities_done'
                       AND status != 'LOCAL_DELETE'
                     ORDER BY file_path LIMIT ?"""
        else:
            raise ValueError(f"Unknown mode: {mode}. Valid: pending, backfill, force, upgrade")

        rows = self.conn.execute(sql, (limit,)).fetchall()
        return [
            {"file_path": row["file_path"], "filename": row["filename"], "file_size": row["file_size"]}
            for row in rows
        ]

    def get_transcripts_by_person(self, person_id: str, limit: int = 50) -> list[dict]:
        """Return transcripts that mention a specific person.

        Returns list of dicts with file_path, filename, mention_count,
        max_confidence, evidence_sample keys, ordered by mention_count DESC.
        """
        rows = self.conn.execute(
            """SELECT f.file_path, f.filename, te.mention_count,
                      te.max_confidence, te.evidence_sample
               FROM transcript_entity te
               JOIN files f ON te.transcript_id = f.file_path
               WHERE te.person_id = ?
               ORDER BY te.mention_count DESC
               LIMIT ?""",
            (person_id, limit),
        ).fetchall()
        return [
            {
                "file_path": row["file_path"],
                "filename": row["filename"],
                "mention_count": row["mention_count"],
                "max_confidence": row["max_confidence"],
                "evidence_sample": row["evidence_sample"],
            }
            for row in rows
        ]

    def get_person_by_name_or_alias(self, query: str) -> str | None:
        """Look up a person_id by canonical name or alias text.

        Case-insensitive. Returns person_id or None.
        Used by CLI to resolve user input like 'Peikoff' to 'leonard-peikoff'.
        """
        # Try canonical name first
        row = self.conn.execute(
            "SELECT person_id FROM person WHERE canonical_name = ? COLLATE NOCASE",
            (query,),
        ).fetchone()
        if row:
            return row["person_id"]

        # Try alias text (non-blocked)
        row = self.conn.execute(
            "SELECT person_id FROM person_alias "
            "WHERE alias_text = ? COLLATE NOCASE AND is_blocked = 0",
            (query,),
        ).fetchone()
        if row:
            return row["person_id"]

        # Try partial match (LIKE) on canonical name
        row = self.conn.execute(
            "SELECT person_id FROM person WHERE canonical_name LIKE ? COLLATE NOCASE",
            (f"%{query}%",),
        ).fetchone()
        if row:
            return row["person_id"]

        return None

    # ---- Sync methods (Phase 5) ----

    def mark_missing(self, file_paths: set[str]) -> None:
        """Set status='missing' and missing_since=now() for the given paths.

        Only marks files that aren't already 'missing' to avoid resetting
        the missing_since timestamp.

        Args:
            file_paths: Set of file paths to mark as missing.
        """
        if not file_paths:
            return
        now = self.conn.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%f', 'now')"
        ).fetchone()[0]
        with self.conn:
            for path in file_paths:
                self.conn.execute(
                    "UPDATE files SET status = 'missing', missing_since = ? "
                    "WHERE file_path = ? AND status != 'missing'",
                    (now, path),
                )

    def get_missing_files(self, min_age_days: int | None = None) -> list[dict]:
        """Return files with status='missing'.

        Args:
            min_age_days: If provided, filter to files where missing_since
                is older than N days.

        Returns:
            List of dicts with file_path, filename, gemini_file_id,
            missing_since keys.
        """
        if min_age_days is not None:
            rows = self.conn.execute(
                """SELECT file_path, filename, gemini_file_id, missing_since
                   FROM files
                   WHERE status = 'missing'
                     AND missing_since <= strftime('%Y-%m-%dT%H:%M:%f', 'now', ?)
                   ORDER BY missing_since""",
                (f"-{min_age_days} days",),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT file_path, filename, gemini_file_id, missing_since
                   FROM files
                   WHERE status = 'missing'
                   ORDER BY missing_since"""
            ).fetchall()
        return [
            {
                "file_path": row["file_path"],
                "filename": row["filename"],
                "gemini_file_id": row["gemini_file_id"],
                "missing_since": row["missing_since"],
            }
            for row in rows
        ]

    def get_orphaned_files(self) -> list[dict]:
        """Return files where orphaned_gemini_file_id IS NOT NULL.

        These are files with old Gemini IDs pending cleanup after
        an upload-first replace operation.

        Returns:
            List of dicts with file_path, orphaned_gemini_file_id keys.
        """
        rows = self.conn.execute(
            """SELECT file_path, orphaned_gemini_file_id
               FROM files
               WHERE orphaned_gemini_file_id IS NOT NULL
               ORDER BY file_path"""
        ).fetchall()
        return [
            {
                "file_path": row["file_path"],
                "orphaned_gemini_file_id": row["orphaned_gemini_file_id"],
            }
            for row in rows
        ]

    def clear_orphan(self, file_path: str) -> None:
        """Set orphaned_gemini_file_id = NULL for the given file.

        Called after successfully cleaning up an orphaned Gemini file.

        Args:
            file_path: Primary key of the file to clear.
        """
        with self.conn:
            self.conn.execute(
                "UPDATE files SET orphaned_gemini_file_id = NULL WHERE file_path = ?",
                (file_path,),
            )

    def set_library_config(self, key: str, value: str) -> None:
        """Store a key-value pair in the library_config table.

        Uses INSERT OR REPLACE for upsert semantics.

        Args:
            key: Configuration key.
            value: Configuration value.
        """
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO library_config (key, value, updated_at) "
                "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%f', 'now'))",
                (key, value),
            )

    def get_library_config(self, key: str) -> str | None:
        """Retrieve a configuration value by key.

        Args:
            key: Configuration key to look up.

        Returns:
            The value string, or None if the key doesn't exist.
        """
        row = self.conn.execute(
            "SELECT value FROM library_config WHERE key = ?",
            (key,),
        ).fetchone()
        return row["value"] if row else None

    def update_file_sync_columns(self, file_path: str, **kwargs: object) -> None:
        """Update arbitrary sync columns on a file record.

        Uses the same pattern as update_file_status but without changing
        the status field. Valid columns: mtime, upload_hash,
        enrichment_version, orphaned_gemini_file_id, missing_since.

        Args:
            file_path: Primary key of the file to update.
            **kwargs: Column=value pairs to set.
        """
        VALID_COLS = {"mtime", "upload_hash", "enrichment_version",
                      "orphaned_gemini_file_id", "missing_since"}
        if not kwargs:
            return
        invalid = set(kwargs.keys()) - VALID_COLS
        if invalid:
            raise ValueError(f"Invalid sync columns: {invalid}. Valid: {VALID_COLS}")

        set_parts = []
        params: list[object] = []
        for col, val in kwargs.items():
            set_parts.append(f"{col} = ?")
            params.append(val)

        params.append(file_path)
        sql = f"UPDATE files SET {', '.join(set_parts)} WHERE file_path = ?"

        with self.conn:
            self.conn.execute(sql, params)

    def get_file_with_sync_data(self, file_path: str) -> dict | None:
        """Return a single file record including sync-relevant columns.

        Used by the sync detector to check current state before deciding
        what action to take.

        Args:
            file_path: Primary key of the file to look up.

        Returns:
            Dict with mtime, content_hash, upload_hash, enrichment_version,
            gemini_file_id, status keys, or None if not found.
        """
        row = self.conn.execute(
            """SELECT mtime, content_hash, upload_hash, enrichment_version,
                      gemini_file_id, status
               FROM files
               WHERE file_path = ?""",
            (file_path,),
        ).fetchone()
        if row is None:
            return None
        return {
            "mtime": row["mtime"],
            "content_hash": row["content_hash"],
            "upload_hash": row["upload_hash"],
            "enrichment_version": row["enrichment_version"],
            "gemini_file_id": row["gemini_file_id"],
            "status": row["status"],
        }

    def get_all_active_files_with_mtime(self) -> dict[str, tuple[str, int, float | None]]:
        """Return all non-deleted files with mtime data.

        Like get_all_active_files but includes mtime for sync change
        detection optimization.

        Returns:
            Dict mapping file_path -> (content_hash, file_size, mtime).
        """
        rows = self.conn.execute(
            "SELECT file_path, content_hash, file_size, mtime FROM files "
            "WHERE status NOT IN (?, ?)",
            (FileStatus.LOCAL_DELETE.value, FileStatus.MISSING.value),
        ).fetchall()
        return {
            row["file_path"]: (row["content_hash"], row["file_size"], row["mtime"])
            for row in rows
        }

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: object) -> None:
        self.close()
