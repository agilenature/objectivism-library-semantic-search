# CONTEXT.md — Phase 3: Search & CLI

**Generated:** 2026-02-16
**Phase Goal:** User can search the indexed library by meaning, filter by metadata, browse by structure, and see results with source citations -- all from a polished CLI interface
**Synthesis Source:** Multi-provider AI analysis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research)

---

## Overview

Phase 3 bridges the gap between the uploaded library (Phase 2) and end-user interaction by implementing semantic search, metadata filtering, structural navigation, and a polished CLI interface. The primary architectural challenge is **integrating two distinct systems**: local SQLite metadata/keyword search and remote Gemini semantic intelligence, making them feel like a unified search engine.

Three AI providers independently analyzed the requirements and converged on several critical gray areas that will block development if left unresolved. This synthesis organizes their findings by confidence level and priority.

**Confidence markers:**
- ✅ **Consensus** — All 3 providers identified this as critical
- ⚠️ **Recommended** — 2 providers identified this as important
- 🔍 **Needs Clarification** — 1 provider identified, potentially important

---

## Gray Areas Identified

### ✅ 1. Hybrid Search Ranking Strategy (Consensus)

**What needs to be decided:**
How to combine semantic search (Gemini vector similarity) with keyword/full-text search (SQLite FTS5) into a unified ranking when scores come from incompatible scales (cosine 0-1 vs BM25 0-100+).

**Why it's ambiguous:**
- Gemini File Search provides semantic search natively, but no indication it supports keyword search
- SQLite FTS5 provides fast keyword search, but no semantic understanding
- Three possible architectures: semantic-only, dual-system hybrid, or route-based query detection
- No guidance on whether hybrid search is necessary for a philosophy library or if semantic alone suffices

**Provider synthesis:**
- **OpenAI:** Recommends two-stage ranking with normalized scores (0.65 semantic + 0.35 keyword weighted sum) using min-max normalization, then stable tie-breakers
- **Gemini:** Suggests using Gemini for retrieval but SQLite for pre-filtering; avoid mathematical merging of incompatible scores; display results based on Gemini relevance only
- **Perplexity:** Recommends semantic-only for Phase 3 MVP, defer hybrid to Phase 4; if hybrid needed, use Reciprocal Rank Fusion (RRF) not score normalization

**Proposed implementation decision:**
**Phase 3 MVP: Semantic-only search via Gemini File Search.**
- Rationale: Philosophical queries are conceptual ("What is Rand's view of rationality?") not keyword-based
- Gemini's vector search handles synonyms and related concepts better than exact matching
- Simpler architecture, clearer performance baselines

**Phase 4 Enhancement: Implement hybrid search with RRF if user feedback indicates keyword queries fail.**
- Use Reciprocal Rank Fusion formula: `rankScore(d) = Σ 1/(k + rank_q(d))` where k=30-60
- RRF emphasizes rank consistency rather than score magnitude, making it robust to incompatible scales

**Open questions:**
- Is keyword search a hard requirement or nice-to-have? If users primarily ask conceptual questions, semantic-only may suffice
- What is acceptable latency? Hybrid search adds 100-200ms (two API calls)
- Should semantic and keyword be weighted equally, or should philosophical queries favor semantic relevance?

**Confidence:** ✅ All 3 providers agreed this is blocking

---

### ✅ 2. Metadata Filtering Architecture (Consensus)

**What needs to be decided:**
Whether to apply metadata filters (course, year, difficulty, topic) via Gemini's server-side `metadata_filter` parameter, via client-side SQLite queries, or both in combination.

**Why it's ambiguous:**
- Gemini File Search supports `metadata_filter` in API, but documentation doesn't specify pre-filter vs post-filter semantics
- SQLite has all metadata locally, enabling flexible queries
- Filtering at wrong layer wastes API calls or reduces search quality
- Unknown whether Gemini applies filters before semantic ranking (pre-filter) or after (post-filter)

