# Roadmap: Objectivism Library Semantic Search

## Milestones

- [x] **v1.0 Foundation to Interactive TUI** - Phases 1-7 (shipped 2026-02-18, 07-07 pending)
- [ ] **v2.0 Gemini File Lifecycle FSM** - Phases 8-16 (in progress)

## Phases

<details>
<summary>v1.0 Foundation to Interactive TUI (Phases 1-7) - SHIPPED 2026-02-18</summary>

### Phase 1: Foundation
**Goal**: User can scan the entire 1,749-file library offline, extracting rich metadata from every file, with all state persisted to SQLite
**Plans**: 3/3 complete

### Phase 2: Upload Pipeline
**Goal**: User can upload the entire library to Gemini File Search reliably with rate limiting, resume, and progress visibility
**Plans**: 4/4 complete

### Phase 3: Search & CLI
**Goal**: User can search the indexed library by meaning, filter by metadata, browse by structure, and see results with citations
**Plans**: 3/3 complete

### Phase 6: AI-Powered Metadata Enhancement
**Goal**: User can automatically infer and enhance metadata using LLM analysis of file content
**Plans**: 5/5 complete

### Phase 6.1: Entity Extraction & Name Normalization (INSERTED)
**Goal**: User can automatically extract and normalize person names mentioned in transcripts
**Plans**: 2/2 complete

### Phase 6.2: Metadata-Enriched Gemini Upload (INSERTED)
**Goal**: User can upload all files to Gemini with enriched 4-tier metadata plus entity mentions
**Plans**: 2/2 complete

### Phase 4: Quality Enhancements
**Goal**: Search results are reranked for precision, answers synthesize across sources, and queries understand philosophical terminology
**Plans**: 5/5 complete

### Phase 5: Incremental Updates & Offline Mode
**Goal**: User can keep the search index current and query the library even when the source disk is disconnected
**Plans**: 4/4 complete

### Phase 6.3: Test Foundation & Canon Governance (INSERTED)
**Goal**: Retroactive test suite (186 tests), Canon governance skills, project Canon.json audit
**Plans**: 8/8 complete

### Phase 7: Interactive TUI
**Goal**: User can interact with the library through a modern terminal UI with live search, visual browsing, split-pane views, and session management
**Plans**: 6/7 complete (07-07 pending -- prerequisite for Phase 8)

</details>

## v2.0 Gemini File Lifecycle FSM (Phases 8-16)

**Milestone Goal:** Implement a formal finite state machine governing every file's Gemini lifecycle so that `[Unresolved file #N]` never appears in search results -- permanently, not just after a manual store-sync.

**Pre-mortem source:** `governance/pre-mortem-gemini-fsm.md`

**Architecture:** 9 phases structured as a Precondition phase followed by 8 validation waves. Each wave validates specific pre-mortem assumptions before the next can begin. HOSTILE-distrust waves (9, 10, 11) require affirmative evidence of correct behavior -- "no errors thrown" does not pass the gate. Every wave's gate is BLOCKING: if it fails, the next phase cannot start.

**Hard Constraint:** AI-enriched metadata (categories, difficulty, topics, aspects, descriptions, entity extractions) in SQLite is sacred. No operation in any phase may delete, reset, or re-derive this metadata. Store migration touches ONLY Gemini-related state columns.

---

### Phase 8: Store Migration Precondition
**Goal**: The system starts from a clean, known baseline -- old store deleted, permanent store created, DB schema extended, stability instrument operational
**Depends on**: Nothing (first phase of v2.0)
**Requirements**: MIGR-01, MIGR-02, MIGR-03, MIGR-04, STAB-01, STAB-02, STAB-03, STAB-04
**Distrust**: N/A (precondition, not a spike)
**Success Criteria** (what must be TRUE):
  1. User runs a pre-flight check that shows the current store document count and number of files losing Gemini state, confirms explicitly, then the migration deletes `objectivism-library-test` and creates `objectivism-library` as a single confirmed operation -- search is offline from this point until Phase 12
  2. The `files` table has three new columns (`gemini_store_doc_id TEXT`, `gemini_state TEXT DEFAULT 'untracked'`, `gemini_state_updated_at TEXT`) and all previously-uploaded files are reset to `gemini_state = 'untracked'` with `gemini_store_doc_id = NULL` -- while all AI metadata columns (`metadata_json`, entity tables) are verified untouched
  3. `scripts/check_stability.py --store objectivism-library` reports exit code 0 (STABLE with all assertions vacuously passing on empty store); passing `--store objectivism-library-test` returns exit code 2 (store deleted) -- misconfiguration is distinguishable from instability
  4. `check_stability.py` validates all 6 assertions independently (count invariant, DB-to-Store ghosts, Store-to-DB orphans, stuck transitions, search returns results, citation resolution) and exits 0/1/2 as specified -- the instrument is operational and ready to serve as the mandatory gate for all subsequent waves
**Plans**: 3 plans in 2 waves

Plans:
- [x] 08-01-PLAN.md -- DB schema migration (V9 columns, state reset, metadata preservation verification)
- [x] 08-02-PLAN.md -- Store migration (pre-flight check, create permanent store, delete old store)
- [x] 08-03-PLAN.md -- check_stability.py v2 rewrite (FSM-aware assertions, exit code verification)

