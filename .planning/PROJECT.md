# Objectivism Library Semantic Search

## What This Is

A semantic search system for a 1,749-file Objectivism Library (112 MB) that enables deep conceptual research and learning through meaning-based queries, preserved pedagogical metadata, and automated synthesis generation. The system uses Google's Gemini File Search API to make philosophical wisdom accessible through natural language.

## Current Milestone: v2.0 — Gemini File Lifecycle FSM

**Goal:** Implement a formal finite state machine governing every file's Gemini lifecycle so that `[Unresolved file #N]` never appears in search results — permanently, not just after a manual store-sync.

**Target features:**
- Store migration: delete `objectivism-library-test`, create permanent `objectivism-library`
- DB schema: `gemini_store_doc_id`, `gemini_state`, `gemini_state_updated_at` columns
- `scripts/check_stability.py` — 6-assertion stability instrument (exit 0/1/2)
- Hand-rolled or library FSM (async-compatible, validated by Wave 1)
- Write-ahead intent pattern extended for two-API-call transitions (Wave 2)
- `_reset_existing_files()` fixed to delete store documents, not just raw files
- FSM as the sole authorized path for all gemini-related state mutations
- Full library upload of ~1,748 files through FSM-managed pipeline (Wave 8)

**Definition of done:** Run a search in the TUI. Every citation shows a real file name. No `[Unresolved file #N]`. Ever.

---

## Core Value

Three equally critical pillars that cannot be compromised:

1. **Semantic search quality** - Finding content by concept and meaning, not just keyword matching
2. **Metadata preservation** - Maintaining the library's pedagogical structure (Year/Quarter/Week, difficulty levels, topic hierarchies) as searchable dimensions
3. **Incremental updates** - Efficiently tracking and updating only new/changed content without re-uploading the entire library

## Requirements

### Validated

(None yet — ship to validate)

### Active

**Library Scanning & Metadata**
- [ ] Scan library directory structure and extract metadata from folder hierarchies
- [ ] Parse Course/Year/Quarter/Week organization patterns
- [ ] Extract metadata from filenames (dates, topics, instructors)
- [ ] Infer difficulty levels, prerequisites, and relationships
- [ ] Generate rich metadata for each file (20-30 fields per file)

**State Management & Tracking**
- [ ] SQLite database to track upload state (file path, hash, upload timestamp, Gemini file ID)
- [ ] Detect new files since last upload
- [ ] Detect modified files (content hash comparison)
- [ ] Detect deleted files and clean up Gemini references
- [ ] Reconciliation workflow to sync local state with Gemini File Search

**Upload Pipeline**
- [ ] Upload files to Gemini with rate limiting (0.5-1s delays)
- [ ] Batch processing: upload all files first, then add to store in chunks of ~100
- [ ] Attach metadata to each uploaded file
- [ ] Resume capability if upload interrupted
- [ ] Progress tracking and reporting
- [ ] Handle API errors gracefully with retries

**Semantic Search**
- [ ] Natural language concept-based search
- [ ] Metadata filters (course, year, quarter, difficulty, topic, branch)
- [ ] Structural navigation (browse by course, year, quarter)
- [ ] Cross-reference discovery (find related discussions)
- [ ] Results with citations and context

**Advanced Query Features**
- [ ] Concept evolution tracking (show how concepts develop from intro → advanced)
- [ ] Filtered searches combining semantic + structural queries
- [ ] Prerequisite chain discovery
- [ ] Find related content across courses

**Synthesis Generation**
- [ ] Generate comprehensive synthesis documents from multiple sources
- [ ] Include proper citations with source file references
- [ ] Organize by themes automatically
- [ ] Export as markdown with table of contents

### Out of Scope

- Visual concept mapping / graph visualization — defer to v2
- Spaced repetition integration — defer to v2
- Note-taking system integration — defer to v2
- Web interface / GUI — v1 is CLI-only
- Multi-user support — personal use only
- Real-time sync — manual trigger for updates
- Support for non-.txt file formats — text only for v1

## Context

**Library Details:**
- Location: `/Volumes/U32 Shadow/Objectivism Library`
- Size: 1,749 text files, 112 MB total
- Organization: Hierarchical structure with Courses (Year/Quarter/Week), Books (chapters), MOTM sessions, Podcasts, etc.
- Content: Lecture transcripts, course materials, book chapters focused on Objectivist philosophy

**Use Case:**
Personal research, study, and learning tool. Primary activities include:
- Deep conceptual research across the library
- Tracing concept evolution through curriculum progression
- Finding prerequisites and related discussions
- Generating synthesis documents for comprehensive understanding

**Starting Point:**
- Comprehensive documentation exists (README, IMPLEMENTATION_PLAN, METADATA_SCHEMA, etc.)
- Reference code exists but starting fresh with clean implementations
- Codebase mapped in `.planning/codebase/`

## Constraints

**API & Cost:**
- **Storage**: 112 MB uses only 11% of 1GB free tier (safe)
- **Indexing Cost**: ~$4.20 one-time fee (requires Pay-As-You-Go billing account)
- **Rate Limits**: Must add 0.5-1s delays between file uploads to avoid 429 errors
- **Batching**: Upload files individually first, then add to store in chunks of ~100

**Data Retention:**
- **Critical**: Raw uploaded files auto-delete after 48 hours
- **Solution**: Indexed data in File Search store persists indefinitely
- **Implication**: SQLite state tracking must record Gemini file IDs, not rely on raw files existing

**Technical:**
- **Tech Stack**: Python (required)
- **File Format**: .txt files only for v1
- **Performance**: Initial upload ~3-6 hours for 1,749 files

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Start fresh (not building on existing code) | Clean implementations based on solid documentation | — Pending |
| SQLite for state management | Efficient change detection, atomic writes, no external dependencies | — Pending |
| Three-phase pipeline (scan → upload → query) | Clear separation of concerns, resumable at each phase | — Pending |
| CLI-first (no GUI for v1) | Faster to build, meets personal use case | — Pending |
| Batch upload strategy (all files → chunk to store) | Respects API design and rate limits | — Pending |

---
*Last updated: 2026-02-19 after v2.0 milestone initialization*