**Provider synthesis:**
- **OpenAI:** Recommends defining strict normalized metadata schema with enumerations (difficulty: intro/intermediate/advanced) and validation; handle "unknown" gracefully
- **Gemini:** Identifies that Gemini File Search may not support structured SQL-like filtering unless metadata was embedded in text during upload; suggests local-first filtering (query SQLite for IDs, then pass to Gemini if API permits)
- **Perplexity:** Recommends hybrid two-stage filtering: simple single-field filters via Gemini `metadata_filter` (pre-filter), complex multi-field filters via SQLite client-side (post-filter)

**Proposed implementation decision:**
**Implement two-stage hybrid filtering:**

**Stage 1 – Gemini server-side filtering (simple filters):**
When user applies single-field filter (e.g., `--year 2023`), pass to Gemini's `metadata_filter` parameter:
```python
FileSearch(
    file_search_store_names=[store_name],
    metadata_filter='year=2023'
)
```
Assumption: Gemini implements pre-filtering (reduces vector space before semantic ranking), improving latency and relevance.

**Stage 2 – SQLite client-side filtering (complex queries):**
For complex filters combining multiple fields (e.g., `year=2023 AND difficulty>=300 AND topic LIKE 'Ethics%'`), retrieve results from Gemini with simple filter, then apply additional filters client-side via SQLite.

**Validation:** Run A/B tests comparing latency and result quality with/without filters to confirm pre-filtering behavior.

**Open questions:**
- What happens if Gemini metadata and SQLite metadata diverge? Is reconciliation needed?
- Should compound boolean filters (AND/OR) be supported in Gemini's `metadata_filter` syntax?
- Is metadata consistency a hard requirement, or can temporary divergence be tolerated?

**Confidence:** ✅ All 3 providers agreed this is blocking

---

### ✅ 3. Passage-Level Citation Format and Extraction (Consensus)

**What needs to be decided:**
How to structure passage-level citations for CLI display: chunk granularity, inline vs footnote style, metadata inclusion, and how to parse Gemini's `grounding_metadata` for source attribution.

**Why it's ambiguous:**
- Gemini's `groundingChunks` point to documents, not specific passages within them
- Unclear whether citations should show full document chunks (clutters interface) or brief excerpts (50-100 chars)
- Terminal width constraints limit formatting options (no footnotes like academic papers)
- Philosophy library users need course/year/instructor context, not just file names

**Provider synthesis:**
- **OpenAI:** Recommends pre-chunking documents during ingest (800-1200 tokens, 15% overlap) with stored byte offsets + heuristic headings; citations cite `doc + heading + chunk_index + (start_char, end_char)`
- **Gemini:** Recommends treating local SQLite as "Source of Truth" for display names; map Gemini URIs to local DB IDs immediately upon receipt; implement three-tier citation (inline + panel + metadata)
- **Perplexity:** Recommends three-tier system: (1) inline citations in response text `[1][2]`, (2) citation details panel below results with passage excerpts, (3) metadata-enriched source listing from SQLite

**Proposed implementation decision:**
**Implement three-tier citation system optimized for terminal display:**

**Tier 1 – Inline citations in response text:**
When Gemini's `groundingSupports` provide text segments, insert bracketed indices at segment boundaries:
```
According to Rand, rational self-interest[1] requires pursuing happiness[2].
```

**Tier 2 – Citation details panel below results:**
```
[1] "Introduction to Objectivism" (Intro to Epistemology, 2022, Year 3)
    Passage: "The virtue of rational self-interest requires..."

[2] "Atlas Shrugged: A Philosophical Reading" (Capitalism and Virtue, 2023)
    Passage: "The primacy of individual value-seeking..."
```

**Tier 3 – Metadata-enriched source listing:**
```
Sources:
[1] intro-to-objectivism.txt
    Course: Intro to Epistemology | Year: 2022 | Quarter: Q3 | Difficulty: 300
[2] atlas-shrugged-reading.txt
    Course: Capitalism and Virtue | Year: 2023 | Quarter: Q1 | Difficulty: 400
```

