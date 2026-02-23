# Phase 16: Full Library Upload - Research

**Researched:** 2026-02-23
**Domain:** Gemini File Search FSM-managed upload at 1,748-file production scale
**Confidence:** HIGH (codebase investigation, SDK verification, prior phase artifacts)

## Summary

Phase 16 scales the FSM-managed upload pipeline from the 50-file proxy corpus (Phase 12) to the full 1,748-file production library. The codebase is mature: `FSMUploadOrchestrator`, `RecoveryManager/RecoveryCrawler`, `retry_failed_file()`, `downgrade_to_failed()`, and `check_stability.py` (7 assertions) are all production-ready from Phases 10-15. The primary code changes needed are: (1) adding 429 in-place retry with exponential backoff to `_upload_fsm_file()` and `_poll_fsm_operation()`, (2) implementing TUI-09 (top_k=20, rank display, citation count, scroll hints), (3) raising the `get_fsm_pending_files()` default limit from 50 to handle ~1,748 files, and (4) fixing store name defaults across CLI commands.

The current DB state shows 90 files already indexed (Phase 12/14/15 corpus) and 1,658 untracked .txt files remaining. The `fsm-upload` command at `--concurrency 10 --limit 0 --batch-size 10` will process all untracked files. The existing retry pass (30s cooldown per batch), RecoveryCrawler at startup, and the post-upload remediation loop (store-sync + downgrade_to_failed + retry_failed_file) provide the full recovery chain.

**Primary recommendation:** The upload infrastructure is ready. Focus planning on: (1) the 429 retry wrapper (surgical addition to `_upload_fsm_file`), (2) TUI-09 changes (search client, results widget, run_tui init), (3) correct store name arguments for every Phase 16 command, and (4) the temporal stability protocol execution sequence.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
1. **429 handling:** In-place retry (no FAILED transition), exponential backoff base 1s max 60s, full jitter, max 5 retries. Only FAILED after transient retry budget exhausted.
2. **Success definition:** Zero non-indexed AFTER complete remediation loop (upload -> store-sync -> downgrade_to_failed -> retry pass), not zero failures during first pass.
3. **TUI-09 rank:** Flat chunk list (up to 20), rank = chunk index + 1, "N citations retrieved" banner, scroll hint when overflow detected.
4. **Assertion 7 sample count:** 20 for all Phase 16 check_stability calls (--sample-count 20).
5. **store-sync timing:** Upload completes -> 60s cooldown -> store-sync dry-run -> store-sync actual if orphans -> check_stability T=0.
6. **RecoveryCrawler:** Called automatically at startup of upload command (before new batch). Already implemented in `UploadOrchestrator.run()` and `EnrichedUploadOrchestrator.run_enriched()`. NOTE: `FSMUploadOrchestrator.run_fsm()` does NOT call RecoveryCrawler -- this is a gap.
7. **Phase 07-07:** Structured manual walkthrough (5+ diverse search queries, results recorded verbatim), not automated test suite.
8. **File count denominator:** Run `objlib status` at start of 16-01 to record exact count.

### Claude's Discretion
- TUI-09 implementation details beyond the locked decisions (widget structure, CSS, etc.)
- Exact batch_size for the full upload run (10 is validated; larger possible)
- Log verbosity and monitoring output during upload

### Deferred Ideas (OUT OF SCOPE)
- Automated Phase 07-07 test suite (Textual pilot tests)
- Stratified sampling for Assertion 7 (pure random is sufficient)
- Visual grouping of same-file citations in TUI
</user_constraints>

## Standard Stack

### Core (Already In Use)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| google-genai | installed | Gemini File Search SDK (upload, import, query) | Only supported SDK for File Search stores |
| python-statemachine | 2.6.0 | FSM transition validation | Phase 10 choice; lightweight, async-compatible |
| aiosqlite | installed | Async SQLite state management | WAL mode, OCC guards, no held transactions across await |
| asyncio | stdlib | Concurrency (Semaphore, gather, sleep) | Standard async I/O |
| textual | installed | TUI framework | Already in use for TUI (VerticalScroll, App, widgets) |
| tenacity | installed | Retry with exponential backoff (existing search client) | Already used in `GeminiSearchClient.query_with_retry()` |
| rich | installed | CLI output formatting | Already used throughout |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| keyring | installed | API key storage | Authentication for all Gemini operations |
| typer | installed | CLI framework | All CLI commands |

