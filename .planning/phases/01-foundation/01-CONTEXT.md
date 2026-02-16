# CONTEXT.md — Phase 1: Foundation

**Generated:** 2026-02-15
**Phase Goal:** Scan entire 1,749-file library offline, extracting rich metadata from every file, with all state persisted to SQLite -- ready for upload
**Synthesis Source:** Multi-provider AI analysis (Gemini Pro, Perplexity Sonar Deep Research)

---

## Overview

Phase 1 establishes the foundation for the entire semantic search system by scanning the philosophical library offline, extracting rich metadata from hierarchical folder structures and filenames, and persisting everything to a SQLite database with Write-Ahead Logging (WAL) mode. This phase has **zero external API dependencies**, enabling offline development and testing against the real 1,749-file library.

The research identified **8 critical gray areas** that require decisions before implementation can proceed. These gray areas span database schema design, metadata extraction logic, file scanning patterns, error handling, and state management. Decisions made in Phase 1 will have cascading effects on Phases 2-5, as the database schema and metadata structure established here become the foundation for all downstream processing.

**Confidence markers:**
- ✅ **Consensus** — Both providers identified this as critical
- ⚠️ **Recommended** — Architectural best practice with strong rationale
- 🔍 **Needs Clarification** — Domain-specific decision requiring stakeholder input

---

## Gray Areas Identified

### ✅ 1. Primary Key Strategy & Handling File Moves (Consensus)

**What needs to be decided:**
Should the database use **file path** or **content hash** as the primary key?

**Why it's ambiguous:**
- FOUN-06 requests "idempotency keys using content hashes" (suggests hash as PK)
- FOUN-04 requires metadata from folder structure (suggests path as PK)
- **Conflict:** A file moved from `/Course/Drafts/Lecture1.txt` to `/Course/Final/Lecture1.txt` has identical content hash but different metadata

**Provider synthesis:**
- **Gemini:** Recommends `file_path` as primary key, `content_hash` as indexed column. This treats file moves as metadata changes requiring re-extraction.
- **Perplexity:** Recommends composite approach with both path and hash tracked separately, enabling detection of both content changes and location changes.

**Proposed implementation decision:**
Use `file_path` (TEXT PRIMARY KEY) with `content_hash` as indexed column (UNIQUE constraint). This approach:
- Detects file moves as new records (correct, since folder metadata changed)
- Prevents duplicate content uploads via hash index
- Enables efficient "find file by path" and "find duplicates by hash" queries

**Open questions:**
- Does Gemini API allow uploading files with identical content from different paths?
- Should duplicate content (same hash, different paths) share one Gemini upload or upload separately?

**Confidence:** ✅ Both providers agreed this is a blocking decision

---

### ✅ 2. Metadata Schema Structure (Columns vs. JSON) (Consensus)

**What needs to be decided:**
Should extracted metadata use **dedicated SQL columns** (rigid but queryable) or **JSON blob** (flexible but harder to query)?

**Why it's ambiguous:**
- Hardcoded columns like `quarter`, `instructor` make schema rigid when patterns evolve
- JSON blobs are flexible but make SQL filtering difficult
- Requirements don't specify which metadata fields need SQL querying

**Provider synthesis:**
- **Gemini:** Recommends hybrid schema - core columns (id, path, hash, status) + JSON metadata blob
- **Perplexity:** Recommends partially denormalized schema with separate `folder_metadata` and `filename_metadata` tables

**Proposed implementation decision:**
**Hybrid schema with strategic normalization:**
- Core table: `files` (file_path, content_hash, status, timestamps, gemini_ids)
- JSON column: `metadata_json` (stores extracted Course, Year, Quarter, Topic, Instructor, etc.)
- Separate table: `metadata_validation_log` (tracks extraction confidence, warnings)

This enables:
- Quick iteration on metadata extraction without schema migrations
- Efficient status queries (`WHERE status = 'PENDING'`)
- Future promotion of high-value fields to columns if querying becomes critical

**Open questions:**
- Which metadata fields will Phase 3 query/filter most frequently?
- Should course, difficulty, or topic be promoted to columns now?

**Confidence:** ✅ Both providers recommend hybrid approach

---

### ✅ 3. "Unknown" Metadata Handling (Consensus)

**What needs to be decided:**
How should the scanner handle files that don't match expected `Course/Year/Quarter/Week` naming patterns?

**Why it's ambiguous:**
- With 1,749 files, some will break conventions (e.g., `ReadMe.txt`, `syllabus_v2.pdf`)
- Should scanner fail, skip, or store with null metadata?

**Provider synthesis:**
- **Gemini:** Recommends permissive fallback - store fields as `null` or `"Unknown"`, don't block DB entry, add `is_fully_parsed` flag
- **Perplexity:** Recommends confidence scoring for extracted fields, storing validation warnings separately

