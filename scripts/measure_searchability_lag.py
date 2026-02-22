#!/usr/bin/env python3
"""Measure import-to-searchable lag for Gemini File Search.

Empirically characterizes the gap between "Gemini import API returns success"
and "the file is actually retrievable via targeted semantic search query."

For each of N files (default 20):
  1. Upload raw file to Gemini Files API
  2. Import to store via documents.import_()
  3. Poll documents.get() until visible (T_listed)
  4. Run targeted search query every 5s until file appears in top-10 (T_searchable)
  5. 300s timeout = silent failure (excluded from percentiles)

Outputs per-file table with T_import, T_listed, T_searchable and lag,
plus P50/P95/empirical-max summary.

Usage:
  python scripts/measure_searchability_lag.py
  python scripts/measure_searchability_lag.py --store objectivism-library --count 20
  python scripts/measure_searchability_lag.py --store objectivism-library --db data/library.db --count 20

Exit codes:
  0  Success (measurements complete)
  1  Failure (not enough files, API errors, etc.)
  2  Error (prerequisites not met)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root or scripts/ directory
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

try:
    import keyring
    from google import genai
    from google.genai import types as genai_types
except ImportError as e:
    print(f"ERROR: Missing dependency: {e}", file=sys.stderr)
    print("Run: pip install google-genai keyring", file=sys.stderr)
    sys.exit(2)


# -- Defaults -----------------------------------------------------------------
DEFAULT_STORE = "objectivism-library"
DEFAULT_DB = str(_REPO_ROOT / "data" / "library.db")
DEFAULT_COUNT = 20
SEARCH_MODEL = "gemini-2.5-flash"
SEARCH_TIMEOUT = 300  # 5 minutes = silent failure
LISTING_TIMEOUT = 60  # 1 minute for listing visibility
POLL_INTERVAL = 5  # seconds between search polls
MIN_SUCCESS_COUNT = 15  # abort if fewer than this many succeed


# -- Terminal formatting -------------------------------------------------------
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"


def _ts() -> str:
    """Current UTC time as HH:MM:SS."""
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


# -- Helpers -------------------------------------------------------------------


def resolve_store(client: genai.Client, display_name: str) -> str:
    """Resolve store display name to resource name."""
    for store in client.file_search_stores.list():
        if getattr(store, "display_name", None) == display_name:
            return store.name
    raise ValueError(f"Store '{display_name}' not found")


def build_targeted_query(filename: str, metadata_json: str | None) -> str:
    """Build a targeted query for a specific file.

    Uses filename stem (underscores/hyphens -> spaces) and metadata topic
    if available, to construct a query that should uniquely identify this file.
    """
    # Extract stem: remove extension, clean up
    stem = Path(filename).stem

    # Clean up common patterns
    # Remove episode IDs in brackets like [1000164803415]
    import re
    stem = re.sub(r'\s*\[[\d]+\]\s*', ' ', stem)
    # Replace underscores and hyphens with spaces
    stem = stem.replace('_', ' ').replace('-', ' ')
    # Collapse multiple spaces
    stem = re.sub(r'\s+', ' ', stem).strip()

    # Try to get topic from metadata
    topic = None
    if metadata_json:
        try:
            meta = json.loads(metadata_json)
            topic = meta.get("topic")
            # Skip generic/unparsed topics
            if topic and topic == filename.replace('.txt', ''):
                topic = None
        except (json.JSONDecodeError, TypeError):
            pass

    if topic and topic != stem:
        query = f"{topic}"
    else:
        query = stem

    return query


def select_candidate_files(
    db_path: str, count: int
) -> list[dict]:
    """Select untracked .txt files from DB for measurement.

    Prefers files with metadata topics for better query construction.
    Returns list of dicts with filename, file_path, metadata_json.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # First try files with good metadata (have topics)
    rows = conn.execute(
        """
        SELECT filename, file_path, metadata_json
        FROM files
        WHERE gemini_state = 'untracked'
          AND filename LIKE '%.txt'
          AND json_extract(metadata_json, '$.topic') IS NOT NULL
          AND length(filename) < 100
        ORDER BY RANDOM()
        LIMIT ?
        """,
        (count + 10,),  # get extras in case some fail
    ).fetchall()

    # If not enough, supplement with any untracked .txt files
    if len(rows) < count:
        extra = conn.execute(
            """
            SELECT filename, file_path, metadata_json
            FROM files
            WHERE gemini_state = 'untracked'
              AND filename LIKE '%.txt'
              AND length(filename) < 100
            ORDER BY RANDOM()
            LIMIT ?
            """,
            (count + 10,),
        ).fetchall()
        # Deduplicate
        seen = {r["file_path"] for r in rows}
        for r in extra:
            if r["file_path"] not in seen:
                rows.append(r)
                seen.add(r["file_path"])

    conn.close()

    candidates = []
    for row in rows[:count + 10]:
        candidates.append({
            "filename": row["filename"],
            "file_path": row["file_path"],
            "metadata_json": row["metadata_json"],
            "query": build_targeted_query(row["filename"], row["metadata_json"]),
        })

    return candidates[:count + 5]  # slight surplus for skip-on-failure


