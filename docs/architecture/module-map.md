# Module Map

Responsibilities and key file paths for every module in `src/objlib/`.

## Top-Level Files

### `cli.py`

**Primary entry point for all user interactions.**

Contains the Typer app and all command definitions organized into sub-apps. The file is large (~3,100 lines) because every command is defined inline (no separate command modules).

Key structures:
- `app`: Main Typer app with `app_callback()` for Gemini initialization
- `_GEMINI_COMMANDS = {"search"}`: allowlist for commands that need Gemini client init
- `AppState`: dataclass holding `gemini_client`, `store_resource_name`, `db_path`, `terminal_width`
- `DEFAULT_LIBRARY_ROOT`, `DEFAULT_MOUNT_POINT`: constants used by offline disk guards
- Sub-apps: `config_app`, `metadata_app`, `entities_app`, `session_app`, `glossary_app`

Commands defined:
- Root: `scan`, `status`, `purge`, `upload`, `enriched-upload`, `sync`, `search`, `view`, `browse`, `filter`
- `config`: `set-api-key`, `get-api-key`, `remove-api-key`, `set-mistral-key`, `get-mistral-key`, `remove-mistral-key`
- `metadata`: `show`, `update`, `batch-update`, `extract-wave1`, `wave1-report`, `wave1-select`, `extract`, `review`, `approve`, `stats`, `batch-extract`
- `entities`: `extract`, `stats`, `report`
- `session`: `start`, `list`, `resume`, `note`, `export`
- `glossary`: `list`, `add`, `suggest`

**Disk availability guards (Phase 5):** `scan`, `upload`, `enriched-upload`, and `sync` call `check_disk_availability()` at startup and abort with an actionable error when `/Volumes/U32 Shadow` is not mounted. Query commands (`search`, `browse`, `filter`, `view`) have no disk dependency. `view --full` distinguishes disk disconnection from file deletion.

**`--store` parameter position:**
- For `search`: defined in `app_callback()` → must come before subcommand
- For `view --show-related`: defined inline in `view()` → must come after subcommand

### `database.py`

**SQLite connection, schema, and all query methods.**

- `SCHEMA_SQL`: Initial schema (V1/V2) — `files`, `_processing_log`, `_extraction_failures`, `_skipped_files`, `upload_operations`, `upload_batches`, `upload_locks`
- `MIGRATION_V3_SQL`: AI metadata tables — `file_metadata_ai`, `file_primary_topics`, `wave1_results`
- `MIGRATION_V4_SQL`: Entity tables — `person`, `person_alias`, `transcript_entity` with seed data for 15 canonical persons
- `MIGRATION_V6_SQL`: Phase 4 tables — `passages`, `sessions`, `session_events`
- `MIGRATION_V7_SQL`: Sync columns — table rebuild to expand CHECK constraint; adds `mtime`, `orphaned_gemini_file_id`, `missing_since`, `upload_hash`, `enrichment_version` to `files`; creates `library_config` table
- `Database` class: context manager, WAL mode setup, schema migration, all CRUD methods

Key methods: `upsert_file()`, `get_pending_files()`, `get_status_counts()`, `get_file_metadata_by_filenames()`, `filter_files_by_metadata()`, `upsert_passage()`, `get_files_needing_entity_extraction()`, `save_transcript_entities()`, `get_enriched_pending_files()`, `get_ai_metadata_stats()`, `approve_files_by_confidence()`

Sync methods (Phase 5): `mark_missing()`, `get_missing_files()`, `get_orphaned_files()`, `clear_orphan()`, `update_file_sync_columns()`, `get_file_with_sync_data()`, `get_all_active_files_with_mtime()`, `set_library_config()`, `get_library_config()`

### `models.py`

**Core dataclasses** (not Pydantic — these are stdlib `dataclass`).

- `FileRecord`: file_path, content_hash, filename, file_size, metadata, status
- `FileStatus`: Enum (pending, uploading, uploaded, failed, skipped, LOCAL_DELETE, **missing**, **error**)
- `MetadataQuality`: Enum (complete, partial, minimal, none, unknown)
- `AppState`: gemini_client, store_resource_name, db_path, terminal_width
- `UploadConfig`: store_name, api_key, max_concurrent_uploads, batch_size, db_path, rate_limit_tier
- `Citation`: index, title, uri, text, document_name, confidence, file_path, metadata

### `config.py`

**Configuration loading and API key retrieval.**

- `ScannerConfig`: dataclass with library_path, db_path, file_extensions
- `load_config(path)`: loads JSON config file
- `get_api_key()`: retrieves Gemini key from keyring (`objlib-gemini`)
- `get_api_key_from_keyring()`: same as above (alias)
- `get_mistral_api_key()`: retrieves Mistral key from keyring (`objlib-mistral`)

---

## `scanner/` (implemented as `scanner.py`)

**File scanning and metadata extraction.**

