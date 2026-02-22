# Phase 15: Wave 7 -- FSM Consistency and store-sync Contract - Research

**Researched:** 2026-02-22
**Domain:** Gemini File Search searchability lag measurement, FSM/store-sync reconciliation, temporal stability
**Confidence:** HIGH

## Summary

Phase 15 bridges the gap between "listed in the store" (Phase 11: P99=0.253s) and "actually searchable via semantic query" -- a distinction all three AI providers identified as the critical gray area. The codebase already has all primitives needed: `GeminiSearchClient.query()` for search, `check_stability.py` for temporal verification, `retry_failed_file()` for the FAILED escape path, and the store-sync CLI for orphan cleanup. The primary engineering work is (1) a new standalone lag measurement script that uploads 20 files sequentially and polls with targeted per-file queries until each is searchable, and (2) a reconciliation policy document plus a small code addition to downgrade FSM state when store-sync finds inconsistencies.

The search path through the CLI (`GeminiSearchClient.query()` -> `generate_content()` with `FileSearch` tool -> grounding_metadata -> citations) is well-understood and stable. The lag measurement script must use this same code path (or its raw equivalent) with per-file targeted queries -- NOT `list_store_documents()` and NOT the default `check_stability.py` query. The key technical risk is query design: queries must be specific enough to unambiguously identify a single file, but general enough to succeed once the file is searchable.

**Primary recommendation:** Build `scripts/measure_searchability_lag.py` as a standalone script (like `check_stability.py`) that uses the raw `genai` SDK to perform targeted searches. Use nearest-rank percentiles on n=20 with empirical max as P99 bound.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
1. **"Searchable" definition:** Targeted semantic search query returns target file in top-10. Uses same code path as end-user CLI. Per-file queries from actual file content -- NO sentinel injection, NO generic queries.
2. **Lag clock T=0:** When upload+import API returns success. Record three timestamps: T_import, T_listed (list_store_documents() first shows it), T_searchable (search query hit). Lag = T_searchable - T_import. Sequential imports.
3. **Silent failure threshold:** 300s hard timeout = silent failure. Excluded from percentile stats; reported as failure_rate.
4. **FSM/store-sync resolution:** Store-sync (empirical searchability) is authoritative. If FSM=INDEXED but targeted search fails after 300s -> log INCONSISTENT, downgrade to FAILED. No new FSM states. No auto-deletes.
5. **Test file selection:** 20 files from Phase 12 50-file corpus. Per-file queries from actual content (unique phrases/Objectivist terminology). Pre-validate: run each query against live store, confirm target file appears.
6. **P99 reporting:** Nearest-rank P50 + P95 on n=20, plus empirical max labeled "P99/max (n=20, empirical bound)".
7. **store-sync role:** Scheduled + targeted post-run. After each fsm-upload batch: run store-sync. Escalation clause if failure rate > 0.
8. **Temporal stability ceremony:** Stateless standalone check_stability.py. SKEPTICAL posture. Fresh Claude sessions NOT required for T+4h/T+24h.

### Claude's Discretion
- Script architecture decisions (file structure, class vs function organization)
- Polling backoff parameters within the locked 300s window
- Query phrasing strategy for the 20 test files
- SUMMARY.md and contract documentation format
- How to implement the FSM downgrade (direct DB write vs state manager method)

### Deferred Ideas (OUT OF SCOPE)
- No new FSM states (VERIFY_FAILED, ORPHAN_REMOTE, etc.)
- No auto-deletes from store-sync
- No per-file lightweight routine verification after every single upload
- No sentinel string injection into test files
- No running full measurement twice one week apart for reproducibility
</user_constraints>

## Standard Stack

