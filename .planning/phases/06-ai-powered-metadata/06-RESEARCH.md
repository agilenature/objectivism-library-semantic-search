# Phase 6: AI-Powered Metadata Enhancement - Research

**Researched:** 2026-02-16
**Domain:** LLM-powered metadata extraction pipeline (Mistral API + SQLite + async Python)
**Confidence:** MEDIUM-HIGH (verified SDK/API capabilities, but some pricing/rate details depend on account tier)

## Summary

Phase 6 adds AI-powered metadata extraction to transform ~496 files with `category: "unknown"` into richly tagged, searchable records using the Mistral AI `magistral-medium-latest` reasoning model. The phase is structured as two sequential waves: Wave 1 discovers the optimal prompt through competitive A/B/C testing on 20 files, then Wave 2 processes the remaining files with the validated approach.

The existing codebase provides strong foundations: an async upload pipeline with semaphore-based concurrency, circuit breaker, rate limiter, and SQLite state management. Phase 6 can reuse these patterns. The primary new work is: (1) integrating the `mistralai` Python SDK, (2) building the 4-tier metadata extraction prompt and response parser, (3) extending the database schema for versioned AI metadata, and (4) adding CLI review commands. The 4-tier hybrid metadata structure (controlled + freeform) is already decided in DECISION-HYBRID-TAXONOMY.md.

**Primary recommendation:** Build Phase 6 as a new `src/objlib/extraction/` module that mirrors the existing `upload/` module architecture (orchestrator + client + state + rate limiter pattern), adding `mistralai` as a project dependency and extending the existing `files` table rather than creating new tables where possible.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Phase Structure:**
- Two-wave approach: Wave 1 (discovery, 20 files, ~$20-30) then Wave 2 (production, ~446-476 files, ~$110-164)
- 4-tier hybrid metadata system as defined in DECISION-HYBRID-TAXONOMY.md
- Mixtral (magistral-medium-latest) as the extraction model
- Pause/resume with stakeholder consultation when Mistral credits run out

**Wave 1:**
- W1.A1: Atomic checkpoint with stakeholder consultation for credit exhaustion
- W1.A2: Competitive parallelism (3 strategy lanes: Minimalist, Teacher, Reasoner)
- W1.A3: Structural archetypes for prompt variation (zero-shot, one-shot, chain-of-thought)
- W1.A4: Stratified sampling by file size for test file selection (20 files)
- W1.A5: Human-in-the-loop with edit distance metric for ground truth validation
- W1.A6: Self-reported confidence with calibration analysis
- W1.A7: Quality gates with hybrid template generation for Wave 2 transition

**Wave 2:**
- W2.A1: Use Wave 1 winner template (or hybrid if split performance)
- W2.A2: Two-phase parser (structured + regex fallback)
- W2.A3: Two-level validation (hard fail + soft warnings)
- W2.A4: Hybrid database schema (junction table + JSON columns + versioning)
- W2.A5: Adaptive chunking (head-tail windowing for long transcripts)
- W2.A6: Progressive disclosure with Rich panels for CLI review
- W2.A7: Multi-dimensional weighted average for confidence scoring
- W2.A8: Asyncio with token bucket (3 concurrent, 60/min)
- W2.A9: Accept partial with status flags
- W2.A10: Semantic versioning with config hashing for prompt tracking
- W2.A11: Privacy-by-default with opt-in debug
- W2.A12: Smart triggers with approved preservation for incremental updates

### Claude's Discretion

These areas were auto-resolved by YOLO mode with recommended options. Implementation details are flexible:
- Exact prompt wording and few-shot examples
- Regex pattern specifics for response parsing
- Exact validation threshold values (can tune during Wave 1)
- FTS5 vs JSON-only for freeform tier storage
- Specific CLI command names and argument structure

### Deferred Ideas (OUT OF SCOPE)
- Phase 6.1: Vocabulary evolution (promoting frequent freeform aspects to controlled vocab)
- Phase 6.2: Aspect consolidation via embeddings
- Local Mixtral inference (running model locally instead of API)
- Email notification on credit exhaustion
- Multi-reviewer inter-rater reliability for Wave 1