def upload_and_import(
    client: genai.Client,
    store_resource_name: str,
    file_path: str,
    display_name: str,
) -> tuple[str, str | None]:
    """Upload file to Files API and import to store.

    Returns (gemini_file_id, gemini_store_doc_id) or raises on failure.
    gemini_file_id is the raw ID (e.g., "abc123"), without "files/" prefix.
    gemini_store_doc_id is the document name suffix after "documents/".
    """
    # Step 1: Upload raw file
    file_ref = client.files.upload(
        file=file_path,
        config={"display_name": display_name.strip()[:512]},
    )
    gemini_file_id = file_ref.name.replace("files/", "")

    # Step 2: Wait for ACTIVE state
    for _ in range(30):
        file_obj = client.files.get(name=file_ref.name)
        if hasattr(file_obj, "state"):
            if file_obj.state.name == "ACTIVE":
                break
            if file_obj.state.name == "FAILED":
                raise RuntimeError(f"File processing failed: {file_ref.name}")
        else:
            break
        time.sleep(1)

    # Step 3: Import to store
    op = client.file_search_stores.import_file(
        file_search_store_name=store_resource_name,
        file_name=file_ref.name,
    )

    # Wait for import operation to complete
    while not getattr(op, "done", True):
        time.sleep(1)
        op = client.operations.get(op)

    # Extract store doc ID from operation result if available
    store_doc_id = None
    result = getattr(op, "result", None)
    if result:
        doc_name = getattr(result, "name", None)
        if doc_name and "/documents/" in doc_name:
            store_doc_id = doc_name.split("/documents/")[-1]

    return gemini_file_id, store_doc_id


def check_listing_visibility(
    client: genai.Client,
    store_resource_name: str,
    gemini_file_id: str,
    timeout: float = LISTING_TIMEOUT,
) -> float | None:
    """Poll until document is visible in store listing.

    Returns seconds until visible, or None if timeout.
    """
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            docs = client.file_search_stores.documents.list(
                parent=store_resource_name
            )
            for doc in docs:
                display_name = getattr(doc, "display_name", "") or ""
                # Document.display_name returns file resource ID (Phase 11 decision [11-01])
                file_id_from_doc = display_name.replace("files/", "")
                if file_id_from_doc == gemini_file_id:
                    return time.monotonic() - start
        except Exception:
            pass
        time.sleep(1)
    return None


def check_search_visibility(
    client: genai.Client,
    store_resource_name: str,
    query: str,
    gemini_file_id: str,
    timeout: float = SEARCH_TIMEOUT,
) -> float | None:
    """Poll search until file appears in top-10 results for targeted query.

    Returns seconds until searchable, or None if timeout (silent failure).
    """
    start = time.monotonic()
    attempts = 0
    while time.monotonic() - start < timeout:
        attempts += 1
        try:
            response = client.models.generate_content(
                model=SEARCH_MODEL,
                contents=query,
                config=genai_types.GenerateContentConfig(
                    tools=[genai_types.Tool(
                        file_search=genai_types.FileSearch(
                            file_search_store_names=[store_resource_name]
                        )
                    )]
                ),
            )

            # Check grounding chunks for our file
            if response.candidates:
                gm = getattr(response.candidates[0], "grounding_metadata", None)
                if gm:
                    chunks = getattr(gm, "grounding_chunks", []) or []
                    for chunk in chunks:
                        rc = getattr(chunk, "retrieved_context", None)
                        if rc:
                            title = getattr(rc, "title", "") or ""
                            # title is file resource ID (e.g., "files/abc123")
                            file_id_from_result = title.replace("files/", "")
                            if file_id_from_result == gemini_file_id:
                                elapsed = time.monotonic() - start
                                return elapsed

        except Exception as e:
            print(f"    Search error (attempt {attempts}): {e}")

        time.sleep(POLL_INTERVAL)

    return None  # Timeout = silent failure


