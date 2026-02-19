# Database Schema

SQLite database at `data/library.db`. Current version: **V8**.

WAL mode enabled for read concurrency. Foreign keys enforced.

---

## Schema Migration History

| Version | Added | Migration SQL |
|---------|-------|--------------|
| V1 | Initial schema | `SCHEMA_SQL` in database.py |
| V2 | upload_operations, upload_batches, upload_locks | Included in SCHEMA_SQL |
| V3 | `ai_metadata_status`, `ai_confidence_score` columns on files; `file_metadata_ai`, `file_primary_topics`, `wave1_results` tables | `MIGRATION_V3_SQL` |
| V4 | `entity_extraction_version`, `entity_extraction_status` on files; `person`, `person_alias`, `transcript_entity` tables + seed data | `MIGRATION_V4_SQL` |
| V5 | `upload_attempt_count`, `last_upload_hash` on files | Inline ALTER TABLE in V5 block |
| V6 | `passages`, `sessions`, `session_events` tables | `MIGRATION_V6_SQL` |
| V7 | `mtime`, `orphaned_gemini_file_id`, `missing_since`, `upload_hash`, `enrichment_version` columns on `files`; expanded `status` CHECK constraint; `library_config` table | `MIGRATION_V7_SQL` |
| V8 | `session_events` table rebuild to add `'bookmark'` to `event_type` CHECK constraint | `MIGRATION_V8_SQL` |

Migration strategy: `PRAGMA user_version` tracks current version. Each block uses `ALTER TABLE ADD COLUMN` with try/except (SQLite lacks `IF NOT EXISTS` for columns) and `CREATE TABLE IF NOT EXISTS` for new tables. **Exception:** V7 uses a full table rebuild (`CREATE files_v7` → `INSERT ... SELECT` → `DROP files` → `ALTER TABLE ... RENAME`) because SQLite cannot modify an existing CHECK constraint in-place.

---

## Core Table: `files`

The primary table tracking every library file.

```sql
CREATE TABLE files (
    file_path           TEXT PRIMARY KEY,          -- Relative path from library root
    content_hash        TEXT NOT NULL,             -- SHA-256 hex digest
    filename            TEXT NOT NULL,             -- Basename only
    file_size           INTEGER NOT NULL,          -- Bytes

    -- Phase 1: Metadata
    metadata_json       TEXT,                      -- JSON blob (course, year, difficulty, etc.)
    metadata_quality    TEXT DEFAULT 'unknown'
        CHECK(metadata_quality IN
              ('complete','partial','minimal','none','unknown')),

    -- Phase 1/2: Upload state
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN
              ('pending','uploading','uploaded','failed','skipped','LOCAL_DELETE',
               'missing','error')),
    error_message       TEXT,

    -- Phase 2: Gemini integration
    gemini_file_uri     TEXT,                      -- Full resource URI
    gemini_file_id      TEXT,                      -- Short file ID (e.g., "e0x3xq9wtglq")
    upload_timestamp    TEXT,
    remote_expiration_ts TEXT,                     -- Gemini 48hr TTL expiry
    embedding_model_version TEXT,

    -- Phase 3 (V3): AI metadata state
    ai_metadata_status  TEXT DEFAULT 'pending',   -- pending/extracted/approved/needs_review/failed_*
    ai_confidence_score REAL,                      -- 0.0-1.0 composite confidence

    -- Phase 6.1 (V4): Entity extraction state
    entity_extraction_version TEXT,
    entity_extraction_status  TEXT DEFAULT 'pending',

    -- Phase 6.2 (V5): Idempotent enriched upload
    upload_attempt_count INTEGER DEFAULT 0,
    last_upload_hash    TEXT,                      -- SHA-256 of (p1_meta+ai_meta+entities+content_hash)

    -- Phase 5 (V7): Incremental sync
    mtime               REAL,                      -- Filesystem modification timestamp (os.stat().st_mtime)
    orphaned_gemini_file_id TEXT,                  -- Old Gemini file ID pending store cleanup after upload-first replacement
    missing_since       TEXT,                      -- ISO 8601 timestamp when file first detected absent from disk
    upload_hash         TEXT,                      -- SHA-256 of enriched bytes actually uploaded to Gemini
    enrichment_version  TEXT,                      -- Short hash (8 hex chars) of enrichment config version

    -- Timestamps
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
```

