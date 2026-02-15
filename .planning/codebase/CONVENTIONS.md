# Coding Conventions

**Analysis Date:** 2026-02-15

## Naming Patterns

**Files:**
- Numbered sequence format: `01_scan_library.py`, `02_upload_to_gemini.py`, `03_query_interface.py`
- Descriptive names with underscores separating words
- Example files in separate directory: `examples/example_queries.py`

**Functions:**
- snake_case for all function names
- Descriptive action verbs: `extract_metadata_from_path()`, `compute_hash()`, `determine_category()`
- Internal helper functions marked with single underscore: `_build_metadata_filter()`, `_flatten_dict()`
- Private methods use leading underscore convention

**Variables:**
- snake_case for all variables and attributes
- Descriptive names indicating purpose and type
- Examples: `self.library_root`, `file_metadata`, `metadata_filter`, `category_counts`
- Constants appear in uppercase (implicit): `scan_depth`, `batch_size`

**Types:**
- Type hints used throughout: `Dict[str, Any]`, `List[Dict[str, str]]`, `Optional[str]`
- Import from `typing` module for all type annotations
- Return types specified on function definitions

**Classes:**
- PascalCase for class names
- Descriptive nouns: `LibraryScanner`, `GeminiUploader`, `ObjectivismLibrary`
- One class per file or module

## Code Style

**Formatting:**
- 4-space indentation (Python standard)
- Lines appear to follow PEP 8 style guidelines
- No apparent automatic formatter configured (no `.flake8`, `.pylintrc`, or `.black` files)

**Linting:**
- No linting config files detected (no `.flake8`, `.pylintrc`, `pyproject.toml`, or `setup.cfg`)
- No ESLint or similar static analysis configuration
- Manual code review approach appears to be in place

## Import Organization

**Order:**
1. Standard library imports (`os`, `json`, `re`, `argparse`, `pathlib`, etc.)
2. Third-party packages (`google.generativeai`, `tqdm`)
3. Local module imports (relative paths with `sys.path.append()`)

**Path Aliases:**
- Relative imports use explicit `sys.path.append('../src')` for cross-module access
- Example in `examples/example_queries.py`: `sys.path.append('../src')`
- No path alias configuration (no `PYTHONPATH`, no `sys.path` setup file)

**Import Patterns:**
- Full module imports: `import json`, `import os`
- Conditional imports with error handling:
```python
try:
    import google.generativeai as genai
except ImportError:
    print("Error: google-generativeai package not installed")
    print("Install with: pip install google-generativeai")
    exit(1)
```

## Error Handling

**Patterns:**
- Try-except blocks with specific error messages to users
- Generic `Exception` catches when specific exception type unknown
- Graceful degradation: optional dependencies handled with try-except
- Progress reporting on failures without stopping execution

**Examples from codebase:**
```python
# Compute hash - graceful degradation
try:
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()
except Exception as e:
    print(f"Warning: Could not hash {file_path}: {e}")
    return ""

# Scan loop - continue on error
try:
    metadata = self.extract_metadata_from_path(file_path)
    self.catalog['files'].append(metadata)
    file_count += 1
except Exception as e:
    print(f"Error processing {file_path}: {e}")
    continue
```

- Validation errors raised with context: `raise ValueError("GEMINI_API_KEY not found...")`
- API errors logged with suggestions for user resolution

## Logging

**Framework:** `print()` function exclusively

**Patterns:**
- Progress tracking: `print(f"[{file_count}] {metadata['intellectual']['title']}")`
- Statistics output: formatted sections with `"="*60` dividers
- Informational messages with context: `print(f"Warning: File not found: {file_path}")`
- Error messages include guidance: `print("Install with: pip install google-generativeai")`
- Verbose mode flag controls output level

**Example output structure:**
```python
print("\n" + "="*60)
print("CATALOG STATISTICS")
print("="*60)
```

## Comments

**When to Comment:**
- Regex patterns explained before use: `# Pattern: "Course Name - Year X - QX - Week X - Title"`
- Complex algorithms explained: `# Flatten nested dict for Gemini metadata`
- Configuration logic clarified: `# Rate limiting - be nice to the API`
- Section markers for multi-step processes

**Docstrings:**
- Single-line docstrings for all classes and functions
- Triple-quoted format: `"""Brief description"""`
- Module-level docstrings at file top with usage examples
- No multi-line docstring format (Args/Returns sections not used)

**Example docstring pattern:**
```python
def extract_metadata_from_path(self, file_path: Path) -> Dict[str, Any]:
    """Extract metadata from file path and name"""
```

## Function Design

**Size:**
- Methods typically 10-40 lines
- Specialized extraction methods 8-15 lines each
- Utility methods extract_* prefix for focused operations

**Parameters:**
- Type hints required for all parameters
- Optional parameters with default values: `config: Dict[str, Any] = None`
- Limit usage of parameters - max 4 common, 5-6 for specialized extraction

**Return Values:**
- Always typed: `-> Dict[str, Any]`, `-> List[Dict[str, str]]`, `-> bool`
- Consistent return structure across similar functions
- None returned explicitly for optional results: `-> Optional[Any]`

## Module Design

**Exports:**
- Single main class per module: `LibraryScanner`, `GeminiUploader`, `ObjectivismLibrary`
- Helper functions defined before main class usage
- `if __name__ == '__main__':` pattern used in all scripts

**Barrel Files:**
- Not used; direct imports from modules instead
- Flat module structure within directories

## Configuration

**Config Loading:**
- JSON configuration files in `config/` directory
- Config loaded via argparse CLI arguments with defaults
- Example: `--config ../config/library_config.json`
- Missing config files gracefully handled with empty dict: `config = {}`

**Environment Variables:**
- Used for sensitive data: `GEMINI_API_KEY`
- Accessed via `os.getenv('GEMINI_API_KEY')`
- Required env vars raise `ValueError` if missing

---

*Convention analysis: 2026-02-15*
