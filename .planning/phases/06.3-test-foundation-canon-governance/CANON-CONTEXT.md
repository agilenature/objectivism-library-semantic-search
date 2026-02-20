# Canon Context — Phase 6.3 Reference

**Purpose:** This document preserves the full conversation and decisions made about Canon before Phase 6.3 was formally planned. It is the authoritative context for the phase discussion, skill implementation, and application to this project.

**Created:** 2026-02-18 (end of Phase 5 session, before context clear)

---

## 1. What Canon Is

Canon is a **real-time documentation retrieval and ranking system** — an intelligent intermediary between AI coding assistants and library documentation. Rather than relying on static training data, it provides up-to-date, version-specific documentation pulled from live sources.

**The two-step workflow:**
1. `resolve-library-id` — resolves a library name to a canonical ID
2. `query-docs` — fetches focused documentation snippets using that ID and a query string

**Note on validated corrections (from Canon Validation.md):**
- The tool is `query-docs`, NOT `get-library-docs` (outdated name)
- There is NO separate `topic` parameter — embed topic in the query string
- "Only latest docs stored" is NOT a hard guarantee — it's a default exclusion heuristic for `old/deprecated/legacy/archived` folder names
- `Canon.json` supports `previousVersions` (tag-based) and `branchVersions` (branch-based)

**Reorganized Canon.md** lives at `/Users/david/Downloads/Canon.md` and is structured as:
- Part I: For Consumers (Agents and Developers) — how to query Canon
- Part II: For Library Owners (Publishers) — how to prepare your library

---

## 2. The Core Insight: TUI as Client

Before planning Phase 7 (Interactive TUI), the user established a foundational principle:

> **The TUI is a client of the system, not a participant in its implementation.**

This means:
- The TUI imports from a documented, stable service layer (`objlib.services`)
- The TUI never touches internal pipeline modules (upload, extraction, entities, sync, cli)
- The interface between the system and the TUI is explicit, versioned, and governed

Canon was chosen as the governance model for this interface because it already solves the problem of: "how do you make a library's public API surface discoverable, stable, and correctly used by agents?"

---

## 3. The Two-Layer Model

Canon.json has two distinct layers with different update cadences:

### Layer 1 — Contract Layer (updated at phase boundaries)
Controls what IS the public API surface and what rules clients must follow.

| Field | Role |
|-------|------|
| `folders` | What Canon indexes — the public surface |
| `excludeFolders` | What Canon ignores — internal pipelines |
| `excludeFiles` | Specific files excluded (e.g., `cli.py`) |
| `rules` | Client usage constraints surfaced alongside docs |

**Updated by:** `/update-docs` skill (and the new `canon-update` skill) after each phase completes.

### Layer 2 — Version Layer (updated at milestone boundaries)
Controls which historical versions clients can pin to.

| Field | Role |
|-------|------|
| `previousVersions` | Tag-based historical releases |
| `branchVersions` | Branch-based pre-release lines |

**Updated by:** Milestone completion process (currently v1, no historical versions yet).

### Governance relationship
- Canon.json and `docs/architecture/client-interface.md` must always agree
- Canon.json IS the source of truth for the public boundary
- The update process must keep both in sync

---

## 4. Files Created in This Session

### `/Users/david/projects/objectivism-library-semantic-search/Canon.json`

```json
{
  "$schema": "https://canon.so/schema/canon.json",
  "projectTitle": "objlib",
  "description": "Service library and CLI for semantic search over a curated Objectivism Library — 1,749 philosophical texts indexed via Google Gemini File Search with AI-enriched 4-tier metadata (category, difficulty, topics, aspects, descriptions) and entity extraction",
  "branch": "main",
  "folders": [
    "docs/",
    "src/objlib/services/"
  ],
  "excludeFolders": [
    "src/objlib/__pycache__",
    "src/objlib/upload",
    "src/objlib/extraction",
    "src/objlib/entities",
    "src/objlib/sync",
    "src/objlib/search/__pycache__",
    "src/objlib/session/__pycache__",
    ".planning",
    "data",
    "tests",
    "scripts"
  ],
  "excludeFiles": [
    "cli.py"
  ],
  "rules": [
    "Import only from objlib.services — never from objlib.cli, objlib.upload, objlib.extraction, objlib.entities, or objlib.sync; those are internal pipeline modules, not part of the public API.",
    "All Gemini search operations are async and carry 300ms–2s network latency — always await SearchService methods inside an async context or dispatch them to a background worker; never call them on the main thread of a TUI.",
    "Use Database as a context manager ('with Database(db_path) as db:') — never hold a connection open across async await boundaries.",
    "Search results are Citation objects — access enriched SQLite metadata via Citation.file_path and Citation.metadata; do not query the database directly for search result enrichment.",
    "The active Gemini store name is read from AppState.store_resource_name — never hardcode a store name in client code.",
    "Session events are append-only — use SessionService.add_event(); there are no update or delete methods for session records.",
    "Numeric metadata fields (year, week, quality_score) require CAST in raw SQL — always use LibraryService filter methods instead of writing SQL directly.",
    "The --store parameter for search must be passed before the subcommand when using the CLI ('python -m objlib --store NAME search QUERY'); for view --show-related it comes after the subcommand.",
    "Disk-dependent commands (scan, upload, enriched-upload, sync) require the library volume at /Volumes/U32 Shadow to be mounted — query commands (search, browse, filter, view) work without it."
  ],
  "previousVersions": [],
  "branchVersions": []
}
```