**Proposed implementation decision:**
**Permissive extraction with quality tracking:**
- Always create DB record, even if regex fails
- Store failed extractions as `null` in JSON metadata
- Add `metadata_quality` column (enum: complete, partial, minimal, none)
- Log unparsed patterns to separate `_extraction_failures` table for pattern discovery

Rationale: Better to have file searchable with limited metadata than missing entirely

**Open questions:**
- Should files with zero extracted metadata be flagged for manual review?
- Are there "junk" files (`.DS_Store`, `Thumbs.db`) to explicitly ignore?

**Confidence:** ✅ Both providers recommend graceful degradation

---

### ✅ 4. 48-Hour Expiration Tracking (Consensus)

**What needs to be decided:**
How to model the 48-hour expiration in the database schema before API integration exists?

**Why it's ambiguous:**
- FOUN-07 mentions "prevent 48-hour expiration issues"
- Unclear if tracking file expiration or cache expiration
- Phase 1 is offline, but schema must support Phase 2 upload tracking

**Provider synthesis:**
- **Gemini:** Add `expiration_ts` column (DATETIME), set to `now + 48h` after upload
- **Perplexity:** Track `upload_ts` and compute expiration status dynamically, add `remote_expiration_ts` for explicit tracking

**Proposed implementation decision:**
Add columns to support Phase 2 tracking:
- `upload_timestamp` (DATETIME, null in Phase 1)
- `remote_expiration_ts` (DATETIME, null in Phase 1)
- In Phase 2: Set both during upload, check expiration before querying

**Open questions:**
- Does 48-hour expiration apply to raw uploaded files or vector store cache?
- Should expired status trigger automatic re-upload?

**Confidence:** ✅ Both providers identified this as critical for Phase 2 integration

---

### ⚠️ 5. File Content Type Allow-List (Recommended)

**What needs to be decided:**
Which file extensions should be processed during scanning?

**Why it's ambiguous:**
- "Recursive discovery" could mean scan everything
- Library might contain images, executables, hidden system files
- Hashing non-text files wastes resources

**Provider synthesis:**
- **Gemini:** Strict allow-list: `{'.txt', '.md', '.pdf', '.docx', '.html'}`
- **Perplexity:** Configurable whitelist with minimum file size threshold (1 KB)

**Proposed implementation decision:**
**Configurable allow-list with defaults:**
```python
ALLOWED_EXTENSIONS = {'.txt', '.md', '.pdf', '.epub', '.docx', '.html'}
MIN_FILE_SIZE = 1024  # 1 KB minimum
```
- Skip hidden files (starting with `.`)
- Skip files below minimum size
- Log skipped files for review

**Open questions:**
- What file types actually exist in the library?
- Should image files (scanned manuscripts) be included?

**Confidence:** ⚠️ Architectural best practice (avoid processing non-content files)

---

### ⚠️ 6. Handling "Orphaned" Database Records (Recommended)

**What needs to be decided:**
What happens to DB records when a file is deleted from disk?

**Why it's ambiguous:**
- Scanner finds current files, but deleted files remain in DB as "ghosts"
- Should they be deleted immediately or marked for cleanup?

**Provider synthesis:**
- **Gemini:** Soft delete - mark as `status = 'MISSING'`, preserve `gemini_id` for API cleanup
- **Perplexity:** Separate tracking table for deleted files, enable purge command

**Proposed implementation decision:**
**Soft delete with cleanup workflow:**
1. Scanner compares disk files vs. DB records
2. Missing files marked `status = 'LOCAL_DELETE'`
3. Preserve record until Phase 2 confirms Gemini cleanup
4. Add `purge` command to remove old LOCAL_DELETE records

Rationale: Need `gemini_id` to send delete command to API in Phase 2

**Open questions:**
- Should purge be automatic after successful Gemini deletion or manual?

**Confidence:** ⚠️ Standard pattern for distributed system cleanup

---

### 🔍 7. Metadata Extraction Pattern Specification (Needs Clarification)

**What needs to be decided:**
What are the **exact folder naming conventions** in the library?

**Why it's ambiguous:**
- Requirements mention `Course/Year/Quarter/Week` patterns but don't define them
- Folder names might vary: "PHIL101" vs "History-of-Metaphysics" vs "Kant-Critique"
- Without examples, can't write reliable regex patterns

**Provider synthesis:**
- **Gemini:** No specific recommendation (requires library samples)
- **Perplexity:** Recommends three-tier pattern matching: exact mappings → regex patterns → unparsed storage

**Proposed implementation decision:**
**Cannot finalize until stakeholder provides examples.**

Three-tier approach once patterns known:
1. **Exact mapping config** (JSON file mapping known folder names to metadata)
2. **Regex patterns** for common conventions
3. **Fallback storage** of unparsed folder names for later discovery

