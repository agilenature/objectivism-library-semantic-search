#!/usr/bin/env python3
"""CRAD Pilot: Run the 3-pass CRAD algorithm on 3 known-failing pilot files.

Phase 16.6-01 — Validates that the CRAD algorithm generates discrimination
phrases achieving rank <= 5 in Gemini File Search for all 3 pilot files.

Pilot files:
  1. ITOE Advanced Topics - Class 14-01 - Office Hour.txt
     Known S4a query: "Zeno's arrow paradox" -> rank 1
  2. ITOE Advanced Topics - Class 13-02 - Office Hour.txt
     Known S4a query: "measurements omitted concept formation..." -> rank 4
  3. Objectivist Logic - Class 14-02 - Open Office Hour.txt
     Known S4c query: "Aristotle's logic" -> rank 2

Requirements:
  - ANTHROPIC_API_KEY env var (for Pass 2 Claude call)
  - Gemini API key in keyring (objlib-gemini service)
  - data/library.db with indexed files and AI metadata

Usage:
  export ANTHROPIC_API_KEY=sk-ant-...
  python scripts/crad_pilot.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Project path setup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from crad_algorithm import (
    build_corpus_freq_map,
    build_discrimination_phrase,
    build_genus_profile,
    create_crad_tables,
    get_claude_discrimination_phrase,
    store_discrimination_phrase,
    store_genus_profile,
    validate_phrase,
)

# -- Constants ----------------------------------------------------------------

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "library.db"

PILOT_FILES = [
    {
        "filename": "ITOE Advanced Topics - Class 14-01 - Office Hour.txt",
        "series_parent": "ITOE Advanced Topics",
        "known_query": "Zeno's arrow paradox",
        "known_rank": 1,
    },
    {
        "filename": "ITOE Advanced Topics - Class 13-02 - Office Hour.txt",
        "series_parent": "ITOE Advanced Topics",
        "known_query": "measurements omitted concept formation generic brand",
        "known_rank": 4,
    },
    {
        "filename": "Objectivist Logic - Class 14-02 - Open Office Hour.txt",
        "series_parent": "Objectivist Logic",
        "known_query": "Aristotle's logic",
        "known_rank": 2,
    },
]

VALIDATION_RUNS = 3
MAX_ACCEPTABLE_RANK = 5


# -- Gemini Client Setup ------------------------------------------------------

def setup_gemini():
    """Initialize Gemini client and resolve store resource name."""
    import keyring
    from google import genai

    api_key = keyring.get_password("objlib-gemini", "api_key")
    if not api_key:
        print("ERROR: No Gemini API key found in keyring.", file=sys.stderr)
        sys.exit(2)

    client = genai.Client(api_key=api_key)

    # Get store resource name from DB
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT value FROM library_config WHERE key = 'gemini_store_resource_name'"
    ).fetchone()
    conn.close()

    if row:
        store_resource_name = row[0]
    else:
        # Fallback: resolve from API
        for store in client.file_search_stores.list():
            if getattr(store, "display_name", None) == "objectivism-library":
                store_resource_name = store.name
                break
        else:
            print("ERROR: Store 'objectivism-library' not found.", file=sys.stderr)
            sys.exit(2)

    return client, store_resource_name


# -- Main Pilot Runner --------------------------------------------------------

def run_pilot():
    """Run the full CRAD pilot on 3 files."""
    started_at = datetime.now(timezone.utc).isoformat()
    print("=" * 70)
    print("  CRAD PILOT — Phase 16.6-01")
    print("=" * 70)
    print(f"  Time: {started_at}")
    print(f"  DB:   {DB_PATH}")
    print(f"  Files: {len(PILOT_FILES)} pilot files")
    print(f"  Validation runs: {VALIDATION_RUNS} per file")
    print(f"  Max acceptable rank: {MAX_ACCEPTABLE_RANK}")
    print("=" * 70)

    # Check Anthropic API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nERROR: ANTHROPIC_API_KEY not set in environment.", file=sys.stderr)
        print("  Set it with: export ANTHROPIC_API_KEY=sk-ant-...", file=sys.stderr)
        sys.exit(2)

    # Setup
    conn = sqlite3.connect(str(DB_PATH))
    create_crad_tables(conn)

    # Build corpus frequency map (used by Pass 2)
    print("\n[1/4] Building corpus frequency map...")
    corpus_freq = build_corpus_freq_map(conn)
    print(f"  Total unique aspects in corpus: {len(corpus_freq)}")

    # Setup Gemini for validation
    print("\n[2/4] Connecting to Gemini File Search...")
    gemini_client, store_resource_name = setup_gemini()
    print(f"  Store: {store_resource_name}")

    # Process each pilot file
    results = []
    genus_cache: dict[str, dict] = {}

    print(f"\n[3/4] Processing {len(PILOT_FILES)} pilot files...")
    for i, pilot in enumerate(PILOT_FILES, 1):
        filename = pilot["filename"]
        series_parent = pilot["series_parent"]
        print(f"\n{'—' * 60}")
        print(f"  Pilot {i}/{len(PILOT_FILES)}: {filename}")
        print(f"  Series: {series_parent}")
        print(f"{'—' * 60}")

        # Get file info from DB
        row = conn.execute("""
            SELECT f.filename, f.gemini_store_doc_id, fma.metadata_json
            FROM files f
            JOIN file_metadata_ai fma ON fma.file_path = f.file_path AND fma.is_current = 1
            WHERE f.filename = ? AND f.gemini_state = 'indexed'
        """, (filename,)).fetchone()

        if not row:
            print(f"  ERROR: File not found in DB (indexed with metadata)")
            results.append({"filename": filename, "error": "not found in DB"})
            continue

        _, store_doc_id, metadata_json = row
        meta = json.loads(metadata_json)
        target_aspects = meta.get("topic_aspects", [])
        print(f"  Aspects ({len(target_aspects)}): {target_aspects}")
        print(f"  Store doc ID: {store_doc_id}")

        # Pass 1: Build genus profile (cached per series)
        if series_parent not in genus_cache:
            print(f"\n  Pass 1: Building genus profile for '{series_parent}'...")
            genus = build_genus_profile(conn, series_parent)
            genus_cache[series_parent] = genus
            print(f"    File count: {genus['file_count']}")
            print(f"    Shared aspects (genus): {len(genus['shared_aspects'])}")
            print(f"    Total unique aspects: {len(genus['aspect_frequency_map'])}")
            if genus["shared_aspects"]:
                print(f"    Genus: {genus['shared_aspects'][:5]}...")
            else:
                print("    No genus aspects (0 reach 80% threshold)")
            # Store genus profile in DB
            store_genus_profile(conn, genus)
        else:
            genus = genus_cache[series_parent]
            print(f"\n  Pass 1: Using cached genus profile for '{series_parent}'")

        # Pass 2: Claude discrimination
        print(f"\n  Pass 2: Calling Claude ({os.environ.get('CLAUDE_MODEL_OVERRIDE', 'claude-haiku-4-5-20251001')})...")
        try:
            claude_result = get_claude_discrimination_phrase(
                target_filename=filename,
                target_aspects=target_aspects,
                series_name=series_parent,
                series_aspects_by_file=genus["files_aspects"],
                series_freq_map=genus["aspect_frequency_map"],
                corpus_freq_map=corpus_freq,
            )
            print(f"    Discrimination phrase: \"{claude_result['discrimination_phrase']}\"")
            print(f"    Aspects used: {claude_result['aspects_used']}")
            print(f"    Reasoning: {claude_result['reasoning']}")
            print(f"    Model: {claude_result['model']}")
        except Exception as e:
            print(f"  ERROR in Pass 2: {e}")
            results.append({"filename": filename, "error": str(e)})
            continue

        # Pass 3: Essentialization (clean up Claude's output)
        print(f"\n  Pass 3: Essentialization...")
        phrase_input = {
            "filename": filename,
            "series_name": series_parent,
            "aspects_used": claude_result["aspects_used"],
        }
        phrase_result = build_discrimination_phrase(phrase_input)
        print(f"    Final phrase: \"{phrase_result['phrase']}\"")
        print(f"    Word count: {phrase_result['word_count']}")
        print(f"    Aspects used: {phrase_result['aspects_used']}")

        # Validation: Query Gemini 3 times
        print(f"\n  Validation: Querying Gemini {VALIDATION_RUNS} times...")
        ranks = []
        for run in range(1, VALIDATION_RUNS + 1):
            rank = validate_phrase(
                client=gemini_client,
                store_resource_name=store_resource_name,
                phrase=phrase_result["phrase"],
                target_store_doc_id=store_doc_id,
            )
            rank_str = str(rank) if rank is not None else "NOT FOUND"
            print(f"    Run {run}: rank = {rank_str}")
            ranks.append(rank)
            if run < VALIDATION_RUNS:
                time.sleep(2)  # Rate limiting between Gemini queries

        # Determine pass/fail
        all_found = all(r is not None for r in ranks)
        all_within_threshold = all(r is not None and r <= MAX_ACCEPTABLE_RANK for r in ranks)
        best_rank = min((r for r in ranks if r is not None), default=None)

        status = "PASS" if all_within_threshold else "FAIL"
        validation_status = "validated" if status == "PASS" else "failed"

        print(f"\n  Result: {status}")
        print(f"    Ranks: {ranks}")
        print(f"    Best rank: {best_rank}")
        print(f"    Known query: \"{pilot['known_query']}\" (rank {pilot['known_rank']})")
        print(f"    CRAD phrase: \"{phrase_result['phrase']}\"")

        result = {
            "filename": filename,
            "series_name": series_parent,
            "phrase": phrase_result["phrase"],
            "word_count": phrase_result["word_count"],
            "aspects_used": phrase_result["aspects_used"],
            "claude_reasoning": claude_result["reasoning"],
            "claude_model": claude_result["model"],
            "validation_ranks": ranks,
            "best_rank": best_rank,
            "known_query": pilot["known_query"],
            "known_rank": pilot["known_rank"],
            "status": status,
            "validation_status": validation_status,
        }
        results.append(result)

        # Store in DB (Task 7)
        phrase_result["validation_rank"] = best_rank
        phrase_result["validation_status"] = validation_status
        store_discrimination_phrase(conn, phrase_result)

    conn.close()

    # Summary
    completed_at = datetime.now(timezone.utc).isoformat()
    print("\n" + "=" * 70)
    print("  CRAD PILOT RESULTS")
    print("=" * 70)

    passes = sum(1 for r in results if r.get("status") == "PASS")
    fails = sum(1 for r in results if r.get("status") == "FAIL")
    errors = sum(1 for r in results if "error" in r)

    for r in results:
        if "error" in r:
            print(f"  ERROR: {r['filename']} — {r['error']}")
        else:
            print(f"  {r['status']}: {r['filename']}")
            print(f"         phrase: \"{r['phrase']}\" ({r['word_count']} words)")
            print(f"         ranks: {r['validation_ranks']} (best: {r['best_rank']})")
            print(f"         known: \"{r['known_query']}\" (rank {r['known_rank']})")

    gate = "PASS" if passes == len(PILOT_FILES) and fails == 0 and errors == 0 else "FAIL"
    print(f"\n  GATE: {gate} ({passes} pass, {fails} fail, {errors} error)")
    print(f"  Started: {started_at}")
    print(f"  Completed: {completed_at}")
    print("=" * 70)

    # Write results to JSON for programmatic consumption
    results_path = Path(__file__).resolve().parent.parent / ".planning" / "phases" / "16.6-crad" / "16.6-01-pilot-results.json"
    with open(results_path, "w") as f:
        json.dump({
            "metadata": {
                "started_at": started_at,
                "completed_at": completed_at,
                "gate": gate,
                "passes": passes,
                "fails": fails,
                "errors": errors,
                "pilot_count": len(PILOT_FILES),
                "validation_runs": VALIDATION_RUNS,
                "max_acceptable_rank": MAX_ACCEPTABLE_RANK,
            },
            "results": results,
        }, f, indent=2)
    print(f"\n  Results JSON: {results_path}")

    return 0 if gate == "PASS" else 1


if __name__ == "__main__":
    sys.exit(run_pilot())
