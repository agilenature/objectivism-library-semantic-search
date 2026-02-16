# CLARIFICATIONS-NEEDED.md

## Phase 3: Search & CLI — Stakeholder Decisions Required

**Generated:** 2026-02-16
**Mode:** Multi-provider synthesis (OpenAI, Gemini, Perplexity)
**Source:** 3 AI providers analyzed Phase 3 requirements

---

## Decision Summary

**Total questions:** 11 gray areas identified
**Tier 1 (Blocking):** 5 questions — Must answer before planning
**Tier 2 (Important):** 4 questions — Should answer for quality
**Tier 3 (Polish):** 2 questions — Can defer to implementation

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: Hybrid Search Strategy — Semantic-Only or Dual-System?

**Question:** Should Phase 3 implement semantic-only search (Gemini File Search alone) or hybrid search combining semantic (Gemini) with keyword/full-text search (SQLite FTS5)?

**Why it matters:**
- Affects architecture complexity, query latency, and result quality
- Semantic search handles conceptual queries ("What is Rand's view of rationality?") but may fail on exact keyword searches ("Find all chapters by Harry Binswanger")
- Hybrid search requires maintaining dual indices and merging incompatible score scales

**Options identified by providers:**

**A. Semantic-only search (Gemini File Search)**
- Use Gemini vector search exclusively for all queries
- Simpler architecture, clearer performance baselines
- Philosophy library users ask conceptual questions, not keyword queries
- Faster to implement (no SQLite FTS5 integration needed)
- _(Proposed by: Gemini, Perplexity as Phase 3 MVP)_

**B. Dual-system hybrid search (Gemini + SQLite FTS5)**
- Query both Gemini (semantic) and SQLite FTS5 (keyword) in parallel
- Merge results using Reciprocal Rank Fusion (RRF) algorithm
- Handles both conceptual and keyword queries
- More complex, adds 100-200ms latency per search
- _(Proposed by: OpenAI, Perplexity as Phase 4 enhancement)_

**C. Route-based search (detect query intent)**
- Analyze query to detect keyword vs semantic intent
- Route keyword queries to SQLite, semantic queries to Gemini
- Requires query intent classification (complex)
- _(Mentioned by: OpenAI as alternative)_

**Synthesis recommendation:** ✅ **Option A (Semantic-only for Phase 3 MVP)**
- Philosophy library use case is primarily conceptual research
- Defer hybrid search to Phase 4 if user feedback indicates keyword queries fail regularly
- Reduces Phase 3 scope and complexity

**Sub-questions:**
- Is keyword search a hard requirement, or can it be deferred?
- What is acceptable latency? <2 seconds or 10-30 seconds for complex queries?
- If hybrid search is needed later, should semantic and keyword be weighted equally (RRF), or should semantic dominate?

---

### Q2: Metadata Filtering Architecture — Where to Apply Filters?

**Question:** Should metadata filters (course, year, difficulty, topic) be applied via Gemini's server-side `metadata_filter` parameter, via client-side SQLite queries, or both in combination?

**Why it matters:**
- Gemini API supports `metadata_filter`, but semantics unclear (pre-filter vs post-filter)
- SQLite has all metadata locally, enabling flexible queries
- Filtering at wrong layer wastes API calls or reduces search quality
- Dual-source-of-truth (Gemini + SQLite metadata) requires sync strategy

**Options identified by providers:**

**A. Server-side filtering only (Gemini `metadata_filter`)**
- Pass all filters to Gemini's `metadata_filter` parameter
- Assumes Gemini pre-filters (reduces vector space before search)
- Simpler code, but limited to Gemini's filter syntax
- _(Proposed by: Gemini as primary approach)_

**B. Client-side filtering only (SQLite post-filter)**
- Query Gemini without filters, get all results
- Filter results locally using SQLite metadata
- Wastes API calls on results that will be discarded
- _(Mentioned by: Gemini as fallback if Gemini filtering unsupported)_

**C. Hybrid two-stage filtering (Gemini + SQLite)**
- Simple single-field filters → Gemini `metadata_filter` (e.g., `year=2023`)
- Complex multi-field filters → SQLite client-side (e.g., `difficulty>=300 AND topic LIKE 'Ethics%'`)
- Best of both worlds, but requires careful split logic
- _(Proposed by: OpenAI, Perplexity as recommended)_

