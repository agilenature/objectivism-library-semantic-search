# Utility Scripts

Collection of utility scripts for the Objectivism Library Semantic Search project.

## Search Scripts

### `qsearch` - Quick Search
Simple command-line search wrapper.

**Usage:**
```bash
./scripts/qsearch "your query"
```

**Examples:**
```bash
./scripts/qsearch "context dropping"
./scripts/qsearch "what is the trader principle?"
./scripts/qsearch "when did Ayn Rand finish Galt's speech?"
```

**What it does:**
- Executes search against Gemini File Search store
- Returns synthesized answer with sources
- Shows citations from the library

### `smart-search.py` - Smart Search (Experimental)
Intelligent query expansion before searching.

**Status:** Experimental - query expansion needs Gemini API fix

**Usage:**
```bash
python scripts/smart-search.py "simple query"
```

**Workflow:**
1. Analyzes user's simple query
2. Expands with domain vocabulary (Objectivist philosophy)
3. Adds multiple question angles
4. Executes enriched search
5. Returns results

**Future:** Will use Gemini to intelligently expand queries for better semantic retrieval.

## Monitoring Scripts

### `check_status.sh`
Check overall system status.

### `monitor_enriched_upload.sh`
Monitor enriched upload pipeline progress.

### `monitor_extraction.sh`
Monitor metadata extraction progress.

### `monitor_upload.sh`
Monitor file upload to Gemini.

### `watch_progress.sh`
Real-time progress monitoring.

## Verification Scripts

### `verify-phase3.sh`
Verify Phase 3 completion.

### `verify_metadata.py`
Verify metadata integrity.

### `test_book_extraction.py`
Test metadata extraction on sample books.

---

## Installation

All scripts are located in `scripts/` directory. Make sure they're executable:

```bash
chmod +x scripts/*.sh scripts/qsearch
```

## Requirements

- Python 3.11+
- objlib package installed (`pip install -e .`)
- Gemini API key in keyring (`keyring set objlib-gemini api_key`)
- Library path: `/Volumes/U32 Shadow/Objectivism Library`
- Database: `data/library.db`

## Quick Reference

**Search the library:**
```bash
./scripts/qsearch "intrinsic value"
```

**Check status:**
```bash
python -m objlib status
```

**Browse library:**
```bash
python -m objlib browse
```

**View file details:**
```bash
python -m objlib view "filename.txt"
```