### Core (Already in Project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| google-genai | (installed) | Gemini File Search API: upload, import, search, list | Only SDK for Gemini File Search |
| aiosqlite | (installed) | Async SQLite for state management | Used by AsyncUploadStateManager |
| keyring | (installed) | API key retrieval | Existing pattern (check_stability.py uses it) |
| python-statemachine | 2.6.0 | FSM validation (create_fsm()) | Phase 9 confirmed |
| tenacity | (installed) | Retry with backoff for search queries | Used by GeminiSearchClient |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| statistics (stdlib) | 3.13 | Percentile computation (median, quantiles) | For P50/P95 nearest-rank |
| math (stdlib) | 3.13 | ceil() for nearest-rank index | Percentile calculation |
| time (stdlib) | 3.13 | perf_counter() for high-resolution timing | T_import, T_listed, T_searchable |
| json (stdlib) | 3.13 | Parse metadata_json for query design | Reading file metadata |
| argparse (stdlib) | 3.13 | CLI for lag measurement script | Same pattern as check_stability.py |

### Alternatives Considered
None -- all decisions are locked. Use the existing project stack.

**Installation:**
No new packages required. All dependencies already installed.

## Architecture Patterns

### Recommended Project Structure
```
scripts/
    check_stability.py          # Existing -- temporal stability (6 assertions)
    measure_searchability_lag.py # NEW -- 15-01 lag measurement script
src/objlib/
    upload/
        orchestrator.py         # Existing FSMUploadOrchestrator (for understanding upload flow)
        state.py                # Existing transition methods (transition_to_failed for downgrade)
        recovery.py             # Existing retry_failed_file() (escape path for downgraded files)
        fsm.py                  # Existing FileLifecycleSM (validation only)
    search/
        client.py               # Existing GeminiSearchClient.query() (reference for search pattern)
governance/
    store-sync-contract.md      # NEW -- 15-02 FSM/store-sync contract documentation
```

### Pattern 1: Standalone Script with Raw SDK (check_stability.py Pattern)
**What:** Scripts that verify system state use the raw `genai` SDK directly, not the objlib search layer. This provides independence from application code bugs.
**When to use:** For measurement and verification scripts (not application features).
**Example:**
```python
# Source: scripts/check_stability.py lines 346-356
# Search uses raw genai SDK -- same as check_stability.py Assertion 5
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=query,
    config=genai_types.GenerateContentConfig(
        tools=[genai_types.Tool(
            file_search=genai_types.FileSearch(
                file_search_store_names=[store_resource_name]
            )
        )]
    ),
)
# Extract citations from grounding_metadata
citations = []
if response.candidates:
    gm = getattr(response.candidates[0], "grounding_metadata", None)
    if gm:
        chunks = getattr(gm, "grounding_chunks", []) or []
        for chunk in chunks:
            rc = getattr(chunk, "retrieved_context", None)
            if rc:
                citations.append(rc)
```

### Pattern 2: Sequential Upload + Poll Loop (Phase 11 Lag Measurement Pattern)
**What:** Upload one file, poll until condition met, record timing, then upload next. Sequential prevents confounding from concurrent API load.
**When to use:** For measuring import-to-searchable lag where each file must be isolated.
**Example:**
```python
# Source: spike/phase11_spike/lag_measurement.py adapted for searchability
# Three timestamps per file:
t_import = time.perf_counter()  # When upload+import returns success
# ... poll list_store_documents() for T_listed ...
# ... poll search query for T_searchable ...
lag = t_searchable - t_import  # Primary metric
listing_gap = t_listed - t_import  # Secondary (should be ~0.25s per Phase 11)
```

### Pattern 3: Nearest-Rank Percentile on Small N
**What:** For n=20, use `math.ceil(p/100 * n) - 1` as the index into sorted data.
**When to use:** When computing P50/P95 from exactly 20 measurements.
**Example:**
```python
import math

def nearest_rank_percentile(sorted_data: list[float], p: int) -> float:
    """Nearest-rank percentile. p is 0-100."""
    n = len(sorted_data)
    idx = math.ceil(p / 100 * n) - 1
    return sorted_data[max(0, idx)]

# For n=20:
# P50 -> sorted[9]  (10th value)
# P95 -> sorted[18] (19th value)
# P99/max -> sorted[19] = max (empirical bound)
```

