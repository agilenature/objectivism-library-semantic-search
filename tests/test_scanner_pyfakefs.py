"""pyfakefs-based scanner tests.

Uses pyfakefs to simulate a complete filesystem without touching disk.
Validates file discovery, filtering, hashing, nested traversal, change
detection (new/modified/deleted), empty directories, and size recording.

CRITICAL: pyfakefs intercepts open() at builtins level, which conflicts
with C-level SQLite file operations. All database fixtures use :memory:
SQLite via the in_memory_db fixture to avoid this conflict.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from objlib.config import ScannerConfig
from objlib.metadata import MetadataExtractor
from objlib.models import FileRecord, MetadataQuality
from objlib.scanner import ChangeSet, FileScanner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LARGE_CONTENT = "This is test content for the Objectivism Library scanner. " * 50
"""Content string >1 KB to satisfy default min_file_size=1024."""


def _make_scanner(
    fs,
    in_memory_db,
    library_root: str = "/library",
    allowed_extensions: set[str] | None = None,
    min_file_size: int = 100,
) -> FileScanner:
    """Create a FileScanner wired to a pyfakefs root and in-memory DB."""
    fs.create_dir(library_root)
    config = ScannerConfig(
        library_path=Path(library_root),
        db_path=Path(":memory:"),
        allowed_extensions=allowed_extensions or {".txt"},
        min_file_size=min_file_size,
    )
    extractor = MetadataExtractor()
    return FileScanner(config, in_memory_db, extractor)


# ---------------------------------------------------------------------------
# Discovery tests
# ---------------------------------------------------------------------------


class TestDiscovery:
    """File discovery on a fake filesystem."""

    def test_discover_txt_files(self, fs, in_memory_db) -> None:
        """Create 3 .txt files (each >100 bytes) and assert all 3 discovered."""
        scanner = _make_scanner(fs, in_memory_db)
        fs.create_file("/library/file1.txt", contents=LARGE_CONTENT)
        fs.create_file("/library/file2.txt", contents=LARGE_CONTENT)
        fs.create_file("/library/sub/file3.txt", contents=LARGE_CONTENT)

        files = scanner.discover_files()

        assert len(files) == 3
        names = {f.name for f in files}
        assert names == {"file1.txt", "file2.txt", "file3.txt"}

    def test_skip_hidden_files(self, fs, in_memory_db) -> None:
        """Hidden files (dot-prefix) are excluded from discovery."""
        scanner = _make_scanner(fs, in_memory_db)
        fs.create_file("/library/normal.txt", contents=LARGE_CONTENT)
        fs.create_file("/library/.hidden_file.txt", contents=LARGE_CONTENT)

        files = scanner.discover_files()
        names = {f.name for f in files}

        assert "normal.txt" in names
        assert ".hidden_file.txt" not in names

    def test_skip_tiny_files(self, fs, in_memory_db) -> None:
        """Files below min_file_size are excluded from discovery."""
        scanner = _make_scanner(fs, in_memory_db, min_file_size=100)
        fs.create_file("/library/big.txt", contents="x" * 200)
        fs.create_file("/library/tiny.txt", contents="x" * 50)

        files = scanner.discover_files()
        names = {f.name for f in files}

        assert "big.txt" in names
        assert "tiny.txt" not in names

    def test_skip_non_txt_files(self, fs, in_memory_db) -> None:
        """Non-.txt files (.epub, .pdf) are excluded from discovery."""
        scanner = _make_scanner(fs, in_memory_db)
        fs.create_file("/library/good.txt", contents=LARGE_CONTENT)
        fs.create_file("/library/book.epub", contents=LARGE_CONTENT)
        fs.create_file("/library/paper.pdf", contents=LARGE_CONTENT)

        files = scanner.discover_files()
        names = {f.name for f in files}

        assert names == {"good.txt"}

    def test_nested_directory_traversal(self, fs, in_memory_db) -> None:
        """Scanner traverses deeply nested directory structures."""
        scanner = _make_scanner(fs, in_memory_db)
        deep_path = "/library/Courses/Course1/Year1/Q1/file.txt"
        fs.create_file(deep_path, contents=LARGE_CONTENT)

        files = scanner.discover_files()

        assert len(files) == 1
        assert files[0].name == "file.txt"
        assert "Q1" in str(files[0].parent)

    def test_empty_directory(self, fs, in_memory_db) -> None:
        """Empty directory tree yields 0 files without crashing."""
        scanner = _make_scanner(fs, in_memory_db)
        fs.create_dir("/library/empty1/empty2/empty3")

        files = scanner.discover_files()

        assert len(files) == 0

    def test_file_size_recorded_correctly(self, fs, in_memory_db) -> None:
        """File size reported by scanner matches actual content length."""
        content = "a" * 512
        scanner = _make_scanner(fs, in_memory_db, min_file_size=100)
        fs.create_file("/library/sized.txt", contents=content)

        files = scanner.discover_files()

        assert len(files) == 1
        actual_size = os.path.getsize(str(files[0]))
        assert actual_size == len(content.encode("utf-8"))


# ---------------------------------------------------------------------------
# Hashing tests
# ---------------------------------------------------------------------------


class TestHashing:
    """SHA-256 hash computation on pyfakefs files."""

    def test_compute_hash_on_fake_file(self, fs) -> None:
        """Hash of known content matches hashlib.sha256 directly."""
        content = "Hello, Objectivism Library!"
        fs.create_file("/tmp/test.txt", contents=content)

        result = FileScanner.compute_hash(Path("/tmp/test.txt"))
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()

        assert result == expected
        assert len(result) == 64  # SHA-256 hex digest length

    def test_hash_deterministic(self, fs) -> None:
        """Same content produces same hash. Different content produces different hash."""
        fs.create_file("/tmp/a.txt", contents="same content")
        fs.create_file("/tmp/b.txt", contents="same content")
        fs.create_file("/tmp/c.txt", contents="different content")

        hash_a = FileScanner.compute_hash(Path("/tmp/a.txt"))
        hash_b = FileScanner.compute_hash(Path("/tmp/b.txt"))
        hash_c = FileScanner.compute_hash(Path("/tmp/c.txt"))

        assert hash_a == hash_b
        assert hash_a != hash_c


# ---------------------------------------------------------------------------
# Change detection tests
# ---------------------------------------------------------------------------


class TestChangeDetection:
    """Change detection: new, modified, deleted files using pyfakefs + in-memory DB."""

    def test_change_detection_new_file(self, fs, in_memory_db) -> None:
        """After initial scan, a newly added file is detected as new."""
        scanner = _make_scanner(fs, in_memory_db)
        fs.create_file("/library/initial.txt", contents=LARGE_CONTENT)

        # Initial scan populates DB
        changes1 = scanner.scan()
        assert len(changes1.new) == 1

        # Add a new file
        fs.create_file("/library/added.txt", contents=LARGE_CONTENT + " new")

        # Re-scan detects the new file
        changes2 = scanner.scan()
        assert len(changes2.new) == 1
        assert any("added.txt" in p for p in changes2.new)
        assert len(changes2.unchanged) == 1

    def test_change_detection_modified_file(self, fs, in_memory_db) -> None:
        """Modifying file content triggers modified detection on re-scan."""
        scanner = _make_scanner(fs, in_memory_db)
        fs.create_file("/library/mutable.txt", contents=LARGE_CONTENT)

        # Initial scan
        scanner.scan()

        # Modify file content by rewriting it
        with open("/library/mutable.txt", "w") as f:
            f.write("completely rewritten content " * 50)

        # Re-scan detects modification
        changes = scanner.scan()
        assert len(changes.modified) == 1
        assert any("mutable.txt" in p for p in changes.modified)

    def test_change_detection_deleted_file(self, fs, in_memory_db) -> None:
        """Removing a file triggers deleted detection on re-scan."""
        scanner = _make_scanner(fs, in_memory_db)
        fs.create_file("/library/file1.txt", contents=LARGE_CONTENT)
        fs.create_file("/library/file2.txt", contents=LARGE_CONTENT + " extra")

        # Initial scan
        scanner.scan()

        # Delete one file
        os.remove("/library/file1.txt")

        # Re-scan detects deletion
        changes = scanner.scan()
        assert len(changes.deleted) == 1
        assert any("file1.txt" in p for p in changes.deleted)
        assert len(changes.unchanged) == 1

    def test_first_scan_all_new(self, fs, in_memory_db) -> None:
        """First scan on a fresh DB marks all files as new."""
        scanner = _make_scanner(fs, in_memory_db)
        for i in range(5):
            fs.create_file(f"/library/file{i}.txt", contents=LARGE_CONTENT + f" {i}")

        changes = scanner.scan()

        assert len(changes.new) == 5
        assert len(changes.modified) == 0
        assert len(changes.deleted) == 0
        assert len(changes.unchanged) == 0

    def test_second_scan_all_unchanged(self, fs, in_memory_db) -> None:
        """Second scan with no changes marks all as unchanged."""
        scanner = _make_scanner(fs, in_memory_db)
        for i in range(3):
            fs.create_file(f"/library/file{i}.txt", contents=LARGE_CONTENT + f" {i}")

        scanner.scan()  # First scan
        changes = scanner.scan()  # Second scan

        assert len(changes.unchanged) == 3
        assert len(changes.new) == 0
        assert len(changes.modified) == 0
        assert len(changes.deleted) == 0
