# CLARIFICATIONS-NEEDED.md

## Phase 6.3: Test Foundation & Canon Governance — Decisions Required

**Generated:** 2026-02-18
**Mode:** Multi-provider synthesis (Gemini Pro, Perplexity Sonar Deep Research)

---

## Decision Summary

**Total questions:** 8
**Tier 1 (Blocking):** 3 questions — Must answer before planning plans 01-04
**Tier 2 (Important):** 3 questions — Must answer before planning plans 06-07
**Tier 3 (Polish):** 2 questions — Can refine during implementation

---

## Tier 1: Blocking Decisions

### Q1: Filesystem Simulation Strategy for Scanner/Sync Tests

**Question:** Plans 06.3-02 and 06.3-04 test the file scanner, SyncDetector, and disk utility. These modules use `os.stat`, `pathlib`, and mtime checks — real OS operations. How do we test them without disk I/O?

**Why it matters:** Without a filesystem simulation strategy, scanner and SyncDetector tests can't be written. Wrong choice requires refactoring the scanner (invasive) or produces shallow tests.

**Options:**

**A. pyfakefs (Recommended)**
- Add `pyfakefs` as test dependency
- Intercepts all OS calls at the stdlib level — no refactoring needed
- Tests exercise real scanner code against in-memory filesystem
- Simulates mtime, file existence, disk mount points cleanly
- _(Proposed by: Gemini, Perplexity)_

**B. unittest.mock patching**
- Patch `os.stat`, `Path.stat`, `Path.exists` individually
- No new dependencies
- More brittle — must patch every OS call separately
- Misses emergent behaviors from OS interaction
- _(Proposed by: neither as primary choice)_

**C. Minimal abstraction layer**
- Refactor scanner to accept `AbstractFileSystem` interface
- More testable long-term but requires code changes
- Not suitable for retroactive tests (changes existing code)
- _(Not recommended for retroactive phase)_

**Synthesis recommendation:** ✅ **Option A — pyfakefs**
- Least invasive for retroactive tests
- Correctly simulates the mtime epsilon behavior noted in `[05-04]`
- `pyfakefs` is a well-maintained, pytest-native library

**Sub-questions:**
- Does SyncDetector use any inotify/kqueue system calls? (Check `src/objlib/sync/` before committing)
- Should scanner tests be tagged `@pytest.mark.filesystem` for selective running?

---

### Q2: API Mocking Level for LLM-Adjacent Tests

**Question:** Plans 06.3-03 and 06.3-04 test query expansion, citation building, reranking, synthesis, and entity fuzzy matching. These call Gemini/Mistral. What level of abstraction do we mock?

**Why it matters:** Mocking at the wrong level produces tests that pass trivially. Mocking at the right level tests real business logic (prompt construction, response parsing, citation mapping, MMR scoring).

**Options:**

**A. Mock at API client boundary (Recommended)**
- Create `MockGeminiSearchClient` that returns predefined `SearchResult` objects
- Tests verify: citation IDs map to correct files, MMR filters duplicates, difficulty ordering sorts correctly, expansion glossary terms appear in query
- What we do NOT test: does Gemini return relevant results (not testable without API)
- _(Proposed by: Gemini)_

**B. Mock at HTTP level (Beeceptor/mock server)**
- Run a local Flask server returning crafted JSON responses
- Real SDK makes real HTTP calls to the mock server
- Tests verify request structure and response parsing
- Higher setup cost; better for integration path
- _(Proposed by: Perplexity as tier-2 option)_

**C. End-to-end mocks only**
- Mock the entire search command result, not intermediate steps
- Fastest to write but lowest value — tests the formatter, not the logic
- _(Not recommended)_

**Synthesis recommendation:** ✅ **Option A for unit tests, Option B is deferred (optional)**
- Unit tests: mock at the `GeminiSearchClient` interface boundary
- Reranker tests: mock `GenerativeModel.generate_content()` to return deterministic `RankedResults` JSON
- Citation tests: mock the raw `retrieved_context` list from Gemini API
- No HTTP mock server needed for this retroactive phase