**Indexes:**
- `idx_content_hash` on `content_hash` (NOT UNIQUE — same content allowed at different paths)
- `idx_status` on `status`
- `idx_metadata_quality` on `metadata_quality`

**Triggers:**
- `update_files_timestamp`: auto-updates `updated_at` on any change
- `log_status_change`: auto-inserts to `_processing_log` on status transitions

**`metadata_json` structure example:**
```json
{
  "category": "course",
  "course": "OPAR",
  "year": 2022,
  "quarter": "Q1",
  "week": 3,
  "topic": "The Nature of Reason",
  "instructor": "Leonard Peikoff",
  "difficulty": "advanced",
  "quality_score": 85
}
```

**`status` values (Phase 5 additions):**
- `missing`: file deleted from disk; Gemini store entry preserved until `--prune-missing` runs. `missing_since` records when first detected.
- `error`: sync-specific error (e.g., disk read failure during hash computation)

**`ai_metadata_status` values:**
- `pending`: not yet extracted
- `extracted`: extracted, confidence ≥ 0.85
- `needs_review`: extracted but confidence < 0.85
- `approved`: manually or auto-approved
- `failed_validation`: schema validation failed
- `failed_json`: JSON parse error

---

## Audit Tables

### `_processing_log`

Auto-populated by trigger on every status transition.

```sql
CREATE TABLE _processing_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT NOT NULL,
    old_status  TEXT,
    new_status  TEXT,
    timestamp   TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    error_details TEXT,
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);
```

### `_extraction_failures`

Records files where folder/filename patterns failed to parse.

```sql
CREATE TABLE _extraction_failures (
    failure_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path           TEXT NOT NULL,
    unparsed_folder_name TEXT,
    unparsed_filename   TEXT,
    timestamp           TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);
```

### `_skipped_files`

Records files skipped during scanning (e.g., non-.txt files).

```sql
CREATE TABLE _skipped_files (
    skip_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT NOT NULL,
    reason      TEXT NOT NULL,
    file_size   INTEGER,
    timestamp   TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
```

---

## Upload Tables (Phase 2)

### `upload_operations`

Tracks individual file upload attempts (crash recovery anchor).

```sql
CREATE TABLE upload_operations (
    operation_name  TEXT PRIMARY KEY,              -- Gemini operation name
    file_path       TEXT NOT NULL,
    gemini_file_name TEXT,
    operation_state TEXT NOT NULL DEFAULT 'pending'
        CHECK(operation_state IN
              ('pending','in_progress','succeeded','failed','timeout')),
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    last_polled_at  TEXT,
    completed_at    TEXT,
    error_message   TEXT,
    retry_count     INTEGER DEFAULT 0,
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);
```

**Indexes:** `idx_upload_ops_state`, `idx_upload_ops_file`

### `upload_batches`

Logical batch tracking.

```sql
CREATE TABLE upload_batches (
    batch_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_number    INTEGER NOT NULL,
    file_count      INTEGER NOT NULL,
    succeeded_count INTEGER DEFAULT 0,
    failed_count    INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'pending'
        CHECK(status IN ('pending','in_progress','completed','failed')),
    started_at      TEXT,
    completed_at    TEXT
);
```

### `upload_locks`

Single-writer lock (max one row enforced by CHECK constraint).

```sql
CREATE TABLE upload_locks (
    lock_id     INTEGER PRIMARY KEY CHECK(lock_id = 1),
    instance_id TEXT NOT NULL,
    acquired_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    last_heartbeat TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
```

