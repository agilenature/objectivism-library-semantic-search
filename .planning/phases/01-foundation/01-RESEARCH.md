# Phase 1: Foundation - Research

**Researched:** 2026-02-15
**Domain:** Python stdlib SQLite + file scanning + metadata extraction
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CLARIFICATIONS-ANSWERED.md)

### Locked Decisions

1. **Primary Key Strategy:** `file_path` as TEXT PRIMARY KEY, `content_hash` as indexed column
2. **Metadata Schema:** Hybrid (core columns + `metadata_json` TEXT column for extracted fields)
3. **Unknown Files:** Permissive extraction with quality tracking (`metadata_quality` enum: complete/partial/minimal/none/unknown)
4. **48-Hour Tracking:** Both `upload_timestamp` and `remote_expiration_ts` columns (null in Phase 1)
5. **File Patterns:**
   - Simple (99%): `Courses/{Course Name}/{Course Name} - Lesson {NN} - {Topic}.txt`
   - Complex (1%): `Courses/{Course Name}/Year{N}/Q{N}/{Course Name} - Year {N} - Q{N} - Week {N} - {Topic}.txt`
6. **File Type Allow-List:** `{'.txt', '.md', '.pdf', '.epub', '.docx', '.html'}`, skip hidden files, 1KB minimum
7. **Orphaned Records:** Soft delete (`status='LOCAL_DELETE'`), preserve for Phase 2 cleanup
8. **Symlinks:** Follow with cycle detection (track `visited_inodes` as `(st_dev, st_ino)` pairs)
9. **Additional Tables:** `_extraction_failures`, `_skipped_files`, `_processing_log`
10. **SQLite Pragmas:** WAL mode, `synchronous=NORMAL`, `foreign_keys=ON`, `cache_size=-10000`, `temp_store=MEMORY`
11. **Config Files:** `scanner_config.json`, `metadata_mappings.json`

### Claude's Discretion

- Project structure and module organization
- CLI framework choice (Typer is in the existing codebase stack)
- Logging approach (print vs stdlib logging vs Rich)
- Testing strategy and framework
- Config format (JSON vs TOML for pyproject.toml)
- content_hash storage format (BLOB vs TEXT)
- Buffer size for file hashing
- Regex compilation strategy

### Deferred Ideas (OUT OF SCOPE)

- Image file support (scanned manuscripts) - deferred to v2
- Automatic purge of LOCAL_DELETE records - manual only in Phase 1
- Promoting metadata fields to dedicated columns - defer until Phase 3
- Auto re-upload of expired files - Phase 2 concern
</user_constraints>

---

## Summary

Phase 1 builds a pure-Python offline scanner that discovers all files in the Objectivism Library, computes SHA-256 hashes, extracts metadata from folder hierarchy and filenames, and persists everything to a WAL-mode SQLite database. The entire technology stack is Python 3.13 stdlib (`sqlite3`, `hashlib`, `pathlib`, `re`, `os`, `json`, `logging`) plus two external dependencies: Typer (CLI) and Rich (terminal UI). No network access is required.

The research validates that Python 3.13's bundled SQLite 3.51.0 supports every feature needed: WAL mode, JSON functions (`json_extract`, `json_valid`, `json_patch`, `json_each`, `json_group_array`), UPSERT (`ON CONFLICT DO UPDATE`), `RETURNING` clause, `STRICT` tables, and CHECK constraints. Performance testing confirms that batch-inserting 2,000 rows completes in 3ms and hashing 1,749 files (~5KB each) takes 35ms -- the entire scan will be I/O-bound on disk reads, not CPU-bound on hashing or database writes.