**Synthesis recommendation:** ✅ **Option C (Hybrid two-stage filtering)**
- Use Gemini server-side for simple filters (year, course) to reduce vector space
- Use SQLite client-side for complex filters (range queries, pattern matching)
- Validate filter behavior empirically through A/B testing

**Sub-questions:**
- What happens if Gemini metadata and SQLite metadata diverge? Reconciliation needed?
- Should compound boolean filters (AND/OR) be supported in Gemini's syntax?
- Is metadata consistency a hard requirement, or can temporary divergence be tolerated?

---

### Q3: Passage-Level Citation Format — How to Display Citations in Terminal?

**Question:** How should passage-level citations be formatted and displayed in the CLI? Inline citations, footnotes, or multi-tier display? What metadata should be included?

**Why it matters:**
- Philosophy library users need to trace claims back to specific files and sections
- Terminal width (80-100 chars) limits formatting options
- Need to balance citation completeness with readability
- Gemini's `groundingChunks` point to documents, not passages within them

**Options identified by providers:**

**A. Inline citations only**
- Insert bracketed indices in response text: "Rational self-interest[1] requires happiness[2]."
- Compact, but citation details not immediately visible
- Requires separate command to view citation sources
- _(Mentioned by: All providers as part of solution)_

**B. Footnote-style (at end of response)**
- Response text followed by numbered footnotes
- Standard academic format, but harder to implement in terminal
- May exceed terminal height for long lists
- _(Not explicitly proposed, but mentioned in context)_

**C. Three-tier progressive disclosure**
- Tier 1: Inline citations in response `[1][2]`
- Tier 2: Citation details panel below response (passage excerpts, course/year metadata)
- Tier 3: Full source listing from SQLite (complete metadata)
- Best comprehensiveness, but requires more vertical space
- _(Proposed by: All 3 providers as consensus)_

**Synthesis recommendation:** ✅ **Option C (Three-tier progressive disclosure)**
- Inline citations show sources at a glance
- Citation panel provides passage excerpts and basic metadata
- Full source listing shows complete metadata (course, year, quarter, difficulty, instructor)
- Use Rich `Panel` and `Table` components for structured display

**Sub-questions:**
- Should excerpts be full chunks (200+ chars) or brief (50-100 chars) to fit terminal?
- How should Gemini's citations be validated (check cited files exist in store)?
- Should cross-references between documents be auto-discovered and displayed?

---

### Q4: CLI Command Structure — Separate Commands or Unified Interface?

**Question:** Should `search`, `filter`, and `browse` be implemented as separate commands, subcommands of unified `query`, or flags on single `find` command? Should filters be stateful (persistent) or stateless (explicit flags)?

**Why it matters:**
- Affects user experience, discoverability, and scriptability
- Requirements show `search "query" --course "X"` (stateless), but also mention separate "filter command"
- Stateful filters improve interactive UX but add complexity
- Unclear whether CLI is primarily interactive or used in scripts

**Options identified by providers:**

**A. Three separate commands (search, filter, browse)**
- `library search "query" [--filter field:value]`
- `library filter field:value` (metadata-only, no semantic query)
- `library browse [--course X]` (structural navigation)
- Clear separation of concerns, easy to discover
- _(Proposed by: Perplexity, Gemini)_

**B. Unified command with subcommands**
- `library query search "text"`
- `library query filter field:value`
- `library query browse structure`
- Hierarchical, but more verbose
- _(Not explicitly proposed)_

**C. Flags on unified `find` command**
- `library find "query" --semantic` (default)
- `library find --filter year:2023` (metadata-only)
- `library find --browse courses`
- Compact, but conflates different interaction patterns
- _(Not explicitly proposed)_

**Synthesis recommendation:** ✅ **Option A (Three separate commands, stateless filters)**
- `search` is primary interaction (semantic query + optional metadata filters)
- `filter` is metadata-only query (lists documents matching filters, no semantic ranking)
- `browse` is structural navigation (interactive drill-down: courses → years → quarters)
- All filters are explicit flags (stateless), not persistent state
- Simpler, scriptable, predictable

**Sub-questions:**
- Should filters persist across multiple searches in one session?
- Is the CLI primarily interactive (human use) or scripted (automation)?
- Should `browse` results include document previews or just names and counts?

---

