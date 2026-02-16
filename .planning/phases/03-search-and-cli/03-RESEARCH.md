# Phase 3: Search & CLI - Research

**Researched:** 2026-02-16
**Domain:** Gemini File Search querying, Typer CLI, Rich terminal formatting, metadata filtering
**Confidence:** HIGH (SDK types verified from installed google-genai v1.63.0, codebase fully inspected)

## Summary

Phase 3 transforms the uploaded Gemini File Search store (Phase 2) into a user-facing CLI. The core challenge is bridging two systems: calling `client.models.generate_content()` with a `FileSearch` tool to perform semantic search, then enriching results with local SQLite metadata for display. The google-genai SDK v1.63.0 provides typed Pydantic models for all grounding response structures (`GroundingMetadata`, `GroundingChunk`, `GroundingSupport`, `Segment`) which map directly to the three-tier citation display.

The existing codebase already has Typer v0.23 with Rich v14.3, a Database class with WAL-mode SQLite, keyring authentication, and a `GeminiFileSearchClient` that manages store creation and file imports. Phase 3 adds three commands (`search`, `filter`, `browse`) to the existing `cli.py`, a new `search/` subpackage for Gemini query logic and display formatting, and extends the `Database` class with metadata query methods for browse/filter.

**Primary recommendation:** Extend the existing `cli.py` with new commands, add `src/objlib/search/` subpackage (client, formatter, citations), use synchronous Typer commands with `asyncio.run()` wrappers for Gemini API calls.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **Hybrid Search:** Semantic-only (Gemini File Search alone), NO keyword/FTS5 in Phase 3. Defer hybrid to Phase 4. 30-second timeout, 10-30s acceptable latency.

2. **Metadata Filtering:** Two-stage hybrid. Simple filters -> Gemini `metadata_filter` parameter. Complex filters -> SQLite client-side post-filter. Eventual consistency acceptable (SQLite is source of truth).

3. **Citation Format:** Three-tier progressive disclosure. Tier 1: Inline citations [1][2]. Tier 2: Citation details panel (100-150 char excerpts). Tier 3: Full source listing from SQLite. Use Rich Panel + Table.

4. **CLI Commands:** Three separate commands, stateless filters. `library search "query" [--filter field:value]`, `library filter field:value` (metadata-only), `library browse [--course X]` (structural navigation). No persistent state between commands.

5. **Error Handling:** Automatic retry with exponential backoff. 3 attempts: 0.5s, 1s, 2s with +/-50% jitter. Display retry status via Rich. No silent degradation to SQLite.

6. **Authentication:** System keychain (consistent with Phase 2). Keyring library primary, GEMINI_API_KEY env var fallback. No .env files.

7. **Result Ranking:** Gemini-native only, normalize to 0-100%. Visual bar graph: `━━━━━━━━○○ 87%`. Tie-breaker: score -> recency -> alphabetical.

8. **Chunking:** Accept Gemini defaults (no custom config). Excerpt truncation: 100-150 chars, terminal width adaptive.

9. **Cross-References:** On-demand "More like this". `library view <result_id> --show-related`. NOT automatic in main results.

10. **State Management:** Typed AppState dataclass. `@dataclass AppState(gemini_client, sqlite_db, store_name, config)`. Initialize in `@app.callback()`.

11. **Display Layout:** Three-tier progressive disclosure. Compact list (rank, title, score, course/year). Detailed view (`library view <id>`). Full document (`library view <id> --full`).

### Claude's Discretion

- Internal module organization within `src/objlib/`
- Specific Rich color scheme choices
- Helper function signatures and internal abstractions
- Test organization and fixtures
- Error message wording

### Deferred Ideas (OUT OF SCOPE)

- Keyword/full-text search (FTS5) -- Phase 4
- Reciprocal Rank Fusion (RRF) -- Phase 4
- Multi-factor ranking (semantic + difficulty + recency weighted) -- Phase 4
- Custom chunking configuration -- Phase 4
- Interactive arrow-key navigation -- Phase 4
- Citation graph caching -- Phase 4
- Circuit breaker for search (already exists for upload) -- Phase 4
- JSON output mode for scripting -- Phase 4
</user_constraints>

## Standard Stack