**Key design decisions in this file:**
- `src/objlib/services/` is listed in `folders` but does NOT yet exist — it is created in Phase 7
- `cli.py` is excluded because Typer command wiring is not a public API
- `src/objlib/upload`, `extraction`, `entities`, `sync` are excluded — internal pipelines
- Rules encode the hard-won constraints from building the system (--store position, CAST for numerics, async latency)

### `docs/architecture/client-interface.md`

Defines the public boundary for the TUI and future clients. Key content:

**The boundary rule:**
```
✅ May import from:
   objlib.services.*     ← service layer (to be built in Phase 7)
   objlib.models         ← core dataclasses
   objlib.search.models  ← Pydantic result types

❌ Must never import from:
   objlib.cli            ← CLI command definitions
   objlib.upload.*       ← Gemini upload pipeline
   objlib.extraction.*   ← Mistral batch extraction
   objlib.entities.*     ← entity extraction pipeline
   objlib.sync.*         ← incremental sync pipeline
   objlib.database       ← raw SQLite access
   objlib.scanner        ← file scanner
```

**The four services to be built in Phase 7:**
- `SearchService` — wraps search pipeline (query, synthesize, expand_query, build_filter)
- `LibraryService` — wraps database read-only methods (browse, filter_files, get_file_metadata, get_file_content)
- `SessionService` — wraps SessionManager (create, list, get, add_event, export_markdown)
- `GlossaryService` — wraps expansion module (get_all, add_term, expand)

**Async contract:**
- `SearchService.query()` and `synthesize()` are async (300ms–2s); use Textual `@work` or `run_worker()`
- `LibraryService.*` and `SessionService.*` are sync; safe to call directly
- `GlossaryService.*` is sync; cached after first load

---

## 5. The Global Canon Skills

### Design decision: Skills, not commands
Per Claude Code documentation: Skills are the modern approach (directory-based, `.claude/skills/my-skill/SKILL.md`). Commands (`.claude/commands/*.md`) are legacy. Skills support:
- Supporting files alongside the main prompt
- YAML frontmatter for invocation behavior
- Auto-invocation when relevant
- Organized templates and detectors

### Skill names
- `/canon-init` — first-time setup for a project
- `/canon-update` — maintenance after each phase

### Skill location (global — works for any project)
```
~/.claude/skills/
  canon-init/
    SKILL.md                        ← main prompt + frontmatter
    templates/
      Canon.json.template
      client-interface.template.md
    workflows/
      gsd.md                        ← how to detect + read a GSD project
      ralph.md                      ← how to detect + read a Ralph project
      bmad.md                       ← how to detect + read a BMAD project
      generic.md                    ← fallback (pyproject.toml, package.json, README)
  canon-update/
    SKILL.md
    workflows/
      gsd.md
      ralph.md
      bmad.md
      generic.md
```

### What each skill does

**`canon-init`:**
1. Detect project workflow type (GSD/Ralph/BMAD/Generic) by checking for control files
2. Read project context using the appropriate workflow detector
3. Analyze codebase: identify public vs internal module structure
4. Generate `Canon.json` at project root (using Canon.json.template as base)
5. Generate `docs/architecture/client-interface.md` (or equivalent)
6. Report what was created and what the public boundary is

**`canon-update`:**
1. Detect project workflow type
2. Read current `Canon.json`
3. Audit codebase against current `folders` and `excludeFolders`
4. Layer 1 audit: any new public modules not in `folders`? New internal modules not in `excludeFolders`? New constraints discovered for `rules`?
5. Layer 2 audit: at milestone boundary? If yes, flag `previousVersions` update needed
6. Update Canon.json if Layer 1 drift detected
7. Update `client-interface.md` if public API surface changed
8. Report changes (or "no drift detected")

### Workflow awareness — project detection
```
GSD?    → .planning/STATE.md + .planning/ROADMAP.md present
Ralph?  → [TBD from research wave]
BMAD?   → [TBD from research wave]
Generic → fallback: pyproject.toml / package.json / README.md
```

---

## 6. Phase 6.3 Structure