---

## AI Metadata Tables (Phase 6, Migration V3)

### `file_metadata_ai`

Versioned AI metadata storage. Multiple rows per file, one marked `is_current=1`.

```sql
CREATE TABLE file_metadata_ai (
    metadata_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path               TEXT NOT NULL,
    metadata_json           TEXT NOT NULL,    -- Full 4-tier metadata JSON
    model                   TEXT NOT NULL,    -- e.g., "mistral-large-latest"
    model_version           TEXT,
    prompt_version          TEXT NOT NULL,    -- e.g., "v1.2-minimalist"
    extraction_config_hash  TEXT,
    is_current              BOOLEAN DEFAULT 1,
    created_at              TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);
```

**Index:** `idx_metadata_ai_current` on `(file_path, is_current)`

**`metadata_json` structure:**
```json
{
  "category": "course",
  "difficulty": "intermediate",
  "primary_topics": ["epistemology", "concept_formation", "objectivity", "reason", "volition", "consciousness", "existence", "identity"],
  "topic_aspects": ["measurement omission", "unit economy", "abstraction process", "..."],
  "semantic_description": {
    "abstract": "An introduction to Objectivist epistemology...",
    "pedagogical_context": "This lecture is part of...",
    "key_claims": ["Concepts are formed by...", "..."]
  }
}
```

### `file_primary_topics`

Fast filtering table for controlled vocabulary topics (denormalized from `file_metadata_ai`).

```sql
CREATE TABLE file_primary_topics (
    file_path   TEXT NOT NULL,
    topic_tag   TEXT NOT NULL,
    PRIMARY KEY (file_path, topic_tag),
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);
```

**Index:** `idx_primary_topic_tag` on `topic_tag`

### `wave1_results`

Results from Wave 1 competitive strategy evaluation (3 strategies × 20 files).

```sql
CREATE TABLE wave1_results (
    result_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path           TEXT NOT NULL,
    strategy            TEXT NOT NULL,        -- minimalist/teacher/reasoner
    metadata_json       TEXT NOT NULL,
    raw_response        TEXT,
    token_count         INTEGER,
    latency_ms          INTEGER,
    confidence_score    REAL,
    human_edit_distance REAL,
    created_at          TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);
```

---

## Entity Tables (Phase 6.1, Migration V4)

### `person`

Canonical person registry (seeded with 15 persons at migration time).

```sql
CREATE TABLE person (
    person_id       TEXT PRIMARY KEY,          -- e.g., "ayn-rand", "leonard-peikoff"
    canonical_name  TEXT NOT NULL UNIQUE,      -- e.g., "Ayn Rand"
    type            TEXT NOT NULL
        CHECK(type IN ('philosopher','ari_instructor')),
    notes           TEXT,
    created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
```

### `person_alias`

Alias lookup table for fuzzy matching.

```sql
CREATE TABLE person_alias (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alias_text  TEXT NOT NULL,
    person_id   TEXT NOT NULL,
    alias_type  TEXT
        CHECK(alias_type IN
              ('nickname','misspelling','partial','initials','title_variant','full_name')),
    is_blocked  BOOLEAN DEFAULT 0,             -- 1 = ambiguous, requires full name
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (person_id) REFERENCES person(person_id)
);
```

**Index:** `idx_person_alias_text` on `alias_text COLLATE NOCASE`

Blocked aliases (e.g., "Smith", "Ben", "Aaron") prevent false positives from common first names.

### `transcript_entity`

One row per (transcript, person) pair — summary of entity mentions.

```sql
CREATE TABLE transcript_entity (
    transcript_id       TEXT NOT NULL,         -- = files.file_path
    person_id           TEXT NOT NULL,
    mention_count       INTEGER NOT NULL CHECK(mention_count >= 1),
    first_seen_char     INTEGER,               -- Char offset of first mention
    max_confidence      REAL
        CHECK(max_confidence >= 0.0 AND max_confidence <= 1.0),
    evidence_sample     TEXT,                  -- Short text snippet
    extraction_version  TEXT NOT NULL,
    created_at          TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    PRIMARY KEY (transcript_id, person_id),
    FOREIGN KEY (person_id) REFERENCES person(person_id)
);
```