### Core (Already Installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| google-genai | 1.63.0 | Gemini File Search querying via `generate_content` | Only SDK for File Search stores |
| typer | 0.23.0 | CLI framework with type hints | Already used in Phase 1/2 CLI |
| rich | 14.3.2 | Terminal formatting (Panel, Table, Console) | Already used, provides all needed widgets |
| tenacity | 9.1.4 | Retry with exponential backoff + jitter | Already a dependency, used in Phase 2 upload |
| keyring | 25.7.0 | System keychain for API key | Already used in Phase 2 auth |
| aiosqlite | 0.22.1 | Async SQLite access | Already used in Phase 2 state management |

### Supporting (Already Installed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sqlite3 (stdlib) | 3.13 | Synchronous SQLite for browse/filter | CLI commands are sync; use for metadata queries |
| shutil (stdlib) | 3.13 | `get_terminal_size()` for adaptive truncation | Width-adaptive excerpt display |
| json (stdlib) | 3.13 | Parse metadata_json from SQLite | Every result enrichment step |
| asyncio (stdlib) | 3.13 | `asyncio.run()` wrapper for Gemini calls | Bridge sync Typer -> async genai SDK |

### No New Dependencies Required
Phase 3 uses exclusively libraries already in `pyproject.toml`. No additions needed.

**Installation:** No changes to `pyproject.toml` dependencies.

## Architecture Patterns

### Recommended Project Structure
```
src/objlib/
├── cli.py                    # Extend: add search, filter, browse, view commands
├── config.py                 # Extend: add get_api_key() with env var fallback
├── database.py               # Extend: add metadata query methods for browse/filter
├── models.py                 # Extend: add SearchResult, Citation, AppState dataclasses
├── search/                   # NEW subpackage
│   ├── __init__.py
│   ├── client.py             # GeminiSearchClient (query via generate_content)
│   ├── formatter.py          # Result formatting, score bars, truncation
│   └── citations.py          # Citation extraction from grounding_metadata
├── upload/                   # Existing (Phase 2)
│   └── ...
└── __init__.py
```

### Pattern 1: Gemini File Search Query via generate_content
**What:** Query the File Search store by passing it as a tool to `generate_content`
**When to use:** Every `search` command invocation
**Confidence:** HIGH (verified from SDK types + official docs)

```python
# Source: Verified from google-genai v1.63.0 SDK types + ai.google.dev/gemini-api/docs/file-search
from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)

response = client.models.generate_content(
    model="gemini-2.5-flash",  # or gemini-2.5-pro for higher quality
    contents="What is the Objectivist view of rights?",
    config=types.GenerateContentConfig(
        tools=[
            types.Tool(
                file_search=types.FileSearch(
                    file_search_store_names=["fileSearchStores/abc123"],
                    metadata_filter="course=OPAR",  # AIP-160 syntax
                    # top_k=10,  # Optional: limit chunks returned
                )
            )
        ]
    )
)

# Access response
text = response.text  # Convenience property: concatenated text
grounding = response.candidates[0].grounding_metadata  # GroundingMetadata object
```

### Pattern 2: Grounding Metadata Extraction
**What:** Extract citations from the GroundingMetadata response
**When to use:** After every successful search query
**Confidence:** HIGH (verified field names from SDK Pydantic model_fields)

```python
# Source: Verified from types.GroundingMetadata.model_fields, types.GroundingChunk.model_fields
# types.GroundingSupport.model_fields, types.Segment.model_fields

# GroundingMetadata structure (all fields Optional):
#   .grounding_chunks: list[GroundingChunk]
#   .grounding_supports: list[GroundingSupport]
#   .retrieval_queries: list[str]
#   .web_search_queries: list[str]  (not used for File Search)
#
# GroundingChunk structure:
#   .retrieved_context: GroundingChunkRetrievedContext  (for File Search)
#   .web: GroundingChunkWeb  (for Google Search, not used)
#
# GroundingChunkRetrievedContext structure:
#   .uri: str          -- Gemini file URI
#   .title: str        -- Display name set during upload
#   .text: str         -- Retrieved text snippet
#   .document_name: str -- Full resource name
#   .rag_chunk: RagChunk (optional, contains .text and .page_span)
#
# GroundingSupport structure:
#   .grounding_chunk_indices: list[int]  -- indices into grounding_chunks
#   .confidence_scores: list[float]      -- 0.0-1.0 per chunk
#   .segment: Segment
#
# Segment structure:
#   .part_index: int
#   .start_index: int  -- byte offset (inclusive)
#   .end_index: int    -- byte offset (exclusive)
#   .text: str         -- the text segment

def extract_citations(grounding_metadata):
    """Extract structured citations from Gemini grounding metadata."""
    if not grounding_metadata or not grounding_metadata.grounding_chunks:
        return []

    citations = []
    for i, chunk in enumerate(grounding_metadata.grounding_chunks):
        ctx = chunk.retrieved_context
        if ctx:
            citations.append({
                "index": i,
                "title": ctx.title,      # display_name from upload
                "uri": ctx.uri,           # Gemini file URI
                "text": ctx.text,         # Retrieved passage text
                "document_name": ctx.document_name,
            })
    return citations

def extract_confidence_map(grounding_metadata):
    """Map text segments to cited chunks with confidence scores."""
    if not grounding_metadata or not grounding_metadata.grounding_supports:
        return []

    supports = []
    for support in grounding_metadata.grounding_supports:
        supports.append({
            "chunk_indices": support.grounding_chunk_indices or [],
            "confidence_scores": support.confidence_scores or [],
            "segment_text": support.segment.text if support.segment else "",
            "start_index": support.segment.start_index if support.segment else 0,
            "end_index": support.segment.end_index if support.segment else 0,
        })
    return supports
```

