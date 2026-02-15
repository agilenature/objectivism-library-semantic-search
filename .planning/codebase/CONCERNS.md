# Codebase Concerns

**Analysis Date:** 2026-02-15

## Tech Debt

### 1. Hardcoded Library Path

**Issue:** Library path is hardcoded as `/Volumes/U32 Shadow/Objectivism Library` in multiple locations
- Files: `src/01_scan_library.py` (line 400), `src/02_upload_to_gemini.py` (line 309), `src/03_query_interface.py`
- Impact: Scripts fail immediately when run on machines without this specific volume mounted. No graceful fallback.
- Fix approach: Use config file path as single source of truth; read from `config/library_config.json` for all three scripts and provide clear error messages if path doesn't exist.

### 2. Missing Error Handling in Upload Flow

**Issue:** `GeminiUploader.upload_batch()` in `src/02_upload_to_gemini.py` (lines 174-257) silently accumulates failures without stopping processing
- Files: `src/02_upload_to_gemini.py` (lines 195-240)
- Impact: Long-running upload (1-6 hours) can silently fail halfway through with no early warning. User wastes 3+ hours uploading before discovering 50% failure rate in summary.
- Fix approach: Add fail-fast option (default to continue); add periodic success rate checks; raise exception if failure rate exceeds threshold; better logging of which files failed and why.

### 3. Incomplete Metadata Filter Implementation

**Issue:** `ObjectivismLibrary._build_metadata_filter()` in `src/03_query_interface.py` (lines 94-98) is a stub placeholder
- Files: `src/03_query_interface.py` (line 94-98)
- Impact: Metadata filters in search operations don't actually filter - they're passed but ignored by Gemini API. Feature documented in README but non-functional.
- Fix approach: Implement proper Gemini metadata filter format; test with actual Gemini API to verify filters work; add validation that filter keys exist.

### 4. Wildcard Search Workaround