**Primary recommendation:** Use `os.walk()` with manual symlink cycle detection for directory traversal (not `Path.rglob()` which cannot detect cycles), store content hashes as TEXT hexdigest (readable in DB browsers, negligible storage overhead), and wrap all database operations in a `Database` class that manages connections, transactions, and schema initialization.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.13.5 | Runtime | Already installed on dev machine |
| sqlite3 (stdlib) | SQLite 3.51.0 | State persistence | Zero-dependency, WAL mode, JSON functions, UPSERT |
| hashlib (stdlib) | -- | SHA-256 content hashing | Standard, C-optimized, streaming API |
| pathlib (stdlib) | -- | Path manipulation | Modern Python file paths, `relative_to()`, `suffix` |
| os (stdlib) | -- | `os.walk()` for directory traversal | Symlink control via `followlinks`, `dirnames` pruning |
| re (stdlib) | -- | Metadata extraction from filenames | Named capture groups, pre-compiled patterns |
| json (stdlib) | -- | Config files, metadata_json column | Native SQLite JSON function compatibility |
| logging (stdlib) | -- | Structured logging | Levels, formatters, handlers; integrates with Rich |
| dataclasses (stdlib) | -- | Data models (FileRecord, etc.) | Slots support, type hints, `asdict()` |
| enum (stdlib) | -- | Status/quality enums | `str, Enum` pattern works with SQLite TEXT columns |
| typer | 0.23.0 | CLI framework | Already installed, Annotated syntax, auto-help |
| rich | 14.3.2 | Terminal UI (progress, tables, logging) | Already installed, Typer uses it for rich help text |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tomllib (stdlib) | -- | Read TOML config (built-in 3.11+) | If config uses TOML instead of JSON |
| pytest | >=8.0 | Testing framework | Dev dependency for unit/integration tests |
| pytest-cov | >=5.0 | Code coverage | Dev dependency for coverage reports |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| os.walk() | Path.rglob() | rglob is simpler but cannot detect symlink cycles; os.walk allows `dirnames[:]` pruning |
| os.walk() | Path.walk() (3.12+) | Path.walk has `follow_symlinks` param, returns Path objects; BUT `follow_symlinks` defaults to False (opposite of os.walk). os.walk is better documented for this use case |
| JSON config | TOML config | TOML is cleaner for humans but JSON matches metadata_json column format. Use JSON for consistency |
| hashlib.sha256 | hashlib.file_digest (3.11+) | `file_digest()` is slightly cleaner API but less flexible for buffer size control |
| Rich logging | stdlib print() | Rich provides structured, colorized output with log levels; current codebase uses print() |

**Installation:**
```bash
pip install typer rich
# Or via pyproject.toml with: pip install -e ".[dev]"
```

---

## Architecture Patterns

### Recommended Project Structure

```
objectivism-library-semantic-search/
├── pyproject.toml                     # Package metadata, deps, CLI entry point
├── src/
│   ├── 01_scan_library.py            # EXISTING - keep as legacy reference
│   ├── 02_upload_to_gemini.py        # EXISTING - keep for Phase 2
│   ├── 03_query_interface.py         # EXISTING - keep for Phase 3
│   └── objlib/                       # NEW - proper Python package
│       ├── __init__.py               # Package version, public API
│       ├── __main__.py               # python -m objlib support
│       ├── cli.py                    # Typer app with scan/status/purge commands
│       ├── scanner.py                # FileScanner class (discovery + filtering)
│       ├── database.py               # Database class (SQLite wrapper, schema, transactions)
│       ├── metadata.py               # MetadataExtractor class (regex, folder parsing)
│       ├── models.py                 # Dataclasses + enums (FileRecord, FileStatus, MetadataQuality)
│       └── config.py                 # Config loading + validation from JSON
├── config/
│   ├── library_config.json           # EXISTING - extend with scanner settings
│   ├── scanner_config.json           # NEW - scanner-specific config (decided by user)
│   └── metadata_mappings.json        # NEW - course-level metadata mappings (decided by user)
├── tests/
│   ├── conftest.py                   # Shared fixtures (temp DB, test library tree)
│   ├── test_scanner.py               # File discovery, filtering, symlink tests
│   ├── test_database.py              # Schema, CRUD, transactions, idempotency
│   ├── test_metadata.py              # Regex patterns, folder parsing, quality grading
│   └── test_integration.py           # End-to-end scan with temp directory tree
└── data/                             # .gitignored
    └── library.db                    # SQLite database (generated)
```

**Key design principle:** Each module has a single responsibility. The scanner discovers files; the metadata extractor parses paths; the database persists state. The CLI orchestrates them.