### Pattern 3: AIP-160 Metadata Filter Syntax
**What:** Filter queries using Google's AIP-160 filter standard
**When to use:** When user provides `--filter` flags on search command
**Confidence:** HIGH (verified from SDK schema + google.aip.dev/160)

```python
# Source: google.aip.dev/160, FileSearch.model_json_schema()['properties']['metadataFilter']

# Simple equality (string):
metadata_filter = 'course="OPAR"'

# Simple equality (numeric):
metadata_filter = 'year=2023'

# AND logic (combine multiple filters):
metadata_filter = 'course="OPAR" AND year=2023'

# Comparison operators:
metadata_filter = 'year>=2020 AND year<=2023'

# OR logic:
metadata_filter = 'course="OPAR" OR course="ITOE"'

# Wildcards:
metadata_filter = 'course="Ancient Greece*"'

# Has operator (field exists):
metadata_filter = 'difficulty:*'

# Mapping user --filter flags to AIP-160:
def build_metadata_filter(filters: list[str]) -> str | None:
    """Convert CLI --filter field:value pairs to AIP-160 syntax.

    Supports:
      field:value     -> field="value" (string) or field=value (numeric)
      field:>value    -> field>value
      field:>=value   -> field>=value
    """
    if not filters:
        return None

    parts = []
    for f in filters:
        key, _, value = f.partition(":")
        if not key or not value:
            continue

        # Detect comparison operators
        if value.startswith(">=") or value.startswith("<=") or value.startswith(">") or value.startswith("<"):
            parts.append(f"{key}{value}")
        else:
            # Try numeric
            try:
                int(value)
                parts.append(f"{key}={value}")
            except ValueError:
                parts.append(f'{key}="{value}"')

    return " AND ".join(parts) if parts else None
```

### Pattern 4: Typed AppState with Typer Callback
**What:** Initialize shared state once, pass to all commands via ctx.obj
**When to use:** CLI app initialization
**Confidence:** HIGH (verified Typer v0.23 supports this pattern, existing cli.py uses same patterns)

```python
# Source: Typer docs, verified with existing cli.py patterns
from dataclasses import dataclass
from google import genai

@dataclass
class AppState:
    """Shared state across all CLI commands."""
    gemini_client: genai.Client
    store_name: str
    db_path: str
    terminal_width: int

app = typer.Typer(help="Objectivism Library - Search, browse, and explore")

@app.callback(invoke_without_command=True)
def init(
    ctx: typer.Context,
    store: str = typer.Option("objectivism-library-v1", "--store", "-s"),
    db_path: Path = typer.Option(Path("data/library.db"), "--db", "-d"),
) -> None:
    """Initialize Gemini client and database connections."""
    # Get API key (keyring primary, env var fallback)
    api_key = _get_api_key()  # from config.py

    ctx.obj = AppState(
        gemini_client=genai.Client(api_key=api_key),
        store_name=store,
        db_path=str(db_path),
        terminal_width=shutil.get_terminal_size().columns,
    )

def get_state(ctx: typer.Context) -> AppState:
    """Type-safe accessor for AppState from context."""
    if ctx.obj is None:
        raise typer.Exit(code=1)
    return ctx.obj
```

### Pattern 5: Score Bar Visualization
**What:** Unicode bar graph for relevance scores
**When to use:** Compact result list display
**Confidence:** HIGH (pure Python/Rich, no external dependency)