</user_constraints>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `mistralai` | latest (>=1.0) | Official Mistral AI Python SDK | Direct API access, handles auth, retries, async support, JSON mode |
| `pydantic` | >=2.0 | Schema validation for 4-tier metadata | model_validate() for LLM output, model_json_schema() for prompt injection, enum support |
| `aiolimiter` | >=1.1 | Async rate limiting (token bucket) | Precise 60 req/min enforcement across concurrent tasks |
| `asyncio` | stdlib | Concurrency control | Semaphore-based concurrency (3 concurrent), already used in upload pipeline |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `typer` | >=0.12 | CLI commands (already in project) | New `meta review`, `meta extract` commands |
| `rich` | >=13.0 | Terminal display (already in project) | 4-tier metadata panels, review workflow |
| `tenacity` | >=9.1 | Retry logic (already in project) | Mistral API retry on 5xx/429 errors |
| `sqlite3` | stdlib | Database (already in project) | Schema migrations, metadata storage |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `mistralai` SDK | Raw `httpx`/`aiohttp` | SDK handles auth, response parsing, thinking block filtering; raw HTTP gives more control but requires more code |
| `aiolimiter` | Custom deque-based limiter | Already have `AdaptiveRateLimiter` in upload/; aiolimiter is simpler for a different API's limits |
| `pydantic` | Manual JSON validation | Pydantic generates JSON schema for prompts AND validates responses; manual code would be duplicative |
| New `extraction/` module | Extending `upload/` | Extraction is a distinct pipeline (different API, different state machine); clean separation is better |

**Installation:**
```bash
pip install mistralai pydantic aiolimiter
```

Add to `pyproject.toml` dependencies:
```toml
dependencies = [
    # ... existing ...
    "mistralai>=1.0",
    "pydantic>=2.0",
    "aiolimiter>=1.1",
]
```

## Architecture Patterns

### Recommended Project Structure

```
src/objlib/
├── extraction/                   # NEW: Phase 6 extraction module
│   ├── __init__.py
│   ├── client.py                 # MistralClient wrapper (API calls, response parsing)
│   ├── schemas.py                # Pydantic models for 4-tier metadata + validation
│   ├── prompts.py                # Prompt templates (3 strategies + production)
│   ├── orchestrator.py           # Batch processing engine (mirrors upload/orchestrator.py)
│   ├── validator.py              # Hard/soft validation, confidence scoring
│   ├── checkpoint.py             # Pause/resume + credit exhaustion handling
│   └── strategies.py             # Wave 1 strategy lane definitions
├── cli.py                        # Extended: new `meta extract`, `meta review` commands
├── database.py                   # Extended: migration for new columns/tables
├── models.py                     # Extended: MetadataStatus enum, ExtractionConfig
└── ... (existing modules unchanged)
```

### Pattern 1: Orchestrator Pattern (reuse from upload pipeline)

**What:** Centralized batch processor composing client, state, rate limiter, and progress tracker
**When to use:** Processing files in batches with concurrency, error handling, and checkpoint/resume
**Example:**

```python
# Mirrors existing upload/orchestrator.py pattern
class ExtractionOrchestrator:
    def __init__(self, client, config, db):
        self._client = client          # MistralClient
        self._semaphore = asyncio.Semaphore(config.max_concurrent)  # 3
        self._rate_limiter = AsyncLimiter(config.rate_limit, 60)    # 60/min
        self._shutdown_event = asyncio.Event()
        self._checkpoint = CheckpointManager(config.checkpoint_path)

    async def process_file(self, file_record):
        async with self._semaphore:
            async with self._rate_limiter:
                return await self._client.extract_metadata(file_record)
```

**Confidence:** HIGH -- this pattern is already proven in the codebase.

### Pattern 2: Pydantic Schema as Prompt + Validator

**What:** Use Pydantic models to generate JSON schema for prompt injection AND validate LLM responses
**When to use:** Anywhere structured LLM output is needed with controlled vocabulary constraints
**Example:**

