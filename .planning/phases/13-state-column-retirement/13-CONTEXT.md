# CONTEXT.md — Phase 13: State Column Retirement

**Generated:** 2026-02-22
**Phase Goal:** Wave 5 — State Column Retirement and Serialization: All query sites using legacy `status` column are mapped to `gemini_state` equivalents with no TUI/CLI/test breakage, and FSM state persists as plain string enum independent of any library.
**Synthesis Source:** Multi-provider AI analysis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research)

---

## Overview

Phase 13 retires the legacy `status` column that was introduced in v1.0 and kept alongside `gemini_state` after the Phase 8 store migration. The FSM has been the sole write path for `gemini_state` since Phase 12 completed. This phase closes the migration window by: (1) inventorying every code site still reading `status`, (2) migrating those reads to `gemini_state`, and (3) dropping or freezing `status` on an explicit schedule.

Key project-specific facts that constrain decisions:
- Phase 8 already reset ALL files to `gemini_state = 'untracked'` (no NULLs in that column)
- Phase 12 FSM pipeline moved 50 files to `gemini_state = 'indexed'`
- No files are in transient states (`uploading`, `processing`) — Phase 12 is fully complete
- `gemini_state` has been the sole FSM write target since Phase 8 — `status` is already stale
- The FSM stores state via explicit `str()` conversion at write boundary (already verified in Phases 10-12)

**Confidence markers:**
- ✅ **Consensus** — All 3 providers identified this as critical
- ⚠️ **Recommended** — 2 providers identified this as important
- 🔍 **Noted** — 1 provider flagged, but lower priority given project context

---

## Gray Areas Identified

### ✅ 1. Legacy `status` Value Mapping (Consensus)

**What needs to be decided:**
The complete, explicit mapping from every legacy `status` value that exists in the live DB to one of the 5 `gemini_state` values (`untracked`, `uploading`, `processing`, `indexed`, `failed`).

**Why it's ambiguous:**
The requirements say "inventoried and mapped" but don't specify the actual legacy values or the mapping. The mapping determines what the `13-01` audit script must output.

**Provider synthesis:**
- **OpenAI:** Define `legacy_status_mapping` dict; catch-all unknown → `untracked` with warning; make this a CI-testable artifact
- **Gemini:** Likely values: `uploaded`→`indexed`, `pending`→`untracked`, `unknown`→`untracked`; caution on transient states mapping to `untracked` (not `uploading`/`processing`)
- **Perplexity:** Make mapping bidirectional and explicit; document in version-controlled file; handle NULL → `untracked`

**Proposed implementation decision:**
Run `SELECT DISTINCT status FROM files` on the live DB first. Expected values from v1 upload pipeline: `'uploaded'`, `'pending'`, potentially `'failed'`, `'skipped'`. Map: `uploaded`→`indexed`, `pending`→`untracked`, `failed`→`failed`, `skipped`→`untracked`, `NULL`→`untracked`. Commit mapping dict to `src/objlib/migration/status_mapping.py` (or inline in the migration script).

**Open questions:**
- What `DISTINCT status` values actually exist in the live DB right now?
- Are any files in `status = 'uploaded'` that should map to `untracked` (not `indexed`) because the Phase 8 migration already cleared their Gemini state?

**Confidence:** ✅ All 3 providers flagged as blocking prerequisite

---

### ✅ 2. Backfill Strategy (Consensus — but simplified by project state)

**What needs to be decided:**
Whether a backfill is needed at all, given that Phase 8 already populated `gemini_state` for all files.

**Why it's ambiguous:**
All 3 providers assumed `gemini_state` may have NULLs for the ~1,698 non-Phase-12 files. In this project, Phase 8's V9 migration set ALL files to `gemini_state = 'untracked'`. So the backfill question becomes: verify there are zero NULLs, not populate them.

**Provider synthesis:**
- **OpenAI:** Run explicit backfill; add NOT NULL constraint after; keep idempotent CLI command
- **Gemini:** Mass-update non-Phase-12 files before switching read queries
- **Perplexity:** Backfill + checksum validation before dropping legacy column