```python
def score_bar(score: float, width: int = 10) -> str:
    """Render a visual score bar: ━━━━━━━━○○ 87%

    Args:
        score: 0.0-1.0 confidence score from Gemini
        width: Number of bar characters

    Returns:
        Formatted string like '━━━━━━━━○○ 87%'
    """
    pct = int(score * 100)
    filled = round(score * width)
    empty = width - filled
    return f"{'━' * filled}{'○' * empty} {pct}%"
```

### Pattern 6: Retry with Exponential Backoff + Jitter
**What:** Retry Gemini API calls with user feedback
**When to use:** Every Gemini query (search, view --show-related)
**Confidence:** HIGH (tenacity v9.1.4 verified, pattern already used in Phase 2)

```python
# Source: tenacity docs, existing upload/client.py patterns
import random
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep,
)
from rich.console import Console

console = Console()

def _log_retry(retry_state):
    """Display retry status via Rich console."""
    attempt = retry_state.attempt_number
    wait = retry_state.next_action.sleep  # seconds until next retry
    console.print(
        f"[yellow]Retrying search ({attempt}/3) in {wait:.1f}s...[/yellow]"
    )

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=2.0),  # 0.5s, 1s, 2s
    retry=retry_if_exception_type((Exception,)),  # Refine to specific errors
    before_sleep=_log_retry,
)
def query_gemini_with_retry(client, model, contents, config):
    """Query Gemini with automatic retry and jitter."""
    # Add manual jitter (+/- 50%) since tenacity's wait_exponential
    # doesn't include jitter by default in older patterns
    return client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )
```

**Note:** tenacity v9.1+ has `wait_exponential_jitter()` which combines exponential + jitter:
```python
from tenacity import wait_exponential_jitter
wait=wait_exponential_jitter(initial=0.5, max=2.0, jitter=0.5)
```

### Pattern 7: SQLite Hierarchical Queries for Browse
**What:** Query metadata_json via json_extract for structural navigation
**When to use:** `browse` command
**Confidence:** HIGH (verified on actual database with json_extract working)

```python
# Source: Verified against actual data/library.db schema

# List all courses with file counts
SELECT json_extract(metadata_json, '$.course') as course,
       COUNT(*) as file_count
FROM files
WHERE json_extract(metadata_json, '$.category') = 'course'
  AND status != 'LOCAL_DELETE'
GROUP BY course
ORDER BY course

# List files in a specific course
SELECT file_path, filename, metadata_json
FROM files
WHERE json_extract(metadata_json, '$.course') = ?
  AND status != 'LOCAL_DELETE'
ORDER BY json_extract(metadata_json, '$.lesson_number'),
         json_extract(metadata_json, '$.year'),
         json_extract(metadata_json, '$.quarter'),
         json_extract(metadata_json, '$.week')

# List categories with counts (top-level browse)
SELECT json_extract(metadata_json, '$.category') as category,
       COUNT(*) as count
FROM files
WHERE metadata_json IS NOT NULL AND status != 'LOCAL_DELETE'
GROUP BY category
ORDER BY count DESC
```

**Actual database contents (verified):**
- 866 course files across 76 unique courses
- 469 MOTM files
- 497 unknown category files
- 52 book files
- 18 files currently uploaded (small test batch), 1884 total

### Anti-Patterns to Avoid
- **Async Typer commands:** Typer does not natively support async commands. Use `asyncio.run()` inside sync command functions for Gemini API calls. Do NOT try `@app.command() async def search()`.
- **Holding DB connections across awaits:** The Phase 2 codebase avoids this (see `AsyncUploadStateManager` docs). For Phase 3, use synchronous `sqlite3` for metadata queries (they are fast, no async needed).
- **Merging scores from different systems:** Locked decision: use Gemini-native ranking only. Do NOT attempt to normalize or combine with SQLite-derived scores.
- **Persistent CLI state:** All filters are stateless explicit flags. Do NOT implement session state, history, or filter memory.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Retry logic | Custom retry loop with sleep | `tenacity.retry` decorator | Edge cases: jitter, max attempts, exception types, backoff calculation |
| Terminal width detection | Manual COLUMNS env var parsing | `shutil.get_terminal_size()` | Handles fallbacks, OS differences |
| API key storage | Config file or .env | `keyring.get_password()` | Security: encrypted OS keychain vs plaintext |
| CLI argument parsing | argparse or manual | Typer with type annotations | Already used, provides help text, validation |
| Terminal formatting | ANSI escape codes | Rich Panel, Table, Console | Already used, handles width, color, wrapping |
| JSON field extraction from SQLite | Python-side JSON parsing | `json_extract()` SQL function | SQLite does it natively, indexable |
| Score normalization | Custom min-max scaling | `int(confidence_score * 100)` | Gemini returns 0.0-1.0, just multiply |

