# Data Pipeline

The system follows a six-stage pipeline: Scan → AI Metadata → Upload → Sync (incremental) → Search → Display.

```
Library files
     │
     ▼
 [1] Scan ──────────────────────► SQLite (files table)
                                       │
     ┌─────────────────────────────────┘
     │
     ▼
 [2] AI Metadata (Mistral Batch) ► SQLite (file_metadata_ai table)
                                       │
     ┌─────────────────────────────────┘
     │
     ▼
 [3] Upload (Gemini File Search) ► Gemini Store (1,721 files)
                                       │
     ┌─────────────────────────────────┘
     │
     ▼
 [3b] Sync (incremental updates) ► Gemini Store (new/modified/pruned)
      ├── new files → enriched upload
      ├── modified → upload-first replace
      └── deleted → mark missing / prune
                                       │
     ┌─────────────────────────────────┘
     │
     ▼
 [4] Search (Gemini + reranker) ──► Citations (with enrichment)
                                       │
     ┌─────────────────────────────────┘
     │
     ▼
 [5] Display (Rich terminal UI) ──► User
```

---

## Stage 1: Scan (`scan` command)

**Entry point:** `objlib scan --library /path/to/library`
**Code:** `src/objlib/scanner.py`, `src/objlib/metadata.py`

The scanner walks the library directory tree (typically `/Volumes/U32 Shadow/Objectivism Library`) and extracts metadata from the folder hierarchy and filename.

### Folder Structure Pattern

```
/Library Root/
  Category/
    Course Name/
      Year/
        Quarter/
          Week N - Topic Name - Instructor.txt
```

**Example:** `Courses/OPAR/2022/Q1/Week 3 - The Nature of Reason - Leonard Peikoff.txt`

Extracted metadata: `category=course`, `course=OPAR`, `year=2022`, `quarter=Q1`, `week=3`, `topic=The Nature of Reason`, `instructor=Leonard Peikoff`

### Change Detection

For each file found:
- Compute SHA-256 content hash
- Compare against stored hash in SQLite
- Classify as: **new** (path not in DB), **modified** (hash changed), **deleted** (in DB but not on disk), **unchanged**

UPSERT logic: if hash changed → reset status to `pending` (triggers re-upload). If unchanged → preserve existing status.

### Output

Each file stored in `files` table with:
- `file_path` (primary key, relative to library root)
- `content_hash` (SHA-256 hex)
- `filename`, `file_size`
- `metadata_json` (JSON blob of extracted fields)
- `metadata_quality` (complete/partial/minimal/none/unknown)
- `status` = `pending` (new/modified) or existing value

---

## Stage 2: AI Metadata Extraction (`metadata batch-extract`)

**Entry point:** `objlib metadata batch-extract`
**Code:** `src/objlib/extraction/batch_orchestrator.py`, `src/objlib/extraction/batch_client.py`

Uses Mistral's asynchronous Batch API to extract 4-tier metadata from all `.txt` files with `ai_metadata_status = 'pending'`.

### 4-Tier Metadata Schema

| Tier | Field | Description |
|------|-------|-------------|
| 1 | `category` | Content category (course, book, motm, qa_session, philosophy_comparison, cultural_commentary, other) |
| 1 | `difficulty` | introductory / intermediate / advanced |
| 2 | `primary_topics` | Exactly 8 topics from a controlled vocabulary (e.g., metaphysics, epistemology, ethics, politics) |
| 3 | `topic_aspects` | Unlimited specific themes and subtopics found in the text |
| 4 | `semantic_description` | Three AI-generated summaries: abstract (1-2 sentences), pedagogical context, key claims list |

### Batch Process

1. Query `pending` files from SQLite
2. For each file: read text, build Mistral prompt (minimalist strategy), create JSONL batch request
3. Submit batch job to Mistral API
4. Poll every 30 seconds for completion (typically 20–60 min for 700+ files)
5. Parse responses, validate schema, compute confidence score
6. Store results in `file_metadata_ai` table (versioned, append-only with `is_current` flag)
7. Update `files.ai_metadata_status` and `files.ai_confidence_score`

### Confidence Scoring

