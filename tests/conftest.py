"""Shared pytest fixtures for Objectivism Library scanner tests.

Provides temporary database, library directory tree, scanner config,
metadata extractor instances, and in-memory database fixtures for all
test modules.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from objlib.config import ScannerConfig
from objlib.database import Database
from objlib.metadata import MetadataExtractor
from objlib.models import FileRecord, MetadataQuality


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


@pytest.fixture
def in_memory_db():
    """Fresh initialized in-memory SQLite database.

    Uses Database.__new__() to bypass __init__ path validation.
    Calls real Database._setup_schema() to test actual schema setup.
    Sets row_factory and foreign_keys BEFORE schema setup.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    db = Database.__new__(Database)  # Skip __init__ path validation
    db.conn = conn
    db.db_path = ":memory:"
    db._setup_schema()
    yield db
    conn.close()


@pytest.fixture
def populated_db(in_memory_db):
    """In-memory database pre-populated with 5 test files and known gemini_state.

    Inserts files with different gemini_states for testing queries.
    gemini_state mapping: 'untracked' (was pending), 'indexed' (was uploaded), 'failed'.
    """
    test_files = [
        ("/library/Courses/OPAR/OPAR - Lesson 01 - Metaphysics.txt", "hash_a", 5000, "untracked"),
        ("/library/Courses/OPAR/OPAR - Lesson 02 - Epistemology.txt", "hash_b", 6000, "indexed"),
        ("/library/Courses/ITOE/ITOE - Lesson 01 - Concepts.txt", "hash_c", 4000, "indexed"),
        ("/library/Courses/HOP/HOP - Lesson 01 - Ancient Greece.txt", "hash_d", 7000, "untracked"),
        ("/library/Courses/Ethics/Ethics - Lesson 01 - Virtue.txt", "hash_e", 3000, "failed"),
    ]
    for file_path, content_hash, size, gemini_state in test_files:
        record = FileRecord(
            file_path=file_path,
            content_hash=content_hash,
            filename=file_path.split("/")[-1],
            file_size=size,
        )
        in_memory_db.upsert_file(record)
        if gemini_state != "untracked":
            in_memory_db.conn.execute(
                "UPDATE files SET gemini_state = ? WHERE file_path = ?",
                (gemini_state, file_path),
            )
    in_memory_db.conn.commit()
    yield in_memory_db


@pytest.fixture
def mock_gemini_client():
    """Mock Google GenAI client with deterministic responses.

    Provides MagicMock with .models.generate_content() returning
    a response with .parsed attribute for Pydantic structured output.
    """
    mock = MagicMock()
    mock.models.generate_content.return_value = MagicMock(parsed=None)
    return mock
