#!/usr/bin/env python3
"""Temporal Stability Check v2 — Gemini File Search ↔ SQLite FSM sync verification.

Tests six independent assertions about the synchronization between the local
SQLite database (using gemini_state FSM columns) and the Gemini File Search API
store. ANY single failure produces an UNSTABLE verdict and a non-zero exit code.

Designed to catch silent drift: a state that looks synchronized at T=0 but
breaks by T+24h. The checks are intentionally distrustful — they do not assume
that a passing state from a previous run implies a passing state now.

v2 changes from v1:
  - Uses gemini_state='indexed' instead of status='uploaded'
  - Uses gemini_store_doc_id instead of gemini_file_id for store matching
  - Prerequisite checks produce exit 2 (not exit 1) for configuration errors
  - Vacuous pass logic for empty stores (0 indexed files)
  - No dependency on objlib search layer (uses raw genai SDK)
  - Default store: objectivism-library (not objectivism-library-test)

Scheduled re-verification after any upload/purge/reset-existing operation:
  T+0    immediately after the operation (baseline)
  T+4h   first re-check
  T+24h  gate blocker — Wave N+1 must not start until this passes
  T+36h  final verification

Usage:
  python scripts/check_stability.py
  python scripts/check_stability.py --store objectivism-library
  python scripts/check_stability.py --store objectivism-library --db data/library.db
  python scripts/check_stability.py --verbose
  python scripts/check_stability.py --query "nature of individual rights"

Exit codes:
  0  STABLE   — all checks passed
  1  UNSTABLE — one or more checks failed
  2  ERROR    — could not complete checks (API unavailable, DB missing, schema wrong, etc.)
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
    from google.genai import types as genai_types
except ImportError as e:
    print(f"ERROR: Missing dependency: {e}", file=sys.stderr)
    print("Run: pip install google-genai keyring", file=sys.stderr)
    sys.exit(2)


# -- Defaults -----------------------------------------------------------------
DEFAULT_STORE = "objectivism-library"
DEFAULT_DB = str(_REPO_ROOT / "data" / "library.db")
# A query broad enough to reliably return results from an Objectivism library.
DEFAULT_QUERY = "Ayn Rand theory of individual rights and capitalism"
SEARCH_MODEL = "gemini-2.5-flash"


# -- Terminal formatting -------------------------------------------------------
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
DIM    = "\033[2m"


def _ok(msg: str) -> str:   return f"  {GREEN}PASS{RESET}  {msg}"
def _fail(msg: str) -> str: return f"  {RED}FAIL{RESET}  {msg}"
def _warn(msg: str) -> str: return f"  {YELLOW}WARN{RESET}  {msg}"
def _info(msg: str) -> str: return f"  {DIM}.{RESET}       {msg}"
def _head(msg: str) -> str: return f"\n{BOLD}{msg}{RESET}"


# -- Checker -------------------------------------------------------------------

class StabilityChecker:
    """Runs all six stability assertions and accumulates results."""

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

    # -- Helpers ---------------------------------------------------------------

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

    # -- Step 0: Prerequisites (NEW in v2) -------------------------------------

    def _check_prerequisites(self):
        """Return exit code 2 if prerequisites fail, None if all pass."""
        # Check DB exists
        if not Path(self.db_path).exists():
            print(f"ERROR: Database not found at {self.db_path}", file=sys.stderr)
            return 2

        # Check schema has required FSM columns
        try:
            conn = sqlite3.connect(self.db_path)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(files)")}
            conn.close()
            required = {"gemini_state", "gemini_store_doc_id", "gemini_state_updated_at"}
            missing = required - cols
            if missing:
                print(f"ERROR: Schema migration not applied. Missing columns: {missing}", file=sys.stderr)
                print("Run: python scripts/migrate_phase8.py", file=sys.stderr)
                return 2
        except Exception as e:
            print(f"ERROR: Cannot read database schema: {e}", file=sys.stderr)
            return 2

        # Check API key
        if not self.api_key:
            print("ERROR: No API key provided", file=sys.stderr)
            return 2

        # Check store resolves
        if not self._resolve_store():
            return 2

        return None  # All prerequisites pass

    # -- Store resolution ------------------------------------------------------

    def _resolve_store(self) -> bool:
        """Resolve store display name to resource name. Returns False if not found."""
        try:
            available = []
            for store in self.client.file_search_stores.list():
                dn = getattr(store, "display_name", None)
                if dn == self.store_display_name:
                    self.store_resource_name = store.name
                    self._verbose(f"Resolved store: {self.store_display_name} -> {store.name}")
                    return True
                if dn:
                    available.append(dn)
            print(f"ERROR: Store '{self.store_display_name}' not found.", file=sys.stderr)
            print(f"Available stores: {available}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"ERROR: API error listing stores: {e}", file=sys.stderr)
            return False

    # -- Step 1: DB (uses gemini_state instead of status) ----------------------

    def _load_db(self) -> tuple[int, set[str], dict[str, int]] | None:
        """
        Load DB state using FSM columns. Returns:
          (indexed_count, canonical_doc_ids, state_counts)
        where canonical_doc_ids is the set of gemini_store_doc_id values
        for all files with gemini_state='indexed'.
        Returns None on error.
        """
        try:
            conn = sqlite3.connect(self.db_path)

            # Count of files in 'indexed' state (the FSM-tracked count)
            indexed_count = conn.execute(
                "SELECT COUNT(*) FROM files WHERE gemini_state = 'indexed'"
            ).fetchone()[0]

            # Canonical store doc IDs for indexed files
            rows = conn.execute(
                "SELECT gemini_store_doc_id FROM files "
                "WHERE gemini_state = 'indexed' AND gemini_store_doc_id IS NOT NULL"
            ).fetchall()
            canonical_doc_ids = {row[0] for row in rows}

            # State counts (for check 4 -- stuck transitions)
            status_rows = conn.execute(
                "SELECT gemini_state, COUNT(*) AS n FROM files GROUP BY gemini_state"
            ).fetchall()
            state_counts = {r[0]: r[1] for r in status_rows}

            conn.close()

            self._verbose(
                "DB state counts: "
                + ", ".join(f"{s}={n}" for s, n in sorted(state_counts.items()))
            )
            self._verbose(f"Indexed count: {indexed_count}")

            return (indexed_count, canonical_doc_ids, state_counts)

        except Exception as e:
            print(f"ERROR: Cannot read database: {e}", file=sys.stderr)
            return None

    # -- Step 2: Store documents -----------------------------------------------

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
            print(f"ERROR: API error listing store documents: {e}", file=sys.stderr)
            return None

    # -- Assertion 1: Count invariant ------------------------------------------

    def _check_count(self, indexed_count: int, store_doc_count: int) -> None:
        """DB indexed count must equal store document count exactly."""
        if indexed_count == store_doc_count:
            self._pass(
                "Assertion 1 -- Count invariant",
                f"DB indexed={indexed_count}, store docs={store_doc_count}",
            )
        else:
            delta = store_doc_count - indexed_count
            direction = f"{delta} orphaned in store" if delta > 0 else f"{abs(delta)} ghosts in DB"
            self._fail(
                "Assertion 1 -- Count invariant",
                f"DB indexed={indexed_count} != store docs={store_doc_count} ({direction})",
            )

    # -- Assertion 2: DB->Store (no ghost records) -----------------------------

    def _check_db_to_store(
        self, canonical_doc_ids: set[str], store_doc_names: set[str]
    ) -> None:
        """Every file with gemini_state='indexed' must have its store doc in the store."""
        if not canonical_doc_ids:
            self._pass("Assertion 2 -- DB->Store (no ghosts)", "N/A -- 0 indexed files")
            return
        ghosts = canonical_doc_ids - store_doc_names
        if not ghosts:
            self._pass(
                "Assertion 2 -- DB->Store (no ghosts)",
                f"all {len(canonical_doc_ids)} indexed files present in store",
            )
        else:
            self._fail(
                "Assertion 2 -- DB->Store (ghost records)",
                f"{len(ghosts)} files with gemini_state='indexed' but no store document",
            )

    # -- Assertion 3: Store->DB (no orphans) -----------------------------------

    def _check_store_to_db(
        self, canonical_doc_ids: set[str], store_doc_names: set[str]
    ) -> None:
        """Every store document must have a matching gemini_store_doc_id in the DB."""
        if not store_doc_names:
            self._pass("Assertion 3 -- Store->DB (no orphans)", "N/A -- store is empty (0 documents)")
            return
        orphans = store_doc_names - canonical_doc_ids
        if not orphans:
            self._pass(
                "Assertion 3 -- Store->DB (no orphans)",
                f"all {len(store_doc_names)} store docs match DB records",
            )
        else:
            sample = sorted(orphans)[:5]
            self._fail(
                "Assertion 3 -- Store->DB (orphaned store docs)",
                f"{len(orphans)} store docs have no matching DB record. Sample: {sample}",
            )

    # -- Assertion 4: No stuck transitions -------------------------------------

    def _check_stuck(self, state_counts: dict) -> None:
        """No files should be stuck in 'uploading' state."""
        stuck = state_counts.get("uploading", 0)
        if stuck == 0:
            self._pass("Assertion 4 -- No stuck transitions", "0 files in 'uploading' state")
        else:
            self._fail(
                "Assertion 4 -- Stuck transitions",
                f"{stuck} files stuck in gemini_state='uploading'",
            )
        # Non-blocking warning for 'failed' files
        failed = state_counts.get("failed", 0)
        if failed > 0:
            self._warn(
                "Assertion 4b -- Failed files",
                f"{failed} files with gemini_state='failed'",
            )

    # -- Assertion 5: Search returns results -----------------------------------

    def _check_search_results(self, indexed_count: int):
        """Run a real search. Vacuous pass on empty store. Fails if zero citations returned."""
        if indexed_count == 0:
            self._pass(
                "Assertion 5 -- Search returns results",
                "N/A -- store is empty (0 indexed files)",
            )
            return None  # Signal to skip assertion 6

        try:
            self._verbose(f"Querying: {self.sample_query!r}")
            response = self.client.models.generate_content(
                model=SEARCH_MODEL,
                contents=self.sample_query,
                config=genai_types.GenerateContentConfig(
                    tools=[genai_types.Tool(
                        file_search=genai_types.ToolFileSearch(
                            file_search_store=self.store_resource_name
                        )
                    )]
                ),
            )
            citations = []
            if response.candidates:
                gm = getattr(response.candidates[0], "grounding_metadata", None)
                if gm:
                    chunks = getattr(gm, "grounding_chunks", []) or []
                    for chunk in chunks:
                        rc = getattr(chunk, "retrieved_context", None)
                        if rc:
                            citations.append(rc)
            if not citations:
                self._fail(
                    "Assertion 5 -- Search returns results",
                    "0 citations returned for sample query (store has indexed files)",
                )
                return None
            self._pass(
                "Assertion 5 -- Search returns results",
                f"{len(citations)} citations returned",
            )
            return citations

        except Exception as e:
            self._fail("Assertion 5 -- Search returns results", f"Exception: {e}")
            return None

    # -- Assertion 6: Citation resolution --------------------------------------

    def _check_citation_resolution(self, citations, indexed_count: int) -> None:
        """All returned citations must resolve to known DB records."""
        if indexed_count == 0:
            self._pass(
                "Assertion 6 -- Citation resolution",
                "N/A -- store is empty (0 indexed files)",
            )
            return
        if citations is None:
            # Assertion 5 failed -- skip (assertion 5 already recorded the failure)
            return

        conn = sqlite3.connect(self.db_path)
        unresolved = []
        for citation in citations:
            title = getattr(citation, "title", "") or ""
            # A resolved citation has a filename extension
            if "." in title:
                continue
            # Try to look up by gemini_store_doc_id or gemini_file_id
            row = conn.execute(
                "SELECT filename FROM files WHERE gemini_store_doc_id = ? OR gemini_file_id = ?",
                (title, f"files/{title}"),
            ).fetchone()
            if not row:
                unresolved.append(title or "<empty>")
        conn.close()

        if unresolved:
            self._fail(
                "Assertion 6 -- Citation resolution",
                f"{len(unresolved)}/{len(citations)} citations unresolvable: {unresolved}",
            )
        else:
            self._pass(
                "Assertion 6 -- Citation resolution",
                f"all {len(citations)} citations resolve to DB records",
            )

    # -- Main run --------------------------------------------------------------

    async def run(self) -> int:
        """Execute all assertions. Returns exit code: 0=STABLE, 1=UNSTABLE, 2=ERROR."""
        now = datetime.now(timezone.utc)
        print(f"\n{BOLD}{'=' * 62}{RESET}")
        print(f"{BOLD}  TEMPORAL STABILITY CHECK v2{RESET}")
        print(f"{BOLD}{'=' * 62}{RESET}")
        print(f"  Time:   {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"  Store:  {self.store_display_name}")
        print(f"  DB:     {self.db_path}")
        print(f"  Query:  {self.sample_query!r}")
        print(f"{BOLD}{'=' * 62}{RESET}")

        t_start = time.monotonic()

        # Step 0: Prerequisites (NEW in v2)
        print(_head("Checking prerequisites..."))
        prereq_code = self._check_prerequisites()
        if prereq_code is not None:
            print(f"\n{RED}{BOLD}  ABORT: Prerequisites failed.{RESET}")
            return prereq_code

        # Step 1: Load DB (now uses gemini_state)
        print(_head("Loading database..."))
        db_result = self._load_db()
        if db_result is None:
            print(f"\n{RED}{BOLD}  ABORT: Cannot read database.{RESET}")
            return 2
        indexed_count, canonical_doc_ids, state_counts = db_result

        # Step 2: List store documents
        print(_head("Listing store documents..."))
        docs = await self._list_store_docs()
        if docs is None:
            print(f"\n{RED}{BOLD}  ABORT: Cannot list store documents.{RESET}")
            return 2

        store_doc_names: set = set()
        for doc in docs:
            name = getattr(doc, "name", "") or ""
            if name:
                store_doc_names.add(name)
        self._verbose(f"Store doc names (sample): {sorted(store_doc_names)[:3]}")

        # Step 3: Structural checks
        print(_head("Structural checks..."))
        self._check_count(indexed_count, len(docs))
        self._check_db_to_store(canonical_doc_ids, store_doc_names)
        self._check_store_to_db(canonical_doc_ids, store_doc_names)
        self._check_stuck(state_counts)

        # Step 4: Search + citation checks
        print(_head("Search + citation resolution..."))
        citations = self._check_search_results(indexed_count)
        self._check_citation_resolution(citations, indexed_count)

        # Verdict
        elapsed = time.monotonic() - t_start
        print(f"\n{BOLD}{'=' * 62}{RESET}")
        print(f"  Passed:   {len(self.passed)}")
        print(f"  Failed:   {len(self.failed)}")
        print(f"  Warnings: {len(self.warnings)}")
        print(f"  Elapsed:  {elapsed:.1f}s")
        print(f"{BOLD}{'=' * 62}{RESET}")

        if self.failed:
            print(f"\n  {RED}{BOLD}VERDICT: UNSTABLE{RESET}")
            for label in self.failed:
                print(f"    {RED}*{RESET} {label}")
            if self.warnings:
                print(f"  {YELLOW}Warnings:{RESET}")
                for label in self.warnings:
                    print(f"    {YELLOW}*{RESET} {label}")
            print()
            return 1

        print(f"\n  {GREEN}{BOLD}VERDICT: STABLE{RESET}")
        if self.warnings:
            print(f"  {YELLOW}Warnings (non-blocking):{RESET}")
            for label in self.warnings:
                print(f"    {YELLOW}*{RESET} {label}")
        print()
        return 0


# -- Entry point ---------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Temporal stability check v2 for Gemini File Search <-> SQLite FSM sync",
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
        help="SQLite DB path (default: data/library.db)",
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
        return 2

    checker = StabilityChecker(
        api_key=api_key,
        store_display_name=args.store,
        db_path=args.db,
        sample_query=args.query,
        verbose=args.verbose,
    )
    return asyncio.run(checker.run())


if __name__ == "__main__":
    sys.exit(main())