`src/objlib/scanner.py`:
- `FileScanner`: walks directory tree, calls `MetadataExtractor`, computes hashes, calls `Database.upsert_file()`
- `ChangeSet`: dataclass with sets: `new`, `modified`, `deleted`, `unchanged`
- Change detection: compare SHA-256 content hash against stored hash

`src/objlib/metadata.py`:
- `MetadataExtractor`: parses folder hierarchy + filename into metadata dict
- Pattern matching: COMPLEX_PATTERN tried first (more specific), SIMPLE_PATTERN as fallback
- Folder metadata merged with filename metadata (filename takes precedence on overlap)
- Graceful degradation: unrecognized filenames get MINIMAL quality with topic from stem

---

## `upload/`

**Gemini File Search upload pipeline.**

| File | Responsibility |
|------|----------------|
| `orchestrator.py` | `UploadOrchestrator` and `EnrichedUploadOrchestrator` — drive the batch upload loop, coordinate all components |
| `state.py` | `AsyncUploadStateManager` — aiosqlite-based state manager, crash recovery, upload intent recording |
| `metadata_builder.py` | `build_enriched_metadata()` — flattens 4-tier AI metadata + entities into Gemini `custom_metadata` format |
| `content_preparer.py` | `prepare_enriched_content()` — prepends AI analysis header to file content; returns None if no Tier 4 content |
| `client.py` | `GeminiFileSearchClient` — wraps google-genai SDK, handles file upload, polling, deletion, store document management (`delete_store_document`, `list_store_documents`, `find_store_document_name`) |
| `circuit_breaker.py` | `RollingWindowCircuitBreaker` — trips on 5% rate threshold OR 3 consecutive 429s |
| `rate_limiter.py` | `AdaptiveRateLimiter` — Tier 1 defaults (20 RPM, 3s interval), 3x delay multiplier when circuit OPEN |
| `progress.py` | `UploadProgressTracker` — Rich progress bar display |
| `recovery.py` | Crash recovery utilities (post-batch retry pass, 30s cooldown) |

**Key design:** Upload intent recorded BEFORE API call (`upload_operations` table). On crash, incomplete uploads are detected and retried. Circuit breaker OPEN → skips files rather than blocking.

---

## `search/`

**Search pipeline: query, rank, synthesize, display.**

| File | Responsibility |
|------|----------------|
| `client.py` | `GeminiSearchClient` — `query_with_retry()`, `resolve_store_name()`, builds `GenerateContentConfig` with grounding |
| `citations.py` | `extract_citations()` from grounding metadata, `enrich_citations()` (two-pass DB lookup), `build_metadata_filter()` (AIP-160 syntax) |
| `reranker.py` | `rerank_passages()` — Gemini Flash scores passages 0–10; `apply_difficulty_ordering()` — bucket sort by difficulty |
| `synthesizer.py` | `synthesize_answer()` — Gemini Flash with `SynthesisOutput` Pydantic schema, quote validation; `apply_mmr_diversity()` — max 2 passages per file |
| `expansion.py` | `expand_query()` — longest-first phrase matching against glossary, term boosting; `load_glossary()` — YAML loader with module-level cache; `add_term()` — adds to `synonyms.yml` |
| `formatter.py` | `display_search_results()`, `display_detailed_view()`, `display_synthesis()`, `display_concept_evolution()`, `display_full_document()` — all Rich UI |
| `models.py` | Pydantic models: `RankedResult`, `RankedResults` (for reranker), `SynthesisClaim`, `SynthesisOutput` (for synthesis) |
| `synonyms.yml` | Curated Objectivist terminology glossary (40+ terms with synonyms) |
| `__init__.py` | Package init |

**Note:** `search/models.py` (Pydantic) is separate from top-level `models.py` (dataclasses).

---

## `extraction/`

**Mistral AI metadata extraction (Phase 6).**

| File | Responsibility |
|------|----------------|
| `batch_orchestrator.py` | `BatchExtractionOrchestrator` — Mistral Batch API workflow: build JSONL, submit, poll, parse, save |
| `batch_client.py` | `MistralBatchClient` — wraps mistralai SDK for batch job submission and polling |
| `orchestrator.py` | `ExtractionOrchestrator` — Wave 1 (competitive strategies) and Wave 2 (production) synchronous extraction |
| `client.py` | `MistralClient` — synchronous Mistral API wrapper for Wave 1/2 |
| `validator.py` | `validate_metadata()` — validates 4-tier schema; `_filter_primary_topics()` — normalizes to exactly 8 topics from controlled vocabulary |
| `schemas.py` | Pydantic schema for 4-tier metadata output |
| `prompts.py` | Prompt templates (minimalist, teacher, reasoner strategies) and `PROMPT_VERSION` |
| `strategies.py` | `WAVE1_STRATEGIES` dict mapping strategy names to prompt configs |
| `sampler.py` | `select_test_files()` — stratified sample of 20 test files for Wave 1 |
| `parser.py` | JSON extraction from LLM responses (supports 2 levels of brace nesting) |
| `confidence.py` | Multi-dimensional confidence scoring: `compute_confidence_score()` |
| `quality_gates.py` | Quality gate evaluation (accuracy ≥0.90, cost ≤$0.30, confidence ≥0.70, validation ≥0.85) |
| `report.py` | Wave 1 report generation and display |
| `review.py` | Interactive review loop (Accept/Edit/Rerun/Skip/Quit) using $EDITOR |
| `checkpoint.py` | `CheckpointManager` — atomic write-to-tmp-then-rename for crash recovery |
| `topic_selector.py` | `TopicSelector` — reduces/expands topics to exactly 8 using semantic normalization |
| `chunker.py` | Adaptive chunking: head-tail for large files, windowed for very large |
| `__init__.py` | Package init |