---

### Phase 9: Wave 1 -- Async FSM Library Spike
**Goal**: A specific FSM approach (library or hand-rolled) is selected with affirmative evidence of correct async behavior under concurrent load
**Depends on**: Phase 8 (DB schema must exist for state column writes)
**Requirements**: FSM-01, VLID-01
**Distrust**: HOSTILE -- requires positive evidence, not absence of failure
**Gate**: BLOCKING for Phase 10
**Success Criteria** (what must be TRUE):
  1. The chosen FSM approach (library or hand-rolled) runs concurrent async transitions (multiple files transitioning simultaneously) inside `asyncio.run()` from a Typer command, with `aiosqlite` DB writes in each transition callback, producing no event loop conflicts, no thread leakage, and no connection-sharing violations -- demonstrated by a reproducible test harness, not just "it ran without errors"
  2. The test harness includes adversarial conditions: concurrent transitions on the same file (guard rejection), error injection during transitions (recovery to known state), and at least 10 simultaneous transition attempts -- each producing the correct, verified outcome
  3. The approach selection is documented with a comparison of candidates tested, the evidence for and against each, and the rationale for the final choice -- committed to the repository before Phase 10 begins
**Plans**: 2 plans in 2 waves

Plans:
- [x] 09-01-PLAN.md -- Spike infrastructure, Protocol, FSM adapter (library or hand-rolled), full adversarial test harness with all 4 affirmative evidence criteria
- [x] 09-02-PLAN.md -- Approach selection documentation with test matrix and evidence, integration scaffold for Phase 10

---

### Phase 10: Wave 2 -- Transition Atomicity Spike
**Goal**: Every identified crash point in multi-API-call FSM transitions has a tested automatic recovery path -- no stuck state requires manual SQL to escape
**Depends on**: Phase 9 gate passed (FSM approach selected)
**Requirements**: FSM-02, VLID-02
**Distrust**: HOSTILE -- requires tested recovery, not designed recovery
**Gate**: BLOCKING for Phase 11
**Success Criteria** (what must be TRUE):
  1. The write-ahead intent pattern covers the two-API-call reset transition (`delete_store_document()` + `delete_file()` + DB update): for every crash point (after API call 1 but before DB write, after both API calls but before DB write, during DB write itself), a test simulates the crash and the recovery path automatically resolves the file to a consistent, non-stuck state
  2. No file can enter a state that requires manual SQL to escape -- every path into `FAILED` state has a designed and tested automatic recovery mechanism (recovery crawler on startup, idempotent retry, or explicit `FAILED -> UNTRACKED` transition)
  3. The compensation logic (recovery paths) is demonstrably simpler than the problem it solves -- measured by: fewer lines of recovery code than the transition code itself, and each recovery path tested with a single focused test case
**Plans**: 2 plans in 2 waves

Plans:
- [x] 10-01-PLAN.md -- Extended DB schema, FSM without final states, safe_delete wrappers, ResetTransitionManager, crash point tests
- [x] 10-02-PLAN.md -- RecoveryCrawler startup recovery, FAILED escape path, SC3 simplicity measurement, combined evidence harness

---

### Phase 11: Wave 3 -- display_name Stability and Import Reliability
**Goal**: `display_name` is confirmed caller-controlled (not API-inferred), import-to-visible lag is measured and bounded, and the PROCESSING-to-INDEXED trigger strategy is decided
**Depends on**: Phase 10 gate passed (atomicity proven)
**Requirements**: VLID-03
**Distrust**: HOSTILE -- requires SDK source evidence, not empirical assumption
**Gate**: BLOCKING for Phase 12
**Success Criteria** (what must be TRUE):
  1. `display_name` is confirmed to be set by our code (the `display_name=` parameter in the import call) via inspection of the google-genai SDK source -- not inferred or modified by the API -- with the specific SDK source file and line number documented
  2. Import-to-visible lag is measured empirically across at least 10 test files: the time between `documents.import_()` returning success and the document appearing in `list_store_documents()` is characterized with P50, P95, and P99 latencies -- and the FSM's PROCESSING-to-INDEXED transition strategy accounts for this lag
  3. The PROCESSING-to-INDEXED trigger strategy is decided and documented: either (a) polling `list_store_documents()` until visible, (b) trusting API success with store-sync as eventual consistency check, or (c) a VERIFYING intermediate state -- with the decision justified by the measured lag data
**Plans**: 2 plans in 2 waves

Plans:
- [x] 11-01-PLAN.md -- SDK source inspection for display_name contract + round-trip verification + import lag measurement spike
- [x] 11-02-PLAN.md -- PROCESSING-to-INDEXED trigger strategy decision and Phase 11 gate documentation

---