**Proposed implementation decision:**
No backfill needed — Phase 8 already populated `gemini_state` for all rows. The `13-01` audit plan should verify `SELECT COUNT(*) FROM files WHERE gemini_state IS NULL` returns 0 as a precondition. If any NULLs exist, set them to `untracked`. A `NOT NULL` constraint check is useful but SQLite requires table rewrite to add it retrospectively — document the invariant in code instead.

**Confidence:** ✅ Consensus that this must be verified; simplified by project state

---

### ✅ 3. Migration Window Scope and End Date (Consensus)

**What needs to be decided:**
Which operations write to which column during the window, and exactly when `status` is dropped or frozen.

**Why it's ambiguous:**
SC-3 requires an "explicit defined scope" with no "open-ended dual-write period." But `status` may still be read by CLI/TUI/tests, creating implicit pressure to keep writing it.

**Provider synthesis:**
- **OpenAI:** Single-write to `gemini_state` immediately; `status` becomes read-only/legacy at start of Phase 13; hard drop date within 30 days
- **Gemini:** "Soft Deprecation" — make `status` a Python property computed from `gemini_state` for one phase; physical `DROP COLUMN` in the next phase
- **Perplexity:** Expand-Migrate-Contract pattern; explicit deadline enforced programmatically; remove dual-write code first, then schema drop

**Proposed implementation decision:**
The FSM has been the sole `gemini_state` writer since Phase 8 — there is NO dual-write happening now. `status` is already stale/frozen. The migration window scope is: "Phase 13 ends the window — no code may write `status` (already true), and `status` reads are eliminated in 13-02." Hard drop `status` within Phase 13 (plan 13-02). No separate "next phase" needed because the window is already effectively closed.

**Open questions:**
- Does any code path still write to `status`? (The audit in 13-01 must check for writes, not just reads)

**Confidence:** ✅ All 3 providers — end date must be explicit and bounded

---

### ✅ 4. Plain String Storage Verification (Consensus)

**What needs to be decided:**
How to prove that `gemini_state` is stored as a plain string in the DB, not as a library-native object or serialization artifact.

**Why it's ambiguous:**
FSM-03 requires sqlite3 CLI verification. The mechanism for enforcement (DB CHECK constraint, type validation, test) is not specified.

**Provider synthesis:**
- **OpenAI:** Three-layer enforcement: DB CHECK constraint + Python StrEnum + integration test reading raw DB
- **Gemini:** TypeDecorator or SQLModel validator enforcing `.value` at write boundary; sqlite3 CLI test as source of truth
- **Perplexity:** Direct sqlite3 inspection; validate `SELECT DISTINCT gemini_state FROM files` returns only the 5 allowed strings; check no pickle/binary markers

**Proposed implementation decision:**
Phase 12 already demonstrated plain string storage (FSM uses explicit `str()` conversion at write boundary). For Phase 13: (1) run `sqlite3 data/library.db "SELECT DISTINCT gemini_state FROM files"` and confirm only valid strings appear, (2) add a `CHECK (gemini_state IN ('untracked','uploading','processing','indexed','failed'))` DB constraint via V11 migration — this adds DB-level enforcement going forward.

**Confidence:** ✅ Consensus — verified by sqlite3 CLI is SC-2; enforcement mechanism is design decision

---

### ✅ 5. Query-Site Inventory Scope (Consensus)

**What needs to be decided:**
What counts as a "query site" for the SC-1 inventory, and how comprehensive the grep/audit must be.

**Why it's ambiguous:**
"Every query site" is vague — does it include tests? Scripts? Docs? The committed list format is not specified.

**Provider synthesis:**
- **OpenAI:** Scope: `src/`, CLI, tests, scripts in repo. Implement ripgrep-based script outputting deterministic report. CI gate with zero remaining `status` reads.
- **Gemini:** Focus on raw SQL strings; ORM model definitions; test fixtures; scripts shipped in repo
- **Perplexity:** Categorize by type and criticality; include views/migrations; document file path, line number, exact context

**Proposed implementation decision:**
Scope: all Python files under `src/`, `tests/`, `scripts/`. Search patterns: `"status"` in SQL string literals, `.status` attribute access on file/record objects, `gemini_state IS NULL` or `status IS NULL` patterns. Output: `docs/migrations/phase13-status-inventory.md` with columns: file path, line number, context snippet, mapped gemini_state query, change status. The list committed to repo is the deliverable for SC-1.

