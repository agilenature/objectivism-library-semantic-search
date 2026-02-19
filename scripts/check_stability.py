#!/usr/bin/env python3
"""Temporal Stability Check — Gemini File Search ↔ SQLite sync verification.

Tests six independent assumptions about the synchronization between the local
SQLite database and the Gemini File Search API store. ANY single failure
produces an UNSTABLE verdict and a non-zero exit code.

Designed to catch silent drift: a state that looks synchronized at T=0 but
breaks by T+24h. The checks are intentionally distrustful — they do not assume
that a passing state from a previous run implies a passing state now.

Scheduled re-verification after any upload/purge/reset-existing operation:
  T+0    immediately after the operation (baseline)
  T+4h   first re-check
  T+24h  gate blocker — Wave N+1 must not start until this passes
  T+36h  final verification

Usage:
  python scripts/check_stability.py
  python scripts/check_stability.py --store objectivism-library-test
  python scripts/check_stability.py --store objectivism-library-test --db data/library.db
  python scripts/check_stability.py --verbose
  python scripts/check_stability.py --query "nature of individual rights"

Exit codes:
  0  STABLE   — all checks passed
  1  UNSTABLE — one or more checks failed
  2  ERROR    — could not complete checks (API unavailable, DB missing, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
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
except ImportError as e:
    print(f"ERROR: Missing dependency: {e}", file=sys.stderr)
    print("Run: pip install google-genai keyring", file=sys.stderr)
    sys.exit(2)


# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_STORE = "objectivism-library-test"
DEFAULT_DB = str(_REPO_ROOT / "data" / "library.db")
# A query broad enough to reliably return results from an Objectivism library.
# Replace with a more specific query if you want to test a particular domain.
DEFAULT_QUERY = "Ayn Rand theory of individual rights and capitalism"
SEARCH_MODEL = "gemini-2.5-flash"


# ── Terminal formatting ────────────────────────────────────────────────────────
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
DIM    = "\033[2m"


def _ok(msg: str) -> str:   return f"  {GREEN}✓ PASS{RESET}  {msg}"
def _fail(msg: str) -> str: return f"  {RED}✗ FAIL{RESET}  {msg}"
def _warn(msg: str) -> str: return f"  {YELLOW}⚠ WARN{RESET}  {msg}"
def _info(msg: str) -> str: return f"  {DIM}·{RESET}       {msg}"
def _head(msg: str) -> str: return f"\n{BOLD}{msg}{RESET}"


# ── Checker ────────────────────────────────────────────────────────────────────

class StabilityChecker:
    """Runs all six stability checks and accumulates results."""

    def __init__(
        self,
        api_key: str,
        store_display_name: str,
        db_path: str,
        sample_query: str,
        verbose: bool = False,
    ) -> None:
        self.api_key = api_key
        self.store_display_name = store_display_name
        self.db_path = db_path
        self.sample_query = sample_query
        self.verbose = verbose

        self.client = genai.Client(api_key=api_key)
        self.store_resource_name: str | None = None

        self.passed: list[str] = []
        self.failed: list[str] = []
        self.warnings: list[str] = []

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _pass(self, label: str, detail: str = "") -> None:
        msg = f"{label}" + (f": {detail}" if detail else "")
        print(_ok(msg))
        self.passed.append(label)

    def _fail(self, label: str, detail: str = "") -> None:
        msg = f"{label}" + (f": {detail}" if detail else "")
        print(_fail(msg))
        self.failed.append(label)

    def _warn(self, label: str, detail: str = "") -> None:
        msg = f"{label}" + (f": {detail}" if detail else "")
        print(_warn(msg))
        self.warnings.append(label)

    def _verbose(self, msg: str) -> None:
        if self.verbose:
            print(_info(msg))

    # ── Step 0: Store resolution ───────────────────────────────────────────────

    def _resolve_store(self) -> bool:
        """Resolve store display name → resource name. Returns False if not found."""
        try:
            for store in self.client.file_search_stores.list():
                if getattr(store, "display_name", None) == self.store_display_name:
                    self.store_resource_name = store.name
                    self._verbose(f"Resolved store: {self.store_display_name} → {store.name}")
                    return True
            self._fail(
                "Store resolution",
                f"No store named '{self.store_display_name}' found in Gemini account",
            )
            return False
        except Exception as e:
            self._fail("Store resolution", f"API error listing stores: {e}")
            return False

    # ── Step 1: DB ─────────────────────────────────────────────────────────────

    def _load_db(self) -> tuple[set[str], dict[str, int]] | None:
        """
        Load DB state. Returns:
          (canonical_file_ids, status_counts)
        where canonical_file_ids is the set of bare file ID suffixes (no 'files/')
        for all files with status='uploaded'.
        Returns None on error.
        """
        db_path = Path(self.db_path)
        if not db_path.exists():
            self._fail("DB access", f"Database not found at {db_path}")
            return None
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row

            # Status counts
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM files GROUP BY status ORDER BY n DESC"
            ).fetchall()
            counts: dict[str, int] = {r["status"]: r["n"] for r in rows}
            self._verbose(
                "DB status counts: "
                + ", ".join(f"{s}={n}" for s, n in sorted(counts.items()))
            )

            # Canonical IDs
            rows = conn.execute(
                "SELECT gemini_file_id FROM files "
                "WHERE status = 'uploaded' AND gemini_file_id IS NOT NULL"
            ).fetchall()
            canonical_ids: set[str] = set()
            for r in rows:
                gid = (r["gemini_file_id"] or "").strip()
                suffix = gid.replace("files/", "")
                if suffix:
                    canonical_ids.add(suffix)

            conn.close()
            return canonical_ids, counts

        except Exception as e:
            self._fail("DB access", str(e))
            return None

    # ── Step 2: Store documents ────────────────────────────────────────────────

    async def _list_store_docs(self) -> list | None:
        """List all documents in the store. Returns list or None on error."""
        assert self.store_resource_name, "Store not resolved"
        try:
            docs: list = []
            pager = await self.client.aio.file_search_stores.documents.list(
                parent=self.store_resource_name
            )
            async for doc in pager:
                docs.append(doc)
            self._verbose(f"Store document count: {len(docs)}")
            return docs
        except Exception as e:
            self._fail("Store listing", f"API error: {e}")
            return None

    # ── Check 1: Count invariant ───────────────────────────────────────────────

    def _check_count(self, db_uploaded: int, store_count: int) -> None:
        """DB uploaded count must equal store document count exactly."""
        if db_uploaded == store_count:
            self._pass(
                "Check 1 — Count invariant",
                f"DB uploaded={db_uploaded}, store docs={store_count}",
            )
        else:
            delta = store_count - db_uploaded
            if delta > 0:
                direction = f"{delta} orphaned in store (not in DB as 'uploaded')"
            else:
                direction = f"{abs(delta)} ghost in DB (missing from store)"
            self._fail(
                "Check 1 — Count invariant",
                f"DB uploaded={db_uploaded} ≠ store docs={store_count} ({direction})",
            )

    # ── Check 2: DB→Store (no ghost records) ──────────────────────────────────

    def _check_db_to_store(
        self, canonical_ids: set[str], store_display_names: set[str]
    ) -> None:
        """Every file marked 'uploaded' in DB must be present in the store."""
        ghosts = canonical_ids - store_display_names
        if not ghosts:
            self._pass(
                "Check 2 — DB→Store (no ghosts)",
                f"all {len(canonical_ids)} uploaded files present in store",
            )
        else:
            sample = sorted(ghosts)[:5]
            self._fail(
                "Check 2 — DB→Store (ghost records)",
                f"{len(ghosts)} files marked 'uploaded' in DB but absent from store. "
                f"Sample: {sample}",
            )

    # ── Check 3: Store→DB (no orphans) ────────────────────────────────────────

    def _check_store_to_db(
        self, canonical_ids: set[str], store_display_names: set[str]
    ) -> None:
        """Every store document must have a corresponding 'uploaded' DB record."""
        orphans = store_display_names - canonical_ids
        if not orphans:
            self._pass(
                "Check 3 — Store→DB (no orphans)",
                f"all {len(store_display_names)} store docs have matching DB records",
            )
        else:
            sample = sorted(orphans)[:5]
            self._fail(
                "Check 3 — Store→DB (orphaned store docs)",
                f"{len(orphans)} store docs have no matching 'uploaded' DB record — "
                f"these will produce [Unresolved file #N] in search. Sample: {sample}",
            )

    # ── Check 4: No stuck transitions ─────────────────────────────────────────

    def _check_stuck(self, counts: dict[str, int]) -> None:
        """No files should be stuck in 'uploading' status."""
        stuck = counts.get("uploading", 0)
        if stuck == 0:
            self._pass("Check 4 — No stuck transitions", "0 files in 'uploading' status")
        else:
            self._fail(
                "Check 4 — Stuck transitions",
                f"{stuck} files still in 'uploading' (upload process died mid-flight)",
            )
        # Non-blocking warning for 'failed' files
        failed = counts.get("failed", 0)
        if failed > 0:
            self._warn(
                "Check 4b — Failed files",
                f"{failed} files with status='failed' (not in store, need retry)",
            )

    # ── Check 5: Search returns results ───────────────────────────────────────

    def _check_search_results(self) -> list | None:
        """Run a real search. Fails if zero citations returned."""
        try:
            from objlib.search.client import GeminiSearchClient
            from objlib.search.citations import extract_citations

            search = GeminiSearchClient(self.client, self.store_resource_name)
            self._verbose(f"Querying: {self.sample_query!r}")
            response = search.query_with_retry(self.sample_query)

            grounding = None
            if response.candidates:
                grounding = getattr(response.candidates[0], "grounding_metadata", None)
            citations = extract_citations(grounding)

            if not citations:
                self._fail(
                    "Check 5 — Search returns results",
                    "0 citations returned — store may be empty or search broken",
                )
                return None

            self._pass(
                "Check 5 — Search returns results",
                f"{len(citations)} citations returned for sample query",
            )
            return citations

        except Exception as e:
            self._fail("Check 5 — Search returns results", f"Exception: {e}")
            return None

    # ── Check 6: Citation resolution (no [Unresolved file #N]) ───────────────

    def _check_citation_resolution(
        self, citations: list, canonical_ids: set[str]
    ) -> None:
        """All returned citations must resolve to known DB records.

        A citation title without an extension (e.g. 'abc123xyz') is a raw
        Gemini file ID — the same ID that would produce '[Unresolved file #N]'
        in the TUI if it's not in the DB. A title with an extension (e.g.
        'some-book.txt') is a resolved filename.
        """
        from objlib.search.citations import enrich_citations
        from objlib.database import Database

        try:
            with Database(self.db_path) as db:
                enriched = enrich_citations(citations, db, self.client)
        except Exception as e:
            self._fail("Check 6 — Citation resolution", f"DB enrichment error: {e}")
            return

        unresolved = []
        for c in enriched:
            title = c.title or ""
            # A resolved citation has a filename (contains ".") or non-empty file_path
            if c.file_path:
                continue  # Successfully resolved
            if "." in title:
                continue  # Looks like a filename — assume resolved
            # Raw Gemini file ID with no DB match
            unresolved.append(title or "<empty>")

        if unresolved:
            self._fail(
                "Check 6 — Citation resolution",
                f"{len(unresolved)}/{len(enriched)} citations unresolvable "
                f"(would show as [Unresolved file #N]): {unresolved}",
            )
        else:
            self._pass(
                "Check 6 — Citation resolution",
                f"all {len(enriched)} citations resolve to DB records",
            )

    # ── Main run ───────────────────────────────────────────────────────────────

    async def run(self) -> int:
        """Execute all checks. Returns exit code: 0=STABLE, 1=UNSTABLE, 2=ERROR."""
        now = datetime.now(timezone.utc)
        print(f"\n{BOLD}{'━'*62}{RESET}")
        print(f"{BOLD}  TEMPORAL STABILITY CHECK{RESET}")
        print(f"{BOLD}{'━'*62}{RESET}")
        print(f"  Time:   {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"  Store:  {self.store_display_name}")
        print(f"  DB:     {self.db_path}")
        print(f"  Query:  {self.sample_query!r}")
        print(f"{BOLD}{'━'*62}{RESET}")

        t_start = time.monotonic()

        # ── Step 0: Resolve store ──────────────────────────────────────────────
        print(_head("Resolving store..."))
        if not self._resolve_store():
            print(f"\n{RED}{BOLD}  ABORT: Cannot resolve store.{RESET}")
            return 2

        # ── Step 1: Load DB ────────────────────────────────────────────────────
        print(_head("Loading database..."))
        db_result = self._load_db()
        if db_result is None:
            print(f"\n{RED}{BOLD}  ABORT: Cannot read database.{RESET}")
            return 2
        canonical_ids, status_counts = db_result
        db_uploaded = status_counts.get("uploaded", 0)
        self._verbose(f"DB canonical IDs (sample): {sorted(canonical_ids)[:3]}")

        # ── Step 2: List store documents ──────────────────────────────────────
        print(_head("Listing store documents..."))
        docs = await self._list_store_docs()
        if docs is None:
            print(f"\n{RED}{BOLD}  ABORT: Cannot list store documents.{RESET}")
            return 2

        store_display_names: set[str] = set()
        for doc in docs:
            dn = getattr(doc, "display_name", "") or ""
            if dn:
                store_display_names.add(dn)
        self._verbose(f"Store display_names (sample): {sorted(store_display_names)[:3]}")

        # ── Structural checks ──────────────────────────────────────────────────
        print(_head("Structural checks..."))
        self._check_count(db_uploaded, len(docs))
        self._check_db_to_store(canonical_ids, store_display_names)
        self._check_store_to_db(canonical_ids, store_display_names)
        self._check_stuck(status_counts)

        # ── Search checks ──────────────────────────────────────────────────────
        print(_head("Search + citation resolution..."))
        citations = self._check_search_results()
        if citations is not None:
            self._check_citation_resolution(citations, canonical_ids)

        # ── Verdict ────────────────────────────────────────────────────────────
        elapsed = time.monotonic() - t_start
        print(f"\n{BOLD}{'━'*62}{RESET}")
        print(f"  Passed:   {len(self.passed)}")
        print(f"  Failed:   {len(self.failed)}")
        print(f"  Warnings: {len(self.warnings)}")
        print(f"  Elapsed:  {elapsed:.1f}s")
        print(f"{BOLD}{'━'*62}{RESET}")

        if self.failed:
            print(f"\n  {RED}{BOLD}VERDICT: UNSTABLE{RESET}")
            print(f"  {RED}Failed checks:{RESET}")
            for label in self.failed:
                print(f"    • {label}")
            if self.warnings:
                print(f"  {YELLOW}Warnings (non-blocking):{RESET}")
                for label in self.warnings:
                    print(f"    • {label}")
            print()
            return 1

        print(f"\n  {GREEN}{BOLD}VERDICT: STABLE{RESET}")
        if self.warnings:
            print(f"  {YELLOW}Warnings (non-blocking):{RESET}")
            for label in self.warnings:
                print(f"    • {label}")
        print()
        return 0


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Temporal stability check for Gemini File Search ↔ SQLite sync",
        epilog="Exit 0=STABLE, 1=UNSTABLE, 2=ERROR (abort)",
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
        help=f"SQLite DB path (default: data/library.db)",
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help="Sample search query for the citation resolution check",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print additional diagnostic detail",
    )
    args = parser.parse_args()

    api_key = keyring.get_password("objlib-gemini", "api_key")
    if not api_key:
        print("ERROR: No API key found in keyring.", file=sys.stderr)
        print("Run: python -m objlib setup  (or set via keyring manually)", file=sys.stderr)
        sys.exit(2)

    checker = StabilityChecker(
        api_key=api_key,
        store_display_name=args.store,
        db_path=args.db,
        sample_query=args.query,
        verbose=args.verbose,
    )
    exit_code = asyncio.run(checker.run())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