### Pattern 4: FSM State Downgrade via Direct DB Write
**What:** When store-sync finds INDEXED files that are not actually searchable, downgrade them to FAILED using the same pattern as `retry_failed_file()`.
**When to use:** For the reconciliation policy (15-02).
**Example:**
```python
# Modeled on recovery.py:retry_failed_file() -- the documented 6th write site
# This would be a 7th authorized write site or reuse the existing transition_to_failed()
async def downgrade_indexed_to_failed(
    state: AsyncUploadStateManager, file_path: str, reason: str
) -> bool:
    db = state._ensure_connected()
    now = state._now_iso()
    cursor = await db.execute(
        """UPDATE files
           SET gemini_state = 'failed',
               error_message = ?,
               gemini_state_updated_at = ?,
               version = version + 1
           WHERE file_path = ?
             AND gemini_state = 'indexed'""",
        (reason, now, file_path),
    )
    await db.commit()
    return cursor.rowcount == 1
```

### Anti-Patterns to Avoid
- **Using check_stability.py's default query for lag measurement:** The default query ("Ayn Rand theory of individual rights and capitalism") tests general searchability, not whether a SPECIFIC file is searchable. Lag measurement MUST use per-file targeted queries.
- **Using list_store_documents() as "searchable" proxy:** Phase 11 proved listing visibility (P99=0.253s) is NOT the same as search query retrieval. The document may be listed but not yet indexed in the vector store.
- **Including silent failures in percentile stats:** 300s timeout files must be excluded from P50/P95 and reported separately as failure_rate.
- **Auto-deleting from store-sync on disagreement:** The locked decision prohibits auto-deletes. Operator must run `store-sync --no-dry-run` explicitly.
- **Concurrent uploads during lag measurement:** Must be sequential to avoid confounding. Upload file N, measure, then upload file N+1.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Gemini search query | Custom embedding lookup | `client.models.generate_content()` with `FileSearch` tool | Must match CLI search path; Gemini handles embedding + retrieval |
| API key retrieval | env var parsing | `keyring.get_password("objlib-gemini", "api_key")` | Existing pattern in check_stability.py and all scripts |
| Store resolution | Hardcoded store name | `client.file_search_stores.list()` loop matching display_name | Store resource name changes; resolution by display_name is standard |
| Retry logic for search | Custom retry loops | `tenacity` with exponential backoff | Already used in GeminiSearchClient; battle-tested |
| FSM transition validation | Manual state checks | `create_fsm(current_state).fail_reset()` | Validates indexed->failed is legal transition |
| File upload + import | Manual API sequencing | `GeminiFileSearchClient.upload_and_import()` | Handles upload -> wait_active -> import atomically |

**Key insight:** The lag measurement script needs raw SDK access (like check_stability.py) for independence, but can reference the existing patterns in `search/client.py` and `upload/client.py` for correct API usage.

## Common Pitfalls

### Pitfall 1: Query Ambiguity -- Multiple Files Match
**What goes wrong:** A targeted query like "What does Objectivism say about ethics?" matches many files, not just the target. The target file may appear in results but at position 11+ (outside top-10 threshold).
**Why it happens:** The Objectivism library corpus has massive thematic overlap. Generic philosophical concepts appear in nearly every file.
**How to avoid:** Use highly specific queries with proper nouns, unique titles, or distinctive phrases found only in the target file. Example: "What does 'A Study of Galt's Speech Lesson 01' discuss about the purpose and structure of Galt's Speech?" rather than "What is ethics?"
**Warning signs:** Pre-validation fails -- the target file doesn't appear in top-10 results.

### Pitfall 2: Document.display_name Contains File ID, Not Filename
**What goes wrong:** When checking search results for the target file, you look for the filename in `retrieved_context.title` but find a Gemini file ID instead.
**Why it happens:** Phase 11 discovery: `Document.display_name` contains the Files API resource ID (e.g., "sqowzecl39n8"), NOT the human-readable display_name submitted during upload.
**How to avoid:** Match search results by checking `retrieved_context.title` against BOTH the filename AND the gemini_file_id suffix. Use the same three-pass lookup as `enrich_citations()` in `src/objlib/search/citations.py`.
**Warning signs:** 0/20 files found in results despite being indexed.