**Implementation:**
1. Maintain SQLite mapping table: `file_name → metadata (course, year, quarter, difficulty, instructor)`
2. Parse Gemini's `grounding_metadata.groundingChunks` to extract file names/URIs
3. Use Rich `Panel` for inline citations, `Table` for citation details
4. Validate cited files exist in File Search store to catch hallucinations

**Open questions:**
- Should excerpts be full chunks (200+ chars) or brief (50-100 chars) to fit terminal width?
- How should Gemini's automatic citations be validated for accuracy?
- Should cross-references between documents be auto-discovered and displayed?

**Confidence:** ✅ All 3 providers agreed this is blocking

---

### ✅ 4. CLI Command Structure and User Experience (Consensus)

**What needs to be decided:**
Whether to implement `search`, `filter`, and `browse` as separate commands, subcommands of `query`, flags on unified `find` command, or some hybrid — and whether filters are stateful (persistent across commands) or stateless (explicit flags).

**Why it's ambiguous:**
- Requirements list three distinct interactions: search (semantic), filter (metadata-only), browse (structural navigation)
- Success criteria show `search "query" --course "X"` (stateless flags), but INTF-04 mentions separate "filter command"
- Stateful filters (set once, apply to all searches) add complexity but improve interactive UX
- Unclear whether CLI is primarily interactive or used in scripts

**Provider synthesis:**
- **OpenAI:** Recommends NOT implementing persistent filter state in v1; use filtering as flags on `search` and `browse` only; provide `filter` as alias that prints help/examples
- **Gemini:** Recommends merging `filter` into `search` (no standalone command); `browse` is for metadata discovery using SQLite only (no Gemini), with drill-down: `browse` → list courses → `browse --course OPAR` → list lectures
- **Perplexity:** Recommends primary `search` command with optional filters/browsing as secondary; `search <query> [--filter]`, `filter <metadata>`, `browse <structure> [--filter]` following progressive disclosure

**Proposed implementation decision:**
**Implement three commands following progressive disclosure:**

```bash
# Primary interaction: Semantic search with optional metadata filters
library search "Rand's objectivity of value" --filter year:2022 --filter topic:Ethics

# Metadata-only query: No semantic content, just filters
library filter year:2023 --course "Intro to Epistemology"

# Structural navigation: Interactive drill-down or direct path
library browse courses
library browse --course "OPAR" --year 2023
```

**Key decisions:**
- **Stateless filters:** All filters are explicit flags, not persistent state (simpler, scriptable)
- **`filter` command exists but is metadata-only:** Lists documents matching filters without semantic ranking
- **`browse` is interactive:** Shows hierarchical structure (courses → years → quarters → documents)
- **Consistent flag syntax:** `--filter field:value` or `--course "X" --year 2023`

**Open questions:**
- Should filters persist across multiple searches in one session, or always be explicit?
- Is the CLI primarily interactive (human use) or scripted (automation)?
- Should `browse` results include document previews or just names and counts?

**Confidence:** ✅ All 3 providers agreed this is blocking

---

### ✅ 5. Error Handling and API Resilience (Consensus)

**What needs to be decided:**
How to handle Gemini API rate limits (429), timeouts, transient failures, and degraded states — specifically whether to retry automatically, show errors immediately, or fall back to SQLite search.

**Why it's ambiguous:**
- No documentation on Gemini File Search rate limits or error codes
- Three strategies: eager failure (simple, poor UX), transparent retry (better reliability, hidden latency), fallback with degradation (best UX, complex)
- Unclear whether google-genai SDK handles retries automatically
- Philosophy researchers may tolerate 10-30s delays, but casual users expect <2s

