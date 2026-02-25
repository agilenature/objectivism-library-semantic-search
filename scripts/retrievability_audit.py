#!/usr/bin/env python3
"""Comprehensive retrievability audit for Gemini File Search store.

Tests every indexed file's retrievability across 3 query strategies, producing
per-series hit rate tables and identifying the minimum viable query strategy.

All 1,749 indexed files are tested (no exclusions). Results are saved to a
resumable JSON progress file keyed by {file_path}_{strategy_num}.

Three query strategies (per Phase 16.4 locked decision #4):
  1. Stem-only: "What is '{stem}' about?"
  2. Stem + aspects: stem query enriched with top-3 topic_aspects from AI metadata
  3. Topics + course: course directory name + top-3 primary_topics

Usage:
  python scripts/retrievability_audit.py --store objectivism-library --db data/library.db --strategy all
  python scripts/retrievability_audit.py --store objectivism-library --db data/library.db --strategy 1
  python scripts/retrievability_audit.py --store objectivism-library --db data/library.db --strategy 2 --concurrency 5
  python scripts/retrievability_audit.py --store objectivism-library --db data/library.db --strategy 3 --verbose

Exit codes:
  0  All strategies completed successfully
  1  Some files failed (normal -- results still saved)
  2  Error (API unavailable, DB missing, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

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

try:
    from rich.console import Console
    from rich.table import Table

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# -- Constants ----------------------------------------------------------------
SEARCH_MODEL = "gemini-2.5-flash"
TOP_K = 5  # Top-5 threshold per locked decision #4
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0  # seconds


# -- Series detection ---------------------------------------------------------

def detect_series(file_path: str) -> str:
    """Classify a file into its series based on path patterns."""
    name = PurePosixPath(file_path).name
    if "/ITOE Advanced Topics/" in file_path and "Office Hour" in name:
        return "ITOE AT OH"
    elif "/ITOE Advanced Topics/" in file_path:
        return "ITOE AT"
    elif "/ITOE/" in file_path and "Office Hour" in name:
        return "ITOE OH"
    elif "/ITOE/" in file_path:
        return "ITOE"
    elif "/Objectivist Logic/" in file_path:
        return "OL"
    elif "/MOTM/" in file_path:
        return "MOTM"
    elif "Episode" in name:
        return "Episodes"
    elif "/Books/" in file_path:
        return "Books"
    else:
        return "Other"


# -- Corpus frequency map builder ---------------------------------------------


def build_corpus_freq_map(db_path: str) -> dict[str, int]:
    """Build aspect corpus frequency map from all files. O(n) DB query."""
    conn = sqlite3.connect(db_path)
    freq: dict[str, int] = {}
    rows = conn.execute(
        "SELECT metadata_json FROM file_metadata_ai WHERE is_current = 1"
    ).fetchall()
    conn.close()
    for (mj,) in rows:
        if not mj:
            continue
        try:
            for aspect in json.loads(mj).get("topic_aspects", []):
                freq[aspect] = freq.get(aspect, 0) + 1
        except (json.JSONDecodeError, TypeError):
            pass
    return freq


# -- Auditor class ------------------------------------------------------------


class RetrievabilityAuditor:
    """Tests every indexed file's retrievability across query strategies."""

    def __init__(
        self,
        store: str,
        db: str,
        strategy: str,
        progress_file: str,
        concurrency: int = 10,
        verbose: bool = False,
    ) -> None:
        self.store_display_name = store
        self.db_path = db
        self.strategy_arg = strategy  # "1", "2", "3", or "all"
        self.progress_file = progress_file
        self.concurrency = concurrency
        self.verbose = verbose

        # Resolve strategies to run
        if strategy == "all":
            self.strategies = [1, 2, 3]
        else:
            self.strategies = [int(strategy)]

        # Initialize API client
        api_key = keyring.get_password("objlib-gemini", "api_key")
        if not api_key:
            print("ERROR: No API key in keyring (service=objlib-gemini, username=api_key)", file=sys.stderr)
            sys.exit(2)
        self.client = genai.Client(api_key=api_key)
        self.store_resource_name: str | None = None

        # Strategy 4/5: corpus aspect frequency map (built once in run())
        self.corpus_freq: dict[str, int] = {}

        # Stats
        self._api_calls = 0
        self._errors = 0

    def _log(self, msg: str) -> None:
        if self.verbose:
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            print(f"  [{ts}] {msg}")

    def _resolve_store(self) -> bool:
        """Resolve store display name to resource name."""
        try:
            for store in self.client.file_search_stores.list():
                dn = getattr(store, "display_name", None)
                if dn == self.store_display_name:
                    self.store_resource_name = store.name
                    self._log(f"Resolved store: {self.store_display_name} -> {store.name}")
                    return True
            print(f"ERROR: Store '{self.store_display_name}' not found.", file=sys.stderr)
            return False
        except Exception as e:
            print(f"ERROR: API error listing stores: {e}", file=sys.stderr)
            return False

    def load_files(self) -> list[dict]:
        """Load all indexed files from DB. No exclusions."""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT file_path, filename, gemini_store_doc_id, gemini_file_id
               FROM files
               WHERE gemini_state = 'indexed'
                 AND gemini_store_doc_id IS NOT NULL
               ORDER BY file_path"""
        ).fetchall()
        conn.close()

        files = []
        for file_path, filename, store_doc_id, gemini_file_id in rows:
            files.append({
                "file_path": file_path,
                "filename": filename,
                "store_doc_id": store_doc_id,
                "gemini_file_id": gemini_file_id,
                "series": detect_series(file_path),
            })

        print(f"Loaded {len(files)} indexed files from DB")
        return files

    def load_progress(self) -> dict:
        """Load existing progress file or create new one."""
        try:
            with open(self.progress_file, "r") as f:
                data = json.load(f)
            existing = len(data.get("results", {}))
            print(f"Loaded progress file: {existing} existing results")
            return data
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "metadata": {
                    "store": self.store_display_name,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "total_files": 0,
                },
                "results": {},
            }

    def save_progress(self, progress: dict) -> None:
        """Save progress to JSON file (atomic write via temp file)."""
        tmp_path = self.progress_file + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(progress, f, indent=2, default=str)
        Path(tmp_path).replace(self.progress_file)

    def build_query(self, file_path: str, filename: str, strategy: int, conn: sqlite3.Connection) -> str:
        """Build query string for given strategy."""
        stem = PurePosixPath(filename).stem

        if strategy == 1:
            return f"What is '{stem}' about?"

        elif strategy == 2:
            # Stem + top-3 topic_aspects from AI metadata
            ai_row = conn.execute(
                "SELECT metadata_json FROM file_metadata_ai WHERE file_path = ? AND is_current = 1",
                (file_path,),
            ).fetchone()
            aspects: list[str] = []
            if ai_row and ai_row[0]:
                try:
                    meta = json.loads(ai_row[0])
                    aspects = (meta.get("topic_aspects") or [])[:3]
                except Exception:
                    pass
            aspect_str = " ".join(str(a) for a in aspects)
            if aspect_str:
                return f"What is '{stem}' about? Topics: {aspect_str}"
            else:
                # Degrade to Strategy 1 if no aspects
                return f"What is '{stem}' about?"

        elif strategy == 3:
            # Course + top-3 primary_topics
            course = PurePosixPath(file_path).parent.name
            topic_rows = conn.execute(
                "SELECT topic_tag FROM file_primary_topics WHERE file_path = ? LIMIT 3",
                (file_path,),
            ).fetchall()
            topic_str = " ".join(r[0] for r in topic_rows)
            if topic_str:
                return f"{course}: {topic_str}"
            else:
                # Degrade to course + stem if no primary_topics
                return f"{course}: {stem}"

        elif strategy == 4:
            # S4a: top-3 rarest aspects (by corpus frequency), no preamble, markdown stripped
            ai_row = conn.execute(
                "SELECT metadata_json FROM file_metadata_ai WHERE file_path = ? AND is_current = 1",
                (file_path,),
            ).fetchone()
            aspects: list[str] = []
            if ai_row and ai_row[0]:
                try:
                    aspects = json.loads(ai_row[0]).get("topic_aspects", []) or []
                except Exception:
                    pass
            sorted_aspects = sorted(aspects, key=lambda a: self.corpus_freq.get(a, 0))
            cleaned = [re.sub(r"[*_`]", "", a) for a in sorted_aspects[:3]]
            return " ".join(cleaned) if cleaned else f"What is '{stem}' about?"

        elif strategy == 5:
            # S4b: individual aspect trials (sequence handled in check_file)
            # This returns the first individual aspect as a representative query string.
            # check_file() calls _build_s4b_sequence() to get the full trial sequence.
            ai_row = conn.execute(
                "SELECT metadata_json FROM file_metadata_ai WHERE file_path = ? AND is_current = 1",
                (file_path,),
            ).fetchone()
            aspects_5: list[str] = []
            if ai_row and ai_row[0]:
                try:
                    aspects_5 = json.loads(ai_row[0]).get("topic_aspects", []) or []
                except Exception:
                    pass
            sorted_aspects_5 = sorted(aspects_5, key=lambda a: self.corpus_freq.get(a, 0))
            if sorted_aspects_5:
                return re.sub(r"[*_`]", "", sorted_aspects_5[0])
            return f"What is '{stem}' about?"

        else:
            raise ValueError(f"Unknown strategy: {strategy}")

    def _build_s4b_sequence(
        self,
        file_path: str,
        filename: str,
        conn: sqlite3.Connection,
    ) -> list[str]:
        """Build sequence of queries to try for S4b (individual aspect cascade).

        Tries each individual aspect alone (rarest first, up to 12).
        For Office Hour files, also tries each aspect + "{course} Office Hour".
        """
        ai_row = conn.execute(
            "SELECT metadata_json FROM file_metadata_ai WHERE file_path = ? AND is_current = 1",
            (file_path,),
        ).fetchone()
        aspects: list[str] = []
        if ai_row and ai_row[0]:
            try:
                aspects = json.loads(ai_row[0]).get("topic_aspects", []) or []
            except Exception:
                pass

        sorted_aspects = sorted(aspects, key=lambda a: self.corpus_freq.get(a, 0))
        cleaned = [re.sub(r"[*_`]", "", a) for a in sorted_aspects[:12]]

        queries: list[str] = list(cleaned)

        if "Office Hour" in filename:
            course = PurePosixPath(file_path).parent.name
            for c in cleaned:
                queries.append(f"{c} {course} Office Hour")

        return queries

    async def _run_single_query(
        self,
        query: str,
        file_path: str,
        filename: str,
        strategy: int,
        expected_file_id: str,
        store_doc_prefix: str,
        semaphore: asyncio.Semaphore,
        file_info: dict,
    ) -> dict:
        """Execute one query with retries and return a result dict."""
        async with semaphore:
            backoff = INITIAL_BACKOFF
            last_error = None
            response = None

            for attempt in range(MAX_RETRIES):
                try:
                    self._api_calls += 1
                    q = query  # capture for lambda
                    response = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda q=q: self.client.models.generate_content(
                            model=SEARCH_MODEL,
                            contents=q,
                            config=genai_types.GenerateContentConfig(
                                tools=[genai_types.Tool(
                                    file_search=genai_types.FileSearch(
                                        file_search_store_names=[self.store_resource_name]
                                    )
                                )]
                            ),
                        ),
                    )
                    break  # Success
                except Exception as e:
                    last_error = e
                    error_str = str(e)
                    if "429" in error_str or "5" in error_str[:1] and any(
                        c in error_str for c in ["500", "502", "503", "504"]
                    ):
                        self._log(f"Retry {attempt + 1}/{MAX_RETRIES} for {filename} (strategy {strategy}): {error_str[:80]}")
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    else:
                        self._errors += 1
                        return {
                            "filename": filename,
                            "file_path": file_path,
                            "strategy": strategy,
                            "found": False,
                            "rank": -1,
                            "query": query,
                            "top_5_ids": [],
                            "error": str(e)[:200],
                            "series": file_info["series"],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
            else:
                self._errors += 1
                return {
                    "filename": filename,
                    "file_path": file_path,
                    "strategy": strategy,
                    "found": False,
                    "rank": -1,
                    "query": query,
                    "top_5_ids": [],
                    "error": f"All {MAX_RETRIES} retries exhausted: {last_error}",
                    "series": file_info["series"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

        # Parse response -- check top-K grounding chunks
        found = False
        rank = -1
        top_ids: list[str] = []

        if response and response.candidates:
            gm = getattr(response.candidates[0], "grounding_metadata", None)
            if gm:
                chunks = getattr(gm, "grounding_chunks", []) or []
                for i, chunk in enumerate(chunks[:TOP_K]):
                    rc = getattr(chunk, "retrieved_context", None)
                    if not rc:
                        continue
                    title_in_result = getattr(rc, "title", "") or ""
                    if title_in_result:
                        top_ids.append(title_in_result)
                    if not found:
                        if expected_file_id and title_in_result == expected_file_id:
                            found = True
                            rank = i + 1
                        elif store_doc_prefix and title_in_result == store_doc_prefix:
                            found = True
                            rank = i + 1

        return {
            "filename": filename,
            "file_path": file_path,
            "strategy": strategy,
            "found": found,
            "rank": rank,
            "query": query,
            "top_5_ids": top_ids,
            "series": file_info["series"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def check_file(
        self,
        file_info: dict,
        strategy: int,
        semaphore: asyncio.Semaphore,
        conn: sqlite3.Connection,
    ) -> dict:
        """Check a single file's retrievability with retries and backoff."""
        file_path = file_info["file_path"]
        filename = file_info["filename"]
        store_doc_id = file_info["store_doc_id"]
        gemini_file_id = file_info["gemini_file_id"]

        expected_file_id = (gemini_file_id or "").replace("files/", "")
        store_doc_prefix = store_doc_id.split("-")[0] if store_doc_id else ""

        if strategy == 5:
            # S4b: individual aspect cascade -- try each aspect until one finds the file
            query_sequence = self._build_s4b_sequence(file_path, filename, conn)
            if not query_sequence:
                stem = PurePosixPath(filename).stem
                query_sequence = [f"What is '{stem}' about?"]

            for query in query_sequence:
                result = await self._run_single_query(
                    query, file_path, filename, strategy,
                    expected_file_id, store_doc_prefix, semaphore, file_info,
                )
                if result.get("found") or result.get("error"):
                    return result  # Found, or hard error (stop trying)

            # All queries exhausted without finding the file
            return {
                "filename": filename,
                "file_path": file_path,
                "strategy": strategy,
                "found": False,
                "rank": -1,
                "query": query_sequence[0],
                "top_5_ids": [],
                "series": file_info["series"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Strategies 1-4: single query
        query = self.build_query(file_path, filename, strategy, conn)
        return await self._run_single_query(
            query, file_path, filename, strategy,
            expected_file_id, store_doc_prefix, semaphore, file_info,
        )

    async def run_strategy(
        self,
        files: list[dict],
        strategy: int,
        progress: dict,
    ) -> None:
        """Run a single strategy across all files with concurrency control."""
        # Open DB connection for query building
        conn = sqlite3.connect(self.db_path)

        semaphore = asyncio.Semaphore(self.concurrency)
        pending = []

        for file_info in files:
            key = f"{file_info['file_path']}_{strategy}"
            if key in progress["results"]:
                continue  # Already completed
            pending.append(file_info)

        if not pending:
            print(f"Strategy {strategy}: all {len(files)} files already completed")
            conn.close()
            return

        print(f"Strategy {strategy}: {len(pending)} files to process ({len(files) - len(pending)} already done)")

        completed = 0
        total = len(pending)
        hits = 0
        start_time = time.time()

        # Process in batches of concurrency size for progress reporting
        batch_size = self.concurrency * 2  # Process in small batches for frequent saves
        for batch_start in range(0, total, batch_size):
            batch = pending[batch_start:batch_start + batch_size]

            tasks = [
                self.check_file(file_info, strategy, semaphore, conn)
                for file_info in batch
            ]
            results = await asyncio.gather(*tasks)

            for result in results:
                key = f"{result['file_path']}_{strategy}"
                progress["results"][key] = result
                completed += 1
                if result["found"]:
                    hits += 1

                if self.verbose and completed % 10 == 0:
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    eta = (total - completed) / rate if rate > 0 else 0
                    print(
                        f"  Strategy {strategy}: {completed}/{total} "
                        f"({hits} hits, {completed - hits} misses) "
                        f"[{rate:.1f}/s, ETA {eta:.0f}s]"
                    )

            # Save after each batch
            self.save_progress(progress)

        elapsed = time.time() - start_time
        # Count strategy results
        strat_results = [
            r for r in progress["results"].values() if r["strategy"] == strategy
        ]
        strat_hits = sum(1 for r in strat_results if r["found"])
        strat_total = len(strat_results)
        hit_rate = (strat_hits / strat_total * 100) if strat_total > 0 else 0

        print(
            f"Strategy {strategy} complete: {strat_hits}/{strat_total} "
            f"({hit_rate:.1f}% hit rate) in {elapsed:.0f}s"
        )

        conn.close()

    def print_summary(self, progress: dict) -> None:
        """Print per-series hit rate summary table."""
        from collections import defaultdict

        results = progress.get("results", {})
        if not results:
            print("No results to summarize.")
            return

        # Detect which strategies are present
        all_strategies = sorted({r["strategy"] for r in results.values()})
        strategy_labels = {1: "S1", 2: "S2", 3: "S3", 4: "S4a", 5: "S4b"}

        # Group by file and strategy
        by_file: dict[str, dict[int, dict]] = defaultdict(dict)
        for key, r in results.items():
            by_file[r["file_path"]][r["strategy"]] = r

        # Accumulate per-series stats for detected strategies
        def make_series_entry() -> dict:
            entry: dict = {"total": 0}
            for s in all_strategies:
                entry[s] = {"hits": 0, "total": 0}
            return entry

        series_stats: dict[str, dict] = defaultdict(make_series_entry)

        for fp, strats in by_file.items():
            series = next(iter(strats.values())).get("series", "Other")
            series_stats[series]["total"] += 1
            for s in all_strategies:
                if s in strats:
                    series_stats[series][s]["total"] += 1
                    if strats[s].get("found"):
                        series_stats[series][s]["hits"] += 1

        # Global stats
        print("\n" + "=" * 80)
        print("RETRIEVABILITY AUDIT RESULTS")
        print("=" * 80)

        for s in all_strategies:
            total = sum(ss[s]["total"] for ss in series_stats.values())
            hits = sum(ss[s]["hits"] for ss in series_stats.values())
            rate = (hits / total * 100) if total > 0 else 0
            lbl = strategy_labels.get(s, f"S{s}")
            print(f"  Strategy {s} ({lbl}): {hits}/{total} = {rate:.1f}%")

        if HAS_RICH:
            console = Console()

            table = Table(title="Per-Series Hit Rates")
            table.add_column("Series", style="bold")
            table.add_column("Total", justify="right")
            for s in all_strategies:
                lbl = strategy_labels.get(s, f"S{s}")
                table.add_column(f"{lbl} Hits", justify="right")
                table.add_column(f"{lbl}%", justify="right")

            for series_name in sorted(series_stats.keys()):
                ss = series_stats[series_name]
                row = [series_name, str(ss["total"])]
                for s in all_strategies:
                    hits = ss[s]["hits"]
                    total = ss[s]["total"]
                    rate = (hits / total * 100) if total > 0 else 0
                    row.extend([str(hits), f"{rate:.1f}%"])
                table.add_row(*row)

            total_row = ["TOTAL", str(sum(ss["total"] for ss in series_stats.values()))]
            for s in all_strategies:
                hits = sum(ss[s]["hits"] for ss in series_stats.values())
                total = sum(ss[s]["total"] for ss in series_stats.values())
                rate = (hits / total * 100) if total > 0 else 0
                total_row.extend([str(hits), f"{rate:.1f}%"])
            table.add_row(*total_row, style="bold")

            console.print(table)
        else:
            print("\nPer-Series Hit Rates:")
            header = f"{'Series':<15} {'Total':>5}"
            for s in all_strategies:
                lbl = strategy_labels.get(s, f"S{s}")
                header += f" {(lbl + ' Hits'):>9} {(lbl + '%'):>6}"
            print(header)
            print("-" * (21 + 16 * len(all_strategies)))
            for series_name in sorted(series_stats.keys()):
                ss = series_stats[series_name]
                parts = [f"{series_name:<15}", f"{ss['total']:>5}"]
                for s in all_strategies:
                    hits = ss[s]["hits"]
                    total = ss[s]["total"]
                    rate = (hits / total * 100) if total > 0 else 0
                    parts.extend([f"{hits:>9}", f"{rate:>5.1f}%"])
                print(" ".join(parts))

        # Files failing all tested strategies
        failing_all = []
        for fp, strats in by_file.items():
            if all(not strats.get(s, {}).get("found", False) for s in all_strategies):
                if all(s in strats for s in all_strategies):
                    failing_all.append(fp)

        if failing_all:
            print(f"\nFiles failing ALL {len(all_strategies)} strategies: {len(failing_all)}")
            for fp in sorted(failing_all)[:20]:
                series = detect_series(fp)
                print(f"  [{series}] {PurePosixPath(fp).name}")
            if len(failing_all) > 20:
                print(f"  ... and {len(failing_all) - 20} more")

    async def run(self) -> int:
        """Execute the audit. Returns exit code."""
        # Resolve store
        if not self._resolve_store():
            return 2

        # Load files
        files = self.load_files()
        if not files:
            print("ERROR: No indexed files found in DB", file=sys.stderr)
            return 2

        # Load progress
        progress = self.load_progress()
        progress["metadata"]["total_files"] = len(files)

        # Build corpus aspect frequency map (needed for strategies 4 and 5)
        print("Building corpus aspect frequency map...")
        self.corpus_freq = build_corpus_freq_map(self.db_path)
        print(f"  Built frequency map for {len(self.corpus_freq)} unique aspects")

        # Run each strategy
        for strategy in self.strategies:
            print(f"\n--- Strategy {strategy} ---")
            await self.run_strategy(files, strategy, progress)

        # Save final progress
        progress["metadata"]["completed_at"] = datetime.now(timezone.utc).isoformat()
        progress["metadata"]["api_calls"] = self._api_calls
        progress["metadata"]["errors"] = self._errors
        self.save_progress(progress)

        # Print summary
        self.print_summary(progress)

        print(f"\nTotal API calls: {self._api_calls}, Errors: {self._errors}")
        print(f"Results saved to: {self.progress_file}")

        return 0


# -- Main ---------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Comprehensive retrievability audit for Gemini File Search store",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all 3 strategies
  python scripts/retrievability_audit.py --store objectivism-library --db data/library.db --strategy all

  # Run only strategy 1 with verbose output
  python scripts/retrievability_audit.py --store objectivism-library --db data/library.db --strategy 1 --verbose

  # Resume interrupted run (progress file auto-loaded)
  python scripts/retrievability_audit.py --store objectivism-library --db data/library.db --strategy 2
""",
    )
    parser.add_argument("--store", required=True, help="Gemini File Search store display name")
    parser.add_argument("--db", required=True, help="Path to library.db")
    parser.add_argument(
        "--strategy",
        required=True,
        choices=["1", "2", "3", "4", "5", "all"],
        help=(
            "Query strategy to run: 1=stem-only, 2=stem+aspects, 3=topics+course, "
            "4=S4a (rarest-aspects, no preamble), 5=S4b (rarest-aspect+course), all=1+2+3"
        ),
    )
    parser.add_argument(
        "--progress", "--progress-file",
        dest="progress",
        required=True,
        help="Path to JSON progress file (created if missing, resumed if exists)",
    )
    parser.add_argument("--concurrency", type=int, default=10, help="Max concurrent API calls (default: 10)")
    parser.add_argument("--verbose", action="store_true", help="Show detailed progress")

    args = parser.parse_args()

    # Verify DB exists
    if not Path(args.db).exists():
        print(f"ERROR: Database not found at {args.db}", file=sys.stderr)
        return 2

    # Ensure progress directory exists
    progress_dir = Path(args.progress).parent
    progress_dir.mkdir(parents=True, exist_ok=True)

    auditor = RetrievabilityAuditor(
        store=args.store,
        db=args.db,
        strategy=args.strategy,
        progress_file=args.progress,
        concurrency=args.concurrency,
        verbose=args.verbose,
    )

    return await auditor.run()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