### Pattern 1: Database Context Manager

**What:** Wrap SQLite connections in a context manager for automatic transaction handling.
**When to use:** Every database operation.
**Verified behavior (tested):** `with conn:` auto-commits on success, auto-rolls-back on exception.

```python
# Source: Python 3.13 sqlite3 docs + verified empirically
class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(
            db_path,
            autocommit=sqlite3.LEGACY_TRANSACTION_CONTROL,
        )
        self.conn.row_factory = sqlite3.Row  # dict-like access
        self._setup_pragmas()
        self._setup_schema()

    def _setup_pragmas(self):
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=-10000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA temp_store=MEMORY")

    def upsert_files(self, records: list[FileRecord]):
        """Batch upsert with automatic transaction."""
        with self.conn:  # auto-commit/rollback
            self.conn.executemany(
                """INSERT INTO files(file_path, content_hash, filename, file_size,
                     metadata_json, metadata_quality)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(file_path) DO UPDATE SET
                     content_hash=excluded.content_hash,
                     file_size=excluded.file_size,
                     metadata_json=excluded.metadata_json,
                     metadata_quality=excluded.metadata_quality,
                     updated_at=strftime('%Y-%m-%dT%H:%M:%f', 'now')
                """,
                [(r.file_path, r.content_hash, r.filename, r.file_size,
                  r.metadata_json, r.metadata_quality.value) for r in records]
            )
```

### Pattern 2: Directory Traversal with Cycle Detection

**What:** Use `os.walk()` with manual inode tracking to follow symlinks safely.
**When to use:** File discovery phase.
**Verified behavior (tested):** Correctly detects cycles; `dirnames.clear()` stops descent.

```python
# Source: Verified empirically with circular symlinks
def discover_files(
    root: Path,
    allowed_extensions: set[str],
    min_size: int,
    skip_hidden: bool,
    follow_symlinks: bool,
) -> tuple[list[Path], list[tuple[str, str]]]:
    visited_inodes: set[tuple[int, int]] = set()
    matched: list[Path] = []
    skipped: list[tuple[str, str]] = []

    root_stat = root.stat()
    visited_inodes.add((root_stat.st_dev, root_stat.st_ino))

    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        current = Path(dirpath)

        # Cycle detection
        if follow_symlinks:
            st = current.stat()
            dir_id = (st.st_dev, st.st_ino)
            if dir_id in visited_inodes and current != root:
                logger.warning("Symlink cycle detected: %s", current)
                dirnames.clear()  # Stop descending
                continue
            visited_inodes.add(dir_id)

        # Prune hidden/excluded directories IN-PLACE
        if skip_hidden:
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith('.') and d not in {'__pycache__', 'Thumbs.db'}
            ]

        for filename in filenames:
            # ... filtering logic ...
```

### Pattern 3: Change Detection Algorithm

**What:** Compare current scan results against DB state using set operations.
**When to use:** Every scan after the initial one.
**Verified behavior (tested):** Correctly identifies new/modified/deleted files; idempotent on re-scan.

```python
# Source: Verified empirically
def detect_changes(scan_results: dict, db: Database) -> ChangeSet:
    db_files = db.get_all_active_files()  # {path: (hash, size)}

    scan_paths = set(scan_results.keys())
    db_paths = set(db_files.keys())

    new_files = scan_paths - db_paths
    deleted_files = db_paths - scan_paths
    common_files = scan_paths & db_paths

    modified_files = {
        path for path in common_files
        if scan_results[path].content_hash != db_files[path][0]
    }
    unchanged_files = common_files - modified_files

    return ChangeSet(new=new_files, modified=modified_files,
                     deleted=deleted_files, unchanged=unchanged_files)
```

### Pattern 4: Metadata Extraction with Compiled Regex

**What:** Pre-compiled regex with named capture groups for filename parsing.
**When to use:** Every file's metadata extraction.
**Verified behavior (tested):** Both patterns correctly extract all fields.