### No New Dependencies
Phase 16 requires zero new pip packages. All 429 retry logic uses stdlib `asyncio.sleep()` + `random.random()` for jitter.

## Architecture Patterns

### Recommended Project Structure
No new files need to be created. All changes go into existing modules:

```
src/objlib/upload/orchestrator.py  # Add 429 retry wrapper to _upload_fsm_file / _poll_fsm_operation
src/objlib/upload/orchestrator.py  # Add RecoveryCrawler call to run_fsm()
src/objlib/search/client.py        # Add top_k parameter to query() method
src/objlib/tui/widgets/results.py  # Add rank display, citation count banner, scroll hints
src/objlib/tui/__init__.py         # Update DEFAULT_STORE_NAME
src/objlib/services/search.py      # Thread top_k through to query call
scripts/check_stability.py         # No code changes; just --sample-count 20 at invocation
```

### Pattern 1: 429 In-Place Retry (New Code)
**What:** Catch `RateLimitError` before FSM FAILED transition; retry with exponential backoff + full jitter.
**When to use:** In `_upload_fsm_file()` wrapping the upload+import API call, and potentially in `_poll_fsm_operation()`.
**Example:**
```python
# In FSMUploadOrchestrator._upload_fsm_file(), replacing the current RateLimitError handler:
import random

MAX_429_RETRIES = 5
BASE_DELAY = 1.0  # seconds
MAX_DELAY = 60.0  # seconds

for attempt in range(MAX_429_RETRIES):
    try:
        async with self._upload_semaphore:
            file_obj, operation = await self._client.upload_and_import(
                upload_path, display_name, custom_metadata
            )
        break  # Success
    except RateLimitError as exc:
        if attempt == MAX_429_RETRIES - 1:
            raise  # Exhaust budget -> fall through to FAILED handler
        delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
        jittered = random.random() * delay  # full jitter
        logger.warning(
            "429 rate limit on %s (attempt %d/%d), retrying in %.1fs",
            file_path, attempt + 1, MAX_429_RETRIES, jittered,
        )
        await asyncio.sleep(jittered)
```
**Source:** Locked decision #1 from CONTEXT.md; exponential backoff + full jitter is AWS best practice.

### Pattern 2: RecoveryCrawler at FSM Upload Startup (Gap Fix)
**What:** `FSMUploadOrchestrator.run_fsm()` currently does NOT call RecoveryCrawler, unlike its parent classes. This is a gap.
**When to use:** Add at the start of `run_fsm()`, after signal handler setup, before store resolution.
**Evidence:** Parent `UploadOrchestrator.run()` (line 129) and `EnrichedUploadOrchestrator.run_enriched()` (line 501) both call `RecoveryManager.run()`. But `FSMUploadOrchestrator.run_fsm()` (line 1010) skips this entirely -- it jumps straight to "Ensure store exists."
**Example:**
```python
async def run_fsm(self, store_display_name: str) -> dict[str, int]:
    self.setup_signal_handlers()

    # Step 0: Run crash recovery (MISSING -- add this)
    recovery = RecoveryManager(self._client, self._state, self._config)
    recovery_result = await recovery.run()
    if recovery_result.recovered_operations > 0 or recovery_result.reset_to_pending > 0:
        logger.info(
            "Recovery: %d ops recovered, %d files reset to pending",
            recovery_result.recovered_operations,
            recovery_result.reset_to_pending,
        )

    # Also run RecoveryCrawler for FSM-specific write-ahead intents
    from objlib.upload.recovery import RecoveryCrawler
    crawler = RecoveryCrawler(self._state, self._client)
    recovered, occ_failures = await crawler.recover_all()
    if recovered:
        logger.info("RecoveryCrawler recovered %d files", len(recovered))

    # Step 1: Ensure store exists...
```

