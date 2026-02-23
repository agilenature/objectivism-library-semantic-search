"""Tests for SyncDetector (mtime optimization, classification, safety guard) and disk utility.

Uses pyfakefs for filesystem simulation and in-memory SQLite for database state.
No real disk I/O or API calls are made.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from objlib.config import ScannerConfig
from objlib.database import Database
from objlib.metadata import MetadataExtractor
from objlib.models import FileRecord, MetadataQuality
from objlib.sync.detector import SyncDetector
from objlib.sync.disk import check_disk_availability


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    db = Database.__new__(Database)
    db.conn = conn
    db.db_path = ":memory:"
    db._setup_schema()
    yield db
    conn.close()


def _file_hash(content: str) -> str:
    """Compute SHA-256 hex digest of a string (matching FileScanner.compute_hash)."""
    return hashlib.sha256(content.encode()).hexdigest()


def _insert_file(db: Database, file_path: str, content_hash: str,
                 file_size: int, mtime: float | None = None) -> None:
    """Insert a file record and optionally set its mtime."""
    record = FileRecord(
        file_path=file_path,
        content_hash=content_hash,
        filename=file_path.split("/")[-1],
        file_size=file_size,
    )
    db.upsert_file(record)
    # Mark as indexed so it counts as "active"
    db.conn.execute(
        "UPDATE files SET gemini_state = 'indexed' WHERE file_path = ?",
        (file_path,),
    )
    db.conn.commit()
    if mtime is not None:
        db.update_file_sync_columns(file_path, mtime=mtime)


def _make_detector(fs_fixture, db: Database, library_root: str) -> SyncDetector:
    """Build a SyncDetector with a fake filesystem library root."""
    config = ScannerConfig(
        library_path=Path(library_root),
        db_path=Path(":memory:"),
        min_file_size=100,  # Low threshold for test files
    )
    extractor = MetadataExtractor()
    return SyncDetector(config, db, extractor)


def _create_test_file(fs, path: str, content: str) -> float:
    """Create a file on the fake filesystem and return its mtime."""
    fs.create_file(path, contents=content)
    return Path(path).stat().st_mtime


# ---------------------------------------------------------------------------
# SyncDetector Classification Tests
# ---------------------------------------------------------------------------


class TestSyncDetectorClassification:
    """Test that SyncDetector correctly classifies files as new, unchanged,
    modified, or deleted."""

    def test_detect_new_file(self, fs, in_memory_db):
        """A file on disk but NOT in the database is classified as 'new'."""
        library_root = "/fake/library"
        fs.create_dir(library_root)
        content = "x" * 200  # Above min_file_size
        _create_test_file(fs, f"{library_root}/new_file.txt", content)

        detector = _make_detector(fs, in_memory_db, library_root)
        changeset = detector.detect_changes()

        assert len(changeset.new_files) == 1
        assert changeset.new_files[0]["file_path"] == f"{library_root}/new_file.txt"
        assert changeset.unchanged_count == 0
        assert len(changeset.missing_files) == 0

    def test_detect_unchanged_file(self, fs, in_memory_db):
        """A file on disk with matching hash, size, and mtime is classified as
        'unchanged' (mtime skip path)."""
        library_root = "/fake/library"
        fs.create_dir(library_root)
        content = "y" * 200
        file_path = f"{library_root}/unchanged.txt"
        mtime = _create_test_file(fs, file_path, content)

        content_hash = _file_hash(content)
        _insert_file(in_memory_db, file_path, content_hash, len(content), mtime=mtime)

        detector = _make_detector(fs, in_memory_db, library_root)
        changeset = detector.detect_changes()

        assert len(changeset.new_files) == 0
        assert len(changeset.modified_files) == 0
        assert len(changeset.missing_files) == 0
        assert changeset.unchanged_count == 1

    def test_detect_modified_file(self, fs, in_memory_db):
        """A file on disk whose content differs from DB hash is classified as
        'modified'."""
        library_root = "/fake/library"
        fs.create_dir(library_root)
        original_content = "a" * 200
        new_content = "b" * 200
        file_path = f"{library_root}/modified.txt"

        # Insert with old hash
        old_hash = _file_hash(original_content)
        _insert_file(in_memory_db, file_path, old_hash, len(original_content),
                     mtime=1000.0)

        # Create file with different content and a different mtime
        _create_test_file(fs, file_path, new_content)

        detector = _make_detector(fs, in_memory_db, library_root)
        changeset = detector.detect_changes()

        assert len(changeset.modified_files) == 1
        assert changeset.modified_files[0]["file_path"] == file_path

    def test_detect_deleted_file(self, fs, in_memory_db):
        """A file in the DB but NOT on disk is classified as 'missing'.
        Enough other files must exist to avoid the safety guard."""
        library_root = "/fake/library"
        fs.create_dir(library_root)

        # Create 3 files on disk, insert 4 into DB (1 missing, <50%)
        live_content = "c" * 200
        for i in range(3):
            path = f"{library_root}/file_{i}.txt"
            mtime = _create_test_file(fs, path, live_content)
            _insert_file(in_memory_db, path, _file_hash(live_content),
                         len(live_content), mtime=mtime)

        # This file exists only in DB, not on disk
        deleted_path = f"{library_root}/deleted_file.txt"
        _insert_file(in_memory_db, deleted_path, "deadbeef", 200, mtime=999.0)

        detector = _make_detector(fs, in_memory_db, library_root)
        changeset = detector.detect_changes()

        assert deleted_path in changeset.missing_files


# ---------------------------------------------------------------------------
# mtime Optimization Tests
# ---------------------------------------------------------------------------


class TestMtimeOptimization:
    """Test mtime-based hash skip optimization per decision [05-03]."""

    def test_mtime_unchanged_skips_hash(self, fs, in_memory_db):
        """When mtime is unchanged, hash is NOT recomputed (file skipped).
        Verified via mtime_skipped_count."""
        library_root = "/fake/library"
        fs.create_dir(library_root)
        content = "d" * 200
        file_path = f"{library_root}/skip_hash.txt"
        mtime = _create_test_file(fs, file_path, content)

        _insert_file(in_memory_db, file_path, _file_hash(content),
                     len(content), mtime=mtime)

        detector = _make_detector(fs, in_memory_db, library_root)
        changeset = detector.detect_changes()

        assert changeset.mtime_skipped_count == 1
        assert changeset.unchanged_count == 1
        assert len(changeset.modified_files) == 0

    def test_mtime_changed_triggers_hash(self, fs, in_memory_db):
        """When mtime differs from DB, hash IS computed and classification
        depends on hash comparison."""
        library_root = "/fake/library"
        fs.create_dir(library_root)
        content = "e" * 200
        file_path = f"{library_root}/check_hash.txt"
        _create_test_file(fs, file_path, content)

        # Insert with correct hash but stale mtime
        _insert_file(in_memory_db, file_path, _file_hash(content),
                     len(content), mtime=1000.0)

        detector = _make_detector(fs, in_memory_db, library_root)
        changeset = detector.detect_changes()

        # Hash matches so file is unchanged, but mtime_skipped should NOT count
        assert changeset.mtime_skipped_count == 0
        # Hash same -> unchanged, mtime gets updated
        assert changeset.unchanged_count == 1
        assert len(changeset.modified_files) == 0

    def test_mtime_epsilon_tolerance(self, fs, in_memory_db):
        """Mtime difference < 1e-6 is treated as unchanged (epsilon tolerance
        per decision [05-03])."""
        library_root = "/fake/library"
        fs.create_dir(library_root)
        content = "f" * 200
        file_path = f"{library_root}/epsilon.txt"
        mtime = _create_test_file(fs, file_path, content)

        # Store mtime with sub-epsilon difference
        _insert_file(in_memory_db, file_path, _file_hash(content),
                     len(content), mtime=mtime + 1e-8)

        detector = _make_detector(fs, in_memory_db, library_root)
        changeset = detector.detect_changes()

        assert changeset.mtime_skipped_count == 1
        assert changeset.unchanged_count == 1


# ---------------------------------------------------------------------------
# Safety Guard Tests
# ---------------------------------------------------------------------------


class TestSafetyGuard:
    """Test the >50% missing files safety guard (RuntimeError)."""

    def test_safety_guard_triggers_on_mass_missing(self, fs, in_memory_db):
        """When >50% of DB files are missing from disk, RuntimeError is raised."""
        library_root = "/fake/library"
        fs.create_dir(library_root)

        # Insert 100 files into DB (above the max(50, ...) threshold)
        content = "g" * 200
        for i in range(100):
            path = f"{library_root}/file_{i:03d}.txt"
            _insert_file(in_memory_db, path, _file_hash(content + str(i)),
                         len(content), mtime=1000.0)

        # Create only 40 on fake filesystem (<50% present)
        for i in range(40):
            path = f"{library_root}/file_{i:03d}.txt"
            fs.create_file(path, contents=content)

        detector = _make_detector(fs, in_memory_db, library_root)

        with pytest.raises(RuntimeError, match="SAFETY ABORT"):
            detector.detect_changes()

    def test_safety_guard_ok_when_enough_present(self, fs, in_memory_db):
        """When >=50% of DB files exist on disk, detection proceeds normally."""
        library_root = "/fake/library"
        fs.create_dir(library_root)

        content = "h" * 200
        # Insert 10 files into DB (below max(50) threshold, so percentage applies)
        # But safety guard uses max(50, len(db_paths) * 0.5)
        # With 10 files, max(50, 5) = 50 -- so 6 missing < 50 -> no trigger
        # We need to test the percentage path: use enough files
        # Actually with 10 files: missing_paths > max(50, 5) = 50
        # Since 50 is the floor, even all 10 missing (10 < 50) won't trigger!
        # Let's use 200 files to test the percentage path (> 50 threshold)
        for i in range(200):
            path = f"{library_root}/file_{i:03d}.txt"
            _insert_file(in_memory_db, path, _file_hash(content + str(i)),
                         len(content), mtime=1000.0)

        # Create 160 on filesystem (80% present, 40 missing < 100 = 50% of 200)
        for i in range(160):
            path = f"{library_root}/file_{i:03d}.txt"
            fs.create_file(path, contents=content)

        detector = _make_detector(fs, in_memory_db, library_root)

        # Should NOT raise -- 40 missing < max(50, 100) = 100
        changeset = detector.detect_changes()
        assert len(changeset.missing_files) == 40

    def test_safety_guard_minimum_threshold(self, fs, in_memory_db):
        """Safety guard has a minimum threshold of 50 -- even 100% missing with
        few files won't trigger if count < 50."""
        library_root = "/fake/library"
        fs.create_dir(library_root)

        content = "i" * 200
        # Insert 10 files in DB, create 0 on disk
        # missing = 10, max(50, 5) = 50, 10 < 50 -> no trigger
        for i in range(10):
            path = f"{library_root}/gone_{i}.txt"
            _insert_file(in_memory_db, path, _file_hash(content + str(i)),
                         len(content), mtime=1000.0)

        # Create just the library root with no files matching DB
        # But we need at least one file on disk for discover_files to find
        # Actually, discover_files will find 0 files, which is fine
        detector = _make_detector(fs, in_memory_db, library_root)

        # Should NOT raise because 10 < 50 minimum threshold
        changeset = detector.detect_changes()
        assert len(changeset.missing_files) == 10


