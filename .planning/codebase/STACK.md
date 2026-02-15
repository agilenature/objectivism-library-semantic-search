# Technology Stack

**Analysis Date:** 2026-02-15

## Languages

**Primary:**
- Python 3 - Core implementation language for all three phases (scanning, uploading, querying)

## Runtime

**Environment:**
- Python 3.x interpreter
- Command-line execution model

**Package Manager:**
- pip - Python package manager
- No lockfile detected (`requirements.txt` not present in repository)

## Frameworks & Libraries

**Core Dependencies:**

- **google-generativeai** - Gemini API client for File API corpus operations
  - Used in: `src/02_upload_to_gemini.py`, `src/03_query_interface.py`
  - Purpose: File uploads, corpus management, semantic search, content generation

- **tqdm** (optional) - Progress bar visualization
  - Used in: `src/02_upload_to_gemini.py`
  - Purpose: User feedback during batch uploads
  - Graceful fallback: Application continues without it

**Standard Library Only:**
- `os` - Environment variable and file system operations
- `json` - Catalog and state file serialization
- `pathlib` - File path manipulation (cross-platform)
- `hashlib` - SHA256 file hashing for deduplication
- `typing` - Type hints (Dict, List, Any, Optional)
- `datetime` - Timestamps and temporal metadata
- `argparse` - CLI argument parsing for all three scripts
- `time` - Sleep/rate limiting between API calls
- `re` - Pattern matching for metadata extraction from filenames

## Configuration

**Environment:**
- `GEMINI_API_KEY` - Required environment variable for all phases that interact with Gemini API
  - Set via: `export GEMINI_API_KEY="..."`
  - Checked in: `src/02_upload_to_gemini.py:38`, `src/03_query_interface.py:30`
  - Fallback: Command-line argument `--api-key`

**Configuration Files:**
- `config/library_config.json` - Library structure, patterns, and metadata rules
  - Exclusion patterns: `.claude`, `.DS_Store`, `.git`, `__pycache__`, `.ipynb_checkpoints`
  - File extensions to scan: `.txt`
  - Corpus settings, upload settings, query settings
  - Known instructors, course patterns, difficulty inference rules, branch keywords

## Data Formats

**Input:**
- Flat text files (`.txt`) from library directory structure
- Metadata extracted from: folder hierarchy, filenames, path structure

**Output & Storage:**
- `../data/library_catalog.json` - Catalog from Phase 1 (metadata for all scanned files)
- `../data/upload_state_<corpus_name>.json` - Upload progress state for resume capability
- Gemini corpus - Remote storage via Google's File API

## Platform Requirements

**Development:**
- macOS, Linux, or Windows with Python 3.x
- File system access to library root directory
- Network access for Gemini API calls

**Production / Usage:**
- Python 3.x runtime
- Network connectivity to Google Gemini API
- GEMINI_API_KEY configured
- Read access to library files during scanning phase

## API Integration

**Google Gemini API:**
- SDK: `google-generativeai` package
- Services used:
  - `genai.configure()` - API authentication
  - `genai.upload_file()` - File upload to Gemini
  - `genai.get_file()` - File status polling
  - `genai.create_corpus()` / `genai.list_corpora()` - Corpus management
  - `genai.GenerativeModel()` - LLM model instantiation
  - `corpus.query()` - Semantic search
  - `model.generate_content()` - Content generation for synthesis

**Models:**
- `gemini-2.0-flash-exp` - Model used for query synthesis and content generation
  - Specified in: `config/library_config.json:33-34`, `src/03_query_interface.py:37`

## Entry Points

**Phase 1 - Library Scanning:**
- `src/01_scan_library.py` - Extracts metadata from library file structure
  - Default library root: `/Volumes/U32 Shadow/Objectivism Library`
  - Outputs: `../data/library_catalog.json`

**Phase 2 - Upload to Gemini:**
- `src/02_upload_to_gemini.py` - Uploads scanned files to Gemini corpus
  - Inputs: catalog JSON, library root
  - Corpus creation or retrieval
  - Batch processing with resume capability

**Phase 3 - Query Interface:**
- `src/03_query_interface.py` - Interactive and programmatic search interface
  - Semantic search with metadata filters
  - Question answering with synthesis
  - Concept evolution tracking
  - Comparative analysis between sources

## Rate Limiting & Performance

**Gemini API:**
- Rate limit delay: 0.5 seconds between uploads (configured in `config/library_config.json:26`)
- Batch processing: 100 files per state save (configurable)
- File processing timeout: 60 seconds per file
- Retry attempts: 3 with 5 second delay between retries

**File Upload:**
- Max file size: 50 MB (configured in `config/library_config.json:27`)
- Progress tracking via tqdm (if installed)
- State checkpointing every batch for resume capability

---

*Stack analysis: 2026-02-15*