```python
from enum import Enum
from pydantic import BaseModel, Field, field_validator

class Category(str, Enum):
    COURSE_TRANSCRIPT = "course_transcript"
    BOOK_EXCERPT = "book_excerpt"
    QA_SESSION = "qa_session"
    ARTICLE = "article"
    PHILOSOPHY_COMPARISON = "philosophy_comparison"
    CONCEPT_EXPLORATION = "concept_exploration"
    CULTURAL_COMMENTARY = "cultural_commentary"

class Difficulty(str, Enum):
    INTRO = "intro"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"

class SemanticDescription(BaseModel):
    summary: str = Field(min_length=50, description="1-2 sentence overview")
    key_arguments: list[str] = Field(min_length=1, description="Main claims and reasoning")
    philosophical_positions: list[str] = Field(default_factory=list)

class ExtractedMetadata(BaseModel):
    category: Category
    difficulty: Difficulty
    primary_topics: list[str] = Field(min_length=3, max_length=8)
    topic_aspects: list[str] = Field(min_length=3, max_length=10)
    semantic_description: SemanticDescription
    confidence_score: float = Field(ge=0.0, le=1.0)

    model_config = ConfigDict(extra='ignore')  # Ignore hallucinated fields

    @field_validator('primary_topics')
    @classmethod
    def validate_controlled_vocab(cls, v):
        invalid = [t for t in v if t not in CONTROLLED_VOCABULARY]
        if invalid:
            # Filter silently (post-processing per CONTEXT decision)
            return [t for t in v if t in CONTROLLED_VOCABULARY]
        return v

# For prompt injection:
schema = ExtractedMetadata.model_json_schema()

# For response validation:
validated = ExtractedMetadata.model_validate(parsed_json)
```

**Confidence:** HIGH -- Pydantic v2 is the standard approach for structured LLM output validation.

### Pattern 3: Magistral Response Parsing (thinking + text array)

**What:** Parse Mistral's magistral model responses which return content as array of objects
**When to use:** Every Mistral API call with magistral-medium-latest
**Example:**

```python
def parse_magistral_response(response) -> dict:
    """Extract JSON from magistral's array-format response."""
    content = response.choices[0].message.content

    # Phase 1: Handle array format (thinking + text objects)
    if isinstance(content, list):
        text_parts = [obj.text for obj in content if getattr(obj, 'type', None) == 'text']
        combined = ''.join(text_parts)
        try:
            return json.loads(combined)
        except json.JSONDecodeError:
            pass  # Fall through to regex

    # Phase 2: Handle string format (some modes)
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

    # Phase 3: Regex extraction (last resort)
    text = str(content)
    match = re.search(r'\{(?:[^{}]|\{[^{}]*\})*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    raise ValueError("No valid JSON found in response")
```

**Confidence:** HIGH -- verified from user's existing MIXTRAL-INVOCATION-GUIDE-YOUR-SYSTEM.md and Mistral docs.

### Pattern 4: Credit Exhaustion Checkpoint

**What:** Atomic save-on-each-file with clean pause on HTTP 402
**When to use:** All Wave 1 and Wave 2 processing
**Example:**

```python
class CheckpointManager:
    def __init__(self, checkpoint_path: Path):
        self.path = checkpoint_path

    def save(self, state: dict):
        """Atomic write: write to temp, then rename."""
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(self.path)

    def load(self) -> dict | None:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return None

# In orchestrator:
except MistralAPIException as e:
    if e.status_code == 402:  # Payment Required
        self._checkpoint.save({
            'wave': 'wave1',
            'lanes': {lane: lane.progress for lane in self._lanes},
            'next_file_index': current_idx,
            'timestamp': datetime.now().isoformat(),
        })
        # Display Rich notification panel
        console.print(Panel("MISTRAL CREDITS EXHAUSTED ...", style="red"))
        sys.exit(0)
```

**Confidence:** HIGH -- straightforward file-based checkpoint; similar to upload pipeline's state management.

### Anti-Patterns to Avoid

