"""Sync orchestrator coordinating detect-upload-mark-cleanup pipeline.

Composes SyncDetector, GeminiFileSearchClient, and Database into a
complete incremental sync workflow with:
- Library config verification (store name mismatch = abort)
- Automatic orphan cleanup on startup
- Change detection with mtime optimization
- Upload-first atomic replacement (new before old deleted)
- Per-file SQLite commits for crash recovery
- Missing file marking and optional pruning
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from objlib.config import ScannerConfig
from objlib.database import Database
from objlib.metadata import MetadataExtractor
from objlib.models import FileRecord, MetadataQuality
from objlib.sync.detector import (
    CURRENT_ENRICHMENT_VERSION,
    SyncChangeSet,
    SyncDetector,
)
from objlib.upload.client import GeminiFileSearchClient
from objlib.upload.content_preparer import cleanup_temp_file, prepare_enriched_content
from objlib.upload.metadata_builder import build_enriched_metadata, compute_upload_hash

logger = logging.getLogger(__name__)


class SyncOrchestrator:
    """Coordinates the full incremental sync pipeline.

    Design constraints:
    - Per-file upload control (not batch-oriented)
    - Upload-first atomicity: new version uploaded before old deleted
    - Per-file SQLite commits for crash recovery
    - 404=success for store document deletion

    Usage::

        orchestrator = SyncOrchestrator(db, client, config, api_key, console)
        await orchestrator.run(dry_run=True)
    """

    def __init__(
        self,
        db: Database,
        client: GeminiFileSearchClient | None,
        config: ScannerConfig,
        api_key: str,
        console: Console,
        store_name: str | None = None,
    ) -> None:
        self.db = db
        self.client = client
        self.config = config
        self.api_key = api_key
        self.console = console
        self.store_name = store_name
        self._metadata_extractor = MetadataExtractor()

        # Tracking
        self._uploaded_new = 0
        self._uploaded_modified = 0
        self._marked_missing = 0
        self._pruned = 0
        self._orphans_cleaned = 0
        self._errors = 0

    async def run(
        self,
        force: bool = False,
        skip_enrichment: bool = False,
        dry_run: bool = False,
        prune_missing: bool = False,
        cleanup_orphans: bool = False,
        prune_age_days: int = 7,
    ) -> dict[str, int]:
        """Execute the full sync pipeline.

        Args:
            force: Re-process all files regardless of change detection.
            skip_enrichment: Use simple upload pipeline instead of enriched.
            dry_run: Preview changes without executing.
            prune_missing: Delete missing files (>prune_age_days old) from Gemini.
            cleanup_orphans: Explicitly clean orphaned Gemini entries.
            prune_age_days: Minimum age in days before missing files are pruned.

        Returns:
            Summary dict with counts.
        """
        # Step 1: Verify library config (store display name)
        # We store the display name (user-facing), not the Gemini resource name.
        stored_store = self.db.get_library_config("gemini_store_display_name")
        current_store = self.store_name
        if stored_store and current_store and stored_store != current_store:
            self.console.print(
                f"[red]Store name mismatch![/red]\n"
                f"  Configured: {current_store}\n"
                f"  Previously used: {stored_store}\n"
                f"  Action: Use --store {stored_store} or update library config."
            )
            return self.summary
        if not stored_store and current_store:
            self.db.set_library_config("gemini_store_display_name", current_store)
            logger.info("Stored library config: gemini_store_display_name=%s", current_store)

        # Step 2: Auto-cleanup orphans on startup
        if not dry_run:
            await self._cleanup_orphans()

        # Step 3: Run change detection
        detector = SyncDetector(self.config, self.db, self._metadata_extractor)
        changeset = detector.detect_changes(force=force)
        self.console.print(f"\n[bold]Change detection:[/bold] {changeset.summary}")

        # Step 3b: Restore LOCAL_DELETE files that reappeared on disk.
        # LOCAL_DELETE files are excluded from the active-files query, so they
        # look "new" to the detector even though they're in the DB. If they're
        # on disk with the same hash, just restore their status — no re-upload.
        if not dry_run:
            await self._restore_local_deletes(changeset.new_files)

        # Step 4: Dry-run mode
        if dry_run:
            self._print_dry_run(changeset)
            return self.summary

        # Step 5: Upload new files
        for file_info in changeset.new_files:
            await self._upload_new_file(file_info, skip_enrichment)

        # Step 6: Upload-first replacement for modified files
        for file_info in changeset.modified_files:
            await self._replace_modified_file(file_info, skip_enrichment)

        # Step 7: Mark missing files
        if changeset.missing_files:
            self.db.mark_missing(changeset.missing_files)
            self._marked_missing = len(changeset.missing_files)
            logger.info("Marked %d files as missing", self._marked_missing)

        # Step 8: Prune missing if requested
        if prune_missing:
            await self._prune_missing_files(prune_age_days)

        # Step 9: Explicit orphan cleanup if requested
        if cleanup_orphans:
            await self._cleanup_orphans()

        # Step 10: Report summary
        self._print_summary(changeset)
        return self.summary

    # ------------------------------------------------------------------
    # New file upload
    # ------------------------------------------------------------------

    async def _upload_new_file(
        self, file_info: dict, skip_enrichment: bool
    ) -> None:
        """Upload a new file to the Gemini store.

        Inserts the file record into the DB first (via upsert), then
        uploads to Gemini, then updates DB with Gemini IDs.
        """
        file_path = file_info["file_path"]
        filename = file_info.get("filename", os.path.basename(file_path))

        try:
            # Upsert file record to DB
            record = FileRecord(
                file_path=file_path,
                content_hash=file_info["content_hash"],
                filename=filename,
                file_size=file_info["file_size"],
                metadata_json=file_info.get("metadata_json"),
                metadata_quality=MetadataQuality(
                    file_info.get("metadata_quality", "unknown")
                ),
            )
            self.db.upsert_file(record)

            # Build metadata and upload
            custom_metadata, upload_path, upload_hash = self._build_file_upload_data(
                file_path, skip_enrichment
            )

            file_obj, operation = await self.client.upload_and_import(
                upload_path, filename[:512], custom_metadata
            )

            # Poll operation to completion
            completed = await self.client.poll_operation(operation)
            done = getattr(completed, "done", False)
            error = getattr(completed, "error", None)

            if done and not error:
                # Update DB with Gemini file info
                self.db.conn.execute(
                    "UPDATE files SET gemini_file_uri = ?, gemini_file_id = ?, "
                    "upload_timestamp = ?, gemini_state = 'indexed' "
                    "WHERE file_path = ?",
                    (
                        getattr(file_obj, "uri", ""),
                        getattr(file_obj, "name", ""),
                        self._now_iso(),
                        file_path,
                    ),
                )
                self.db.conn.commit()
                self.db.update_file_sync_columns(
                    file_path,
                    mtime=file_info.get("mtime"),
                    upload_hash=upload_hash,
                    enrichment_version=CURRENT_ENRICHMENT_VERSION,
                )
                self._uploaded_new += 1
                logger.info("Uploaded new file: %s", filename)
            else:
                error_msg = str(error) if error else "Import did not complete"
                self.db.conn.execute(
                    "UPDATE files SET error_message = ?, gemini_state = 'failed' "
                    "WHERE file_path = ?",
                    (error_msg, file_path),
                )
                self.db.conn.commit()
                self._errors += 1
                logger.error("Failed to import %s: %s", filename, error_msg)

        except Exception as exc:
            self.db.conn.execute(
                "UPDATE files SET error_message = ?, gemini_state = 'failed' "
                "WHERE file_path = ?",
                (str(exc), file_path),
            )
            self.db.conn.commit()
            self._errors += 1
            logger.error("Failed to upload new file %s: %s", filename, exc)

    # ------------------------------------------------------------------
    # Modified file replacement (upload-first atomicity)
    # ------------------------------------------------------------------

    async def _replace_modified_file(
        self, file_info: dict, skip_enrichment: bool
    ) -> None:
        """Replace a modified file using upload-first atomicity.

        1. Upload new version
        2. On success: store old gemini_file_id in orphaned_gemini_file_id
        3. Update to new gemini_file_id
        4. Attempt to delete old store document
        5. On delete success: clear orphaned_gemini_file_id
        """
        file_path = file_info["file_path"]
        filename = os.path.basename(file_path)
        old_gemini_file_id = file_info.get("old_gemini_file_id")

        try:
            # Update content hash in DB
            self.db.conn.execute(
                "UPDATE files SET content_hash = ?, file_size = ? WHERE file_path = ?",
                (file_info["content_hash"], file_info["file_size"], file_path),
            )
            self.db.conn.commit()

            # Build metadata and upload new version
            custom_metadata, upload_path, upload_hash = self._build_file_upload_data(
                file_path, skip_enrichment
            )

            file_obj, operation = await self.client.upload_and_import(
                upload_path, filename[:512], custom_metadata
            )

            # Poll operation
            completed = await self.client.poll_operation(operation)
            done = getattr(completed, "done", False)
            error = getattr(completed, "error", None)

            if not (done and not error):
                error_msg = str(error) if error else "Import did not complete"
                self.db.conn.execute(
                    "UPDATE files SET error_message = ?, gemini_state = 'failed' "
                    "WHERE file_path = ?",
                    (error_msg, file_path),
                )
                self.db.conn.commit()
                self._errors += 1
                logger.error("Failed to import replacement for %s: %s", filename, error_msg)
                return

            # Step 2: Store old ID as orphan, update to new
            if old_gemini_file_id:
                self.db.update_file_sync_columns(
                    file_path, orphaned_gemini_file_id=old_gemini_file_id
                )

            # Update with new Gemini file info
            self.db.conn.execute(
                "UPDATE files SET gemini_file_uri = ?, gemini_file_id = ?, "
                "upload_timestamp = ?, gemini_state = 'indexed' "
                "WHERE file_path = ?",
                (
                    getattr(file_obj, "uri", ""),
                    getattr(file_obj, "name", ""),
                    self._now_iso(),
                    file_path,
                ),
            )
            self.db.conn.commit()
            self.db.update_file_sync_columns(
                file_path,
                mtime=file_info.get("mtime"),
                upload_hash=upload_hash,
                enrichment_version=CURRENT_ENRICHMENT_VERSION,
            )

            # Step 3: Attempt to delete old store document
            if old_gemini_file_id:
                doc_name = await self.client.find_store_document_name(
                    old_gemini_file_id
                )
                if doc_name:
                    deleted = await self.client.delete_store_document(doc_name)
                    if deleted:
                        self.db.clear_orphan(file_path)
                        logger.info(
                            "Deleted old store document for %s", filename
                        )
                else:
                    # Could not find document -- clear orphan anyway
                    # (may have expired or been deleted already)
                    self.db.clear_orphan(file_path)
                    logger.info(
                        "Old store document not found for %s, cleared orphan",
                        filename,
                    )

            self._uploaded_modified += 1
            logger.info("Replaced modified file: %s", filename)

        except Exception as exc:
            self._errors += 1
            logger.error("Failed to replace %s: %s", filename, exc)

    # ------------------------------------------------------------------
    # Per-file enrichment helper
    # ------------------------------------------------------------------

    def _build_file_upload_data(
        self, file_path: str, skip_enrichment: bool
    ) -> tuple[list[dict[str, Any]], str, str]:
        """Build metadata and content for a single file upload.

        Args:
            file_path: Path to the file.
            skip_enrichment: If True, use simple metadata only.

        Returns:
            Tuple of (custom_metadata_list, upload_path, upload_hash).
            upload_path may be original file or temp file with injected content.
        """
        # Load Phase 1 metadata from files table
        row = self.db.conn.execute(
            "SELECT metadata_json, content_hash FROM files WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        phase1_json = row["metadata_json"] if row else "{}"
        content_hash = row["content_hash"] if row else ""
        phase1_metadata = json.loads(phase1_json) if phase1_json else {}

        if skip_enrichment:
            # Simple metadata only (Tier 1)
            custom_metadata = GeminiFileSearchClient.build_custom_metadata(
                phase1_metadata
            )
            upload_hash = compute_upload_hash(phase1_metadata, {}, [], content_hash)
            return custom_metadata, file_path, upload_hash

        # Load AI metadata
        ai_row = self.db.conn.execute(
            """SELECT metadata_json FROM file_metadata_ai
               WHERE file_path = ? AND is_current = 1""",
            (file_path,),
        ).fetchone()
        ai_json = ai_row["metadata_json"] if ai_row else "{}"
        ai_metadata = json.loads(ai_json) if ai_json else {}

        # Load entity names
        entity_rows = self.db.conn.execute(
            """SELECT p.canonical_name
               FROM transcript_entity te
               JOIN person p ON te.person_id = p.person_id
               WHERE te.transcript_id = ?
               ORDER BY te.mention_count DESC""",
            (file_path,),
        ).fetchall()
        entity_names = [r["canonical_name"] for r in entity_rows]

        # Build enriched metadata
        custom_metadata = build_enriched_metadata(
            phase1_metadata, ai_metadata, entity_names
        )

        # Prepare enriched content (temp file with Tier 4 header)
        temp_path = prepare_enriched_content(file_path, ai_metadata)
        upload_path = temp_path if temp_path is not None else file_path

        # Compute upload hash for idempotency
        upload_hash = compute_upload_hash(
            phase1_metadata, ai_metadata, entity_names, content_hash
        )

        # Note: caller is NOT responsible for cleanup of temp_path here.
        # The upload_and_import call reads the file synchronously,
        # so we clean up after the upload call returns.
        # For simplicity, we let the temp file persist until process exit
        # or the next sync run -- Python's tempfile module handles cleanup.
        # If this becomes a concern, the caller should handle cleanup.

        return custom_metadata, upload_path, upload_hash

    # ------------------------------------------------------------------
    # LOCAL_DELETE restoration

    async def _restore_local_deletes(self, new_files: list[dict]) -> None:
        """Restore LOCAL_DELETE files that have reappeared on disk.

        When the library disk was temporarily disconnected, the scanner marks
        all DB files as LOCAL_DELETE. On reconnect, the sync detector sees them
        as "new" (excluded from active-files query). If the file's hash matches
        what's in the DB, it's a false new — just restore status to uploaded.

        Modifies new_files in-place: removes entries that were restored so
        the upload step skips them.
        """
        restored_count = 0
        files_to_remove: list[dict] = []

        for file_info in new_files:
            file_path = file_info["file_path"]
            # Check if this file exists in DB as LOCAL_DELETE
            row = self.db.conn.execute(
                "SELECT is_deleted, content_hash, gemini_file_id FROM files "
                "WHERE file_path = ? AND is_deleted = 1",
                (file_path,),
            ).fetchone()
            if row is None:
                continue  # genuinely new file, let upload proceed

            db_hash = row["content_hash"]
            disk_hash = file_info.get("content_hash")
            gemini_id = row["gemini_file_id"]

            if disk_hash == db_hash and gemini_id:
                # Same content, still has a Gemini ID — just restore status
                self.db.conn.execute(
                    "UPDATE files SET is_deleted = 0, error_message = NULL, "
                    "mtime = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now') "
                    "WHERE file_path = ?",
                    (file_info.get("mtime"), file_path),
                )
                self.db.conn.commit()
                files_to_remove.append(file_info)
                restored_count += 1
                logger.info("Restored reappeared file: %s", file_path)

        for f in files_to_remove:
            new_files.remove(f)

        if restored_count:
            self.console.print(
                f"[green]Restored {restored_count} files[/green] that reappeared "
                "on disk (same content, no re-upload needed)."
            )

    # ------------------------------------------------------------------
    # Orphan cleanup
    # ------------------------------------------------------------------

    async def _cleanup_orphans(self) -> None:
        """Clean up orphaned Gemini entries from previous failed replacements."""
        orphans = self.db.get_orphaned_files()
        if not orphans:
            return

        logger.info("Cleaning up %d orphaned Gemini entries", len(orphans))
        for orphan in orphans:
            file_path = orphan["file_path"]
            orphaned_id = orphan["orphaned_gemini_file_id"]

            try:
                doc_name = await self.client.find_store_document_name(orphaned_id)
                if doc_name:
                    deleted = await self.client.delete_store_document(doc_name)
                    if deleted:
                        self.db.clear_orphan(file_path)
                        self._orphans_cleaned += 1
                        logger.info("Cleaned orphan for %s", file_path)
                else:
                    # Document not found in store -- clear the orphan marker
                    self.db.clear_orphan(file_path)
                    self._orphans_cleaned += 1
                    logger.info(
                        "Orphan document not found (expired?), cleared for %s",
                        file_path,
                    )
            except Exception as exc:
                logger.error(
                    "Failed to clean orphan for %s: %s", file_path, exc
                )

    # ------------------------------------------------------------------
    # Missing file pruning
    # ------------------------------------------------------------------

    async def _prune_missing_files(self, min_age_days: int) -> None:
        """Delete missing files (older than min_age_days) from Gemini store."""
        missing = self.db.get_missing_files(min_age_days=min_age_days)
        if not missing:
            self.console.print(
                f"[dim]No missing files older than {min_age_days} days to prune.[/dim]"
            )
            return

        self.console.print(
            f"Pruning {len(missing)} missing files (>{min_age_days} days old)..."
        )
        for file_info in missing:
            file_path = file_info["file_path"]
            gemini_file_id = file_info.get("gemini_file_id")

            try:
                if gemini_file_id:
                    doc_name = await self.client.find_store_document_name(
                        gemini_file_id
                    )
                    if doc_name:
                        await self.client.delete_store_document(doc_name)

                # Mark as deleted
                self.db.mark_deleted({file_path})
                self._pruned += 1
                logger.info("Pruned missing file: %s", file_path)

            except Exception as exc:
                self._errors += 1
                logger.error("Failed to prune %s: %s", file_path, exc)

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _print_dry_run(self, changeset: SyncChangeSet) -> None:
        """Print what would happen without executing."""
        self.console.print("\n[bold yellow]DRY RUN[/bold yellow] -- no changes made\n")

        if changeset.new_files:
            table = Table(title=f"New Files ({len(changeset.new_files)})")
            table.add_column("Filename", style="green")
            table.add_column("Size", justify="right")
            for f in changeset.new_files[:20]:
                size_kb = f["file_size"] / 1024
                table.add_row(
                    os.path.basename(f["file_path"]),
                    f"{size_kb:.0f} KB",
                )
            if len(changeset.new_files) > 20:
                table.add_row(
                    f"... and {len(changeset.new_files) - 20} more", ""
                )
            self.console.print(table)

        if changeset.modified_files:
            table = Table(title=f"Modified Files ({len(changeset.modified_files)})")
            table.add_column("Filename", style="yellow")
            table.add_column("Size", justify="right")
            for f in changeset.modified_files[:20]:
                size_kb = f["file_size"] / 1024
                table.add_row(
                    os.path.basename(f["file_path"]),
                    f"{size_kb:.0f} KB",
                )
            if len(changeset.modified_files) > 20:
                table.add_row(
                    f"... and {len(changeset.modified_files) - 20} more", ""
                )
            self.console.print(table)

        if changeset.missing_files:
            self.console.print(
                f"\n[red]Missing from disk:[/red] {len(changeset.missing_files)} files"
            )
            for path in list(changeset.missing_files)[:10]:
                self.console.print(f"  - {os.path.basename(path)}")
            if len(changeset.missing_files) > 10:
                self.console.print(
                    f"  ... and {len(changeset.missing_files) - 10} more"
                )

        self.console.print(
            f"\n[dim]Unchanged: {changeset.unchanged_count} "
            f"(mtime skipped: {changeset.mtime_skipped_count})[/dim]"
        )

    def _print_summary(self, changeset: SyncChangeSet) -> None:
        """Print sync summary after execution."""
        table = Table(title="Sync Summary")
        table.add_column("Metric", style="bold")
        table.add_column("Count", justify="right")

        table.add_row("New uploaded", f"[green]{self._uploaded_new}[/green]")
        table.add_row("Modified replaced", f"[yellow]{self._uploaded_modified}[/yellow]")
        table.add_row("Marked missing", f"[red]{self._marked_missing}[/red]")
        table.add_row("Pruned", str(self._pruned))
        table.add_row("Orphans cleaned", str(self._orphans_cleaned))
        table.add_row("Errors", f"[red]{self._errors}[/red]" if self._errors else "0")
        table.add_row("Unchanged", str(changeset.unchanged_count))
        table.add_row("mtime skipped", f"[dim]{changeset.mtime_skipped_count}[/dim]")

        self.console.print(table)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _now_iso() -> str:
        """Return current UTC time in ISO 8601 format."""
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    @property
    def summary(self) -> dict[str, int]:
        """Return sync summary counts."""
        return {
            "new_uploaded": self._uploaded_new,
            "modified_replaced": self._uploaded_modified,
            "marked_missing": self._marked_missing,
            "pruned": self._pruned,
            "orphans_cleaned": self._orphans_cleaned,
            "errors": self._errors,
        }
