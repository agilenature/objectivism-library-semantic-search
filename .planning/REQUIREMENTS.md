# Requirements: Objectivism Library Semantic Search — v2.0

**Defined:** 2026-02-19
**Milestone:** v2.0 — Gemini File Lifecycle FSM
**Core Value:** `[Unresolved file #N]` never appears in TUI search results — permanently.
**Pre-mortem source:** `governance/pre-mortem-gemini-fsm.md`

---

## Hard Constraint: AI-Enriched Metadata Is Sacred

The AI-enriched metadata (categories, difficulty, topics, aspects, semantic descriptions, entity extractions) was computed via Mistral batch API and stored in SQLite. It represents irreplaceable work that must NOT be re-derived.

**Rule:** Store migration resets ONLY Gemini-related state columns (`status`, `gemini_file_id`, `gemini_store_doc_id`, `gemini_state`). All AI metadata columns (`metadata_json`, AI metadata, entity tables) are untouched. The re-upload reads this preserved metadata directly via `build_enriched_metadata()`.

---

## v2.0 Requirements

### Store Migration (MIGR)

- [ ] **MIGR-01**: User can run a pre-flight check showing current store document count and the number of files that will lose gemini-related state, with explicit confirmation required before any irreversible action proceeds
- [ ] **MIGR-02**: Migration deletes `objectivism-library-test` and creates the permanent `objectivism-library` store as a single explicitly-confirmed operation
- [ ] **MIGR-03**: DB schema migration adds three columns to the `files` table: `gemini_store_doc_id TEXT`, `gemini_state TEXT DEFAULT 'untracked'`, `gemini_state_updated_at TEXT`
- [ ] **MIGR-04**: All files with `status = 'uploaded'` are reset to `gemini_state = 'untracked'` and `gemini_store_doc_id = NULL`; AI-enriched metadata columns are untouched

### Stability Infrastructure (STAB)

- [ ] **STAB-01**: `scripts/check_stability.py` validates 6 independent assertions: (1) count invariant — DB `indexed` count matches store document count; (2) DB→Store — no files marked indexed but absent from store; (3) Store→DB — no store documents without a DB record; (4) no stuck transitions — no files in `uploading` state; (5) search returns results — sample query returns at least one citation; (6) citation resolution — all citations returned by search resolve to DB records
- [ ] **STAB-02**: `check_stability.py` exits with code 0 (STABLE — all pass), 1 (UNSTABLE — at least one failed), or 2 (ERROR — misconfiguration such as wrong store name or missing API key)
- [ ] **STAB-03**: Passing the old store name (`objectivism-library-test`) after migration returns exit code 2 (ERROR/store not found), not 1 (UNSTABLE) — misconfiguration is distinguishable from instability
- [ ] **STAB-04**: `check_stability.py` is the mandatory gate instrument: run at T=0, T+4h, T+24h, T+36h after any upload/purge/reset-existing; wave N+1 is blocked until T+24h reports STABLE

### FSM Core (FSM)

- [ ] **FSM-01**: The chosen FSM approach (library or hand-rolled) passes affirmative concurrent-transition testing in the asyncio + aiosqlite stack — "no errors thrown" is insufficient; positive evidence of correct behavior under concurrent load is required (Wave 1 gate)
- [ ] **FSM-02**: Every identified crash point in the multi-API-call `INDEXED → UPLOADING` (reset) transition has a tested automatic recovery path; no stuck state requires manual SQL to escape (Wave 2 gate)
- [ ] **FSM-03**: `gemini_state` persists as a plain string enum (`'untracked'`, `'uploading'`, `'processing'`, `'indexed'`, `'failed'`) — never library-native serialization — stable across library version upgrades
- [ ] **FSM-04**: `AsyncUploadStateManager` write methods are FSM transition triggers; no gemini-related state mutation bypasses the FSM
- [ ] **FSM-05**: `_reset_existing_files()` calls `delete_store_document()` before `delete_file()` during reset — orphaned store documents cannot accumulate from reset operations

### Validation Waves (VLID)

