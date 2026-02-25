#!/usr/bin/env python3
"""Validate Strategy 4 (S4) on the 12 known structural failures from Phase 16.4-03.

Tests a cascade of query strategies until each file is found in top-5 or all
strategies are exhausted.

Cascade order:
  S4a: top-3 rarest aspects (by corpus frequency), no preamble
  S4b: top-5 rarest aspects (catches files where 4th/5th aspect is discriminating)
  S4c: each individual aspect tried alone (rarest-first)
  S4d: for Office Hour files: each individual aspect + "{course} Office Hour" suffix

Usage:
  python scripts/validate_s4.py --store objectivism-library --db data/library.db

Exit codes:
  0  All 12 files PASS (found in top-5)
  1  One or more files FAIL
  2  Error (API unavailable, DB missing, etc.)
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path, PurePosixPath

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

try:
    import keyring
    from google import genai
    from google.genai import types as genai_types
except ImportError as e:
    print(f"ERROR: Missing dependency: {e}", file=sys.stderr)
    sys.exit(2)

SEARCH_MODEL = "gemini-2.5-flash"
TOP_K = 5

# The 12 known structural failures from Phase 16.4-03
KNOWN_FAILURES = [
    "ITOE - Class 02-01.txt",
    "ITOE Advanced Topics - Class 09-02.txt",
    "ITOE Advanced Topics - Class 10-02.txt",
    "ITOE Advanced Topics - Class 13-02 - Office Hour.txt",
    "ITOE Advanced Topics - Class 14-01 - Office Hour.txt",
    "ITOE Advanced Topics - Class 14-02 - Office Hour.txt",
    "ITOE - Class 10-01 - Office Hour.txt",
    "Objectivist Logic - Class 03-01.txt",
    "Objectivist Logic - Class 15-02 - Open Office Hour.txt",
    "MOTM_2021-05-16_History-of-the-Objectivist-movement-a-personal-account-part.txt",
    "Ayn Rand - Atlas Shrugged (1971).txt",
    "existence doesn't mean physical existence.txt",
]


def build_corpus_freq_map(conn: sqlite3.Connection) -> dict[str, int]:
    """Build aspect corpus frequency map from all files. O(n) DB query."""
    freq: dict[str, int] = {}
    rows = conn.execute(
        "SELECT metadata_json FROM file_metadata_ai WHERE is_current = 1"
    ).fetchall()
    for (mj,) in rows:
        if not mj:
            continue
        try:
            for aspect in json.loads(mj).get("topic_aspects", []):
                freq[aspect] = freq.get(aspect, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass
    return freq


def run_query(
    client: genai.Client,
    store_resource_name: str,
    query: str,
    expected_prefix: str,
) -> tuple[bool, int]:
    """Run a query and return (found, rank). Rank is 1-based, -1 if not found."""
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

    if not response.candidates:
        return False, -1

    gm = getattr(response.candidates[0], "grounding_metadata", None)
    if not gm:
        return False, -1

    chunks = getattr(gm, "grounding_chunks", []) or []
    for i, chunk in enumerate(chunks[:TOP_K]):
        rc = getattr(chunk, "retrieved_context", None)
        if not rc:
            continue
        title = getattr(rc, "title", "") or ""
        if title == expected_prefix:
            return True, i + 1
    return False, -1


def try_queries(
    client: genai.Client,
    store_resource_name: str,
    queries: list[tuple[str, str]],
    expected_prefix: str,
) -> tuple[bool, int, str, str]:
    """
    Try a list of (strategy_label, query) pairs until one finds the file.
    Returns (found, rank, strategy_label, query).
    """
    for label, q in queries:
        found, rank = run_query(client, store_resource_name, q, expected_prefix)
        if found:
            return True, rank, label, q
    return False, -1, "", ""


def build_query_cascade(
    aspects: list[str],
    corpus_freq: dict[str, int],
    course: str,
    is_oh: bool,
) -> list[tuple[str, str]]:
    """
    Build the full cascade of queries to try for a file.
    Returns list of (strategy_label, query_string).
    """
    sorted_aspects = sorted(aspects, key=lambda a: corpus_freq.get(a, 0))
    cleaned = [re.sub(r"[*_`]", "", a) for a in sorted_aspects]

    queries: list[tuple[str, str]] = []

    # S4a: top-3 rarest aspects concatenated
    if len(cleaned) >= 1:
        q_s4a = " ".join(cleaned[:3])
        queries.append(("S4a(top-3)", q_s4a))

    # S4b: top-5 rarest aspects concatenated
    if len(cleaned) >= 4:
        q_s4b = " ".join(cleaned[:5])
        queries.append(("S4b(top-5)", q_s4b))

    # S4c: each individual aspect tried alone (rarest first, up to 10)
    for i, c in enumerate(cleaned[:10]):
        queries.append((f"S4c(aspect[{i+1}])", c))

    # S4d: for Office Hour files, each individual aspect + "{course} Office Hour"
    if is_oh:
        oh_suffix = f"{course} Office Hour"
        for i, c in enumerate(cleaned[:10]):
            q_oh = f"{c} {oh_suffix}"
            queries.append((f"S4d(aspect[{i+1}]+OH)", q_oh))

    return queries


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate S4 strategy on the 12 known structural failures from Phase 16.4-03"
    )
    parser.add_argument("--store", required=True, help="Gemini File Search store display name")
    parser.add_argument("--db", required=True, help="Path to library.db")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"ERROR: Database not found at {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(args.db)

    # Build corpus frequency map
    print("Building corpus aspect frequency map...")
    corpus_freq = build_corpus_freq_map(conn)
    print(f"  Built frequency map for {len(corpus_freq)} unique aspects\n")

    # Initialize Gemini client
    api_key = keyring.get_password("objlib-gemini", "api_key")
    if not api_key:
        print("ERROR: No API key in keyring (service=objlib-gemini, username=api_key)", file=sys.stderr)
        conn.close()
        return 2

    client = genai.Client(api_key=api_key)

    # Resolve store
    store_resource_name = None
    for store in client.file_search_stores.list():
        if getattr(store, "display_name", None) == args.store:
            store_resource_name = store.name
            break

    if not store_resource_name:
        print(f"ERROR: Store '{args.store}' not found", file=sys.stderr)
        conn.close()
        return 2

    print(f"Store resolved: {store_resource_name}\n")
    print(f"Validating S4 cascade on {len(KNOWN_FAILURES)} known structural failures...\n")

    results = []

    for fname in KNOWN_FAILURES:
        row = conn.execute(
            """SELECT f.file_path, f.gemini_store_doc_id, fma.metadata_json
               FROM files f
               JOIN file_metadata_ai fma ON fma.file_path = f.file_path AND fma.is_current = 1
               WHERE f.filename = ?
               ORDER BY f.file_path
               LIMIT 1""",
            (fname,),
        ).fetchone()

        if not row:
            print(f"MISSING: {fname}")
            results.append({"fname": fname, "result": "MISSING_FROM_DB"})
            continue

        file_path, store_doc_id, metadata_json = row
        expected_prefix = store_doc_id.split("-")[0] if store_doc_id else ""
        course = PurePosixPath(file_path).parent.name
        is_oh = "Office Hour" in fname

        # Get aspects
        aspects: list[str] = []
        try:
            aspects = json.loads(metadata_json).get("topic_aspects", []) or []
        except Exception:
            pass

        if not aspects:
            print(f"NO ASPECTS: {fname}")
            results.append({"fname": fname, "result": "NO_ASPECTS"})
            continue

        # Build cascade and try until found
        cascade = build_query_cascade(aspects, corpus_freq, course, is_oh)
        found, rank, strategy_label, winning_query = try_queries(
            client, store_resource_name, cascade, expected_prefix
        )

        if found:
            print(f"PASS ({strategy_label} rank {rank}): {fname}")
            print(f"  Query: {winning_query[:100]}")
            results.append({
                "fname": fname,
                "result": "PASS",
                "strategy": strategy_label,
                "rank": rank,
                "query": winning_query,
            })
        else:
            print(f"FAIL (all {len(cascade)} strategies exhausted): {fname}")
            for label, q in cascade[:5]:
                print(f"  Tried [{label}]: {q[:80]}")
            results.append({"fname": fname, "result": "FAIL", "cascade_tried": len(cascade)})

    conn.close()

    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r["result"] == "PASS")
    failed = sum(1 for r in results if r["result"] == "FAIL")
    errors = sum(1 for r in results if r["result"] not in ("PASS", "FAIL"))

    print(f"SUMMARY: {passed}/{len(results)} PASS  |  {failed} FAIL  |  {errors} errors")

    # Show strategy breakdown for passes
    if passed:
        from collections import Counter
        strategies = Counter(r["strategy"] for r in results if r.get("result") == "PASS")
        for strat, count in sorted(strategies.items()):
            print(f"  {strat}: {count} files")

    if failed == 0 and errors == 0:
        print("\nALL 12 PASS -- S4 cascade validated for Phase 16.5-01 gate")
        return 0
    else:
        print("\nVALIDATION FAILED -- review failures above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
