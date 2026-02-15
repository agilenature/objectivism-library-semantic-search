# Requirements: Objectivism Library Semantic Search

**Defined:** 2026-02-15
**Core Value:** Three equally critical pillars - semantic search quality, metadata preservation, incremental updates

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Foundation & State Management

- [ ] **FOUN-01**: SQLite database with WAL mode for state tracking (file hashes, upload status, metadata, Gemini IDs)
- [ ] **FOUN-02**: File scanner with recursive discovery of library directory structure
- [ ] **FOUN-03**: Hash-based change detection (SHA-256 content hashing for each file)
- [ ] **FOUN-04**: Metadata extraction from hierarchical folder structure (Course/Year/Quarter/Week patterns)
- [ ] **FOUN-05**: Metadata extraction from filenames (dates, topics, instructors, session numbers)
- [ ] **FOUN-06**: Idempotency keys using content hashes for deduplication
- [ ] **FOUN-07**: Upload timestamp tracking to prevent 48-hour expiration issues
- [ ] **FOUN-08**: Embedding model version tracking in state schema
- [ ] **FOUN-09**: Status tracking with atomic state transitions (pending -> uploading -> uploaded/failed)

### Upload Pipeline

- [ ] **UPLD-01**: Gemini File Search API client wrapper using google-genai SDK (v1.63.0+)
- [ ] **UPLD-02**: Async batch upload with rate limiting (5-10 concurrent uploads via Semaphore)
- [ ] **UPLD-03**: Exponential backoff with jitter using tenacity library
- [ ] **UPLD-04**: Operation polling for indexing completion status
- [ ] **UPLD-05**: Per-file status updates with idempotent retry (skip already-succeeded files)
- [ ] **UPLD-06**: Circuit breaker pattern to prevent rate limit cascades (reduce rate 50% after 5% 429 errors)
- [ ] **UPLD-07**: Batch processing orchestrator (100-200 files per batch, 36-hour completion deadline)
- [ ] **UPLD-08**: Attach rich metadata to each uploaded file (20-30 fields)
- [ ] **UPLD-09**: Progress tracking and reporting with Rich progress bars
- [ ] **UPLD-10**: Resume capability from any interruption point using SQLite state

### Semantic Search

- [ ] **SRCH-01**: Semantic search via Gemini File Search API (vector similarity)
- [ ] **SRCH-02**: Keyword/full-text search capabilities
- [ ] **SRCH-03**: Hybrid search combining semantic + keyword with unified ranking
- [ ] **SRCH-04**: Metadata filtering (author, course, year, quarter, difficulty, topic, branch)
- [ ] **SRCH-05**: Structural navigation (browse by course, year, quarter without query)
- [ ] **SRCH-06**: Source citation with passage-level attribution
- [ ] **SRCH-07**: Result context/preview showing relevant text excerpts
- [ ] **SRCH-08**: Cross-reference discovery (find related discussions automatically)

### Query Interface

- [ ] **INTF-01**: CLI interface using Typer with type-hint-driven commands
- [ ] **INTF-02**: Rich terminal formatting (tables, panels, progress bars)
- [ ] **INTF-03**: Search command with semantic query input
- [ ] **INTF-04**: Filter command with metadata-based filtering
- [ ] **INTF-05**: Browse command for structural navigation without query
- [ ] **INTF-06**: Response formatter mapping Gemini file refs to human-readable source names
- [ ] **INTF-07**: Display results with relevance scores and source citations

### Advanced Features

- [ ] **ADVN-01**: Concept evolution tracking (show how concepts develop from intro -> advanced)
- [ ] **ADVN-02**: Cross-encoder reranking for top-50 -> top-10 precision improvement
- [ ] **ADVN-03**: Multi-document synthesis with LLM (synthesized answers from 5-10 passages)
- [ ] **ADVN-04**: Inline citation format (every claim traces to source passage with quote)
- [ ] **ADVN-05**: Query expansion for philosophical terminology (synonym mapping)
- [ ] **ADVN-06**: Difficulty-aware result ordering (surface introductory explanations first for learning)
- [ ] **ADVN-07**: Saved searches / research sessions with resume capability

### Incremental Updates

- [ ] **INCR-01**: Change detection via content hash comparison
- [ ] **INCR-02**: Incremental upload (only upload new/modified files)
- [ ] **INCR-03**: Orphan cleanup (delete old chunks when document re-processed)
- [ ] **INCR-04**: Force re-process flag for manual override
- [ ] **INCR-05**: Sync command to detect and upload changes

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced Intelligence

- **ADVN2-01**: Knowledge graph of philosophical concepts with entity extraction
- **ADVN2-02**: Contradiction and tension detection across sources
- **ADVN2-03**: Reading list / learning path generation (ordered sequences intro -> advanced)
- **ADVN2-04**: Hierarchical chunk indexing with query routing (summaries vs details)
- **ADVN2-05**: Domain-tuned embeddings fine-tuned on corpus for better concept similarity

