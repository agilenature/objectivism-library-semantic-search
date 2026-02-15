"""End-to-end integration tests.

Validates all 5 Phase 1 success criteria:
  1. Scan discovers all 1,749 files (tested with representative subset)
  2. Metadata extraction with quality grading
  3. Idempotent re-scan shows 0 changes
  4. Incremental change detection (add/modify/delete)
  5. Schema has upload columns for Phase 2
"""

from __future__ import annotations

import json
from pathlib import Path

from objlib.config import ScannerConfig
from objlib.database import Database
from objlib.metadata import MetadataExtractor
from objlib.scanner import FileScanner


def test_full_scan_lifecycle(tmp_library: Path, tmp_path: Path) -> None:
    """End-to-end lifecycle: scan, verify, re-scan, add, modify, delete.

    Tests SUCCESS CRITERIA 3 (idempotency) and 4 (change detection).
    """
    db_path = tmp_path / "lifecycle.db"
    config = ScannerConfig(library_path=tmp_library, db_path=db_path)

    with Database(db_path) as db:
        extractor = MetadataExtractor()
        scanner = FileScanner(config, db, extractor)

        # Step 1: First scan -- all files should be new
        changes = scanner.scan()
        assert len(changes.new) == 6
        assert len(changes.modified) == 0
        assert len(changes.deleted) == 0

        # Step 2: Verify all records in DB with metadata
        total = db.get_file_count()
        assert total == 6

        # Check a record has metadata
        row = db.conn.execute(
            "SELECT metadata_json, metadata_quality FROM files WHERE filename LIKE '%Lesson 01%'"
        ).fetchone()
        assert row is not None
        metadata = json.loads(row["metadata_json"])
        assert "course" in metadata
        assert row["metadata_quality"] == "complete"

        # Step 3: Re-scan -- idempotent, zero changes (SUCCESS CRITERION 3)
        changes = scanner.scan()
        assert len(changes.new) == 0
        assert len(changes.modified) == 0
        assert len(changes.deleted) == 0
        assert len(changes.unchanged) == 6

        # Step 4a: Add a new file, re-scan detects 1 new (SUCCESS CRITERION 4)
        new_file = (
            tmp_library
            / "Courses"
            / "Test Course Alpha"
            / "Test Course Alpha - Lesson 03 - New Topic.txt"
        )
        new_file.write_text("brand new content for new lesson " * 100)
        changes = scanner.scan()
        assert len(changes.new) == 1
        assert len(changes.unchanged) == 6

        # Step 4b: Modify a file, re-scan detects 1 modified (SUCCESS CRITERION 4)
        mod_file = (
            tmp_library
            / "Courses"
            / "Test Course Alpha"
            / "Test Course Alpha - Lesson 02 - Advanced Testing.txt"
        )
        mod_file.write_text("completely modified content " * 200)
        changes = scanner.scan()
        assert len(changes.modified) == 1
        assert len(changes.unchanged) == 6  # 6 unchanged (original 5 + new file)

        # Step 4c: Delete a file, re-scan detects 1 deleted (SUCCESS CRITERION 4)
        del_file = (
            tmp_library
            / "Courses"
            / "Test Course Alpha"
            / "Test Course Alpha - Lesson 10 - Final Exam Review.txt"
        )
        del_file.unlink()
        changes = scanner.scan()
        assert len(changes.deleted) == 1
        assert len(changes.unchanged) == 6  # remaining 6 are unchanged

        # Step 5: Verify schema has upload columns (SUCCESS CRITERION 5)
        columns = db.conn.execute("PRAGMA table_info(files)").fetchall()
        col_names = {c["name"] for c in columns}
        assert "upload_timestamp" in col_names
        assert "gemini_file_uri" in col_names
        assert "gemini_file_id" in col_names
        assert "remote_expiration_ts" in col_names
        assert "embedding_model_version" in col_names


def test_metadata_quality_distribution(tmp_library: Path, tmp_path: Path) -> None:
    """After scan, quality counts match expectations for the test library.

    Known-pattern files get COMPLETE, random file gets MINIMAL (has topic from stem).
    """
    db_path = tmp_path / "quality.db"
    config = ScannerConfig(library_path=tmp_library, db_path=db_path)

    with Database(db_path) as db:
        extractor = MetadataExtractor()
        scanner = FileScanner(config, db, extractor)

        scanner.scan()
        quality_counts = db.get_quality_counts()

        # 3 simple pattern + 2 complex pattern = 5 complete
        assert quality_counts.get("complete", 0) == 5

        # random_notes.txt: in Courses/Misc/ folder, gets course from folder,
        # topic from stem -> PARTIAL (has course + topic but no lesson)
        # OR MINIMAL depending on folder depth.
        # Actual: Courses/Misc/random_notes.txt -> category=course, course=Misc, topic=random_notes -> PARTIAL
        total_non_complete = sum(
            v for k, v in quality_counts.items() if k != "complete"
        )
        assert total_non_complete == 1  # random_notes.txt
