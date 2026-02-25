# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-19)

**Core value:** Three equally critical pillars -- semantic search quality, metadata preservation, incremental updates
**Current focus:** Milestone v2.0 -- Gemini File Lifecycle FSM
**Definition of done:** `[Unresolved file #N]` never appears in TUI search results

## Current Position

Phase: 16.4 (Metadata Pipeline Invariant + Comprehensive Retrievability Audit) -- IN PROGRESS
Plan: Plan 16.4-02 (Structural Quality Audit) -- COMPLETE
Status: 16.4-02 complete. 40 Episodes batch-extracted + re-uploaded with identity headers. 1 Book skipped (oversized). Audit exits 0 with per-series breakdown. All 1,748 non-skipped indexed files have file_primary_topics. Next: 16.4-03 (comprehensive retrievability audit).
Last activity: 2026-02-25 -- Completed 16.4-02: batch-extract 40 Episodes, approve all, re-upload with Tags, extend audit with per-series breakdown + condition 6, store-sync 0 orphans

Progress: [##################################] 34/38 v2.0 plans complete

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
Phase 16:  [#####░░░░░] 2/4 plans -- IN PROGRESS (16-01 + 16-04 COMPLETE; 16-02 BLOCKED by Phase 16.4 gate)
Phase 16.4:[#####░░░░░] 2/4 plans -- IN PROGRESS (16.4-01 + 16.4-02 COMPLETE: routing + structural quality audit; BLOCKS Phase 16-02)
Phase 16.1:[##########] 3/3 plans -- COMPLETE (audit + fix + re-validation done; A7 structural fix delivered in Phase 16.3)
Phase 16.2:[##########] 2/2 plans -- COMPLETE (audit exits 0; all 1,885 files satisfy invariant; Phase 16.3 readiness 100%; gate PASSED 2026-02-24)
Phase 16.3:[##########] 3/3 plans -- COMPLETE (Retrievability Research: diagnosis + intervention + production remediation; all 1,749 files re-uploaded with identity headers; gate PASSED 2026-02-25; ITOE OH 60 files also batch-extracted + re-uploaded 2026-02-25)
Phase 17:  [░░░░░░░░░░] 0/4 plans -- BLOCKED by Phase 16 gate (RxPY TUI reactive pipeline)
Phase 18:  [░░░░░░░░░░] 0/5 plans -- BLOCKED by Phase 17 gate (RxPY codebase-wide async migration)

## Performance Metrics

**v1.0 Velocity (archived):**
- Total plans completed: 40
- Average duration: 3.2 min
- Total execution time: 128 min

**v2.0 Velocity:**
- Total plans completed: 31
- Average duration: 18.7 min
- Total execution time: 580 min

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
- [16.1-01]: Identity contract CONFIRMED: retrieved_context.title = 12-char prefix of gemini_store_doc_id = file resource ID (13/13 Phase 11 measurements)
- [16.1-01]: SUBSTR fix validated: all 1,749 files have 1 hyphen, 12-char unique prefix, 0 NULLs in gemini_store_doc_id
- [16.1-01]: File ID restoration REJECTED: 1 mismatch file (store_doc_id prefix != file_id suffix) would be corrupted
- [16.1-01]: A7 matching logic CONFIRMED CORRECT: secondary match (substring in store_doc_id) handles NULL file_id and mismatch cases
- [16.1-01]: 12 A7 failures are QUERY failures: display_title and title are NULL for all 1,749 files; topic is the only discriminating metadata
- [16.1-01]: Episode files (333) excluded from A7: zero discriminating metadata (topic=NULL, display_title=NULL, title=NULL)
- [16.1-01]: Corpus breakdown: Episode(333 exclude), MOTM(468 topic), Other-discriminating(508 topic!=stem), Other-stem(440 topic==stem risk)
- [16.1-02]: A6 uses SUBSTR(gemini_store_doc_id, 1, INSTR(gemini_store_doc_id, '-') - 1) for citation resolution -- covers all 1,749 files
- [16.1-02]: A7 matching changed from substring 'in' to explicit split('-')[0] == (functionally equivalent, more explicit)
- [16.1-02]: Production citation pipeline: 4-pass lookup (filename -> store_doc_prefix -> gemini_file_id -> API fallback)
- [16.1-02]: A7 initial run: 6/7 PASS, A7 FAIL (4/20 = 20% miss at zero tolerance) -- query-specificity failures, not code bugs
- [16.1-02]: A6 FIXED: all 5 citations resolve (previously 2/5 unresolvable for NULL gemini_file_id files)
- [16.1-03]: Fresh session run: A6 PASS. A7 FAIL 8/20 at zero tolerance. Two runs confirm structural pattern: category A = course class-number files (topic==stem, ~440/1416 = 31% of non-Episode corpus), category B = generic MOTM topics. Not transient, not a code bug. Zero-tolerance is empirically wrong for this corpus. Tolerance decision blocks Phase 16-02.
- [16.2-01]: file_primary_topics is authoritative for "topics populated" -- audit checks EXISTS(file_primary_topics), not metadata_json
- [16.2-01]: Signal A (scanner topic NULL) uses files.metadata_json, catches 333 Episode files. MOTM NOT caught (468/468 have scanner topic).
- [16.2-01]: Boilerplate threshold 40% identifies 5 topics: epistemology, ethics, metaphysics, rational_egoism, values
- [16.2-01]: Upload gate enforces scan -> batch-extract -> approve -> upload ordering invariant in get_fsm_pending_files()
- [16.2-01]: 40 Episode files failed Mistral extraction (JSON format issues) -- at failed_validation status, retriable
- [16.2-01]: 1 oversized file (Philosophy Who Needs It) marked skipped by batch_orchestrator -- exceeds Mistral context window
- [16.2-01]: Audit exits 0 with Phase 16.3 readiness: MOTM 468/468, MOTM scanner topic 468/468, Other-stem 443/443
- [16.3-01]: H1 PARTIALLY FALSIFIED: content_preparer.py injects Tier 4 AI analysis header (summary, key_arguments, philosophical_positions) but NOT identity fields (filename, class number, course, topic, primary_topics)
- [16.3-01]: H2 FALSIFIED: two independent A7 runs show same two failure categories (Category A = Other-stem, Category B = generic MOTM) -- structural, not transient
- [16.3-01]: H3 CONFIRMED: class number strings (e.g., "09-02", "02-02") absent from raw transcript content -- zero grep matches across full files
- [16.3-01]: H4 FALSIFIED: retrieved_context.document_name is NULL for all File Search API responses -- field is Vertex AI Search only
- [16.3-01]: Root cause = discriminating identifiers absent from indexed content. Fix = extend existing content_preparer.py header with identity fields at TOP of header
- [16.3-01]: Gemini returns wrong files for class-number queries: "Objectivist Logic Class 09-02" returns Class 09-01, Class 05-01 -- target file absent from top 5
- [16.3-02]: Identity header format: --- DOCUMENT METADATA --- / Title/Course/Class/Topic/Tags / --- END METADATA --- prepended BEFORE existing [AI Analysis] header
- [16.3-02]: build_identity_header() in header_builder.py: file_path+conn -> structured header string. Class regex: r"Class\s+(\d{2}-\d{2})". Tags = space-separated primary_topics.
- [16.3-02]: Intervention test: E-A 100% rank 1 (3/3), C-A 50% (1/2), E-B 100% rank 1 (3/3), C-B 50% (1/2), W-H 100% rank 1 (3/3). Ephemeral store created+deleted. Prod untouched (1748->1748).
- [16.3-02]: GO for Plan 16.3-03 production rollout. header_builder.py is production-ready.
- [16.3-03]: Production remediation executed 2026-02-25. All 1,749 files re-uploaded with identity headers via re_enrich_retrieval.py (upload-first sequence). 1,737 succeeded first pass, 12 retried. Elapsed: ~7h25min.
- [16.3-03]: Post-remediation: 1,084 orphaned store docs accumulated (stale gemini_store_doc_id from prior cycles → delete-old-doc returned 404). Cleared by two store-sync --no-dry-run passes. Final: DB=1749, Store=1749, Orphans=0.
- [16.3-03]: store-sync bug fixed (database.py + cli.py): store-sync was matching store docs as canonical if display_name matched any known file ID, without verifying the full store_doc_id suffix. Added get_canonical_file_id_to_store_doc_map(); classification now requires exact suffix match.
- [16.3-03]: check_stability.py A7: always use full stem as query subject; Office Hour files excluded (60 files, same rationale as Episodes); tolerance=2 (large numbered series have inherent ~2% per-file miss rate).
- [16.3-03]: MEMORY.md permanent fix for _reset_existing_files() (delete_store_document before delete_file) NOT yet implemented in orchestrator.py. Remediation used standalone script. Fix remains documented in MEMORY.md; implement before next bulk fsm-upload --reset-existing operation.
- [16.4-01]: BOOK_SIZE_BYTES = 830,000 defined in src/objlib/constants.py. Byte check placed BEFORE read_text in batch_orchestrator.py loop -- book files never loaded into memory. Two-tier skip: BOOK_SIZE_BYTES (structural routing) + MAX_DOCUMENT_TOKENS (Mistral limit).
- [16.4-01]: Layer 2 upload gate (state.py:714-717) verified sound: requires ai_metadata_status='approved' AND EXISTS file_primary_topics. No code change needed.
- [16.4-01]: 40 failed_validation Episodes + 1 skipped Book (552KB < 830KB) reset to pending. 60 needs_review OH files approved. Full grep audit: 77 ai_metadata_status refs across 7 files, 0 violations.
- [16.4-02]: 40 Episode files batch-extracted (8 primary_topics each, Mistral Batch API). 5 initial failures retried successfully (non-deterministic JSON format issues). 1 Book skipped (~115K tokens > 100K MAX_DOCUMENT_TOKENS).
- [16.4-02]: All 40 Episodes re-uploaded with updated identity headers (Tags field reflects new primary_topics). Store-sync: 15 orphans cleaned, DB=1749, Store=1749, Orphans=0.
- [16.4-02]: Condition 6 added to metadata audit: indexed non-skipped files without file_primary_topics. All 6 conditions PASS, exit code 0.
- [16.4-02]: Per-series breakdown: 9 series (Books, Episodes, ITOE, ITOE AT, ITOE AT OH, ITOE OH, MOTM, OL, Other). All non-Book series at 100% topics coverage. Books 96% (1 skipped).
- [16.4-02]: ITOE Advanced Topics (not ITOE Addenda) is the correct directory name for ITOE AT/ITOE AT OH series.

### Roadmap Evolution

- Phase 17 added (2026-02-22): RxPY reactive observable pipeline for TUI event streams, validated by pre/post UATs. Replaces manual debounce/generation-tracking, @work(exclusive=True), and scattered filter-refire logic. 4 plans: spike -> pre-UAT -> impl -> post-UAT.
- Phase 18 added (2026-02-23): RxPY codebase-wide async migration. Migrates all asyncio primitives outside tui/ to RxPY observables. 5 plans: 18-01 spike (HOSTILE gate) -> 18-02 Tier3 -> 18-03 Tier2 -> 18-04 Tier1 (fsm-upload --limit 20 gate) -> 18-05 validation + Canon update. Blocked by Phase 17.
- Phase 16.1 inserted (2026-02-24): Stability Instrument Correctness Audit. T+24h check blocked by A6 (1,075 files with gemini_file_id=NULL cause citation resolution failures; LIKE fix rejected -- must use exact-match semantics) and A7 (query strategy produces systematic false negatives for Episode/MOTM files; tolerance set to 0). HOSTILE posture: check_stability.py is the adversarial target. 3 plans: spike (7 challenges) -> fix -> re-validation (new T=0 baseline). BLOCKING Phase 16-02 and Phase 17.
- Phase 16.2 inserted (2026-02-24): Metadata Completeness Invariant Enforcement. ai_metadata_status is not a valid completeness invariant -- conflates "approved by scanner filename-parsing" (no primary_topics) with "approved by AI extraction" (has primary_topics). Root cause: _get_pending_files() LIKE '%.txt' silently excludes .md files (Bernstein Heroes book is pending with no extraction attempted). 26 books have ai_metadata_status='approved' but zero primary_topics. 2 plans: audit command + .md fix + batch-extract Bernstein -> verify audit exits 0. ADJUSTED 2026-02-24: audit command must also produce Phase 16.3 readiness breakdown (Other-stem/MOTM primary_topics coverage) — both categories at 100% required before Phase 16.3 metadata-header intervention.
- Phase 16.4 inserted (2026-02-25): Metadata Pipeline Invariant + Comprehensive Retrievability Audit. Root cause: every accumulated workaround in the stability instrument (OH excluded, Episodes excluded, tolerance raised) is an instance of the same violated invariant — the metadata pipeline has no structural rule that collapses all small non-book files to a single path (batch-extract → primary_topics → topic_aspects → review). The invariant: every .txt/.md file is either a book (large, exceeds Mistral context window, scanner-only 'skipped') or a non-book (must AI-extract). Phase 16.4 enforces this in 4 plans: (1) routing audit + fix — define book size threshold constant, enumerate and eliminate all category gates; (2) structural quality audit — `objlib metadata audit` per-series breakdown, exit 0 gate; (3) comprehensive retrievability audit — all 1,809 files, 3 query strategies, per-series hit rate tables, minimum viable query strategy identified; (4) A7 update + zero-tolerance validation — max_misses=0, no exclusion filters, two consecutive STABLE runs. BLOCKING Phase 16-02.
- Phase 16.3 inserted (2026-02-24): Gemini File Search Retrievability Research. A7 zero-tolerance failure is structural: ~440 "Other-stem" files (topic==stem, class-number queries have no semantic content) and generic MOTM files (~3% of 468) fail targeted per-file queries. Two independent runs (16.1-02: 4/20, 16.1-03: 8/20) confirm. Hypotheses: H1 (metadata not in indexed content), H2 (silent partial indexing), H3 (class numbers absent from transcript), H4 (document_name exact-match available). 3 plans: diagnosis spike (H1-H4 falsification) -> intervention test (fix on 6 failing files in test context) -> production remediation (pipeline extension + two fresh-session A7=0 confirmations). BLOCKING Phase 17. Depends on Phase 16.2 (primary_topics complete for metadata-header injection).

### Standing Constraints

These apply to ALL future phases and plans. They are not re-derived per phase.

- **No `--reset-existing` without explicit user instruction.** The ~1,748 files indexed in `objectivism-library` are production state. No plan may use `--reset-existing`, `_reset_existing_files()`, or any equivalent operation on already-indexed files unless the user explicitly requests it for a specific file or set of files. Validation and UAT tests use NEWLY added lectures or books (UNTRACKED state), not resets of existing corpus.
- **AI-enriched metadata is sacred** (carried from v2.0 init). No operation may delete, reset, or re-derive `metadata_json` or entity tables.
- **FAILED states on new uploads are not blockers.** RecoveryCrawler and `--retry-failed` handle recovery. A plan gate fails only if files are stuck in UPLOADING/PROCESSING, or if the pipeline crashes — not if some new files land in FAILED state on first pass.

### Pending Todos

None.

### Blockers/Concerns

- Store orphan accumulation during FSM retry pass -- RecoveryManager fix in 16-01 prevents most cases; store-sync after any fsm-upload run still recommended
- [RESOLVED] check_stability.py A6: FIXED in 16.1-02. SUBSTR-based prefix extraction from gemini_store_doc_id resolves all 1,749 files. All 5 citations now resolve.
- [RESOLVED] check_stability.py A7 tolerance: Production remediation complete (2026-02-25). All 1,749 files re-uploaded with identity headers. Two STABLE runs achieved (tolerance=2, Office Hour + Episode excluded). Gate PASSED. Phase 16-02 unblocked.

## Session Continuity

Last session: 2026-02-25
Stopped at: Plan 16.4-01 complete. BOOK_SIZE_BYTES constant defined, routing fixed, 41 files pending re-extraction, grep audit clean. Next: Plan 16.4-02 (batch-extract 41 pending files, re-upload with identity headers, extend audit with per-series breakdown).

Temporal stability log (Phase 16 -- full library, post-remediation):
- T=0 baseline: Run 1 (2026-02-25 11:50:32 UTC): STABLE -- 1749 indexed, 1749 store, 0 orphans; A7 19/20 (Objectivist Logic Class 10-02 miss, within tolerance=2); 333 Episode + 60 OH excluded
- T=0 baseline: Run 2 (2026-02-25 11:54:00 UTC): STABLE -- 1749 indexed, 1749 store, 0 orphans; A7 20/20; 333 Episode + 60 OH excluded
- Phase 16-02 T+4h: TBD (~2026-02-25 15:50 UTC)
- Phase 16-02 T+24h: TBD (~2026-02-26 11:50 UTC) -- BLOCKING gate for Phase 16 completion
- Phase 16-02 T+36h: TBD (~2026-02-26 23:50 UTC)

Prior Phase 16 stability log (pre-remediation, superseded):
- T=0   (2026-02-23 18:21:59 UTC): 5/7 PASS -- assertions 6-7 fail; gate BLOCKED
- T+24h (2026-02-24 10:12:41 UTC): 5/7 FAIL -- A6 fix needed, A7 structural failure. Phase 16.1 inserted.
- T=0 (corrected) (2026-02-24 15:47:47 UTC): 6/7 FAIL -- A6 PASS, A7 FAIL 8/20. Phase 16.3 inserted.

Temporal stability log (Phase 15 -- 90-file proxy):
- T=0  (2026-02-22 ~16:04 UTC): STABLE -- 90 indexed, 6/6 pass, 0 orphans
- T+4h (2026-02-22  22:12 UTC): STABLE -- 90 indexed, 6/6 pass, 0 orphans
- T+24h (2026-02-23 12:54 UTC): STABLE -- 90 indexed, 6/6 pass, 0 orphans (~20h50m elapsed)
- Post-upgrade (2026-02-23 13:05 UTC): STABLE -- 90 indexed, 7/7 pass (Assertion 7: 4/5 found, 1 within tolerance)

Resume file: .planning/phases/16.4-metadata-invariant-retrievability-audit/16.4-03-PLAN.md
Resume instruction: Plan 16.4-02 complete (2026-02-25). All 1,748 non-skipped indexed files have file_primary_topics. 40 Episodes re-uploaded with identity headers. Audit exits 0 with per-series breakdown. Next: Plan 16.4-03 comprehensive retrievability audit across all 1,749 files.