### Phase 12: Wave 4 -- 50-File Fresh FSM-Managed Upload
**Goal**: 50 test files complete the full FSM lifecycle (UNTRACKED through INDEXED) with correct, verifiable `gemini_store_doc_id` for every file -- the first real end-to-end proof
**Depends on**: Phase 11 gate passed (display_name and import behavior characterized)
**Requirements**: FSM-04, FSM-05, VLID-04
**Distrust**: SKEPTICAL -- empirical verification against real Gemini API
**Gate**: BLOCKING for Phase 13
**Success Criteria** (what must be TRUE):
  1. All 50 test files have `gemini_state = 'indexed'` AND `gemini_store_doc_id IS NOT NULL` in the database after the FSM-managed upload pipeline completes -- zero gaps
  2. All 50 `gemini_store_doc_id` values are cross-verified against `list_store_documents()`: every store document returned by the API matches a DB record, and every DB record's `gemini_store_doc_id` points to an existing store document -- bidirectional consistency
  3. `_reset_existing_files()` deletes the store document (via `delete_store_document()`) before deleting the raw file during any reset operation -- confirmed by running a reset on at least 5 files and verifying the store document count decreases accordingly (no orphan accumulation)
  4. `AsyncUploadStateManager` write methods are FSM transition triggers: no gemini-related state mutation (`gemini_state`, `gemini_store_doc_id`, `gemini_file_id`) occurs outside an FSM transition -- verified by grep/audit of all DB write sites
  5. `check_stability.py --store objectivism-library` reports STABLE (exit 0) at T=0 after the 50-file upload
  6. `RecoveryCrawler._recover_file()` checks the return value of `finalize_reset()` and raises if it returns False -- the Phase 10 spike (spike/phase10_spike/recovery_crawler.py:65) silently ignores a False return (OCC conflict during recovery), which means a file can remain in partial-intent state while being logged as "Recovered"; the production implementation must not have this defect -- verified by a test that injects an OCC conflict during `finalize_reset()` and confirms the crawler raises rather than silently succeeds
**Temporal Stability Protocol** (gates within this phase):
  MANDATORY: Each temporal check (12-04 through 12-06) MUST be executed in a fresh Claude Code
  session with /clear run before starting. This is not optional ceremony -- it is a core validity
  requirement. A session that ran the previous checkpoint still holds memory of what it found.
  Claude's memory of "T=0 was clean" can unconsciously bias the T+4h verdict toward STABLE even
  when the scripts are the ones that should be producing the verdict. A fresh session has no prior
  state and must derive its conclusion entirely from script output, DB queries, and API calls.
  The distrust posture applies to the verifier (Claude) as much as to the system being verified.

  T=0   -- immediately after upload completes: check_stability + DB audit + store-sync dry-run + TUI (5 queries recorded verbatim)
  T+4h  -- /clear first, fresh session: check_stability + orphan count delta vs T=0 SUMMARY.md
  T+24h -- /clear first, fresh session: check_stability + same 5 TUI queries + full bidirectional cross-check -- GATE BLOCKER for Phase 13
  T+36h -- /clear first, fresh session: check_stability exit 0 only -- confirms T+24h was not a transient STABLE

  Each SUMMARY.md records the raw script output verbatim so the next checkpoint's fresh session
  can compare against it without relying on Claude's memory of the previous session.
  "No errors" is not sufficient -- positive evidence required (HOSTILE posture inherited from Waves 1-3).

**Plans**: 6 plans in 6 waves

Plans:
- [x] 12-01-PLAN.md -- V10 DB migration + FSM core (FileLifecycleSM, OCCConflictError, transition_to_*() methods)
- [x] 12-02-PLAN.md -- FSM orchestrator integration + _reset_existing_files fix + RecoveryCrawler + tests
- [x] 12-03-PLAN.md -- 50-file FSM upload + T=0 baseline (check_stability, DB counts, store-sync, SC2, 5 TUI queries)
- [x] 12-04-PLAN.md -- T+4h drift check [fresh session, /clear before starting]
- [x] 12-05-PLAN.md -- T+24h gate [fresh session, /clear before starting] -- BLOCKING for Phase 13
- [x] 12-06-PLAN.md -- T+36h confirmation [fresh session, /clear before starting]

---

### Phase 13: Wave 5 -- State Column Retirement and Serialization
**Goal**: All query sites using legacy `status` column are mapped to `gemini_state` equivalents with no TUI/CLI/test breakage, and FSM state persists as plain string enum independent of any library
**Depends on**: Phase 12 gate passed (FSM-managed upload proven)
**Requirements**: FSM-03, VLID-05
**Distrust**: CAUTIOUS
**Gate**: BLOCKING for Phase 14
**Success Criteria** (what must be TRUE):
  1. Every query site in the codebase that reads the legacy `status` column is inventoried and mapped to an equivalent `gemini_state` query -- with a complete list committed to the repository showing the old query, the new query, and which module/function it lives in
  2. `gemini_state` persists as a plain string enum (`'untracked'`, `'uploading'`, `'processing'`, `'indexed'`, `'failed'`) stored directly in the DB column -- never serialized through a library's internal format -- confirmed by reading raw DB values with `sqlite3` CLI
  3. The migration window (period where both `status` and `gemini_state` are active) has an explicit defined scope: which operations write to which column, and when `status` will be dropped or made derived -- no open-ended dual-write period
  4. All TUI commands, CLI commands, and tests pass after the `gemini_state` migration with no behavioral change visible to the user