**Issue:** `ObjectivismLibrary.get_by_structure()` uses `"*"` as query (line 109) which is not a valid semantic search query
- Files: `src/03_query_interface.py` (line 109)
- Impact: Searching by structure without keyword relies on metadata filters working (see issue #3). If filters don't work, returns all results or no results.
- Fix approach: Once metadata filters are fixed, validate that structure-based queries return expected results; add fallback mechanism.

## Known Bugs

### 1. File Hash Collision Potential

**Issue:** `LibraryScanner.compute_hash()` in `src/01_scan_library.py` (lines 97-107) only reads first 4096 bytes blocks but doesn't validate actual content
- Files: `src/01_scan_library.py` (line 99-103)
- Symptoms: If two files have identical first 4096 bytes, they get same hash even if rest of file differs
- Trigger: Happens if multiple lecture transcripts start with identical boilerplate header
- Workaround: Current code computes full SHA256 correctly (reads all blocks), but error handling returns empty string on failure which could mask issues

### 2. Incomplete Course Sequence Extraction

**Issue:** `LibraryScanner.extract_course_metadata()` in `src/01_scan_library.py` (lines 206-244) doesn't handle all course structure patterns
- Files: `src/01_scan_library.py` (lines 206-244)
- Symptoms: Year/Quarter/Week structure only recognized if folders exactly match "Year1", "Q1", "Week1" format - typos or variations (e.g., "YEAR1", "Q-1") are silently ignored
- Trigger: Any non-standard folder naming in course structure
- Workaround: Manually add course_sequence data to JSON catalog and re-upload

### 3. API Rate Limiting Not Enforced

**Issue:** Upload script only does fixed `time.sleep(0.5)` between uploads (line 245 in `src/02_upload_to_gemini.py`)
- Files: `src/02_upload_to_gemini.py` (line 245)
- Symptoms: Script may hit Gemini API rate limits during upload, causing 429 errors
- Trigger: Uploading 1000+ files in rapid succession
- Workaround: Reduce batch size or manually add delays between runs

### 4. Result Truncation in Query Interface

**Issue:** `ObjectivismLibrary.search()` truncates content to 500 chars (line 83 in `src/03_query_interface.py`)
- Files: `src/03_query_interface.py` (line 83)
- Symptoms: User sees truncated excerpts; may miss critical context
- Trigger: When search results are displayed
- Workaround: None - truncation is hardcoded

## Security Considerations

### 1. API Key Exposure Risk

**Risk:** Gemini API key stored in environment variable without protection
- Files: `src/02_upload_to_gemini.py` (lines 38-40), `src/03_query_interface.py` (lines 30-32)
- Current mitigation: Relies on user to set environment variable securely (no dotenv in code)
- Recommendations:
  - Add `.env` support using `python-dotenv` (currently `python-dotenv` is listed as dependency in QUICK_START but not used)
  - Add warning if API key is visible in shell history
  - Implement API key rotation mechanism

### 2. No Input Validation on Queries

**Risk:** User queries passed directly to Gemini prompt without sanitization
- Files: `src/03_query_interface.py` (lines 146, 236, 303)
- Current mitigation: None
- Recommendations:
  - Sanitize user input to prevent prompt injection
  - Validate query length before sending to API
  - Add query rate limiting per user/session

### 3. Metadata Injection Potential

**Risk:** Metadata extracted from filenames without validation, could inject malicious content into Gemini
- Files: `src/01_scan_library.py` (lines 138-158, 289-306)
- Current mitigation: None
- Recommendations:
  - Validate extracted metadata matches expected types/patterns
  - Limit metadata string lengths
  - Escape special characters in metadata

## Performance Bottlenecks

### 1. Full Library Scan on Every Run

**Problem:** `LibraryScanner.scan()` rescans entire library every time, even for incremental updates
- Files: `src/01_scan_library.py` (lines 308-347)
- Cause: No incremental scanning or change detection
- Improvement path:
  - Store file modification timestamps in catalog
  - Only re-scan files with newer mtime
  - Cache metadata from previous scans
  - Estimated improvement: 90% faster for 1000+ file libraries

### 2. Metadata Flattening Inefficiency

**Problem:** `GeminiUploader.prepare_metadata_for_gemini()` (lines 90-116 in `src/02_upload_to_gemini.py`) flattens nested metadata inefficiently
- Cause: Recursive dictionary traversal for every file, creates thousands of separate metadata entries
- Improvement path:
  - Use single JSON blob instead of flattening
  - Batch flatten operation instead of per-file
  - Estimated improvement: 10-20x faster metadata preparation

### 3. No Caching Between Queries

**Problem:** `ObjectivismLibrary.search()` makes fresh API call for every identical query
- Files: `src/03_query_interface.py` (lines 54-92)
- Cause: No local cache of search results
- Improvement path:
  - Add LRU cache (100-1000 most recent queries)
  - Add persistent cache option for frequently used queries
  - Estimated improvement: 100-1000x faster for repeated queries

## Fragile Areas

### 1. Course Structure Parsing

**Files:** `src/01_scan_library.py` (lines 206-244, 289-306)
**Why fragile:** Relies on exact folder naming conventions. Any deviation breaks structure detection.
- Pattern matching is brittle (exact string matching, not fuzzy)
- No validation that extracted structure makes sense
- Falls back to 'Unknown' or 'Other' silently instead of warning

**Safe modification:**
- Add logging when structure doesn't match expected patterns
- Validate year/quarter/week values are in reasonable ranges
- Add tests for various naming convention deviations
- Consider fuzzy matching for course names

**Test coverage:** No unit tests for metadata extraction logic

### 2. Gemini API Integration

**Files:** `src/02_upload_to_gemini.py` (lines 49-75, 150-172), `src/03_query_interface.py` (lines 39-52, 54-92)
**Why fragile:** Directly calls Gemini API without abstraction; tightly coupled to API response format
- Changes to Gemini File API response format would break code
- No retry logic for transient failures
- No circuit breaker for persistent failures

**Safe modification:**
- Extract Gemini API calls into separate module/class
- Add retry decorator with exponential backoff
- Add circuit breaker to fail gracefully
- Update unit tests with mocked Gemini responses

**Test coverage:** No tests for Gemini integration

### 3. Interactive Query Loop

**Files:** `src/03_query_interface.py` (lines 307-361)
**Why fragile:** Command parsing is string-based with minimal validation
- No input length limits
- No timeout on single queries
- Exception handling at loop level hides specific errors

**Safe modification:**
- Add input validation (max length, allowed characters)
- Add query timeout (e.g., 30 seconds max)
- Add more specific error messages for each command type
- Add command history/autocomplete for interactive mode

**Test coverage:** No tests for interactive mode

## Scaling Limits

### 1. File Upload Throughput

**Current capacity:** ~0.5 files/second with 0.5s delay, ~1440 files/day
**Limit:** Gemini API rate limits (not documented), likely 10-100 req/sec
**Scaling path:**
- Increase parallelism (currently sequential)
- Batch upload multiple files per request if API supports
- Implement proper rate limit detection and adaptation
- Target: 10-50x throughput improvement

### 2. Metadata Size Limits

**Current capacity:** Flattened metadata entries can be 100+ per file, Gemini corpus likely has per-entry size limits
**Limit:** Unknown - need to test with large metadata blobs
**Scaling path:**
- Profile actual metadata size per file
- Test Gemini limits for custom_metadata field
- Implement selective metadata inclusion (only most important fields)
- Compress metadata if possible

### 3. Query Response Size

**Current capacity:** Results truncated to 500 chars, can handle ~10 results
**Limit:** Prompt size limit for synthesis (typically 1M tokens)
**Scaling path:**
- Make result length configurable
- Implement pagination for large result sets
- Add result compression/summarization

### 4. Corpus Size

**Current capacity:** Tested with ~1250 files
**Limit:** Unknown - Gemini doesn't publish corpus size limits
**Scaling path:**
- Implement multi-corpus strategy for large libraries (>10k files)
- Add sharding by category/course
- Test with actual large corpus to find limits

## Dependencies at Risk

### 1. Google Generative AI SDK Version Pinning

**Risk:** Code targets `google-generativeai>=0.3.0` with loose version constraint
- Files: Dependencies listed in QUICK_START.md (line 17)
- Impact: Breaking API changes in new versions could fail without warning
- Migration plan:
  - Pin to specific tested version (e.g., `google-generativeai==0.4.1`)
  - Add version compatibility tests
  - Monitor changelog for breaking changes

### 2. Python Version Compatibility

**Risk:** Code written for Python 3.9+, but type hints and async code may not work on 3.9
- Files: All Python scripts use f-strings, pathlib (fine for 3.9+)
- Impact: Lower bound enforcement missing
- Migration plan:
  - Test on Python 3.9, 3.10, 3.11, 3.12
  - Add version check at script startup
  - Pin to specific versions in requirements.txt

## Missing Critical Features

### 1. Incremental Library Updates

**Problem:** No way to update library after initial scan without full re-scan
- Blocks: Can't easily add new lectures/books
- Current workaround: Re-run full scan (inefficient for large libraries)
- Path: Implement delta detection based on filesystem mtime

### 2. Metadata Backup & Restore

**Problem:** Catalog and upload state live in `data/` directory with no backup mechanism
- Blocks: If files corrupted, entire corpus needs re-creation (6+ hour process)
- Current workaround: Manual backup
- Path: Auto-backup catalog on each successful operation

### 3. Search Result Deduplication

**Problem:** Similar content from different sources may appear multiple times
- Blocks: User has to manually identify duplicates
- Current workaround: None
- Path: Add deduplication based on content similarity threshold

### 4. Multi-Language Support

**Problem:** Hard-coded English metadata field names, patterns, instructor names
- Blocks: Can't extend to libraries with non-English content
- Current workaround: Modify code for each language
- Path: Externalize strings to config/translation files

## Test Coverage Gaps

### 1. Metadata Extraction

**What's not tested:** Core `extract_metadata_from_path()` logic
- Files: `src/01_scan_library.py` (lines 48-95)
- Risk: Metadata errors silent until upload fails or queries return wrong results
- Priority: **High** - this is critical path
- Solution: Add unit tests for:
  - Course/Year/Quarter/Week extraction with various naming patterns
  - Difficulty level inference with edge cases
  - Title extraction from complex filenames
  - Philosophy branch inference

### 2. Gemini Integration

**What's not tested:** `GeminiUploader` and corpus operations
- Files: `src/02_upload_to_gemini.py` (lines 34-258)
- Risk: Upload failures only discovered after hours of processing
- Priority: **High** - expensive to test
- Solution: Add integration tests with mocked Gemini API:
  - Test corpus creation/retrieval
  - Test file upload with various metadata
  - Test metadata filter building
  - Test error handling for API failures

### 3. Query Interface

**What's not tested:** Search, filtering, synthesis generation
- Files: `src/03_query_interface.py` (lines 54-304)
- Risk: Query results may be wrong without user knowing
- Priority: **Medium** - users can validate manually
- Solution: Add tests with fixture data:
  - Search with/without filters
  - Concept evolution sorting
  - Comparative analysis
  - Synthesis prompt building

### 4. Interactive Mode

**What's not tested:** Command parsing, error handling in interactive loop
- Files: `src/03_query_interface.py` (lines 307-361)
- Risk: Crashes on unexpected input
- Priority: **Medium**
- Solution: Add tests:
  - Valid command parsing
  - Invalid command handling
  - Ctrl+C handling
  - Timeout on long-running commands

## Configuration Issues

### 1. Missing Validation

**Issue:** `library_config.json` loaded without schema validation
- Files: `src/01_scan_library.py` (lines 412-416)
- Risk: Invalid config values cause cryptic runtime errors
- Fix: Add JSON schema validation on load

### 2. Hardcoded Defaults

**Issue:** Magic numbers and strings scattered throughout code
- Files: Multiple - e.g., batch_size=100, results_count=5, rate_limit_delay=0.5
- Risk: Difficult to tune for different environments
- Fix: Centralize in config file

### 3. Model Version Hardcoded

**Issue:** Query interface hardcodes `"gemini-2.0-flash-exp"` model (line 37 in `src/03_query_interface.py`)
- Risk: Model deprecated/unavailable requires code change
- Fix: Make model name configurable in config file

## Documentation Gaps

### 1. API Limitations Not Documented

**What's missing:** Gemini File API limits
- Max corpus size, max files, max metadata size per file
- Rate limits and retry strategies
- Storage retention policy

**Impact:** Users can't estimate scale or plan for limits

### 2. Metadata Schema Not Fully Implemented

**What's missing:** Several metadata sections defined in `METADATA_SCHEMA.md` are not populated
- Files: `src/01_scan_library.py` (lines 79-82) - temporal, relational, pedagogical_structure partially empty
- Impact: Users expect rich metadata that isn't actually extracted

### 3. No Troubleshooting Guide for Upload Failures

**What's missing:** Step-by-step debug guide for when uploads fail
- How to identify which file failed and why
- How to resume from specific point
- How to rollback partial upload

---

*Concerns audit: 2026-02-15*