Multi-dimensional composite score:
- Category confidence: weight 0.30
- Topics confidence: weight 0.40
- Aspects confidence: weight 0.15
- Description confidence: weight 0.15

Hallucination penalty: -0.15 for short transcripts (<800 chars) with high tier4 confidence.

### Validation

- `primary_topics` must be exactly 8 items from controlled vocabulary
- `category` must match allowed values (alias repair via substring matching)
- Files failing validation: `ai_metadata_status = 'failed_validation'`
- Files needing human review (confidence < 0.85): `ai_metadata_status = 'needs_review'`

---

## Stage 3: Upload (`enriched-upload` command)

**Entry point:** `objlib enriched-upload --store objectivism-library-test`
**Code:** `src/objlib/upload/orchestrator.py` (EnrichedUploadOrchestrator), `src/objlib/upload/metadata_builder.py`, `src/objlib/upload/content_preparer.py`

### Pre-Upload Steps

For each file eligible for enriched upload:
1. **Build enriched metadata**: flatten AI 4-tier metadata + entity mentions into Gemini `custom_metadata` format (7–9 string_list_value fields)
2. **Prepare enriched content**: prepend AI analysis header to file content
3. **Compute upload hash**: SHA-256 of (Phase 1 metadata + AI metadata + entities + content_hash) — idempotency guard

### Gemini Upload

- `Semaphore(2)` concurrency (conservative to avoid Gemini rate limits)
- 1-second stagger between uploads
- Exponential backoff on 429 / 503 errors
- Circuit breaker trips on: 5% rate threshold OR 3 consecutive 429s

### State Tracking

Before each upload:
1. Record upload intent in `upload_operations` table (crash recovery anchor)
2. Make API call
3. Update result (succeeded/failed)

### Idempotency

Before uploading, check `last_upload_hash`:
- If hash matches → skip (content unchanged)
- If hash differs or null → re-upload
- If status = `failed` → always retry (handles polling timeouts)

### Post-Batch Retry

After each batch: one retry pass with 30-second cooldown for any files that failed.

### TTL Management

Gemini files expire after 48 hours. `remote_expiration_ts` is tracked in SQLite. Files with expired TTL are deleted from Gemini and re-uploaded.

---

## Stage 3b: Sync (`sync` command)

**Entry point:** `objlib sync [--dry-run] [--force] [--prune-missing]`
**Code:** `src/objlib/sync/detector.py`, `src/objlib/sync/orchestrator.py`

Keeps the Gemini store current as the library evolves, without re-uploading unchanged files.

### Startup Checks

1. **Disk availability**: `check_disk_availability()` verifies the library mount is present. Aborts with a clear error if not.
2. **Library config**: reads `gemini_store_display_name` from `library_config` table. If set and differs from current `--store` value, aborts (prevents cross-store accidents). If not set, records the current store name.
3. **Auto-orphan cleanup**: queries `files` for rows with `orphaned_gemini_file_id IS NOT NULL` (leftover from interrupted replacements) and deletes them from the Gemini store via `delete_store_document()`.

### Change Detection (SyncDetector)

1. Discover all eligible files on disk via `FileScanner.discover_files()`
2. Load DB state: `get_all_active_files_with_mtime()` → `{path: (hash, size, mtime)}`
3. Classify: **new** (on disk, not in DB), **missing** (in DB, not on disk), **common** (both)
4. For common files:
   - **mtime optimization**: if DB mtime matches current mtime (within 1e-6 epsilon) and not `--force` → skip hash (mtime_skipped)
   - Otherwise: compute SHA-256 hash
   - If hash differs → **modified**; if hash matches → **unchanged** (update DB mtime)

### Upload New Files

Uses the enriched upload pipeline by default (Phase 1 metadata + AI metadata + entity names → `build_enriched_metadata()` + `prepare_enriched_content()`). Falls back to `build_custom_metadata()` if AI metadata is missing for a file. `--skip-enrichment` forces basic metadata for all files.

Per-file SQLite commits for crash recovery.

### Upload-First Replacement (Modified Files)