**Key insight:** Every component needed is already in the project's dependency tree. Phase 3 adds zero new dependencies.

## Common Pitfalls

### Pitfall 1: Grounding Metadata May Be None
**What goes wrong:** `response.candidates[0].grounding_metadata` can be `None` if Gemini decides to answer without File Search results (e.g., trivial questions, or if no relevant documents found).
**Why it happens:** Gemini treats File Search as a tool it *may* use, not one it *must* use. Every field in GroundingMetadata is `Optional`.
**How to avoid:** Always check `grounding_metadata is not None` and `grounding_chunks is not None` before iterating. Provide a "No sources cited" fallback message.
**Warning signs:** `AttributeError: 'NoneType' has no attribute 'grounding_chunks'`

### Pitfall 2: Mapping Gemini File URIs to SQLite Records
**What goes wrong:** `GroundingChunkRetrievedContext.title` contains the `display_name` set during upload, but this may not match `file_path` in SQLite. `GroundingChunkRetrievedContext.uri` contains a Gemini-internal URI, not the local file path.
**Why it happens:** Phase 2 uploads use `filename` (e.g., `"Objectivism Seminar - Foundations - Year 1 - Q1 - Week 4.txt"`) as the display_name. SQLite stores full absolute `file_path`.
**How to avoid:** Build a lookup mapping: `filename -> file_path` from SQLite at initialization. Match `retrieved_context.title` (which is the upload display_name) against the `filename` column. The `gemini_file_uri` column in SQLite stores the URI from upload.
**Warning signs:** Citation shows raw filename instead of enriched metadata.

### Pitfall 3: Confidence Scores Are Per-Support, Not Per-Chunk
**What goes wrong:** Treating `confidence_scores` in `GroundingSupport` as a single relevance score for the document.
**Why it happens:** Each `GroundingSupport` maps a text *segment* to one or more chunks. The `confidence_scores` list is parallel to `grounding_chunk_indices` -- each score rates how well that specific chunk supports that specific text segment.
**How to avoid:** For document-level ranking, aggregate: average the confidence scores across all supports that reference a given chunk. For display, use the max confidence score per chunk.
**Warning signs:** All results show the same score, or scores seem arbitrary.

### Pitfall 4: AIP-160 Filter Syntax Requires Exact Field Names
**What goes wrong:** Filter like `metadata_filter="course_name=OPAR"` returns no results because the actual field is `course` (not `course_name`).
**Why it happens:** The metadata filter matches against `custom_metadata` keys set during Phase 2 upload. The upload client (`build_custom_metadata`) uses keys: `category`, `course`, `difficulty`, `quarter`, `date`, `year` (numeric), `week` (numeric), `quality_score` (numeric).
**How to avoid:** Document the exact filterable fields. Validate user-provided filter keys against the known set before sending to Gemini. Show helpful error if unknown field.
**Warning signs:** Filters silently return no results, or `INVALID_ARGUMENT` errors.

### Pitfall 5: Only 18 Files Currently Uploaded
**What goes wrong:** Search returns very few results or fails because only 18 of 1884 files are uploaded.
**Why it happens:** Phase 2 upload was tested with a small batch. The full library has not been uploaded yet.
**How to avoid:** Design and test with the small uploaded set. Include a `library status` enhancement showing "18/1884 files indexed" so users understand coverage. Search should work correctly with any subset.
**Warning signs:** Unexpected empty results for queries that should match.

### Pitfall 6: Typer ctx.obj Not Available Without Callback
**What goes wrong:** `ctx.obj` is `None` when a command runs, causing AttributeError.
**Why it happens:** The `@app.callback()` must run before any command. If `invoke_without_command=True` is not set, or if the callback raises an exception (e.g., missing API key), commands get `None`.
**How to avoid:** Use `invoke_without_command=True` on callback. Handle auth errors in callback with clear error message and `typer.Exit(code=1)`. Add the `get_state()` helper with explicit None check.
**Warning signs:** `AttributeError: 'NoneType' has no attribute 'gemini_client'`

