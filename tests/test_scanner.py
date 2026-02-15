"""File scanner tests.

Validates:
  FOUN-02: Recursive file discovery with filtering
  FOUN-03: SHA-256 hash-based change detection
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from objlib.config import ScannerConfig
from objlib.database import Database
from objlib.metadata import MetadataExtractor
from objlib.scanner import FileScanner


def test_discover_files_finds_txt(tmp_library: Path, scanner_config: ScannerConfig, tmp_db: Database) -> None:
    """Discover finds all .txt files above min size."""
    extractor = MetadataExtractor()
    scanner = FileScanner(scanner_config, tmp_db, extractor)

    files = scanner.discover_files()
    names = {f.name for f in files}

    # Should find 6 valid files (3 simple + 2 complex + 1 random_notes)
    # NOT hidden_file.txt (hidden), NOT tiny.txt (too small)
    assert "Test Course Alpha - Lesson 01 - Introduction to Testing.txt" in names
    assert "Test Course Alpha - Lesson 02 - Advanced Testing.txt" in names
    assert "Test Course Alpha - Lesson 10 - Final Exam Review.txt" in names
    assert "Objectivism Seminar - Foundations - Year 1 - Q1 - Week 1 - Philosophy Overview.txt" in names
    assert "Objectivism Seminar - Foundations - Year 1 - Q1 - Week 2 - Metaphysics.txt" in names
    assert "random_notes.txt" in names
    assert len(files) == 6


def test_discover_skips_hidden(tmp_library: Path, scanner_config: ScannerConfig, tmp_db: Database) -> None:
    """Hidden files are not in discovery results."""
    extractor = MetadataExtractor()
    scanner = FileScanner(scanner_config, tmp_db, extractor)

    files = scanner.discover_files()
    names = {f.name for f in files}

    assert ".hidden_file.txt" not in names


def test_discover_skips_tiny(tmp_library: Path, scanner_config: ScannerConfig, tmp_db: Database) -> None:
    """Files below min_size are not in discovery results."""
    extractor = MetadataExtractor()
    scanner = FileScanner(scanner_config, tmp_db, extractor)

    files = scanner.discover_files()
    names = {f.name for f in files}

    assert "tiny.txt" not in names


def test_hash_deterministic() -> None:
    """Same content produces same hash across calls."""
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("deterministic content " * 100)
        f.flush()
        path = Path(f.name)

    try:
        hash1 = FileScanner.compute_hash(path)
        hash2 = FileScanner.compute_hash(path)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest
    finally:
        path.unlink()


def test_hash_different_content() -> None:
    """Different content produces different hashes."""
    import tempfile

    files = []
    try:
        for content in ["content A " * 100, "content B " * 100]:
            f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
            f.write(content)
            f.close()
            files.append(Path(f.name))

        hash1 = FileScanner.compute_hash(files[0])
        hash2 = FileScanner.compute_hash(files[1])
        assert hash1 != hash2
    finally:
        for f in files:
            f.unlink()


def test_change_detection_new(tmp_library: Path, scanner_config: ScannerConfig, tmp_db: Database) -> None:
    """First scan marks all files as new."""
    extractor = MetadataExtractor()
    scanner = FileScanner(scanner_config, tmp_db, extractor)

    changes = scanner.scan()

    assert len(changes.new) == 6
    assert len(changes.modified) == 0
    assert len(changes.deleted) == 0
    assert len(changes.unchanged) == 0


def test_change_detection_unchanged(tmp_library: Path, scanner_config: ScannerConfig, tmp_db: Database) -> None:
    """Second scan on unchanged library marks all as unchanged."""
    extractor = MetadataExtractor()
    scanner = FileScanner(scanner_config, tmp_db, extractor)

    scanner.scan()  # First scan
    changes = scanner.scan()  # Second scan

    assert len(changes.new) == 0
    assert len(changes.modified) == 0
    assert len(changes.deleted) == 0
    assert len(changes.unchanged) == 6


def test_change_detection_modified(tmp_library: Path, scanner_config: ScannerConfig, tmp_db: Database) -> None:
    """Modifying file content triggers modified detection on re-scan."""
    extractor = MetadataExtractor()
    scanner = FileScanner(scanner_config, tmp_db, extractor)

    scanner.scan()  # First scan

    # Modify a file
    target = tmp_library / "Courses" / "Test Course Alpha" / "Test Course Alpha - Lesson 01 - Introduction to Testing.txt"
    target.write_text("completely new content " * 200)

    changes = scanner.scan()  # Re-scan

    assert len(changes.modified) == 1
    assert len(changes.unchanged) == 5


def test_change_detection_deleted(tmp_library: Path, scanner_config: ScannerConfig, tmp_db: Database) -> None:
    """Deleting a file triggers deleted detection on re-scan."""
    extractor = MetadataExtractor()
    scanner = FileScanner(scanner_config, tmp_db, extractor)

    scanner.scan()  # First scan

    # Delete a file
    target = tmp_library / "Courses" / "Test Course Alpha" / "Test Course Alpha - Lesson 01 - Introduction to Testing.txt"
    target.unlink()

    changes = scanner.scan()  # Re-scan

    assert len(changes.deleted) == 1
    assert len(changes.unchanged) == 5


def test_symlink_cycle_detection(tmp_path: Path) -> None:
    """Scanner doesn't hang on circular symlinks (timeout protection)."""
    root = tmp_path / "cycle_lib"
    root.mkdir()
    sub = root / "subdir"
    sub.mkdir()

    # Create a circular symlink: subdir/link -> root
    link = sub / "link_to_root"
    link.symlink_to(root)

    # Create a valid file
    (root / "valid_file.txt").write_text("valid content " * 200)

    db_path = tmp_path / "cycle.db"
    config = ScannerConfig(library_path=root, db_path=db_path, follow_symlinks=True)

    with Database(db_path) as db:
        extractor = MetadataExtractor()
        scanner = FileScanner(config, db, extractor)

        # Should complete without hanging
        changes = scanner.scan()

        # Should find the one valid file
        assert len(changes.new) >= 1
