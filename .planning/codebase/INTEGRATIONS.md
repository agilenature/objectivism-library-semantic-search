# External Integrations

**Analysis Date:** 2026-02-15

## APIs & External Services

**Google Gemini API:**
- Purpose: Semantic search, file storage, content generation
  - SDK/Client: `google-generativeai` package
  - Authentication: Environment variable `GEMINI_API_KEY` (required)
  - Services:
    - File API: Upload and storage of library files
    - Retrieval API: Semantic search within corpus
    - Generative API: LLM-based content synthesis and question answering
    - Corpus API: Creation and management of searchable document corpora

## Data Storage

**Remote - Gemini File API:**
- Provider: Google Cloud Gemini
- Purpose: Searchable corpus hosting
- Connection: `GEMINI_API_KEY` environment variable
- Client: `google-generativeai` package
- Implementation:
  - Files uploaded via `genai.upload_file()` in `src/02_upload_to_gemini.py:128`
  - Files organized into corpus via `corpus.create_document()` in `src/02_upload_to_gemini.py:157`
  - Metadata stored as custom metadata with flattened key-value pairs
  - Chunks linked to file URIs in `src/02_upload_to_gemini.py:165`

**Local - File System:**
- Catalog storage: `../data/library_catalog.json` - Complete metadata catalog from Phase 1
- State files: `../data/upload_state_<corpus_name>.json` - Upload progress tracking
- Configuration: `config/library_config.json` - System configuration
- Library root: `/Volumes/U32 Shadow/Objectivism Library` (configurable via `--library-root` flag)

## Authentication & Identity

**Auth Provider:**
- Method: API Key authentication with Google Gemini
- Implementation: Custom key-based authentication
  - Source: Environment variable `GEMINI_API_KEY`
  - Fallback: `--api-key` command-line argument
  - Validation: Checked in `src/02_upload_to_gemini.py:39-40` and `src/03_query_interface.py:30-32`
  - Configuration via: `genai.configure(api_key=self.api_key)` in both uploading and querying scripts

**API Key Requirement:**
- Must be set before running any script that interacts with Gemini
- Error handling: Raises `ValueError` if not found
- No session management - key-based per request

## Monitoring & Observability

**File Upload Status:**
- State tracking via `src/02_upload_to_gemini.py:77-88`
- Progress saved every batch (configurable batch size: 100 files)
- State includes: uploaded files list, failed uploads list, last processed index, timestamp
- Resume capability: `--resume` flag restarts from last checkpoint

**File Processing Status:**
- Polling loop in `src/02_upload_to_gemini.py:134-139`
- Checks file state: `"PROCESSING"` → `"ACTIVE"` or `"FAILED"`
- Timeout: 60 seconds per file
- Failed uploads logged with error details

**Query Verification:**
- Test query capability in `src/02_upload_to_gemini.py:280-300`
- Runs sample semantic search on newly created corpus
- Returns result count to verify functionality

**Error Handling:**
- Try-catch blocks with detailed error messages in all classes
- Logs to stdout for user visibility
- Failed uploads tracked separately for post-process retry
- File not found warnings in `src/02_upload_to_gemini.py:122-124`

## CI/CD & Deployment

**Hosting:**
- Google Cloud - Gemini API (remote)
- Local execution - Python scripts run on user's machine
- No containerization detected

**Setup Process:**
- Manual: Set `GEMINI_API_KEY` environment variable
- Sequential: Run scripts in order (01 → 02 → 03)
- No automated CI/CD pipeline detected

**Corpus Deployment:**
- Corpus created via Gemini API: `genai.create_corpus()` in `src/02_upload_to_gemini.py:64-67`
- Reuses existing corpus if found: `genai.list_corpora()` lookup
- Corpus naming: `objectivism-library-v1` (configurable)
- Display name: Auto-generated with timestamp for versioning

## Environment Configuration

**Required Environment Variables:**
- `GEMINI_API_KEY` - Google Gemini API key for authentication (required)