**Sub-questions:**
- Is `enrich_citations()` tightly coupled to raw Gemini response format, or does it operate on intermediate `Citation` dataclasses? (Check `src/objlib/search/`)
- Should there be a shared `conftest.py` fixture for `mock_gemini_response()` or inline per test?

---

### Q3: Schema Migration Test Scope (V1 → V7)

**Question:** Plan 06.3-01 specifies testing "schema migrations V1→V7." Does the codebase have discrete per-version migration SQL? If not, what does this plan actually test?

**Why it matters:** If we don't have migration scripts, we can't test sequential V1→V7 migration. Fabricating a fake migration history tests something that doesn't exist.

**Options:**

**A. Test sequential migrations (only if scripts exist)**
- Apply V1 schema, then V2 migration SQL, then V3, etc.
- Tests prove each migration applies cleanly and leaves DB in expected state
- Requires that each version's SQL exists as a discrete artifact
- _(Viable only if database.py has versioned migration blocks)_

**B. Test cumulative schema + ALTER TABLE (Recommended — likely current state)**
- The database uses `CREATE TABLE IF NOT EXISTS` + `try/except ALTER TABLE` pattern (per `[06-01]`)
- Test: call `Database.initialize()` on a fresh in-memory DB, verify all V7 tables/columns/triggers exist
- Also test: calling `initialize()` twice is idempotent (no errors, no data loss)
- Also test: specific columns added in key versions exist (e.g., `gemini_file_id`, `metadata_json`, AI metadata columns)
- _(Proposed by: Gemini and Perplexity when discrete scripts absent)_

**C. Use SQLite `user_version` pragma for version tracking**
- The DB could use `PRAGMA user_version` to track schema version explicitly
- Check if this is currently implemented; if not, out of scope for retroactive tests

**Synthesis recommendation:** ✅ **Option B — test cumulative initialization and idempotency**
- First task in plan 06.3-01: audit `src/objlib/database.py` to determine what migration artifacts exist
- Test the resulting V7 schema correctness, not hypothetical intermediate states
- Test all key columns across all schema additions: foundation columns, upload columns, AI metadata columns, entity columns, enriched upload columns, sync columns

**Sub-questions:**
- Does `Database.initialize()` use `PRAGMA user_version`? If yes, test version increments.
- Are there SQLite triggers (e.g., auto-update `updated_at`) that need explicit testing?

---

## Tier 2: Important Decisions

### Q4: Canon.json Template Parameterization

**Question:** Plan 06.3-06 builds `canon-init` with a `Canon.json.template`. How is the template parameterized across workflow types? Single template with variables, or per-workflow templates?

**Why it matters:** Template design determines how easily `canon-init` generalizes to new projects.

**Options:**

**A. Single template with placeholder variables (Recommended)**
- `{{PROJECT_TITLE}}`, `{{PUBLIC_FOLDERS}}`, `{{EXCLUDE_FOLDERS}}`, `{{RULES}}`
- Workflow-specific `rules/gsd-rules.md`, `rules/ralph-rules.md`, etc. provide the default rules text
- One template to maintain; workflow flavor comes from the rules reference files
- _(Synthesis recommendation)_

**B. Per-workflow templates**
- `canon-layer2-gsd.json.template`, `canon-layer2-ralph.json.template`, etc.
- More explicit but more files to maintain
- _(Proposed by Perplexity)_

**Synthesis recommendation:** ⚠️ **Option A — single template**

**Sub-questions:**
- Should Canon.json include a `_generated_by` metadata field (e.g., `"_workflow": "gsd"`) for `canon-update` to know which workflow rules to use on next audit? (Not part of canon.so schema, but useful pragmatically)
- Should `client-interface.md` be generated by `canon-init` in the same skill execution, or a separate step?

---

### Q5: Workflow Detection Algorithm Placement

**Question:** Where does the detection logic live — in SKILL.md itself (as Claude instructions), or in the `workflows/*.md` reference files?

