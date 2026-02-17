# Roadmap: Objectivism Library Semantic Search

## Overview

This roadmap transforms a 1,749-file Objectivism Library into a semantic search system using Google Gemini's File Search API. The journey follows the natural three-phase pipeline (scan, upload, query) dictated by the architecture, extended with quality enhancements, incremental updates, offline query mode, AI-powered metadata enrichment, and an interactive terminal interface. Each phase delivers a complete, independently verifiable capability: Phase 1 builds the foundation offline with zero API dependencies, Phase 2 gets files into Gemini reliably, Phase 3 delivers working search, Phase 4 sharpens result quality with reranking and synthesis, Phase 5 makes the system maintainable long-term with incremental updates and enables querying without source disk access, Phase 6 uses LLMs to automatically infer rich metadata from content, and Phase 7 wraps everything in a modern TUI for immersive research workflows.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation** - SQLite state tracking and library scanning with metadata extraction
- [x] **Phase 2: Upload Pipeline** - Reliable batch upload to Gemini File Search with rate limiting and resume
- [x] **Phase 3: Search & CLI** - Semantic search, filtering, and CLI interface for querying the indexed library
- [ ] **Phase 4: Quality Enhancements** - Reranking, synthesis, query expansion, and difficulty-aware ordering
- [ ] **Phase 5: Incremental Updates & Offline Mode** - Change detection, selective re-upload, and disk-independent querying
- [ ] **Phase 6: AI-Powered Metadata** - LLM-based category inference, difficulty detection, and topic extraction
- [ ] **Phase 7: Interactive TUI** - Modern terminal UI with live search, visual browsing, and session management

## Phase Details

### Phase 1: Foundation
**Goal**: User can scan the entire 1,749-file library offline, extracting rich metadata from every file, with all state persisted to SQLite -- ready for upload
**Depends on**: Nothing (first phase)
**Requirements**: FOUN-01, FOUN-02, FOUN-03, FOUN-04, FOUN-05, FOUN-06, FOUN-07, FOUN-08, FOUN-09
**Success Criteria** (what must be TRUE):
  1. Running the scanner against `/Volumes/U32 Shadow/Objectivism Library` discovers all 1,749 .txt files and records each in the SQLite database with its content hash, file path, and size
  2. Each scanned file has extracted metadata (course, year, quarter, week, topic, instructor, difficulty) derived from its folder hierarchy and filename -- viewable by querying the database
  3. Re-running the scanner on an unchanged library produces zero new inserts and zero hash changes (idempotent)
  4. Running the scanner after adding, modifying, or deleting files correctly detects each change type (new, modified, deleted) and updates the database accordingly
  5. The SQLite database schema includes upload status tracking (pending/uploading/uploaded/failed), Gemini file IDs, upload timestamps, and embedding model version -- ready for Phase 2 to consume
**Plans:** 3 plans

Plans:
- [ ] 01-01-PLAN.md — Project scaffolding, data models, config, and SQLite database layer
- [ ] 01-02-PLAN.md — Metadata extraction engine and file scanner with change detection
- [ ] 01-03-PLAN.md — Typer CLI interface and comprehensive test suite

### Phase 2: Upload Pipeline
**Goal**: User can upload the entire library to Gemini File Search reliably -- with rate limiting, resume from interruption, and progress visibility -- resulting in a fully indexed and queryable store
**Depends on**: Phase 1
**Requirements**: UPLD-01, UPLD-02, UPLD-03, UPLD-04, UPLD-05, UPLD-06, UPLD-07, UPLD-08, UPLD-09, UPLD-10
**Success Criteria** (what must be TRUE):
  1. Running the upload command processes all pending files in batches of 100-200, with Rich progress bars showing per-file and per-batch status, completing within the 36-hour safety window per batch
  2. Interrupting the upload mid-batch (Ctrl+C or crash) and restarting skips already-uploaded files and resumes from the exact point of interruption -- no duplicate uploads, no lost progress
  3. When Gemini returns 429 rate-limit errors, the system backs off automatically (exponential with jitter) and reduces concurrency, without user intervention, eventually completing the batch
  4. After upload completes, every file in the SQLite database shows status "uploaded" with a valid Gemini file ID, and the Gemini File Search store reports the correct file count
  5. Each uploaded file carries its full metadata (20-30 fields) attached to the Gemini file record, preserving the pedagogical structure for downstream filtering