**Optional CLI Arguments (Override Defaults):**
- Phase 1 (`src/01_scan_library.py`):
  - `--library-root` - Path to library (default: `/Volumes/U32 Shadow/Objectivism Library`)
  - `--config` - Config JSON file path
  - `--output` - Output catalog path (default: `../data/library_catalog.json`)
  - `--verbose` - Detailed progress output

- Phase 2 (`src/02_upload_to_gemini.py`):
  - `--catalog` - Input catalog path (default: `../data/library_catalog.json`)
  - `--library-root` - Path to library files
  - `--corpus-name` - Corpus name (default: `objectivism-library-v1`)
  - `--batch-size` - Save state every N files (default: 100)
  - `--resume` - Resume from last checkpoint
  - `--api-key` - API key (alternative to env var)

- Phase 3 (`src/03_query_interface.py`):
  - `--corpus-name` - Corpus to query (default: `objectivism-library-v1`)
  - `--query` - Run single semantic search
  - `--question` - Ask question with synthesis
  - `--trace` - Trace concept evolution
  - `--interactive` - Interactive mode
  - `--synthesize` - Generate synthesis document

**Configuration File (library_config.json):**
- `library_root` - Scanner starting directory
- `excluded_patterns` - Folders/files to skip during scan
- `file_extensions` - File types to scan (`.txt`)
- `corpus_settings` - Gemini corpus metadata
- `upload_settings` - Batch size, retry logic, rate limits
- `query_settings` - Default result limits, model selection
- `metadata_enrichment` - Auto-inference toggles
- `known_instructors` - Recognized instructor names
- `difficulty_inference_rules` - Keywords for difficulty levels
- `branch_keywords` - Keywords for philosophy branches

## Webhooks & Callbacks

**Incoming:**
- Not applicable - No incoming webhooks detected

**Outgoing:**
- Not applicable - No outgoing webhooks detected

## Corpus Metadata Structure

**Gemini Custom Metadata Format:**
- Flattened key-value pairs stored with each document
- Keys use dot notation for nested fields (e.g., `intellectual.title`, `core.source_path`)
- Values converted to strings for storage
- Implementation in `src/02_upload_to_gemini.py:90-116`

**Metadata Categories Stored:**
- `core.*` - Source path, filename, file size, hash, modified date
- `classification.*` - Primary category, content type, format
- `intellectual.*` - Title, topics, subtopics, key concepts
- `instructional.*` - Instructor, difficulty level, prerequisites
- `pedagogical_structure.*` - Course name, course sequence (year/quarter/week/class)
- `temporal.*` - Recording date, year
- `relational.*` - Cross-references and relationships
- `content_characteristics.*` - Philosophy branch and content type
- `book_metadata.*` - Book title, author information (for books)
- `motm_metadata.*` - Session date, host, format (for MOTM)
- `podcast_metadata.*` - Podcast name, host, episode (for podcasts)
- `bibliographic.*` - Chapter numbers and references

## Rate Limiting & Quotas

**Gemini API Rate Limiting:**
- Delay between uploads: 0.5 seconds (configured in `config/library_config.json:26`)
- Implemented via `time.sleep(0.5)` in `src/02_upload_to_gemini.py:245`
- Per-batch state saves avoid excessive API calls

**File Processing Quotas:**
- Max file size: 50 MB (configured in `config/library_config.json:27`)
- Upload state checkpoint: Every 100 files (configurable batch size)
- Processing timeout: 60 seconds per file with polling every 2 seconds

**Query Limits:**
- Default results limit: 10 (configured in `config/library_config.json:31`)
- Max results limit: 50 (hard limit in `config/library_config.json:32`)
- Synthesis queries: No per-query limit (uses model directly)

## Error Recovery

**Upload Failure Handling:**
- Failed uploads tracked in state file with error details
- Retry mechanism: 3 attempts with 5 second delay between retries (configured)
- Failed uploads can be reprocessed by fixing underlying issue and re-running with `--resume`
- Partial uploads supported - only missing files reprocessed

**Corpus Query Fallback:**
- Metadata filter errors don't break search - returns results without filter
- Empty results handled gracefully with user message
- Test verification: Sample query validates corpus searchability

---

*Integration audit: 2026-02-15*