**Open questions:**
- ❓ **BLOCKING:** Can you provide 10-20 example file paths from the actual library?
- Are there standardized course codes or conventions already in use?
- Should unmatched patterns trigger warnings or silent degradation?

**Confidence:** 🔍 **DOMAIN-SPECIFIC** - Requires actual library examples

---

### 🔍 8. Symlink Handling Strategy (Needs Clarification)

**What needs to be decided:**
Should symbolic links be followed, ignored, or treated as special cases?

**Why it's ambiguous:**
- Philosophical libraries might use symlinks for cross-referencing
- Following symlinks could create infinite loops
- Ignoring them could miss content

**Provider synthesis:**
- **Gemini:** Not explicitly addressed
- **Perplexity:** Recommends `visited_inodes` tracking with cycle detection, log circular references

**Proposed implementation decision:**
**Follow symlinks with cycle detection:**
- Track `visited_inodes` (device + inode pairs)
- Skip symlinks pointing to already-visited targets
- Log circular references as warnings (don't fail scan)

**Open questions:**
- Are symlinks used intentionally in the library?
- Should symlink resolution use actual file path or symlink path in metadata?

**Confidence:** 🔍 Implementation detail, can use safe default (follow with cycle detection)

---

## Summary: Decision Checklist

Before planning, confirm:

**Tier 1 (Blocking - Must Decide):**
- [ ] ✅ Gray Area 1: Primary key strategy (file_path vs content_hash)
- [ ] ✅ Gray Area 2: Metadata storage (columns vs JSON vs hybrid)
- [ ] ✅ Gray Area 3: Unknown metadata handling (fail vs skip vs null)
- [ ] ✅ Gray Area 4: 48-hour expiration tracking schema
- [ ] 🔍 Gray Area 7: **Exact folder naming patterns (NEED EXAMPLES FROM LIBRARY)**

**Tier 2 (Important - Should Decide):**
- [ ] ⚠️ Gray Area 5: File type allow-list
- [ ] ⚠️ Gray Area 6: Orphaned record handling

**Tier 3 (Implementation Details):**
- [ ] 🔍 Gray Area 8: Symlink handling

---

## Recommended SQLite Schema (Phase 1)

Based on synthesis, here's the proposed schema:

```sql
-- Core files table
CREATE TABLE files (
    file_path TEXT PRIMARY KEY,           -- Absolute path
    content_hash BLOB NOT NULL,           -- SHA-256 binary
    filename TEXT NOT NULL,
    file_size INTEGER NOT NULL,

    -- Metadata (JSON blob for flexibility)
    metadata_json TEXT,                   -- {course, year, quarter, week, topic, instructor, difficulty}
    metadata_quality TEXT DEFAULT 'unknown', -- complete|partial|minimal|none

    -- State management
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|uploaded|failed|missing
    error_message TEXT,

    -- API integration (placeholders for Phase 2)
    gemini_file_uri TEXT,
    gemini_file_id TEXT,
    upload_timestamp DATETIME,
    remote_expiration_ts DATETIME,
    embedding_model_version TEXT,        -- e.g., "models/embedding-001"

    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX idx_content_hash ON files(content_hash);
CREATE INDEX idx_status ON files(status);
CREATE INDEX idx_file_size ON files(file_size);
CREATE INDEX idx_metadata_quality ON files(metadata_quality);

-- Processing log for audit trail
CREATE TABLE _processing_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    error_details TEXT,
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);

-- Extraction failures for pattern discovery
CREATE TABLE _extraction_failures (
    failure_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    unparsed_folder_name TEXT,
    unparsed_filename TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);

-- WAL mode configuration
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -10000;  -- 10 MB cache
PRAGMA foreign_keys = ON;
PRAGMA temp_store = MEMORY;
```

---

## Next Steps

**Provider availability:**
- ✅ Gemini Pro (responded comprehensively)
- ✅ Perplexity Deep Research (responded comprehensively)
- ❌ OpenAI gpt-5.2 (connection issue during synthesis)

**Files created:**
- `.planning/phases/01-foundation/01-CONTEXT.md` (this file)
- `.planning/phases/01-foundation/CLARIFICATIONS-NEEDED.md` (stakeholder questions)
- `.planning/phases/01-foundation/CLARIFICATIONS-ANSWERED.md` (YOLO mode - auto-generated)

**YOLO Mode Active:**
Clarifications have been auto-answered using balanced strategy (consensus options preferred). Review CLARIFICATIONS-ANSWERED.md before proceeding to planning.

**Next command:**
`/gsd:plan-phase 1` to create detailed execution plan

---

*Multi-provider synthesis by: Gemini Pro, Perplexity Sonar Deep Research*
*Generated: 2026-02-15*
*YOLO Mode: Auto-generated answers available*