**Provider synthesis:**
- **OpenAI:** Recommends centralized Gemini client with tenacity retry (exponential backoff min 0.5s, max 8s, 5 attempts, retry on 429/5xx/timeouts), global rate limiter (1 req/sec), Rich panel for errors, circuit breaker after 5 consecutive failures
- **Gemini:** Does not explicitly address error handling
- **Perplexity:** Recommends exponential backoff with jitter (prevents thundering herd), user feedback via Rich "[yellow]⟳ Retrying...[/yellow]", timeout 30s, respect `Retry-After` header on 429

**Proposed implementation decision:**
**Implement automatic retry with exponential backoff + jitter and user feedback:**

```python
@retry_with_backoff(RetryConfig(max_attempts=3, base_delay=0.5, jitter=True))
def search_gemini(query: str, filter_expr: str = None):
    """Call Gemini File Search API with automatic retry."""
    # Implementation
    pass
```

**Key features:**
1. **Automatic retries:** Up to 3 attempts with exponential backoff (0.5s, 1s, 2s) + random ±50% jitter
2. **User feedback:** Display "[yellow]⟳ Retrying (1/3) in 0.5s...[/yellow]" via Rich
3. **Timeout:** 30 seconds global timeout on API calls
4. **Rate limit handling:** Respect `Retry-After` header on 429, or use exponential backoff if missing
5. **Circuit breaker (optional):** After 5 consecutive failures, disable Gemini for 60s cooldown, fall back to SQLite (if implemented)

**Open questions:**
- Should the system ever silently degrade to SQLite search, or always inform the user?
- What is acceptable timeout? 30s for complex queries, or must be <2s?
- Should repeated failures eventually give up, or keep retrying indefinitely?

**Confidence:** ✅ All 3 providers agreed this is important

---

### ⚠️ 6. Gemini Authentication and Configuration (Recommended)

**What needs to be decided:**
How the CLI obtains Gemini API credentials (environment variable, keychain, config file), where they're stored, and how errors are surfaced to avoid accidental key leakage.

**Why it's ambiguous:**
- Requirements mention `google-genai SDK` but not auth mode
- Multi-user machines may need different auth strategies
- Config files risk exposing secrets in version control
- Unclear whether to support Google ADC (service accounts) or just API keys

**Provider synthesis:**
- **OpenAI:** Recommends environment-based API key only (`GEMINI_API_KEY`) for v1, read at CLI startup, fail fast with actionable error; provide `--diagnose` command that confirms "key present" without revealing it
- **Gemini:** Does not explicitly address
- **Perplexity:** Mentions API key management but defers to broader configuration strategy

**Proposed implementation decision:**
**Use system keychain for API key storage (consistent with Phase 2 decision):**

Phase 2 used system keychain for Gemini API key (decision 02-03). Continue this pattern:
```bash
# Store key (one-time setup)
security add-generic-password -s "objlib-gemini" -a "api_key" -w "YOUR_KEY"

# CLI reads from keychain at startup
api_key = keyring.get_password("objlib-gemini", "api_key")
```

**Fallback to environment variable:**
If keychain fails, try `GEMINI_API_KEY` environment variable as fallback.

**Error handling:**
Display actionable error if no key found:
```
❌ Gemini API key not found
   Run: library config set-api-key
   Or: export GEMINI_API_KEY="your-key"
```

**Open questions:**
- Should the CLI support `.env` files via `python-dotenv`, or strictly keychain + env vars?
- Should Google ADC (service accounts) be supported for deployment scenarios?
- Is this tool expected to run in CI/CD where key handling needs stricter controls?

**Confidence:** ⚠️ 2 providers (OpenAI, Perplexity) identified this as important

---

### ⚠️ 7. Result Ranking and Relevance Scoring (Recommended)

**What needs to be decided:**
How to interpret and display Gemini's relevance scores (cosine similarity, dot product, Euclidean distance?), whether to normalize them, and whether to apply secondary ranking criteria (recency, difficulty, popularity).

