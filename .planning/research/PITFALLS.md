# Pitfalls Research

**Domain:** Semantic Search / RAG for Document Library (1,749 files, Gemini API, state-tracked pipeline)
**Researched:** 2026-02-15
**Confidence:** HIGH (deep research with multiple corroborating sources)

## Critical Pitfalls

### Pitfall 1: Naive Fixed-Size Chunking Destroys Semantic Coherence

**What goes wrong:**
Fixed-size chunking (e.g., 512 tokens with overlap) splits text at arbitrary points regardless of meaning. Sentences are severed mid-thought, arguments are fragmented across chunks, and the embedding model generates vectors that poorly represent the intended meaning. For a library of philosophical texts where arguments span multiple paragraphs, this is devastating -- a chunk containing half of Rand's argument about the primacy of existence followed by unrelated content produces a meaningless embedding.

**Why it happens:**
Fixed-size chunking is the default in most tutorials and libraries. It appears to "work" in demos with small document sets. The quality degradation is invisible -- the system returns results, they just aren't the best results. No error is thrown when a concept is split across chunks.

**How to avoid:**
- Use structure-aware chunking that respects document boundaries (headings, paragraphs, section breaks).
- For Markdown/text files: split at heading boundaries first, then paragraph boundaries, then sentence boundaries.
- Preserve parent context: each chunk should carry its section heading and document title as prefix metadata.
- Test chunking quality manually on 20-30 representative documents before scaling to 1,749.
- Set a minimum chunk size (avoid chunks under 100 tokens -- they lack sufficient context for meaningful embeddings).

**Warning signs:**
- Search queries return chunks that start or end mid-sentence.
- Related concepts require multiple chunks to reconstruct.
- Users search for a concept they know exists but the right chunk is never in top-5 results.

**Phase to address:**
Phase 1 (Foundation) -- chunking strategy must be validated before any bulk upload begins. Rework after upload means re-embedding everything.

---

### Pitfall 2: File Expiration Creates a Silent State Corruption Death Spiral

**What goes wrong:**
Gemini's File API retains uploaded files for only 48 hours. Systems that upload files for processing must complete ALL processing stages within that window. If rate limiting forces backoff and extends processing time beyond 48 hours, files expire mid-pipeline. The system's state tracker still references expired file IDs, causing cryptic "File not found" errors. Re-uploading expired files counts against quotas, which triggers more rate limiting, which causes more expirations -- a death spiral.

**Why it happens:**
Developers test with small batches (10-50 files) that complete well within 48 hours. The expiration constraint only surfaces at scale (1,749 files). Rate limit backoff is unpredictable, making it impossible to guarantee completion within the window without explicit tracking.

**How to avoid:**
- Track upload timestamp for every file alongside its API file ID.
- Calculate a "safe processing deadline" (e.g., 36 hours after upload, leaving 12-hour buffer).
- Implement a pre-expiration check: before any processing step, verify the file hasn't expired.
- Design pipeline stages to be independently resumable -- if a file expires between chunking and embedding, re-upload only that file and resume from the embedding stage.
- Process in controlled batches (100-200 files) rather than uploading all 1,749 at once. Complete each batch fully before starting the next.

**Warning signs:**
- "File not found" or "Resource not found" errors appearing 24+ hours into a batch run.
- Processing time estimates exceeding 36 hours.
- Increasing error rates as a batch progresses.

**Phase to address:**
Phase 1 (Foundation) -- state tracking schema must include upload timestamps and expiration awareness from day one.

---

### Pitfall 3: No Idempotency in Upload Pipeline Causes Duplicate Embeddings

**What goes wrong:**
A batch upload of 200 files succeeds on files 1-147, fails on file 148 (transient network error), then succeeds on files 149-200. The system retries the batch. Without idempotency, files 1-147 and 149-200 are uploaded and embedded again, creating duplicate entries in the vector store. Search results now return the same content twice, confusing ranking and wasting storage. Over multiple retry cycles, some documents have 3-4 duplicate embedding sets.