### Pitfall 3: Polling Too Aggressively Burns API Quota
**What goes wrong:** 1-second polling intervals across 20 files, each potentially waiting up to 300s, means hundreds of API calls. At ~$0.003/query this adds up, and 429 rate limits can confound measurement.
**Why it happens:** Exponential backoff not configured properly; initial interval too short.
**How to avoid:** Use locked polling strategy: 1s -> 2s -> 4s -> 8s -> 16s -> 30s cap. Each file needs at most ~15 search queries before 300s timeout. Total across 20 files: ~300 queries max.
**Warning signs:** 429 errors in measurement logs; inconsistent timing data.

### Pitfall 4: Store Orphan Accumulation During Lag Measurement
**What goes wrong:** The lag measurement uploads 20 new files to measure timing. If the script crashes or files are left in the store, they become orphans.
**Why it happens:** The known blocker: FSM retry path doesn't clean store documents. Also, test files uploaded for measurement need cleanup.
**How to avoid:** Two strategies: (a) Re-upload 20 files from the existing corpus using `--reset-existing` pattern, then measure searchability of the re-uploaded versions. (b) Upload 20 NEW test files, measure, then clean up using store-sync. Strategy (a) is preferred because the locked decision says "20 files from Phase 12 50-file corpus."
**Warning signs:** Store document count increases unexpectedly; check_stability.py shows count mismatch.

### Pitfall 5: Race Condition -- File Listed Before Searchable
**What goes wrong:** T_listed (list_store_documents) shows the file within 0.25s, creating false confidence that it's "ready." But targeted search fails for seconds or minutes after listing.
**Why it happens:** The Gemini pipeline has three stages: (1) raw file stored, (2) chunked + embeddings generated, (3) vector index updated. Listing succeeds after stage 1, search requires stage 3.
**How to avoid:** Record T_listed and T_searchable separately. The primary metric is T_searchable - T_import. The T_listed measurement is supplementary to characterize the gap.
**Warning signs:** Consistently seeing T_listed << T_searchable with a large gap between them.

### Pitfall 6: Using statistics.quantiles() for Nearest-Rank with n=20
**What goes wrong:** `statistics.quantiles(data, n=100)` uses linear interpolation, not nearest-rank. For n=20 this produces interpolated values that don't correspond to any actual measurement.
**Why it happens:** Python's `statistics.quantiles()` defaults to the "exclusive" method which interpolates between data points.
**How to avoid:** Implement nearest-rank directly: `sorted_data[math.ceil(p/100 * n) - 1]`. This returns an actual measured value.
**Warning signs:** P50 reported as 10.5 when all measurements are integers -- that's interpolation, not nearest-rank.

## Code Examples

### Example 1: Search for a Specific File (Targeted Query)
```python
# Source: check_stability.py lines 346-376 adapted for targeted per-file search
def search_for_file(
    client: genai.Client,
    store_resource_name: str,
    query: str,
    target_filename: str,
    target_file_id_suffix: str,  # gemini_file_id without "files/" prefix
) -> bool:
    """Return True if target file appears in top-10 search results."""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
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
        return False
    gm = getattr(response.candidates[0], "grounding_metadata", None)
    if not gm:
        return False
    chunks = getattr(gm, "grounding_chunks", []) or []
    for chunk in chunks[:10]:  # top-10 only
        rc = getattr(chunk, "retrieved_context", None)
        if not rc:
            continue
        title = getattr(rc, "title", "") or ""
        # Match by filename OR by file ID suffix (Phase 11 finding)
        if title == target_filename or target_file_id_suffix in title:
            return True
    return False
```