**Phase name:** Test Foundation & Canon Governance
**Inserted between:** Phase 6.2 (complete) and Phase 7 (TUI)
**Phase number:** 6.3 (follows decimal insertion pattern from 6.1, 6.2)

**Goal:** Before the TUI is built as a client, prove the system is stable (retroactive tests), understand the workflow landscape (research), build the Canon skills properly (implementation), and apply them to this project — so Phase 7 starts from verified ground.

### Wave 1 (parallel with Wave 2) — Retroactive Test Suite

| Plan | Coverage |
|------|---------|
| 6.3-01 | Database: schema migrations V1→V7, all CRUD methods, sync methods, triggers — in-memory SQLite |
| 6.3-02 | Metadata: folder/filename pattern parsing, MetadataExtractor edge cases, change detection logic |
| 6.3-03 | Search: query expansion, citation building + enrichment, metadata filter syntax, MMR diversity, difficulty bucketing |
| 6.3-04 | Sync + entities + session: SyncDetector classification, disk utility logic, entity fuzzy matching thresholds, SessionManager append-only semantics |

### Wave 2 (parallel with Wave 1) — Workflow Research

| Plan | Coverage |
|------|---------|
| 6.3-05 | Deep research into GSD, Ralph (https://github.com/frankbria/ralph-claude-code), and BMAD (https://github.com/bmad-code-org/BMAD-METHOD, https://docs.bmad-method.org/) workflows. Map each workflow's control documents, their roles, and what project state they encode. Produce workflow detector summaries for `canon-init/workflows/` and `canon-update/workflows/`. |

### Wave 3 (depends on Wave 2) — Canon Skill Implementation

| Plan | What |
|------|-----|
| 6.3-06 | Build `~/.claude/skills/canon-init/` — workflow-aware project initialization skill with templates |
| 6.3-07 | Build `~/.claude/skills/canon-update/` — workflow-aware audit and update skill |

### Wave 4 (depends on Wave 1 + Wave 3) — Apply to This Project

| Plan | What |
|------|-----|
| 6.3-08 | Run `/canon-update` on this project, hook it into `/update-docs`, run full test suite, verify no regressions |

### Verification criteria
- All tests pass (zero failures)
- `/canon-init` initializes a scratch project correctly (produces valid Canon.json + client-interface.md)
- `/canon-update` detects drift and reports it correctly on this project
- Canon.json for this project matches actual codebase boundary
- All existing CLI commands work end-to-end (regression)

---

## 7. Key Decisions Made

| Decision | Rationale |
|----------|-----------|
| TUI is a client of the system, not embedded in it | Enforces stability, testability, and clean separation before Phase 7 |
| Canon as governance model | Already solves the "public API surface for agents/clients" problem; applying it to our system gives us the same guarantees |
| Skills not commands | Modern Claude Code approach; directory-based skills support templates and supporting files needed for workflow detectors |
| Global skills (`~/.claude/skills/`) | Must work for any project, not just this one — first applied here, reusable everywhere |
| Two-layer model | Contract layer (phase-boundary cadence) and version layer (milestone cadence) have different owners and triggers |
| `update-docs` is the hook for Layer 1 | Already part of workflow discipline; Canon.json audit added to same process |
| Retroactive tests before TUI | TUI clients need a stable foundation; tests prove stability before we define the public API |
| Research wave before skill implementation | Skill can only be workflow-aware if we know what GSD/Ralph/BMAD control documents look like |

---

## 8. What Comes After Phase 6.3

**Phase 7: Interactive TUI**
- The TUI is built as a client of `objlib.services`
- Canon.json defines exactly what the TUI can import
- `client-interface.md` defines the service contracts the TUI depends on
- The retroactive test suite from 6.3 proves the services are stable
- The Textual framework is the planned TUI implementation technology

**The TUI's service entry point (to be built in Phase 7):**
```python
from objlib.services import SearchService, LibraryService, SessionService, GlossaryService
```

Nothing from `objlib.cli`, `objlib.upload`, `objlib.extraction`, `objlib.entities`, or `objlib.sync` is accessible to the TUI.

---

## 9. Artifacts Reference

| File | Location | Status |
|------|----------|--------|
| Canon.md (reorganized) | `/Users/david/Downloads/Canon.md` | Complete |
| Canon Validation.md | `/Users/david/Downloads/Canon Validation.md` | Reference (applied to Canon.md) |
| Canon.json for objlib | `/Users/david/projects/objectivism-library-semantic-search/Canon.json` | Created, Layer 2 empty (v1 not yet released) |
| client-interface.md | `docs/architecture/client-interface.md` | Created, services layer planned for Phase 7 |
| Phase 6.3 directory | `.planning/phases/06.3-test-foundation-canon-governance/` | Created (this file) |

---

*This document was created at the end of the Phase 5 session to preserve Canon context before a context window clear. It is the primary reference for Phase 6.3 planning and the canon-init / canon-update skill implementation.*