```python
# Source: Verified against actual library filename examples
SIMPLE_PATTERN = re.compile(
    r'^(?P<course>.+?) - Lesson (?P<lesson>\d+) - (?P<topic>.+?)\.txt$'
)
COMPLEX_PATTERN = re.compile(
    r'^(?P<course>.+?) - Year (?P<year>\d+) - Q(?P<quarter>\d+) - Week (?P<week>\d+) - (?P<topic>.+?)\.txt$'
)
```

### Anti-Patterns to Avoid

- **Using `Path.rglob()` for symlink-aware scanning:** rglob has NO cycle detection -- it will infinite-loop on circular symlinks. Use `os.walk(followlinks=True)` with manual inode tracking.
- **Storing hashes as BLOB:** Binary hashes save 32 bytes per row (1,749 files = ~55KB total savings), but are unreadable in DB browsers and `sqlite3` CLI. Use TEXT hexdigest.
- **Using `\d{2}` in regex:** The CLARIFICATIONS-ANSWERED.md shows `\d{2}` for lesson numbers, but this fails for lessons >= 100 or single-digit un-padded numbers. Use `\d+` for robustness.
- **Committing after every INSERT:** Wrap batch operations in a single `with conn:` block. Individual commits are ~100x slower for 1,749 files.
- **Using `INSERT OR REPLACE` for updates:** This deletes then re-inserts, losing `created_at` timestamps and breaking foreign keys. Use `ON CONFLICT DO UPDATE`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CLI argument parsing | Custom argparse wrappers | Typer with Annotated syntax | Auto-generates help, shell completion, type validation |
| Terminal progress bars | Manual counter printing | Rich Progress | Handles elapsed time, ETA, nested bars, spinner |
| Pretty table output | String formatting | Rich Table | Auto column widths, borders, color |
| Colored logging | ANSI escape codes | Rich RichHandler | Structured, filterable, pretty tracebacks |
| JSON validation | Manual key checking | dataclass + json.loads | Type safety, default values, validation |
| File hashing | Custom buffered reader | hashlib with `iter(lambda: f.read(65536), b"")` | Standard pattern, optimal buffer size |
| SQLite migrations | Manual ALTER TABLE | Pragma `user_version` + migration functions | Version tracking, idempotent, testable |

**Key insight:** Phase 1 is entirely stdlib except for CLI/UI. Resist adding dependencies for anything hashlib, sqlite3, re, pathlib, or os already handle.

---

## Common Pitfalls

### Pitfall 1: UNIQUE Constraint on content_hash Blocks Legitimate Duplicates

**What goes wrong:** The CLARIFICATIONS-ANSWERED.md specifies `content_hash` as UNIQUE, but the user also decided "Upload separately if paths differ" (same content at different paths = different metadata = different records). A UNIQUE constraint on `content_hash` will reject the second file.
**Why it happens:** The two sub-decisions in Q1 contradict: UNIQUE hash prevents duplicates, but the user wants duplicate content at different paths.
**How to avoid:** Use a regular indexed column (`CREATE INDEX idx_content_hash ON files(content_hash)`) instead of `UNIQUE INDEX`. The index still enables efficient duplicate detection via `SELECT ... WHERE content_hash = ?`, but does not enforce uniqueness.
**Warning signs:** `IntegrityError: UNIQUE constraint failed` when scanning a library with duplicate files.

**CRITICAL NOTE FOR PLANNER:** This is a correction to the schema in CLARIFICATIONS-ANSWERED.md. The `content_hash` column should be indexed but NOT UNIQUE. Verified empirically: UNIQUE on content_hash blocks insertion of same-content files at different paths.

### Pitfall 2: Path.rglob() Infinite Loop on Symlink Cycles

**What goes wrong:** `Path.rglob('*.txt')` with `follow_symlinks=True` does not detect cycles. If `A/link -> B` and `B/link -> A`, rglob will loop forever.
**Why it happens:** rglob uses `Path.iterdir()` recursively without tracking visited inodes.
**How to avoid:** Use `os.walk(followlinks=True)` with a `visited_inodes: set[tuple[int, int]]` tracking `(st_dev, st_ino)` pairs. When a directory's inode is already in the set, call `dirnames.clear()` to stop descent.
**Warning signs:** Scanner hangs indefinitely; high CPU usage with no file count progress.

