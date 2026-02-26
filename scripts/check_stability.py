#!/usr/bin/env python3
"""Temporal Stability Check v2 — Gemini File Search ↔ SQLite FSM sync verification.

Tests seven independent assertions about the synchronization between the local
SQLite database (using gemini_state FSM columns) and the Gemini File Search API
store. ANY single failure produces an UNSTABLE verdict and a non-zero exit code.

Designed to catch silent drift: a state that looks synchronized at T=0 but
breaks by T+24h. The checks are intentionally distrustful — they do not assume
that a passing state from a previous run implies a passing state now.

v2 changes from v1:
  - Uses gemini_state='indexed' (legacy status column retired in V11)
  - Uses gemini_store_doc_id instead of gemini_file_id for store matching
  - Prerequisite checks produce exit 2 (not exit 1) for configuration errors
  - Vacuous pass logic for empty stores (0 indexed files)
  - No dependency on objlib search layer (uses raw genai SDK)
  - Default store: objectivism-library (not objectivism-library-test)

Assertions:
  1. Count invariant: DB indexed count == store document count
  2. DB->Store: every indexed file has a store document (no ghosts)
  3. Store->DB: every store document has a DB record (no orphans)
  4. No stuck transitions: 0 files in 'uploading' state
  5. Search returns results: a sample query produces citations
  6. Citation resolution: all citations resolve to DB records
  7. Per-file searchability: a random sample of N indexed files each appear in
     top-10 search results for a targeted query constructed from the file's name

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
import json
import re
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
    """Runs all seven stability assertions and accumulates results."""

    def __init__(
        self,
        api_key: str,
        store_display_name: str,
        db_path: str,
        sample_query: str,
        verbose: bool = False,
        sample_size: int = 5,
    ) -> None:
        self.api_key = api_key
        self.store_display_name = store_display_name
        self.db_path = db_path
        self.sample_query = sample_query
        self.verbose = verbose
        self.sample_size = sample_size

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

    # -- Step 1: DB (uses gemini_state -- legacy status column retired V11) ----

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
                        file_search=genai_types.FileSearch(
                            file_search_store_names=[self.store_resource_name]
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
            # Try to look up by store_doc_id prefix (SUBSTR extraction) or gemini_file_id.
            # Identity contract (Phase 11 spike, 13/13 match): retrieved_context.title
            # is the 12-char file resource ID = SUBSTR(gemini_store_doc_id, 1, hyphen-1).
            # SUBSTR covers all 1,749 indexed files including 1,075 with NULL gemini_file_id.
            row = conn.execute(
                "SELECT filename FROM files "
                "WHERE SUBSTR(gemini_store_doc_id, 1, INSTR(gemini_store_doc_id, '-') - 1) = ? "
                "OR gemini_file_id = ?",
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

    # -- Assertion 7: Per-file searchability sample ----------------------------

    def _check_targeted_searchability(
        self, indexed_count: int, sample_size: int = 5
    ) -> None:
        """Sample N indexed files and verify each is searchable via a targeted query.

        This is the critical upgrade from Phase 15: Assertion 5 proves "search
        returns some results", but this assertion proves "specific indexed files
        are retrievable". Zero tolerance: any miss -> UNSTABLE.

        Episode exclusion: 333 Episode files are excluded from sampling because
        they have zero discriminating metadata (topic/display_title/title all NULL,
        category='unknown', series='Peikoff Podcast'). These files are still
        covered by Assertion 5 (general search returns results).

        Query construction: uses metadata fallback chain:
          display_title -> title -> topic -> filename stem
        Since display_title and title are NULL for all 1,749 files, the effective
        chain is: topic (1,416 files) -> stem (440 files where topic == stem).

        Result matching: checks retrieved_context.title against:
          1. gemini_file_id suffix (exact match, handles 674 files with non-NULL file_id)
          2. gemini_store_doc_id prefix via split('-')[0] (exact match, covers all 1,749)
          3. filename (fallback for display_name changes)

        Store doc prefix matching (Phase 11 identity contract): retrieved_context.title
        == 12-char prefix of gemini_store_doc_id == file resource ID. This covers all
        1,749 indexed files including 1,075 with NULL gemini_file_id.
        """
        if indexed_count == 0:
            self._pass(
                "Assertion 7 -- Per-file searchability",
                "N/A -- store is empty (0 indexed files)",
            )
            return

        if sample_size == 0:
            self._pass(
                "Assertion 7 -- Per-file searchability",
                "N/A -- sample-count=0, assertion skipped",
            )
            return

        if indexed_count < sample_size:
            self._pass(
                "Assertion 7 -- Per-file searchability",
                f"N/A -- only {indexed_count} indexed file(s), need {sample_size} for sample",
            )
            return

        # Build corpus aspect frequency map for S4a fallback (O(n) DB query).
        corpus_freq: dict[str, int] = {}
        try:
            _freq_conn = sqlite3.connect(self.db_path)
            _freq_rows = _freq_conn.execute(
                "SELECT metadata_json FROM file_metadata_ai WHERE is_current = 1"
            ).fetchall()
            _freq_conn.close()
            for (_mj,) in _freq_rows:
                if not _mj:
                    continue
                try:
                    for _a in json.loads(_mj).get("topic_aspects", []):
                        corpus_freq[_a] = corpus_freq.get(_a, 0) + 1
                except Exception:
                    pass
        except Exception as e:
            self._fail("Assertion 7 -- Per-file searchability", f"DB error building corpus frequency map: {e}")
            return

        # Sample N random indexed files from DB.
        #
        # No exclusions. All 1,749 indexed files are in scope:
        # - Episodes (333 files): included. Unique numeric IDs provide exact discrimination.
        # - Office Hour files (60 files): included. AI metadata extracted (2026-02-25).
        # Zero exclusions, zero tolerance: every sampled file must be retrievable.
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                """SELECT f.filename, f.gemini_store_doc_id, f.gemini_file_id, f.file_path,
                          fma.metadata_json AS ai_metadata_json
                   FROM files f
                   LEFT JOIN file_metadata_ai fma
                     ON fma.file_path = f.file_path AND fma.is_current = 1
                   WHERE f.gemini_state = 'indexed'
                     AND f.gemini_store_doc_id IS NOT NULL
                   ORDER BY RANDOM()
                   LIMIT ?""",
                (sample_size,),
            ).fetchall()
            conn.close()
        except Exception as e:
            self._fail("Assertion 7 -- Per-file searchability", f"DB error: {e}")
            return

        if not rows:
            self._pass(
                "Assertion 7 -- Per-file searchability",
                "N/A -- no indexed files with store doc IDs",
            )
            return

        missed = []
        for filename, store_doc_id, gemini_file_id, file_path, ai_metadata_json_str in rows:
            # Construct targeted query from filename stem
            stem = Path(filename).stem  # e.g. "B001 Introduction to Objectivism"
            # Enrich query with metadata: use display_title, title, or topic
            # (display_title and title are NULL for all 1,749 files; topic is the
            # primary discriminating field for MOTM (468) and Other (508) files)
            title = None  # unused — subject always set to stem (see comment below)
            # Always use the full stem as the query subject. The stem is the
            # most specific identifier for every file and exactly matches the
            # Title field in the identity header. Using topic alone fails for:
            # - Course lesson/class files (topic doesn't include course+number)
            # - MOTM series with identical topics (e.g. 9 "History...part" files)
            # - Seminar "Week N" files with generic topics (e.g. "Capitalism")
            # The identity header's Title = stem, so a stem-based query
            # directly leverages the discriminating metadata we added.
            subject = stem
            query = f"What is '{subject}' about?"
            self._verbose(f"Assertion 7: querying for '{filename}' via: {query!r}")

            # Run targeted search
            try:
                response = self.client.models.generate_content(
                    model=SEARCH_MODEL,
                    contents=query,
                    config=genai_types.GenerateContentConfig(
                        tools=[genai_types.Tool(
                            file_search=genai_types.FileSearch(
                                file_search_store_names=[self.store_resource_name]
                            )
                        )]
                    ),
                )
            except Exception as e:
                self._fail(
                    "Assertion 7 -- Per-file searchability",
                    f"API error querying for '{filename}': {e}",
                )
                return

            # Check top-5 grounding chunks for the target file (TOP_K = 5 per Phase 16.5).
            # Phase 11 finding: retrieved_context.title returns the raw file
            # resource ID (e.g. "yg1gquo3eo88"), NOT the display_name.
            # DB stores: gemini_file_id = "files/yg1gquo3eo88"
            #            gemini_store_doc_id = "yg1gquo3eo88-hyzl1kilgv1v"
            # Primary match: strip "files/" from gemini_file_id and compare
            # directly to title (same approach as measure_searchability_lag.py).
            expected_file_id = (gemini_file_id or "").replace("files/", "")
            # Pre-compute store doc prefix for exact prefix matching.
            # Identity contract: title_in_result == store_doc_id prefix (12-char).
            store_doc_prefix = store_doc_id.split("-")[0] if store_doc_id else ""
            found = False
            if response.candidates:
                gm = getattr(response.candidates[0], "grounding_metadata", None)
                if gm:
                    chunks = getattr(gm, "grounding_chunks", []) or []
                    for chunk in chunks[:5]:
                        rc = getattr(chunk, "retrieved_context", None)
                        if not rc:
                            continue
                        title_in_result = getattr(rc, "title", "") or ""
                        if not title_in_result:
                            continue
                        # Primary: exact match on file resource ID
                        if expected_file_id and title_in_result == expected_file_id:
                            found = True
                            break
                        # Secondary: exact match on store_doc_id prefix
                        # (covers all 1,749 files including 1,075 with NULL gemini_file_id
                        # and the 1 mismatch file where prefix != file_id suffix)
                        if store_doc_prefix and title_in_result == store_doc_prefix:
                            found = True
                            break
                        # Tertiary: match by filename (if display_name changes)
                        if filename in title_in_result:
                            found = True
                            break

            if not found:
                # S4a fallback: top-3 rarest aspects, no preamble (per Phase 16.5 fix)
                aspects_s4a: list[str] = []
                if ai_metadata_json_str:
                    try:
                        aspects_s4a = json.loads(ai_metadata_json_str).get("topic_aspects", []) or []
                    except Exception:
                        pass
                if aspects_s4a:
                    _sorted = sorted(aspects_s4a, key=lambda a: corpus_freq.get(a, 0))
                    _cleaned = [re.sub(r"[*_`]", "", a) for a in _sorted[:3]]
                    s4a_query = " ".join(_cleaned)
                    if s4a_query:
                        self._verbose(
                            f"Assertion 7: S4a fallback for '{filename}': {s4a_query!r}"
                        )
                        try:
                            s4a_response = self.client.models.generate_content(
                                model=SEARCH_MODEL,
                                contents=s4a_query,
                                config=genai_types.GenerateContentConfig(
                                    tools=[genai_types.Tool(
                                        file_search=genai_types.FileSearch(
                                            file_search_store_names=[self.store_resource_name]
                                        )
                                    )]
                                ),
                            )
                            if s4a_response.candidates:
                                gm_s4a = getattr(s4a_response.candidates[0], "grounding_metadata", None)
                                if gm_s4a:
                                    chunks_s4a = getattr(gm_s4a, "grounding_chunks", []) or []
                                    for chunk_s4a in chunks_s4a[:5]:
                                        rc_s4a = getattr(chunk_s4a, "retrieved_context", None)
                                        if not rc_s4a:
                                            continue
                                        title_s4a = getattr(rc_s4a, "title", "") or ""
                                        if expected_file_id and title_s4a == expected_file_id:
                                            found = True
                                            break
                                        if store_doc_prefix and title_s4a == store_doc_prefix:
                                            found = True
                                            break
                        except Exception as e_s4a:
                            self._verbose(
                                f"Assertion 7: S4a API error for '{filename}': {e_s4a}"
                            )

            if not found:
                missed.append(filename)
                self._verbose(
                    f"Assertion 7: '{filename}' NOT found via S1 or S4a fallback"
                )

        # Zero tolerance: every sampled file must be retrievable. Any miss means
        # the corpus has a real retrieval problem that must be fixed — not hidden.
        # Episodes (333 files) are included — verified retrievable 5/5 at rank 1
        # (2026-02-25) via unique numeric IDs in identity header Title field.
        # Office Hour files (60 files) are temporarily excluded pending
        # batch-extract + re-upload (see TODO above).
        max_misses = 0
        if len(missed) == 0:
            self._pass(
                "Assertion 7 -- Per-file searchability",
                f"{len(rows)}/{len(rows)} sampled files retrievable (no exclusions)",
            )
        else:
            self._fail(
                "Assertion 7 -- Per-file searchability",
                f"{len(missed)}/{len(rows)} files not retrievable (no exclusions, zero tolerance): "
                f"{missed[:5]}{'...' if len(missed) > 5 else ''}",
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
        print(f"  Sample: {self.sample_size} indexed files (Assertion 7)")
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
        store_doc_full_names: set = set()
        for doc in docs:
            name = getattr(doc, "name", "") or ""
            if name:
                store_doc_full_names.add(name)
                # Extract suffix after "documents/" to match DB format
                # DB stores document_name from operation response (e.g. "xxx-yyy")
                # Store returns full resource name (e.g. "fileSearchStores/.../documents/xxx-yyy")
                suffix = name.split("/documents/")[-1] if "/documents/" in name else name
                store_doc_names.add(suffix)
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

        # Step 5: Per-file searchability sample (Assertion 7)
        print(_head("Per-file searchability sample..."))
        self._check_targeted_searchability(indexed_count, self.sample_size)

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
        "--sample-count",
        type=int,
        default=5,
        help="Number of random indexed files to verify in Assertion 7 (default: 5, 0=skip)",
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
        sample_size=args.sample_count,
    )
    return asyncio.run(checker.run())


if __name__ == "__main__":
    sys.exit(main())
