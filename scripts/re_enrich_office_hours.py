#!/usr/bin/env python3
"""Targeted re-upload of 60 Office Hour files with enriched identity headers.

Sources current gemini_store_doc_id from DB (not stale manifest).
Run AFTER batch-extract has populated file_primary_topics for these files.

Usage:
    python scripts/re_enrich_office_hours.py [--dry-run] [-v]

After completion, run:
    python -m objlib store-sync --store objectivism-library --no-dry-run --yes
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import sqlite3
import sys
import time
from pathlib import Path

# Add project root to path for objlib imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import keyring
from google import genai

# ---------------------------------------------------------------------------
# Import helpers from re_enrich_retrieval.py without running main()
# ---------------------------------------------------------------------------

_script = Path(__file__).resolve().parent / "re_enrich_retrieval.py"
_spec = importlib.util.spec_from_file_location("re_enrich_retrieval", _script)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

resolve_store_name = _mod.resolve_store_name
build_enriched_content_with_header = _mod.build_enriched_content_with_header
upload_file_with_poll = _mod.upload_file_with_poll
import_to_store_with_poll = _mod.import_to_store_with_poll
delete_old_store_doc = _mod.delete_old_store_doc
delete_old_raw_file = _mod.delete_old_raw_file
process_file = _mod.process_file

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "library.db"
SLEEP_BETWEEN_FILES = 2
SLEEP_BETWEEN_BATCHES = 5
BATCH_SIZE = 10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_office_hour_files(conn: sqlite3.Connection) -> list[dict]:
    """Get all indexed Office Hour files with current store doc IDs from DB."""
    rows = conn.execute(
        """SELECT file_path, filename, gemini_store_doc_id, gemini_file_id
           FROM files
           WHERE gemini_state = 'indexed'
             AND gemini_store_doc_id IS NOT NULL
             AND (filename LIKE '% - Office Hour%' OR filename LIKE '% - Office Hours%')
           ORDER BY filename"""
    ).fetchall()
    return [
        {
            "file_path": r[0],
            "filename": r[1],
            "gemini_store_doc_id": r[2],
            "gemini_file_id": r[3],
        }
        for r in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-upload Office Hour files with enriched identity headers"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    conn = sqlite3.connect(str(DB_PATH))
    files = get_office_hour_files(conn)
    logger.info("Found %d indexed Office Hour files to re-upload", len(files))

    if not files:
        logger.info("Nothing to do.")
        conn.close()
        return

    api_key = keyring.get_password("objlib-gemini", "api_key")
    if not api_key:
        logger.error("API key not found in keyring (service=objlib-gemini, key=api_key)")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    store_name = resolve_store_name(client)

    succeeded = 0
    failed = 0
    failed_files = []

    for idx, file_info in enumerate(files, 1):
        ok = process_file(client, store_name, conn, file_info, idx, len(files), args.dry_run)
        if ok:
            succeeded += 1
        else:
            failed += 1
            failed_files.append(file_info["filename"])

        # Rate limiting
        if idx % BATCH_SIZE == 0 and idx < len(files):
            logger.info("Batch pause (%ds)...", SLEEP_BETWEEN_BATCHES)
            time.sleep(SLEEP_BETWEEN_BATCHES)
        elif idx < len(files):
            time.sleep(SLEEP_BETWEEN_FILES)

    conn.close()
    logger.info("Done: %d succeeded, %d failed", succeeded, failed)
    if failed_files:
        logger.warning("Failed files:")
        for f in failed_files:
            logger.warning("  %s", f)
    if not args.dry_run:
        logger.info("Next: run store-sync --no-dry-run --yes to clear orphaned store docs")


if __name__ == "__main__":
    main()