### Q5: Error Handling and Retry Strategy — How to Handle API Failures?

**Question:** When Gemini API returns errors (429 rate limits, timeouts, 5xx), should the CLI retry automatically, show errors immediately, or fall back to alternative methods (SQLite search)?

**Why it matters:**
- Philosophy researchers may tolerate delays, but poor error handling creates bad UX
- Rate limits are unpredictable; automatic retries improve reliability
- Transparent retries can hide slow responses from users without feedback
- Fallback to SQLite adds complexity but improves availability

**Options identified by providers:**

**A. Eager failure (show errors immediately)**
- Return errors to user without retry
- Simple to implement, but poor user experience
- User must manually retry
- _(Not recommended by any provider)_

**B. Automatic retry with exponential backoff**
- Retry up to 3 times with increasing delays (0.5s, 1s, 2s)
- Add random jitter (±50%) to prevent thundering herd
- Show user feedback: "[yellow]⟳ Retrying (1/3) in 0.5s...[/yellow]"
- Timeout after 30 seconds
- _(Proposed by: All 3 providers as consensus)_

**C. Fallback with graceful degradation**
- When Gemini unavailable, fall back to SQLite full-text search
- Best UX, but requires maintaining dual code paths
- Circuit breaker: disable Gemini for 60s cooldown after 5 consecutive failures
- _(Proposed by: OpenAI as optional enhancement)_

**Synthesis recommendation:** ✅ **Option B (Automatic retry with backoff + user feedback)**
- Retry up to 3 attempts with exponential backoff (0.5s, 1s, 2s) + jitter
- Display retry status via Rich: "[yellow]⟳ Retrying...[/yellow]"
- Respect `Retry-After` header on 429 responses
- Global timeout 30 seconds for API calls
- Optional circuit breaker (Phase 4): fall back to SQLite after repeated failures

**Sub-questions:**
- Should the system ever silently degrade to SQLite search, or always inform user?
- What is acceptable timeout? 30s for complex queries, or must be <2s?
- Should repeated failures eventually give up, or keep retrying indefinitely?

---

## Tier 2: Important Decisions (⚠️ Recommended)

### Q6: Gemini Authentication Strategy

**Question:** How should the CLI obtain and store Gemini API credentials? System keychain (like Phase 2), environment variables, config file, or combination?

**Why it matters:**
- Phase 2 used system keychain (`objlib-gemini` service, `api_key` key)
- Consistency across phases improves UX
- Config files risk exposing secrets in version control
- Multi-user machines may need different auth strategies

**Options identified by providers:**

**A. System keychain only (consistent with Phase 2)**
- Use keyring library to read from system keychain
- Fallback to `GEMINI_API_KEY` environment variable if keychain fails
- Most secure, but requires one-time setup
- _(Implied by Phase 2 decision 02-03)_

**B. Environment variable only**
- Read `GEMINI_API_KEY` on startup
- Simple, works on all platforms
- Risk of accidental logging/exposure
- _(Proposed by: OpenAI)_

**C. Config file with encryption**
- Store encrypted key in `~/.objlib/config.json`
- Requires master password or OS keychain integration
- More complex
- _(Not explicitly proposed)_

**Synthesis recommendation:** ⚠️ **Option A (System keychain + env var fallback)**
- Primary: Read from keychain using keyring library (consistent with Phase 2)
- Fallback: Try `GEMINI_API_KEY` environment variable if keychain fails
- Error message: Display actionable setup instructions if no key found

**Sub-questions:**
- Should the CLI support `.env` files via `python-dotenv`?
- Should Google ADC (service accounts) be supported for deployment scenarios?
- Is this tool expected to run in CI/CD where key handling needs stricter controls?

**Confidence:** ⚠️ 2 providers identified this

---

### Q7: Result Ranking and Score Display

**Question:** Should the CLI display raw Gemini relevance scores, normalize them to 0-100%, or hide scores entirely? Should secondary ranking criteria (difficulty, recency) be applied?

**Why it matters:**
- Raw similarity scores (e.g., 0.7 cosine) are not meaningful to end users
- Philosophy library may benefit from difficulty-aware ranking (intro before advanced)
- Multi-factor ranking adds complexity but improves learning progression

**Options identified by providers:**

**A. Gemini-native ranking only (no modification)**
- Display results in Gemini's native order
- Normalize scores to 0-100% for display
- Simple, preserves semantic relevance
- _(Proposed by: Gemini)_

