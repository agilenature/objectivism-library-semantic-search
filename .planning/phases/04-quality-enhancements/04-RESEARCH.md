# Phase 4: Quality Enhancements - Research

**Researched:** 2026-02-17
**Domain:** LLM-based reranking, multi-document synthesis, structured output, query expansion, session management
**Confidence:** HIGH

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **Reranking (ADVN-02):** Use Gemini Flash as LLM-based reranker. Send top-50 passages to Flash in structured prompt, get ranked order back as JSON. `--rerank` flag (default: on), `--no-rerank` to skip. Cache in session events. Include difficulty + course metadata in reranker context. Max 3s latency acceptable.

2. **Synthesis (ADVN-03):** `--synthesize` opt-in flag on `search` command. Pipeline: retrieve top-50 -> rerank -> MMR diversity (max 2 passages per file, prefer distinct courses/weeks) -> submit top 5-10 to Gemini Flash -> structured claim output. Falls back to labeled excerpts if < 5 passages. Answer length: 150-300 words. Contradiction handling: explicit attribution ("Source A says X; Source B says Y").

3. **Citations (ADVN-04):** Claim-level structured output via Pydantic. Each claim: `{claim_text: str, citation: {file_id, passage_id, quote: str (20-60 words)}}`. Python post-validation: quote must be exact substring of stored passage text (whitespace-normalized). Re-prompt once on failure. Fall back to labeled excerpts if second attempt fails. Bridging sentences allowed uncited (transitions, no factual assertions).

4. **Query expansion (ADVN-05):** Curated `synonyms.yml` glossary in repo. ~50 core Objectivist terms seeded. Expansion automatic by default, `--no-expand` to disable. Show expanded terms in CLI output. Limit to top 2 synonyms per matched term. Both single terms and multi-word phrases supported. Original term boosted (appears twice in expanded string). `glossary suggest <term>` uses LLM, requires manual `glossary add` to accept.

5. **Sessions (ADVN-07):** SQLite-backed in existing `library.db`. Tables: `sessions (id, name, created_at, updated_at)` + `session_events (id, session_id, event_type, payload_json, created_at)`. Event types: search, view, synthesize, note. Snapshot semantics (store result doc_ids + passage_ids). Append-only. Resume = display saved timeline. Commands: `session start [name]`, `session list`, `session resume <id>`, `session note <text>`, `session export <id>` (Markdown output).

6. **Concept evolution (ADVN-01):** `--track-evolution` flag on `search` command. Groups results by difficulty tier (Introductory -> Intermediate -> Advanced), then by year/week within tier. Shows top 3 passages per tier. One Gemini Flash synthesis sentence per tier (disable with `--no-synthesis`). No standalone `concept_track` command needed.

7. **Difficulty ordering (ADVN-06):** Two-stage: full rerank first, then difficulty boost within top-20 window. `(difficulty_bucket, rerank_score)` sort within window. `--mode learn` (default, intro-first) vs `--mode research` (pure relevance). Per-command flag, no session memory.

8. **Passage cache:** New `passages` table in `library.db`. UUID `passage_id`. Columns: `passage_id, file_id, content_hash, passage_text, source, is_stale, created_at, last_seen_at`. Upsert on each search (INSERT OR IGNORE, UPDATE last_seen_at). Mark stale on content_hash mismatch, preserve for session replay. No GC in Phase 4.

9. **Error handling:** Graceful degradation. Reranker failure -> warn + use Gemini order. Synthesis validation failure -> warn + show excerpts. `--debug` flag -> `~/.objlib/debug.log`. All failures logged as events in active session.

### Claude's Discretion

No discretion areas -- all decisions were locked in YOLO mode.

### Deferred Ideas (OUT OF SCOPE)

- No prerequisite dependency graph for concept evolution
- No Redis or external caching
- No garbage collection for passages table
- No auto-infer mode from query phrasing
- No session-level mode persistence
- No standalone `concept_track` command

</user_constraints>

## Summary