**Plans:** 3 plans

Plans:
- [ ] 02-01-PLAN.md — Dependencies, schema extensions, Gemini client wrapper, circuit breaker, and rate limiter
- [ ] 02-02-PLAN.md — Async state manager, upload orchestrator, Rich progress tracking, and CLI upload command
- [ ] 02-03-PLAN.md — Crash recovery protocol, unit test suite, and real-API verification

### Phase 3: Search & CLI
**Goal**: User can search the indexed library by meaning, filter by metadata, browse by structure, and see results with source citations -- all from a polished CLI interface
**Depends on**: Phase 2
**Requirements**: SRCH-01, SRCH-02, SRCH-03, SRCH-04, SRCH-05, SRCH-06, SRCH-07, SRCH-08, INTF-01, INTF-02, INTF-03, INTF-04, INTF-05, INTF-06, INTF-07
**Success Criteria** (what must be TRUE):
  1. Running `search "What is the Objectivist view of rights?"` returns semantically relevant results from across the library, ranked by relevance, with each result showing the source file name, course context, and a text excerpt -- not just file paths
  2. Running `search "causality" --course "OPAR" --difficulty introductory` returns only results matching the metadata filters, demonstrating that semantic search and metadata filtering work together
  3. Running `browse --course "History of Philosophy"` displays the structural hierarchy (years, quarters, weeks) and lets the user navigate without a search query
  4. Every search result includes passage-level citation (specific text excerpt with source attribution) that traces back to the exact file and section in the library
  5. The CLI uses Rich formatting (tables for results, panels for detail views, color-coded relevance scores) and provides `search`, `filter`, and `browse` commands via Typer with `--help` documentation
**Plans:** 3 plans

Plans:
- [ ] 03-01-PLAN.md -- Query layer: Gemini search client, citation extraction, AppState, search command
- [ ] 03-02-PLAN.md -- Display layer: Three-tier Rich formatting, score bars, view command
- [ ] 03-03-PLAN.md -- Navigation layer: Browse and filter commands with SQLite metadata queries

### Phase 4: Quality Enhancements
**Goal**: Search results are sharper (reranked for precision), answers synthesize across sources (with inline citations), and queries understand philosophical terminology -- transforming raw search into a research tool
**Depends on**: Phase 3
**Requirements**: ADVN-01, ADVN-02, ADVN-03, ADVN-04, ADVN-05, ADVN-06, ADVN-07
**Success Criteria** (what must be TRUE):
  1. Searching for a concept like "free will" returns results ordered with introductory explanations first and advanced treatments later -- the user sees a natural learning progression without manually filtering by difficulty
  2. Running `search "What is the relationship between reason and emotion?" --synthesize` produces a multi-paragraph answer citing 5-10 specific passages with inline citations (e.g., "[OPAR Ch.4, p.12]"), where every claim traces to a quoted source
  3. Searching for "egoism" also retrieves results about "rational self-interest" and related philosophical terminology, demonstrating query expansion without the user needing to know all synonyms
  4. Running `search "concept formation" --track-evolution` shows how the concept develops from introductory (ITOE basics) through intermediate to advanced treatments, ordered by curriculum progression
  5. The user can save a research session and resume it later, picking up where they left off with previous queries and results preserved
**Plans**: TBD

Plans:
- [ ] 04-01: TBD
- [ ] 04-02: TBD