**B. Multi-factor ranking (semantic + difficulty + recency)**
- Combine: 70% semantic + 15% difficulty match + 10% recency + 5% popularity
- Better learning progression (intro before advanced)
- More complex, requires tuning weights
- _(Proposed by: OpenAI, Perplexity)_

**C. Hide scores entirely (rank-only display)**
- Show results in ranked order without scores
- Avoids false precision perception
- _(Not explicitly proposed)_

**Synthesis recommendation:** ⚠️ **Option A for Phase 3 MVP, Option B for Phase 4**
- Phase 3: Use Gemini's native semantic ranking, normalize to 0-100%, display with visual bar `━━━━━━━━○○ 87%`
- Phase 4: Add multi-factor ranking if users report difficulty-ordering issues

**Sub-questions:**
- Should the CLI allow users to customize ranking weights for power users?
- How should ties be broken? Recency, difficulty, alphabetical?
- Is 0-100% scale misleading if 70% is actually very good in practice?

**Confidence:** ⚠️ 2 providers identified this

---

### Q8: Chunk Size and Context Extraction

**Question:** Should Phase 3 configure Gemini's chunk size via `chunking_config`, or accept defaults? How should excerpts be truncated for terminal display?

**Why it matters:**
- Smaller chunks improve precision but fragment context
- Larger chunks preserve context but reduce precision
- Philosophy texts are dense; optimal chunk size unknown
- Terminal width limits excerpt display (80-100 chars)

**Options identified by providers:**

**A. Accept Gemini defaults (no custom chunking)**
- Use Gemini's automatic chunking without configuration
- Simplest, fastest to implement
- May produce suboptimal results for philosophy domain
- _(Proposed by: Perplexity as Phase 3 approach)_

**B. Configure custom chunk size (800-1200 tokens)**
- Set `chunking_config` with fixed size + 15% overlap
- Requires empirical testing to find optimal size
- More control over result granularity
- _(Proposed by: OpenAI as recommended approach)_

**C. Dynamic chunking (semantic boundaries)**
- Chunk at paragraph or section boundaries
- Preserves conceptual coherence
- Complex to implement, requires document structure parsing
- _(Mentioned as ideal, but not explicitly proposed)_

**Synthesis recommendation:** ⚠️ **Option A for Phase 3 MVP, test and optimize in Phase 4**
- Accept Gemini defaults to avoid premature optimization
- Gather user feedback on whether excerpts are too fragmented or too long
- If needed in Phase 4, conduct empirical testing using NVIDIA's methodology to find optimal chunk size

**Sub-questions:**
- What is acceptable preview length? 500 chars? 1000? Adapt to terminal width?
- Should chunk boundaries respect conceptual boundaries (paragraphs, sections)?
- Should users be able to request full document after preview (`library view <doc_id>`)?

**Confidence:** ⚠️ 2 providers identified this

---

### Q9: Cross-Reference Discovery Scope

**Question:** How should SRCH-08 "cross-reference discovery" be implemented? Automatically for all results, or on-demand when user selects a result?

**Why it matters:**
- "Automatically" could mean N+1 queries (expensive, slow)
- "Related" is undefined: vector similarity, shared topics, citation graph?
- Could block Phase 3 if treated as hard requirement for all searches
- Overlaps with Phase 4 advanced features

**Options identified by providers:**

**A. On-demand "More like this"**
- Do NOT show cross-references in main search results
- Provide detail command: `library view <result_id> --show-related`
- When user requests, query Gemini for similar documents
- Avoids N+1 query problem
- _(Proposed by: OpenAI, Gemini)_

**B. Automatic for all results**
- Show related documents for every search result
- Expensive (N+1 queries), slow
- Best discoverability
- _(Not recommended by any provider)_

**C. Cached cross-references**
- Pre-compute related documents during indexing
- Store in SQLite: `related_cache(source_id, related_id, score)`
- Fast lookup, but requires maintenance
- _(Mentioned by: OpenAI as optional enhancement)_

**Synthesis recommendation:** ⚠️ **Option A (On-demand "More like this")**
- Do not show cross-references automatically in main results
- Provide `library view <result_id> --show-related` for on-demand discovery
- Phase 4 enhancement: Cache related results if query frequency justifies it