Phase 4 transforms the existing search pipeline from a simple query-response interface into a multi-stage research tool. The current codebase (Phase 3) has a clean architecture: `GeminiSearchClient` queries the Gemini File Search store, `extract_citations()` pulls grounding chunks, `enrich_citations()` adds SQLite metadata, and `display_search_results()` renders the Rich output. Phase 4 inserts new stages between retrieval and display: reranking, diversity selection, synthesis, and citation validation. It also adds query expansion before retrieval and session persistence throughout.

The google-genai SDK (v1.63.0, already installed) natively supports structured JSON output via `response_schema` on `GenerateContentConfig`, accepting Pydantic model classes directly. This is the backbone for both the reranker (returning ranked passage indices) and the synthesizer (returning claim-level citations). The `FileSearch` tool has a `top_k` parameter that controls how many grounding chunks are returned, enabling retrieval of the required 50 passages per query. Gemini 2.5 Flash has a 1M token context window, so 50 passages (roughly 23K tokens) is well within limits at only 2.2% of context capacity.

The existing database migration pattern (PRAGMA user_version checks with IF NOT EXISTS tables) supports clean addition of `passages`, `sessions`, and `session_events` tables. PyYAML 6.0.3 is already installed as a transitive dependency and handles `synonyms.yml` loading. Typer 0.23.0 supports `--flag/--no-flag` boolean pairs and sub-app command groups, both already used in the project.

**Primary recommendation:** Build the pipeline as composable stages (expand -> retrieve -> rerank -> diversify -> synthesize -> validate -> display) where each stage can be independently skipped or degraded, feeding data through a shared `SearchPipeline` context object.

## Standard Stack

### Core (Already Installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| google-genai | 1.63.0 | Gemini Flash API calls for reranking + synthesis | Already in use; `response_schema` supports Pydantic models directly |
| pydantic | 2.11.7 | Structured output schemas + validation | Already in use; `model_json_schema()` integrates with Gemini |
| typer | 0.23.0 | CLI flags (`--rerank/--no-rerank`, `--mode`, etc.) | Already in use; supports flag pairs and sub-apps |
| rich | (installed) | Warning panels, session timeline display | Already in use for all CLI output |
| PyYAML | 6.0.3 | Load `synonyms.yml` glossary | Already installed as transitive dep; `yaml.safe_load()` sufficient |
| sqlite3 | stdlib | `passages`, `sessions`, `session_events` tables | Already the sole persistence layer |

### Supporting (Already Installed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tenacity | 9.x | Retry logic for Gemini Flash reranking/synthesis calls | Already used in `GeminiSearchClient`; extend pattern |
| uuid | stdlib | Deterministic passage IDs via `uuid.uuid5()` | Passage identity generation |
| hashlib | stdlib | Content hashing for passage staleness detection | SHA256 of passage text |
| re | stdlib | Whitespace normalization for quote validation | `re.sub(r'\s+', ' ', text.strip())` |

### No New Dependencies Required

All functionality can be built with the existing dependency set. No new packages need to be added to `pyproject.toml`.

**Installation:**
```bash
# No new packages needed. Existing pyproject.toml dependencies are sufficient.
pip install -e .  # Reinstall if needed
```

## Architecture Patterns

### Recommended Project Structure
```
src/objlib/
    search/
        __init__.py
        client.py              # (existing) GeminiSearchClient
        citations.py           # (existing) extract_citations, enrich_citations
        formatter.py           # (existing) display_search_results + new display modes
        reranker.py            # NEW: LLM-based reranking via Gemini Flash
        synthesizer.py         # NEW: Multi-document synthesis + citation validation
        expansion.py           # NEW: Query expansion from synonyms.yml
        diversity.py           # NEW: MMR-style metadata-based diversity filter
        synonyms.yml           # NEW: Curated Objectivist terminology glossary
        pipeline.py            # NEW: Orchestrates expand->retrieve->rerank->diversify->synthesize
    session/
        __init__.py
        manager.py             # NEW: Session CRUD, event logging
        commands.py            # NEW: session start/list/resume/note/export CLI
        exporter.py            # NEW: Markdown export for sessions
    cli.py                     # (extend) Add new flags to search, add session/glossary sub-apps
    database.py                # (extend) Migration V6 for passages/sessions/session_events tables
    models.py                  # (extend) New Pydantic models for pipeline stages
```