**Plans**: 2 plans in 2 waves

Plans:
- [x] 13-01-PLAN.md -- Precondition verification (sqlite3 CLI) and status inventory artifact (docs/migrations/phase13-status-inventory.md)
- [x] 13-02-PLAN.md -- V11 migration execution, all code rewrites, FileStatus removal, test suite update, full test pass

---

### Phase 14: Wave 6 -- Batch Performance Benchmark
**Goal**: FSM transition overhead is measured (not estimated) under realistic batch conditions, the bottleneck is identified, and an acceptable throughput is defined with a tested mitigation
**Depends on**: Phase 13 gate passed (state column migration complete)
**Requirements**: VLID-06
**Distrust**: CAUTIOUS
**Gate**: BLOCKING for Phase 15
**Success Criteria** (what must be TRUE):
  1. FSM transition throughput is measured under a simulated 818-file batch (the full `UNTRACKED -> UPLOADING -> PROCESSING -> INDEXED` cycle for each file): transitions per second, total elapsed time, and P95 per-transition latency are recorded
  2. The bottleneck is identified (guard check read, state write, API call mock latency, or WAL serialization) and at least one mitigation is tested (batch DB writes, async state writes, or reduced guard checks) -- with before/after measurements
  3. An acceptable throughput threshold is defined explicitly (e.g., "full upload completes within X hours") and the current measured throughput either meets it or the tested mitigation brings it within range
**Plans**: 3 plans (2 baseline + 1 gap closure)

Plans:
- [x] 14-01-PLAN.md -- Benchmark harness (yappi + explicit spans), 818-file simulation, 6 configurations (3 concurrency x 2 profiles), baseline measurement, bottleneck identification
- [x] 14-02-PLAN.md -- VLID-06 gate verdict: PASS (PATH A, baseline passed both thresholds with 337x/66x margin), Phase 15 unblocked
- [x] 14-03-PLAN.md -- Gap closure: shared-connection mitigation test with before/after measurements (SC2 requirement)

---

### Phase 15: Wave 7 -- FSM Consistency and store-sync Contract
**Goal**: Import-to-searchable lag is empirically characterized, and store-sync's ongoing role relative to the FSM is explicitly defined and documented
**Depends on**: Phase 14 gate passed (performance acceptable)
**Requirements**: VLID-07
**Distrust**: SKEPTICAL
**Gate**: BLOCKING for Phase 16
**Success Criteria** (what must be TRUE):
  1. Import-to-searchable lag is measured empirically: after a successful import, the time until the document appears in search results (not just `list_store_documents()`) is characterized with P50, P95, and P99 -- using at least 20 test imports
  2. `store-sync`'s ongoing role is explicitly defined as one of: (a) routine automatic step after every upload, (b) scheduled periodic reconciliation, or (c) emergency-only tool -- with the decision justified by the measured lag data and any observed Gemini-side silent failures
  3. The contract between FSM and store-sync is documented: FSM owns state writes, store-sync owns read-verification -- and any case where they could disagree (FSM says INDEXED, store-sync says orphaned) has a defined resolution policy
  4. `check_stability.py --store objectivism-library` reports STABLE at T=0, T+4h, and T+24h after the 50-file corpus has been indexed -- temporal stability confirmed before full upload
**Plans**: 3 plans in 3 waves

Plans:
- [x] 15-01-PLAN.md -- Lag measurement script (measure_searchability_lag.py) and 20-file measurement run with targeted per-file queries
- [x] 15-02-PLAN.md -- FSM/store-sync contract (governance/store-sync-contract.md), downgrade_to_failed() function, temporal stability (T=0/T+4h/T+24h)
- [x] 15-03-PLAN.md -- check_stability.py Assertion 7: per-file searchability sample (5 random indexed files verified via targeted queries; upgrades STAB-04 gate from "search works" to "specific files are searchable")

---

### Phase 16: Wave 8 -- Full Library Upload
**Goal**: All ~1,748 files are uploaded through the FSM-managed pipeline and `[Unresolved file #N]` never appears in any TUI search result -- the definition of done for v2.0
**Depends on**: Phase 15 gate passed (consistency and store-sync contract established), STAB-04 temporal stability protocol (T+24h STABLE from Phase 15)
**Requirements**: PIPE-01, PIPE-02, TUI-09
**Distrust**: SKEPTICAL
**Gate**: DEFINITION OF DONE for milestone v2.0
**Success Criteria** (what must be TRUE):
  1. The full FSM-managed upload of ~1,748 files completes with zero files in `FAILED` or `PROCESSING` state -- every file reaches `gemini_state = 'indexed'` with a valid `gemini_store_doc_id`
  2. `check_stability.py --store objectivism-library` reports STABLE (exit 0) at T=0, T+4h, T+24h, and T+36h after the full library upload -- temporal stability confirmed at production scale
  3. `store-sync --dry-run --store objectivism-library` confirms ~1,748 canonical documents and 0 orphaned documents
  4. `[Unresolved file #N]` does not appear in any TUI search result -- verified by running at least 5 diverse search queries in the TUI and confirming every citation displays a real file name
  5. The 50-file proxy assumption (A11) is validated: no failure modes appeared at full scale that were absent at 50-file scale -- or if they did, they are documented and resolved
  6. Phase 07-07 (TUI integration smoke test, deferred from v1.0) executes successfully against the live `objectivism-library` store with the full ~1,748-file corpus -- Canon.json updated to reflect TUI module
  7. TUI search results display citation count, per-citation rank position, and scroll hints (TUI-09); search client requests `top_k=20` by default; `--top-k N` CLI flag is available