### Pitfall 7: Terminal Width Breaks Table Layout
**What goes wrong:** Rich Table exceeds terminal width, causing wrapping that destroys alignment.
**Why it happens:** Fixed column widths that assume 120-char terminal on an 80-char terminal.
**How to avoid:** Use `Console(width=shutil.get_terminal_size().columns)`. Set `Table(expand=False)`. Truncate long values (title, excerpt) to `width - margin`. Test at 80-column width.
**Warning signs:** Garbled table output, line wrapping mid-cell.

## Code Examples

### Example 1: Complete Search Command Implementation

```python
# Source: Verified patterns from SDK types + existing cli.py structure

@app.command()
def search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Semantic search query")],
    filter: Annotated[
        list[str] | None,
        typer.Option("--filter", "-f", help="Metadata filter (field:value)"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max results")] = 10,
) -> None:
    """Search the library by meaning with optional metadata filters."""
    state = get_state(ctx)

    # Build metadata filter string (AIP-160)
    metadata_filter = build_metadata_filter(filter) if filter else None

    # Query Gemini
    config = types.GenerateContentConfig(
        tools=[
            types.Tool(
                file_search=types.FileSearch(
                    file_search_store_names=[state.store_name],
                    metadata_filter=metadata_filter,
                )
            )
        ]
    )

    try:
        response = query_with_retry(state.gemini_client, "gemini-2.5-flash", query, config)
    except Exception as e:
        console.print(f"[red]Search failed after 3 attempts:[/red] {e}")
        raise typer.Exit(code=1)

    # Extract citations from grounding metadata
    grounding = None
    if response.candidates:
        grounding = response.candidates[0].grounding_metadata

    citations = extract_citations(grounding)

    # Enrich with SQLite metadata
    with Database(state.db_path) as db:
        enriched = enrich_citations_from_db(citations, db)

    # Display results
    display_search_results(response.text, enriched, state.terminal_width)
```

### Example 2: Citation Enrichment from SQLite

```python
def enrich_citations_from_db(citations: list[dict], db: Database) -> list[dict]:
    """Match Gemini citations to SQLite metadata for rich display.

    The key mapping: GroundingChunkRetrievedContext.title matches
    the filename column in SQLite (set as display_name during upload).
    """
    # Build filename -> metadata lookup
    rows = db.conn.execute(
        "SELECT filename, file_path, metadata_json FROM files WHERE status = 'uploaded'"
    ).fetchall()
    lookup = {}
    for row in rows:
        lookup[row["filename"]] = {
            "file_path": row["file_path"],
            "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
        }

    for citation in citations:
        title = citation.get("title", "")
        match = lookup.get(title)
        if match:
            citation["file_path"] = match["file_path"]
            citation["metadata"] = match["metadata"]
        else:
            citation["file_path"] = None
            citation["metadata"] = {}

    return citations
```

### Example 3: Three-Tier Display with Rich

```python
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

def display_search_results(
    response_text: str,
    citations: list[dict],
    terminal_width: int,
) -> None:
    """Render three-tier citation display."""
    console = Console(width=terminal_width)

    # Tier 1: Response text with inline citations
    # Insert [1], [2] markers based on grounding_supports
    console.print(Panel(response_text, title="Search Results", border_style="cyan"))

    if not citations:
        console.print("[dim]No sources cited.[/dim]")
        return

    # Tier 2: Citation details panel
    console.print()
    for i, cite in enumerate(citations, 1):
        meta = cite.get("metadata", {})
        course = meta.get("course", "Unknown")
        year = meta.get("year", "")

        # Truncate excerpt to 100-150 chars at word boundary
        excerpt = cite.get("text", "")
        max_len = min(150, terminal_width - 20)
        if len(excerpt) > max_len:
            excerpt = excerpt[:max_len].rsplit(" ", 1)[0] + "..."

        console.print(f"[yellow][{i}][/yellow] [bold]{cite.get('title', 'Unknown')}[/bold]")
        if course != "Unknown":
            console.print(f"     Course: {course} | Year: {year}")
        console.print(f"     [dim]{excerpt}[/dim]")
        console.print()

    # Tier 3: Source listing table
    table = Table(title="Sources", show_header=True, header_style="bold magenta")
    table.add_column("Ref", width=5, style="yellow")
    table.add_column("File", no_wrap=False)
    table.add_column("Course", width=20)
    table.add_column("Score", width=15)

    for i, cite in enumerate(citations, 1):
        meta = cite.get("metadata", {})
        scores = cite.get("confidence_scores", [])
        avg_score = sum(scores) / len(scores) if scores else 0.0

        table.add_row(
            f"[{i}]",
            cite.get("title", "Unknown"),
            meta.get("course", ""),
            score_bar(avg_score),
        )

    console.print(table)
```