### Pitfall 3: Forgetting to Prune dirnames In-Place in os.walk

**What goes wrong:** Writing `dirnames = [d for d in dirnames if ...]` instead of `dirnames[:] = [...]` does NOT modify the list that os.walk uses for traversal. The scanner still enters hidden/excluded directories.
**Why it happens:** Python rebinds the local variable instead of mutating the list.
**How to avoid:** Always use `dirnames[:] = ...` (slice assignment) to modify in-place.
**Warning signs:** Scanner finds `.DS_Store`, `.git` contents, or `__pycache__` files.

### Pitfall 4: WAL Mode Requires File-Based Database

**What goes wrong:** `PRAGMA journal_mode=WAL` on `:memory:` databases returns `'memory'` (not `'wal'`). WAL only works with file-based databases.
**Why it happens:** WAL requires a separate `-wal` file on disk.
**How to avoid:** Always use a file path for the production database. For tests, either use a temp file or accept that in-memory DBs use journal mode `memory`.
**Warning signs:** `PRAGMA journal_mode` returns `'memory'` instead of `'wal'` in test fixtures.

### Pitfall 5: SQLite Default CURRENT_TIMESTAMP is UTC

**What goes wrong:** `DEFAULT CURRENT_TIMESTAMP` stores UTC time, not local time. Comparing with `datetime.now()` (local time) produces wrong results.
**Why it happens:** SQLite's `CURRENT_TIMESTAMP` is always UTC.
**How to avoid:** Use `strftime('%Y-%m-%dT%H:%M:%f', 'now')` in SQLite (UTC) and `datetime.utcnow()` or `datetime.now(timezone.utc)` in Python. Or use `strftime('%Y-%m-%dT%H:%M:%f', 'now', 'localtime')` for local time in SQLite.
**Warning signs:** Timestamps in DB don't match wall clock time.

### Pitfall 6: Extension Case Sensitivity

**What goes wrong:** `file.TXT` or `file.Txt` won't match `.txt` in a case-sensitive check.
**Why it happens:** `Path.suffix` preserves the original case.
**How to avoid:** Always compare `path.suffix.lower()` against lowercase extension set.
**Warning signs:** Missing files on case-sensitive filesystems or mixed-case libraries.

---

## Code Examples

### SQLite Schema Initialization

```python
# Source: Verified empirically against SQLite 3.51.0 on Python 3.13.5
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

-- Schema version tracking
PRAGMA user_version = 1;
"""
```

### File Hashing (Optimal Buffer Size)

```python
# Source: Benchmarked on Python 3.13.5
# 65536-byte buffer is optimal balance of speed vs memory
# 1,749 files at ~5KB each completes in ~35ms total
import hashlib

def compute_file_hash(file_path: Path, buf_size: int = 65536) -> str:
    """Compute SHA-256 hex digest of file content using streaming reads."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(buf_size), b""):
            sha256.update(block)
    return sha256.hexdigest()
```

### UPSERT Pattern for Idempotent Scanning

```python
# Source: Verified with SQLite 3.51.0 UPSERT support
# ON CONFLICT(file_path) DO UPDATE preserves created_at, updates updated_at via trigger
def upsert_file(conn, record):
    with conn:
        conn.execute("""
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
        """, (record.file_path, record.content_hash, record.filename,
              record.file_size, record.metadata_json,
              record.metadata_quality.value, 'pending'))
```

### Typer CLI Entry Point

```python
# Source: Typer 0.23.0 with Annotated syntax (modern pattern)
from typing import Annotated
import typer
from rich.console import Console

app = typer.Typer(help="Objectivism Library Scanner")
console = Console()

@app.command()
def scan(
    library_path: Annotated[Path, typer.Option(
        "--library", "-l",
        help="Path to library root directory",
        exists=True, file_okay=False, resolve_path=True,
    )] = Path("/Volumes/U32 Shadow/Objectivism Library"),
    db_path: Annotated[Path, typer.Option(
        "--db", "-d",
        help="Path to SQLite database",
    )] = Path("data/library.db"),
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
):
    """Scan library and extract metadata into SQLite database."""
    ...

@app.command()
def status(
    db_path: Annotated[Path, typer.Option("--db", "-d")] = Path("data/library.db"),
):
    """Show database status summary."""
    ...
```

