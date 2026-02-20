# Architecture Documentation

This directory contains technical documentation for the Objectivism Library semantic search system.

## System Summary

A semantic search engine over 1,721 Objectivist philosophy texts (~700 lecture transcripts, ~800 other documents). Files are indexed in Google Gemini File Search with enriched AI-generated metadata. Search queries are expanded with Objectivist terminology, results reranked by difficulty and relevance, and optionally synthesized into a cited answer.

## Contents

| File | Description |
|------|-------------|
| [system-overview.md](system-overview.md) | High-level system design, tech stack, external dependencies, key decisions |
| [data-pipeline.md](data-pipeline.md) | Complete data flow: scan → metadata → upload → search → display |
| [module-map.md](module-map.md) | Module responsibilities and key file paths |
| [database-schema.md](database-schema.md) | SQLite schema V6 — all tables, columns, relationships, migration history |

## At a Glance

```
Local Machine                    Gemini API              Mistral API
┌─────────────────────┐          ┌──────────────┐        ┌────────────┐
│ SQLite (library.db) │◄────────►│ File Search  │        │ Batch API  │
│ .txt files (local)  │          │ Store        │        │ (metadata) │
│ CLI (Typer + Rich)  │◄────────►│ Flash model  │◄──────►│            │
└─────────────────────┘          └──────────────┘        └────────────┘
```

## Phase Completion Status

| Phase | Focus | Status |
|-------|-------|--------|
| 1: Foundation | SQLite schema, file scanning | Complete |
| 2: Upload Pipeline | Reliable upload with rate limiting | Complete |
| 3: Search & CLI | Semantic search, browse, filter | Complete |
| 6: AI Metadata | Mistral-powered 4-tier metadata | Complete |
| 6.1: Entity Extraction | Person name recognition | Complete |
| 6.2: Enriched Upload | Upload with AI metadata | Complete |
| 4: Quality Enhancements | Reranking, synthesis, sessions | In Progress |
| 5: Incremental Updates | Change detection, offline mode | Planned |
| 7: Interactive TUI | Textual terminal UI | Planned |

---

_Last updated: Phase 4 — Session manager, reranking, synthesis, query expansion_