**Why it happens:**
Developers implement retry logic at the batch level ("retry the whole batch") instead of the individual file level. File upload APIs often don't enforce idempotency by default. The duplicates don't cause errors -- they cause silently degraded search quality.

**How to avoid:**
- Track per-file upload status (not just per-batch).
- Use content hashes as idempotency keys: before uploading, check if a file with this hash already exists.
- On retry, skip files that already succeeded -- only retry genuinely failed files.
- Before embedding, check if embeddings for this content hash already exist in the vector store.
- Implement a deduplication check as a post-upload validation step.

**Warning signs:**
- Vector store size growing faster than expected relative to document count.
- Same passages appearing multiple times in search results.
- Document count in vector store exceeding expected chunk count.

**Phase to address:**
Phase 1 (Foundation) -- idempotency keys and per-file tracking are core pipeline requirements.

---

### Pitfall 4: Metadata Loss Through the Ingestion Pipeline

**What goes wrong:**
Document metadata (source file path, author, book title, chapter, publication date, category) is lost during chunking and embedding. Chunks end up in the vector store with no way to trace them back to source documents, no way to filter by author or category, and no way to display meaningful citations to users. Six months in, someone asks "show me everything from The Virtue of Selfishness" and the system cannot answer because book-level metadata was dropped during chunking.

**Why it happens:**
Chunking is treated as a text-processing step, separate from metadata management. Most chunking libraries output plain text chunks without metadata. Developers plan to "add metadata later" but the association between chunks and source documents is already broken.

**How to avoid:**
- Define the metadata schema BEFORE building the chunking pipeline. Required fields: source file path, document title, section/chapter heading, chunk position (e.g., chunk 3 of 12), content hash.
- Propagate metadata at every pipeline stage: chunk creation, embedding, storage.
- Store metadata in queryable fields (not serialized JSON blobs) -- the vector store must support filtering by metadata fields.
- Validate metadata completeness as a post-ingestion check: every chunk in the vector store must have all required metadata fields populated.

**Warning signs:**
- Chunks in the vector store with null or empty metadata fields.
- Inability to answer "which document did this come from?" for any retrieved chunk.
- Search results that cannot be filtered by category, author, or source.

**Phase to address:**
Phase 1 (Foundation) -- metadata schema must be defined before any processing begins. Retrofitting metadata is extremely expensive (requires re-processing all documents).

---

### Pitfall 5: Embedding Model Version Change Silently Breaks All Search

**What goes wrong:**
Google updates the Gemini embedding model (e.g., `text-embedding-004` to `text-embedding-005`). New documents are embedded with the new model. Old documents remain embedded with the old model. Cosine similarity between old and new embeddings is meaningless -- the semantic spaces are geometrically different. Queries now only find recently-added documents, silently missing the majority of the collection. The system appears to work but recall drops catastrophically.

**Why it happens:**
API providers present model updates as improvements. The new model IS better in isolation. But mixing embeddings from different model versions in the same vector index is comparing apples to oranges. No error is thrown -- similarity scores are returned, they're just meaningless across versions.

**How to avoid:**
- Pin the embedding model version explicitly in configuration (e.g., `text-embedding-004`, not `text-embedding-latest`).
- Record the model version used for every embedding alongside the embedding itself.
- When updating models, treat it as a full re-indexing event: build a new index with the new model, validate quality, then swap atomically.
- Never mix embeddings from different model versions in the same index.
- Budget for periodic full re-embedding (cost: ~1,749 documents * chunks-per-doc * price-per-embedding).