### Example 4: Browse Command with Hierarchical Navigation

```python
@app.command()
def browse(
    ctx: typer.Context,
    course: Annotated[str | None, typer.Option("--course", "-c")] = None,
    year: Annotated[str | None, typer.Option("--year", "-y")] = None,
    category: Annotated[str | None, typer.Option("--category")] = None,
) -> None:
    """Browse library structure: courses, years, files."""
    state = get_state(ctx)

    with Database(state.db_path) as db:
        if course is None and category is None:
            # Top-level: show categories with counts
            rows = db.conn.execute("""
                SELECT json_extract(metadata_json, '$.category') as cat,
                       COUNT(*) as cnt
                FROM files
                WHERE metadata_json IS NOT NULL AND status != 'LOCAL_DELETE'
                GROUP BY cat ORDER BY cnt DESC
            """).fetchall()

            table = Table(title="Library Structure")
            table.add_column("Category", style="bold")
            table.add_column("Files", justify="right")
            for r in rows:
                table.add_row(r["cat"] or "unknown", str(r["cnt"]))
            console.print(table)

        elif course is None and category:
            # Show courses/items within category
            if category == "course":
                rows = db.conn.execute("""
                    SELECT json_extract(metadata_json, '$.course') as course,
                           COUNT(*) as cnt
                    FROM files
                    WHERE json_extract(metadata_json, '$.category') = 'course'
                      AND status != 'LOCAL_DELETE'
                    GROUP BY course ORDER BY course
                """).fetchall()

                table = Table(title=f"Courses ({len(rows)} total)")
                table.add_column("Course", style="cyan")
                table.add_column("Files", justify="right")
                for r in rows:
                    table.add_row(r["course"], str(r["cnt"]))
                console.print(table)

        elif course:
            # Show files within a course, optionally filtered by year
            query = """
                SELECT filename, metadata_json FROM files
                WHERE json_extract(metadata_json, '$.course') = ?
                  AND status != 'LOCAL_DELETE'
            """
            params = [course]
            if year:
                query += " AND json_extract(metadata_json, '$.year') = ?"
                params.append(year)
            query += " ORDER BY filename"

            rows = db.conn.execute(query, params).fetchall()
            # Display as table...
```

### Example 5: API Key with Environment Variable Fallback