### Pattern 3: TUI-09 top_k Integration
**What:** Thread `top_k` parameter from FileSearch SDK through the search pipeline.
**SDK verification:** `types.FileSearch(file_search_store_names=[...], top_k=20)` confirmed working via `python3 -c "from google.genai import types; fs = types.FileSearch(file_search_store_names=['test'], top_k=20); print(fs)"`
**Where to change:**
1. `GeminiSearchClient.query()` -- add `top_k: int = 20` parameter, pass to `types.FileSearch(top_k=top_k)`
2. `GeminiSearchClient.query_with_retry()` -- pass through `top_k`
3. `SearchService.search()` -- accept and pass through `top_k`
4. `ObjlibApp._run_search()` -- pass `top_k` to search service (or use default)

### Pattern 4: Full-Scale Upload Limit
**What:** The `get_fsm_pending_files()` default limit is 50. The CLI `fsm-upload` also defaults to `--limit 50`. For Phase 16, pass `--limit 0` (which maps to 10000 in code at line 1045: `limit = self._file_limit if self._file_limit > 0 else 50`).
**CRITICAL BUG:** At line 1045 of orchestrator.py, `run_fsm()` uses `limit = ... else 50` -- this caps at 50 files even with `--limit 0`. Need to change to `else 10000` (matching the parent classes) or a large number.

### Anti-Patterns to Avoid
- **Wrong store name:** `store-sync` defaults to `objectivism-library-test`, `fsm-upload` defaults to `objectivism-library`, TUI defaults to `objectivism-library-test`. ALWAYS explicitly pass `--store objectivism-library` to every Phase 16 command.
- **Running store-sync during active upload:** Race condition risk. Only run after upload completes + 60s cooldown.
- **Assuming first-pass perfection:** Success criterion is zero non-indexed AFTER remediation, not during first pass.
- **Forgetting RecoveryCrawler:** run_fsm() currently lacks it. Must add before Phase 16 execution.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 429 exponential backoff | Custom retry framework | `asyncio.sleep(random.random() * min(BASE * 2^attempt, MAX))` | Simple stdlib math; tenacity overkill for 5-retry loop inside existing code |
| Store document listing pagination | Custom pagination | `client.list_store_documents()` (already handles async for loop via SDK pager) | SDK returns an async pager that handles pagination automatically |
| Upload concurrency | Custom thread pool | `asyncio.Semaphore(10)` already in orchestrator | Phase 14 validated c=10 with Semaphore approach |
| FSM validation | Manual state checks | `create_fsm(state).start_upload()` | python-statemachine validates transitions; ephemeral FSM pattern from Phase 10 |
| OCC conflict handling | Locking | `WHERE version = ?` guard in SQL UPDATE | Already implemented in all `transition_to_*()` methods |

**Key insight:** The codebase already has all the infrastructure. Phase 16 changes are surgical additions to existing code, not new subsystems.

## Common Pitfalls

### Pitfall 1: Store Name Mismatch Across Commands
**What goes wrong:** Running `store-sync` or TUI without `--store objectivism-library` uses the wrong store (objectivism-library-test), causing "store not found" errors or operating on the wrong data.
**Why it happens:** Different commands have different default store names (historical artifact from Phase 1 -> Phase 8 migration). The defaults were never fully harmonized.
**How to avoid:** Document exact command syntax for every Phase 16 operation. Always pass `--store objectivism-library` explicitly.
**Warning signs:** "Store 'X' not found" errors; store-sync showing 0 documents when you expect ~1,748.
**Current defaults:**
- `fsm-upload`: `objectivism-library` (CORRECT for Phase 16)
- `store-sync`: `objectivism-library-test` (WRONG -- must override)
- `tui` / `run_tui()`: `objectivism-library-test` (WRONG -- must override or update default)
- `check_stability.py`: `objectivism-library` (CORRECT for Phase 16)
- `search` CLI: `objectivism-library-v1` (WRONG -- must override)