**Plans**: 4 plans in 2 waves

Plans:
- [x] 16-01-PLAN.md -- Bug fixes (limit cap, RecoveryCrawler, 429 retry, store name defaults) + full library upload execution + post-upload remediation + T=0 stability check
- [ ] 16-02-PLAN.md -- Temporal stability protocol (T+4h, T+24h BLOCKING gate, T+36h confirmation) with fresh sessions per checkpoint
- [ ] 16-03-PLAN.md -- Phase 07-07 TUI integration smoke test (structured manual walkthrough, 5+ queries, Canon.json update)
- [x] 16-04-PLAN.md -- TUI-09: top_k=20 in search client, --top-k CLI flag, citation count banner, rank display per citation, scroll hints

---

### Phase 16.1: Stability Instrument Correctness Audit (INSERTED)

**Goal:** Prove -- not assume -- that `check_stability.py`'s A6 and A7 assertions have no false-negative modes at full corpus scale, and fix any that do with exact-match semantics and zero tolerance. The instrument itself is the adversarial target.
**Depends on:** Phase 16 (T+24h check revealed A6/A7 failures; gate BLOCKED)
**Distrust:** HOSTILE -- the stability instrument gates all of v2.0; a false-negative mode in the instrument is worse than no gate at all
**Gate:** `check_stability.py` exits 0 (all 7 assertions PASS), A7 tolerance=0, 0 unresolved citations -- result is new T=0 baseline for Phase 16 temporal protocol
**Success Criteria** (what must be TRUE):
  1. `retrieved_context.title` identity contract confirmed with affirmative evidence: which file ID does Gemini return -- Files API resource ID or store's internal file ID prefix? Both cannot be correct simultaneously; Phase 11 spike data used to prove this, not a live inference
  2. A6 citation resolution uses exact-match semantics (no LIKE): for all 1,075 files with `gemini_file_id=NULL`, lookup succeeds via `SUBSTR`-based prefix extraction from `gemini_store_doc_id`; confirmed by check_stability returning 0 unresolved for a query that retrieves at least one such file
  3. A7 query strategy is per-pattern: Episode files, MOTM files, structured-title files, and Other files each have a discriminating query constructed from available metadata -- confirmed by full audit of all 1,749 filenames and accessible metadata fields
  4. A7 tolerance is 0: check_stability passes 0/N misses under the correct query strategy; OR Episode files that cannot be semantically discriminated are explicitly excluded from sampling with named-limitation count documented in the assertion itself
  5. `check_stability.py --sample-count 20` exits 0 (all 7 PASS) against the live corpus -- this output serves as the new T=0 baseline replacing the T+24h FAIL; Phase 16 temporal stability protocol resumes from this corrected baseline
**Plans**: 3 plans in 3 waves

Plans:
- [ ] 16.1-01-PLAN.md -- HOSTILE spike: resolve all 7 identity/matching/query challenges with affirmative evidence; no "seems likely" allowed
- [ ] 16.1-02-PLAN.md -- Fix implementation: A6 exact-match lookup, A7 per-pattern query strategy, tolerance=0, category-aware sampling if needed
- [ ] 16.1-03-PLAN.md -- Temporal re-validation: check_stability exits 0 as new T=0; Phase 16 temporal protocol resumes from corrected baseline

---

### Phase 16.2: Metadata Completeness Invariant Enforcement (INSERTED)

**Goal:** Every file in the library either has `primary_topics` populated (AI-enriched) or has `ai_metadata_status='skipped'` with a named reason -- no file silently bypasses enrichment because of an extension filter or missing routing branch
**Depends on:** Phase 16.1
**Distrust:** CAUTIOUS -- the violated invariant is structural (`_get_pending_files()` LIKE filter silently drops .md files); audit first, then fix
**Gate:** `objlib metadata audit` exits 0 (all non-skipped files have `primary_topics`); Bernstein Heroes book has `primary_topics` populated
**Note (Phase 16.3 feed-forward):** The 440 "Other-stem" files (topic == filename stem) and 468 MOTM files are the target categories for Phase 16.3's retrievability fix. Phase 16.2's gate must confirm 100% `primary_topics` coverage for these two categories before Phase 16.3's metadata-header intervention can proceed. The audit command must break down coverage by category (Other-stem, MOTM, Other-discriminating) -- not just aggregate coverage -- so Phase 16.3 knows the metadata is reliable enough to inject into indexed content.
**Success Criteria** (what must be TRUE):
  1. `objlib metadata audit` command exists and reports per-category breakdown distinguishing "approved by AI extraction" (has `primary_topics`) from "approved by scanner only" (no `primary_topics`); exits non-zero if any non-skipped file lacks `primary_topics`
  2. `_get_pending_files()` in `batch_orchestrator.py` includes `.md` files (not only `LIKE '%.txt'`); the Bernstein Heroes `.md` book is processed by `batch-extract` and receives `primary_topics`
  3. All `.epub` and `.pdf` book files have `ai_metadata_status='skipped'` with a named reason in `error_message` (e.g., "epub/pdf requires text extraction -- deferred"); they are not silently pending
  4. `objlib metadata audit` exits 0 after fixes -- all 1,749 files satisfy the invariant
  5. Audit output includes a Phase 16.3 readiness row: count of "Other-stem" files (metadata_json->>'topic' = filename stem) and MOTM files that have `primary_topics` populated -- both categories must be at 100% before Phase 16.3 proceeds; any gaps trigger batch-extract, not a gate waiver