**Index:** `idx_transcript_entity_person` on `person_id`

**Idempotency:** `save_transcript_entities()` uses delete-then-insert for clean re-extraction.

---

## Phase 4 Tables (Migration V6)

### `passages`

Cache of passage text from Gemini grounding results. Provides citation stability.

```sql
CREATE TABLE passages (
    passage_id  TEXT PRIMARY KEY,              -- UUID5 of (file_id + content_hash)
    file_id     TEXT NOT NULL,                 -- Gemini file ID or file_path
    content_hash TEXT,                         -- SHA-256 of passage text
    passage_text TEXT NOT NULL,
    source      TEXT DEFAULT 'gemini_grounding',
    is_stale    BOOLEAN DEFAULT 0,
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    last_seen_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
```

**Indexes:** `idx_passages_file` on `file_id`, `idx_passages_hash` on `content_hash`

Upsert uses `INSERT OR IGNORE` + `UPDATE` pattern for clarity.

### `sessions`

Research session records.

```sql
CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,              -- UUID
    name        TEXT,                          -- User-provided or auto-generated
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
```

### `session_events`

Append-only event log. No UPDATE or DELETE operations ever.

```sql
CREATE TABLE session_events (
    id          TEXT PRIMARY KEY,              -- UUID
    session_id  TEXT NOT NULL,
    event_type  TEXT NOT NULL
        CHECK(event_type IN ('search','view','synthesize','note','error','bookmark')),
    payload_json TEXT NOT NULL,               -- Event-specific data
    created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
```

**Index:** `idx_session_events_session` on `session_id`

**`payload_json` structures by event type:**

| Event Type | Payload Fields |
|------------|---------------|
| `search` | `query`, `expanded_query`, `result_count`, `doc_ids` (list) |
| `synthesize` | `query`, `claim_count` |
| `view` | filename |
| `note` | `text` |
| `error` | `message` |
| `bookmark` | `file_path`, `action` (`"added"` or `"removed"`) |

---

## Sync Config Table (Phase 5, Migration V7)

### `library_config`

Key-value store for sync settings. Persists configuration across sync runs.

```sql
CREATE TABLE library_config (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
```

**Current keys:**

| Key | Value | Description |
|-----|-------|-------------|
| `gemini_store_display_name` | e.g., `objectivism-library-test` | Store display name recorded on first sync. Subsequent syncs abort if this changes. |

Managed via `db.set_library_config(key, value)` / `db.get_library_config(key)`.

---

## Key SQL Patterns

### UPSERT (used for file records)

```sql
INSERT INTO files(file_path, content_hash, ...) VALUES (?, ?, ...)
ON CONFLICT(file_path) DO UPDATE SET
    content_hash = excluded.content_hash,
    status = CASE
        WHEN files.content_hash != excluded.content_hash THEN 'pending'
        ELSE files.status
    END
```

Status is reset to `pending` ONLY when content_hash changes (hash-based change detection).

### Numeric Filtering (requires CAST)

```sql
-- Year range query (must use CAST for comparison operators)
WHERE CAST(json_extract(metadata_json, '$.year') AS INTEGER) >= 2020
```

Without CAST, SQLite performs string comparison which breaks `>=`, `<=`, `>`, `<`.

### Gemini ID Normalization

Database stores full resource names: `"files/e0x3xq9wtglq"`
Gemini API returns short IDs: `"e0x3xq9wtglq"`
Normalization: add `"files/"` prefix when looking up by Gemini ID.

---

_Last updated: Phase 7 — Schema V8 (session_events 'bookmark' event type)_