### Phase 5: Incremental Updates & Offline Mode
**Goal**: User can keep the search index current as the library grows AND query the library even when the source disk is disconnected -- detecting new or changed files and updating only what changed, while enabling full query functionality without filesystem access
**Depends on**: Phase 2 (pipeline), Phase 3 (CLI for sync command)
**Requirements**: INCR-01, INCR-02, INCR-03, INCR-04, INCR-05, OFFL-01, OFFL-02, OFFL-03
**Success Criteria** (what must be TRUE):
  1. After adding new files to the library directory, running `sync` detects the additions, uploads only the new files, and makes them searchable -- existing indexed files are untouched
  2. After modifying a file's content, running `sync` detects the content hash change, removes the old version from the Gemini store, uploads the updated version, and the new content appears in search results
  3. After deleting files from the library, running `sync` detects the removals and cleans up the corresponding Gemini store entries -- orphaned index entries do not pollute search results
  4. Running `sync --force` re-processes all files regardless of change detection, providing a manual override for cases where the user wants a full re-index
  5. With the source disk disconnected (library path unavailable), running `search`, `browse`, `filter`, and `view` (metadata only) commands work correctly using Gemini and SQLite -- query operations remain fully functional
  6. When source disk is disconnected, running `view --full` gracefully degrades to metadata-only view with clear messaging ("Source disk required for full document view") -- no crashes or confusing errors
  7. When source disk is disconnected, running `scan` or `upload` commands fail with clear, actionable error messages ("Library disk not connected at /Volumes/U32 Shadow/Objectivism Library") -- maintenance operations are explicitly disk-dependent
  8. The system automatically detects disk availability and adjusts operation modes accordingly -- user doesn't need to manually specify offline mode

### Phase 6: AI-Powered Metadata Enhancement
**Goal**: User can automatically infer and enhance metadata (categories, difficulty, topics) using LLM analysis of file content -- transforming generic "unknown" categories into rich, searchable metadata without manual effort
**Depends on**: Phase 1 (database schema), Phase 3 (metadata commands)
**Requirements**: META-01, META-02, META-03, META-04, META-05
**Success Criteria** (what must be TRUE):
  1. Running `metadata infer-categories` analyzes file content with a cost-effective LLM (Gemini Flash, Mixtral, or Haiku) and assigns appropriate categories (course, book, qa_session, philosophy_comparison, cultural_commentary, etc.) -- files with category="unknown" get meaningful classifications
  2. Running `metadata infer-difficulty` analyzes philosophical content complexity and assigns difficulty levels (introductory, intermediate, advanced) based on vocabulary, concept density, and prerequisite knowledge -- enabling difficulty-based search filtering
  3. The inference process provides a review/approval workflow showing proposed changes before applying them, with batch accept/reject options -- user maintains control over automated categorization
  4. Running `metadata infer --batch --auto-approve` processes the entire library unattended, with a summary report showing categorization statistics and low-confidence items flagged for manual review
  5. All inferred metadata is saved to SQLite and can optionally trigger re-upload to Gemini with `--set-pending` flag -- metadata improvements flow through to search results
**Plans:** 5 plans

Plans:
- [ ] 06-01-PLAN.md — Foundation: schema migration v3, Pydantic 4-tier models, Mistral client, response parser, API key management
- [ ] 06-02-PLAN.md — Wave 1 infrastructure: prompt strategies, test file sampler, competitive orchestrator, checkpoint/resume
- [ ] 06-03-PLAN.md — Wave 1 execution: CLI commands (extract-wave1, wave1-report, wave1-select), quality gates, human review checkpoint
- [ ] 06-04-PLAN.md — Wave 2 production pipeline: validation engine, confidence scoring, adaptive chunking, production orchestrator
- [ ] 06-05-PLAN.md — Wave 2 CLI & review: production extract/review/approve/stats commands, Rich 4-tier panels, human review checkpoint

### Phase 6.1: Entity Extraction & Name Normalization (INSERTED)

**Goal**: User can automatically extract and normalize person names mentioned in transcripts against a canonical list of Objectivist philosophers and ARI instructors -- transforming raw text mentions into structured, searchable entity metadata
**Depends on**: Phase 6 (AI metadata extraction)
**Status**: Complete (2026-02-16)
**Plans:** 2 plans

Plans:
- [x] 06.1-01-PLAN.md -- Schema v4 migration, person registry, entity extraction engine with TDD
- [x] 06.1-02-PLAN.md -- CLI commands (extract, stats, report) and database persistence methods

**Details:**
Extracts person name entities from transcripts, fuzzy matches against canonical list (Ayn Rand, Leonard Peikoff, Onkar Ghate, Robert Mayhew, Tara Smith, Ben Bayer, Mike Mazza, Aaron Smith, Tristan de Liège, Gregory Salmieri, Harry Binswanger, Jean Moroney, Yaron Brook, Don Watkins, Keith Lockitch), normalizes spelling variations, stores mention counts and normalized names as additional metadata for inclusion in Gemini upload.

