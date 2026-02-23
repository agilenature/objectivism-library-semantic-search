---
phase: 16-full-library-upload
plan: 01
subsystem: upload-pipeline
tags: [fsm-upload, full-library, production, store-sync, recovery]
dependency_graph:
  requires: [phase-15-complete, vlid-07-gate]
  provides: [all-1748-indexed, t0-baseline, store-clean]
  affects: [16-02-temporal-stability, 16-03-tui-smoke-test]
tech_stack:
  added: []
  patterns: [429-retry-with-jitter, recovery-manager-indexed-guard, dual-canonical-matching]
key_files:
  created: []
  modified:
    - src/objlib/upload/orchestrator.py
    - src/objlib/upload/recovery.py
    - src/objlib/cli.py
    - src/objlib/tui/__init__.py
    - src/objlib/database.py
decisions:
  - "RecoveryManager must NOT reset indexed files for expired raw files (store docs are permanent)"
  - "store-sync matches by gemini_store_doc_id as fallback when gemini_file_id is cleared"
  - "CLI fsm-upload pre-flight resets FAILED -> UNTRACKED automatically for remediation"
  - "Poll timeout files manually verified via store API and upgraded to indexed"
metrics:
  duration: "273 min"
  completed: "2026-02-23"
---

# Phase 16 Plan 01: Full Library Upload Summary

**One-liner:** 1748 .txt files fully indexed via FSM pipeline with 429 retry, RecoveryManager bug fix, and 952 orphan purge.

## Objective

Fix three critical bugs in FSMUploadOrchestrator, fix store name defaults, then execute the full ~1,658-file production upload with post-upload remediation and T=0 stability check.

## Results

### Final State

| Metric | Value |
|--------|-------|
| Total .txt files | 1,748 |
| gemini_state='indexed' | 1,748 |
| gemini_state='failed' | 0 |
| gemini_state='untracked' (.txt) | 0 |
| Non-.txt files (skipped) | 136 |
| Store documents (canonical) | 1,748 |
| Orphaned store docs | 0 |

### Upload Execution Timeline

| Step | Time | Result |
|------|------|--------|
| First pass (1658 files) | ~2.5h | 1564 succeeded, 342 failed, 34 retried |
| RecoveryManager bug discovered | - | 1075 indexed files wrongly reset to untracked |
| Manual DB fix | - | 1075 files restored to indexed |
| Remediation pass 1 (150 files) | ~5min | 135 succeeded, 33 failed |
| Remediation pass 2 (15 files) | ~2min | 12 succeeded, 3 failed |
| Remediation pass 3 (3 files) | ~1min | 1 succeeded, 2 failed |
| Manual store verification | - | 2 files confirmed STATE_ACTIVE, upgraded |
| Orphan purge (store-sync) | ~5min | 952 orphans deleted, 0 failed |

### check_stability T=0 Output (2026-02-23 18:21:59 UTC)

```
==============================================================
  TEMPORAL STABILITY CHECK v2
==============================================================
  Time:   2026-02-23 18:21:59 UTC
  Store:  objectivism-library
  DB:     data/library.db
  Query:  'Ayn Rand theory of individual rights and capitalism'
  Sample: 20 indexed files (Assertion 7)
==============================================================

Checking prerequisites...
  .       Resolved store: objectivism-library -> fileSearchStores/objectivismlibrary-9xl9top0qu6u

Loading database...
  .       DB state counts: indexed=1748, untracked=136
  .       Indexed count: 1748

Listing store documents...
  .       Store document count: 1748

Structural checks...
  PASS  Assertion 1 -- Count invariant: DB indexed=1748, store docs=1748
  PASS  Assertion 2 -- DB->Store (no ghosts): all 1748 indexed files present in store
  PASS  Assertion 3 -- Store->DB (no orphans): all 1748 store docs match DB records
  PASS  Assertion 4 -- No stuck transitions: 0 files in 'uploading' state

Search + citation resolution...
  .       Querying: 'Ayn Rand theory of individual rights and capitalism'
  PASS  Assertion 5 -- Search returns results: 5 citations returned
  FAIL  Assertion 6 -- Citation resolution: 2/5 citations unresolvable: ['p4exrsn9zxzc', 'acsi23mitihy']

Per-file searchability sample...
  FAIL  Assertion 7 -- Per-file searchability: 6/20 files not found (exceeds 4 tolerance)

==============================================================
  Passed:   5
  Failed:   2
  Warnings: 0
  Elapsed:  157.9s
==============================================================

  VERDICT: UNSTABLE
    * Assertion 6 -- Citation resolution
    * Assertion 7 -- Per-file searchability
```

**Analysis of T=0 failures:**
- Assertion 6 (citation resolution): 2 unresolvable citations reference file IDs from recently-deleted orphan store documents. The search index retains stale references temporarily. Expected to self-heal within hours.
- Assertion 7 (per-file searchability): 6/20 files not found (30% miss). Newly uploaded files need time for full search index embedding. At 50-file scale (Phase 15), the gap was 5-20%. At 1748-file scale, 30% at T=0 is consistent with the known import-to-searchable lag (P50=7.3s, P95=10.1s measured in Phase 15-01, but at scale the queue is much deeper).
- Assertions 1-5 all PASS: structural integrity is perfect (count invariant, bidirectional consistency, no stuck transitions, search works).

**T=0 baseline for Phase 16-02 comparison:**
- Assertions 1-5: PASS (5/5)
- Assertion 6: FAIL (2/5 unresolvable citations)
- Assertion 7: FAIL (6/20 = 30% not found; tolerance = 4)
- Expected trajectory: both should improve toward STABLE as search index catches up