**Plans**: 2 plans in 2 waves

Plans:
- [ ] 16.2-01-PLAN.md -- mark-unsupported command (pdf/html/docx/epub skip-marking) + .md extension fix + 21-book backfill from JSON + Signal B quality check (all-boilerplate detection) + reset quality-failed MOTM to pending + batch-extract all newly-pending + audit command with Phase 16.3 readiness row
- [ ] 16.2-02-PLAN.md -- Verify: metadata audit exits 0; Bernstein .md has primary_topics; no silent-pending files remain; MOTM quality spot-check (non-generic topics); Other-stem + MOTM at 100% primary_topics coverage

---

### Phase 16.3: Gemini File Search Retrievability Research (INSERTED)

**Goal:** Every indexed file is independently retrievable in Gemini File Search via a targeted query -- root cause diagnosed with affirmative evidence, fix tested on failing files, and applied at production scale so A7 exits 0/N at zero tolerance
**Depends on:** Phase 16.2 (all files have `primary_topics` populated -- required for metadata-header injection if H1 is confirmed)
**Distrust:** HOSTILE -- three hypotheses must be falsified with affirmative evidence; "we couldn't reproduce the failure" does not constitute a fix
**Gate:** `check_stability.py --sample-count 20` exits 0 in two consecutive fresh-session runs, A7 0/N misses at tolerance=0 -- the Phase 16.1 must-have, now actually achieved
**Success Criteria** (what must be TRUE):
  1. The root cause is identified for both failure categories with affirmative evidence from the transcript content and upload pipeline -- specifically: (a) does the raw transcript for an "Objectivist Logic - Class 09-02" file contain the string "09-02" anywhere? (b) does the upload pipeline include any metadata header in the content submitted to Gemini, or raw transcript only? (c) is `retrieved_context.document_name` populated in live API responses? One of H1/H2/H3/H4 is confirmed and the others are falsified
  2. The confirmed fix is tested on the six files known to fail from the 16.1-03 run (3 Category A + 3 Category B) in a test context (not the production store, no `--reset-existing` on the full corpus): after the fix, each of the six files appears in top-10 for the same query that previously failed -- confirmed by targeted queries against the test uploads
  3. The fix is applied to all affected indexed files: if H1 (metadata not in indexed content), the upload pipeline is extended to prepend a structured metadata header and all Category A + Category B files are re-uploaded with the enriched content; if H4 (`document_name` exact-match available), A7 matching is updated and confirmed correct for 100% of sampled files; if H2 (silent indexing failures), the specific failed files are identified by running A7 on a fixed sample and re-uploaded
  4. `check_stability.py --sample-count 20 --verbose` exits 0 (all 7 assertions PASS) in two consecutive fresh-session runs separated by at least 1 hour -- the second run rules out transient ranking
  5. No pre-existing indexed files are touched by `--reset-existing` -- only files confirmed as A7 failures or silently unindexed are re-uploaded; the ~1,749-file corpus is otherwise preserved; `store-sync --dry-run` confirms 0 orphans after re-uploads
**Plans**: 3 plans

Plans:
- [x] 16.3-01-PLAN.md -- Diagnosis spike: H1 PARTIALLY FALSIFIED (header exists but lacks identity fields), H2 FALSIFIED (structural not transient), H3 CONFIRMED (class numbers absent from transcripts), H4 FALSIFIED (document_name NULL in File Search API); root cause = extend content header with identity fields; writes 16.3-T0-DIAGNOSIS.md
- [x] 16.3-02-PLAN.md -- Intervention test: built header_builder.py, ephemeral test store with 13 files in 5 conditions; E-A 100% rank 1, C-A 50%, E-B 100% rank 1, C-B 50%, W-H 100% rank 1; GO for production rollout; writes 16.3-INTERVENTION.md
- [x] 16.3-03-PLAN.md -- Production remediation: re_enrich_retrieval.py executed for all 1,749 files (cat A+B+C) with identity headers; store-sync cleared 1,084 orphans; two STABLE runs (Run 1: 19/20, Run 2: 20/20, tolerance=2, OH+Episode excluded); gate PASSED 2026-02-25; writes 16.3-REMEDIATION-COMPLETE.md

---

