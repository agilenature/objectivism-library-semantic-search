# Architecture

**Analysis Date:** 2026-02-15

## Pattern Overview

**Overall:** Three-Phase Pipeline with Semantic Search Integration

This is a **command-line batch processing pipeline** that transforms a file-based library into a semantic search system. The architecture uses Google's Gemini File API as the indexing and query backend.

**Key Characteristics:**
- **Phase-based execution**: Scan → Upload → Query (three sequential stages)
- **Metadata-first design**: Rich structural metadata extracted from file paths and names
- **API-first backend**: Google Gemini handles indexing, searching, and synthesis
- **Stateful uploads**: Resume-capable batch processing with progress tracking
- **Multiple query modes**: Semantic search, structured navigation, concept tracing, synthesis generation

## Layers

**Presentation/Interface Layer:**
- Location: `src/03_query_interface.py`
- Purpose: Provides user-facing query interfaces (interactive CLI, command-line arguments, Python API)
- Contains: `ObjectivismLibrary` class with methods for search, question answering, concept evolution tracking, synthesis
- Depends on: Gemini API client (via `google.generativeai`), corpus metadata
- Used by: End users via CLI or Python scripts

**Extraction & Metadata Layer:**
- Location: `src/01_scan_library.py`
- Purpose: Scans file system, parses structure, extracts rich metadata from paths and filenames
- Contains: `LibraryScanner` class with specialized extractors for courses, books, MOTM, podcasts
- Depends on: File system access, config file (`config/library_config.json`)
- Used by: Upload phase, consumes catalog JSON

**Upload & Indexing Layer:**
- Location: `src/02_upload_to_gemini.py`
- Purpose: Uploads files to Gemini, creates corpus, indexes with metadata, handles failures and resumption
- Contains: `GeminiUploader` class with batch processing, state management, verification
- Depends on: Catalog from scanner, Gemini API, resume state file
- Used by: Query layer (indirectly), requires completed upload before queries work

**Configuration Layer:**
- Location: `config/library_config.json`
- Purpose: Centralized configuration for library path, exclusion patterns, batch sizes, metadata enrichment rules
- Contains: File extensions, scan depth, upload settings, query settings, branch keywords, instructor mappings

**Data Storage Layer:**
- Inputs: Live file system at `/Volumes/U32 Shadow/Objectivism Library` (course transcripts, books, MOTM sessions)
- Intermediate: `data/library_catalog.json` (comprehensive metadata for all scanned files)
- State: `data/upload_state_objectivism-library-v1.json` (resume capability)
- Remote: Gemini corpus with indexed files and metadata

## Data Flow

**Phase 1 - Library Scanning:**

1. User runs: `python src/01_scan_library.py`
2. `LibraryScanner` recursively walks library root directory
3. For each `.txt` file:
   - Builds relative path from root
   - Extracts metadata from folder structure (course name, Year/Quarter/Week)
   - Detects category (Course, Book, MOTM, Podcast)
   - Infers difficulty level from path and naming patterns
   - Identifies instructor from known patterns
   - Computes SHA256 hash for deduplication
4. Builds comprehensive metadata object with 10+ sections (core, classification, intellectual, instructional, pedagogical_structure, temporal, relational, content_characteristics, quality_metadata, search_optimization, technical)
5. Outputs: `data/library_catalog.json` containing all files and metadata

**Phase 2 - Gemini Upload:**

1. User runs: `python src/02_upload_to_gemini.py --resume`
2. `GeminiUploader` loads catalog JSON
3. Checks for existing corpus; creates new if needed
4. For each file (in batches):
   - Uploads actual file content to Gemini File API
   - Waits for processing to complete
   - Flattens metadata to Gemini format (nested keys become dot-notation)
   - Creates document in corpus linked to uploaded file
   - Saves progress every N files (resumable)
5. Outputs: Corpus in Gemini backend + `data/upload_state_objectivism-library-v1.json` (resume state)

**Phase 3 - Semantic Query:**

1. User runs: `python src/03_query_interface.py --query "..."`
2. `ObjectivismLibrary` connects to Gemini corpus
3. For semantic search:
   - Sends query to Gemini corpus API
   - Receives ranked results with metadata and content snippets
   - Formats and returns to user
4. For question answering:
   - Searches for relevant content
   - Constructs context from top results
   - Uses Gemini model to synthesize answer
   - Returns answer with source citations
5. For concept evolution tracking:
   - Searches for concept across library
   - Sorts results by pedagogical level (Foundations → Intermediate → Advanced)
   - Then by Year/Quarter/Week sequence
   - Returns progression showing how concept is explained across curriculum

**State Management:**

- **Resume capability**: Upload stores `last_index`, `uploaded`, `failed` in state file
- **Corpus persistence**: Gemini corpus remains on servers; state file tracks local progress
- **Idempotency**: Files already uploaded can be re-run without re-uploading (via resume)

## Key Abstractions