**Sub-questions:**
- Is SRCH-08 required for Phase 3 acceptance, or can it be minimal/basic?
- Should cross-references be within same course only, or across whole library?
- Do we need to explain why something is related (shared terms/topics) for trust?

**Confidence:** ⚠️ 2 providers identified this

---

## Tier 3: Polish Decisions (🔍 Can Defer)

### Q10: Typer CLI State Management Pattern

**Question:** How should the Gemini client and SQLite connection be stored and passed across Typer commands? Typed dataclass, context object, or singleton pattern?

**Why it matters:**
- Typer's `ctx.obj` is untyped, defeating IDE autocompletion
- Expensive resources (API clients) should initialize once
- Testability requires mockable state injection

**Options identified by providers:**

**A. Typed AppState dataclass in callback**
- Create `@dataclass AppState(gemini_client, sqlite_db, config)`
- Initialize in `@app.callback()`, attach to `ctx.obj`
- Type-hinted helper: `get_app_state(ctx) -> AppState`
- Best type safety, testability
- _(Proposed by: Perplexity)_

**B. Untyped context (default Typer)**
- Use `ctx.obj` without typing
- Simple, but loses IDE support
- _(Not recommended)_

**C. Singleton pattern**
- Global state object initialized on module load
- Avoids context passing, but hard to test
- _(Not recommended)_

**Synthesis recommendation:** 🔍 **Option A (Typed AppState dataclass)**
- Provides type safety and IDE autocompletion
- Easy to test (pass mock AppState)
- Consistent with best practices

**Sub-questions:**
- Should configuration be read from file, environment variables, or both?
- Should API credentials be stored in config file or required as env vars?
- Should the CLI support multiple File Search stores for different libraries?

**Confidence:** 🔍 1 provider identified this

---

### Q11: Result Display Layout Hierarchy

**Question:** How should search results balance information density with terminal readability? Show all metadata in compact list, or progressive disclosure (compact → detailed → full)?

**Why it matters:**
- Single result has 10+ fields (title, score, course, year, quarter, difficulty, instructor, topic, excerpt, citations)
- Terminal width (80-100 chars) limits horizontal space
- Need to decide which fields are essential vs on-demand

**Options identified by providers:**

**A. Compact list only (minimal info)**
- Show: rank, title, relevance score, course/year
- Fits in 80-column terminal
- User runs separate command for details
- _(Part of all provider proposals)_

**B. Detailed table (all metadata)**
- Show all fields in wide table
- Rich information, but exceeds terminal width
- Requires horizontal scrolling
- _(Not recommended)_

**C. Three-tier progressive disclosure**
- Tier 1: Compact list (rank, title, score, course/year)
- Tier 2: Detailed view on selection (all metadata, excerpt, citations)
- Tier 3: Full document (`library view <doc_id> --full`)
- Best balance of scannability and detail
- _(Proposed by: Perplexity)_

**Synthesis recommendation:** 🔍 **Option C (Three-tier progressive disclosure)**
- Default: Compact list for quick scanning
- Selection: Rich panel with full metadata and excerpt
- Full view: Entire document in pager

**Sub-questions:**
- Should compact list be interactive (arrow-key navigable) or just printed table?
- How long should excerpts be? 100 chars? 200? Truncate mid-sentence?
- Should topics, difficulty, instructor be shown in compact view or only detailed view?

**Confidence:** 🔍 1 provider identified this in detail

---

## Next Steps (Non-YOLO Mode)

**✋ PAUSED — Awaiting Your Decisions**

1. **Review these 11 questions** across 3 tiers
2. **Provide answers** (create CLARIFICATIONS-ANSWERED.md manually, or tell Claude your decisions in the next message)
3. **Then run:** `/gsd:plan-phase 3` to create execution plan

---

## Alternative: YOLO Mode

If you want Claude to auto-generate reasonable answers based on synthesis recommendations:

```bash
/meta-gsd:discuss-phase-ai 3 --yolo
```

This will:
- Auto-select recommended options (marked ✅ ⚠️ above)
- Generate CLARIFICATIONS-ANSWERED.md automatically
- Proceed to planning without pause

---

*Multi-provider synthesis: OpenAI + Gemini + Perplexity (with industry citations)*
*Generated: 2026-02-16*
*Non-YOLO mode: Human input required*