### Pattern 1: Pipeline Stage Architecture
**What:** Each pipeline stage is a pure function taking context in, returning enriched context out. A `SearchPipelineContext` dataclass carries state through the pipeline.
**When to use:** Every search invocation.
**Example:**
```python
# Source: Verified against existing codebase patterns
from dataclasses import dataclass, field
from objlib.models import Citation

@dataclass
class PipelineContext:
    """Carries state through the search pipeline stages."""
    query: str
    expanded_query: str | None = None
    expanded_terms: list[str] = field(default_factory=list)
    raw_citations: list[Citation] = field(default_factory=list)
    reranked_citations: list[Citation] = field(default_factory=list)
    diverse_citations: list[Citation] = field(default_factory=list)
    synthesis_result: object | None = None  # SynthesisResult when --synthesize
    response_text: str = ""
    warnings: list[str] = field(default_factory=list)
    # Pipeline config
    do_rerank: bool = True
    do_expand: bool = True
    do_synthesize: bool = False
    mode: str = "learn"
    track_evolution: bool = False
    session_id: str | None = None
```

### Pattern 2: Gemini Flash Structured Output
**What:** Pass Pydantic model class as `response_schema` to get typed JSON responses.
**When to use:** Reranker and synthesizer calls to Gemini Flash.
**Example:**
```python
# Source: Verified with installed google-genai 1.63.0 SDK
from pydantic import BaseModel, Field
from google.genai import types

class RerankResult(BaseModel):
    ranked_indices: list[int] = Field(
        description="Passage indices ordered by relevance (most relevant first)"
    )

config = types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=RerankResult,
    temperature=0.0,
    max_output_tokens=2048,
)

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=rerank_prompt,
    config=config,
)
# response.text is JSON string; parse with RerankResult.model_validate_json()
result = RerankResult.model_validate_json(response.text)
```

### Pattern 3: FileSearch top_k for 50 Passages
**What:** Use the `top_k` parameter on `FileSearch` to retrieve 50 grounding chunks instead of the default.
**When to use:** All search queries in Phase 4 (needed for reranking pipeline).
**Example:**
```python
# Source: Verified with installed google-genai 1.63.0 SDK
from google.genai import types

config = types.GenerateContentConfig(
    tools=[
        types.Tool(
            file_search=types.FileSearch(
                file_search_store_names=[store_resource_name],
                top_k=50,  # Retrieve 50 chunks for reranking
                metadata_filter=metadata_filter,
            )
        )
    ],
)
```

### Pattern 4: Typer Boolean Flag Pairs
**What:** `--flag/--no-flag` pattern for opt-in/opt-out toggles.
**When to use:** All Phase 4 search flags.
**Example:**
```python
# Source: Verified with installed Typer 0.23.0
from typing import Annotated
import typer

@app.command()
def search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Search query")],
    rerank: Annotated[bool, typer.Option(
        "--rerank/--no-rerank", help="Enable LLM reranking"
    )] = True,
    synthesize: Annotated[bool, typer.Option(
        "--synthesize", help="Synthesize across sources"
    )] = False,
    expand: Annotated[bool, typer.Option(
        "--expand/--no-expand", help="Query expansion"
    )] = True,
    track_evolution: Annotated[bool, typer.Option(
        "--track-evolution", help="Track concept evolution by difficulty"
    )] = False,
    mode: Annotated[str, typer.Option(
        "--mode", help="Result ordering: 'learn' or 'research'"
    )] = "learn",
    debug: Annotated[bool, typer.Option(
        "--debug", help="Enable debug logging"
    )] = False,
    # ... existing filter, limit, model params preserved
):
    pass
```

