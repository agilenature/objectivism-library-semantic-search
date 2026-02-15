# Testing Patterns

**Analysis Date:** 2026-02-15

## Test Framework

**Status:** No automated testing framework detected

**Not Found:**
- `pytest.ini`, `tox.ini` - No pytest configuration
- `unittest` - No unittest imports or test classes
- `.coverage`, `.coveragerc` - No coverage configuration
- `conftest.py`, `test_*.py`, `*_test.py` - No test files

**Approach:**
- Manual testing via example scripts
- Verification methods built into main modules

**Run Commands:**
```bash
# Manual testing via example scripts
python examples/example_queries.py              # Run example queries (demonstrates usage patterns)

# Direct script execution
python src/01_scan_library.py --verbose        # Scan with progress output
python src/02_upload_to_gemini.py --resume     # Upload with state tracking
python src/03_query_interface.py --interactive # Interactive query mode
```

## Test File Organization

**Structure:**
- No dedicated test directory
- Example usage file: `examples/example_queries.py` (123 lines)
- Integration verification methods embedded in main modules

**Examples Directory:**
- Location: `/Users/david/projects/objectivism-library-semantic-search/examples/`
- Contains: `example_queries.py` - demonstrates all major query modes

## Test Structure

**Manual Testing Pattern:**
The codebase uses example-based verification rather than automated tests. The `examples/example_queries.py` file demonstrates all features:

```python
# Initialize library
library = ObjectivismLibrary()

# Test 1: Basic search
results = library.search("How does knowledge deepen...", limit=3)

# Test 2: Filtered search
results = library.search(
    "values and virtues",
    filters={"content_characteristics.primary_branch": "Ethics"},
    limit=3
)

# Test 3: Navigation by structure
results = library.get_by_structure(year="Year1", quarter="Q1")

# Test 4: Question answering
answer = library.ask_question("What is the relationship between hierarchy and context?")

# Test 5: Concept tracing
evolution = library.trace_concept_evolution("free will")

# Test 6: Cross-source comparison
comparison = library.compare_explanations(
    concept="objectivity",
    source1_filter={"course_name": "ITOE"},
    source2_filter={"course_name": "Objectivism Through Induction"}
)
```

**Verification Methods:**
- Built into modules directly as public methods
- `verify_upload()` in `GeminiUploader` class
- Progress tracking and statistics in main scan methods

## Built-in Verification

**In `src/02_upload_to_gemini.py` - Upload Verification:**
```python
def verify_upload(self) -> bool:
    """Verify upload by running test query"""
    print("\nVerifying upload with test query...")
    try:
        results = self.corpus.query(
            query="What is Objectivism?",
            results_count=5
        )
        if results:
            print("✓ Corpus is searchable!")
            print(f"  Test query returned {len(results)} results")
            return True
        else:
            print("✗ No results returned from test query")
            return False
    except Exception as e:
        print(f"✗ Verification failed: {e}")
        return False
```

**State Tracking for Resume:**
- Upload state saved after every batch: `upload_state_{corpus_name}.json`
- Enables recovery from failures mid-process
- Records: uploaded files, failed uploads, last processed index

## Error Testing Patterns

**Graceful Degradation:**
- Missing files logged as warnings, not failures
- Failed uploads tracked separately and continued
- Progress preserved across interruptions

**Example from `src/01_scan_library.py`:**
```python
try:
    metadata = self.extract_metadata_from_path(file_path)
    self.catalog['files'].append(metadata)
except Exception as e:
    print(f"Error processing {file_path}: {e}")
    continue  # Continue with next file
```

**Import Failures Handled:**
```python
try:
    import google.generativeai as genai
except ImportError:
    print("Error: google-generativeai package not installed")
    print("Install with: pip install google-generativeai")
    exit(1)
```

## Manual Test Data

**No Test Fixtures:**
- Uses actual library files via `--library-root` argument
- Configuration via JSON files in `config/` directory
- Default paths point to production library location

**Configuration Testing:**
- JSON config loaded from `config/library_config.json`
- Contains patterns for known instructors, difficulty levels, branches
- Can be overridden via CLI arguments

## Testing Modes

**Verbose Mode:**
```bash
python src/01_scan_library.py --verbose
```
Outputs detailed progress for every file processed.

**Interactive Mode:**
```bash
python src/03_query_interface.py --interactive
```
REPL-style interface for testing queries:
```
Commands:
  search <query>              - Semantic search
  ask <question>              - Ask question with synthesis
  trace <concept>             - Trace concept evolution
  compare <concept>           - Compare across sources
  navigate <year> <quarter>   - Browse by structure
```

**Single Operation Mode:**
```bash
python src/03_query_interface.py --query "your question"
python src/03_query_interface.py --trace "concept"
python src/03_query_interface.py --synthesize "concept"
```

## Coverage

**Requirements:** None enforced

**Manual Verification Methods:**
- `print_statistics()` in `LibraryScanner` - verifies file processing
- `print_summary()` in `GeminiUploader` - shows success rates
- `print_results()` in interactive mode - shows result format correctness

**Example Statistics Output:**
```
============================================================
CATALOG STATISTICS
============================================================

Files by Category:
  Course               : 1000
  Book                 :  150
  Podcast              :   50
  MOTM                 :   80

Total Unique Courses: 25

Files by Difficulty:
  Foundations          :  400
  Intermediate         :  700
  Advanced             :  180
```

## Test Types

**Unit-like Testing:**
- Individual extraction methods testable via example queries
- Method `extract_metadata_from_path()` tests filename parsing
- Extraction methods (`extract_course_metadata()`, `extract_book_metadata()`) isolated

**Integration Testing:**
- Full pipeline: Scan → Upload → Query
- End-to-end verification via `examples/example_queries.py`
- State file proves successful upload completion

**Manual E2E Testing:**
```bash
# Phase 1: Scan library
python src/01_scan_library.py --output data/catalog.json

# Phase 2: Upload to Gemini
python src/02_upload_to_gemini.py --catalog data/catalog.json

# Phase 3: Query interface
python src/03_query_interface.py --interactive
```

## Async/Concurrent Testing

**Not Applicable:**
- All operations are synchronous
- File uploads handled sequentially with intentional rate limiting: `time.sleep(0.5)`
- Batch processing tracks state to support manual retry/resume

## Quality Practices

**What IS Tested (via examples):**
- Basic search functionality
- Filtered search with metadata
- Structural navigation (year/quarter)
- Concept evolution ordering (by difficulty level)
- Cross-source comparison
- Answer synthesis from multiple sources
- Prerequisites discovery
- Specific course content browsing

**What IS NOT Tested:**
- API error scenarios (timeout, rate limit, authentication)
- Malformed input handling (invalid queries, corrupt files)
- Edge cases in metadata extraction (missing fields, ambiguous formats)
- Large-scale operations (performance with 100k+ files)
- Concurrent uploads
- Recovery from mid-process API failures

---

*Testing analysis: 2026-02-15*