### Example 2: Exponential Backoff Polling for Searchability
```python
# Source: adapted from spike/phase11_spike/lag_measurement.py
import asyncio
import time

async def poll_until_searchable(
    client, store_resource_name, query, target_filename, target_file_id,
    max_wait=300.0,  # 300s locked timeout
) -> dict:
    """Poll search until target file appears or timeout."""
    start = time.perf_counter()
    interval = 1.0  # Start at 1s
    polls = 0

    while True:
        elapsed = time.perf_counter() - start
        if elapsed >= max_wait:
            return {"searchable": False, "elapsed": elapsed, "polls": polls, "timed_out": True}

        polls += 1
        found = search_for_file(client, store_resource_name, query, target_filename, target_file_id)
        if found:
            elapsed = time.perf_counter() - start
            return {"searchable": True, "elapsed": elapsed, "polls": polls, "timed_out": False}

        await asyncio.sleep(interval)
        interval = min(interval * 2, 30.0)  # 1s -> 2s -> 4s -> 8s -> 16s -> 30s cap
```

### Example 3: Nearest-Rank Percentile Computation
```python
import math

def compute_percentiles_nearest_rank(latencies: list[float]) -> dict:
    """Compute P50/P95/max using nearest-rank method for n=20."""
    n = len(latencies)
    if n == 0:
        return {"error": "No data", "n": 0}

    sorted_lats = sorted(latencies)

    def nearest_rank(p: int) -> float:
        idx = math.ceil(p / 100 * n) - 1
        return sorted_lats[max(0, idx)]

    result = {
        "n": n,
        "p50": round(nearest_rank(50), 3),
        "p95": round(nearest_rank(95), 3),
        "p99_max": round(sorted_lats[-1], 3),  # Empirical max
        "min": round(sorted_lats[0], 3),
        "max": round(sorted_lats[-1], 3),
        "mean": round(sum(sorted_lats) / n, 3),
    }
    return result
```