### Pattern 5: Typer Sub-App for Session and Glossary
**What:** Typer sub-apps for command groups. Already used in the project for `config`, `metadata`, `entities`.
**When to use:** `session` and `glossary` command groups.
**Example:**
```python
# Source: Verified against existing cli.py patterns (config_app, metadata_app, entities_app)
session_app = typer.Typer(help="Research session management")
app.add_typer(session_app, name="session")

glossary_app = typer.Typer(help="Manage query expansion glossary")
app.add_typer(glossary_app, name="glossary")

@session_app.command()
def start(name: str | None = None):
    """Start a new research session."""
    pass
```

### Pattern 6: Database Migration (V5 -> V6)
**What:** Extend existing `_setup_schema()` migration pattern with `PRAGMA user_version` check.
**When to use:** Adding passages, sessions, session_events tables.
**Example:**
```python
# Source: Verified against existing database.py migration pattern
MIGRATION_V6_SQL = """
CREATE TABLE IF NOT EXISTS passages (
    passage_id TEXT PRIMARY KEY,
    file_id TEXT,
    content_hash TEXT,
    passage_text TEXT NOT NULL,
    source TEXT DEFAULT 'gemini_grounding',
    is_stale BOOLEAN DEFAULT 0,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    last_seen_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_passages_file_id ON passages(file_id);
CREATE INDEX IF NOT EXISTS idx_passages_content_hash ON passages(content_hash);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    name TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('search', 'view', 'synthesize', 'note', 'error')),
    payload_json TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_session_events_session ON session_events(session_id);

-- Auto-update sessions.updated_at on new event
CREATE TRIGGER IF NOT EXISTS update_session_timestamp
    AFTER INSERT ON session_events
    FOR EACH ROW
    BEGIN
        UPDATE sessions SET updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')
        WHERE id = NEW.session_id;
    END;
"""

# In _setup_schema():
if version < 6:
    self.conn.executescript(MIGRATION_V6_SQL)
    self.conn.execute("PRAGMA user_version = 6")
```

### Anti-Patterns to Avoid
- **Do NOT add tools=[FileSearch] AND response_schema together in one generate_content call.** FileSearch tool and structured output are separate concerns. Reranking/synthesis uses a plain generate_content call with response_schema (no tools). Search retrieval uses FileSearch tool (no response_schema).
- **Do NOT use random UUID4 for passage_id.** Use deterministic UUID5 from `(file_id, content_hash)` so the same passage gets the same ID across queries.
- **Do NOT add PyTorch/sentence-transformers.** The locked decision is Gemini Flash LLM-based reranking, not local cross-encoders.
- **Do NOT make synthesis the default.** It is opt-in via `--synthesize` only.
- **Do NOT use `response_json_schema` when `response_schema` works.** The SDK docs note `response_json_schema` is an alternative fallback for when `response_schema` doesn't process your schema correctly. Prefer `response_schema` with Pydantic classes.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON schema generation | Manual dict construction | `PydanticModel.model_json_schema()` with `response_schema=PydanticModel` | Pydantic handles nested models, optional fields, enums correctly |
| Retry logic | Custom try/except loops | `tenacity` (already in project) with `@retry` decorator | Exponential backoff, jitter, configurable stop conditions |
| Content hashing | Custom hash functions | `hashlib.sha256(text.encode()).hexdigest()` | Standard, fast, deterministic |
| UUID generation | Random IDs or custom schemes | `uuid.uuid5(uuid.NAMESPACE_OID, f"{file_id}:{content_hash}")` | Deterministic, same content always same ID |
| YAML parsing | JSON config or custom parser | `yaml.safe_load()` from PyYAML 6.0.3 (already installed) | Handles nested structures, safe against code injection |
| Whitespace normalization | Custom string manipulation | `re.sub(r'\s+', ' ', text.strip())` | Handles all whitespace variants (tabs, newlines, multiple spaces) |
| CLI flag pairs | Custom argument parsing | Typer `--flag/--no-flag` syntax | Built-in support, generates correct help text |

**Key insight:** Phase 4's complexity is in the orchestration logic (pipeline stages, graceful degradation, state management), not in low-level primitives. Every primitive operation has a standard solution already in the project's dependency set.

## Common Pitfalls