- **Mixed sync/async in extraction pipeline:** The upload pipeline is fully async. The extraction pipeline should also be async end-to-end to maintain consistency and enable proper semaphore-based concurrency. Do not mix `requests` with `asyncio`.
- **Modifying existing metadata_json directly:** The 4-tier AI metadata should be stored separately (in `file_metadata` table or new JSON columns) rather than mutating the scanner-extracted `metadata_json` field. Scanner metadata and AI metadata serve different purposes and have different update cycles.
- **Global state for rate limiting:** Use a single `AsyncLimiter` instance shared across all concurrent tasks, not per-task limiters. The Mistral API enforces limits globally across the account.
- **Retrying on 402 (Payment Required):** Unlike 429 (rate limit) which should be retried with backoff, 402 means credits are exhausted. Retrying wastes time. Detect and checkpoint immediately.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rate limiting | Custom deque-based limiter | `aiolimiter.AsyncLimiter` | Token bucket with proper burst handling; one-liner setup |
| JSON schema for prompts | String templates with hand-built schema | `Pydantic.model_json_schema()` | Generates valid JSON Schema from Python types; stays in sync with validation |
| LLM output validation | Manual dict key checking | `Pydantic.model_validate()` | Type coercion, enum validation, nested objects, clear error messages |
| API retries | Custom retry loop | `tenacity` (already in project) | Exponential backoff, retry-on-exception, max attempts, already proven |
| Async HTTP to Mistral | `aiohttp` raw client | `mistralai` SDK `.complete_async()` | Handles auth, response format, thinking block filtering, error types |
| Token counting | Character-based estimation | `mistralai` response `.usage` field | Exact counts from API response; estimation only needed for pre-flight budget checks |

**Key insight:** The `mistralai` SDK handles the hardest part -- magistral's array-format response with thinking/text blocks. Using the SDK avoids reimplementing response content extraction.

## Common Pitfalls

### Pitfall 1: Magistral Temperature Requirement
**What goes wrong:** Setting temperature < 1.0 for magistral-medium-latest causes degraded or error responses.
**Why it happens:** Mistral reasoning models require `temperature=1.0` (documented constraint for magistral family).
**How to avoid:** Hard-code temperature=1.0 in the extraction config for production (Wave 2). For Wave 1, only Lane A (Minimalist) uses temp=0.1 and Lane B uses temp=0.3 as explicit experiments -- document that these may fail and that's useful data.
**Warning signs:** Empty or nonsensical responses at low temperature settings.
**Confidence:** HIGH -- verified from user's existing config.js and Mistral docs.

### Pitfall 2: Actual File Count is ~473 TXT, Not 496
**What goes wrong:** Planning for 496 files but the actual count of processable `.txt` files with `category: "unknown"` is 473. The remaining 23 are `.epub` (3), `.pdf` (14), and other (6) files that cannot be processed by the text-based extraction pipeline.
**Why it happens:** The 496 count includes all unknown-category files regardless of format. Only `.txt` files can have their content sent to Mixtral.
**How to avoid:** Filter to `filename LIKE '%.txt'` AND `category = 'unknown'` for processing targets. The 333 Peikoff Podcast files with `series: "Peikoff Podcast"` are also in this 473 count and WILL be processed (they have category "unknown" but do have episode metadata).
**Warning signs:** Processing pipeline trying to read `.epub` content as text.
**Confidence:** HIGH -- verified from database query.

### Pitfall 3: Unknown Files Have Heterogeneous Sub-Populations
**What goes wrong:** Treating all 473 unknown files as homogeneous when they have very different characteristics.
**Why it happens:** The unknown category contains at least 3 distinct populations:
  - **333 Peikoff Podcast episodes** -- have episode_number, episode_id; mostly medium-sized (8-20KB)
  - **~140 miscellaneous TXT files** -- OCON talks, essays, Q&A sessions, coaching calls; wide size range (2KB-89KB)
  - Each population needs different prompting emphasis
**How to avoid:** Wave 1 test file selection MUST include samples from both populations. Stratified sampling should account for "podcast vs non-podcast" in addition to file size.
**Warning signs:** Prompt works great for essays but produces nonsensical categories for podcast transcripts.
**Confidence:** HIGH -- verified from database query showing 333 podcast + 140 other.

