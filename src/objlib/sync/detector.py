"""Sync change detector with mtime-optimized file comparison.

Wraps FileScanner for discovery and adds mtime optimization on top:
files whose mtime hasn't changed skip the expensive SHA-256 hash
computation. This reduces sync time dramatically when most files
are unchanged (the common case).
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
from objlib.scanner import FileScanner

logger = logging.getLogger(__name__)


# Enrichment version: bump when enrichment logic changes materially
# (e.g., new metadata tiers, content injection format changes).
_VERSION_STRING = "enriched_upload_v1"
CURRENT_ENRICHMENT_VERSION = hashlib.sha256(
    _VERSION_STRING.encode()
).hexdigest()[:8]


@dataclass
class SyncChangeSet:
    """Result of sync change detection with mtime optimization."""

    new_files: list[dict] = field(default_factory=list)
    modified_files: list[dict] = field(default_factory=list)
    missing_files: set[str] = field(default_factory=set)
    unchanged_count: int = 0
    mtime_skipped_count: int = 0

    @property
    def summary(self) -> str:
        return (
            f"new={len(self.new_files)}, modified={len(self.modified_files)}, "
            f"missing={len(self.missing_files)}, unchanged={self.unchanged_count}, "
            f"mtime_skipped={self.mtime_skipped_count}"
        )


class SyncDetector:
    """mtime-optimized change detector that wraps FileScanner primitives.

    Reuses FileScanner.discover_files() for file discovery and
    FileScanner.compute_hash() for SHA-256 computation, adding mtime
    optimization on top: files with unchanged mtime skip hash computation.

    Usage::

        detector = SyncDetector(config, db, metadata_extractor)
        changeset = detector.detect_changes(force=False)
        print(changeset.summary)
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
        # Reuse FileScanner for discovery and hashing
        self._scanner = FileScanner(config, db, metadata_extractor)

    def detect_changes(self, force: bool = False) -> SyncChangeSet:
        """Detect new, modified, and missing files with mtime optimization.

        Args:
            force: If True, skip mtime optimization and re-check all
                files. Also treats files with outdated enrichment_version
                as modified.

        Returns:
            SyncChangeSet with categorized files.
        """
        # Step 1: Discover eligible files on disk
        discovered_paths = self._scanner.discover_files()
        scan_paths = {str(p) for p in discovered_paths}
        # Build path -> Path lookup for later use
        path_lookup: dict[str, Path] = {str(p): p for p in discovered_paths}

        # Step 2: Load DB state
        db_files = self.db.get_all_active_files_with_mtime()
        db_paths = set(db_files.keys())

        # Step 3: Set operations
        new_paths = scan_paths - db_paths
        missing_paths = db_paths - scan_paths
        common_paths = scan_paths & db_paths

        changeset = SyncChangeSet(missing_files=missing_paths)

        # Step 4: Process common files (mtime optimization)
        for path_str in common_paths:
            db_hash, db_size, db_mtime = db_files[path_str]

            # Get current mtime
            try:
                current_mtime = os.stat(path_str).st_mtime
            except OSError as e:
                logger.warning("Cannot stat %s: %s", path_str, e)
                continue

            # mtime optimization: skip hash if mtime unchanged
            if (
                not force
                and db_mtime is not None
                and abs(current_mtime - db_mtime) < 1e-6
            ):
                changeset.mtime_skipped_count += 1
                changeset.unchanged_count += 1
                continue

            # Compute hash
            content_hash = FileScanner.compute_hash(Path(path_str))
            if not content_hash:
                continue

            if content_hash != db_hash:
                # File content changed -- needs re-upload
                file_data = self._get_file_with_sync_data(path_str)
                old_gemini_file_id = (
                    file_data.get("gemini_file_id") if file_data else None
                )
                changeset.modified_files.append({
                    "file_path": path_str,
                    "content_hash": content_hash,
                    "mtime": current_mtime,
                    "file_size": os.path.getsize(path_str),
                    "old_gemini_file_id": old_gemini_file_id,
                })
            else:
                # Hash same but mtime may have changed -- update mtime
                changeset.unchanged_count += 1
                if db_mtime is None or abs(current_mtime - db_mtime) >= 1e-6:
                    self.db.update_file_sync_columns(
                        path_str, mtime=current_mtime
                    )

                # In force mode, also check enrichment version
                if force:
                    file_data = self._get_file_with_sync_data(path_str)
                    if (
                        file_data
                        and file_data.get("enrichment_version")
                        != CURRENT_ENRICHMENT_VERSION
                    ):
                        old_gemini_file_id = file_data.get("gemini_file_id")
                        changeset.modified_files.append({
                            "file_path": path_str,
                            "content_hash": content_hash,
                            "mtime": current_mtime,
                            "file_size": os.path.getsize(path_str),
                            "old_gemini_file_id": old_gemini_file_id,
                        })
                        # Remove from unchanged count since we just added it
                        changeset.unchanged_count -= 1

        # Step 5: Process new files
        for path_str in new_paths:
            file_path = path_lookup[path_str]
            content_hash = FileScanner.compute_hash(file_path)
            if not content_hash:
                continue

            try:
                stat = file_path.stat()
                file_size = stat.st_size
                mtime = stat.st_mtime
            except OSError as e:
                logger.warning("Cannot stat %s: %s", path_str, e)
                continue

            # Extract metadata using the same extractor as scanner
            metadata, quality = self.metadata_extractor.extract(
                file_path, self.config.library_path
            )
            metadata_json = json.dumps(metadata, ensure_ascii=False)

            changeset.new_files.append({
                "file_path": path_str,
                "content_hash": content_hash,
                "mtime": mtime,
                "file_size": file_size,
                "metadata_json": metadata_json,
                "metadata_quality": quality.value,
                "filename": file_path.name,
            })

        logger.info("Sync detection complete: %s", changeset.summary)
        return changeset

    def _get_file_with_sync_data(self, file_path: str) -> dict | None:
        """Load sync data for a file from the database."""
        return self.db.get_file_with_sync_data(file_path)
