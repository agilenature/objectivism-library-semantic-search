---
phase: 16-full-library-upload
plan: 02
checkpoint: T+24h
status: BLOCKED -- instrument failures discovered; Phase 16.1 inserted
---

# Phase 16 Plan 02: T+24h Check (PARTIAL -- BLOCKED)

**Timestamp:** 2026-02-24 10:12:41 UTC (~15h51m elapsed from T=0)
**Note:** Nominal T+24h was ~18:22 UTC. Check run ~6h early but findings are structural, not timing-sensitive.

## check_stability Output (verbatim)

```
==============================================================
  TEMPORAL STABILITY CHECK v2
==============================================================
  Time:   2026-02-24 10:12:41 UTC
  Store:  objectivism-library
  DB:     /Users/david/projects/objectivism-library-semantic-search/data/library.db
  Query:  'Ayn Rand theory of individual rights and capitalism'
  Sample: 20 indexed files (Assertion 7)
==============================================================

Checking prerequisites...
  .       Resolved store: objectivism-library -> fileSearchStores/objectivismlibrary-9xl9top0qu6u

Loading database...
  .       DB state counts: indexed=1749, untracked=136
  .       Indexed count: 1749

Listing store documents...
  .       Store document count: 1749
  .       Store doc names (sample): ['006gl0nplwn4-j2fh700c5crj', '00jqivefpbmr-kl21errkb2xc', '00zgwu7oap3b-drtd1a2j5pq3']

Structural checks...
  PASS  Assertion 1 -- Count invariant: DB indexed=1749, store docs=1749
  PASS  Assertion 2 -- DB->Store (no ghosts): all 1749 indexed files present in store
  PASS  Assertion 3 -- Store->DB (no orphans): all 1749 store docs match DB records
  PASS  Assertion 4 -- No stuck transitions: 0 files in 'uploading' state

Search + citation resolution...
  .       Querying: 'Ayn Rand theory of individual rights and capitalism'
  PASS  Assertion 5 -- Search returns results: 5 citations returned
  FAIL  Assertion 6 -- Citation resolution: 2/5 citations unresolvable: ['p4exrsn9zxzc', 'acsi23mitihy']

Per-file searchability sample...
  [20 per-file queries run -- see full output]
  FAIL  Assertion 7 -- Per-file searchability: 12/20 files not found (exceeds 4 tolerance):
    ['22 - __10 - More on Breaking Out of a Vicious Cycle - 10-24-2023.txt',
     'MOTM_2022-02-06_History-of-the-Objectivist-Movement-Part.txt',
     'Perception - Class 05-01.txt',
     'ITOE - Class 01-01 - Office Hours.txt',
     'Episode 418 [1000376455369].txt',
     'Episode 122 [1000085122120].txt',
     'Episode 218 [1000116042581].txt',
     'Objectivist Logic - Class 15-01.txt',
     'What Is Liberty_ - Lesson 05 - Government_ Who Needs It.txt',
     'Episode 146 [1000090293258].txt',
     'Episode 360 [1000335653941].txt',
     'Ayn Rand - Capitalism - The Unknown Ideal (1986).txt']

==============================================================
  Passed:   5
  Failed:   2
  Warnings: 0
  Elapsed:  170.7s
==============================================================

  VERDICT: UNSTABLE
    * Assertion 6 -- Citation resolution
    * Assertion 7 -- Per-file searchability
```

## store-sync Output (verbatim)

```
Canonical uploaded file IDs in DB: 674
Canonical store doc IDs in DB: 1749
Total store documents: 1749
Canonical documents: 1749
Orphaned documents: 0
Store is clean — nothing to purge.
```

## DB State Query

```
=== .txt files by gemini_state ===
  indexed: 1748
Total .txt: 1748
```

**Note:** check_stability shows 1749 indexed (all file types). The 1749th is `Andrew Bernstein - Heroes, Legends, Champions - Why Heroism Matters.md`, indexed at 2026-02-23T22:56:15 UTC (late remediation pass). Bidirectional consistency holds.

## Comparison to T=0

| Metric | T=0 | T+24h | Delta |
|--------|-----|-------|-------|
| Indexed (all types) | 1748 | 1749 | +1 (.md file) |
| Store docs | 1748 | 1749 | +1 |
| Orphans | 0 | 0 | 0 |
| A1 Count invariant | PASS | PASS | stable |
| A2 DB→Store ghosts | PASS | PASS | stable |
| A3 Store→DB orphans | PASS | PASS | stable |
| A4 Stuck transitions | PASS | PASS | stable |
| A5 Search returns results | PASS | PASS | stable |
| A6 Citation resolution | FAIL (2/5) | FAIL (2/5) | same IDs -- not temporal |
| A7 Per-file searchability | FAIL (6/20) | FAIL (12/20) | worse -- sampling variance |

## Root Cause Analysis

### A6 — Citation Resolution Failure

The 2 unresolvable citation titles (`p4exrsn9zxzc`, `acsi23mitihy`) ARE indexed files in the DB:
- `p4exrsn9zxzc` → `Objectivist Logic - Class 15-02.txt` (store_doc_id: `p4exrsn9zxzc-s0b8omb47n8q`, gemini_file_id: NULL)
- `acsi23mitihy` → `Seminar on Ayn Rand's Political Philosophy - Lesson 04 - The Objectivity of the Free Market.txt` (store_doc_id: `acsi23mitihy-761ecyzi2yik`, gemini_file_id: NULL)

**Scale of impact:** 1,075 of 1,749 indexed files have `gemini_file_id=NULL` (61% of corpus). These files were manually DB-restored after the RecoveryManager bug on 2026-02-23 without re-uploading. Their raw file IDs were cleared.

**Lookup failure chain:**
1. Filename lookup: citation title is a file ID (`p4exrsn9zxzc`), not a filename → FAIL
2. `gemini_file_id` lookup: column is NULL → FAIL
3. API fallback (`files.get()`): raw file expired/cleared → API error → silently ignored

**LIKE fix rejected by user.** Correct fix must use exact-match semantics (SUBSTR-based prefix extraction from `gemini_store_doc_id`). Requires spike to confirm retrieved_context.title identity contract first.

### A7 — Per-File Searchability Failure

12/20 = 60% miss rate. The secondary match logic (`title_in_result in store_doc_id`) may also fail for NULL-gemini_file_id files. Two sub-patterns:
- ~8/12: opaque-named files ("Episode 418 [1000376455369].txt") — query "What is 'Episode 418 [...]' about?" semantically matches all ~333 Peikoff Podcast episodes
- ~4/12: structured titles ("Perception - Class 05-01.txt", "Objectivist Logic - Class 15-01.txt") — may be matching failures, not retrieval failures

**User mandate:** tolerance = 0. Full audit of all 1,749 filenames required. Per-pattern query strategy must be designed.

## Verdict

**T+24h: BLOCKED — Instrument failures discovered, not temporal decay**

Structural data is sound (A1-A5 all PASS). The failures are in the instrument's identity model and query strategy, not in the FSM or data pipeline. However, A6 represents a real user-facing defect: ~61% of the indexed corpus cannot produce resolved citations. The milestone DoD ("never appears in search results") is not met.

**Action:** Phase 16.1 inserted to resolve A6 and A7 with HOSTILE posture before Phase 16 temporal protocol can resume.