**Why it matters:** Affects maintainability and how easily the skill is updated when Ralph/BMAD signals are discovered.

**Options:**

**A. Detection logic in SKILL.md, signals in reference files (Recommended)**
- SKILL.md has the algorithm (priority order, confidence scoring, fallback)
- `workflows/gsd.md`, `workflows/ralph.md`, etc. document the specific file signals and what project state they encode
- Claude reads the reference files when needed to know what signals to look for
- _(Clean separation of algorithm from data)_

**B. All detection in SKILL.md**
- Self-contained, simpler file structure
- Harder to update when new signals are discovered

**Synthesis recommendation:** ✅ **Option A — algorithm in SKILL.md, signals in reference files**
- GSD signals (known): `.planning/STATE.md` + `.planning/ROADMAP.md` present
- Ralph signals: TBD from plan 06.3-05 research → encoded in `workflows/ralph.md`
- BMAD signals: TBD from plan 06.3-05 research → encoded in `workflows/bmad.md`
- Detection priority: existing Canon.json (highest) → BMAD → Ralph → GSD → Generic (fallback)

**Sub-questions:**
- On ambiguity (multiple workflow signals present), should skill default to Generic silently or output a warning and ask?
- Should detection results be written to Canon.json for debugging/auditing?

---

### Q6: canon-update Hook into /update-docs

**Question:** Plan 06.3-07 says "hook into /update-docs." What does this mean concretely — modify the existing `/update-docs` skill to call `canon-update`, or document that users should run both?

**Why it matters:** Determines whether Canon auditing is automatic or manual.

**Options:**

**A. Modify `/update-docs` skill to include canon-update steps (Recommended)**
- `/update-docs` already runs after each phase completion
- Add a final step: "Run `/canon-update` to audit Canon.json Layer 1 drift"
- Or: inline the Layer 1 audit logic directly in `/update-docs`
- _(Keeps governance integrated into existing workflow discipline)_

**B. Standalone `canon-update` only — document separately**
- Users remember to run it after each phase
- Less reliable; depends on user discipline
- _(Not recommended)_

**Synthesis recommendation:** ✅ **Option A — integrate into /update-docs**
- The `/update-docs` skill is at `.claude/commands/update-docs.md` (from git status)
- Add a final section to that skill: "Layer 1 Canon Audit — check folders/excludeFolders/rules against actual codebase"
- The full `canon-update` skill is more comprehensive; the inline audit in update-docs can be a lightweight version

**Sub-questions:**
- Read `.claude/commands/update-docs.md` first to understand its current structure before modifying
- Should Layer 1 audit detect new public modules that should be added to `folders`?

---

## Tier 3: Polish Decisions

### Q7: Test Coverage Targets

**Question:** What numeric coverage target gates plan completion?

**Proposed answer:** 80% line coverage per module, measured by `pytest --cov`. Branch coverage measured but not gated. Functional completeness (checklist of behaviors) is the primary gate.

**Sub-questions:**
- Include or exclude `cli.py` from coverage measurement?
- Should a `pytest.ini` or `pyproject.toml` coverage config be added?

---

### Q8: Shared Test Fixture Organization

**Question:** Should the four retroactive test plans share a root `tests/conftest.py` with common fixtures?

**Proposed answer:** Yes — create `tests/conftest.py` with `in_memory_db()`, `populated_db()`, and `mock_gemini_client()` fixtures (scope=function). Individual test files add plan-specific fixtures.

**Sub-questions:**
- Should schema initialization in conftest call the real `Database.initialize()` or hardcode schema SQL?
- Recommended: call real `Database.initialize()` — it tests the method AND provides the fixture.

---

## Next Steps (YOLO Mode)

YOLO mode — answers auto-generated in `CLARIFICATIONS-ANSWERED.md`.

Proceed to `/gsd:plan-phase 6.3` when ready.

---

*Multi-provider synthesis: Gemini Pro + Perplexity Sonar Deep Research*
*Generated: 2026-02-18*
*YOLO mode: Auto-answers generated*