**LibraryScanner:**
- Purpose: Transforms unstructured file system into structured metadata catalog
- Examples: `src/01_scan_library.py` - `LibraryScanner` class
- Pattern: Factory-like metadata extraction with category-specific handlers
- Key methods: `extract_metadata_from_path()`, `extract_course_metadata()`, `extract_motm_metadata()`, `infer_difficulty()`, `infer_philosophy_branch()`

**GeminiUploader:**
- Purpose: Bridges local metadata catalog to Gemini API with fault tolerance
- Examples: `src/02_upload_to_gemini.py` - `GeminiUploader` class
- Pattern: Batch processor with state persistence
- Key methods: `create_or_get_corpus()`, `upload_file()`, `create_document_in_corpus()`, `upload_batch()`, `load_state()`, `save_state()`

**ObjectivismLibrary:**
- Purpose: User-facing query interface with multiple search modes
- Examples: `src/03_query_interface.py` - `ObjectivismLibrary` class
- Pattern: Facade over Gemini API with specialized query methods
- Key methods: `search()`, `ask_question()`, `trace_concept_evolution()`, `compare_explanations()`, `generate_synthesis()`, `get_by_structure()`

**Metadata Schema:**
- Purpose: Comprehensive representation of file attributes across 10+ semantic dimensions
- Examples: Core, Classification, Intellectual, Instructional, Pedagogical_structure, Temporal, Relational, Content_characteristics, Quality_metadata, Search_optimization, Technical
- Pattern: Hierarchical nested dictionaries with standardized key names
- Enables: Semantic search, structured navigation, prerequisite tracking, concept evolution discovery

## Entry Points

**01_scan_library.py:**
- Location: `src/01_scan_library.py`
- Triggers: User runs manually to scan library after acquiring new content
- Responsibilities: Parse file system, extract metadata, create comprehensive catalog, print statistics
- Command: `python src/01_scan_library.py --verbose --library-root /path/to/library --output ../data/library_catalog.json`

**02_upload_to_gemini.py:**
- Location: `src/02_upload_to_gemini.py`
- Triggers: User runs after scanning to index content in Gemini
- Responsibilities: Upload files, create corpus, index with metadata, handle failures, save progress
- Command: `python src/02_upload_to_gemini.py --batch-size 100 --resume`

**03_query_interface.py:**
- Location: `src/03_query_interface.py`
- Triggers: User runs to search library (via CLI or Python import)
- Responsibilities: Provide multiple query interfaces, format results, synthesize answers
- Commands:
  - `python src/03_query_interface.py --query "your question"` - Simple search
  - `python src/03_query_interface.py --question "your question"` - Synthesized answer
  - `python src/03_query_interface.py --trace "concept"` - Evolution tracking
  - `python src/03_query_interface.py --synthesize "concept"` - Full synthesis doc
  - `python src/03_query_interface.py --interactive` - Interactive mode

**Python API Usage:**
- Import: `from src.query_interface import ObjectivismLibrary`
- Initialize: `library = ObjectivismLibrary()`
- Use: `results = library.search("query", filters={...})` or other methods

## Error Handling

**Strategy:** Graceful degradation with detailed logging

**Patterns:**

- **File Processing**: Individual file errors don't halt scanning. Errors logged, processing continues.
  ```python
  # In LibraryScanner.scan()
  try:
      metadata = self.extract_metadata_from_path(file_path)
      self.catalog['files'].append(metadata)
  except Exception as e:
      print(f"Error processing {file_path}: {e}")
      continue
  ```

- **Upload Recovery**: Failed uploads tracked separately; resumable from last checkpoint.
  ```python
  # In GeminiUploader.upload_batch()
  if (i + 1) % batch_size == 0:
      state = {'uploaded': [...], 'failed': [...], 'last_index': i + 1}
      self.save_state(state)
  ```

- **API Failures**: Search/query errors return empty results or error messages rather than crashing.
  ```python
  # In ObjectivismLibrary.search()
  except Exception as e:
      print(f"Search error: {e}")
      return []
  ```

- **Missing Files**: Upload phase checks file existence before processing.
  ```python
  if not file_path.exists():
      print(f"Warning: File not found: {file_path}")
      return None
  ```

## Cross-Cutting Concerns

**Logging:**
- Print-based progress reporting (number of files processed, upload progress, search results)
- Statistics printing at end of scanning and uploading phases
- Summary reports showing success/failure counts

**Validation:**
- File path validation (excludes patterns like `.claude`, `.git`, `.DS_Store`)
- Metadata extraction validates patterns (Year/Quarter/Week, episode numbers)
- File hash computation for deduplication
- API response validation (checks for "PROCESSING" state before proceeding)

**Authentication:**
- Gemini API key loaded from `GEMINI_API_KEY` environment variable
- Raised as `ValueError` if missing
- Passed to `genai.configure(api_key=...)`

---

*Architecture analysis: 2026-02-15*