### Pitfall 4: JSON Mode + Thinking Blocks Conflict
**What goes wrong:** Enabling `response_format: { type: "json_object" }` with magistral models that also produce thinking blocks can cause unexpected response structures.
**Why it happens:** The `content` field returns an array `[{type: "thinking", ...}, {type: "text", ...}]` even in JSON mode. The JSON is inside the `text` object, not the top-level content.
**How to avoid:** Always use the two-phase parser (Pattern 3 above). Never assume `content` is a plain string. Test with actual magistral-medium-latest responses in Wave 1.
**Warning signs:** `json.loads(response.choices[0].message.content)` throws TypeError (content is list, not string).
**Confidence:** HIGH -- verified from user's existing MIXTRAL-INVOCATION-GUIDE-YOUR-SYSTEM.md.

### Pitfall 5: Database Schema Migration on Existing Data
**What goes wrong:** Adding new columns or tables breaks existing queries or corrupts the 1,884 file records already in the database.
**Why it happens:** The database has real data (866 courses, 469 MOTM, 496 unknown, etc.) with existing triggers and indexes.
**How to avoid:** Use `ALTER TABLE ... ADD COLUMN` for new columns on `files` table. Create new tables (`file_metadata`, `file_primary_topics`) without touching existing structure. Wrap migration in a transaction. Add a PRAGMA user_version check (currently version 2; increment to 3).
**Warning signs:** Schema changes that require data migration or column type changes.
**Confidence:** HIGH -- standard SQLite migration practice.

### Pitfall 6: Context Window vs File Size Mismatch
**What goes wrong:** Sending files >128K tokens to magistral-medium-latest causes truncation or timeout.
**Why it happens:** File sizes range from 2.6KB to 89KB for TXT unknowns (non-podcast). At ~4 chars/token, an 89KB file is ~22K tokens. This fits within the 128K context window, but the prompt + schema + examples add ~2-4K tokens, and the response needs room (~2K tokens). Very large files (>100KB, like the 1MB Fossil Future.txt) would overflow.
**How to avoid:** The adaptive chunking strategy (W2.A5) handles this. For the 20 very_large files (>100KB), use head-tail windowing. For the vast majority (474 files under 100KB), send full text. Pre-calculate token estimate before each call and choose strategy accordingly.
**Warning signs:** Timeouts (>240s) or incomplete responses on large files.
**Confidence:** HIGH -- verified file size distribution from database.

## Code Examples

### Mistral SDK - Async Chat Completion with JSON Mode

```python
# Source: mistralai SDK docs + user's MIXTRAL-INVOCATION-GUIDE
import os
from mistralai import Mistral

client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

# Async call with JSON mode
response = await client.chat.complete_async(
    model="magistral-medium-latest",
    messages=[
        {"role": "system", "content": "You are an Objectivist philosophy archivist. Return ONLY valid JSON."},
        {"role": "user", "content": f"Extract metadata from: {transcript_text}"}
    ],
    temperature=1.0,               # Required for magistral reasoning models
    max_tokens=8000,               # Generous for 4-tier extraction
    response_format={"type": "json_object"}
)

# Parse magistral response (content is array, not string)
content = response.choices[0].message.content
if isinstance(content, list):
    text_obj = next((obj for obj in content if getattr(obj, 'type', None) == 'text'), None)
    json_str = text_obj.text if text_obj else ''
else:
    json_str = content

result = json.loads(json_str)
print(f"Tokens used: {response.usage.total_tokens}")
```

### Database Migration for Phase 6

