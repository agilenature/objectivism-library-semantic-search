---
phase: 15-consistency-store-sync
plan: 02
subsystem: contract + temporal-stability
tags: [fsm, store-sync, contract, vlid-07, temporal-stability]

requires:
  - phase: 15-01
    provides: "Lag measurement: P50=7.3s, P95=10.1s, 5-20% failure rate"
provides:
  - "VLID-07 gate: PASS — temporal stability confirmed at T=0, T+4h, T+24h"
  - "governance/store-sync-contract.md — FSM/store-sync reconciliation policy"
  - "downgrade_to_failed() — 7th authorized gemini_state write site"
  - "Phase 15 COMPLETE — Phase 16 UNBLOCKED"
affects: [16-full-library-upload]

key-files:
  created:
    - governance/store-sync-contract.md
  modified:
    - src/objlib/upload/recovery.py

key-decisions:
  - "downgrade_to_failed() is 7th authorized write site: indexed -> failed, OCC-guarded"
  - "store-sync role: scheduled + targeted post-run (escalated from scheduled-only by 5-20% failure rate)"
  - "VLID-07 gate PASSED: T=0 STABLE, T+4h STABLE, T+24h STABLE (90 indexed, 0 orphans)"
  - "Phase 15 COMPLETE — all 3 success criteria met (SC1 from 15-01, SC2+SC3 from 15-02, SC4 from temporal checks)"

duration: multi-session (temporal checkpoint)
completed: 2026-02-23
---

# Phase 15 Plan 02: FSM/store-sync Contract + Temporal Stability Summary

**VLID-07 gate: PASS. All 4 success criteria met. Three temporal checkpoints stable (T=0, T+4h, T+24h ~20h50m). Phase 15 COMPLETE. Phase 16 UNBLOCKED.**

## Performance

- **Duration:** Multi-session (temporal checkpoint protocol)
- **Task 1 completed:** 2026-02-22 ~16:04 UTC (T=0)
- **T+4h check:** 2026-02-22 22:12:16 UTC
- **T+24h check:** 2026-02-23 12:54:49 UTC (~20h50m, run at user request)
- **Tasks:** 3 (Task 1 auto, Task 2 human-verify checkpoint, Task 3 auto)

## Accomplishments

- Implemented `downgrade_to_failed()` as the 7th authorized `gemini_state` write site
- Created `governance/store-sync-contract.md` — authoritative FSM/store-sync reconciliation policy
- Confirmed temporal stability at T=0, T+4h, and T+24h (all STABLE, no drift)
- Declared VLID-07 gate PASS — Phase 16 unblocked

## Artifacts Created

### governance/store-sync-contract.md

8-section authoritative contract document covering:
1. Overview — FSM as writer, store-sync as auditor
2. Roles and ownership (FSM owns writes, store-sync owns read-verification)
3. Store-sync classification: **Scheduled + targeted post-run** (justified by 5-20% failure rate)
4. Disagreement resolution policy (empirical searchability is authoritative)
5. Authorized DB write sites (all 7 enumerated)
6. Step-by-step protocol for FSM/store-sync disagreement
7. Invariants (5 invariants, including "store-sync never promotes")
8. Temporal stability results (T=0, T+4h, T+24h verbatim output)

### src/objlib/upload/recovery.py — downgrade_to_failed()

7th authorized `gemini_state` write site. Transitions INDEXED → FAILED with:
- OCC guard (`WHERE gemini_state = 'indexed'`)
- `error_message` set with reason string
- `version` incremented
- Returns `True` if downgrade succeeded, `False` if file already changed state

Full write site inventory (per contract):
| # | Function | Transition |
|---|----------|-----------|
| 1 | `transition_to_uploading()` | untracked → uploading |
| 2 | `transition_to_processing()` | uploading → processing |
| 3 | `transition_to_indexed()` | processing → indexed |
| 4 | `transition_to_failed()` | any → failed |
| 5 | `finalize_reset()` | indexed → untracked |
| 6 | `retry_failed_file()` | failed → untracked |
| 7 | `downgrade_to_failed()` | indexed → failed (store-sync only) |

## Temporal Stability Results

### T=0 (2026-02-22 ~16:04 UTC)

STABLE — 90 indexed, 90 store docs, 0 orphans, 6/6 assertions pass.
(Recorded in STATE.md at checkpoint; script output not saved to disk.)

### T+4h (2026-02-22 22:12:16 UTC)

