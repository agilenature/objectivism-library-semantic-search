# System Overview

## What the System Is

The Objectivism Library Semantic Search system indexes 1,721 Objectivist philosophy texts into a semantic search engine. The library consists primarily of lecture transcripts from ARI (Ayn Rand Institute) courses, along with books, Q&A sessions, and other materials. Files are organized hierarchically by category, course, year, and week.

The system enables users to search by meaning (not keywords), filter by rich metadata (course, difficulty, topic), get synthesized answers with citations, and track research sessions.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| CLI | Typer (Typer app with sub-apps), Rich (terminal UI) |
| Database | SQLite (WAL mode, schema V6) |
| Vector Search | Google Gemini File Search API |
| LLM | Google Gemini Flash (reranking, synthesis, suggestions) |
| AI Metadata | Mistral AI via Batch API |
| Entity Matching | RapidFuzz (fuzzy string matching) |
| YAML | PyYAML (glossary) |
| HTTP | google-genai SDK, mistralai SDK |
| Key Storage | keyring (OS system keyring) |

## External Dependencies

### Gemini File Search Store

Files are uploaded to a Gemini File Search store (named `objectivism-library-test`). This is Google's managed semantic search service — it handles embedding, indexing, and vector retrieval. The store supports:
- Custom metadata attached to each file (used for filtering)
- AIP-160 filter expressions for server-side metadata filtering
- Grounding metadata in responses (passage text + source file ID)

**48-hour TTL:** Gemini File Search files expire after 48 hours and must be re-uploaded. This is tracked via `remote_expiration_ts` in SQLite.

### Mistral Batch API

Used for AI metadata extraction (4-tier schema: category, difficulty, topics, aspects, descriptions). Batch API provides:
- 50% cost savings over synchronous API
- Zero rate limiting (all files submitted at once, processed at Mistral's pace)
- Async polling (typically 20–60 minutes for 700+ files)

### System Keyring

API keys are stored exclusively in the OS system keyring (macOS Keychain, Linux Secret Service, Windows Credential Manager). Never in environment variables or config files.

| Service | Key | Usage |
|---------|-----|-------|
| `objlib-gemini` | `api_key` | Gemini File Search + Flash model |
| `objlib-mistral` | `api_key` | Mistral Batch API for metadata |

## System Boundaries

```
╔══════════════════════════════════════╗
║           Local Machine              ║
║                                      ║
║  /Volumes/U32 Shadow/Objlib Library  ║
║           (1,721 .txt files)         ║
║                │                     ║
║         SQLite database              ║
║         (data/library.db)            ║
║                │                     ║
║     CLI (Typer + Rich + objlib)      ║
║                │                     ║
╚══════════════════════════════════════╝
                 │
         ┌───────┴───────┐
         │               │
╔════════╧═════╗  ╔══════╧══════╗
║  Gemini API  ║  ║ Mistral API ║
║              ║  ║             ║
║ File Search  ║  ║ Batch API   ║
║ Flash model  ║  ║ (metadata)  ║
╚══════════════╝  ╚═════════════╝
```

**Disk-dependent operations:** `scan`, `upload`, `entities extract`
**Always available (disk optional):** `search`, `browse`, `filter`, `view` (metadata only), `session`, `glossary`

## Key Design Decisions

### Why Gemini File Search?

Gemini File Search handles embedding, indexing, and retrieval as a managed service — no local vector database to maintain. It supports custom metadata filtering (AIP-160 syntax), which allows combining semantic search with structured metadata queries (e.g., "find conceptually similar passages, but only from OPAR, difficulty intermediate").

### Why SQLite?

The library metadata (file paths, content hashes, upload status, AI-extracted metadata, entity mentions, sessions) fits comfortably in SQLite. It requires no server, runs on any machine, and provides full SQL query flexibility. JSON columns store flexible metadata blobs. Schema migrations are handled via `PRAGMA user_version` and `ALTER TABLE ADD COLUMN` with try/except.

### Why Enriched Metadata?

Raw Gemini File Search works on file content only. By prepending an AI-generated analysis header (category, difficulty, 8 primary topics, key aspects, summaries) to each file before upload, Gemini can filter and rank results using richer semantic signals. This is the core value of Phase 6 (Mistral metadata extraction) + Phase 6.2 (enriched upload).

### Metadata-First Strategy

Phase 6 (AI metadata) was executed before Phase 4 (quality enhancements) and before full library upload. This ensures all 1,721 files are uploaded with enriched metadata from day one, avoiding a costly re-upload cycle.

### Append-Only Sessions

Research sessions use an append-only event log. Events can be added but never modified or deleted. This preserves research integrity and enables reliable audit trails.

---

_Last updated: Phase 4 — Session manager, reranking, synthesis, query expansion_