```python
# Source: pattern from existing database.py
MIGRATION_V3_SQL = """
-- Add AI metadata status to files table
ALTER TABLE files ADD COLUMN ai_metadata_status TEXT DEFAULT 'pending'
    CHECK(ai_metadata_status IN (
        'pending', 'extracted', 'partial', 'needs_review',
        'failed_json', 'failed_validation', 'retry_scheduled', 'approved'
    ));

-- Add confidence score column for fast filtering
ALTER TABLE files ADD COLUMN ai_confidence_score REAL;

-- Versioned AI metadata storage (append-only history)
CREATE TABLE IF NOT EXISTS file_metadata_ai (
    metadata_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    metadata_json TEXT NOT NULL,         -- Full 4-tier JSON structure
    model TEXT NOT NULL,                  -- 'magistral-medium-latest'
    model_version TEXT,
    prompt_version TEXT NOT NULL,
    extraction_config_hash TEXT,
    is_current BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);
CREATE INDEX IF NOT EXISTS idx_ai_meta_current ON file_metadata_ai(file_path, is_current);

-- Junction table for controlled vocabulary topics (fast filtering)
CREATE TABLE IF NOT EXISTS file_primary_topics (
    file_path TEXT NOT NULL,
    topic_tag TEXT NOT NULL,
    PRIMARY KEY (file_path, topic_tag),
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);
CREATE INDEX IF NOT EXISTS idx_primary_topic_tag ON file_primary_topics(topic_tag);

-- Wave 1 comparison results
CREATE TABLE IF NOT EXISTS wave1_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    strategy TEXT NOT NULL,              -- 'minimalist', 'teacher', 'reasoner'
    metadata_json TEXT NOT NULL,
    raw_response TEXT,                    -- Optional debug storage
    token_count INTEGER,
    latency_ms INTEGER,
    confidence_score REAL,
    human_edit_distance REAL,            -- Filled during review
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    FOREIGN KEY (file_path) REFERENCES files(file_path)
);
"""
```

### Pydantic Schema with JSON Schema Generation for Prompt

```python
# Source: Pydantic v2 docs
from pydantic import BaseModel, Field, ConfigDict, field_validator
from enum import Enum

CONTROLLED_VOCABULARY = {
    "epistemology", "metaphysics", "ethics", "politics", "aesthetics",
    "reason", "volition", "rational_egoism", "individual_rights", "capitalism",
    "objective_reality", "consciousness", "existence", "identity",
    "altruism", "mysticism", "collectivism", "pragmatism", "intrinsicism",
    "subjectivism", "determinism", "concept_formation", "free_will",
    "emotions", "rights_theory", "art_theory", "virtue_ethics",
    # ... remaining ~13 tags to reach 40
}

class ExtractedMetadata(BaseModel):
    category: str = Field(description="Exactly 1 from: course_transcript, book_excerpt, qa_session, article, philosophy_comparison, concept_exploration, cultural_commentary")
    difficulty: str = Field(description="One of: intro, intermediate, advanced")
    primary_topics: list[str] = Field(min_length=3, max_length=8, description="Select ONLY from controlled vocabulary")
    topic_aspects: list[str] = Field(min_length=3, max_length=10, description="Novel specific concepts from text")
    semantic_description: dict = Field(description="Object with summary, key_arguments, philosophical_positions")
    confidence_score: float = Field(ge=0.0, le=1.0, description="Self-assessed extraction confidence")

    model_config = ConfigDict(extra='ignore')

# Generate schema for prompt injection
schema = ExtractedMetadata.model_json_schema()
# Inject into prompt: "Return JSON matching this schema: {json.dumps(schema)}"
```

### Async Extraction with Rate Limiting and Checkpoint