For each modified file:
1. Upload new version → get new `gemini_file_id`
2. Store old ID in `orphaned_gemini_file_id`, update record to new ID
3. Find old store document: `find_store_document_name(old_id)` → `delete_store_document(doc_name)`
4. On delete success: `clear_orphan()`. On failure: leave for next startup cleanup (fire-and-forget)

### Missing File Handling

`mark_missing(changeset.missing_files)`: sets `status='missing'`, records `missing_since` timestamp. **Does not** delete from Gemini automatically.

`--prune-missing`: deletes Gemini store entries for files with `status='missing'` and `missing_since` older than 7 days. Updates status to `LOCAL_DELETE`.

### Dry-Run Mode

`--dry-run`: initializes `SyncDetector`, runs change detection, renders Rich tables of new/modified/missing files, then exits without uploading or marking anything.

---

## Stage 4: Search

**Entry point:** `python -m objlib --store NAME search "query"`
**Code:** `src/objlib/search/` (client, reranker, synthesizer, expansion, citations)

The search pipeline has 7 stages:

### 4a: Query Expansion

Loads `synonyms.yml` glossary. Scans query for known terms (longest-first). For each match, appends original term + top 2 synonyms to query.

Example: `"egoism"` → `"egoism egoism rational self-interest selfishness"`

Cached at module level for performance.

### 4b: Gemini File Search

Sends expanded query to Gemini File Search via `query_with_retry()`. Applies AIP-160 metadata filter if `--filter` was specified.

Returns `GenerateContentResponse` with grounding metadata containing:
- Response text (Gemini's answer)
- `grounding_chunks` (source file references)
- `grounding_supports` (passage text ↔ source mappings)

### 4c: Citation Extraction & Enrichment

**Extraction:** Parses `grounding_metadata` into `Citation` objects (title, uri, text, file ID).

**Enrichment (two-pass lookup):**
1. Try lookup by filename in SQLite
2. If not found: lookup by Gemini file ID (`files/e0x3xq9wtglq` → `e0x3xq9wtglq` mapping)

Enriched citations include: file_path, course, difficulty, category, year, week, instructor from SQLite metadata.

**Passage caching:** Each citation passage is stored in the `passages` table (UUID5 of file_id + content_hash) for citation stability.

### 4d: Reranking

Gemini Flash scores each passage 0–10 for relevance to the original query. Temperature 0.0 for deterministic scores. Passages truncated to 500 chars to save tokens. Results reordered by score.

Falls back to Gemini's original ranking if reranking fails.

### 4e: Difficulty Ordering

Groups citations into difficulty buckets (intro=0, intermediate=1, advanced=2) based on extracted metadata. Unknown difficulty defaults to intermediate. Processes top 20 results.

- `--mode learn`: sorts buckets intro → intermediate → advanced
- `--mode research`: preserves rerank order

### 4f: Session Logging

If `OBJLIB_SESSION` is set, logs a `search` event to `session_events` table (query, expanded query, result count, top doc IDs). Best-effort — search proceeds even if session logging fails.

### 4g: Display Branch

- Default: `display_search_results()` — Rich panels for each citation
- `--synthesize`: MMR diversity filter → `synthesize_answer()` → `display_synthesis()`
- `--track-evolution`: `display_concept_evolution()` grouped by difficulty bucket

**MMR Diversity (for synthesis):** Max 2 passages per file. Prefers unseen files with unseen courses. Returns None if fewer than 5 citations.

**Synthesis:** Gemini Flash with structured `SynthesisOutput` schema. Validates that cited quotes appear in source passages. Returns partial results (only validated claims) after second attempt.

---

## Stage 5: Display (`src/objlib/search/formatter.py`)

The formatter renders results using Rich panels and tables:

- **Standard results**: Rich Panel per citation with title, course/difficulty badge, text excerpt
- **Synthesis**: Full answer panel with inline citation numbers (`[1]`, `[2]`), followed by source attribution list
- **Concept evolution**: Three panels (Introductory / Intermediate / Advanced) with grouped results

Session events are appended after display completes (for synthesize events).

---

_Last updated: Phase 5 — Sync stage (incremental change detection, upload-first replacement, missing file handling)_