**Confidence:** ✅ All 3 providers — inventory must be scripted and committed

---

### ⚠️ 6. In-Flight / Transient State Handling (Recommended)

**What needs to be decided:**
How to handle any files whose legacy `status` would map to a transient FSM state (`uploading`, `processing`).

**Why it's ambiguous:**
If legacy status = 'uploading' or 'processing', mapping to those FSM states is unsafe — the process that was performing the upload no longer exists. Files stuck in transient FSM states require manual recovery.

**Provider synthesis:**
- **Gemini:** Map any transient legacy status to `untracked` (safe restart) rather than `uploading`/`processing`
- **OpenAI:** Handle unknown legacy values → `untracked` with warning; never map to in-progress states without active process

**Proposed implementation decision:**
Map all legacy transient states (`uploading`, `in_progress`, `processing`, any partial-upload value) to `untracked`. This is safe because: (1) the Phase 8 reset already set `gemini_state = 'untracked'` for all files; (2) the FSM is the only valid path to transient states and requires an active upload process. The `13-01` audit should confirm no files have `gemini_state IN ('uploading', 'processing')` after Phase 12 completed.

**Confidence:** ⚠️ 2 providers — important for mapping completeness; simplified by Phase 8 having pre-reset all states

---

### ⚠️ 7. FSM State Serialization Mechanics (Recommended)

**What needs to be decided:**
How python-statemachine 2.6.0 represents state — specifically whether `current_state.id` reliably returns the lowercase string identifier.

**Why it's ambiguous:**
The library could store state as State object repr, uppercase ID, or value attribute depending on how `State` objects are defined.

**Provider synthesis:**
- **Gemini:** Use `StrEnum` for states; configure library to use `.value`; add SQLAlchemy TypeDecorator for safety
- **Perplexity:** Verify with sqlite3 CLI; check no binary serialization signatures in raw DB bytes

**Proposed implementation decision:**
This was already resolved in Phase 12 — the FSM uses `current_state.id` which returns the state's string identifier (lowercase: `'untracked'`, `'uploading'`, etc.). The Phase 12 T=0 baseline and temporal stability checks confirmed correct plain string storage. The `13-01` sqlite3 verification reconfirms this. No additional TypeDecorator needed — the existing write pattern is confirmed correct.

**Confidence:** ⚠️ 2 providers — already solved; needs verification confirmation only

---

### 🔍 8. Behavioral Compatibility: TUI Labels (Noted)

**What needs to be decided:**
Whether user-facing labels in TUI/CLI should change when displaying `gemini_state` values instead of `status` values.

**Provider synthesis:**
- **OpenAI:** Preserve UX labels via presentation layer; decouple storage migration from displayed terminology; update tests to assert same displayed text

**Proposed implementation decision:**
The `status` column in v1 held internal pipeline state (not displayed as-is to users). TUI displays file names and search results — not raw status strings. Any status-based filtering in TUI (e.g., "show only uploaded files") needs to be mapped to `gemini_state` equivalents in 13-02. For the TUI's upload progress display, `gemini_state` values are already meaningful ('indexed' = done, 'failed' = error). No label translation layer needed.

**Confidence:** 🔍 1 provider — low risk given TUI architecture

---

## Summary: Decision Checklist

Before planning, confirm:

**Tier 1 (Blocking):**
- [ ] What `DISTINCT status` values exist in `data/library.db` right now?
- [ ] Is any code path still writing to `status`? (audit writes, not just reads)
- [ ] Define complete `status → gemini_state` mapping dict including edge cases
- [ ] Define SC-1 inventory format and committed artifact location

**Tier 2 (Important):**
- [ ] Confirm `SELECT COUNT(*) FROM files WHERE gemini_state IS NULL` = 0
- [ ] Decide: DB CHECK constraint for valid gemini_state values (yes/no + when)
- [ ] Confirm no files in transient FSM states from Phase 12

**Tier 3 (Polish):**
- [ ] TUI label compatibility review (likely no changes needed)
- [ ] Error persistence model (out of scope for Phase 13)

---

*Multi-provider synthesis by: OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research*
*Generated: 2026-02-22*
*Phase 13 directory: .planning/phases/13-state-column-retirement/*