**Why it's ambiguous:**
- Gemini documentation doesn't specify which distance metric or score ranges
- Raw similarity scores (e.g., 0.7 cosine) are not meaningful to end users
- Philosophy library may benefit from difficulty-aware ranking (intro before advanced)
- Unclear whether to show raw scores, normalized scores, or hide scores entirely

**Provider synthesis:**
- **OpenAI:** Recommends multi-factor ranking: 70% semantic relevance + 15% difficulty match + 10% recency + 5% popularity; normalize scores to 0-100% for display; stable tie-breakers
- **Gemini:** Does not merge scores; display results based on Gemini's native relevance, annotated with local metadata
- **Perplexity:** Recommends normalizing to 0-100% scale for comprehension, but multi-factor ranking (semantic + difficulty + recency) with weighted sum; display visual bar graph `━━━━━━━━○○ 74%`

**Proposed implementation decision:**
**Display relevance scores normalized to 0-100%, but keep ranking simple (Gemini-native) for Phase 3 MVP.**

**Phase 3 MVP:**
- Use Gemini's native semantic ranking
- Normalize scores to 0-100% for display: `int(cosine_similarity * 100)`
- Display visual indicator: `━━━━━━━━○○ 87% relevance`
- Stable tie-breaker: higher semantic score → recency → alphabetical

**Phase 4 Enhancement (if needed):**
- Implement multi-factor ranking: `0.70*semantic + 0.15*difficulty_match + 0.10*recency + 0.05*popularity`
- Allow users to customize weights via config

**Open questions:**
- Should the CLI allow users to customize ranking weights for power users?
- How should ties be broken? Recency, difficulty, alphabetical?
- Is 0-100% scale misleading if 70% is actually very good?

**Confidence:** ⚠️ 2 providers (OpenAI, Perplexity) identified this as important

---

### ⚠️ 8. Chunk Handling and Context Extraction (Recommended)

**What needs to be decided:**
Whether to control Gemini's chunk size via `chunking_config`, accept defaults, and how to display context when retrieved passages are longer than terminal width allows.

**Why it's ambiguous:**
- Gemini File Search auto-chunks documents; optimal chunk size for philosophy texts unknown
- Smaller chunks improve precision but fragment context; larger chunks preserve context but reduce precision
- NVIDIA research suggests page-level chunking for some domains, 512-token for others
- Terminal width (80-100 chars) limits excerpt display

**Provider synthesis:**
- **OpenAI:** Recommends pre-chunking during Phase 2 ingest (800-1200 tokens, 15% overlap) with stored byte offsets; citations cite chunk boundaries
- **Gemini:** Does not explicitly address chunking
- **Perplexity:** Recommends accepting Gemini's default chunking for Phase 3, conduct empirical testing in Phase 4 using NVIDIA's methodology if results are too fragmented or too long

**Proposed implementation decision:**
**Accept Gemini's default chunking for Phase 3 MVP.**

Rationale: Premature optimization. Test with defaults first, gather user feedback on whether excerpts are too fragmented or too verbose.

**Phase 4 (if needed):**
Configure `chunking_config` based on empirical testing:
```python
chunking_config = types.ChunkingConfig(
    strategy=types.ChunkingStrategy.FIXED_SIZE,
    max_tokens_per_chunk=1000,
    overlap_tokens=150
)
```

**Result display:**
Truncate excerpts to terminal width with indicator:
```
"The chapter introduces Rand's concept of objectivity...
    [... (see full document) ...]"
```

**Open questions:**
- What is acceptable preview length? 500 chars? 1000? Adapt to terminal width?
- Should chunk boundaries respect conceptual boundaries (paragraphs, sections) rather than token counts?
- Should users be able to request full document after seeing preview (e.g., `library view <doc_id>`)?

**Confidence:** ⚠️ 2 providers (Gemini, Perplexity) identified this as relevant

---

### ⚠️ 9. Cross-Reference Discovery Implementation (Recommended)

**What needs to be decided:**
How to implement SRCH-08 "cross-reference discovery (find related discussions automatically)" — specifically whether to show related documents automatically in all search results or on-demand, and how to define "related."