- [ ] **VLID-01** (Wave 1 gate): Chosen FSM approach selected and documented with affirmative concurrent async evidence; approach committed before Wave 2 begins
- [ ] **VLID-02** (Wave 2 gate): Every crash scenario in the two-API-call reset transition tested (not designed); recovery confirmed automatic; `FAILED` state escape path designed for all failure modes
- [ ] **VLID-03** (Wave 3 gate): `display_name` confirmed caller-set via SDK source (not empirical assumption); import-to-visible lag measured (P50/P95/P99) and bounded; `PROCESSING → INDEXED` trigger strategy decided and documented
- [ ] **VLID-04** (Wave 4 gate): 50/50 test files have correct non-null `gemini_store_doc_id` after FSM-managed upload; all 50 store documents cross-verified via `list_store_documents()`
- [ ] **VLID-05** (Wave 5 gate): All query sites using legacy `status` column inventoried and mapped to `gemini_state` equivalents with no TUI/CLI/test breakage; migration window defined with explicit end date
- [ ] **VLID-06** (Wave 6 gate): FSM transition overhead measured (not estimated) under 818-file simulated batch; bottleneck identified; acceptable throughput defined with a tested mitigation
- [ ] **VLID-07** (Wave 7 gate): Import-to-searchable lag characterized empirically (P50/P95/P99); `store-sync` ongoing role explicitly defined (routine / scheduled / emergency only) and its contract relative to the FSM documented

### Pipeline Integration & Definition of Done (PIPE)

- [ ] **PIPE-01**: `[Unresolved file #N]` does not appear in any TUI search result after the full ~1,748-file upload — the sole definition of done for this milestone
- [ ] **PIPE-02**: `check_stability.py --store objectivism-library` reports STABLE (exit 0) at T=0, T+4h, T+24h, and T+36h after the full library upload

---

## v3 Requirements (deferred)

### STALE state automation

- **STALE-01**: Automated scanner detecting content hash changes and triggering `INDEXED → STALE` automatically; only implement if Wave 7 determines this is required for store-sync elimination
- **STALE-02**: `STALE` FSM state — only implement alongside STALE-01; if the scanner is deferred, drop `STALE` from the state enum entirely (dead code is worse than a missing state)

### Concurrency lock

- **CONC-01**: Lockfile (`/tmp/objlib-upload.lock`) preventing two concurrent pipeline invocations; acceptable risk at personal-use scale but Story J shows it causes double-uploads

---

## Out of Scope for v2.0

| Feature | Reason |
|---------|--------|
| Re-running AI metadata extraction | Metadata is already perfect in SQLite; re-extraction is wasted work and cost |
| Backfilling `gemini_store_doc_id` from old store | Old store is deleted; starting fresh eliminates backfill complexity (Story E eliminated by the store migration precondition) |
| `STALE` state without automated scanner | Dead code; pre-mortem Open Question 9 — drop the state if scanner is not in scope |
| Quota/billing eviction recovery (A12) | Document the risk; find API documentation confirming permanence before Wave 8 full upload |
| Non-.txt file format support | v1.0 decision stands |
| Multi-user support | Personal use only |

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| MIGR-01 | Phase 8 | Pending |
| MIGR-02 | Phase 8 | Pending |
| MIGR-03 | Phase 8 | Pending |
| MIGR-04 | Phase 8 | Pending |
| STAB-01 | Phase 8 | Pending |
| STAB-02 | Phase 8 | Pending |
| STAB-03 | Phase 8 | Pending |
| STAB-04 | Phase 8 | Pending |
| FSM-01 | Phase 9 | Pending |
| VLID-01 | Phase 9 | Pending |
| FSM-02 | Phase 10 | Pending |
| VLID-02 | Phase 10 | Pending |
| VLID-03 | Phase 11 | Pending |
| FSM-04 | Phase 12 | Pending |
| FSM-05 | Phase 12 | Pending |
| VLID-04 | Phase 12 | Pending |
| FSM-03 | Phase 13 | Pending |
| VLID-05 | Phase 13 | Pending |
| VLID-06 | Phase 14 | Pending |
| VLID-07 | Phase 15 | Pending |
| PIPE-01 | Phase 16 | Pending |
| PIPE-02 | Phase 16 | Pending |

**Coverage:**
- v2.0 requirements: 22 total
- Mapped to phases: 22
- Unmapped: 0 ✓

---

## Archive: v1.0 Requirements (Phases 1–7, all complete)

<details>
<summary>v1.0 requirements — 46 total, all shipped</summary>

FOUN-01 through FOUN-09: Foundation & State Management (Phase 1) ✓
UPLD-01 through UPLD-10: Upload Pipeline (Phase 2) ✓
SRCH-01 through SRCH-08: Semantic Search (Phase 3) ✓
INTF-01 through INTF-07: Query Interface (Phase 3) ✓
ADVN-01 through ADVN-07: Advanced Features (Phase 4) ✓
INCR-01 through INCR-05: Incremental Updates (Phase 5) ✓
META-01 through META-05: AI-Powered Metadata (Phase 6) ✓
TUI-01 through TUI-08: Interactive TUI (Phase 7) ✓ (07-07 pending)

</details>

---
*Requirements defined: 2026-02-19*
*Pre-mortem: governance/pre-mortem-gemini-fsm.md*
*Last updated: 2026-02-19 after initial v2.0 definition*