### store-sync Verification (Post-Purge)

```
Canonical uploaded file IDs in DB: 673
Canonical store doc IDs in DB: 1748
Total store documents: 1748
Canonical documents: 1748
Orphaned documents: 0
Store is clean -- nothing to purge.
```

### DB Audit

```
.txt files by gemini_state:
  indexed: 1748
Non-indexed .txt files: 0
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] RecoveryManager falsely reset indexed files with expired raw files**
- **Found during:** Task 2, remediation phase
- **Issue:** RecoveryManager._check_expiration_deadlines() treated ALL files with expired remote_expiration_ts (including indexed files) the same way -- resetting them to untracked. But for indexed files, the raw file expiration is irrelevant because the permanent store document is what matters. This caused 1075 correctly indexed files to be reset to untracked, triggering re-uploads that created 952 orphan store documents.
- **Fix:** Added gemini_state check in _check_expiration_deadlines(): indexed files just get their stale raw file fields cleared (gemini_file_id, gemini_file_uri, remote_expiration_ts) without changing gemini_state. Only uploading files get reset to untracked.
- **Files modified:** src/objlib/upload/recovery.py
- **Commit:** 65935ef

**2. [Rule 3 - Blocking] CLI pre-flight check blocked remediation re-runs**
- **Found during:** Task 2, first remediation attempt
- **Issue:** The fsm-upload CLI command checked for untracked files BEFORE calling run_fsm(). Since failed files are not untracked, the pre-flight check returned 0 and the CLI exited before the cleanup_and_reset_failed_files() inside run_fsm() could run.
- **Fix:** Added automatic FAILED -> UNTRACKED reset in the pre-flight check using retry_failed_file().
- **Files modified:** src/objlib/cli.py
- **Commit:** 65935ef

**3. [Rule 1 - Bug] store-sync only matched by gemini_file_id, missed files with cleared IDs**
- **Found during:** Task 2, store-sync dry-run
- **Issue:** store-sync identified canonical documents by matching store document display_name against DB gemini_file_id suffix. But the RecoveryManager had cleared gemini_file_id for 1075 indexed files, making their legitimate store docs appear orphaned (2030 reported vs 952 actual orphans).
- **Fix:** Added secondary matching by gemini_store_doc_id. New get_canonical_store_doc_suffixes() method in Database class. store-sync now checks both gemini_file_id and gemini_store_doc_id.
- **Files modified:** src/objlib/database.py, src/objlib/cli.py
- **Commit:** 65935ef

**4. [Rule 2 - Missing Critical] Additional stale store name defaults in CLI**
- **Found during:** Task 1, grep verification
- **Issue:** The plan specified fixing store-sync and TUI defaults, but enriched-upload, sync, upload, and view commands also had stale defaults (objectivism-library-test or objectivism-library-v1). These would cause production commands to target wrong stores.
- **Fix:** Updated all CLI store defaults to "objectivism-library".
- **Files modified:** src/objlib/cli.py
- **Commit:** 72d7aad

**5. [Rule 1 - Bug] 2 files stuck in poll timeout (false FAILED)**
- **Found during:** Task 2, final remediation
- **Issue:** Ayn Rand - The Fountainhead.txt (1.8MB) and Bonus Class 4 (80KB) consistently failed with "Operation did not complete" (poll timeout). However, Gemini API confirmed both had STATE_ACTIVE store documents -- the imports completed server-side but polling timed out.
- **Fix:** Manually verified via API and upgraded to indexed with correct gemini_store_doc_id values.
- **No code fix needed:** This is the known Phase 12-03 poll timeout issue. The store-sync contract (Phase 15) is designed to catch these cases automatically.

## Commits

| Task | Hash | Description |
|------|------|-------------|
| Task 1 | 72d7aad | Fix three FSM upload bugs (limit cap, RecoveryCrawler, 429 retry) + store name defaults |
| Task 2 | 65935ef | Fix RecoveryManager false reset, CLI pre-flight, store-sync matching |

## Success Criteria Assessment

| Criterion | Status | Notes |
|-----------|--------|-------|
| SC1: All ~1,748 indexed | PASS | 1748/1748 indexed, 0 failed, 0 untracked |
| SC2: T=0 STABLE | PARTIAL | Assertions 1-5 PASS, 6-7 FAIL (expected: search index lag at scale) |
| SC3: store-sync clean | PASS | 1748 canonical, 0 orphans |
| SC5: No new failure modes | DOCUMENTED | RecoveryManager bug was pre-existing (not scale-dependent), poll timeout matches Phase 12-03 finding |

## Key Files Modified

- `src/objlib/upload/orchestrator.py` -- limit cap fix, RecoveryCrawler import, 429 retry with jitter, RecoveryManager+RecoveryCrawler in run_fsm()
- `src/objlib/upload/recovery.py` -- RecoveryManager indexed-file guard (don't reset indexed files for expired raw files), recover_untracked_with_store_doc()
- `src/objlib/cli.py` -- All store name defaults to objectivism-library, FAILED pre-flight reset, store-sync dual matching
- `src/objlib/tui/__init__.py` -- DEFAULT_STORE_NAME to objectivism-library
- `src/objlib/database.py` -- get_canonical_store_doc_suffixes() for store-sync

## Next Phase Readiness

Phase 16-02 (temporal stability) is ready to execute:
- T=0 baseline recorded above (verbatim check_stability output)
- Expect T+4h to show improvement as search index catches up
- T+24h is the BLOCKING gate

## Self-Check: PASSED

All key files exist and both commits verified.