### Visualization & Integration

- **VIZ-01**: Visual concept mapping / graph visualization
- **INTG-01**: Spaced repetition integration
- **INTG-02**: Note-taking system integration (Obsidian, Roam)
- **INTG-03**: Export to knowledge graph formats

### Interface Enhancements

- **UI-01**: Web interface (currently CLI-only)
- **UI-02**: Interactive research workspace with side-by-side comparison
- **UI-03**: Batch export of synthesis documents

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| "Chat with your library" as primary interface | Obscures provenance, encourages trust over verification, hallucination risk; semantic search with citations is better for research |
| Over-retrieval (top-50+ results by default) | LLM position bias causes middle results to be ignored; top-10-20 with reranking is optimal |
| Real-time web search integration | Pollutes curated corpus with unvetted content; this is a closed-corpus tool |
| Automatic summarization of entire documents | Loses argumentative structure that IS the philosophical content |
| Multi-user collaboration features | Single-user personal research tool; collaboration adds massive complexity for zero value |
| Support for non-.txt file formats in v1 | Text files only for v1; PDF/EPUB defer to v2 |
| Docker containerization | Single-machine Python CLI adds complexity without benefit |
| LangChain/LlamaIndex integration | Massive dependency trees that hide Gemini-specific features; unnecessary for single-provider system |
| Separate vector database (ChromaDB, Pinecone, Weaviate) | Gemini File Search manages vector storage internally; separate DB creates duplicate infrastructure |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FOUN-01 | Phase 1: Foundation | Pending |
| FOUN-02 | Phase 1: Foundation | Pending |
| FOUN-03 | Phase 1: Foundation | Pending |
| FOUN-04 | Phase 1: Foundation | Pending |
| FOUN-05 | Phase 1: Foundation | Pending |
| FOUN-06 | Phase 1: Foundation | Pending |
| FOUN-07 | Phase 1: Foundation | Pending |
| FOUN-08 | Phase 1: Foundation | Pending |
| FOUN-09 | Phase 1: Foundation | Pending |
| UPLD-01 | Phase 2: Upload Pipeline | Pending |
| UPLD-02 | Phase 2: Upload Pipeline | Pending |
| UPLD-03 | Phase 2: Upload Pipeline | Pending |
| UPLD-04 | Phase 2: Upload Pipeline | Pending |
| UPLD-05 | Phase 2: Upload Pipeline | Pending |
| UPLD-06 | Phase 2: Upload Pipeline | Pending |
| UPLD-07 | Phase 2: Upload Pipeline | Pending |
| UPLD-08 | Phase 2: Upload Pipeline | Pending |
| UPLD-09 | Phase 2: Upload Pipeline | Pending |
| UPLD-10 | Phase 2: Upload Pipeline | Pending |
| SRCH-01 | Phase 3: Search & CLI | Pending |
| SRCH-02 | Phase 3: Search & CLI | Pending |
| SRCH-03 | Phase 3: Search & CLI | Pending |
| SRCH-04 | Phase 3: Search & CLI | Pending |
| SRCH-05 | Phase 3: Search & CLI | Pending |
| SRCH-06 | Phase 3: Search & CLI | Pending |
| SRCH-07 | Phase 3: Search & CLI | Pending |
| SRCH-08 | Phase 3: Search & CLI | Pending |
| INTF-01 | Phase 3: Search & CLI | Pending |
| INTF-02 | Phase 3: Search & CLI | Pending |
| INTF-03 | Phase 3: Search & CLI | Pending |
| INTF-04 | Phase 3: Search & CLI | Pending |
| INTF-05 | Phase 3: Search & CLI | Pending |
| INTF-06 | Phase 3: Search & CLI | Pending |
| INTF-07 | Phase 3: Search & CLI | Pending |
| ADVN-01 | Phase 4: Quality Enhancements | Pending |
| ADVN-02 | Phase 4: Quality Enhancements | Pending |
| ADVN-03 | Phase 4: Quality Enhancements | Pending |
| ADVN-04 | Phase 4: Quality Enhancements | Pending |
| ADVN-05 | Phase 4: Quality Enhancements | Pending |
| ADVN-06 | Phase 4: Quality Enhancements | Pending |
| ADVN-07 | Phase 4: Quality Enhancements | Pending |
| INCR-01 | Phase 5: Incremental Updates | Pending |
| INCR-02 | Phase 5: Incremental Updates | Pending |
| INCR-03 | Phase 5: Incremental Updates | Pending |
| INCR-04 | Phase 5: Incremental Updates | Pending |
| INCR-05 | Phase 5: Incremental Updates | Pending |

**Coverage:**
- v1 requirements: 46 total
- Mapped to phases: 46
- Unmapped: 0

---
*Requirements defined: 2026-02-15*
*Last updated: 2026-02-15 after roadmap creation (phase names added to traceability, count corrected to 46)*