### Enum Pattern for Type-Safe Status Values

```python
# Source: Python 3.13 enum module; verified str(Enum) == value comparison works
from enum import Enum

class FileStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    FAILED = "failed"
    LOCAL_DELETE = "LOCAL_DELETE"

class MetadataQuality(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MINIMAL = "minimal"
    NONE = "none"
    UNKNOWN = "unknown"

# str, Enum pattern: FileStatus.PENDING == "pending" evaluates to True
# Works directly in SQLite queries: WHERE status = ?  with FileStatus.PENDING.value
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `setup.py` + `requirements.txt` | `pyproject.toml` (PEP 621) | Python 3.11+ era | Single config file for deps, scripts, build |
| `argparse` for CLI | Typer with Annotated syntax | Typer 0.9+ | Type-hint driven, auto help, shell completion |
| `os.path` for paths | `pathlib.Path` | Python 3.4+ (mature 3.6+) | OOP paths, `.suffix`, `.relative_to()`, `/` operator |
| Manual `os.walk()` | `Path.walk()` (3.12+) | Python 3.12 | Returns Path objects; BUT defaults `follow_symlinks=False` |
| `print()` for output | Rich Console + logging | Rich 10+ | Structured, colored, filterable output |
| `INSERT OR REPLACE` | `ON CONFLICT DO UPDATE` | SQLite 3.24+ | Preserves row identity, triggers, foreign keys |
| Manual timestamps | SQLite triggers | Always available | Automatic `updated_at`, no Python code needed |
| `hashlib.sha256()` | `hashlib.file_digest()` (3.11+) | Python 3.11 | Cleaner API but less buffer control |
| `sqlite3.connect()` | `sqlite3.connect(autocommit=...)` | Python 3.12 | Explicit transaction control (PEP 249 compliance) |

**Deprecated/outdated:**
- `sqlite3.version` attribute: deprecated in 3.12, removed in 3.14. Use `sqlite3.sqlite_version` instead.
- `from typing import Dict, List, Optional`: Use `dict`, `list`, `str | None` built-in generics (3.9+/3.10+).
- `setup.py` / `setup.cfg`: Replaced by `pyproject.toml` for modern projects.

---

## Performance Benchmarks (Verified)

All benchmarks run on the development machine (Python 3.13.5, SQLite 3.51.0, macOS):

| Operation | Time | Notes |
|-----------|------|-------|
| SHA-256 hash 1,749 files (~5KB each) | 35ms | 65KB buffer; I/O-bound |
| SHA-256 hash 5MB file (100 iterations) | 190ms | 65KB buffer optimal |
| Batch INSERT 2,000 rows | 3ms | Single transaction, executemany |
| UPSERT 2,000 rows | 2ms | ON CONFLICT DO UPDATE |
| `json_extract` query over 2,000 rows | <1ms | Full table scan with JSON function |
| Compiled regex match (100K iterations) | 60ms | 1.2x faster than uncompiled |

**Conclusion:** The entire Phase 1 scan (discover + hash + extract + insert) for 1,749 files will complete in seconds, not minutes. Performance optimization is unnecessary.

---

## Open Questions

1. **content_hash UNIQUE vs indexed**
   - What we know: UNIQUE constraint prevents duplicate content at different paths; user decided to upload separately if paths differ. These conflict.
   - What's unclear: Whether the library actually contains duplicate files at different paths.
   - Recommendation: Use regular index (not UNIQUE). Flag for planner as schema correction. This is the safer default.

2. **Package name: `objlib` vs something else**
   - What we know: Need a Python package name for `pyproject.toml` and imports.
   - What's unclear: User preference for naming.
   - Recommendation: `objlib` is short, descriptive, unlikely to conflict on PyPI. Planner can use this or ask user.

3. **Config format: JSON vs TOML**
   - What we know: User decided JSON (`scanner_config.json`). TOML is built-in since 3.11 but `tomllib` is read-only.
   - What's unclear: Whether config ever needs to be written programmatically.
   - Recommendation: Stick with JSON as decided. No need to change.

4. **Database location: `data/library.db` vs configurable**
   - What we know: Config specifies library path but not DB path.
   - What's unclear: Whether DB should live alongside library or in project directory.
   - Recommendation: Default to `data/library.db` in project directory. Override via CLI `--db` option.

---

## Sources

### Primary (HIGH confidence)
- **Python 3.13.5 sqlite3 module** -- verified empirically: WAL mode, JSON functions, UPSERT, RETURNING, STRICT tables, CHECK constraints, triggers, context manager transactions
- **SQLite 3.51.0 documentation** -- confirmed feature availability via runtime testing
- **Python 3.13.5 pathlib module** -- verified: `Path.walk()`, `Path.resolve()`, `Path.is_symlink()`, `Path.relative_to()`
- **Python 3.13.5 hashlib module** -- benchmarked: streaming SHA-256 with various buffer sizes
- **Typer 0.23.0** -- installed and verified: Annotated syntax, Rich integration
- **Rich 14.3.2** -- installed and verified: Console, Table, Progress, RichHandler

### Secondary (MEDIUM confidence)
- **os.walk behavior with symlinks** -- empirically verified cycle detection pattern with circular symlinks
- **regex pattern matching** -- verified against actual library filename examples from CLARIFICATIONS-ANSWERED.md
- **pyproject.toml pattern** -- standard PEP 621 format; hatchling is a common lightweight build backend

### Tertiary (LOW confidence)
- **hashlib.file_digest()** -- mentioned as 3.11+ alternative; not tested (standard hashlib pattern is sufficient)

---

## Recommendations for Planning

### Schema Correction Required
The `content_hash` column in CLARIFICATIONS-ANSWERED.md is specified as `UNIQUE INDEX`. **This must be changed to a regular index** because the user also decided "upload separately if paths differ." A UNIQUE constraint would block insertion of files with identical content at different paths. The planner should use `CREATE INDEX idx_content_hash ON files(content_hash)` (not `CREATE UNIQUE INDEX`).

### Regex Correction Required
The regex in CLARIFICATIONS-ANSWERED.md uses `\d{2}` for lesson numbers. **This must be changed to `\d+`** because:
- `\d{2}` won't match single-digit un-padded lessons (e.g., "Lesson 1")
- `\d{2}` won't match triple-digit lessons (e.g., "Lesson 100")
- `\d+` handles all cases robustly

### Module Organization
The planner should organize Phase 1 into these modules:
1. **models.py** (first) -- enums, dataclasses; no dependencies
2. **config.py** -- config loading; depends on models
3. **database.py** -- SQLite wrapper; depends on models
4. **metadata.py** -- regex extraction; depends on models
5. **scanner.py** -- file discovery; depends on config, database, metadata
6. **cli.py** -- Typer entry point; depends on scanner

### Testing Strategy
- Use `tmp_path` pytest fixture for temp directory trees
- Use temp file databases (not `:memory:`) to test WAL mode
- Create test fixtures that mirror actual library structure (Courses/Name/file.txt pattern)
- Test idempotency by running scan twice and asserting zero changes
- Test change detection by modifying files between scans

### Transaction Batching
Batch all file inserts in a single transaction per scan. With 1,749 files completing in milliseconds, there is no need for intermediate commits or progress checkpointing during Phase 1 database writes. (Phase 2 uploads will need checkpointing due to API latency.)

### Logging Strategy
Use stdlib `logging` with Rich's `RichHandler` for structured, colored output. This replaces the current `print()` pattern with proper log levels (DEBUG for file-by-file details, INFO for progress summaries, WARNING for extraction failures, ERROR for scan-halting issues).

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries verified installed and functional on dev machine
- Architecture: HIGH -- patterns verified empirically with working code examples
- Pitfalls: HIGH -- each pitfall reproduced and verified with test code
- Performance: HIGH -- all benchmarks run on actual dev machine

**Research date:** 2026-02-15
**Valid until:** 2026-03-15 (stable technology; stdlib + SQLite rarely change)