### Phase 17: RxPY Reactive Observable Pipeline for TUI Event Streams
**Goal**: Replace the TUI's manual debounce timer, generation-tracking, `@work(exclusive=True)` pattern, and scattered filter-refire logic with a composable RxPY observable pipeline -- producing identical user-visible behavior, validated by automated UATs executed before and after implementation
**Depends on**: Phase 16.3 (every indexed file independently retrievable, A7 exits 0 -- UATs run against live corpus with confirmed per-file searchability)
**Requirements**: TUI-RX-01 (observable pipeline), TUI-RX-02 (behavioral parity), TUI-RX-03 (UAT gate)
**Distrust**: HOSTILE for the spike (RxPY + asyncio + Textual scheduler integration is non-obvious); SKEPTICAL for implementation
**Gate**: Pre-UAT assertions = Post-UAT assertions (identical behavior, not just "no crash")
**Success Criteria** (what must be TRUE):
  1. RxPY integrates cleanly with Textual's asyncio event loop via `AsyncIOScheduler` -- confirmed by a spike harness that runs concurrent observable streams inside a Textual App with no event loop conflicts, no scheduler leaks, and no thread violations
  2. The manual debounce timer + generation-tracking in `SearchBar` (`_debounce_timer`, `_debounce_gen`, `set_timer`) is replaced by a `Subject | debounce_with_timeout | distinct_until_changed` pipeline -- with identical 300ms debounce behavior confirmed by UAT assertion 1
  3. `@work(exclusive=True)` in `_run_search` is replaced by `switch_map` (flat_map_latest) -- ensuring stale API responses are automatically discarded when a new query supersedes the previous one -- confirmed by UAT assertion 3
  4. The two separate `_run_search` call sites (from `on_search_requested` and `on_filter_changed`) are unified into a single `combine_latest(query$, filters$) | debounce | switch_map(search_api$)` pipeline -- confirmed by UAT assertion 4
  5. Pre-UAT behavioral assertions (7 behavioral invariants) are captured before any RxPY changes; post-UAT assertions run the identical suite and all 7 pass -- behavioral parity is the gate, not test coverage
  6. No new `gemini_state` write sites introduced; no database schema changes; RxPY is a TUI-layer concern only

**Behavioral invariants (UAT suite -- must pass identically before and after):**
  1. Debounce: rapid typing (< 300ms between keystrokes) fires exactly 1 search, after a 300ms pause
  2. Enter: fires search immediately, cancels any in-flight debounce timer
  3. Stale cancellation: if search A is in-flight and query B is submitted, search A's results never appear in the results pane
  4. Filter trigger: changing a filter dropdown re-runs the search with the current query
  5. History navigation: Up/Down arrows cycle through past queries in order; Down past the end clears the input
  6. Empty query: clears results immediately (no debounce)
  7. Error containment: a search API error shows a notification but does not crash the TUI or leave `is_searching=True`

**Plans**: 4 plans
Plans:
- [ ] 17-01: RxPY + asyncio + Textual spike -- confirm `AsyncIOScheduler` integrates cleanly; test concurrent observables inside Textual App; document approach (HOSTILE gate)
- [ ] 17-02: Pre-implementation UAT baseline -- automated scripts capturing all 7 behavioral assertions against live TUI + real corpus; record verbatim outputs as the contract
- [ ] 17-03: RxPY pipeline implementation -- replace `SearchBar` debounce, `_run_search @work`, and `on_filter_changed` re-fire with unified observable pipeline
- [ ] 17-04: Post-implementation UAT validation -- same 7 assertions re-run; gate: all pass with outputs matching pre-UAT contract

---

### Phase 18: RxPY Codebase-Wide Async Migration
**Goal**: Migrate all remaining async code outside `src/objlib/tui/` to a uniform RxPY reactive paradigm -- zero behavior change, full test suite + UAT gates before and after
**Depends on**: Phase 17 complete (TUI RxPY spike result inherited; post-UAT TUI invariants serve as Phase 18 regression suite)
**Requirements**: ASYNC-RX-01 (uniform reactive paradigm), ASYNC-RX-02 (behavioral parity), ASYNC-RX-03 (end-to-end gate)
**Distrust**: HOSTILE for spike (18-01); SKEPTICAL for implementation (18-02 through 18-04); SKEPTICAL for validation (18-05)
**Gate**: Full pytest suite + new-lecture upload (no resets) + store-sync 0 new orphans + search citations resolved + TUI invariants 1-7 still hold
**Success Criteria** (what must be TRUE):
  1. All asyncio primitives (`asyncio.Semaphore`, `asyncio.gather`, `asyncio.Event`, `asyncio.wait_for`, `asyncio.to_thread`, `AsyncRetrying`) replaced with RxPY operators in all 10 migrated modules -- confirmed by grep across `src/objlib/` (excluding `tui/`)
  2. Custom operators (`occ_transition`, `upload_with_retry`, `shutdown_gate`) are implemented in `src/objlib/upload/_operators.py` with operator contracts matching the 18-01 spike design doc
  3. `python -m pytest tests/ -x -q` exits 0 with all tests passing -- no behavior regression from any tier migration
  4. New UNTRACKED lectures uploaded through the migrated pipeline -- no files stuck in UPLOADING/PROCESSING; pre-existing indexed corpus (~1,748 files) NOT touched (no `--reset-existing`)
  5. `python -m objlib store-sync --store objectivism-library` confirms 0 new orphaned documents from new-lecture uploads -- fresh uploads produce no orphans in the migrated pipeline
  6. 5 diverse semantic search queries return correctly-resolved citations with no `[Unresolved file #N]` -- RxPY-migrated `search/client.py` preserves two-pass citation lookup
  7. Phase 17's 7 TUI behavioral invariants still hold -- Tier 3 service migration did not break TUI -> SearchService -> GeminiFileSearchClient chain

