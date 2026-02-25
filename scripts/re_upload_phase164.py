#!/usr/bin/env python3
"""Phase 16.4 targeted re-upload: re-upload 40 Episode files with updated identity headers.

These 40 Episode files were batch-extracted in Plan 16.4-02 (previously failed_validation
from Phase 16.2, reset to pending in Plan 16.4-01). They now have 8 primary_topics each
and need re-upload so their Gemini File Search identity headers include the Tags field.

Upload-first sequence (same as re_enrich_retrieval.py):
1. Build content: identity_header + AI analysis header + transcript
2. Write temp file, upload to Files API -> new_gemini_file_id
3. Poll until ACTIVE
4. Import to production store -> new_store_doc_name; poll operation.done
5. Delete old store doc
6. Delete old raw file (404/403 = success, 48hr TTL may be expired)
7. Update SQLite: gemini_file_id, gemini_store_doc_id, gemini_state_updated_at
8. Remove temp file

Usage:
    python scripts/re_upload_phase164.py --store objectivism-library --db data/library.db
    python scripts/re_upload_phase164.py --store objectivism-library --db data/library.db --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path for objlib imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import keyring
from google import genai
from google.genai import types as genai_types

from objlib.upload.header_builder import build_identity_header

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Rate limiting
SLEEP_BETWEEN_FILES = 2  # seconds between each file
SLEEP_BETWEEN_BATCHES = 5  # seconds after every 10 files
BATCH_SIZE = 10


def resolve_store_name(client: genai.Client, display_name: str) -> str:
    """Find production store resource name by display_name."""
    stores = client.file_search_stores.list()
    for store in stores:
        if getattr(store, "display_name", None) == display_name:
            logger.info("Found store: %s", store.name)
            return store.name
    raise RuntimeError(f"Store '{display_name}' not found")


def get_phase164_files(conn: sqlite3.Connection) -> list[dict]:
    """Get the 40 Episode files that were batch-extracted in Phase 16.4-02.

    Identifies them by: approved, indexed, and have file_metadata_ai created today
    with prompt_version='batch-v1' (from this session's batch-extract).
    Excludes Office Hour files (already re-uploaded in Phase 16.3).
    """
    rows = conn.execute(
        """
        SELECT f.file_path, f.filename, f.gemini_store_doc_id, f.gemini_file_id,
               f.gemini_state
        FROM files f
        WHERE f.ai_metadata_status = 'approved'
          AND f.gemini_state = 'indexed'
          AND f.file_path IN (
            SELECT fma.file_path FROM file_metadata_ai fma
            WHERE fma.is_current = 1
              AND fma.prompt_version = 'batch-v1'
              AND date(fma.created_at) = date('now')
          )
          AND f.filename LIKE 'Episode%'
        ORDER BY f.filename
        """,
    ).fetchall()

    return [
        {
            "file_path": row[0],
            "filename": row[1],
            "gemini_store_doc_id": row[2],
            "gemini_file_id": row[3],
            "gemini_state": row[4],
        }
        for row in rows
    ]


def build_enriched_content_with_header(
    file_path: str, conn: sqlite3.Connection
) -> str | None:
    """Build full content: identity header + AI analysis header + raw transcript.

    Mirrors re_enrich_retrieval.py build_enriched_content_with_header().
    """
    identity_header = build_identity_header(file_path, conn)

    if not os.path.exists(file_path):
        return None

    try:
        transcript = Path(file_path).read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not read %s: %s", file_path, exc)
        return None

    # Build AI analysis header from metadata (same as content_preparer.py)
    row = conn.execute(
        "SELECT metadata_json FROM files WHERE file_path = ?",
        (file_path,),
    ).fetchone()

    ai_header = ""
    if row and row[0]:
        try:
            ai_metadata = json.loads(row[0])
            semantic = ai_metadata.get("semantic_description", {})
            summary = semantic.get("summary", "")
            key_arguments = semantic.get("key_arguments", [])
            positions = semantic.get("philosophical_positions", [])

            if summary or key_arguments or positions:
                header_parts = ["[AI Analysis]"]
                header_parts.append(
                    f"Category: {ai_metadata.get('category', 'unknown')} | "
                    f"Difficulty: {ai_metadata.get('difficulty', 'unknown')}"
                )
                header_parts.append("")

                if summary:
                    header_parts.append(f"Summary: {summary}")
                    header_parts.append("")

                if key_arguments:
                    header_parts.append("Key Arguments:")
                    for arg in key_arguments:
                        header_parts.append(f"- {arg}")
                    header_parts.append("")

                if positions:
                    header_parts.append("Philosophical Positions:")
                    for pos in positions:
                        header_parts.append(f"- {pos}")
                    header_parts.append("")

                header_parts.append("[Original Content]")
                ai_header = "\n".join(header_parts) + "\n"
        except (json.JSONDecodeError, TypeError):
            pass

    return identity_header + ai_header + transcript


def upload_file_with_poll(
    client: genai.Client, tmp_path: str, display_name: str, timeout: int = 300
) -> str:
    """Upload file to Files API and poll until ACTIVE. Returns file resource name."""
    file_obj = client.files.upload(
        file=tmp_path,
        config={"display_name": display_name[:512]},
    )
    logger.debug("Uploaded %s -> %s", display_name, file_obj.name)

    deadline = time.time() + timeout
    while time.time() < deadline:
        file_obj = client.files.get(name=file_obj.name)
        state_name = getattr(getattr(file_obj, "state", None), "name", None)
        if state_name == "ACTIVE":
            return file_obj.name
        if state_name == "FAILED":
            raise RuntimeError(f"File processing failed: {file_obj.name}")
        time.sleep(2)

    raise RuntimeError(f"Timeout waiting for file to become ACTIVE: {file_obj.name}")


def import_to_store_with_poll(
    client: genai.Client, store_name: str, file_name: str, timeout: int = 600
) -> str:
    """Import file to store and poll operation. Returns new store doc ID suffix."""
    operation = client.file_search_stores.import_file(
        file_search_store_name=store_name,
        file_name=file_name,
    )
    logger.debug("Import operation started for %s", file_name)

    deadline = time.time() + timeout
    while time.time() < deadline:
        operation = client.operations.get(operation=operation)
        if getattr(operation, "done", None) is True:
            error = getattr(operation, "error", None)
            if error:
                raise RuntimeError(f"Import failed: {error}")

            response = getattr(operation, "response", None)
            doc_name = None
            if response is not None:
                doc_name = getattr(response, "document_name", None)
                if doc_name is None:
                    doc_name = getattr(response, "name", None)

            if doc_name is None:
                raw = getattr(operation, "_raw_response", None)
                if isinstance(raw, dict):
                    resp = raw.get("response", {})
                    doc_name = resp.get("documentName") or resp.get("name")

            if doc_name is None:
                logger.warning("Could not extract document_name from operation response")
                return ""

            if "/documents/" in doc_name:
                return doc_name.split("/documents/")[-1]
            return doc_name

        time.sleep(5)

    raise RuntimeError("Timeout waiting for import operation to complete")


def delete_old_store_doc(
    client: genai.Client, store_name: str, old_store_doc_id: str
) -> bool:
    """Delete old store document. Returns True on success (404 = success)."""
    if not old_store_doc_id:
        return True

    full_name = f"{store_name}/documents/{old_store_doc_id}"
    try:
        client.file_search_stores.documents.delete(
            name=full_name,
            config=genai_types.DeleteDocumentConfig(force=True),
        )
        logger.debug("Deleted old store doc: %s", full_name)
        return True
    except Exception as exc:
        exc_str = str(exc)
        if "404" in exc_str or "NOT_FOUND" in exc_str or "not found" in exc_str.lower():
            logger.debug("Old store doc already gone (404): %s", full_name)
            return True
        if "403" in exc_str or "PERMISSION_DENIED" in exc_str:
            logger.debug("Old store doc inaccessible (403): %s", full_name)
            return True
        logger.error("Failed to delete old store doc %s: %s", full_name, exc)
        return False


def delete_old_raw_file(client: genai.Client, old_file_id: str) -> bool:
    """Delete old raw file. Returns True on success (404/403 = success)."""
    if not old_file_id:
        return True

    file_name = old_file_id if old_file_id.startswith("files/") else f"files/{old_file_id}"
    try:
        client.files.delete(name=file_name)
        logger.debug("Deleted old raw file: %s", file_name)
        return True
    except Exception as exc:
        exc_str = str(exc)
        if "404" in exc_str or "NOT_FOUND" in exc_str or "not found" in exc_str.lower():
            logger.debug("Old raw file already gone (404): %s", file_name)
            return True
        if "403" in exc_str or "PERMISSION_DENIED" in exc_str:
            logger.debug("Old raw file expired/inaccessible (403): %s", file_name)
            return True
        logger.error("Failed to delete old raw file %s: %s", file_name, exc)
        return False


def process_file(
    client: genai.Client,
    store_name: str,
    conn: sqlite3.Connection,
    file_info: dict,
    idx: int,
    total: int,
    dry_run: bool = False,
) -> bool:
    """Process a single file: upload-first sequence. Returns True on success."""
    file_path = file_info["file_path"]
    filename = file_info["filename"]
    old_store_doc_id = file_info["gemini_store_doc_id"]
    old_file_id = file_info.get("gemini_file_id")

    logger.info("[%d/%d] Processing: %s", idx, total, filename)

    if not old_store_doc_id:
        logger.warning("  SKIP: NULL gemini_store_doc_id")
        return False

    content = build_enriched_content_with_header(file_path, conn)
    if content is None:
        logger.warning("  SKIP: source file not found on disk: %s", file_path)
        return False

    if dry_run:
        logger.info("  DRY-RUN: would upload %d bytes for %s", len(content.encode("utf-8")), filename)
        return True

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    try:
        tmp.write(content)
        tmp.close()

        # Step 1: Upload to Files API + poll ACTIVE
        new_file_name = upload_file_with_poll(client, tmp.name, filename)
        logger.info("  Uploaded: %s", new_file_name)

        # Step 2: Import to store + poll operation
        new_store_doc_id = import_to_store_with_poll(client, store_name, new_file_name)
        logger.info("  Imported: store_doc_id=%s", new_store_doc_id)

        # Step 3: Delete old store document
        delete_old_store_doc(client, store_name, old_store_doc_id)

        # Step 4: Delete old raw file (404 = success)
        if old_file_id:
            delete_old_raw_file(client, old_file_id)

        # Step 5: Update SQLite
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """UPDATE files
               SET gemini_file_id = ?,
                   gemini_store_doc_id = ?,
                   gemini_state_updated_at = ?,
                   updated_at = ?
               WHERE file_path = ?""",
            (new_file_name, new_store_doc_id, now, now, file_path),
        )
        conn.commit()
        logger.info("  DB updated: file_id=%s, store_doc_id=%s", new_file_name, new_store_doc_id)
        return True

    except Exception as exc:
        logger.error("  FAILED: %s: %s", filename, exc)
        return False
    finally:
        try:
            os.unlink(tmp.name)
        except (FileNotFoundError, OSError):
            pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 16.4 targeted re-upload: 40 Episode files with updated identity headers"
    )
    parser.add_argument("--db", type=str, default="data/library.db", help="Path to SQLite database")
    parser.add_argument("--store", type=str, default="objectivism-library", help="Gemini store display name")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without uploading")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of files to process (0=all)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    db_path = Path(args.db)
    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Get files to re-upload
    files = get_phase164_files(conn)
    logger.info("Found %d Episode files for Phase 16.4 re-upload", len(files))

    if args.limit > 0:
        files = files[:args.limit]
        logger.info("Limited to %d files", len(files))

    if not files:
        logger.info("No files to process")
        conn.close()
        return

    # Initialize API client
    api_key = keyring.get_password("objlib-gemini", "api_key")
    if not api_key:
        logger.error("API key not found in keyring (service=objlib-gemini, key=api_key)")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # Resolve store
    store_name = resolve_store_name(client, args.store)

    # Process files
    succeeded = 0
    failed = 0
    skipped = 0
    total = len(files)
    start_time = time.time()

    for idx, file_info in enumerate(files, 1):
        try:
            ok = process_file(client, store_name, conn, file_info, idx, total, dry_run=args.dry_run)
            if ok:
                succeeded += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.error("[%d/%d] Unexpected error for %s: %s", idx, total, file_info["filename"], exc)
            failed += 1

        # Rate limiting
        if not args.dry_run:
            time.sleep(SLEEP_BETWEEN_FILES)
            if idx % BATCH_SIZE == 0:
                logger.info("  -- Batch pause (every %d files) --", BATCH_SIZE)
                time.sleep(SLEEP_BETWEEN_BATCHES)

        # Failure rate check
        if failed > 0 and (failed / idx) > 0.2 and idx >= 10:
            logger.error(
                "ABORT: failure rate %.0f%% (%d/%d) exceeds 20%% threshold",
                (failed / idx) * 100, failed, idx,
            )
            break

    elapsed = time.time() - start_time
    logger.info(
        "\n=== PHASE 16.4 RE-UPLOAD COMPLETE ===\n"
        "  Succeeded: %d\n"
        "  Failed:    %d\n"
        "  Skipped:   %d\n"
        "  Total:     %d\n"
        "  Elapsed:   %.1f seconds (%.1f min)\n"
        "  Rate:      %.1f files/min",
        succeeded, failed, skipped, total,
        elapsed, elapsed / 60,
        (succeeded / elapsed * 60) if elapsed > 0 else 0,
    )

    conn.close()

    if failed > 0:
        logger.warning("Some files failed -- check logs above for details")
        sys.exit(1)


if __name__ == "__main__":
    main()