```python
# Extend existing config.py pattern
def get_api_key() -> str:
    """Get Gemini API key: keyring first, then env var fallback.

    Returns:
        API key string.

    Raises:
        typer.Exit: If no key found anywhere.
    """
    # Try keyring first (consistent with Phase 2)
    api_key = keyring.get_password("objlib-gemini", "api_key")
    if api_key:
        return api_key

    # Fallback to environment variable
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        return api_key

    # Neither found -- actionable error
    console.print(
        "[red]Gemini API key not found.[/red]\n"
        "Set it with: [bold]objlib config set-api-key YOUR_KEY[/bold]\n"
        "Or: [bold]export GEMINI_API_KEY=your-key[/bold]"
    )
    raise typer.Exit(code=1)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `google-generativeai` SDK (`genai.configure()`) | `google-genai` SDK (`genai.Client()`) | 2025 | Different API surface; existing `03_query_interface.py` uses OLD SDK and must be replaced |
| Corpus API (`genai.list_corpora()`) | File Search Stores (`client.file_search_stores`) | 2025 | Completely different query pattern; old `ObjectivismLibrary` class is obsolete |
| Direct corpus.query() | generate_content() with FileSearch tool | 2025 | Search is now a tool call, not a direct API; response includes grounding_metadata |
| Manual metadata filter dicts | AIP-160 string syntax | 2025 | Filter is a string like `'course="OPAR" AND year=2023'`, not a dict |

**Deprecated/outdated:**
- `src/03_query_interface.py`: Uses the OLD `google-generativeai` SDK with `genai.configure()` and corpus API. This entire file is obsolete and should NOT be used as a pattern for Phase 3. The new SDK uses `genai.Client()` and File Search tools.
- `genai.list_corpora()` / `corpus.query()`: Corpus API is replaced by File Search Stores. Queries go through `generate_content()` with `FileSearch` tool.

## Open Questions

1. **Store Name Resolution**
   - What we know: Phase 2 uses `display_name` (e.g., `"objectivism-library-v1"`) for store creation. The `FileSearch` tool requires `file_search_store_names` which expects the Gemini resource name (e.g., `"fileSearchStores/abc123"`).
   - What's unclear: Does the CLI need to resolve display_name -> resource_name at startup? The Phase 2 `GeminiFileSearchClient.get_or_create_store()` already does this and stores the result on `self.store_name`.
   - Recommendation: At CLI init, call `get_or_create_store(display_name)` to resolve the actual resource name. Cache on AppState. This reuses the existing Phase 2 client method. **LOW risk** -- the method exists and works.

2. **Confidence Score Distribution**
   - What we know: `confidence_scores` in `GroundingSupport` are `list[float]` in range 0.0-1.0.
   - What's unclear: What is the typical distribution? Is 0.7 "good"? Is 0.3 ever returned? The documentation says "confidence" but doesn't specify if this is cosine similarity, BM25, or a trained metric.
   - Recommendation: Display raw normalized score (0-100%). Add a note in `--help` that 60-70% is typical for good matches. Gather empirical data during testing to calibrate expectations. **MEDIUM risk** -- may need to adjust display thresholds after real usage.

3. **File Search Store Resource Name Persistence**
   - What we know: The store's resource name (`fileSearchStores/xyz`) is needed for every query. Currently Phase 2 resolves it by listing all stores and matching by display_name.
   - What's unclear: Should we persist the resolved resource name in config or SQLite to avoid the list-stores API call on every CLI invocation?
   - Recommendation: Store the resolved resource name in `config/library_config.json` after first resolution. Check at startup; re-resolve only if not found. This avoids a list-stores call on every search. **LOW risk** -- optimization, not blocker.

4. **Model Selection for Queries**
   - What we know: File Search works with `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-3-pro-preview`, `gemini-3-flash-preview`. The config file specifies `gemini-2.0-flash-exp`.
   - What's unclear: Which model gives best File Search results for philosophical queries? Flash is faster/cheaper; Pro is more thorough.
   - Recommendation: Default to `gemini-2.5-flash` for speed. Allow `--model` flag for power users. The old config's `gemini-2.0-flash-exp` should be updated. **LOW risk** -- easily configurable.

## Sources

### Primary (HIGH confidence)
- google-genai SDK v1.63.0 installed locally -- types inspected via `model_fields` (GroundingMetadata, GroundingChunk, GroundingChunkRetrievedContext, GroundingSupport, Segment, FileSearch, GenerateContentResponse, Candidate)
- Existing codebase: `src/objlib/cli.py`, `src/objlib/upload/client.py`, `src/objlib/database.py`, `src/objlib/models.py`, `src/objlib/config.py`
- Existing database: `data/library.db` schema and actual content verified (1884 files, 76 courses, 18 uploaded)
- `pyproject.toml` verified: all dependencies already present, no additions needed
- google.aip.dev/160 -- AIP-160 filter syntax specification (official Google standard)

### Secondary (MEDIUM confidence)
- ai.google.dev/gemini-api/docs/file-search -- Official File Search documentation (query pattern, metadata_filter usage)
- atamel.dev blog post (2025-11-14) -- Practical File Search examples with grounding metadata access pattern
- tenacity v9.1.4 docs -- `wait_exponential_jitter`, `retry_if_exception_type`, `AsyncRetrying`

### Tertiary (LOW confidence)
- Confidence score distribution and typical ranges -- No official documentation found. Empirical testing needed.
- Gemini File Search rate limits for queries -- Not documented. Phase 2 used conservative rate limiting for uploads; queries may have different limits.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- All libraries already installed and verified, no new deps
- Architecture (Gemini query pattern): HIGH -- SDK types verified locally, response structure confirmed
- Architecture (CLI patterns): HIGH -- Typer/Rich patterns verified against existing cli.py
- Architecture (metadata filtering): HIGH -- AIP-160 syntax verified, filterable fields confirmed from upload client
- Pitfalls: HIGH -- Based on actual SDK inspection and codebase analysis
- Score interpretation: MEDIUM -- Score range (0-1) confirmed, but distribution/calibration unknown
- Rate limits for queries: LOW -- Not documented, needs empirical testing

**Research date:** 2026-02-16
**Valid until:** 2026-03-16 (stable -- SDK types unlikely to change within minor version)