def update_db_state(
    db_path: str,
    file_path: str,
    gemini_file_id: str,
    store_doc_id: str | None,
) -> None:
    """Update DB with gemini_file_id and state=indexed after successful upload."""
    conn = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE files
        SET gemini_file_id = ?,
            gemini_store_doc_id = ?,
            gemini_state = 'indexed',
            gemini_state_updated_at = ?,
            version = version + 1
        WHERE file_path = ?
        """,
        (
            gemini_file_id,
            store_doc_id,
            now,
            file_path,
        ),
    )
    conn.commit()
    conn.close()


def percentile_nearest_rank(sorted_values: list[float], p: float) -> float:
    """Compute percentile using nearest-rank method.

    Args:
        sorted_values: sorted list of values
        p: percentile (0-100)

    Returns:
        The percentile value.
    """
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    rank = math.ceil(p / 100.0 * n) - 1
    rank = max(0, min(rank, n - 1))
    return sorted_values[rank]


# -- Main measurement loop ----------------------------------------------------


def run_measurement(
    client: genai.Client,
    store_resource_name: str,
    db_path: str,
    candidates: list[dict],
    target_count: int,
) -> dict:
    """Run the full measurement for target_count files.

    Returns dict with results, summary stats, and any errors.
    """
    results = []
    errors = []
    silent_failures = []
    measured = 0

    print(f"\n{BOLD}Measuring import-to-searchable lag for {target_count} files...{RESET}\n")

    for i, candidate in enumerate(candidates):
        if measured >= target_count:
            break

        filename = candidate["filename"]
        file_path = candidate["file_path"]
        query = candidate["query"]

        print(f"  [{measured + 1}/{target_count}] {filename}")
        print(f"    Query: {query!r}")

        # Check file exists on disk
        if not Path(file_path).exists():
            print(f"    {YELLOW}SKIP{RESET}: File not found on disk")
            errors.append({"filename": filename, "error": "File not found on disk"})
            continue

        # Step 1: Upload and import
        try:
            t_upload_start = time.monotonic()
            t_import_ts = datetime.now(timezone.utc)

            gemini_file_id, store_doc_id = upload_and_import(
                client, store_resource_name, file_path, filename
            )

            t_import_done = time.monotonic()
            upload_duration = t_import_done - t_upload_start
            print(f"    Upload+import: {upload_duration:.1f}s (file_id={gemini_file_id})")

        except Exception as e:
            print(f"    {RED}FAIL{RESET}: Upload/import error: {e}")
            errors.append({"filename": filename, "error": str(e)})
            continue

        # Step 2: Check listing visibility (T_listed)
        t_listed_start = time.monotonic()
        listing_lag = check_listing_visibility(
            client, store_resource_name, gemini_file_id
        )
        if listing_lag is not None:
            t_listed = t_listed_start + listing_lag
            print(f"    Listed: {listing_lag:.3f}s")
        else:
            t_listed = None
            print(f"    {YELLOW}Listed: TIMEOUT ({LISTING_TIMEOUT}s){RESET}")

        # Step 3: Check search visibility (T_searchable)
        t_search_start = time.monotonic()
        search_lag_from_search_start = check_search_visibility(
            client, store_resource_name, query, gemini_file_id
        )

        # Compute total lag from T_import_done
        if search_lag_from_search_start is not None:
            total_lag = (t_search_start - t_import_done) + search_lag_from_search_start
            t_searchable_ts = t_import_ts.timestamp() + total_lag
            print(f"    {GREEN}Searchable: {total_lag:.1f}s total lag{RESET}")

            # Update DB state
            update_db_state(db_path, file_path, gemini_file_id, store_doc_id)

            results.append({
                "filename": filename,
                "query": query,
                "gemini_file_id": gemini_file_id,
                "store_doc_id": store_doc_id,
                "t_import": t_import_ts.strftime("%H:%M:%S"),
                "t_listed": f"{listing_lag:.3f}s" if listing_lag is not None else "TIMEOUT",
                "t_searchable": f"{total_lag:.1f}s",
                "lag_seconds": total_lag,
            })
            measured += 1
        else:
            print(f"    {RED}SILENT FAILURE: not searchable after {SEARCH_TIMEOUT}s{RESET}")

            # Still update DB state -- file IS imported, just not search-verified
            update_db_state(db_path, file_path, gemini_file_id, store_doc_id)

            silent_failures.append({
                "filename": filename,
                "query": query,
                "gemini_file_id": gemini_file_id,
                "t_import": t_import_ts.strftime("%H:%M:%S"),
                "t_listed": f"{listing_lag:.3f}s" if listing_lag is not None else "TIMEOUT",
            })
            measured += 1  # Count silent failures toward total

        print()

    return {
        "results": results,
        "errors": errors,
        "silent_failures": silent_failures,
        "total_measured": measured,
    }


def print_results(measurement: dict) -> None:
    """Print formatted results table and percentile summary."""
    results = measurement["results"]
    silent_failures = measurement["silent_failures"]
    errors = measurement["errors"]
    total = measurement["total_measured"]

    print(f"\n{BOLD}{'=' * 90}{RESET}")
    print(f"{BOLD}  IMPORT-TO-SEARCHABLE LAG MEASUREMENT RESULTS{RESET}")
    print(f"{BOLD}{'=' * 90}{RESET}\n")

    # Per-file table
    print(f"{'File':<55} {'T_import':<10} {'T_listed':<12} {'T_searchable':<14} {'Lag(s)':<8}")
    print(f"{'-' * 55} {'-' * 10} {'-' * 12} {'-' * 14} {'-' * 8}")

    for r in results:
        fname = r["filename"][:54]
        print(
            f"{fname:<55} {r['t_import']:<10} {r['t_listed']:<12} "
            f"{r['t_searchable']:<14} {r['lag_seconds']:<8.1f}"
        )

    for sf in silent_failures:
        fname = sf["filename"][:54]
        print(
            f"{fname:<55} {sf['t_import']:<10} {sf['t_listed']:<12} "
            f"{'TIMEOUT':<14} {'---':<8}"
        )

    # Summary statistics
    successful_lags = sorted([r["lag_seconds"] for r in results])
    n_success = len(successful_lags)
    n_failures = len(silent_failures)

    print(f"\n{BOLD}Summary:{RESET}")
    print(f"  Files measured: {total} ({n_failures} silent failures)")
    print(f"  Successful measurements: {n_success}")

    if n_success > 0:
        p50 = percentile_nearest_rank(successful_lags, 50)
        p95 = percentile_nearest_rank(successful_lags, 95)
        p_max = max(successful_lags)
        p_min = min(successful_lags)
        mean = sum(successful_lags) / n_success

        print(f"  Lag min:  {p_min:.1f}s")
        print(f"  Lag mean: {mean:.1f}s")
        print(f"  Lag P50:  {p50:.1f}s")
        print(f"  Lag P95:  {p95:.1f}s")
        print(f"  Lag P99/max (n={n_success}, empirical bound): {p_max:.1f}s")
        print(
            f"  Failure rate: {n_failures}/{total} = "
            f"{n_failures / total * 100:.1f}%"
        )
        print(
            f"\n  {DIM}Note: Statistical P99 requires n>=100; "
            f"empirical max from n={n_success} is a conservative upper bound.{RESET}"
        )
    else:
        print(f"  {RED}No successful measurements -- cannot compute percentiles{RESET}")

    if errors:
        print(f"\n  Errors ({len(errors)} files skipped):")
        for e in errors:
            print(f"    - {e['filename']}: {e['error']}")

    print(f"\n{BOLD}{'=' * 90}{RESET}\n")


# -- Entry point ---------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure import-to-searchable lag for Gemini File Search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--store",
        default=DEFAULT_STORE,
        help=f"Store display name (default: {DEFAULT_STORE})",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB,
        help=f"SQLite DB path (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        help=f"Number of files to measure (default: {DEFAULT_COUNT})",
    )
    args = parser.parse_args()

    # Prerequisites
    print(f"\n{BOLD}Import-to-Searchable Lag Measurement{RESET}")
    print(f"  Store:  {args.store}")
    print(f"  DB:     {args.db}")
    print(f"  Count:  {args.count}")
    print(f"  Time:   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

    if not Path(args.db).exists():
        print(f"\nERROR: Database not found at {args.db}", file=sys.stderr)
        return 2

    # API key
    api_key = keyring.get_password("objlib-gemini", "api_key")
    if not api_key:
        print("\nERROR: No API key found in keyring.", file=sys.stderr)
        print("Run: python -m objlib setup", file=sys.stderr)
        return 2

    # Initialize client
    client = genai.Client(api_key=api_key)

    # Resolve store
    print(f"\n  Resolving store '{args.store}'...", end=" ")
    try:
        store_resource_name = resolve_store(client, args.store)
        print(f"OK ({store_resource_name})")
    except ValueError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 2

    # Select candidate files
    print(f"  Selecting {args.count} untracked .txt files...", end=" ")
    candidates = select_candidate_files(args.db, args.count)
    if len(candidates) < args.count:
        print(f"\nERROR: Only {len(candidates)} candidates available, need {args.count}", file=sys.stderr)
        return 2
    print(f"OK ({len(candidates)} candidates)")

    # Run measurement
    measurement = run_measurement(
        client, store_resource_name, args.db, candidates, args.count
    )

    # Check minimum success threshold
    n_success = len(measurement["results"])
    n_total = measurement["total_measured"]
    if n_success < MIN_SUCCESS_COUNT:
        print(
            f"\n{RED}ABORT: Only {n_success} successful measurements "
            f"(minimum {MIN_SUCCESS_COUNT} required){RESET}"
        )
        # Still print what we have
        print_results(measurement)
        return 1

    # Print results
    print_results(measurement)
    return 0


if __name__ == "__main__":
    sys.exit(main())