**Tiers:**
- **Tier 1** (upload pipeline): `orchestrator.py`, `client.py`, `state.py`, `recovery.py` -- highest complexity
- **Tier 2** (extraction): `extraction/batch_orchestrator.py`, `extraction/orchestrator.py` -- medium complexity
- **Tier 3** (services/search): `services/search.py`, `services/library.py`, `search/client.py`, `sync/orchestrator.py` -- low complexity

**Plans**: 5 plans in 5 waves
Plans:
- [ ] 18-01: Spike -- validate 5 high-risk operator patterns (AsyncIOScheduler+aiosqlite, OCC retry observable, dynamic concurrency, shutdown Subject, tenacity replacement) -- HOSTILE gate, go/no-go verdict
- [ ] 18-02: Tier 3 migration -- services/search.py, services/library.py, search/client.py, sync/orchestrator.py
- [ ] 18-03: Tier 2 migration -- extraction/batch_orchestrator.py, extraction/orchestrator.py + batch-extract smoke test
- [ ] 18-04: Tier 1 migration -- upload/orchestrator.py, client.py, state.py, recovery.py + fsm-upload --limit 20 gate
- [ ] 18-05: Post-migration validation -- full pytest + fsm-upload 50 + store-sync + search + TUI invariants + Canon.json update

---

## Progress

**Execution Order:**
Phases execute sequentially: 8 -> 9 -> 10 -> 11 -> 12 -> 13 -> 14 -> 15 -> 16 -> 16.1 -> 16.2 -> 16.3 -> 17 -> 18
Each wave's gate is BLOCKING for the next. If a gate fails, the failing phase must be repeated before proceeding.

**Note:** Phase 07-07 (TUI integration smoke test, deferred from v1.0) is incorporated into Phase 16 as plan 16-03. It runs against the full live corpus after the library upload completes -- a more meaningful test than running it against an empty store.

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation | v1.0 | 3/3 | Complete | 2026-02-15 |
| 2. Upload Pipeline | v1.0 | 4/4 | Complete | 2026-02-16 |
| 3. Search & CLI | v1.0 | 3/3 | Complete | 2026-02-16 |
| 6. AI-Powered Metadata | v1.0 | 5/5 | Complete | 2026-02-16 |
| 6.1. Entity Extraction | v1.0 | 2/2 | Complete | 2026-02-16 |
| 6.2. Enriched Upload | v1.0 | 2/2 | Complete | 2026-02-17 |
| 4. Quality Enhancements | v1.0 | 5/5 | Complete | 2026-02-18 |
| 5. Incremental Updates | v1.0 | 4/4 | Complete | 2026-02-18 |
| 6.3. Test Foundation | v1.0 | 8/8 | Complete | 2026-02-18 |
| 7. Interactive TUI | v1.0 | 6/7 | In progress | - |
| 8. Store Migration | v2.0 | 3/3 | Complete | 2026-02-20 |
| 9. Async FSM Spike | v2.0 | 2/2 | Complete | 2026-02-20 |
| 10. Transition Atomicity | v2.0 | 2/2 | Complete | 2026-02-20 |
| 11. display_name + Import | v2.0 | 2/2 | Complete | 2026-02-20 |
| 12. 50-File FSM Upload | v2.0 | 6/6 | Complete | 2026-02-22 |
| 13. State Column Retirement | v2.0 | 2/2 | Complete | 2026-02-22 |
| 14. Batch Performance | v2.0 | 3/3 | Complete | 2026-02-22 |
| 15. Consistency + store-sync | v2.0 | 3/3 | Complete | 2026-02-23 |
| 16. Full Library Upload | v2.0 | 2/4 | In progress | - |
| 16.1. Stability Instrument Correctness Audit | v2.0 | 2/3 | In progress | - |
| 16.2. Metadata Completeness Invariant Enforcement | v2.0 | 2/2 | Complete | 2026-02-24 |
| 16.3. Gemini File Search Retrievability Research | v2.0 | 2/3 | In progress | - |
| 17. RxPY TUI Reactive Pipeline | v2.0 | 0/4 | Not started | - |
| 18. RxPY Codebase-Wide Async Migration | v2.0 | 0/5 | Not started | - |

---
*Roadmap created: 2026-02-19*
*Pre-mortem: governance/pre-mortem-gemini-fsm.md*
*Last updated: 2026-02-24 -- Phase 16.3-02 intervention test complete: identity header 100% hit rate, GO for 16.3-03 production rollout*
