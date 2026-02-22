# FSM / store-sync Contract

> Authoritative reconciliation policy between the file lifecycle FSM and
> the `store-sync` verification tool.

**Version:** 1.0
**Effective:** 2026-02-22
**Authority:** Phase 15 (Consistency + store-sync)

---

## 1. Overview

Two subsystems govern whether a file is searchable in the Gemini File Search
store:

1. **The File Lifecycle FSM** -- a five-state machine (`untracked` ->
   `uploading` -> `processing` -> `indexed` | `failed`) that tracks each
   file's journey through the upload pipeline.  The FSM owns all
   `gemini_state` writes and all transition logic.

2. **store-sync** -- a post-batch reconciliation tool that verifies empirical
   searchability.  It reads FSM state, queries the Gemini store, and detects
   disagreements between the two.  When FSM says `indexed` but the store says
   the file is missing, store-sync resolves the disagreement by calling
   `downgrade_to_failed()`.

The FSM is the *writer*; store-sync is the *auditor*.  Neither is subordinate
to the other -- they have complementary roles with a clear disagreement
resolution protocol.

---

## 2. Roles and Ownership

### 2.1 FSM Owns

| Responsibility               | Implementation                               |
|------------------------------|----------------------------------------------|
| All `gemini_state` writes    | `AsyncUploadStateManager.transition_to_*()`  |
| All `gemini_store_doc_id` writes | `transition_to_indexed()`                |
| All state transition logic   | `FileLifecycleSM` validation + DB persistence|
| OCC version guards           | `WHERE version = ?` on every write           |
| Intent logging               | `write_reset_intent()` before API deletions  |

### 2.2 store-sync Owns

| Responsibility                     | Implementation                              |
|------------------------------------|---------------------------------------------|
| Read-verification of store state   | `list_store_documents()` + `search()` calls |
| Orphan detection                   | DB files vs. store documents comparison     |
| Orphan cleanup                     | `delete_store_document()` for unmatched docs|
| Inconsistency detection            | INDEXED files missing from store            |
| Disagreement resolution            | `downgrade_to_failed()` call                |

### 2.3 Neither Owns (shared responsibility)

| Responsibility                       | Notes                                   |
|--------------------------------------|-----------------------------------------|
| Defining "searchable"               | Per Q1: targeted semantic query returns file in top-10 results |
| Silent failure timeout               | Per Q3: 300 seconds                     |

---

## 3. Store-sync Classification

**Role: Scheduled periodic + targeted post-run**

This classification is driven by the empirical measurements from Phase 15
Plan 01:

| Metric         | Value  | Implication                                      |
|----------------|--------|--------------------------------------------------|
| Lag P50        | 7.3s   | Median file takes ~7s to become searchable       |
| Lag P95        | 10.1s  | 95th-percentile is ~10s -- narrow distribution   |
| Lag max        | 10.1s  | No extreme outliers in successful measurements   |
| Failure rate   | 5.0%   | 1 in 20 files never became searchable in 300s    |
| Listing P50    | ~1.5s  | Files are listed fast but search-indexing adds delay |

**Justification:**

Given P50=7.3s lag and a 5% silent failure rate, store-sync must run after
every batch upload session -- not just on a schedule.  The 5% failure rate
means roughly 1 in 20 files may silently fail to become searchable even
though the FSM marks them as `indexed`.  Without post-batch verification,
these inconsistencies accumulate undetected.

Per Q7 decision: any silent failure rate > 0% triggers escalation from
"scheduled only" to "after each batch."  The measured 5% rate confirms this
escalation.

**When to run store-sync:**

1. **After every `fsm-upload` batch run** -- immediate reconciliation to
   catch the ~5% silent failures before the next session.
2. **After any batch > 50 files** -- comprehensive validation including
   orphan detection and cleanup.
3. **Weekly scheduled** -- catch any drift from API-side changes (store
   document expiration, service-side deletions).
4. **Emergency trigger** -- when `check_stability.py` reports UNSTABLE.

---

## 4. Disagreement Resolution

This is the most critical section of the contract.  It defines what happens
when FSM state and empirical store state disagree.

### 4.1 The Scenario

The FSM says a file has `gemini_state = 'indexed'` (meaning the upload
pipeline completed successfully: upload -> import -> store document created).
But store-sync queries the Gemini store and cannot find the file -- either
`list_store_documents()` does not include it, or a targeted search query
does not return it in the top-10 results.

### 4.2 The Policy

**Empirical searchability is authoritative.**  Per Q4 decision: `INDEXED`
must mean "actually searchable," not merely "upload succeeded."

When store-sync detects a file that is INDEXED in the DB but missing from
the store:

1. **Log the inconsistency** with timestamp, file path, and query used.
2. **Downgrade FSM state** from `indexed` to `failed` by calling
   `downgrade_to_failed()` in `src/objlib/upload/recovery.py`.
3. **Existing retry path handles re-upload** -- on the next `fsm-upload`
   run, `retry_failed_file()` transitions `failed` -> `untracked`, and the
   normal upload pipeline picks it up.
4. **No automatic store deletions** -- store-sync reports orphans; the
   operator confirms and runs `store-sync --no-dry-run` to purge.