```
==============================================================
  TEMPORAL STABILITY CHECK v2
==============================================================
  Time:   2026-02-22 22:12:16 UTC
  Store:  objectivism-library
  DB:     data/library.db
  Query:  'Ayn Rand theory of individual rights and capitalism'
==============================================================

PASS  Assertion 1 -- Count invariant: DB indexed=90, store docs=90
PASS  Assertion 2 -- DB->Store (no ghosts): all 90 indexed files present in store
PASS  Assertion 3 -- Store->DB (no orphans): all 90 store docs match DB records
PASS  Assertion 4 -- No stuck transitions: 0 files in 'uploading' state
PASS  Assertion 5 -- Search returns results: 5 citations returned
PASS  Assertion 6 -- Citation resolution: all 5 citations resolve to DB records

  Passed: 6 / Failed: 0 / Warnings: 0 / Elapsed: 9.2s

VERDICT: STABLE
```

store-sync: 0 orphans, store clean.

### T+24h (2026-02-23 12:54:49 UTC, ~20h50m elapsed)

```
==============================================================
  TEMPORAL STABILITY CHECK v2
==============================================================
  Time:   2026-02-23 12:54:49 UTC
  Store:  objectivism-library
  DB:     data/library.db
  Query:  'Ayn Rand theory of individual rights and capitalism'
==============================================================

PASS  Assertion 1 -- Count invariant: DB indexed=90, store docs=90
PASS  Assertion 2 -- DB->Store (no ghosts): all 90 indexed files present in store
PASS  Assertion 3 -- Store->DB (no orphans): all 90 store docs match DB records
PASS  Assertion 4 -- No stuck transitions: 0 files in 'uploading' state
PASS  Assertion 5 -- Search returns results: 5 citations returned
PASS  Assertion 6 -- Citation resolution: all 5 citations resolve to DB records

  Passed: 6 / Failed: 0 / Warnings: 0 / Elapsed: 8.1s

VERDICT: STABLE
```

store-sync: 0 orphans, store clean.

**All three checkpoints: zero drift. DB and store perfectly synchronized throughout.**

## VLID-07 Gate Verdict: PASS

Success criteria review:

| SC | Criterion | Status | Evidence |
|----|-----------|--------|---------|
| SC1 | Lag measured empirically (≥20 imports, P50/P95/P99, targeted queries) | **PASS** | 15-01-SUMMARY.md: Run A P50=7.3s P95=10.1s 5% failure; Run B P50=7.4s P95=44.3s 20% failure |
| SC2 | store-sync role explicitly classified (scheduled + targeted post-run) | **PASS** | governance/store-sync-contract.md §3, justified by 5-20% failure rate |
| SC3 | FSM/store-sync contract with disagreement resolution policy | **PASS** | governance/store-sync-contract.md §4 (empirical searchability is authoritative) |
| SC4 | check_stability.py STABLE at T=0, T+4h, T+24h | **PASS** | Three checkpoints above, all 6/6 assertions, 0 orphans |

**VLID-07: PASS — Phase 15 gate satisfied.**

## Impact on Phase 16

Phase 16 (Full Library Upload + 07-07 TUI smoke test) is now UNBLOCKED.

What the contract means for the 1,748-file upload:
- store-sync MUST run after each `fsm-upload` batch (not just scheduled)
- Silent failure rate 5-20% means ~87-350 files may need downgrade → retry across the full corpus
- `downgrade_to_failed()` is the recovery mechanism — no new code needed
- Temporal stability confirms the 90-file corpus is stable after 21h with zero drift

The check_stability.py STAB-04 gate gates Phase 16 temporal checkpoints (same protocol).
Plan 15-03 will upgrade check_stability.py with Assertion 7 (per-file searchability sample).

## Self-Check Results

### Truths
- [x] store-sync ongoing role classified as "scheduled + targeted post-run" — VERIFIED: governance/store-sync-contract.md §3
- [x] FSM/store-sync contract documented with disagreement resolution policy — VERIFIED: governance/store-sync-contract.md §4
- [x] downgrade_to_failed() exists and transitions INDEXED → FAILED — VERIFIED: recovery.py
- [x] check_stability.py STABLE at T=0, T+4h, T+24h — VERIFIED: all three checkpoints above

### Artifacts
- [x] governance/store-sync-contract.md exists and contains "disagreement resolution" — VERIFIED
- [x] governance/store-sync-contract.md contains "downgrade_to_failed" — VERIFIED
- [x] governance/store-sync-contract.md contains "7th authorized write site" — VERIFIED
- [x] src/objlib/upload/recovery.py contains downgrade_to_failed — VERIFIED

## Self-Check: PASSED

---
*Phase: 15-consistency-store-sync*
*Completed: 2026-02-23*