**Why it's ambiguous:**
- "Automatically" could mean for every search result (expensive, N+1 query problem) or triggered by user action
- "Related" undefined: shared topics? Shared authors? Vector similarity? Citation graph?
- Could block Phase 3 if treated as hard requirement for all searches
- Overlaps with Phase 4 advanced features

**Provider synthesis:**
- **OpenAI:** Recommends "More like this" using embedding similarity over top results; cache related results in SQLite; fetch top K similar chunks/docs via Gemini using chunk text as query; make it on-demand not automatic
- **Gemini:** Recommends not showing automatically in main list; show search results in list, user selects result ID (e.g., `search inspect <ID>`), then perform "More like this" or metadata query
- **Perplexity:** Does not explicitly address

**Proposed implementation decision:**
**Implement SRCH-08 as on-demand "More like this," not automatic.**

**Phase 3 MVP:**
- Do NOT show cross-references in main search results (avoids N+1 queries)
- Provide detail view command: `library view <result_id> --show-related`
- When user requests related documents, perform semantic similarity query using selected document's text

**Implementation:**
```bash
# User searches and sees results
library search "rational egoism"

# User selects result #3 to see details and related documents
library view 3 --show-related

# System queries Gemini for documents similar to result #3's text
```

**Optional Phase 4 enhancement:**
- Build citation graph (if documents reference each other)
- Cache related results: `related_cache(source_chunk_id, related_chunk_id, score, computed_at)`

**Open questions:**
- Is SRCH-08 required for Phase 3 acceptance, or can it be minimal/basic?
- Should cross-references be within same course only, or across whole library?
- Do we need to explain why something is related (shared terms/topics) for trust?

**Confidence:** ⚠️ 2 providers (OpenAI, Gemini) identified this

---

### 🔍 10. Typer CLI State Management (Needs Clarification)

**What needs to be decided:**
How to store and pass the Gemini API client and SQLite connection across Typer commands while maintaining type safety and testability.

**Why it's ambiguous:**
- Typer's context object (`ctx.obj`) is untyped, defeating IDE autocompletion
- No standard pattern for initializing expensive resources (API clients) that persist for CLI lifetime
- Unclear whether commands should be async (for API calls) or sync (for Typer simplicity)

**Provider synthesis:**
- **OpenAI:** Does not explicitly address
- **Gemini:** Does not explicitly address
- **Perplexity:** Recommends typed AppState dataclass initialized in `@app.callback()`, accessed via type-hinted context parameter; use synchronous Typer commands with thin async runner only where needed

**Proposed implementation decision:**
**Create typed AppState dataclass initialized in callback:**

```python
@dataclass
class AppState:
    gemini_client: Client
    store_name: str
    sqlite_db: sqlite3.Connection
    config: dict

@app.callback(invoke_without_command=True)
def initialize_app(ctx: typer.Context, config_path: str = "~/.objlib/config.json"):
    """Initialize application state."""
    config = load_config(config_path)
    state = AppState(
        gemini_client=Client(api_key=get_api_key()),
        store_name=config['file_search_store'],
        sqlite_db=sqlite3.connect(config['sqlite_path']),
        config=config,
    )
    ctx.obj = state

def get_app_state(ctx: typer.Context) -> AppState:
    """Type-hinted helper for accessing state."""
    if ctx.obj is None:
        raise typer.Exit("State not initialized", code=1)
    return ctx.obj

@app.command()
def search(query: str, ctx: typer.Context):
    state = get_app_state(ctx)  # Type-hinted
    results = search_gemini(state.gemini_client, query)
    display_results(results, state.sqlite_db)
```

**Open questions:**
- Should configuration be read from file, environment variables, or both?
- Should API credentials be stored in config file or required as env vars for security?
- Should the CLI support multiple File Search stores for different libraries?

**Confidence:** 🔍 1 provider (Perplexity) identified this

---

### 🔍 11. Result Display Layout and Information Hierarchy (Needs Clarification)

