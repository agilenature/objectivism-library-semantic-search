#!/usr/bin/env python3
"""Phase 16.3 production remediation: re-upload Category A + B files with identity metadata headers.

Upload-first sequence (safe: new file verified before old file deleted):
1. Build content: identity_header + existing_enriched_content (AI header + transcript)
2. Write temp file, upload to Files API -> new_gemini_file_id
3. Poll until ACTIVE
4. Import to production store -> new_store_doc_name; poll operation.done
5. Delete old store doc: delete(old_full_store_doc_resource_name)
6. Delete old raw file: delete(old_gemini_file_id) [404 = success, 48hr TTL may be expired]
7. Update SQLite: gemini_file_id, gemini_store_doc_id, gemini_state_updated_at
8. Remove temp file

Usage:
    python scripts/re_enrich_retrieval.py [--limit N] [--dry-run] [--category {a,b,c,all}]
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "retrieval-fix-manifest.json"
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "library.db"
PRODUCTION_STORE_DISPLAY_NAME = "objectivism-library"

# Rate limiting
SLEEP_BETWEEN_FILES = 2  # seconds between each file
SLEEP_BETWEEN_BATCHES = 5  # seconds after every 10 files
BATCH_SIZE = 10


def resolve_store_name(client: genai.Client) -> str:
    """Find production store resource name by display_name."""
    stores = client.file_search_stores.list()
    for store in stores:
        if getattr(store, "display_name", None) == PRODUCTION_STORE_DISPLAY_NAME:
            logger.info("Found production store: %s", store.name)
            return store.name
    raise RuntimeError(
        f"Production store '{PRODUCTION_STORE_DISPLAY_NAME}' not found"
    )


def build_enriched_content_with_header(
    file_path: str, conn: sqlite3.Connection
) -> str | None:
    """Build full content: identity header + raw transcript.

    The identity header provides discriminating metadata (title, course,
    class number, topic, primary_topics tags) that Gemini uses for
    semantic search ranking.

    For files that already have AI analysis content (via content_preparer.py),
    we read the original file on disk and prepend the identity header.
    The AI analysis header was injected during the first upload but is NOT
    in the on-disk file -- it was in a temp file that was cleaned up.
    So we rebuild: identity_header + raw_transcript_from_disk.

    Returns the combined content string, or None if source file not found.
    """
    identity_header = build_identity_header(file_path, conn)

    # Read raw transcript from disk
    if not os.path.exists(file_path):
        return None

    try:
        transcript = Path(file_path).read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not read %s: %s", file_path, exc)
        return None

    # Also build the AI analysis header from metadata (same as content_preparer.py)
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

    # Combined: identity header + AI analysis header + transcript
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

    # Poll until ACTIVE
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

    # Poll operation until done
    deadline = time.time() + timeout
    while time.time() < deadline:
        operation = client.operations.get(operation=operation)
        if getattr(operation, "done", None) is True:
            error = getattr(operation, "error", None)
            if error:
                raise RuntimeError(f"Import failed: {error}")

            # Extract document name from response
            response = getattr(operation, "response", None)
            if response is not None:
                doc_name = getattr(response, "document_name", None)
                if doc_name is None:
                    doc_name = getattr(response, "name", None)

            if doc_name is None:
                # Try raw dict parsing
                raw = getattr(operation, "_raw_response", None)
                if isinstance(raw, dict):
                    resp = raw.get("response", {})
                    doc_name = resp.get("documentName") or resp.get("name")

            if doc_name is None:
                logger.warning("Could not extract document_name from operation response")
                return ""

            # doc_name might be full resource name or just suffix
            # e.g. "fileSearchStores/.../documents/abc123-def456"
            # We store just the suffix after the last "documents/"
            if "/documents/" in doc_name:
                return doc_name.split("/documents/")[-1]
            return doc_name

        time.sleep(5)

    raise RuntimeError(f"Timeout waiting for import operation to complete")


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
    """Delete old raw file. Returns True on success.

    404 = file not found (already deleted or TTL expired).
    403 = PERMISSION_DENIED (file expired past 48hr TTL, Gemini returns 403 not 404).
    Both are success: the old raw file is gone.
    """
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
            # Gemini returns 403 for expired files (past 48hr TTL) instead of 404
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

    # Build enriched content with identity header
    content = build_enriched_content_with_header(file_path, conn)
    if content is None:
        logger.warning("  SKIP: source file not found on disk: %s", file_path)
        return False

    if dry_run:
        logger.info("  DRY-RUN: would upload %d bytes for %s", len(content.encode("utf-8")), filename)
        return True

    # Write temp file
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
        # Extract new file_id suffix from resource name (e.g. "files/abc123" -> "abc123")
        new_file_id_for_db = new_file_name  # Store full resource name
        conn.execute(
            """UPDATE files
               SET gemini_file_id = ?,
                   gemini_store_doc_id = ?,
                   gemini_state_updated_at = ?,
                   updated_at = ?
               WHERE file_path = ?""",
            (new_file_id_for_db, new_store_doc_id, now, now, file_path),
        )
        conn.commit()
        logger.info("  DB updated: file_id=%s, store_doc_id=%s", new_file_id_for_db, new_store_doc_id)
        return True

    except Exception as exc:
        logger.error("  FAILED: %s: %s", filename, exc)
        return False
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp.name)
        except (FileNotFoundError, OSError):
            pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 16.3 production remediation: re-upload files with identity metadata headers"
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit number of files to process (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without uploading")
    parser.add_argument("--category", choices=["a", "b", "c", "all"], default="all", help="Which category to process")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N files (for resuming)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load manifest
    if not MANIFEST_PATH.exists():
        logger.error("Manifest not found: %s", MANIFEST_PATH)
        sys.exit(1)

    manifest = json.loads(MANIFEST_PATH.read_text())
    logger.info("Loaded manifest: generated_at=%s", manifest["generated_at"])

    # Build file list based on category
    files: list[dict] = []
    if args.category in ("a", "all"):
        files.extend(manifest["category_a"]["files"])
    if args.category in ("b", "all"):
        files.extend(manifest["category_b"]["files"])
    if args.category in ("c", "all"):
        files.extend(manifest.get("category_c", {}).get("files", []))

    # Apply offset
    if args.offset > 0:
        logger.info("Skipping first %d files (offset)", args.offset)
        files = files[args.offset:]

    # Apply limit
    if args.limit > 0:
        files = files[:args.limit]

    logger.info("Processing %d files (category=%s, offset=%d, limit=%d)",
                len(files), args.category, args.offset, args.limit)

    if not files:
        logger.info("No files to process")
        return

    # Initialize API client
    api_key = keyring.get_password("objlib-gemini", "api_key")
    if not api_key:
        logger.error("API key not found in keyring (service=objlib-gemini, key=api_key)")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # Resolve production store
    store_name = resolve_store_name(client)

    # Open DB connection
    conn = sqlite3.connect(str(DB_PATH))

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
        "\n=== REMEDIATION COMPLETE ===\n"
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