# ---------------------------------------------------------------------------
# Disk Utility Tests
# ---------------------------------------------------------------------------


class TestDiskUtility:
    """Test disk availability checking with pyfakefs."""

    def test_disk_mounted(self, fs):
        """When mount point and library root exist, disk reports 'available'."""
        mount_point = "/Volumes/TestDisk"
        library_root = f"{mount_point}/MyLibrary"
        fs.create_dir(mount_point)
        fs.create_dir(library_root)
        fs.create_file(f"{library_root}/somefile.txt", contents="data")

        result = check_disk_availability(library_root, mount_point)
        assert result == "available"

    def test_disk_unmounted(self, fs):
        """When mount point does not exist, disk reports 'unavailable'."""
        mount_point = "/Volumes/MissingDisk"
        library_root = f"{mount_point}/MyLibrary"

        result = check_disk_availability(library_root, mount_point)
        assert result == "unavailable"

    def test_disk_empty_mount_point(self, fs):
        """When mount point exists but library root does not, reports 'degraded'."""
        mount_point = "/Volumes/EmptyDisk"
        library_root = f"{mount_point}/MyLibrary"
        fs.create_dir(mount_point)
        # Mount point exists and is listable, but library_root does not exist

        result = check_disk_availability(library_root, mount_point)
        assert result == "degraded"

    def test_disk_mount_not_listable(self, fs):
        """When mount point exists but is not accessible, reports 'unavailable'."""
        mount_point = "/Volumes/BrokenDisk"
        library_root = f"{mount_point}/MyLibrary"
        fs.create_dir(mount_point)

        # Patch os.listdir to simulate permission error
        with patch("objlib.sync.disk.os.listdir", side_effect=OSError("Permission denied")):
            result = check_disk_availability(library_root, mount_point)
        assert result == "unavailable"