```python
# Source: pattern from existing upload/orchestrator.py + aiolimiter docs
import asyncio
from aiolimiter import AsyncLimiter

class ExtractionOrchestrator:
    def __init__(self, client, config):
        self._client = client
        self._semaphore = asyncio.Semaphore(3)           # Max 3 concurrent
        self._rate_limiter = AsyncLimiter(60, 60)         # 60 requests per 60 seconds
        self._checkpoint = CheckpointManager(config.checkpoint_path)

    async def process_batch(self, files: list[dict]):
        tasks = [self._process_one(f) for f in files]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

    async def _process_one(self, file_record: dict):
        async with self._semaphore:
            async with self._rate_limiter:
                try:
                    result = await self._client.extract(file_record)
                    # Save immediately (atomic per-file)
                    self._save_result(file_record, result)
                    return result
                except CreditExhaustedException:
                    self._checkpoint.save_and_exit()
                except RateLimitException:
                    # Exponential backoff handled by tenacity/SDK
                    raise
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `MistralClient` class import | `Mistral` direct import | mistralai SDK 1.0+ (2025) | Import path changed: `from mistralai import Mistral` |
| `response.choices[0].message.content` as string | Content as array of objects (thinking + text) | magistral models (June 2025) | Must filter for `type='text'` objects in content array |
| `open-mixtral-8x7b` model | `magistral-medium-latest` reasoning model | June 2025 | 128K context, $2/M input, $5/M output, requires temp=1.0 |
| Pydantic v1 `.schema()` | Pydantic v2 `.model_json_schema()` | Pydantic 2.0 (2023) | New method names, `ConfigDict`, `model_validate()` |

**Deprecated/outdated:**
- `from mistralai.client import MistralClient` -- old SDK import; use `from mistralai import Mistral`
- `response_format={"type": "json_object"}` alone may not be sufficient for magistral reasoning models; test in Wave 1 whether `json_schema` type with explicit schema produces better compliance
- The mixtral-invocation-guide.md in the project references `open-mixtral-8x7b` as the default model; the actual model to use is `magistral-medium-latest`

## Codebase-Specific Findings

### Existing Patterns to Reuse

1. **Async orchestrator pattern** (`upload/orchestrator.py`): Semaphore-based concurrency, signal handling, progress tracking. Can be adapted for extraction pipeline.

2. **Rate limiter** (`upload/rate_limiter.py`): Existing `AdaptiveRateLimiter` with circuit breaker. However, this is configured for Gemini API rate limits (tier-based RPM). The Mistral API has different limits (60 req/min, 3 concurrent). Recommend creating a Mistral-specific rate limiter using `aiolimiter` for simplicity rather than adapting the Gemini one.

3. **Database layer** (`database.py`): WAL mode, UPSERT pattern, JSON metadata via `json_extract()`. Phase 6 schema additions should follow the same conventions.

4. **API key management** (`config.py`): Keyring-based with env var fallback. Add a parallel service for Mistral: `objlib-mistral` / `mistral_api_key`.

5. **CLI structure** (`cli.py`): Typer app with subcommand groups. The existing `metadata_app` typer group can be extended with `extract`, `review`, `approve` commands.

### Existing Database State

- **1,884 total files** (1,721 pending, 135 skipped, 18 uploaded, 10 failed)
- **496 unknown-category files**: 333 Peikoff Podcast + 140 misc TXT + 23 non-TXT
- **473 processable TXT files** with `category: "unknown"` (the actual extraction target)
- **Current metadata keys**: category, topic, course, series, episode_number, episode_id, year, quarter, week, lesson_number, date, raw_filename
- **Schema version**: PRAGMA user_version = 2

### File Size Distribution (Unknown TXT Files)

| Bucket | Count | Avg Size | Range |
|--------|-------|----------|-------|
| Small (<5KB) | 2 | 3.5KB | 2.6-4.4KB |
| Medium (5-20KB) | 327 | 12.1KB | 6-19KB |
| Large (20-100KB) | 147 | 56.4KB | 20-95KB |
| Very large (>100KB) | 20 | 1.1MB | 103KB-7MB |

**Critical finding for Wave 1 test selection:** The "small" bucket has only 2 files. The stratified sampling plan in CONTEXT.md calls for 5 small files. Either (a) include the 2 small files + 3 from the lower end of medium, or (b) adjust bucket boundaries (e.g., <10KB = small).

### Cost Estimation (Updated)

Based on 473 TXT files (not 496) and magistral-medium-latest pricing ($2/M input, $5/M output):

**Wave 1 (20 files x 3 strategies = 60 API calls):**
- Average input: ~3K tokens (12KB file / 4 chars per token) + ~500 tokens prompt = ~3.5K
- Average output: ~1K tokens (4-tier JSON)
- Cost per call: (3,500 x $2/M) + (1,000 x $5/M) = $0.007 + $0.005 = $0.012
- **Wave 1 total: ~60 x $0.012 = ~$0.72** (well under $20-30 budget)
- Budget headroom allows for retries, Wave 1.5, and experimentation

**Wave 2 (453 remaining files x 1 call each + retries):**
- Same per-call cost: ~$0.012
- With ~10% retry rate: 453 x 1.1 x $0.012 = ~$5.98
- **Wave 2 total: ~$6** (well under $110-164 budget)

**Note:** The CONTEXT.md budget estimates ($130-194 total) appear to be based on older, more expensive pricing or more verbose prompts. Actual costs will likely be 5-10x lower than budgeted. This is good news but should be validated in Wave 1.

**Confidence:** MEDIUM -- pricing verified from Perplexity search but actual token counts depend on prompt length and response verbosity; Wave 1 will provide exact data.

## Open Questions

1. **Mistral API Key Storage**
   - What we know: Gemini key is in keyring as `objlib-gemini/api_key`. Mistral key is currently in macOS keychain as `mistral-api-key` (from the knowledge-graph project, different from this project).
   - What's unclear: Should Phase 6 use the existing `mistral-api-key` keychain entry, or create a new `objlib-mistral` keyring entry for consistency with `objlib-gemini`?
   - Recommendation: Create `objlib-mistral` keyring entry for consistency. Add `config set-mistral-key` CLI command parallel to existing `config set-api-key`.

2. **Podcast File Processing Strategy**
   - What we know: 333 of 473 files are Peikoff Podcast episodes. They already have `episode_number` and `episode_id` metadata but `category: "unknown"`.
   - What's unclear: Should these be batch-categorized as "podcast" without AI (simple metadata update), or should AI also extract topics/aspects from podcast transcripts?
   - Recommendation: Process them through the full AI pipeline. Their category may map to `qa_session` or `concept_exploration` depending on episode content. The topic/aspect extraction adds genuine search value.

3. **Controlled Vocabulary Completeness**
   - What we know: DECISION-HYBRID-TAXONOMY.md defines ~40 tags but only lists ~30 explicitly.
   - What's unclear: The exact 40-tag list needs to be finalized before Wave 1 (it goes into the prompt).
   - Recommendation: Finalize the controlled vocabulary list as the first task in Phase 6 planning. It's a prerequisite for all prompt construction.

4. **Wave 1 Report Format**
   - What we know: Human review uses edit distance scoring on side-by-side comparison.
   - What's unclear: Should the comparison report be HTML (richer display), CSV (spreadsheet-friendly), or Rich terminal output?
   - Recommendation: Generate both CSV (for scoring) and Rich terminal display (for quick review). HTML is over-engineering for 20 files.

## Sources

### Primary (HIGH confidence)
- Existing codebase: `src/objlib/` -- database.py, models.py, cli.py, upload/*.py (verified current state)
- SQLite database: `data/library.db` -- queried for exact file counts, size distributions, metadata patterns
- User documents: DECISION-HYBRID-TAXONOMY.md, MIXTRAL-INVOCATION-GUIDE-YOUR-SYSTEM.md (project-specific)

### Secondary (MEDIUM confidence)
- Mistral AI docs: https://docs.mistral.ai/models/magistral-medium-1-2-25-09 -- 128K context, pricing
- Mistral AI SDK: https://docs.mistral.ai/getting-started/clients -- Python SDK usage patterns
- Mistral reasoning docs: https://docs.mistral.ai/capabilities/reasoning -- thinking/text response format
- Pydantic v2 docs: https://docs.pydantic.dev/latest/ -- model_validate, model_json_schema
- aiolimiter: https://aiolimiter.readthedocs.io -- AsyncLimiter API

### Tertiary (LOW confidence)
- Mistral pricing from Perplexity search: $2/M input, $5/M output for magistral-medium-latest -- verify on https://mistral.ai/pricing before Wave 1
- Mistral rate limits from Perplexity search: Tier-based, varies by account level -- verify actual limits on https://console.mistral.ai/

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - `mistralai` SDK, Pydantic, aiolimiter are well-documented, verified through official docs
- Architecture: HIGH - Mirrors existing codebase patterns (upload orchestrator, database layer, CLI structure)
- Pitfalls: HIGH - Verified through actual database queries and user's existing Mixtral integration guide
- Cost estimates: MEDIUM - Pricing verified but actual token usage depends on prompt design (Wave 1 validates)
- API specifics: MEDIUM - magistral-medium-latest response format verified from docs + user guide, but SDK version evolution may change details

**Research date:** 2026-02-16
**Valid until:** 2026-03-16 (30 days -- Mistral SDK and pricing may change)