### 4.3 The Mechanism

The resolution mechanism is `downgrade_to_failed()` in
`src/objlib/upload/recovery.py` -- the 7th authorized DB write site.

```python
async def downgrade_to_failed(
    db_path: str,
    file_path: str,
    reason: str = "store-sync detected missing from store"
) -> bool:
```

This function:
- Sets `gemini_state = 'failed'` with an OCC guard (`AND gemini_state = 'indexed'`)
- Clears `gemini_store_doc_id` (the store reference is stale)
- Stores the reason in `error_message`
- Updates `gemini_state_updated_at` timestamp
- Returns `True` if the downgrade succeeded, `False` if the file was not in
  `indexed` state (another process already changed it)

The OCC guard (`AND gemini_state = 'indexed'`) prevents overwriting a state
that has already been changed by another process (e.g., a concurrent
`fsm-upload` run that already reset the file).

---

## 5. Authorized DB Write Sites

All `gemini_state` writes in the codebase are listed here.  Any new write
site must be added to this table and documented in this contract.

| # | Function                              | Module               | Transition           | Caller              |
|---|---------------------------------------|----------------------|----------------------|---------------------|
| 1 | `transition_to_uploading()`           | `state.py`           | untracked -> uploading | FSM upload pipeline |
| 2 | `transition_to_processing()`          | `state.py`           | uploading -> processing | FSM upload pipeline |
| 3 | `transition_to_indexed()`             | `state.py`           | processing -> indexed | FSM upload pipeline  |
| 4 | `transition_to_failed()`              | `state.py`           | any -> failed        | FSM upload pipeline  |
| 5 | `finalize_reset()`                    | `state.py`           | indexed -> untracked | RecoveryCrawler      |
| 6 | `retry_failed_file()`                 | `recovery.py`        | failed -> untracked  | CLI / retry path     |
| 7 | `downgrade_to_failed()`               | `recovery.py`        | indexed -> failed    | store-sync only      |

**Legacy write sites** (backward compatibility, not FSM-mediated):

| Function                        | Module      | Notes                                     |
|---------------------------------|-------------|-------------------------------------------|
| `record_upload_intent()`        | `state.py`  | Sets `uploading` -- legacy upload path     |
| `record_upload_failure()`       | `state.py`  | Sets `failed` -- legacy upload path        |
| `RecoveryManager._recover_*`    | `recovery.py` | Sets `indexed`/`untracked` -- crash recovery |

---

## 6. Protocol for FSM/store-sync Disagreement

Step-by-step protocol when store-sync detects an inconsistency:

### 6.1 Detection

store-sync queries the Gemini store for every file with `gemini_state = 'indexed'`
in the database:

```sql
SELECT id, file_path, gemini_store_doc_id
FROM files
WHERE gemini_state = 'indexed'
```

For each file, store-sync verifies:
1. The `gemini_store_doc_id` exists in the store (`list_store_documents()`)
2. Optionally: a targeted search query returns the file in the top-10 results

If either check fails, the file is flagged as INCONSISTENT.

### 6.2 Resolution

For each INCONSISTENT file:

```python
result = await downgrade_to_failed(db_path, file_path, reason="store-sync: not found in store")
if result:
    logger.warning("Downgraded file %s to FAILED", file_path)
else:
    logger.info("File %s already changed state (no downgrade needed)", file_path)
```

### 6.3 Re-upload

On the next `fsm-upload` run:

1. `retry_failed_file()` transitions `failed` -> `untracked` (write site #6)
2. The normal upload pipeline picks up the `untracked` file
3. The file goes through the full `untracked -> uploading -> processing -> indexed` cycle
4. After the batch completes, store-sync runs again to verify

This creates a self-healing loop: detect inconsistency -> downgrade -> retry ->
verify.

---

## 7. Invariants

These invariants must hold at all times:

1. **Single-writer per file:** Only one process writes `gemini_state` for a
   given file at a time (enforced by OCC version guards).
2. **FSM validates transitions:** Every write site uses the FSM to validate
   the transition is legal before persisting.  Exception: `downgrade_to_failed()`
   uses a direct `WHERE gemini_state = 'indexed'` guard (same pattern as
   `retry_failed_file()` for emergency operations).
3. **store-sync never promotes:** store-sync can only *downgrade* state
   (indexed -> failed).  It never sets a file to `indexed` or any other
   forward state.
4. **Empirical searchability is authoritative:** If the store says a file is
   not searchable, the DB must eventually reflect that -- regardless of what
   the FSM recorded.
5. **No auto-deletes:** store-sync reports orphan store documents but does
   not delete them without operator confirmation (`--no-dry-run` flag).

---

## 8. Temporal Stability

Per Phase 15 plan, temporal stability is verified at T=0, T+4h, and T+24h
after the 70-file corpus is indexed.  The `check_stability.py` script
(Phase 8 design) runs as a stateless standalone process -- new DB connection,
new API client -- to verify that:

1. All `indexed` files are present in the store
2. No orphan store documents exist
3. A targeted search query returns expected results

**T+24h is the VLID-07 gate blocker for Phase 16.**

---

*This contract is the authoritative reference for FSM/store-sync interaction.
Any changes to the reconciliation policy must update this document.*