### Phase 6.2: Metadata-Enriched Gemini Upload (INSERTED)

**Goal**: User can upload all files to Gemini File Search with enriched 4-tier metadata (category, difficulty, topics, aspects, descriptions) plus entity mentions -- enabling powerful metadata-based filtering and semantic search with full philosophical context
**Depends on**: Phase 6.1 (entity extraction), Phase 2 (upload pipeline)
**Plans:** 0 plans

Plans:
- [ ] TBD (run /gsd:plan-phase 6.2 to break down)

**Details:**
Extends Phase 2 upload pipeline to include 4-tier metadata from Phase 6 extraction and entity mentions from Phase 6.1. Flattens nested structures (semantic_description) into Gemini custom_metadata format (7 searchable fields). Implements parallel upload (3-5 concurrent), tracks per-file upload status, handles failures gracefully. Tests with ~280 already-extracted files first, then processes new files as extraction completes.

### Phase 7: Interactive TUI
**Goal**: User can interact with the library through a modern terminal UI with keyboard/mouse navigation, live search, visual browsing, split-pane views, and session management -- transforming the CLI into an immersive research environment
**Depends on**: Phase 3 (search & CLI), Phase 4 (synthesis), Phase 6 (metadata)
**Requirements**: TUI-01, TUI-02, TUI-03, TUI-04, TUI-05, TUI-06, TUI-07, TUI-08
**Success Criteria** (what must be TRUE):
  1. Running `objlib tui` launches an interactive terminal interface with live search input that updates results as you type -- no more typing `objlib search "query"` repeatedly
  2. The browse mode displays a navigable tree view (categories → courses → files) with keyboard controls (↑↓ arrows to navigate, Enter to drill down, Esc to go back) and file count badges -- visual exploration replaces memorizing browse command syntax
  3. The interface uses split-pane layout with search/navigation on the left, results in the middle, and document preview on the right -- user can see context without switching views
  4. Interactive filters provide checkboxes and sliders for category, difficulty, year ranges instead of command-line filter syntax -- metadata filtering becomes visual and discoverable
  5. The TUI preserves search history (accessible with ↑↓ arrows), allows bookmarking files and searches, and can save/load research sessions -- enabling iterative research workflows
  6. Document viewer supports scrolling, search term highlighting, and citation linking (click [1] to jump to source) -- seamless navigation between synthesis and sources
  7. The TUI supports both keyboard shortcuts (for power users) and mouse interaction (for discoverability) -- accessible to different user preferences
  8. All existing CLI functionality (search, browse, filter, view, metadata commands) is accessible through the TUI -- no regression in capabilities
**Plans**: TBD

Plans:
- [ ] 07-01: TBD
- [ ] 07-02: TBD
- [ ] 07-03: TBD

## Progress

**Execution Order:**
Phases execute in strategic order (not strictly numeric):

**Standard order:** 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7

**Actual execution (Metadata-First Strategy):**
1 -> 2 -> 3 -> **6** -> [FULL UPLOAD] -> 4 -> 5 -> 7

**Rationale:** Phase 6 (metadata enhancement) done BEFORE full library upload to:
- Infer categories for 496 "unknown" files (~28% of library)
- Upload with enriched metadata from day one
- Avoid re-uploading 1,721 files just to update metadata
- Better search filtering quality from the start

| Phase | Plans Complete | Status | Completed |
|-------|---------------|--------|-----------|
| 1. Foundation | 3/3 | Complete | 2026-02-15 |
| 2. Upload Pipeline | 4/4 | Complete | 2026-02-16 |
| 3. Search & CLI | 3/3 | Complete | 2026-02-16 |
| 6. AI-Powered Metadata | 5/5 | Complete | 2026-02-16 |
| 6.1. Entity Extraction | 2/2 | Complete | 2026-02-16 |
| **6.2. Enriched Upload** | **0/TBD** | **Next** | **-** |
| **[FULL UPLOAD: 1,721 files]** | **-** | **After Phase 6.2** | **-** |
| 4. Quality Enhancements | 0/TBD | Deferred | - |
| 5. Incremental Updates | 0/TBD | Deferred | - |
| 7. Interactive TUI | 0/TBD | Deferred | - |