---

## `entities/`

**Person entity extraction and normalization (Phase 6.1).**

| File | Responsibility |
|------|----------------|
| `extractor.py` | `EntityExtractor` — deterministic-first pipeline: exact match → alias match → RapidFuzz fuzzy (≥92 accept, 80–91 LLM fallback, <80 reject) |
| `registry.py` | `PersonRegistry` — loads canonical persons and aliases from SQLite `person`/`person_alias` tables |
| `models.py` | `EntityMention` (person_id, canonical_name, confidence, evidence), `EntityExtractionResult` |
| `__init__.py` | Package init |

**Canonical registry (15 persons):** Ayn Rand, Leonard Peikoff, Onkar Ghate, Robert Mayhew, Tara Smith, Ben Bayer, Mike Mazza, Aaron Smith, Tristan de Liege, Gregory Salmieri, Harry Binswanger, Jean Moroney, Yaron Brook, Don Watkins, Keith Lockitch.

**Blocked aliases:** Common first names (Smith, Aaron, Tara, Ben, Mike, Harry, Greg, Keith, Don) blocked to prevent false positives.

---

## `sync/`

**Incremental sync pipeline — change detection, upload-first replacement, orphan cleanup (Phase 5).**

| File | Responsibility |
|------|----------------|
| `disk.py` | `check_disk_availability(library_root, mount_point)` → `"available"` / `"unavailable"` / `"degraded"`. `disk_error_message()` → user-facing error string with resolution steps |
| `detector.py` | `SyncDetector` — mtime-optimized change detection: wraps `FileScanner.discover_files()`, loads DB state, compares mtime then SHA-256. `SyncChangeSet` dataclass with `new_files`, `modified_files`, `missing_files`, `unchanged_count`, `mtime_skipped_count`. `CURRENT_ENRICHMENT_VERSION` constant (8-char SHA-256 of enrichment config) |
| `orchestrator.py` | `SyncOrchestrator` — runs the full sync pipeline: verify library config → auto-cleanup orphans → detect changes → upload new (enriched by default) → replace modified (upload-first atomicity) → mark missing → prune/cleanup on request. Accepts optional Gemini client (None for dry-run) |
| `__init__.py` | Exports: `check_disk_availability`, `SyncDetector`, `SyncOrchestrator` |

**Key design decisions:**
- mtime epsilon of 1e-6 for float comparison (avoids filesystem timestamp rounding issues)
- Upload-first atomicity: new version uploaded and committed before old store entry is deleted; old ID stored as `orphaned_gemini_file_id` and cleaned up on next startup
- Mark-missing, never auto-delete: `sync` marks deleted files as `status='missing'` with `missing_since` timestamp; use `--prune-missing` to explicitly clean Gemini store
- Library config: stores store display name in `library_config` table on first run; aborts if name changes on subsequent runs

---

## `session/`

**Research session management (Phase 4).**

| File | Responsibility |
|------|----------------|
| `manager.py` | `SessionManager` — creates sessions, logs events (append-only), displays Rich timeline, exports Markdown |
| `__init__.py` | `from objlib.session.manager import SessionManager` |

Key methods:
- `create(name)` → session UUID
- `add_event(session_id, event_type, payload_dict)` — only valid types: search/view/synthesize/note/error
- `list_sessions()` → list of dicts with event counts
- `find_by_prefix(prefix)` → returns None if 0 or 2+ matches (ambiguity detection)
- `get_session(id)` → dict or None
- `display_timeline(session_id, console)` → Rich panel with chronological events
- `export_markdown(session_id, output_path)` → writes .md file, returns Path
- `get_active_session_id()` → static method, reads `OBJLIB_SESSION` env var

**Design:** Takes `sqlite3.Connection` directly (not `Database` wrapper). Events are append-only — no update/delete methods. UUID prefix lookup has ambiguity detection (returns None if multiple sessions match).

---

_Last updated: Phase 5 — sync/ module (disk detection, change detection, incremental upload)_