**What needs to be decided:**
How to balance comprehensive information (title, score, metadata, excerpt, citations) with terminal width constraints (80-100 columns) when displaying search results.

**Why it's ambiguous:**
- A single result could include 10+ fields (title, relevance, course, year, quarter, difficulty, instructor, topic, excerpt, citations)
- Displaying all fields exceeds typical terminal width
- Need to decide which fields are essential (always shown), secondary (show if space), tertiary (on-demand)

**Provider synthesis:**
- **OpenAI:** Recommends Rich table with Rank, Score, Source, Course/Year/Qtr, Heading, Excerpt columns; default top 10 results with `--limit`/`--offset`; 300-500 char excerpts with highlights
- **Gemini:** Does not explicitly address
- **Perplexity:** Recommends three-tier hierarchy: (1) compact list with minimal info, (2) detailed view on selection with expanded metadata, (3) full document via `library view <doc_id>`

**Proposed implementation decision:**
**Implement three-tier progressive disclosure:**

**Tier 1 – Compact result list (default):**
```
1. "Introduction to Objectivism"  [87%] ▓▓▓▓▓▓▓▓▓░  │ Epistemology, 2022
2. "Rational Egoism in Practice"  [74%] ▓▓▓▓▓░░░░░  │ Ethics, 2023
```

**Tier 2 – Detailed result (on selection):**
```bash
library view 1

╭─ Introduction to Objectivism ──────────────────────╮
│ Course:     Intro to Epistemology                  │
│ Year:       2022 | Quarter: Q3                     │
│ Difficulty: 300 (Intermediate)                     │
│ Relevance:  87% ▓▓▓▓▓▓▓▓▓░                         │
├────────────────────────────────────────────────────┤
│ "The chapter introduces Rand's concept..."         │
╰────────────────────────────────────────────────────╯
```

**Tier 3 – Full document:**
```bash
library view intro-to-objectivism.txt --full
```

**Open questions:**
- Should compact list be interactive (arrow-key navigable) or just printed table?
- How long should excerpts be? 100 chars? 200? Truncate mid-sentence?
- Should topics, difficulty, instructor be shown in compact view or only detailed view?

**Confidence:** 🔍 1 provider (Perplexity) identified this in detail

---

## Summary: Decision Checklist

Before planning, confirm:

**Tier 1 (Blocking — Must Decide):**
- [ ] Hybrid search strategy: Semantic-only MVP or dual-system from start?
- [ ] Metadata filtering: Server-side (Gemini) vs client-side (SQLite) vs both?
- [ ] Citation format: Three-tier (inline + panel + metadata) acceptable?
- [ ] CLI commands: Three separate commands (search, filter, browse) or unified?
- [ ] Error handling: Automatic retry with backoff + user feedback?

**Tier 2 (Important — Should Decide for Quality):**
- [ ] Authentication: System keychain (consistent with Phase 2) or environment variables?
- [ ] Result ranking: Gemini-native scores only, or multi-factor ranking?
- [ ] Chunking: Accept Gemini defaults or configure custom chunk sizes?
- [ ] Cross-references: On-demand "More like this" or always shown?

**Tier 3 (Polish — Can Defer to Implementation):**
- [ ] State management: Typed AppState dataclass in Typer callback?
- [ ] Display layout: Three-tier progressive disclosure (compact → detailed → full)?

---

## Next Steps

**Non-YOLO Mode (current):**
1. ✅ Review this CONTEXT.md
2. ⏭ Answer questions in CLARIFICATIONS-NEEDED.md
3. ⏭ Create CLARIFICATIONS-ANSWERED.md with your decisions
4. ⏭ Run `/gsd:plan-phase 3` to create execution plan

**Alternative (YOLO Mode):**
Run `/meta-gsd:discuss-phase-ai 3 --yolo` to auto-generate answers

---

*Multi-provider synthesis by: OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research*
*Generated: 2026-02-16*