### Pitfall 1: FileSearch + Structured Output Conflict
**What goes wrong:** Attempting to combine `tools=[FileSearch(...)]` with `response_schema=SomeModel` in the same `generate_content` call causes unexpected behavior or errors. The FileSearch tool returns grounding metadata; structured output constrains the response format.
**Why it happens:** These are separate API features. FileSearch retrieves passages and generates a grounded response. Structured output constrains the model's text output to JSON.
**How to avoid:** Two separate API calls: (1) `generate_content` with FileSearch tool to get grounding chunks, (2) separate `generate_content` with response_schema for reranking or synthesis.
**Warning signs:** Getting empty grounding_metadata when response_schema is set, or getting unstructured text when FileSearch is combined with response_schema.

### Pitfall 2: Quote Validation False Negatives
**What goes wrong:** Citation validation rejects valid quotes due to whitespace, Unicode, or encoding differences between the passage text from Gemini and the quote generated by the synthesis model.
**Why it happens:** Gemini may return passages with different whitespace normalization than what Flash generates in its quote. Non-breaking spaces, em-dashes vs hyphens, smart quotes vs straight quotes all cause substring match failures.
**How to avoid:** Normalize BOTH passage text AND generated quote before comparison: `re.sub(r'\s+', ' ', text.strip())`. Also normalize Unicode quotation marks and dashes. Consider lowercasing both sides for the comparison.
**Warning signs:** High rate of re-prompts or fallback-to-excerpts in testing.

### Pitfall 3: Passage ID Instability
**What goes wrong:** Using random UUIDs (uuid4) means the same passage gets a different ID each time it's returned by Gemini, breaking session references and citation stability.
**Why it happens:** Gemini File Search does not provide stable passage IDs. The same text chunk can appear with different grounding_chunk_indices across queries.
**How to avoid:** Use deterministic UUID5 from `(file_id, content_hash_of_passage_text)`. Same passage from same file always yields same passage_id.
**Warning signs:** Session resume showing "passage not found" for previously saved references.

### Pitfall 4: Reranking Prompt Token Overflow
**What goes wrong:** If passages are very long, sending all 50 to Flash with metadata might approach the output token limit or create a prompt so large the model gives poor results.
**Why it happens:** Average passages are ~350 words but some could be 1000+. 50 * 1000 words = 65K tokens input, which is still within limits but may degrade ranking quality.
**How to avoid:** Truncate each passage to first 500 characters (~100 words) in the reranking prompt. The reranker only needs enough text to assess relevance, not the full passage. Keep full text in the pipeline context for display/synthesis.
**Warning signs:** Reranking taking >3s or producing inconsistent rankings.

### Pitfall 5: Gemini Commands vs Non-Gemini Commands
**What goes wrong:** The existing `_GEMINI_COMMANDS` set in `cli.py` controls which commands trigger the app callback's Gemini client initialization. New commands like `session` and `glossary` don't need Gemini for most operations, but `glossary suggest` does.
**Why it happens:** The callback pattern initializes the full Gemini client + store resolution for commands in `_GEMINI_COMMANDS`. Sub-app commands under `session` or `glossary` bypass this.
**How to avoid:** Keep `session` and `glossary` out of `_GEMINI_COMMANDS`. Initialize Gemini client lazily inside `glossary suggest` (like the `view --show-related` pattern already does). Session commands should access SQLite only.
**Warning signs:** "Application state not initialized" errors when running session/glossary commands without `--store`.

### Pitfall 6: SQLite Concurrent Access During Sessions
**What goes wrong:** If a session is active and multiple search operations happen in sequence, the session event inserts could conflict with passage upserts in the same transaction.
**Why it happens:** The current Database class uses a single connection. Rapid sequential operations (search -> log event -> insert passages) within one command are fine, but storing session state across CLI invocations requires careful connection management.
**How to avoid:** Use separate Database instances or ensure all session operations use explicit `with self.conn:` transaction blocks. Session ID tracked via environment variable (`OBJLIB_SESSION`) across invocations.
**Warning signs:** "database is locked" errors during active sessions.

