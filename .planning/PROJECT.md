# Objectivism Library Semantic Search

## What This Is

A semantic search system for a 1,749-file Objectivism Library (112 MB) that enables deep conceptual research and learning through meaning-based queries, preserved pedagogical metadata, and automated synthesis generation. The system uses Google's Gemini File Search API with a formal finite state machine governing every file's lifecycle. Every citation in every search result resolves to a real file name — permanently.

## Shipped: v2.0 — Gemini File Lifecycle FSM

**Shipped:** 2026-02-27

All 1,749 library files are indexed in `objectivism-library` (Gemini File Search) with:
- FSM-managed upload pipeline (UNTRACKED → UPLOADING → PROCESSING → INDEXED)
- Identity headers injected into indexed content for reliable per-file retrievability
- CRAD discrimination phrases for 63 semantically-homogeneous files
- Reactive TUI with RxPY observable pipeline (debounce, switch_map, combine_latest)
- Uniform RxPY async paradigm across all modules outside `tui/`
- `check_stability.py` — 7-assertion stability instrument (60/60 files STABLE)

---

## Core Value

Three equally critical pillars that cannot be compromised:

1. **Semantic search quality** — Finding content by concept and meaning, not just keyword matching; every citation resolves to a real file
2. **Metadata preservation** — Maintaining the library's pedagogical structure (Year/Quarter/Week, difficulty, topic hierarchies) as searchable dimensions; AI-enriched metadata is sacred
3. **Incremental updates** — Efficiently tracking and updating only new/changed content without re-uploading the entire library; FSM manages all state transitions

## Requirements

### Validated

- ✓ **MIGR-01/02/03/04**: Store migration with pre-flight check, permanent store created, V9 schema, state reset — v2.0
- ✓ **STAB-01/02/03/04**: `check_stability.py` 7-assertion instrument (expanded from 6), exit codes 0/1/2, mandatory gate — v2.0
- ✓ **FSM-01**: python-statemachine 2.6.0 selected with affirmative concurrent evidence — v2.0
- ✓ **FSM-02**: Write-ahead intent pattern; RecoveryCrawler; every crash point has tested recovery — v2.0
- ✓ **FSM-03**: `gemini_state` plain string enum in DB; status column dropped; V11 migration — v2.0
- ✓ **FSM-04**: All gemini-related state mutations go through FSM transitions — v2.0
- ✓ **FSM-05**: delete_store_document() called before delete_file() in reset operations — v2.0
- ✓ **VLID-01 through VLID-07**: All 7 validation wave gates PASSED — v2.0
- ✓ **PIPE-01**: `[Unresolved file #N]` does not appear in any TUI search result — v2.0
- ✓ **PIPE-02**: STABLE at T=0/T+4h/T+24h/T+36h (confirmed multiple times, last: 60/60 2026-02-27) — v2.0
- ✓ **TUI-09**: top_k=20, --top-k flag, citation count, rank display, scroll hints — v2.0
- ✓ **TUI-RX-01/02/03**: RxPY TUI reactive pipeline replacing manual debounce/generation-tracking — v2.0
- ✓ **ASYNC-RX-01/02/03**: RxPY codebase-wide async migration; 0 asyncio primitives outside tui/ — v2.0
- ✓ Scan library, extract metadata, SQLite state management, detect new/modified/deleted files — v1.0
- ✓ Upload pipeline with rate limiting, batch processing, resume capability, retries — v1.0
- ✓ Semantic search, metadata filters, structural navigation, citations — v1.0
- ✓ Concept evolution tracking, filtered search, prerequisite discovery — v1.0
- ✓ Synthesis document generation with citations — v1.0
- ✓ AI-powered metadata (primary_topics, topic_aspects, summaries, entity extraction) — v1.0
- ✓ Interactive TUI (Textual-based) with split-pane views, session management — v1.0

### Active (v3.0 candidates)

- [ ] STALE-01/02: Automated STALE detection when content hashes change
- [ ] CONC-01: Concurrency lockfile preventing double-uploads
- [ ] _reset_existing_files() direct fix in orchestrator.py: call delete_store_document() before delete_file()
- [ ] Remove tenacity from pyproject.toml (zero imports in src/ but package not yet removed)
- [ ] services/session.py: 5 remaining asyncio.to_thread calls (out of Phase 18 scope)

