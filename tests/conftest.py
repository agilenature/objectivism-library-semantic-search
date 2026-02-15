"""Shared pytest fixtures for Objectivism Library scanner tests.

Provides temporary database, library directory tree, scanner config,
and metadata extractor instances for all test modules.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from objlib.config import ScannerConfig
from objlib.database import Database
from objlib.metadata import MetadataExtractor


@pytest.fixture
def tmp_db(tmp_path: Path) -> Database:
    """Create a temporary SQLite database (file-based for WAL support)."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    yield db
    db.close()


@pytest.fixture
def tmp_library(tmp_path: Path) -> Path:
    """Create a temporary directory tree mimicking the real Objectivism Library.

    Structure:
        Courses/
          Test Course Alpha/
            Test Course Alpha - Lesson 01 - Introduction to Testing.txt  (>1KB)
            Test Course Alpha - Lesson 02 - Advanced Testing.txt         (>1KB)
            Test Course Alpha - Lesson 10 - Final Exam Review.txt        (>1KB)
          Objectivism Seminar - Foundations/
            Year1/
              Q1/
                Objectivism Seminar - Foundations - Year 1 - Q1 - Week 1 - Philosophy Overview.txt (>1KB)
                Objectivism Seminar - Foundations - Year 1 - Q1 - Week 2 - Metaphysics.txt (>1KB)
          Misc/
            random_notes.txt   (>1KB, unknown pattern)
            .hidden_file.txt   (should be skipped)
            tiny.txt           (<100 bytes, should be skipped)
    """
    root = tmp_path / "library"
    root.mkdir()

    # Simple pattern files
    simple_dir = root / "Courses" / "Test Course Alpha"
    simple_dir.mkdir(parents=True)
    content = "This is test content for the Objectivism Library scanner. " * 50

    (simple_dir / "Test Course Alpha - Lesson 01 - Introduction to Testing.txt").write_text(content)
    (simple_dir / "Test Course Alpha - Lesson 02 - Advanced Testing.txt").write_text(content + " extra")
    (simple_dir / "Test Course Alpha - Lesson 10 - Final Exam Review.txt").write_text(content + " more")

    # Complex pattern files
    complex_dir = root / "Courses" / "Objectivism Seminar - Foundations" / "Year1" / "Q1"
    complex_dir.mkdir(parents=True)

    (complex_dir / "Objectivism Seminar - Foundations - Year 1 - Q1 - Week 1 - Philosophy Overview.txt").write_text(content)
    (complex_dir / "Objectivism Seminar - Foundations - Year 1 - Q1 - Week 2 - Metaphysics.txt").write_text(content + " philosophy")

    # Misc files (some should be skipped)
    misc_dir = root / "Courses" / "Misc"
    misc_dir.mkdir(parents=True)

    (misc_dir / "random_notes.txt").write_text(content)
    (misc_dir / ".hidden_file.txt").write_text(content)
    (misc_dir / "tiny.txt").write_text("small")  # <100 bytes, below min_file_size

    return root


@pytest.fixture
def scanner_config(tmp_library: Path, tmp_db: Database) -> ScannerConfig:
    """Create a ScannerConfig pointing to the temporary library and database."""
    return ScannerConfig(
        library_path=tmp_library,
        db_path=Path(tmp_db.db_path),
    )


@pytest.fixture
def metadata_extractor() -> MetadataExtractor:
    """Create a fresh MetadataExtractor instance."""
    return MetadataExtractor()
