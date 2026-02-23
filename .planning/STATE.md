# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-19)

**Core value:** Three equally critical pillars -- semantic search quality, metadata preservation, incremental updates
**Current focus:** Milestone v2.0 -- Gemini File Lifecycle FSM
**Definition of done:** `[Unresolved file #N]` never appears in TUI search results

## Current Position

Phase: 16 of 17 (Full Library Upload) -- IN PROGRESS (Wave 1 complete: 16-01 and 16-04 done)
Plan: 2 of 4 complete in Phase 16 (16-01 and 16-04)
Status: Full library upload COMPLETE. 1748/1748 .txt files indexed. Awaiting temporal stability (16-02).
Last activity: 2026-02-23 -- Plan 16-01 COMPLETE. All 1748 .txt files indexed, store-sync clean, T=0 baseline recorded.

Progress: [#########################] 25/32 v2.0 plans complete

Note: Phase 07-07 (TUI integration smoke test from v1.0) deferred to Phase 16, plan 16-03.
  Runs against full live corpus after upload -- more meaningful than running on empty store.
  Plan file: .planning/phases/07-interactive-tui/07-07-PLAN.md

v2.0 Phase Progress:
Phase 8:  [##########] 3/3 plans -- COMPLETE (Store Migration Precondition)
Phase 9:  [##########] 2/2 plans -- COMPLETE (Wave 1: Async FSM Spike) -- gate PASSED 2026-02-20
Phase 10: [##########] 2/2 plans -- COMPLETE (Wave 2: Transition Atomicity) -- gate PASSED 2026-02-20
Phase 11: [##########] 2/2 plans -- COMPLETE (Wave 3: display_name + Import) -- gate PASSED 2026-02-20
Phase 12: [##########] 6/6 plans -- COMPLETE (Wave 4: 50-File FSM Upload) -- gate PASSED 2026-02-22
Phase 13: [##########] 2/2 plans -- COMPLETE (Wave 5: State Column Retirement) -- gate PASSED 2026-02-22
Phase 14: [##########] 3/3 plans -- COMPLETE (Wave 6: Batch Performance) -- VLID-06 PASSED + SC2 gap closed 2026-02-22
Phase 15: [##########] 3/3 plans -- COMPLETE (Wave 7: Consistency + store-sync) -- gate PASSED 2026-02-23
Phase 16: [#####░░░░░] 2/4 plans -- IN PROGRESS (16-01 + 16-04 COMPLETE, T=0 recorded) (Wave 8: Full Library Upload + 07-07)
Phase 17: [░░░░░░░░░░] 0/4 plans -- BLOCKED by Phase 16 gate (RxPY TUI reactive pipeline)

## Performance Metrics

**v1.0 Velocity (archived):**
- Total plans completed: 40
- Average duration: 3.2 min
- Total execution time: 128 min

**v2.0 Velocity:**
- Total plans completed: 25
- Average duration: 21.8 min
- Total execution time: 524 min

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [v2.0 init]: Store migration precondition -- delete objectivism-library-test, create objectivism-library (irreversible, search offline until Phase 12)
- [v2.0 init]: AI-enriched metadata is sacred -- no operation may delete/reset metadata columns
- [v2.0 init]: HOSTILE distrust for Phases 9, 10, 11 -- affirmative evidence required, not absence of failure
- [v2.0 init]: Wave gates are BLOCKING -- each phase's success criteria must pass before the next phase begins
- [v2.0 init]: STALE state and scanner deferred to v3 (STALE-01, STALE-02)
- [v2.0 init]: Concurrency lock deferred to v3 (CONC-01)
- [08-01]: V9 migration uses individual ALTER TABLE with try/except (not executescript) for column-exists safety
- [08-01]: No CHECK constraint on gemini_state -- FSM enforces valid transitions in application code
- [08-01]: Destructive state reset in standalone script (not auto-migration) -- requires explicit invocation
- [08-03]: Stability instrument v2 uses raw genai SDK (no objlib dependency) for independence
- [08-03]: Prerequisite failures produce exit 2 (error) not exit 1 (unstable) -- distinguishes config from sync
- [08-03]: Vacuous pass on empty store prevents false negatives during migration window
- [08-02]: Create new store before deleting old -- never leaves system without a store
- [08-02]: force=True required for non-empty store deletion (FAILED_PRECONDITION otherwise)
- [08-02]: Store resource name persisted to library_config for all future phases
- [09-01]: python-statemachine 2.6.0 PASSES async guard binary test -- library path confirmed, no pivot to hand-rolled
- [09-01]: on_enter_state callback params must be optional (None defaults) for activate_initial_state() compatibility
- [09-01]: All 4 affirmative evidence criteria pass: DB invariants, JSON event log, thread/task leak check, same-file adversarial test
- [09-02]: python-statemachine 2.6.0 selected as final FSM approach -- all 9 test criteria pass, documented in APPROACH-SELECTION.md
- [09-02]: FileTransitionManager is the Phase 10 bridge pattern between AsyncUploadStateManager and StateMachineAdapter
- [09-02]: Phase 9 BLOCKING gate PASSED -- Phase 10 unblocked
- [10-01]: Intent columns on files table (not separate table) -- simple schema, no cross-table joins for recovery
- [10-01]: safe_delete catches ClientError code==404 as success, re-raises all others
- [10-01]: Txn A writes intent (no version increment), Txn B finalizes (increments version)
- [10-01]: ResetTransitionManager bypasses StateMachineAdapter -- multi-step transitions need direct DB control
- [10-02]: RecoveryCrawler uses linear step resumption (no retry loops) -- GA-9
- [10-02]: retry_failed_file() is standalone function (not FSM adapter) for FAILED->UNTRACKED escape
- [10-02]: SC3 measurement: recovery 28 lines <= transition 36 lines, zero while loops
- [10-02]: Phase 10 BLOCKING gate PASSED -- Phase 11 unblocked
- [11-01]: File.display_name is 100% caller-controlled -- 13/13 exact round-trip match across special chars, case, spaces, 500-char names
- [11-01]: Document.display_name = file resource ID, NOT submitted display_name -- 0/13 match. Citation mapping must use file_id -> DB lookup.
- [11-01]: documents.get() P50=0.243s, documents.list() P50=0.495s -- get() is 2x faster and should be primary visibility check
- [11-01]: No exponential backoff needed for post-import visibility -- documents visible immediately after import completes
- [11-01]: Leading whitespace in display_name causes import hang -- defensive strip() recommended
- [11-02]: Non-blocking polling: single documents.get() after operation.done is sufficient (P99=0.253s, 1,184x safety margin on 300s timeout)
- [11-02]: No long-running polling loop needed -- visibility is immediate after import completes
- [11-02]: Phase 11 BLOCKING gate PASSED -- all 3 success criteria met, Phase 12 unblocked
- [12-01]: FSM is validation-only (no on_enter_state callbacks) -- transition_to_*() methods handle DB persistence
- [12-01]: No final=True on any FSM state (Phase 10 finding -- causes InvalidDefinition)
- [12-01]: transition_to_failed has no gemini_state guard (fail can come from uploading or processing)
- [12-02]: retry_failed_file writes gemini_state directly (6th allowed write site) -- standalone FAILED->UNTRACKED escape per Phase 10 design
- [12-02]: write_reset_intent does NOT increment version (Txn A pattern from Phase 10)
- [12-02]: RecoveryCrawler.recover_all returns (recovered, occ_failures) tuple for caller visibility
- [12-03]: gemini_store_doc_id stores document name suffix only, not full resource name -- reconstruct with store_name/documents/ prefix when needed
- [12-03]: Poll timeout on large files (3MB+) requires store-lookup fallback -- operations.get() returns done=None indefinitely for some imports
- [12-03]: retry_failed_file() must be called before retry pass in _process_fsm_batch -- stale version in file_info dict causes OCC conflicts
- [12-05]: T+24h gate PASSED at 21:43:47Z (25h53m elapsed) -- Phase 13 UNBLOCKED. All deltas zero.
- [12-06]: T+36h CONFIRMED at 08:43:41Z Feb 22 (60h53m elapsed) -- T+24h verdict non-transient. Phase 12 temporal stability protocol COMPLETE. Phase 12 COMPLETE.
- [13-01]: --set-pending CLI flags will be REMOVED (not repurposed) per locked decision #7
- [13-01]: Historical V7 migration SQL frozen -- only SCHEMA_SQL (V1 DDL) and new V11 migration modified
- [13-01]: is_deleted INTEGER NOT NULL DEFAULT 0 replaces status='LOCAL_DELETE' filtering
- [13-02]: V11 applied -- status column physically dropped, is_deleted added, CHECK(gemini_state IN ('untracked','uploading','processing','indexed','failed')) enforced
- [13-02]: FileStatus enum fully removed; all 84 status references rewritten across 10 src files + 8 test files + 5 scripts
- [13-02]: Legacy record_upload_intent/record_upload_failure retain gemini_state writes (uploading/failed) for backward compat
- [13-02]: Phase 13 BLOCKING gate PASSED -- Phase 14 unblocked
- [14-01]: Bottleneck identified as db_total_ms (WAL lock contention): lock_wait P95=39.88ms is 99.8% of db_total P95=39.95ms at c=10 zero profile
- [14-01]: Threshold 1 PASS (0.89s vs 300s) and Threshold 2 PASS (8.73s vs 21600s) -- enormous margin
- [14-01]: FSM dispatch overhead negligible (P95 < 0.15ms) -- python-statemachine 2.6.0 is not the bottleneck
- [14-02]: VLID-06 declared PASS -- both thresholds met with 337x (T1) and 66x (T2) margin, zero mitigation needed
- [14-02]: Production upload recommendation: c=10 concurrency (FSM+DB is 0.17% of total execution time at realistic profile)
- [14-02]: WAL contention production-irrelevant: super-linear at c>=50 zero profile only, real API latency distributes writes
- [14-02]: Phase 14 BLOCKING gate PASSED -- Phase 15 unblocked
- [14-03]: Shared connection mitigation eliminates 98% of WAL lock contention (lock_wait P95: 40.65ms -> 0.77ms) -- available as production option
- [14-03]: SC2 gap closed: mitigation tested with before/after measurements, results saved to results-mitigation-*.json
- [15-01]: Import-to-searchable lag: P50=7.3s, P95=10.1s, max=10.1s -- meaningful gap between listing (~1.5s) and search visibility (~7s)
- [15-01]: Silent failure rate 5% (1/20 files never searchable in 300s) -- likely query-specificity issue, not indexing failure
- [15-01]: Listing visibility fast (~1.5-2s, consistent with Phase 11), but embedding/search indexing adds 5-8s
- [15-01]: 5% failure rate triggers store-sync escalation consideration per Q7 decision (any failure rate > 0%)
- [15-02]: downgrade_to_failed() is 7th authorized gemini_state write site: indexed -> failed, OCC-guarded, store-sync only
- [15-02]: store-sync role = scheduled + targeted post-run (escalated from scheduled-only by 5-20% silent failure rate)
- [15-02]: VLID-07 gate PASSED -- T=0 STABLE, T+4h STABLE, T+24h STABLE (90 indexed, 0 orphans across all checks)
- [15-02]: Phase 15 COMPLETE -- Phase 16 UNBLOCKED
- [15-03]: check_stability.py upgraded to 7 assertions; Assertion 7 samples 5 random indexed files via targeted per-file queries; --sample-count flag controls sample size (0=skip)
- [15-03]: Matching by gemini_file_id (primary), tolerance of max(1, N//5) misses for known 5-20% query-specificity gap
- [15-03]: Phase 15 FULLY COMPLETE -- all 3 plans done; VLID-07 gate: see 15-02-SUMMARY.md (15-03 adds coverage, does not re-gate)
- [16-01]: RecoveryManager must NOT reset indexed files for expired raw files (store docs are permanent, raw files are ephemeral)
- [16-01]: store-sync matches by gemini_store_doc_id as fallback when gemini_file_id is cleared
- [16-01]: CLI fsm-upload pre-flight resets FAILED -> UNTRACKED automatically for remediation re-runs
- [16-01]: Poll timeout files manually verified via store API and upgraded to indexed (matches Phase 12-03 finding)
- [16-01]: At full scale (1748 files), T=0 check_stability shows 5/7 PASS (assertions 1-5), 2/7 FAIL (assertions 6-7 due to search index lag)
- [16-04]: top_k=20 default across search pipeline (client, service, CLI, TUI); flat chunk list per locked decision #3; rank = "[N / total]" in bold cyan
- [16-04]: Scroll hints shown when result count > 3; ResultItem rank/total parameters optional for backward compatibility

### Roadmap Evolution

- Phase 17 added (2026-02-22): RxPY reactive observable pipeline for TUI event streams, validated by pre/post UATs. Replaces manual debounce/generation-tracking, @work(exclusive=True), and scattered filter-refire logic. 4 plans: spike -> pre-UAT -> impl -> post-UAT.

### Pending Todos

None.

### Blockers/Concerns

- Store orphan accumulation during FSM retry pass -- RecoveryManager fix in 16-01 prevents most cases; store-sync after any fsm-upload run still recommended

## Session Continuity

Last session: 2026-02-23
Stopped at: Plan 16-01 COMPLETE. All 1748 .txt files indexed. T=0 baseline recorded. Awaiting 16-02 temporal stability.

Temporal stability log (Phase 16 -- full library):
- T=0  (2026-02-23 18:21:59 UTC): 5/7 PASS -- 1748 indexed, 0 orphans, assertions 1-5 pass; assertions 6-7 fail (search index lag at scale)

Temporal stability log (Phase 15 -- 90-file proxy):
- T=0  (2026-02-22 ~16:04 UTC): STABLE -- 90 indexed, 6/6 pass, 0 orphans
- T+4h (2026-02-22  22:12 UTC): STABLE -- 90 indexed, 6/6 pass, 0 orphans
- T+24h (2026-02-23 12:54 UTC): STABLE -- 90 indexed, 6/6 pass, 0 orphans (~20h50m elapsed)
- Post-upgrade (2026-02-23 13:05 UTC): STABLE -- 90 indexed, 7/7 pass (Assertion 7: 4/5 found, 1 within tolerance)

Resume file: .planning/phases/16-full-library-upload/ (Phase 16 plans)
Resume instruction: Plan 16-01 done. Plan 16-04 done. Next: 16-02 (temporal stability T+4h/T+24h/T+36h) then 16-03 (TUI smoke test). T+4h check should run ~22:22 UTC or later.