### Example 4: Three-Timestamp Measurement Per File
```python
# Core measurement loop for one file:
# Step 1: Upload + import (T_import)
t_import = time.perf_counter()
file_obj, operation = await client.upload_and_import(file_path, display_name, metadata)
completed = await client.poll_operation(operation, timeout=600)
# T_import is NOW (upload+import API returned success)

# Step 2: Poll list_store_documents for T_listed
t_listed = None
# ... poll list_store_documents() until doc_id appears ...

# Step 3: Poll search for T_searchable
t_searchable = None
# ... poll search_for_file() with targeted query ...

# Record
result = {
    "file": filename,
    "t_import": 0,  # baseline
    "t_listed": t_listed - t_import if t_listed else None,
    "t_searchable": t_searchable - t_import if t_searchable else None,
    "timed_out": t_searchable is None,
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| list_store_documents() as "visible" proxy | Targeted search query as "searchable" proof | Phase 15 | Measures actual user-facing searchability, not just metadata propagation |
| status column for upload state | gemini_state FSM column | Phase 13 (V11) | Clean state model; status column retired |
| Manual store cleanup | store-sync CLI command | Phase 8+ | Automated orphan detection and purge |
| 10-minute timeout for failures | 300s hard timeout | Phase 15 decision | Tighter bound; Phase 11 showed listing is sub-second |

**Deprecated/outdated:**
- `status` column: Retired in Phase 13 V11 schema migration. All queries now use `gemini_state`.
- `objectivism-library-test` store: Deleted in Phase 8. Permanent store is `objectivism-library`.
- Phase 11 lag_measurement.py: Measured listing lag only (P99=0.253s). Phase 15 measures SEARCH lag which is expected to be significantly higher.

## Open Questions

1. **What is the actual import-to-searchable lag?**
   - What we know: Import-to-listed is ~0.25s (Phase 11). Import-to-searchable is expected to be longer because embedding generation and vector index update happen after listing.
   - What's unclear: Could be seconds, minutes, or (rarely) never. No empirical data exists for this project.
   - Recommendation: The entire purpose of Plan 15-01 is to answer this. Design the script to handle anything from sub-second to 300s.

2. **Will the 20-file re-upload approach work without store orphans?**
   - What we know: `_reset_existing_files_fsm()` now deletes store documents before raw files (SC3, Phase 12). But the lag measurement needs to upload files and then search for them while they're "fresh."
   - What's unclear: Whether re-uploading already-indexed files and measuring time-to-searchable is a valid proxy for fresh upload behavior.
   - Recommendation: Use FRESH uploads of 20 files that are currently `untracked` (there are 1834 untracked files). This avoids the complexity of reset-and-reupload. After measurement, run store-sync to confirm no orphans.

3. **How to handle the FSM downgrade code -- new function or reuse existing?**
   - What we know: `transition_to_failed()` requires a version guard and accepts failure from any in-flight state. `retry_failed_file()` is the FAILED->UNTRACKED escape path (documented 6th write site).
   - What's unclear: Whether the reconciliation downgrade should use `transition_to_failed()` (OCC-guarded, requires reading version first) or a new standalone function like `retry_failed_file()`.
   - Recommendation: Create a new `downgrade_to_failed()` function modeled on `retry_failed_file()` -- a direct write that sets `gemini_state='failed'` WHERE `gemini_state='indexed'`. This becomes the documented 7th authorized write site. Simpler than OCC for a reconciliation tool that runs outside the upload pipeline.

## Sources

### Primary (HIGH confidence)
- `scripts/check_stability.py` -- Existing stability instrument with search pattern (lines 345-376)
- `src/objlib/search/client.py` -- GeminiSearchClient.query() implementation
- `src/objlib/upload/client.py` -- GeminiFileSearchClient with upload_and_import, list_store_documents, delete_store_document
- `src/objlib/upload/orchestrator.py` -- FSMUploadOrchestrator.run_fsm() full pipeline
- `src/objlib/upload/state.py` -- FSM transition methods (transition_to_uploading/processing/indexed/failed)
- `src/objlib/upload/recovery.py` -- retry_failed_file() escape path, RecoveryCrawler
- `src/objlib/upload/fsm.py` -- FileLifecycleSM with 5 states, 8 transitions
- `spike/phase11_spike/lag_measurement.py` -- Phase 11 listing lag measurement (P99=0.253s)
- `.planning/phases/12-50-file-fsm-upload/12-VERIFICATION.md` -- Phase 12 verification (50/50 indexed, SC2 bidirectional)
- `.planning/phases/11-display-name-import/VERIFICATION.md` -- Phase 11 verification (display_name confirmed, P99=0.253s listing lag)
- `.planning/phases/15-consistency-store-sync/15-CONTEXT.md` -- All 8 locked decisions
- `.planning/phases/15-consistency-store-sync/CLARIFICATIONS-ANSWERED.md` -- Decision rationale

### Secondary (MEDIUM confidence)
- `.planning/REQUIREMENTS.md` -- VLID-07 definition
- `.planning/STATE.md` -- Phase 14 COMPLETE, Phase 15 UNBLOCKED
- `data/library.db` schema -- 50 indexed files, 1834 untracked, FSM columns confirmed

### Tertiary (LOW confidence)
- Gemini File Search indexing pipeline internals (opaque API -- three-stage assumption from provider synthesis, not verified against official documentation)
- Expected searchability lag range (no empirical data yet -- could be sub-second or multi-minute)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already in use in the project
- Architecture: HIGH -- all patterns replicate existing check_stability.py and Phase 11 spike patterns
- Pitfalls: HIGH -- derived from actual Phase 11 findings and confirmed codebase behavior
- Search API behavior: MEDIUM -- Gemini search via generate_content is well-tested in this project, but the timing of "when does a file become searchable after import" is unmeasured
- Percentile computation: HIGH -- nearest-rank is a simple algorithm, verified with Python test

**Research date:** 2026-02-22
**Valid until:** 2026-03-22 (stable -- no version changes expected)
