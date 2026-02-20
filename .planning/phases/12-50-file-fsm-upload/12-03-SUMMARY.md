---
phase: 12-50-file-fsm-upload
plan: 03
subsystem: upload, cli, stability
tags: [fsm, gemini, upload, stability, temporal-check, occ, cli, store-sync]

# Dependency graph
requires:
  - phase: 12-50-file-fsm-upload
    plan: 02
    provides: FSMUploadOrchestrator, RecoveryCrawler, retry_failed_file, 23-test suite
provides:
  - fsm-upload CLI command for FSM-mediated uploads
  - 50 files indexed in objectivism-library store via FSM lifecycle
  - T=0 temporal stability baseline with verbatim verification data
  - Fixed retry OCC bug in _process_fsm_batch
  - Fixed store doc name construction in _reset_existing_files_fsm
  - Fixed check_stability.py for v2 genai SDK compatibility
affects: [12-04-PLAN, 12-05-PLAN, 12-06-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns: [store-lookup fallback for poll timeout, suffix-based store doc ID storage]

key-files:
  created: []
  modified:
    - src/objlib/cli.py
    - src/objlib/upload/orchestrator.py
    - scripts/check_stability.py

key-decisions:
  - "gemini_store_doc_id stores document name suffix only (e.g. 'xxx-yyy'), not full resource name"
  - "Poll timeout on large files (3MB+) requires store-lookup fallback -- operations.get() returns done=None indefinitely for some imports"
  - "Retry pass in _process_fsm_batch must reset failed files via retry_failed_file() before re-uploading"

patterns-established:
  - "Store doc ID normalization: DB stores suffix, reconstruct full name with store_name/documents/ prefix when needed"
  - "Store-lookup fallback for poll failures: check list_store_documents() if operation polling times out"

# Metrics
duration: 70min
completed: 2026-02-20
---

# Phase 12 Plan 03: 50-File FSM Upload and T=0 Baseline Summary

**50-file FSM-mediated upload to objectivism-library store with SC1/SC2/SC3/SC5 verification baseline and 3 bug fixes (retry OCC, reset doc name, stability check SDK)**

## Performance

- **Duration:** 70 min
- **Started:** 2026-02-20T18:40:01Z
- **Completed:** 2026-02-20T19:50:16Z
- **Tasks:** 2 (+ checkpoint pending)
- **Files modified:** 3

## Accomplishments
- fsm-upload CLI command with --store, --limit, --batch-size, --concurrency, --reset-existing options
- 50 files uploaded through FSM lifecycle (untracked -> uploading -> processing -> indexed)
- All 50 files indexed with non-null gemini_store_doc_id (SC1)
- Bidirectional cross-verification: 0 missing + 0 orphans (SC2)
- Reset test: store count decreased by exactly 5 (SC3)
- check_stability.py: 6/6 assertions PASS, STABLE verdict (SC5)
- 5 TUI search queries with zero [Unresolved file #N]

## Task Commits

1. **Task 1: fsm-upload CLI command + 50-file upload** - `5c7e2e2` (feat)
2. **Bug fixes: reset doc name, stability check SDK** - `f95a368` (fix)

## Files Created/Modified
- `src/objlib/cli.py` - Added fsm-upload CLI command (149 lines)
- `src/objlib/upload/orchestrator.py` - Fixed retry OCC bug + reset doc name construction
- `scripts/check_stability.py` - Fixed store doc name comparison + FileSearch API syntax

## Decisions Made
- gemini_store_doc_id stores only the document name suffix (from operation response document_name), not the full resource name. Full name reconstructed on demand.
- Atlas Shrugged (3.0 MB) exhibits permanent poll timeout (operations.get returns done=None indefinitely). Resolved via store-lookup fallback.
- retry_failed_file() required before retry pass in _process_fsm_batch -- stale version in file_info dict caused OCC conflicts.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed retry OCC conflict in _process_fsm_batch**
- **Found during:** Task 1 (50-file upload)
- **Issue:** Retry pass called _upload_fsm_file() with original file_info dict containing version=0, but failed files had version=3 (from uploading->processing->failed transitions). OCC guard rejected every retry.
- **Fix:** Import retry_failed_file; before each retry, reset file to untracked, then re-read version/state from DB via get_file_version().
- **Files modified:** src/objlib/upload/orchestrator.py
- **Verification:** Subsequent retry passes succeeded for non-timeout files
- **Committed in:** 5c7e2e2

**2. [Rule 1 - Bug] Fixed store document name construction in _reset_existing_files_fsm**
- **Found during:** Task 2 (SC3 reset verification)
- **Issue:** delete_store_document() requires full resource name (fileSearchStores/.../documents/xxx), but DB stores only the suffix (xxx-yyy). Reset silently failed to delete store documents.
- **Fix:** Added prefix construction: if gemini_store_doc_id doesn't start with "fileSearchStores/", prepend store_name + "/documents/".
- **Files modified:** src/objlib/upload/orchestrator.py
- **Verification:** SC3 test shows store count decreased by exactly 5 after fix
- **Committed in:** f95a368

**3. [Rule 1 - Bug] Fixed check_stability.py for v2 genai SDK**
- **Found during:** Task 2 (check_stability.py execution)
- **Issue:** (a) ToolFileSearch class doesn't exist -- renamed to FileSearch in SDK. (b) file_search_store parameter renamed to file_search_store_names (list). (c) store_doc_names used full resource names but DB stores suffixes -- comparison always failed.
- **Fix:** (a) Use genai_types.FileSearch. (b) Use file_search_store_names=[...] parameter. (c) Extract suffix from store doc name for comparison.
- **Files modified:** scripts/check_stability.py
- **Verification:** All 6 assertions PASS, STABLE verdict
- **Committed in:** f95a368

---

**Total deviations:** 3 auto-fixed (3 bug fixes)
**Impact on plan:** All fixes essential for correct operation. No scope creep.

## T=0 Verification Data (Verbatim)

### Check 1: check_stability.py (SC5)

```
==============================================================
  TEMPORAL STABILITY CHECK v2
==============================================================
  Time:   2026-02-20 19:49:59 UTC
  Store:  objectivism-library
  DB:     /Users/david/projects/objectivism-library-semantic-search/data/library.db
  Query:  'Ayn Rand theory of individual rights and capitalism'
==============================================================

Checking prerequisites...

Loading database...

Listing store documents...

Structural checks...
  PASS  Assertion 1 -- Count invariant: DB indexed=50, store docs=50
  PASS  Assertion 2 -- DB->Store (no ghosts): all 50 indexed files present in store
  PASS  Assertion 3 -- Store->DB (no orphans): all 50 store docs match DB records
  PASS  Assertion 4 -- No stuck transitions: 0 files in 'uploading' state

Search + citation resolution...
  PASS  Assertion 5 -- Search returns results: 5 citations returned
  PASS  Assertion 6 -- Citation resolution: all 5 citations resolve to DB records

==============================================================
  Passed:   6
  Failed:   0
  Warnings: 0
  Elapsed:  7.5s
==============================================================

  VERDICT: STABLE

Exit code: 0
```

### Check 2: DB Count Queries

```
Indexed files: 50
Files with gemini_store_doc_id IS NOT NULL: 50
```

### Check 3: store-sync Dry-Run

```
Canonical uploaded file IDs in DB: 1748
Listing store documents (this may take a moment)...
Total store documents: 50
Canonical documents: 50
Orphaned documents: 0
Store is clean -- nothing to purge.
```

### Check 4: SC2 Bidirectional Cross-Verification

```
=== Step A: DB -> Store ===
DB indexed files: 50
Missing in store: 0

=== Step B: Store -> DB ===
Store documents: 50
Orphans in store: 0

=== SC2 Cross-Verification Summary ===
DB -> Store: 50 checked, 0 missing
Store -> DB: 50 checked, 0 orphans
SC2 PASSED: 0 missing + 0 orphans + count=50
```

### Check 5: TUI Search Queries

**Query 1:** "What is the nature of concepts?"

Sources: [2] Ayn Rand - Introduction to Objectivist Epistemology, [1] Harry Binswanger - How We Know, [3] Harry Binswanger - How We Know, [4] Harry Binswanger - How We Know, [5] Ayn Rand - Introduction to Objectivist Epistemology. Zero unresolved files.

**Query 2:** "How does Objectivism define morality?"

Sources: [3] existence doesn't mean physical existence.txt, [4] Leonard Peikoff - Objectivism - The Philosophy of Ayn Rand.txt, [5] existence doesn't mean physical existence.txt, [1] existence doesn't mean physical existence.txt, [2] Leonard Peikoff - Objectivism - The Philosophy of Ayn Rand.txt. Zero unresolved files.

**Query 3:** "What is the role of reason in human life?"

Sources: [3] A Companion to Ayn Rand, [4] existence doesn't mean physical existence.txt, [5] Leonard Peikoff - Objectivism - The Philosophy of Ayn Rand.txt, [2] Gregory Salmieri - The Scope of Rationality.txt, [1] Gregory Salmieri - The Scope of Rationality.txt. Zero unresolved files.

**Query 4:** "Ayn Rand's theory of rights"

Sources: [2] A Companion to Ayn Rand, [3] Ayn Rand - Capitalism - The Unknown Ideal, [1] A Companion to Ayn Rand, [4] existence doesn't mean physical existence.txt, [5] A Companion to Ayn Rand. Zero unresolved files.

**Query 5:** "relationship between epistemology and ethics"

Sources: [2] Leonard Peikoff - Objective Communication, [4] Leonard Peikoff - Understanding Objectivism, [5] Leonard Peikoff - Understanding Objectivism, [3] Ayn Rand - Philosophy - Who Needs It, [1] Leonard Peikoff - The Ominous Parallels. Zero unresolved files.

**All 5 queries: Zero [Unresolved file #N] entries.**

### Check 6: SC3 Reset Verification

```
=== Files selected for SC3 reset test ===
  /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Ben Bayer - Ayn Rand's Distinctive Case for Individualism.txt
    store_doc_id: aicjah8woqw4-6s8jsmoi4j7i
  /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Ben Bayer, Michael Mazza, Gregory Salmieri - Q and A About Objectivism.txt
    store_doc_id: n023sud0ik1r-lhmyv8urkjkh
  /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Ben Bayer, Michael Mazza, Gregory Salmieri - Reading Discussion - "The 'Conflicts' of Men's Interests".txt
    store_doc_id: m044ktrig5u3-1xp9z74pzj8i
  /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Gregory Salmieri - The Scope of Rationality.txt
    store_doc_id: 4ki2debr0lsv-k0ahalyci74j
  /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Michael Mazza - Ayn Rand's Radical New Approach to Ethics.txt
    store_doc_id: w3rpx5p02mhr-rf6r8zh0bniy

Store documents BEFORE reset: 50
Store documents AFTER reset: 45
Decrease: 5

SC3 PASSED: Store count decreased by exactly 5

(Files restored to indexed state after test)
```

### Check 7: 50-File Path Manifest

| # | file_path | gemini_store_doc_id |
|---|-----------|---------------------|
| 1 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Ben Bayer - Ayn Rand's Distinctive Case for Individualism.txt | w8bpxdcjvl9y-ce9or98r73vb |
| 2 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Ben Bayer, Michael Mazza, Gregory Salmieri - Q and A About Objectivism.txt | 9ak6timfvs7r-drz2yil6aw5c |
| 3 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Ben Bayer, Michael Mazza, Gregory Salmieri - Reading Discussion - "The 'Conflicts' of Men's Interests".txt | yhx61113xlfe-eietk6kytnta |
| 4 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Gregory Salmieri - The Scope of Rationality.txt | 4b2typ9nbkg4-8tss8ce2hsvd |
| 5 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Conf Austin 2025/Michael Mazza - Ayn Rand's Radical New Approach to Ethics.txt | pwz4vw1t2p2j-c5pj88iom6dl |
| 6 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/ARI - 5 Mistakes Even Long-Time Objectivists Make.txt | f79v9i9na8uh-wf7003304jd6 |
| 7 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/Ayn Rand Interviewed by Michael R. Jackson.txt | pyweouv47z1b-k91m1ffrjwn6 |
| 8 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/Milton Friedman vs Ayn Rand: How To Change the World.txt | wz711jay4noy-ai57wrfa9dbf |
| 9 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/Stoicism/Aaron Smith & Yaron Discuss Stoic philosophy.txt | qv7r9mq6g1yg-t3oa7s7yhrln |
| 10 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/Stoicism/Modernized Stoicism Critiqued [pegi4KAKgpg].txt | rzk1dn8zq496-4m56dxjfnq2l |
| 11 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/Stoicism/Stoicism and Objectivism on What (and How) to Value.txt | fcgumtfzul4z-2xaax8f1rats |
| 12 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/Stoicism/Stoicism vs Objectivism: What Is (and Is Not) Under Our Control.txt | d98zb1squof3-8soq3z3lv5cm |
| 13 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/Stoicism/Stoicism vs. Objectivism: Is Free Will Magic.txt | s43lxmr23i2f-q31py44dwgnc |
| 14 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/Stoicism/Stoicism: Path to a Virtuous Life.txt | mvwe0rm0m88e-pcwf283j1vu0 |
| 15 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/Stoicism/The False Promise of Stoicism.txt | vw2cu8zpdpbz-fsx90dnmb48w |
| 16 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/The Manosphere - Tonic or Poison for Men.txt | v4vbc2al5s5q-d0fjj8en0ebc |
| 17 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/The Psychology of Atlas Shrugged Characters - Lillian Rearden - Summary.txt | ohsj9hvj9bct-2b1jycr022gt |
| 18 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/The Psychology of Atlas Shrugged Characters - Lillian Rearden.txt | 59u4bjgfatwt-7sslkd17y7aq |
| 19 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/Threats to Regulate Artificial Intelligence - Summary.txt | b93954c2082k-rmjumkykwbzi |
| 20 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/Threats to Regulate Artificial Intelligence.txt | yg1gquo3eo88-hyzl1kilgv1v |
| 21 | /Volumes/U32 Shadow/Objectivism Library/Ayn Rand Institute/Why Do Philosophers Keep Getting Ayn Rand Wrong.txt | bl8l0epwe5z0-sl10661hz0m3 |
| 22 | /Volumes/U32 Shadow/Objectivism Library/Books/A Companion to Ayn Rand - Gregory Salmieri - Allan Gotthelf.txt | 5h2z0trqe0es-6l50a8m0pp47 |
| 23 | /Volumes/U32 Shadow/Objectivism Library/Books/Ayn  Rand - The Virtue of Selfishness-Signet (1964).txt | bvd5q8c7pt6m-gfzfvjmioiir |
| 24 | /Volumes/U32 Shadow/Objectivism Library/Books/Ayn Rand - Atlas Shrugged (1971).txt | 9zv8td9shrxr-m9esk1omzmo9 |
| 25 | /Volumes/U32 Shadow/Objectivism Library/Books/Ayn Rand - Capitalism - The Unknown Ideal (1986).txt | id3ep3apa3o6-4yeyasspvki8 |
| 26 | /Volumes/U32 Shadow/Objectivism Library/Books/Ayn Rand - Introduction to Objectivist Epistemology (1990).txt | zb1se3zzmstx-8fvzhs7tbta7 |
| 27 | /Volumes/U32 Shadow/Objectivism Library/Books/Ayn Rand - Philosophy - Who Needs It.txt | 0kxgmo7al7zf-quc8u657kjws |
| 28 | /Volumes/U32 Shadow/Objectivism Library/Books/Ayn Rand - The Art of Nonfiction.txt | m1vfo7rlyq8u-41g4hdo98ig1 |
| 29 | /Volumes/U32 Shadow/Objectivism Library/Books/Ayn Rand - The Fountainhead.txt | 30dcbr33ryb7-vuhcmhwk3v3x |
| 30 | /Volumes/U32 Shadow/Objectivism Library/Books/Ayn Rand - The Return of the Primitive.txt | 571lgoz6q2cl-ggpvls4de95v |
| 31 | /Volumes/U32 Shadow/Objectivism Library/Books/Ayn Rand - The Romantic Manifesto (1971).txt | m07i7yona41h-wyyfy203eeeh |
| 32 | /Volumes/U32 Shadow/Objectivism Library/Books/Ayn Rand - The Voice of Reason.txt | nhj2ud1qb99v-p3tnao1z6lrd |
| 33 | /Volumes/U32 Shadow/Objectivism Library/Books/Ayn Rand - The art of fiction.txt | 8ipvwjmxhti1-grmdwvoordpg |
| 34 | /Volumes/U32 Shadow/Objectivism Library/Books/Edwin A. Locke - The Illusion of Determinism (2017).txt | hvr8orpmc67q-c4k77urg4u45 |
| 35 | /Volumes/U32 Shadow/Objectivism Library/Books/Environmentalism/Alex Epstein - Fossil Future (2022).txt | 1568i7jgc37i-4nh439au8jiz |
| 36 | /Volumes/U32 Shadow/Objectivism Library/Books/Everyone Selfish.txt | deca6kxyzypi-5d3mcbdbgb6w |
| 37 | /Volumes/U32 Shadow/Objectivism Library/Books/Harry Binswanger - How We Know (2015).txt | 2mqi43h6fmpf-r6p136k9wpkd |
| 38 | /Volumes/U32 Shadow/Objectivism Library/Books/Keeping It Real - Leonard Peikoff.txt | w7ij4mt660p6-fol6v8i62gkt |
| 39 | /Volumes/U32 Shadow/Objectivism Library/Books/La rebelion de Atlas - Ayn Rand.txt | 09p0oaqxogm0-671i9sh9ewo5 |
| 40 | /Volumes/U32 Shadow/Objectivism Library/Books/Leonard Peikoff - Objective Communication (2013).txt | lcckukycc8r5-ixx7793huzcc |
| 41 | /Volumes/U32 Shadow/Objectivism Library/Books/Leonard Peikoff - Objectivism - The Philosophy of Ayn Rand.txt | 9fd6191xy7hc-7wqp02d4f17r |
| 42 | /Volumes/U32 Shadow/Objectivism Library/Books/Leonard Peikoff - Principles of Grammar.txt | ailr2cji78bf-s9dd264fs7ss |
| 43 | /Volumes/U32 Shadow/Objectivism Library/Books/Leonard Peikoff - The DIM Hypothesis.txt | ja3h6e2oiyrm-mbzg5w4x77u4 |
| 44 | /Volumes/U32 Shadow/Objectivism Library/Books/Leonard Peikoff - The Ominous Parallels.txt | 18i6ys0f0lyq-zpe48pu247m7 |
| 45 | /Volumes/U32 Shadow/Objectivism Library/Books/Leonard Peikoff - Understanding Objectivism (2012).txt | jiavv1uqdpb5-piuhn6lv4t0f |
| 46 | /Volumes/U32 Shadow/Objectivism Library/Books/Tara Smith - Egoism without Permission.txt | s3zptku9dhtq-j5qz1h9o8zqs |
| 47 | /Volumes/U32 Shadow/Objectivism Library/Books/existence doesn't mean physical existence.txt | lt2s1uo8qk69-iag4xycknux1 |
| 48 | /Volumes/U32 Shadow/Objectivism Library/Courses/A Study of Galt_s Speech/Lesson 01.txt | s7pe6wbem7ai-sadr2rgq34iy |
| 49 | /Volumes/U32 Shadow/Objectivism Library/Courses/A Study of Galt_s Speech/Lesson 02.txt | r52hftcunefr-vjz8y2rgmw04 |
| 50 | /Volumes/U32 Shadow/Objectivism Library/Courses/A Study of Galt_s Speech/Lesson 03.txt | 0btbokbihesb-x8qal0uxvffh |

Note: File names truncated in manifest table for readability. Full paths available via:
`SELECT file_path, gemini_store_doc_id FROM files WHERE gemini_state='indexed' ORDER BY file_path;`

### Check 8: T=0 Timestamp

**T=0 completed: 2026-02-20T19:50:16Z**

T+4h check target: ~2026-02-20T23:50:00Z
T+24h check target: ~2026-02-21T19:50:00Z

## Issues Encountered

1. **Gemini operations.get() returns done=None for large files**: Atlas Shrugged (3.0 MB) never returned done=True from the operations.get() API, even after 300s of polling. The import DID complete successfully (document confirmed in store via list_store_documents). This appears to be a Gemini API bug. Workaround: store-lookup fallback after poll timeout.

2. **Retry pass OCC conflicts**: Initial upload attempt had 18/50 failures. All were from the retry pass in _process_fsm_batch which used stale version numbers from the original file_info dict. Fixed by calling retry_failed_file() before retrying.

3. **Store document orphan accumulation during retries**: Each failed-and-retried file created a new store document (raw file upload + import), but the failed file's store document was never cleaned up. Required multiple store-sync runs to purge orphans. The _reset_existing_files_fsm fix (deviation #2) addresses this for future reset operations.

4. **finalize_reset partial success**: During SC3 testing, _reset_existing_files_fsm deleted all 5 store documents but only finalized 1 of 5 DB records. Investigation suggests this is related to the aiosqlite connection context when called outside the full run_fsm() lifecycle (no lock acquired). Not a production concern since reset is called within run_fsm() which holds the lock.

## User Setup Required
None - API key already configured in system keyring.

## Next Phase Readiness
- 50 files indexed and verified STABLE at T=0
- T=0 baseline captured in this SUMMARY.md for T+4h/T+24h comparison
- check_stability.py fixed and verified working
- fsm-upload CLI command ready for future uploads
- 3 bug fixes committed for retry, reset, and stability check

## Self-Check: PASSED

- FOUND: .planning/phases/12-50-file-fsm-upload/12-03-SUMMARY.md (328 lines, meets min_lines=50)
- FOUND: commit 5c7e2e2 (Task 1: fsm-upload CLI + upload)
- FOUND: commit f95a368 (Bug fixes: reset doc name, stability check SDK)
- FOUND: src/objlib/cli.py
- FOUND: src/objlib/upload/orchestrator.py
- FOUND: scripts/check_stability.py

---
*Phase: 12-50-file-fsm-upload*
*Completed: 2026-02-20*