**Warning signs:**
- Search quality drops suddenly after an API update (even if you didn't change anything).
- Recently added documents are disproportionately favored in results.
- Changelog or release notes from Google mentioning embedding model updates.

**Phase to address:**
Phase 1 (Foundation) -- model version pinning and version tracking in state schema. Phase 3+ (Operations) -- re-indexing procedures when model updates are desired.

---

### Pitfall 6: Rate Limit Cascade During Bulk Upload

**What goes wrong:**
Uploading 1,749 files to Gemini with naive parallelism hits the requests-per-minute (RPM) limit. All excess requests return 429 errors. Naive retry logic immediately retries all failed requests, which also get 429'd. The system enters a cascade where every retry adds more load, extending backoff times exponentially. What should take 2 hours takes 12+ hours, potentially pushing into the 48-hour file expiration window.

**Why it happens:**
Rate limits on Gemini API operate at multiple levels simultaneously: RPM (requests per minute), TPM (tokens per minute), and RPD (requests per day). Staying within one limit doesn't guarantee compliance with others. Developers test with small batches that fit within all limits and don't encounter the interaction effects.

**How to avoid:**
- Implement proactive rate limiting on the client side -- throttle outgoing requests to 80% of the known RPM limit before hitting the API.
- Use token bucket or leaky bucket algorithms, not just simple delays between requests.
- Implement circuit breaker pattern: if 5% of requests get 429, reduce request rate by 50% and wait before resuming.
- Parse `Retry-After` headers from 429 responses and respect them.
- Separate rate limit budgets for different operation types (file upload vs. embedding vs. query).
- Log actual API response times and 429 rates to calibrate throttling over time.

**Warning signs:**
- 429 errors appearing in logs.
- Batch processing time estimates growing during execution.
- API usage dashboard showing burst patterns followed by gaps.

**Phase to address:**
Phase 1 (Foundation) -- rate limiter must be built before any bulk operations. Test with real API limits on a 50-file batch before scaling to 1,749.

---

### Pitfall 7: No Incremental Update Strategy Forces Full Re-Index on Every Change

**What goes wrong:**
The system is built to handle bulk upload but has no mechanism for incremental updates. When a single document changes, the only option is to re-process all 1,749 files. This is prohibitively expensive (API costs, time, rate limits) so updates are deferred indefinitely. The search index becomes stale. New content is never searchable. The system becomes a snapshot frozen at initial upload time.

**Why it happens:**
Bulk upload is the obvious first milestone. Incremental update is deferred as "we'll add that later." But the data model and state tracking needed for incremental updates must be designed upfront. Retrofitting incremental capability onto a bulk-only pipeline requires significant rework.

**How to avoid:**
- Design the state tracking schema for incremental updates from the start, even if the first implementation is bulk-only.
- Track per-file: content hash, last-processed timestamp, current chunk IDs in vector store, embedding model version used.
- Change detection: compare current file hash against stored hash. Only process files where hash differs.
- Chunk-level updates: when a document changes, delete its old chunks from the vector store and insert new chunks. Don't leave orphaned chunks.
- Include a "force re-process" flag for manual override when needed.

**Warning signs:**
- State tracking only stores "processed: true/false" without content hashes or timestamps.
- No mechanism to delete old chunks when a document is updated.
- Updates require "start from scratch" as the only recovery path.

**Phase to address:**
Phase 1 (Foundation) -- state schema design. Phase 2 (Core) -- incremental update implementation.

---

### Pitfall 8: State Tracking Lives Only in Memory

**What goes wrong:**
The pipeline tracks progress (which files uploaded, which chunks embedded) in in-memory data structures. A crash, timeout, or restart loses all state. The system doesn't know what's been processed and what hasn't. Recovery requires either re-processing everything (expensive, slow) or manual inspection (tedious, error-prone for 1,749 files).

**Why it happens:**
In-memory tracking is fast and simple. It works perfectly during development when batches are small and the developer is watching. The failure only manifests during long-running batch operations that encounter interruptions.

**How to avoid:**
- Persist state to disk (SQLite, JSON file) immediately after each state transition.
- Use write-ahead logging: write the intended state change to a log before executing, then mark complete after.
- Implement checkpointing: save full pipeline state every N files (e.g., every 50 files).
- On startup, read persisted state and resume from last checkpoint.
- SQLite is ideal for this -- single file, ACID transactions, no server process, handles concurrent reads.

**Warning signs:**
- Pipeline progress is only visible through console output (not persisted anywhere).
- After a crash, the only recovery option is "start over."
- No file on disk tracks which documents have been processed.

**Phase to address:**
Phase 1 (Foundation) -- persistent state is a prerequisite for all pipeline operations.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Store all metadata as a serialized JSON blob | Fast to implement, flexible schema | Cannot filter/query by metadata fields; must deserialize to inspect | Never -- use structured fields from the start |
| Skip content hashing for change detection | Simpler state schema | Cannot detect file changes for incremental updates; must re-process everything | Never -- hashing is trivial to implement |
| Use embedding model "latest" tag | Always get newest model | Embeddings become incompatible across index without warning | Never -- always pin versions |
| Process all files sequentially (no batching) | Simplest control flow | 1,749 files take 10x longer than batched processing; no parallelism | Only during initial development/testing with <50 files |
| Hardcode rate limits | Quick to implement | Limits change without notice; system breaks on API tier changes | MVP only -- parameterize within first week |
| Skip chunk overlap | Fewer chunks, lower storage/cost | Concepts at chunk boundaries are lost; queries about boundary content fail | Never for philosophical/argumentative text where ideas flow across paragraphs |
| Defer error handling ("happy path only") | Ship faster | First production failure requires emergency debugging with no recovery path | Never for a pipeline processing 1,749 files |

## Integration Gotchas

Common mistakes when connecting to external services (Gemini API specifically).

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Gemini File API | Uploading all 1,749 files at once, then processing | Upload in batches of 100-200; complete each batch fully before starting next |
| Gemini File API | Ignoring the 48-hour file retention limit | Track upload timestamps; implement pre-expiration re-upload logic |
| Gemini Embedding API | Not accounting for token counting discrepancy (local count vs API count) | Build empirical correction factor from API response usage data; apply 15-20% safety margin initially |
| Gemini Embedding API | Assuming RPM is the only rate limit | Track RPM, TPM, and RPD simultaneously; throttle to 80% of the lowest applicable limit |
| Gemini Batch API | Using real-time API for bulk operations | Use Batch API for all non-interactive operations (30-50% cost reduction) |
| Vector Store (any) | Storing embeddings without model version tag | Every embedding record must include `model_version` field |
| Vector Store (any) | No index on metadata fields used for filtering | Create indices on frequently-filtered metadata fields (source, category, author) |

## Performance Traps

Patterns that work at small scale but fail as the collection grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Pure vector similarity search (no hybrid) | Precision degrades as collection grows; relevant documents missed | Implement hybrid search combining vector similarity with keyword matching (BM25) and re-ranking | Measurable at ~1,000 docs; significant at 1,700+ docs (~52% precision at 10K docs vs 70%+ at small scale) |
| Retrieving too many chunks for LLM context | "Lost in the middle" effect -- LLM ignores information positioned in the middle of context | Retrieve top-5 most relevant chunks (not top-20); place highest-relevance at beginning and end of context | Immediate -- LLMs exhibit primacy/recency bias at any context length |
| No caching of repeated queries | Same popular queries re-embed and re-search every time | Cache query embeddings and results for frequently-asked queries with TTL | Noticeable when same queries are run >10 times/day |
| Full document re-embedding on any change | A single typo fix re-embeds entire 50-page document | Track changes at chunk level; only re-embed chunks whose content actually changed | Immediate for documents updated frequently |
| Sequential file processing without parallelism | Bulk upload takes days instead of hours | Process files in parallel within rate limit constraints (e.g., 5-10 concurrent uploads) | At ~100+ files, sequential becomes impractical |

## Security Mistakes

Domain-specific security issues for a personal research tool with external API integration.

| Mistake | Risk | Prevention |
|---------|------|------------|
| API key hardcoded in source or config file | Key leaked via git, screenshots, or file sharing | Use environment variables or a secrets manager; add API key patterns to .gitignore |
| No API key rotation plan | Compromised key provides indefinite access | Rotate keys periodically; design system to accept key changes without re-deployment |
| Uploading sensitive personal annotations mixed with source texts | Personal notes exposed to Gemini API processing | Separate source texts from personal annotations in the pipeline; decide explicitly what gets sent to external APIs |
| State database containing file paths exposed | Reveals local directory structure and file organization | Keep state database in .gitignore; use relative paths in state tracking |

## UX Pitfalls

Common user experience mistakes in semantic search systems (even for single-user personal tools).

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No source attribution in search results | Cannot verify where information came from; cannot read surrounding context | Every search result must show: source document, section/chapter, and a link/path to the original file |
| Returning raw chunks without context | Chunks start mid-sentence or reference "as mentioned above" with no context | Include parent section heading and 1-2 sentences of surrounding context with each result |
| No indication of search confidence | User cannot distinguish strong matches from weak matches | Show relevance scores (even simplified: high/medium/low) alongside results |
| Boolean search not supported alongside semantic | User cannot search for exact phrases or specific terms | Implement hybrid search: semantic by default, with option for exact-match keyword search |
| No way to see what's in the index | User forgets what's been uploaded; cannot audit coverage | Provide a "collection status" view showing document count, last update, coverage by category |
| Slow search response after initial enthusiasm | Query latency >2 seconds kills habitual use | Target <1 second query latency; cache embeddings for common query patterns |

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Chunking:** Often missing overlap between chunks -- verify chunks share 10-15% content at boundaries to avoid losing concepts that span chunk edges
- [ ] **Upload pipeline:** Often missing per-file error tracking -- verify every file has an explicit success/failure status, not just batch-level success
- [ ] **State tracking:** Often missing content hashes -- verify state records include file content hash for change detection, not just "processed: true"
- [ ] **Metadata:** Often missing chunk-to-source mapping -- verify every chunk in vector store can be traced back to its exact source file and position
- [ ] **Search:** Often missing empty-result handling -- verify the system behaves sensibly when no results match (helpful message, not blank page or error)
- [ ] **Incremental update:** Often missing orphan cleanup -- verify that when a document is re-processed, old chunks from the previous version are deleted
- [ ] **Rate limiting:** Often missing multi-dimension tracking -- verify rate limiter tracks RPM AND TPM AND RPD simultaneously, not just one
- [ ] **Recovery:** Often missing resume capability -- verify that after a crash, the pipeline can resume from where it stopped rather than restarting
- [ ] **Expiration:** Often missing proactive re-upload -- verify the system detects approaching file expiration and re-uploads before the 48-hour deadline

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Chunks with lost metadata | HIGH | Must re-process all affected documents from source files; no way to reconstruct metadata from chunks alone |
| Duplicate embeddings from failed retries | MEDIUM | Query vector store for duplicate content hashes; delete duplicates keeping most recent; validate result count matches expected |
| Mixed embedding model versions in index | HIGH | Full re-embedding required with single model version; build new index in parallel, swap when complete |
| Expired files mid-pipeline | LOW | Re-upload only expired files (use state tracker to identify which); resume pipeline from the stage where expiration occurred |
| Corrupt state database | MEDIUM | If backups exist, restore from last known good backup. If not, compare vector store contents against source files to reconstruct state |
| Rate limit death spiral | LOW | Stop all API calls. Wait 5 minutes. Resume at 20% of previous rate. Gradually increase. Do NOT retry everything at once |
| Stale index (no incremental updates) | MEDIUM | Run content hash comparison against all source files. Process only changed files. This is the incremental update path |
| Search quality degradation | MEDIUM | Run test queries against known-good results. If recall dropped, investigate: model version mismatch, stale chunks, or collection size degradation. Apply appropriate fix |

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Naive chunking | Phase 1: Foundation | Manual review of 20+ chunked documents; no mid-sentence splits; heading context preserved |
| File expiration death spiral | Phase 1: Foundation | State schema includes upload_timestamp and expiration_deadline for every file |
| No idempotency | Phase 1: Foundation | Re-running the pipeline on already-processed files produces zero duplicates |
| Metadata loss | Phase 1: Foundation | Every chunk in vector store has all required metadata fields populated; spot-check 50 random chunks |
| Embedding model drift | Phase 1: Foundation (schema); Phase 3: Operations (re-index procedure) | State schema includes model_version; config pins specific model version string |
| Rate limit cascade | Phase 1: Foundation | Bulk upload of 200 files completes without any 429 errors using client-side rate limiting |
| No incremental updates | Phase 2: Core Pipeline | Modify one source file, run pipeline, verify only that file is re-processed and old chunks removed |
| State in memory only | Phase 1: Foundation | Kill pipeline mid-run, restart, verify it resumes from last checkpoint without re-processing completed files |
| Search quality degradation | Phase 3: Operations | Maintain 20+ test queries with expected results; weekly automated quality check; alert if precision drops below threshold |
| Lost-in-the-middle effect | Phase 2: Core Pipeline | Search results position highest-relevance chunks at beginning/end of LLM context; test with multi-chunk queries |

## Sources

- [Milvus: Common failure modes in semantic search](https://milvus.io/ai-quick-reference/what-are-common-failure-modes-in-semantic-search-systems) -- failure mode taxonomy
- [Machine Learning Mastery: Chunking techniques for LLM applications](https://machinelearningmastery.com/essential-chunking-techniques-for-building-better-llm-applications/) -- chunking strategy comparison
- [AWS: Intelligent governance of document processing pipelines](https://aws.amazon.com/blogs/machine-learning/intelligent-governance-of-document-processing-pipelines-for-regulated-industries/) -- metadata governance patterns
- [Gemini API: Rate limits documentation](https://ai.google.dev/gemini-api/docs/rate-limits) -- RPM, TPM, RPD limits
- [Google: Gemini API file limits](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-api-new-file-limits/) -- 48-hour retention policy
- [Milvus: Impact of embedding drift](https://milvus.io/ai-quick-reference/what-is-the-impact-of-embedding-drift-and-how-do-i-manage-it) -- model version incompatibility
- [Microsoft: Future-proofing AI model upgrades](https://techcommunity.microsoft.com/blog/fasttrackforazureblog/future-proofing-ai-strategies-for-effective-model-upgrades-in-azure-openai/4029077) -- embedding version management
- [EyeLevel: Do vector databases lose accuracy at scale?](https://www.eyelevel.ai/post/do-vector-databases-lose-accuracy-at-scale) -- precision degradation at scale (52% at 10K docs)
- [Snorkel: RAG failure modes and how to fix them](https://snorkel.ai/blog/retrieval-augmented-generation-rag-failure-modes-and-how-to-fix-them/) -- retrieval quality patterns
- [Algomaster: Idempotency in system design](https://algomaster.io/learn/system-design/idempotency) -- idempotency key patterns
- [Weaviate: Chunking strategies for RAG](https://weaviate.io/blog/chunking-strategies-for-rag) -- late chunking and semantic chunking
- [Batch processing retry strategies](https://oneuptime.com/blog/post/2026-01-30-batch-processing-retry-strategies/view) -- circuit breaker and retry patterns
- [Confluent: Kafka dead letter queue](https://www.confluent.io/learn/kafka-dead-letter-queue/) -- DLQ patterns for failed operations
- [FinOps: How token pricing really works](https://www.finops.org/wg/genai-finops-how-token-pricing-really-works/) -- cost management for GenAI APIs
- [Gemini API: Batch API](https://ai.google.dev/gemini-api/docs/batch-api) -- 30-50% cost reduction via batch processing
- [Towards AI: RAG versioning, observability, and evaluation in production](https://pub.towardsai.net/rag-in-practice-exploring-versioning-observability-and-evaluation-in-production-systems-85dc28e1d9a8) -- state management patterns

---
*Pitfalls research for: Semantic Search / RAG Document Library with Gemini API*
*Researched: 2026-02-15*