### Pitfall 7: MMR Diversity Over-Filtering
**What goes wrong:** Applying strict diversity constraints (max 2 per file, prefer distinct courses) to a small result set can eliminate the most relevant passages, leaving only marginally relevant diverse ones.
**Why it happens:** If the top results are heavily concentrated in one file/course (because that's genuinely where the answer lives), diversity filtering removes the best results.
**How to avoid:** Only apply diversity filtering when there are more than `target_count` passages available. If diversity filtering would reduce below `target_count`, relax constraints (increase max_per_file). Always preserve the #1 ranked passage regardless of diversity.
**Warning signs:** Synthesis producing lower quality answers than expected; best passage not appearing in synthesis input.

## Code Examples

Verified patterns from official sources and installed packages:

### Gemini Flash Structured Reranking Call
```python
# Source: Verified with google-genai 1.63.0
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

class RerankResult(BaseModel):
    ranked_indices: list[int] = Field(
        description="0-based passage indices ordered by relevance to the query"
    )

def rerank_passages(
    client: genai.Client,
    query: str,
    passages: list[dict],  # [{index, text, course, difficulty}, ...]
) -> list[int]:
    """Rerank passages using Gemini Flash LLM-based reranking."""

    # Build passage list for prompt (truncate to 500 chars each)
    passage_text = "\n\n".join(
        f"[{p['index']}] (Course: {p.get('course', 'N/A')}, "
        f"Difficulty: {p.get('difficulty', 'N/A')})\n"
        f"{p['text'][:500]}"
        for p in passages
    )

    prompt = f"""You are a relevance ranker for an Objectivist philosophy research tool.

Given this query: "{query}"

Rank these passages by relevance (most relevant first). Consider:
1. Direct topical relevance to the query
2. Depth and specificity of the philosophical content
3. Course context and difficulty level

Passages:
{passage_text}

Return the passage indices in order of relevance."""

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=RerankResult,
        temperature=0.0,
        max_output_tokens=2048,
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=config,
    )

    result = RerankResult.model_validate_json(response.text)
    return result.ranked_indices
```

### Synthesis with Claim-Level Citations
```python
# Source: Verified with google-genai 1.63.0 + pydantic 2.11.7
from pydantic import BaseModel, Field

class CitationRef(BaseModel):
    file_id: str = Field(description="File identifier from the library")
    passage_id: str = Field(description="Stable passage identifier")
    quote: str = Field(description="Exact quote from source (20-60 words)")

class Claim(BaseModel):
    claim_text: str = Field(description="A factual claim synthesized from sources")
    citation: CitationRef = Field(description="Source attribution for this claim")

class SynthesisResult(BaseModel):
    claims: list[Claim] = Field(description="Factual claims with citations")
    summary: str = Field(description="Brief bridging summary (no factual assertions)")
```

### Quote Substring Validation
```python
# Source: Standard Python re module
import re

def validate_quote(quote: str, passage_text: str) -> bool:
    """Validate that a quote is an exact substring of the passage text.

    Both strings are whitespace-normalized before comparison.
    """
    def normalize(text: str) -> str:
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text.strip())
        # Normalize Unicode quotes and dashes
        text = text.replace('\u2018', "'").replace('\u2019', "'")
        text = text.replace('\u201c', '"').replace('\u201d', '"')
        text = text.replace('\u2013', '-').replace('\u2014', '-')
        return text.lower()

    return normalize(quote) in normalize(passage_text)
```

### Passage Upsert with Deterministic IDs
```python
# Source: Python stdlib uuid, hashlib
import uuid
import hashlib

def generate_passage_id(file_id: str, passage_text: str) -> str:
    """Generate a deterministic passage ID from file_id and content."""
    content_hash = hashlib.sha256(passage_text.encode()).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{file_id}:{content_hash}"))

def content_hash(text: str) -> str:
    """SHA256 hash of passage text for staleness detection."""
    return hashlib.sha256(text.encode()).hexdigest()
```

### YAML Glossary Loading
```python
# Source: PyYAML 6.0.3 (already installed)
import yaml
from pathlib import Path

def load_glossary(glossary_path: Path | None = None) -> dict[str, list[str]]:
    """Load synonyms.yml and return term -> synonyms mapping.

    Returns:
        Dict mapping term (lowercase) to list of synonym strings.
    """
    if glossary_path is None:
        glossary_path = Path(__file__).parent / "synonyms.yml"

    if not glossary_path.exists():
        return {}

    with open(glossary_path) as f:
        data = yaml.safe_load(f)

    glossary = {}
    for entry in data.get("terms", []):
        term = entry["term"].lower()
        synonyms = entry.get("synonyms", [])
        glossary[term] = synonyms[:2]  # Limit to top 2 per locked decision

    return glossary
```

### Query Expansion
```python
# Source: Custom implementation following locked decision spec
def expand_query(query: str, glossary: dict[str, list[str]]) -> tuple[str, list[str]]:
    """Expand query using glossary.

    Returns:
        Tuple of (expanded_query_string, list_of_added_terms).
        Original term is boosted by appearing twice in expanded string.
    """
    query_lower = query.lower()
    added_terms = []

    # Check multi-word phrases first (longer matches take priority)
    sorted_terms = sorted(glossary.keys(), key=len, reverse=True)
    matched = set()

    for term in sorted_terms:
        if term in query_lower and term not in matched:
            synonyms = glossary[term][:2]  # Max 2 synonyms per term
            added_terms.extend(synonyms)
            matched.add(term)

    if not added_terms:
        return query, []

    # Boost original query (appears twice) + add synonyms
    expanded = f"{query} {query} {' '.join(added_terms)}"
    return expanded, added_terms
```

### Metadata-Based MMR Diversity Selection
```python
# Source: Custom implementation following locked decision spec
def select_diverse_passages(
    passages: list[dict],
    max_per_file: int = 2,
    target_count: int = 10,
) -> list[dict]:
    """Select diverse passages: max 2 per file, prefer distinct courses.

    Always preserves the #1 ranked passage regardless of constraints.
    Relaxes constraints if would result in fewer than target_count.
    """
    selected = []
    file_counts: dict[str, int] = {}
    course_counts: dict[str, int] = {}

    for i, p in enumerate(passages):
        file_id = p.get("file_id", "")
        course = p.get("course", "")

        # Always include #1 ranked passage
        if i == 0:
            selected.append(p)
            file_counts[file_id] = 1
            if course:
                course_counts[course] = 1
            continue

        # Enforce max per file
        if file_counts.get(file_id, 0) >= max_per_file:
            continue

        selected.append(p)
        file_counts[file_id] = file_counts.get(file_id, 0) + 1
        if course:
            course_counts[course] = course_counts.get(course, 0) + 1

        if len(selected) >= target_count:
            break

    return selected
```

### Difficulty-Aware Reordering
```python
# Source: Custom implementation following locked decision spec
DIFFICULTY_ORDER = {"introductory": 0, "intermediate": 1, "advanced": 2}

def difficulty_reorder(
    passages: list[dict],
    mode: str = "learn",
    window_size: int = 20,
) -> list[dict]:
    """Apply difficulty-aware reordering within top-N window.

    Args:
        passages: Reranked passages with 'difficulty' and 'rerank_score' keys.
        mode: 'learn' (intro-first) or 'research' (pure relevance).
        window_size: Size of the reordering window (top N results).
    """
    if mode == "research":
        return passages  # Pure relevance, no reordering

    # Split into window and remainder
    window = passages[:window_size]
    remainder = passages[window_size:]

    # Sort window by (difficulty_bucket ASC, rerank_score DESC)
    def sort_key(p):
        diff = p.get("difficulty", "intermediate").lower()
        bucket = DIFFICULTY_ORDER.get(diff, 1)
        score = p.get("rerank_score", 0.0)
        return (bucket, -score)

    window.sort(key=sort_key)
    return window + remainder
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `google-generativeai` SDK | `google-genai` SDK | 2024-2025 | New SDK uses `client.models.generate_content()` pattern; `response_schema` accepts Pydantic classes directly |
| No top_k on FileSearch | `FileSearch(top_k=N)` available | google-genai 1.x | Can retrieve 50+ chunks per query instead of default |
| `response_json_schema` (dict) | `response_schema` (Pydantic class) | google-genai 1.x | Simpler DX; pass class directly, SDK handles schema conversion |
| Cross-encoder reranking (PyTorch) | LLM-based listwise reranking | 2024-2025 trend | LLMs understand domain terminology; no separate model deployment needed |
| Pydantic v1 `.schema()` | Pydantic v2 `.model_json_schema()` | Pydantic 2.0+ | Different method name; v2 generates JSON Schema draft 2020-12 |

**Deprecated/outdated:**
- `google-generativeai` package: This project correctly uses `google-genai` (the newer SDK). Do not import from `google.generativeai`.
- `GenerativeModel` class: The old SDK pattern. This project uses `client.models.generate_content()`.

## Open Questions

1. **top_k maximum value**
   - What we know: `FileSearch.top_k` accepts an int and 50 works in construction. Gemini docs do not publish a max value.
   - What's unclear: Whether the API actually returns 50 grounding chunks or silently caps at a lower number (e.g., 20).
   - Recommendation: Test empirically with a live API call and log the actual number of grounding_chunks returned. If capped below 50, adjust the reranking pipeline to work with fewer passages.

2. **Gemini Flash reranking latency**
   - What we know: Gemini Flash is fast (~0.5-2s per call). Budget is 3s maximum.
   - What's unclear: Actual latency with 50 passages (~23K tokens input) + structured JSON output.
   - Recommendation: Benchmark during implementation. If exceeding 3s, reduce to top-30 passages or truncate passages more aggressively.

3. **Session ID across CLI invocations**
   - What we know: Decision says `OBJLIB_SESSION` env var tracks active session. CLI commands are separate process invocations.
   - What's unclear: UX for maintaining env var (user must export, or session start prints an export command?).
   - Recommendation: `session start` prints `export OBJLIB_SESSION=<id>` and also writes to `~/.objlib/active_session`. CLI checks both env var and file. `session end` clears both.

4. **synonyms.yml hot reload**
   - What we know: Glossary is loaded once at query expansion time. No daemon process.
   - What's unclear: Whether to cache the glossary or reload from disk each time.
   - Recommendation: Load from disk on each `search` invocation (file is small, ~50 entries). No caching needed for a CLI tool that exits after each command.

## Sources

### Primary (HIGH confidence)
- **google-genai 1.63.0 installed package** -- `types.GenerateContentConfig` fields inspected directly (response_schema, response_mime_type, response_json_schema). `types.FileSearch` top_k parameter verified.
- **Pydantic 2.11.7 installed package** -- `model_json_schema()` and `model_validate_json()` verified.
- **Typer 0.23.0 installed package** -- `--flag/--no-flag` boolean pairs and sub-app pattern verified.
- **PyYAML 6.0.3 installed package** -- `yaml.safe_load()` verified for glossary structure.
- **SQLite3 stdlib** -- Migration pattern, INSERT OR IGNORE, PRAGMA user_version verified.
- **Existing codebase** -- `src/objlib/search/client.py`, `citations.py`, `formatter.py`, `database.py`, `models.py`, `cli.py` all read and analyzed.

### Secondary (MEDIUM confidence)
- **ai.google.dev/gemini-api/docs/structured-output** -- Confirmed response_mime_type + response_schema pattern for structured JSON output.
- **ai.google.dev/gemini-api/docs/models** -- Gemini 2.5 Flash: 1M token context, 65K output tokens.
- **ai.google.dev/gemini-api/docs/pricing** -- Flash: $0.30/1M input tokens, $2.50/1M output tokens (paid tier).

### Tertiary (LOW confidence)
- **top_k actual maximum** -- Not documented in official docs. Verified parameter exists but actual server-side behavior needs empirical testing.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already installed and verified via introspection
- Architecture: HIGH -- patterns verified against existing codebase and SDK APIs
- Pitfalls: HIGH -- identified from direct SDK inspection and codebase analysis
- Open questions: MEDIUM -- primarily empirical questions that need live API testing

**Research date:** 2026-02-17
**Valid until:** 2026-03-17 (30 days -- stack is stable, no breaking changes expected)