### Out of Scope

- Visual concept mapping / graph visualization
- Spaced repetition integration
- Note-taking system integration
- Web interface / GUI — CLI + TUI covers all use cases
- Multi-user support — personal use only
- Non-.txt file format support (epub/pdf/html/docx marked 'skipped' in pipeline)

## Context

**Library:**
- Location: `/Volumes/U32 Shadow/Objectivism Library`
- Size: 1,749 text files, 112 MB
- Series: ITOE, ITOE AT, ITOE AT OH, ITOE OH, OL, MOTM (468), Episodes (333), Books, Other
- Content: Lecture transcripts, course materials focused on Objectivist philosophy

**Codebase (post v2.0):**
- ~25,000 LOC Python
- Tech stack: Python 3.13, SQLite (aiosqlite), Gemini File Search API, Mistral Batch API, Textual TUI, RxPY 3.2.0, Rich CLI (Typer)
- Key modules: `upload/` (FSM pipeline), `extraction/` (Mistral batch), `search/` (Gemini queries), `tui/` (Textual app), `services/` (coordination layer)
- Test suite: 476 tests, 37 warnings (all from RxPY 3.2.0 internals — utcnow deprecation)

**Use Case:**
Personal research, study, and learning. Primary activities:
- Deep conceptual research across the full library
- Tracing concept evolution through curriculum progression
- Finding related discussions across series and courses
- Generating synthesis documents for comprehensive understanding

## Constraints

**API & Cost:**
- Storage: 112 MB uses 11% of 1 GB free tier (safe)
- Rate Limits: Handled by RxPY dynamic_semaphore + make_retrying_observable (429 backoff)
- Gemini store documents persist indefinitely (raw files expire 48h — irrelevant for indexed content)
- identity headers injected at upload time ensure per-file retrievability

**Data:**
- AI-enriched metadata (primary_topics, topic_aspects, summaries, entity extractions) is **SACRED** — never re-derive, never reset
- `gemini_state` persists as plain string enum — never library-native serialization
- DB schema at V12 (CRAD tables: series_genus, file_discrimination_phrases)

**Technical:**
- .txt and .md files only in upload pipeline (epub/pdf/html/docx marked skipped)
- Performance: full library upload ~7h25min at c=10 concurrency

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Start fresh (not building on existing code) | Clean implementations based on solid documentation | ✓ Good |
| SQLite for state management | Efficient change detection, atomic writes, no external deps | ✓ Good |
| Three-phase pipeline (scan → upload → query) | Clear separation of concerns, resumable at each phase | ✓ Good |
| CLI-first (no GUI for v1) | Faster to build, meets personal use case | ✓ Good |
| python-statemachine 2.6.0 for FSM | Affirmative concurrent async evidence (Phase 9) | ✓ Good |
| gemini_store_doc_id stores suffix only (12-char prefix = file resource ID) | Avoids store name prefix dependency | ✓ Good |
| BOOK_SIZE_BYTES = 830,000 | Structural routing threshold for AI extraction | ✓ Good |
| Identity headers in indexed content | Enables per-file targeted queries; resolves A7 failures | ✓ Good |
| S4 (rarest aspects, no preamble) + CRAD for S1-deaf files | Zero misses at zero tolerance | ✓ Good |
| RxPY AsyncIOScheduler + Future-based subscription | Prevents .run() deadlock in async contexts | ✓ Good |
| ops.map(factory).pipe(ops.merge(max_concurrent=N)) | RxPY 3.x idiom for bounded concurrency | ✓ Good |
| Two-signal shutdown_gate (stop_accepting + force_kill) | Graceful shutdown without stuck state | ✓ Good |
| Write-ahead intent pattern for OCC transitions | Crash-safe two-API-call sequences | ✓ Good |
| store-sync role: scheduled + targeted post-run | 5% silent failure rate justifies scheduled reconciliation | ✓ Good |
| top_k=20 across entire search pipeline | 4× more results than server default ~5 | ✓ Good |

---
*Last updated: 2026-02-27 after v2.0 milestone completion*
