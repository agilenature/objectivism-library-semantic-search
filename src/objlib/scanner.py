"""File scanner with discovery, hashing, and change detection.

Discovers all eligible files in the Objectivism Library, computes
SHA-256 content hashes, extracts metadata, and detects changes
against the database state. Uses os.walk() for symlink-safe traversal
with cycle detection via inode tracking.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from objlib.config import ScannerConfig
from objlib.database import Database
from objlib.metadata import MetadataExtractor
from objlib.models import FileRecord, MetadataQuality

logger = logging.getLogger(__name__)


@dataclass
class ChangeSet:
    """Results of comparing a scan against database state.

    Each set contains file path strings (not Path objects) to match
    the database's file_path TEXT column.
    """

    new: set[str] = field(default_factory=set)
    modified: set[str] = field(default_factory=set)
    deleted: set[str] = field(default_factory=set)
    unchanged: set[str] = field(default_factory=set)

    @property
    def summary(self) -> str:
        """Human-readable summary of changes."""
        return (
            f"new={len(self.new)}, modified={len(self.modified)}, "
            f"deleted={len(self.deleted)}, unchanged={len(self.unchanged)}"
        )


class FileScanner:
    """Scans a directory tree, extracts metadata, computes hashes, and detects changes.

    Usage:
        config = ScannerConfig(library_path=Path("/path/to/library"))
        db = Database("data/library.db")
        extractor = MetadataExtractor()
        scanner = FileScanner(config, db, extractor)
        changes = scanner.scan()
        print(changes.summary)
    """

    def __init__(
        self,
        config: ScannerConfig,
        db: Database,
        metadata_extractor: MetadataExtractor,
    ) -> None:
        self.config = config
        self.db = db
        self.metadata_extractor = metadata_extractor

    def discover_files(self) -> list[Path]:
        """Discover all eligible files recursively from the library root.

        Uses os.walk() with symlink cycle detection (visited_inodes).
        Prunes hidden directories and skip_patterns in-place.
        Filters files by extension, size, and hidden status.

        Returns:
            List of Path objects for files matching all filters.
        """
        root = self.config.library_path
        matched: list[Path] = []
        visited_inodes: set[tuple[int, int]] = set()

        # Track root inode
        try:
            root_stat = root.stat()
            visited_inodes.add((root_stat.st_dev, root_stat.st_ino))
        except OSError as e:
            logger.error("Cannot stat library root %s: %s", root, e)
            return matched

        for dirpath, dirnames, filenames in os.walk(
            str(root), followlinks=self.config.follow_symlinks
        ):
            current = Path(dirpath)

            # Symlink cycle detection
            if self.config.follow_symlinks and current != root:
                try:
                    st = current.stat()
                    dir_id = (st.st_dev, st.st_ino)
                    if dir_id in visited_inodes:
                        logger.warning(
                            "Symlink cycle detected: %s", current
                        )
                        dirnames.clear()
                        continue
                    visited_inodes.add(dir_id)
                except OSError as e:
                    logger.warning("Cannot stat directory %s: %s", current, e)
                    dirnames.clear()
                    continue

            # Prune directories IN-PLACE (slice assignment)
            if self.config.skip_hidden:
                dirnames[:] = [
                    d
                    for d in dirnames
                    if not d.startswith(".")
                    and d not in self.config.skip_patterns
                ]
            else:
                dirnames[:] = [
                    d
                    for d in dirnames
                    if d not in self.config.skip_patterns
                ]

            for filename in filenames:
                full_path = current / filename

                # Skip hidden files
                if self.config.skip_hidden and filename.startswith("."):
                    self.db.log_skipped_file(
                        str(full_path), "hidden_file"
                    )
                    continue

                # Check extension (case-insensitive)
                ext = Path(filename).suffix.lower()
                if ext not in self.config.allowed_extensions:
                    self.db.log_skipped_file(
                        str(full_path),
                        f"extension_not_allowed: {ext}",
                    )
                    continue

                # Check file size
                try:
                    file_size = os.path.getsize(str(full_path))
                except OSError as e:
                    logger.warning("Cannot stat file %s: %s", full_path, e)
                    self.db.log_skipped_file(
                        str(full_path), f"stat_error: {e}"
                    )
                    continue

                if file_size < self.config.min_file_size:
                    self.db.log_skipped_file(
                        str(full_path),
                        f"too_small: {file_size} < {self.config.min_file_size}",
                        file_size=file_size,
                    )
                    continue

                matched.append(full_path)

        logger.info("Discovered %d eligible files", len(matched))
        return matched

    @staticmethod
    def compute_hash(file_path: Path, buf_size: int = 65536) -> str:
        """Compute SHA-256 hex digest of file content using streaming reads.

        Args:
            file_path: Path to the file.
            buf_size: Read buffer size in bytes (default 64KB).

        Returns:
            Hex digest string, or empty string on permission error.
        """
        sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for block in iter(lambda: f.read(buf_size), b""):
                    sha256.update(block)
        except PermissionError:
            logger.warning("Permission denied reading %s", file_path)
            return ""
        except OSError as e:
            logger.warning("Error reading %s: %s", file_path, e)
            return ""
        return sha256.hexdigest()

    def scan(self) -> ChangeSet:
        """Run a full scan: discover, hash, extract metadata, detect changes.

        Orchestrates the complete scanning pipeline:
        1. Discover eligible files
        2. Compute hashes and extract metadata for each file
        3. Detect changes against database state
        4. Persist new/modified files via UPSERT
        5. Mark deleted files as LOCAL_DELETE
        6. Log extraction failures

        Returns:
            ChangeSet with new/modified/deleted/unchanged file sets.
        """
        files = self.discover_files()

        # Build scan results: {file_path_str: FileRecord}
        scan_results: dict[str, FileRecord] = {}
        extraction_failures: list[tuple[str, str | None, str | None]] = []

        for file_path in files:
            content_hash = self.compute_hash(file_path)
            if not content_hash:
                # Hash failed (permission error) -- skip this file
                continue

            try:
                file_size = file_path.stat().st_size
            except OSError:
                continue

            # Extract metadata
            metadata, quality = self.metadata_extractor.extract(
                file_path, self.config.library_path
            )

            # Track extraction failures for logging
            if metadata.get("_unparsed_filename") or metadata.get(
                "_unparsed_folder"
            ):
                extraction_failures.append(
                    (
                        str(file_path),
                        str(file_path.parent.name)
                        if metadata.get("_unparsed_folder")
                        else None,
                        file_path.name
                        if metadata.get("_unparsed_filename")
                        else None,
                    )
                )

            metadata_json = json.dumps(metadata, ensure_ascii=False)

            record = FileRecord(
                file_path=str(file_path),
                content_hash=content_hash,
                filename=file_path.name,
                file_size=file_size,
                metadata_json=metadata_json,
                metadata_quality=quality,
            )
            scan_results[str(file_path)] = record

        # Detect changes against DB
        changes = self.detect_changes(scan_results)

        # Persist new + modified files
        records_to_upsert = [
            scan_results[p]
            for p in changes.new | changes.modified
        ]
        if records_to_upsert:
            self.db.upsert_files(records_to_upsert)
            logger.info(
                "Upserted %d files (%d new, %d modified)",
                len(records_to_upsert),
                len(changes.new),
                len(changes.modified),
            )

        # Mark deleted files
        if changes.deleted:
            # Safety guard: if >50% of library appears deleted, the disk is
            # likely disconnected. Abort rather than mass-corrupt the DB.
            db_file_count = len(changes.deleted) + len(changes.unchanged) + len(changes.modified)
            if len(changes.deleted) > max(50, db_file_count * 0.5):
                raise RuntimeError(
                    f"SAFETY ABORT: {len(changes.deleted)}/{db_file_count} files "
                    f"({len(changes.deleted) * 100 // max(db_file_count, 1)}%) "
                    "appear deleted — library disk likely disconnected. "
                    "Mount the drive and retry."
                )
            self.db.mark_deleted(changes.deleted)
            logger.info("Marked %d files as deleted", len(changes.deleted))

        # Log extraction failures
        for fp, folder, fname in extraction_failures:
            self.db.log_extraction_failure(fp, folder, fname)

        logger.info("Scan complete: %s", changes.summary)
        return changes

    def detect_changes(
        self, scan_results: dict[str, FileRecord]
    ) -> ChangeSet:
        """Compare scan results against database state using set operations.

        Args:
            scan_results: Dict mapping file path string to FileRecord
                from the current scan.

        Returns:
            ChangeSet categorizing all files as new/modified/deleted/unchanged.
        """
        db_files = self.db.get_all_active_files()

        scan_paths = set(scan_results.keys())
        db_paths = set(db_files.keys())

        new = scan_paths - db_paths
        deleted = db_paths - scan_paths
        common = scan_paths & db_paths

        modified = {
            p
            for p in common
            if scan_results[p].content_hash != db_files[p][0]
        }
        unchanged = common - modified

        return ChangeSet(
            new=new,
            modified=modified,
            deleted=deleted,
            unchanged=unchanged,
        )
