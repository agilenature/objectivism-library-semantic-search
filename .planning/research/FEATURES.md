# Feature Research

**Domain:** Semantic search and document intelligence for philosophical research (closed corpus)
**Researched:** 2026-02-15
**Confidence:** HIGH

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Semantic search (vector similarity)** | Core product promise. Researchers expect to search by meaning, not just keywords. Without this, it's just grep. | MEDIUM | Requires embedding model selection, vector storage, and similarity scoring. Foundation everything else builds on. |
| **Keyword/full-text search** | Philosophical terminology is precise. "Rational self-interest" must find that exact phrase, not just conceptually similar passages. Researchers switch between semantic and exact modes constantly. | LOW | BM25 via SQLite FTS5 or similar. Must work alongside vector search, not replace it. |
| **Hybrid search (semantic + keyword combined)** | Neither pure semantic nor pure keyword suffices for philosophical research. Users expect a single search that handles both conceptual and terminological queries without manual mode-switching. | MEDIUM | Requires score fusion (e.g., Reciprocal Rank Fusion) to merge vector and keyword results into one ranked list. |
| **Metadata filtering** | Researchers need to scope searches: "find discussions of virtue in introductory courses only" or "only Peikoff lectures." Without filtering, every search returns noise from the full 1,749-file corpus. | LOW | Filter by author, course, document type, difficulty level, topic. Pre-filter before vector search for performance. |
| **Source citation with passage-level attribution** | Researchers must verify every claim against source text. Generic "from document X" is insufficient -- need exact passage references. Without this, the system is academically useless. | MEDIUM | Store chunk-to-source mappings. Return source document, section, and ideally page/paragraph reference with every result. |
| **Result ranking and relevance scoring** | Users need to know which results are most relevant. Unranked or poorly ranked results waste researcher time on irrelevant material. | LOW | Cosine similarity scores for vector results, BM25 scores for keyword. Display relevance indicators so users can prioritize reading. |
| **Document chunking that preserves argument structure** | Philosophical arguments span paragraphs. Fixed-size chunking splits arguments mid-sentence, making retrieved chunks incoherent. Users expect retrieved passages to be self-contained and meaningful. | MEDIUM | Semantic chunking (topic-boundary detection) or structure-aware chunking (by section/heading). Chunks must be large enough to preserve argumentative flow (~512-2048 tokens). |
| **Basic query interface (CLI or simple UI)** | Users need a way to issue queries and read results. Even a CLI is acceptable for a personal research tool, but there must be a usable interface. | LOW | Start with CLI. Can be a simple terminal interface or basic web UI. |
| **Persistent index (don't re-embed on every query)** | Re-embedding 1,749 documents per query is unacceptable. Users expect instant search after initial indexing. | LOW | Store embeddings in vector DB (SQLite + vec extension, or Chroma, etc.). One-time indexing with incremental updates. |
| **Search result context/preview** | Users need enough surrounding text to judge relevance before opening the full document. A title alone is not enough. | LOW | Show the matching chunk plus a few sentences of surrounding context. Highlight matching terms where possible. |

### Differentiators (Competitive Advantage)

Features that set the product apart. Not required, but valuable.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Concept evolution tracking** | Trace how a philosophical idea develops from introductory presentations through advanced elaborations. E.g., track "concept formation" from OPAR Ch.2 through advanced epistemology lectures. No existing tool does this for a closed philosophical corpus. | HIGH | Requires temporal/difficulty metadata, cross-document concept linking, and a way to visualize concept trajectories. Depends on: metadata filtering, knowledge graph. |
| **Multi-document synthesis generation** | Ask a question, get an answer synthesized from multiple sources with citations. E.g., "What is the Objectivist view of rights?" returns a synthesized answer drawing from 5-10 relevant passages across different works. | HIGH | RAG pipeline: retrieve relevant chunks, pass to LLM with synthesis prompt, require inline citations. Depends on: semantic search, citation tracking, LLM integration. |
| **Reranking with cross-encoder** | Initial vector retrieval returns approximate matches. A cross-encoder reranker (e.g., ms-marco-MiniLM) scores each candidate against the query with much higher precision, surfacing the truly relevant results. | MEDIUM | Two-stage retrieval: fast vector search (top-50), then cross-encoder reranking (top-10). Significant quality improvement for moderate compute cost. |
| **Faceted navigation / browse mode** | Let researchers explore the corpus by facets (author, course, topic, difficulty) without a search query. Supports serendipitous discovery -- "What does the advanced epistemology course cover?" | MEDIUM | Requires rich metadata and aggregation queries. More of a UI feature than a search feature. Depends on: metadata filtering. |
| **Difficulty-aware result ordering** | For a given concept, surface introductory explanations first for learning, or advanced treatments first for research. Respects the pedagogical structure of the Objectivism Library (intro -> intermediate -> advanced). | LOW | Metadata field for difficulty/level on each document. Sort or boost results by difficulty. Depends on: metadata filtering. |
| **Query expansion for philosophical terminology** | Automatically expand "egoism" to also search "rational self-interest," "selfishness (Rand's usage)," "self-interest." Handles the terminological diversity of philosophical discourse. | MEDIUM | Synonym/concept mapping specific to Objectivist terminology. Can be a static mapping or LLM-generated expansions. Depends on: domain knowledge of Objectivist terminology. |
| **Contradiction and tension detection** | Flag when retrieved sources present conflicting or evolving positions on the same topic. E.g., noting that Rand's treatment of "emergencies" in ethics evolved across her writing. | HIGH | Requires LLM analysis of retrieved passages for logical consistency. Valuable for philosophical research where tracking intellectual development matters. Depends on: multi-document synthesis. |
| **Knowledge graph of philosophical concepts** | Explicit graph of concepts, thinkers, and relationships (influences, critiques, develops, contradicts). Enables queries like "What concepts does Peikoff's epistemology build on?" | HIGH | Requires entity extraction, relationship annotation (possibly LLM-assisted), and graph storage/query. Major undertaking but uniquely powerful for philosophical research. |
| **Reading list / learning path generation** | Given a concept the researcher wants to understand, generate an ordered reading path from introductory to advanced materials. Leverages the pedagogical structure of the library. | MEDIUM | Combine metadata (difficulty, topic, prerequisites) with graph relationships to generate ordered sequences. Depends on: metadata filtering, difficulty-aware ordering. |
| **Saved searches and research sessions** | Let the researcher save queries, bookmark results, and build research threads over multiple sessions. Personal research is iterative, not one-shot. | MEDIUM | Persistence layer for user state. Not complex technically, but a significant UX feature for sustained research. |
| **Domain-tuned embeddings** | Fine-tune embedding model on the Objectivism Library corpus so that philosophical concepts are encoded with domain-appropriate similarity. "Rational self-interest" should be closer to "egoism" than to "financial self-interest." | MEDIUM | Fine-tune BAAI/bge-base-en-v1.5 or similar on the corpus using contrastive learning. 1,749 documents is enough for meaningful improvement. One-time compute cost. |
| **Hierarchical chunk indexing** | Index documents at multiple granularities: document-level summaries, section-level chunks, paragraph-level chunks. Route broad questions to summaries, specific questions to detailed chunks. | MEDIUM | Multiple index layers with query routing (LlamaIndex router pattern). Depends on: document chunking. |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create problems.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **"Chat with your library" as primary interface** | Conversational AI is trendy. Seems natural to "talk to your books." | Conversational interfaces obscure provenance, encourage trust in generated answers over source verification, and make it hard to compare multiple results. Philosophical research requires seeing sources, not chatbot responses. LLM hallucination is especially dangerous for philosophy where precision matters. | Search-first interface with optional synthesis. Show retrieved passages prominently; generated summaries are secondary and always accompanied by citations. |
| **Over-retrieval (top-50+ results by default)** | "More context = better answers." Feels thorough. | Language models exhibit position bias (middle results get ignored). More context = more noise, higher latency, higher cost, and paradoxically worse answers. For 1,749 documents, top-50 could be 3% of the corpus -- that's not search, it's browsing. | Retrieve top-20, rerank to top-5-10. Quality over quantity. Let users request "more results" explicitly. |
| **Real-time web search integration** | "Combine library search with internet sources." Seems comprehensive. | Mixes authoritative closed-corpus results with unvetted web content. For Objectivism research, web results include mischaracterizations, hostile critiques, and inaccurate summaries. Pollutes the curated corpus. | Keep corpus search and external search strictly separate. If web search is offered, clearly label and segregate results. |
| **Automatic summarization of entire documents** | "Give me the summary of Atlas Shrugged." Saves time. | Summarizing philosophical texts loses the argumentation structure that IS the content. A summary of a philosophical argument is not the argument -- it's a distortion. Encourages superficial engagement with deep material. | Provide section-level navigation and structured outlines, not reductive summaries. Let researchers navigate structure, not consume summaries. |
| **"Smart" auto-tagging with uncurated LLM-generated metadata** | Automate metadata creation. 1,749 files is a lot to tag manually. | LLM-generated philosophical categorizations are unreliable. Misclassifying a text as "epistemology" when it's "metaphysics" corrupts filtering. Errors compound silently -- researchers trust filters but get wrong results. | Use LLM-assisted tagging with mandatory human review. Semi-automated: LLM proposes, researcher confirms. Build trusted metadata gradually. |
| **Multi-user collaboration features** | "What if multiple people use this?" | This is a personal research tool for one researcher. Multi-user adds auth, permissions, conflict resolution, and social features -- massive complexity for zero value. YAGNI. | Single-user by design. If sharing is needed later, export research sessions or share the database file. |
| **Complex permission/access control** | "Some documents might be restricted." | Single-user personal research tool. Access control is overhead that solves no real problem. | All documents accessible. If copyright is a concern, handle it at the corpus curation level, not in the search system. |
| **Mobile-first or responsive UI** | "Access research on the go." | Philosophical research requires deep reading and sustained attention. Mobile is the wrong form factor. Building for mobile first compromises the desktop research experience. | Desktop-first. If mobile access is genuinely needed later, a read-only mobile view is sufficient. |
| **Real-time collaborative editing of notes/annotations** | Trendy in knowledge management tools. | Single user. No collaboration needed. Real-time sync adds websocket infrastructure, conflict resolution, and distributed state management for zero benefit. | Local-first notes and annotations. Simple file-based storage. |
| **Embedding every new model that comes out** | "Newer models have better embeddings." | Re-embedding 1,749 documents is expensive and invalidates all existing similarity relationships. Constant model chasing provides marginal improvement at high cost. Breaks reproducibility. | Choose one good model, fine-tune it on the corpus, and stick with it. Re-embed only with clear evidence of significant quality improvement. Design for model-swap capability but don't exercise it frequently. |

## Feature Dependencies

```
[Semantic Search (vector similarity)]
    |
    |--requires--> [Embedding Model Selection]
    |--requires--> [Document Chunking]
    |--requires--> [Vector Storage (persistent index)]
    |
    |--enhances--> [Hybrid Search]
    |                  |--requires--> [Keyword/Full-Text Search]
    |
    |--enhances--> [Multi-Document Synthesis]
    |                  |--requires--> [LLM Integration]
    |                  |--requires--> [Citation Tracking]
    |                  |--enhances--> [Contradiction Detection]
    |
    |--enhances--> [Reranking]

[Metadata Filtering]
    |--requires--> [Metadata Schema + Ingestion Pipeline]
    |--enhances--> [Faceted Navigation]
    |--enhances--> [Difficulty-Aware Ordering]
    |--enhances--> [Reading List Generation]

[Document Chunking]
    |--enhances--> [Hierarchical Chunk Indexing]
                       |--enhances--> [Query Routing (summary vs detail)]

[Knowledge Graph]
    |--requires--> [Entity Extraction]
    |--requires--> [Relationship Annotation]
    |--enhances--> [Concept Evolution Tracking]
    |--enhances--> [Reading List Generation]

[Domain-Tuned Embeddings]
    |--requires--> [Semantic Search (baseline working first)]
    |--enhances--> [All vector-based retrieval quality]

[Query Expansion]
    |--requires--> [Domain Terminology Mapping]
    |--enhances--> [Semantic Search]
    |--enhances--> [Hybrid Search]
```

### Dependency Notes

- **Semantic Search requires Embedding Model + Chunking + Storage:** These three are inseparable foundations. You cannot have semantic search without all three.
- **Hybrid Search requires both Semantic Search and Keyword Search:** Both retrieval modes must work independently before fusion makes sense.
- **Multi-Document Synthesis requires LLM Integration and Citation Tracking:** Synthesis without citations is hallucination. Citations without synthesis is just search. Both must exist together.
- **Concept Evolution Tracking requires Knowledge Graph:** You cannot track how ideas develop without explicit concept-to-concept and concept-to-document relationships.
- **Domain-Tuned Embeddings require a working baseline first:** Fine-tune only after you can measure improvement against the baseline. Premature optimization.
- **Reranking enhances but does not require changes to base retrieval:** Can be added as a post-processing step to any retrieval pipeline.
- **Contradiction Detection requires Multi-Document Synthesis:** Must already be retrieving and comparing multiple sources before inconsistencies can be identified.

## MVP Definition

### Launch With (v1)

Minimum viable product -- what's needed to validate that semantic search over the Objectivism Library is useful.

- [ ] **Semantic search (vector similarity)** -- Core value proposition. Must work or nothing else matters.
- [ ] **Keyword/full-text search** -- Precise terminology lookup. Philosophical research requires exact matching.
- [ ] **Hybrid search (combined ranking)** -- Single query interface combining both modes. Reduces researcher cognitive load.
- [ ] **Metadata filtering (author, course, type, difficulty)** -- Scope searches to relevant subsets. Essential for a 1,749-document corpus.
- [ ] **Document chunking (semantic or structure-aware)** -- Chunks must be coherent philosophical passages, not arbitrary text splits.
- [ ] **Persistent vector index** -- One-time embedding, instant queries thereafter.
- [ ] **Source citation (document + section reference)** -- Every result traces to source. Non-negotiable for research.
- [ ] **CLI query interface** -- Functional interface for issuing queries and reading results. No UI needed yet.
- [ ] **Result context/preview** -- Show enough text to judge relevance without opening the document.

### Add After Validation (v1.x)

Features to add once core search is working and the researcher is actively using it.

- [ ] **Reranking with cross-encoder** -- Add when initial retrieval quality feels "close but not precise enough." Significant quality jump for moderate effort.
- [ ] **Multi-document synthesis (RAG)** -- Add when the researcher wants answers, not just passages. Requires LLM integration.
- [ ] **Faceted navigation / browse mode** -- Add when the researcher wants to explore the corpus without a specific query.
- [ ] **Difficulty-aware result ordering** -- Add when pedagogical navigation becomes a real workflow (studying a concept from intro to advanced).
- [ ] **Query expansion for philosophical terms** -- Add when searches miss relevant results due to terminology variations.
- [ ] **Saved searches / research sessions** -- Add when research becomes iterative and the researcher wants to resume work.
- [ ] **Domain-tuned embeddings** -- Add when baseline quality is measurable and there's evidence domain-tuning would help. Fine-tune on the corpus.

### Future Consideration (v2+)

Features to defer until product-market fit is established.

- [ ] **Knowledge graph of philosophical concepts** -- Defer because it requires substantial entity extraction and relationship annotation effort. Build only after the simpler features prove their value.
- [ ] **Concept evolution tracking** -- Defer because it depends on the knowledge graph. High value but high complexity.
- [ ] **Contradiction and tension detection** -- Defer because it requires sophisticated LLM reasoning over multiple sources. Build on top of working synthesis.
- [ ] **Reading list / learning path generation** -- Defer because it requires rich metadata and graph relationships. Nice to have, not essential for core research.
- [ ] **Hierarchical chunk indexing with query routing** -- Defer because it requires multiple index layers and routing logic. Optimize after baseline is proven.
- [ ] **Simple web UI** -- Defer because CLI is sufficient for a single researcher. Build UI only if the CLI proves limiting for specific workflows.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Semantic search (vector) | HIGH | MEDIUM | P1 |
| Keyword/full-text search | HIGH | LOW | P1 |
| Hybrid search (fusion) | HIGH | MEDIUM | P1 |
| Metadata filtering | HIGH | LOW | P1 |
| Argument-aware chunking | HIGH | MEDIUM | P1 |
| Persistent vector index | HIGH | LOW | P1 |
| Source citation tracking | HIGH | MEDIUM | P1 |
| CLI interface | MEDIUM | LOW | P1 |
| Result context/preview | MEDIUM | LOW | P1 |
| Cross-encoder reranking | HIGH | MEDIUM | P2 |
| Multi-document synthesis (RAG) | HIGH | HIGH | P2 |
| Faceted navigation | MEDIUM | MEDIUM | P2 |
| Difficulty-aware ordering | MEDIUM | LOW | P2 |
| Query expansion | MEDIUM | MEDIUM | P2 |
| Research sessions / saved searches | MEDIUM | MEDIUM | P2 |
| Domain-tuned embeddings | MEDIUM | MEDIUM | P2 |
| Knowledge graph | HIGH | HIGH | P3 |
| Concept evolution tracking | HIGH | HIGH | P3 |
| Contradiction detection | MEDIUM | HIGH | P3 |
| Reading list generation | MEDIUM | MEDIUM | P3 |
| Hierarchical indexing + routing | MEDIUM | HIGH | P3 |
| Web UI | LOW | MEDIUM | P3 |

**Priority key:**
- P1: Must have for launch (v1 MVP)
- P2: Should have, add when core is validated (v1.x)
- P3: Nice to have, future consideration (v2+)

## Competitor Feature Analysis

| Feature | Perplexity | Elicit / Semantic Scholar | NotebookLM | Obsidian + AI Plugins | Our Approach |
|---------|-----------|--------------------------|------------|----------------------|--------------|
| Semantic search | Yes (web-wide) | Yes (academic papers) | Yes (uploaded docs) | Plugin-dependent | Yes (closed corpus, philosophy-optimized) |
| Keyword search | Blended | Yes | Limited | Yes (native) | Yes (BM25, equal citizen with vector) |
| Hybrid search | Implicit | Yes | No explicit control | No | Yes (explicit fusion with tunable weights) |
| Metadata filtering | No (web) | Yes (date, author, field) | No | Manual tags only | Yes (rich philosophical metadata) |
| Source citations | Inline URLs | Paper citations | Document citations | No synthesis | Passage-level citations with document context |
| Multi-doc synthesis | Yes (web sources) | Yes (paper summaries) | Yes (uploaded docs) | No | Yes (corpus-grounded, citation-required) |
| Concept tracking | No | Citation graphs | No | Manual linking | Future: knowledge graph with evolution tracking |
| Domain specialization | None (general) | Academic NLP | None (general) | User-configured | Philosophy-tuned embeddings and terminology |
| Difficulty navigation | No | No | No | Manual | Yes (pedagogical metadata, intro-to-advanced paths) |
| Closed corpus focus | No (web) | No (all papers) | Yes (uploaded) | Yes (vault) | Yes (curated Objectivism Library) |
| Philosophical terminology | No | Academic terms | No | No | Yes (Objectivist concept mappings) |
| Offline/local-first | No | No | No | Yes | Yes (all processing local, no cloud dependency) |

**Key competitive insight:** No existing tool combines semantic search with philosophical domain specialization, pedagogical metadata, and concept evolution tracking on a curated closed corpus. The closest competitors are NotebookLM (good synthesis, no domain specialization) and Obsidian + AI plugins (good local-first, no integrated semantic search). Our approach fills the gap between general-purpose AI research tools and manual philosophical scholarship.

## Sources

- Perplexity deep research synthesis (2026-02-15) covering:
  - Vector database comparison: Pinecone, Weaviate, Qdrant, Chroma, Milvus, pgvector [1, 5, 26, 35]
  - RAG architecture patterns and best practices [2, 6, 9, 12, 46]
  - Chunking strategies for specialized text [10, 13, 45, 60]
  - Multi-hop reasoning frameworks: LiR3AG, CogGRAG [24, 48]
  - Query expansion and refinement techniques [43]
  - Citation and attribution in RAG systems: SALSA [53, 56]
  - RAG failure modes and anti-patterns [54, 57]
  - Embedding model benchmarks and domain-specific fine-tuning [50, 59, 62]
  - LangChain vs LlamaIndex comparison [3, 7]
  - Academic research tools: Semantic Scholar, Connected Papers, Elicit [16, 37, 40]
  - NotebookLM for research synthesis [41, 44]
  - Knowledge graph integration with RAG [18, 48]
  - Multimodal RAG considerations [25, 28]
  - Metadata filtering and faceted search in vector databases [4, 8]

---
*Feature research for: Semantic search and document intelligence for philosophical research*
*Researched: 2026-02-15*