### Pitfall 2: FSMUploadOrchestrator.run_fsm() Limit Cap at 50
**What goes wrong:** Passing `--limit 0` (intended to mean "all files") only processes 50 files because line 1045 in orchestrator.py says `limit = self._file_limit if self._file_limit > 0 else 50`.
**Why it happens:** The FSM orchestrator was built for Phase 12's 50-file proxy corpus. The parent classes use `else 10000`.
**How to avoid:** Either fix the code to use `else 10000`, or always pass an explicit large `--limit` value (e.g., `--limit 2000`).
**Warning signs:** Upload finishes suspiciously fast; summary shows "Total files: 50" when you expected ~1,658.

### Pitfall 3: RecoveryCrawler Not Called in run_fsm()
**What goes wrong:** Files stuck in `uploading`/`processing` from a prior interrupted run are not recovered at startup, causing them to block or error.
**Why it happens:** `run_fsm()` was written from scratch and doesn't call the recovery code that `run()` and `run_enriched()` include. Oversight.
**How to avoid:** Add RecoveryManager + RecoveryCrawler calls at the top of `run_fsm()` before processing.
**Warning signs:** OCC conflict errors on files that are in unexpected states; files remaining in `uploading` state after run completes.

### Pitfall 4: 429 Rate Limits Causing Unnecessary FAILED Transitions
**What goes wrong:** Current `_upload_fsm_file()` catches `RateLimitError` and immediately transitions to FAILED state (line 1347-1352). At 1,748 files with c=10, 429s are likely and would cause hundreds of unnecessary FAILED transitions.
**Why it happens:** The current code was adequate for 50-file scale where 429s were rare.
**How to avoid:** Wrap the upload API call in a 429-specific retry loop (locked decision #1). Only fall through to FAILED after 5 retry attempts exhausted.
**Warning signs:** High FAILED count during first pass; many files needing remediation loop.

### Pitfall 5: Import-to-Searchable Lag Causing False T=0 Failures
**What goes wrong:** Running check_stability.py immediately after upload completes may show Assertion 7 failures for files that haven't finished import-to-searchable propagation.
**Why it happens:** P95 import-to-searchable lag is 10.1s. Files uploaded in the last batch may not be searchable yet.
**How to avoid:** Wait 60 seconds after upload completes before running check_stability.py (locked decision #5).
**Warning signs:** Assertion 7 shows misses that disappear on re-run 60 seconds later.

### Pitfall 6: store-sync Pagination at Full Scale
**What goes wrong:** `list_store_documents()` may need to paginate through ~1,748+ documents. The SDK pager handles this automatically via async iteration.
**Why it happens:** At Phase 12 scale (50-90 docs), pagination was never exercised. At 1,748+ docs, the SDK may return multiple pages.
**How to avoid:** The existing `list_store_documents()` implementation (line 380 in client.py) uses `async for doc in pager:` which handles pagination correctly. No code change needed, but verify at full scale during 16-01.
**Warning signs:** `list_store_documents()` returning fewer documents than expected; timeout during listing.

## Code Examples

### Current 429 Handling (To Be Replaced)
```python
# src/objlib/upload/orchestrator.py, _upload_fsm_file(), lines 1347-1356
# CURRENT: RateLimitError -> immediate FAILED transition
except RateLimitError as exc:
    logger.warning("Rate limited uploading %s: %s", file_path, exc)
    try:
        await self._state.transition_to_failed(file_path, version, str(exc))
    except OCCConflictError:
        pass
    self._failed += 1
    if self._progress is not None:
        self._progress.file_rate_limited(file_path)
    return None
```

### GeminiSearchClient.query() (To Add top_k)
```python
# src/objlib/search/client.py, lines 51-82
# CURRENT: No top_k parameter
def query(self, query: str, metadata_filter: str | None = None, model: str = "gemini-2.5-flash") -> Any:
    config = types.GenerateContentConfig(
        tools=[types.Tool(
            file_search=types.FileSearch(
                file_search_store_names=[self._store_resource_name],
                metadata_filter=metadata_filter,
                # ADD: top_k=top_k
            )
        )],
    )
```

### ResultsList.update_results() (To Add Rank Display)
```python
# src/objlib/tui/widgets/results.py, lines 134-147
# CURRENT: Shows "{count} results" header, no rank per citation
def update_results(self, citations: list[Citation]) -> None:
    self.remove_children()
    if not citations:
        self.mount(Static("No results found"))
    else:
        self.mount(Static(f"{len(citations)} results"))  # -> "N citations retrieved"
        for i, citation in enumerate(citations):
            self.mount(ResultItem(citation, i))  # ResultItem needs rank display
```

### ResultItem.__init__() (To Show Rank)
```python
# src/objlib/tui/widgets/results.py, lines 47-97
# CURRENT: Shows filename, metadata, excerpt
# NEED: Add rank display like "[3 / 20]" before filename
# Citation.index is already 1-based from extract_citations() (line 74 of citations.py)
```

### check_stability.py Invocation (Phase 16)
```bash
# All Phase 16 stability checks use --sample-count 20
python scripts/check_stability.py --store objectivism-library --sample-count 20 --verbose
```

### Full Upload Command (Phase 16)
```bash
# Phase 16 production upload
# --concurrency 10: validated in Phase 14
# --limit 2000: ensure all ~1,658 untracked files are processed (code bug: --limit 0 caps at 50)
# --no-reset-existing: don't re-upload already indexed files
# --batch-size 10: matches Phase 12/14 validated batch size
objlib fsm-upload --store objectivism-library --concurrency 10 --limit 2000 --batch-size 10
```

### Post-Upload Remediation Loop
```bash
# 1. Wait 60 seconds for import-to-searchable lag
sleep 60

# 2. store-sync dry-run (MUST override default store name!)
python -m objlib store-sync --store objectivism-library --dry-run

# 3. store-sync actual (if orphans found)
python -m objlib store-sync --store objectivism-library --no-dry-run --yes

# 4. check_stability T=0
python scripts/check_stability.py --store objectivism-library --sample-count 20 --verbose

# 5. If FAILED files remain, retry them
# (done via re-running fsm-upload which skips indexed files, picks up untracked from retry_failed_file)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Status column (pending/uploading/indexed) | gemini_state FSM (5 states, OCC-guarded) | Phase 8-10 | All Phase 16 uses FSM path exclusively |
| objectivism-library-test store | objectivism-library (production) | Phase 8 migration | Must explicitly pass --store to commands with wrong defaults |
| 5-file Assertion 7 sample | 20-file sample for Phase 16 | Phase 15 | --sample-count 20 in all Phase 16 stability checks |
| No 429 retry (immediate FAILED) | In-place retry with backoff (Phase 16) | Phase 16 (new) | Prevents unnecessary FAILED transitions at scale |

**Deprecated/outdated:**
- `UploadOrchestrator.run()` and `EnrichedUploadOrchestrator.run_enriched()`: superseded by `FSMUploadOrchestrator.run_fsm()` for all new uploads
- `objectivism-library-test` store name: migration to `objectivism-library` happened in Phase 8. Some CLI defaults still reference the old name.

## Critical Code Issues Found

### Issue 1: run_fsm() Limit Cap (BLOCKER)
**File:** `src/objlib/upload/orchestrator.py`, line 1045
**Code:** `limit = self._file_limit if self._file_limit > 0 else 50`
**Problem:** With `--limit 0`, only 50 files are processed. Parent class uses `else 10000`.
**Fix:** Change `else 50` to `else 10000` (or use a constant).

### Issue 2: run_fsm() Missing RecoveryCrawler (BLOCKER)
**File:** `src/objlib/upload/orchestrator.py`, `run_fsm()` method (line 1010)
**Problem:** Does not call `RecoveryManager.run()` or `RecoveryCrawler.recover_all()` at startup.
**Fix:** Add recovery calls after signal handler setup, matching `run()` and `run_enriched()` patterns.

### Issue 3: Store Name Defaults (HIGH)
**Files:** Multiple CLI commands
**Problem:** `store-sync` defaults to `objectivism-library-test`; `tui/__init__.py` defaults to `objectivism-library-test`.
**Fix:** Either update defaults to `objectivism-library` or document explicit `--store` flags for every Phase 16 command.

### Issue 4: 429 Handling (HIGH)
**File:** `src/objlib/upload/orchestrator.py`, `_upload_fsm_file()` lines 1347-1356
**Problem:** `RateLimitError` causes immediate FAILED transition. At scale, 429s are expected.
**Fix:** Add in-place retry loop per locked decision #1.

## DB State Snapshot (Phase 16 Entry)

```
gemini_state | count
-------------|------
indexed      | 90     (Phase 12/14/15 proxy corpus)
untracked    | 1794   (includes 1658 .txt + 136 non-.txt)

.txt files with gemini_state='untracked': 1658
.txt files with gemini_state='indexed': 90
Total .txt files: 1748
```

The upload denominator for Phase 16 is 1,658 new + 90 already indexed = 1,748 total target. Success criterion: all 1,748 .txt files reach `gemini_state='indexed'`.

## Open Questions

1. **TUI store name override mechanism**
   - What we know: `run_tui()` hardcodes `DEFAULT_STORE_NAME = "objectivism-library-test"`. The `tui` CLI command passes no store argument.
   - What's unclear: Should we update the default or add a CLI flag?
   - Recommendation: Update `DEFAULT_STORE_NAME` to `"objectivism-library"` in `tui/__init__.py`. This is the permanent production store post-Phase 8 migration.

2. **Store-sync default store name**
   - What we know: `store-sync` defaults to `objectivism-library-test`.
   - What's unclear: Should the default be updated to match production?
   - Recommendation: Update default to `objectivism-library` for consistency. But for Phase 16, always pass `--store objectivism-library` explicitly regardless.

3. **Upload duration estimate**
   - What we know: Phase 12 uploaded 50 files in approximately 10-15 minutes with c=2. Phase 14 validated c=10.
   - What's unclear: Exact wall-clock time for 1,658 files at c=10 with 1s stagger + rate limiting.
   - Recommendation: Estimate ~2-4 hours based on: 1,658 files / c=10 effective parallelism / ~3s per file average (upload + poll). Plan for interruption recovery via RecoveryCrawler.

## Sources

### Primary (HIGH confidence)
- **Codebase inspection:** All findings from direct reading of source files in `src/objlib/upload/`, `src/objlib/search/`, `src/objlib/tui/`, `scripts/check_stability.py`
- **SDK verification:** `python3 -c "from google.genai import types; help(types.FileSearch)"` confirms `topK: Optional[int]` parameter
- **SDK verification:** `types.FileSearch(file_search_store_names=['test'], top_k=20)` confirmed working
- **DB state:** Direct SQLite queries against `data/library.db`

### Secondary (HIGH confidence)
- **Phase 15 VERIFICATION.md:** Confirms VLID-07 gate PASS, 7-assertion stability checker operational, 5-20% query-specificity gap documented
- **Phase 15-03 SUMMARY.md:** Assertion 7 implementation details, tolerance formula `max(1, N//5)`
- **CONTEXT.md / CLARIFICATIONS-ANSWERED.md:** All 8 locked decisions from multi-provider synthesis

### Tertiary (MEDIUM confidence)
- **Upload duration estimate:** Extrapolated from Phase 12/14 empirical data; actual duration depends on API load conditions

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new dependencies; all libraries already in use and verified
- Architecture: HIGH - codebase inspected line-by-line; all patterns derived from existing code
- Pitfalls: HIGH - discovered 4 concrete code issues from direct source reading
- TUI-09: HIGH - SDK parameter verified; widget structure understood from reading results.py and app.py

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (stable codebase, no fast-moving external dependencies)
