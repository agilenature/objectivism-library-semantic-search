# Stack Research

**Domain:** Semantic Search / RAG System (Google Gemini File Search API)
**Project:** Objectivism Library Semantic Search
**Researched:** 2026-02-15
**Confidence:** HIGH

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| Python | >=3.12 | Runtime | Required by google-genai SDK; modern typing features (generics, `type` statement) simplify data modeling. 3.13 stable, 3.14 in beta. Pin to `>=3.12,<3.15`. | HIGH |
| google-genai | >=1.63.0 | Gemini API SDK | **The** official SDK for Gemini File Search API. Legacy `google-generativeai` is deprecated (Nov 2025) and lacks File Search support entirely. `google-genai` is GA, actively maintained, covers both Developer API and Vertex AI. | HIGH |
| SQLite (stdlib `sqlite3`) | builtin | State tracking DB | Tracks upload status, file hashes, metadata. Zero external dependencies. For 1,749 files with simple CRUD (no joins, no complex relations), stdlib sqlite3 is faster, simpler, and sufficient. SQLAlchemy ORM adds ~30-200% overhead for zero benefit at this scale. | HIGH |
| uv | >=0.6.0 | Package/project manager | 10-100x faster than pip/poetry. Handles venvs, lockfiles, Python version management. Single tool replaces pip + venv + pyenv + poetry. `uv.lock` ensures reproducible builds. Industry standard for new Python projects in 2025+. | HIGH |

### Gemini File Search API (the core service)

| Aspect | Detail | Notes |
|--------|--------|-------|
| **Embedding model** | Managed (gemini-embedding-001 internally) | You do NOT call the embedding model directly. File Search handles chunking + embedding automatically. |
| **Query model** | `gemini-2.5-flash` or newer | The model used for `generateContent` with File Search tool. Flash is fast and cheap. Pro for higher quality synthesis. |
| **File size limit** | 100 MB per file (File Search stores) | Your library is 112 MB / 1,749 files = ~64 KB avg. Well within limits. |
| **Storage limits** | Free: 1 GB, Tier 1: 10 GB, Tier 2: 100 GB | Your 112 MB fits comfortably in Free tier. |
| **Persistence** | Indefinite (no TTL) | Files in File Search stores persist until manually deleted. Raw Files API objects expire in 48 hours -- but File Search store data does not. |
| **Chunking** | Automatic, configurable | Default ~400 tokens/chunk. Configurable via `chunking_config` (max_tokens_per_chunk, max_overlap_tokens). |
| **Metadata** | Custom key-value pairs per document | Supports string and numeric values. Filterable at query time via `metadata_filter`. Critical for author/year/category filtering. |
| **Pricing** | Embeddings: $0.15/M tokens (one-time at index). Storage: free. Query-time embedding: free. Retrieved tokens: standard input pricing. | Very cost-effective for your collection size. |
| **Upload method** | `upload_to_file_search_store()` | Single SDK call handles upload + import + chunking + embedding. Poll `operations.get()` for completion. |

### Supporting Libraries

| Library | Version | Purpose | When to Use | Confidence |
|---------|---------|---------|-------------|------------|
| typer | >=0.15.0 | CLI framework | All CLI commands (search, upload, status, sync). Type-hint-driven, auto-generates help. Built on Click but less boilerplate. | HIGH |
| rich | >=14.0.0 | Terminal formatting | Progress bars during upload, tables for search results, panels for synthesis output, status spinners. Integrates natively with Typer. | HIGH |
| pydantic | >=2.10.0 | Data validation | Config file parsing, API response validation, metadata schemas. Use `BaseModel` for all structured data. Catches malformed data before it hits SQLite or the API. | HIGH |
| PyMuPDF (pymupdf) | >=1.25.0 | PDF metadata extraction | Extract title/author/date/keywords from PDF files. 3-5x faster than alternatives. Also handles scanned PDFs with OCR (via Tesseract). Import as `pymupdf` (new) or `fitz` (legacy compat). | HIGH |
| python-docx | >=1.1.0 | DOCX metadata extraction | Extract `core_properties` (title, author, subject, dates) from Word documents. Lightweight, stdlib-like API. | MEDIUM |
| EbookLib | >=0.18 | EPUB metadata extraction | Extract Dublin Core metadata (title, creator, subject, date) from EPUB files via OPF parsing. Only library that handles EPUB properly. | MEDIUM |
| structlog | >=25.4.0 | Structured logging | JSON-structured logs in production, pretty console logs in dev. Critical for debugging upload pipelines (which file failed, why, at what step). | MEDIUM |
| tenacity | >=9.0.0 | Retry logic | Retry failed API calls with exponential backoff + jitter. Cleaner than hand-rolled retry loops. Decorates async functions cleanly. | HIGH |

### Development Tools

| Tool | Version | Purpose | Notes |
|------|---------|-------|-------|
| ruff | >=0.9.0 | Linting + formatting | Replaces flake8, isort, black in a single Rust-based tool. 10-100x faster. Configure in `pyproject.toml`. |
| pytest | >=9.0.0 | Testing | Function-based tests, parametrize for metadata edge cases, fixtures for mock API responses. |
| pytest-asyncio | >=0.24.0 | Async test support | Required if using async upload/search functions. |
| mypy | >=1.13.0 | Type checking | Enforce type hints on all public interfaces. Catches mismatched types between SQLite rows and Pydantic models. |

---

## Installation

```bash
# Initialize project
uv init objectivism-library-semantic-search
cd objectivism-library-semantic-search

# Core dependencies
uv add google-genai typer rich pydantic structlog tenacity

# Document processing (only needed for metadata extraction)
uv add pymupdf python-docx EbookLib

# Dev dependencies
uv add --group dev pytest pytest-asyncio ruff mypy

# Set API key
export GOOGLE_API_KEY="your-key-here"
```

### pyproject.toml skeleton

```toml
[project]
name = "objectivism-library-semantic-search"
version = "0.1.0"
description = "Semantic search system for the Objectivism Library using Google Gemini File Search API"
requires-python = ">=3.12"

dependencies = [
    "google-genai>=1.63.0",
    "typer>=0.15.0",
    "rich>=14.0.0",
    "pydantic>=2.10.0",
    "structlog>=25.4.0",
    "tenacity>=9.0.0",
    "pymupdf>=1.25.0",
    "python-docx>=1.1.0",
    "EbookLib>=0.18",
]

[dependency-groups]
dev = [
    "pytest>=9.0.0",
    "pytest-asyncio>=0.24.0",
    "ruff>=0.9.0",
    "mypy>=1.13.0",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "RUF", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
warn_return_any = true
disallow_untyped_defs = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not the Alternative |
|----------|-------------|-------------|------------------------|
| **Gemini SDK** | google-genai | google-generativeai | Deprecated Nov 2025. No File Search API support. No new features. Will stop working. |
| **DB** | stdlib sqlite3 | SQLAlchemy | ORM overhead unjustified for simple state tracking (file status, hashes). 5 tables max, basic CRUD. SQLAlchemy shines with complex relations and migrations -- neither needed here. |
| **DB** | stdlib sqlite3 | PostgreSQL + pgvector | You are NOT managing your own embeddings. Gemini File Search handles vector storage. Postgres adds deployment complexity for zero benefit. |
| **CLI** | Typer | Click | Typer is built on Click but eliminates boilerplate via type hints. Same underlying engine, less code. |
| **CLI** | Typer | argparse | Verbose, no auto-completion, no rich help formatting. Only use if zero-dependency is a hard requirement. |
| **Package mgr** | uv | poetry | Poetry is slower (10-100x), more complex config, slower resolver. uv is the clear 2025+ standard. |
| **Package mgr** | uv | pip + venv | No lockfile, no reproducibility, manual venv management. uv replaces both tools. |
| **Linting** | ruff | flake8 + black + isort | Three tools vs one. Ruff is faster, unified config, same rules. No reason to use the trio anymore. |
| **PDF** | PyMuPDF | PyPDF2/PyPDF | Slower text extraction (3-5x), no table detection, no built-in OCR. PyMuPDF is strictly better for metadata + text extraction. |
| **PDF** | PyMuPDF | pdfplumber | Good for tables but slower overall. PyMuPDF added table detection in recent versions. One dependency instead of two. |
| **Retry** | tenacity | hand-rolled retry | tenacity handles exponential backoff, jitter, async, stop conditions, logging -- all declaratively. Avoids reimplementing poorly. |
| **Logging** | structlog | stdlib logging | structlog outputs structured JSON (machine-parseable) in prod and pretty dev output. stdlib logging requires extensive config for the same result. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **google-generativeai** (legacy SDK) | Deprecated Nov 2025. No File Search, no Live API, no new features. Will eventually break. | `google-genai` |
| **LangChain** | Massive dependency tree, abstractions that hide Gemini-specific features, unnecessary complexity for a single-provider system. You only use Gemini -- LangChain's multi-provider abstraction adds overhead with zero benefit. | Direct `google-genai` SDK calls |
| **LlamaIndex** | Same reasoning as LangChain. These frameworks help when orchestrating multiple LLMs/vector DBs. With Gemini File Search handling RAG end-to-end, the framework adds indirection without value. | Direct `google-genai` SDK calls |
| **ChromaDB / Pinecone / Weaviate** | You do NOT need a separate vector database. Gemini File Search API manages embeddings, chunking, and vector search internally. Adding a vector DB creates duplicate infrastructure, sync headaches, and costs. | Gemini File Search stores |
| **Sentence-transformers / custom embeddings** | Same reasoning. Gemini generates and manages embeddings internally. Custom embeddings cannot be used with File Search. | Gemini's managed embeddings |
| **SQLAlchemy** | Overkill for this project's DB needs. 5 tables, basic CRUD, no migrations needed (schema is stable and simple). Adds 30-200% query overhead and a learning curve for no gain. | stdlib `sqlite3` with Pydantic for validation |
| **Alembic** | Database migration tool for SQLAlchemy. Without SQLAlchemy, Alembic is irrelevant. For schema changes in sqlite3, use simple `ALTER TABLE` or recreate. | Manual schema versioning (a `schema_version` table) |
| **FastAPI / Flask** | This is a CLI tool, not a web service. No HTTP endpoints needed. If a web UI is needed later, add it as a separate phase. | Typer CLI |
| **Docker** | Single-machine Python CLI tool. Docker adds complexity without benefit. The user runs it on their machine against their local library files. | `uv run` with lockfile |

---

## Stack Patterns by Variant

**If you need async uploads (recommended for batch operations):**
- Use `asyncio` + `asyncio.Semaphore` for rate-limited concurrent uploads
- tenacity supports async retry out of the box
- sqlite3 is thread-safe in Python 3.12+ with proper connection handling (one connection per thread, or use `check_same_thread=False` carefully)

**If you stay synchronous (simpler, fine for <100 files at a time):**
- Sequential upload loop with `time.sleep()` for rate limiting
- tenacity with sync retry decorators
- Single sqlite3 connection, straightforward error handling
- Recommended for initial implementation; refactor to async only if rate limits make sequential too slow

**If the library grows to 10,000+ files:**
- Use Gemini Batch API (50% cost reduction, async processing, 24-hour turnaround)
- Consider multiple File Search stores organized by category/author for retrieval quality
- Add `watchdog` library for filesystem monitoring (auto-detect changes)

**If you later need a web interface:**
- Add FastAPI as a separate entry point reusing the same core library
- Keep CLI and web as thin wrappers over shared business logic
- Do NOT refactor the CLI into a web app -- add alongside

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| google-genai >=1.63.0 | Python >=3.9 | Tested with 3.12 and 3.13. Pin `>=1.63.0` for File Search store support. |
| PyMuPDF >=1.25.0 | Python 3.10-3.14 | Requires C extension compilation. Pre-built wheels available for major platforms. |
| typer >=0.15.0 | Python >=3.8 | Requires `click>=8.0`. Installed automatically as dependency. |
| rich >=14.0.0 | Python >=3.8 | No C extensions. Pure Python. |
| pydantic >=2.10.0 | Python >=3.9 | Uses pydantic-core (Rust-based). Pre-built wheels required. |
| ruff >=0.9.0 | Python >=3.7 (for analysis) | Ruff itself is a standalone Rust binary. Analyzes any Python version. |
| structlog >=25.4.0 | Python >=3.8 | Pure Python. No compatibility issues. |
| pytest >=9.0.0 | Python >=3.9 | pytest-asyncio >=0.24.0 required for async tests. |
| sqlite3 (stdlib) | Python >=3.12 | SQLite 3.45+ bundled with Python 3.12+. Supports JSON functions, WAL mode. |

**Overall compatibility target:** Python 3.12+ on macOS/Linux. All packages have pre-built wheels for these platforms.

---

## Gemini-Specific Implementation Notes

### File Search Store Organization
- **Single store** for the initial 112 MB library is fine (well under 20 GB recommendation)
- If query relevance degrades, split into stores by category (e.g., "primary-sources", "secondary-analysis", "periodicals")
- Stores are cheap (free storage) -- the cost is only at indexing time

### Upload Workflow
```
Local file scan --> Hash comparison (sqlite3) --> Upload changed files --> Poll for completion --> Update DB
```
1. Scan library directory recursively
2. Compute SHA-256 hash for each file
3. Compare against stored hashes in SQLite
4. Upload new/modified files to File Search store with metadata
5. Poll `operations.get()` until indexing completes
6. Record new hash, file_search_doc_id, and status in SQLite
7. Handle deleted files: remove from store + DB

### Metadata Strategy
Attach to every uploaded document:
- `author` (string) -- extracted from file metadata or directory structure
- `title` (string) -- from file metadata or filename
- `year` (numeric) -- publication year if available
- `category` (string) -- derived from directory hierarchy
- `format` (string) -- file extension / MIME type
- `source_path` (string) -- relative path in library for traceability

### Rate Limit Strategy
- **Tier awareness**: Check your tier's RPM/TPM/RPD limits before batch uploads
- **Semaphore pattern**: `asyncio.Semaphore(5)` for concurrent uploads (start conservative)
- **Exponential backoff**: Use tenacity with `wait_exponential(min=1, max=60)` + `retry_if_exception_type(RateLimitError)`
- **Progress tracking**: Rich progress bar shows upload status; SQLite tracks which files succeeded (resume on failure)
- **Batch API**: For full re-index of all 1,749 files, use Batch API at 50% cost with 24-hour turnaround

### Query Patterns
```python
# Basic semantic search
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="What does Rand say about the virtue of selfishness?",
    config=types.GenerateContentConfig(
        tools=[types.Tool(
            file_search=types.FileSearch(
                file_search_store_names=[store.name]
            )
        )]
    )
)

# Filtered search (by author)
# Uses metadata_filter parameter to restrict results
config=types.GenerateContentConfig(
    tools=[types.Tool(
        file_search=types.FileSearch(
            file_search_store_names=[store.name],
            metadata_filter='author="Ayn Rand"'
        )
    )]
)
```

---

## Sources

- Google Gemini File Search API docs (HIGH confidence): https://ai.google.dev/gemini-api/docs/file-search
- Google Gemini Files API docs (HIGH confidence): https://ai.google.dev/gemini-api/docs/files
- Google Gemini Rate Limits docs (HIGH confidence): https://ai.google.dev/gemini-api/docs/rate-limits
- Google Gemini Batch API docs (HIGH confidence): https://ai.google.dev/gemini-api/docs/batch-api
- Google Gemini Pricing (HIGH confidence): https://ai.google.dev/gemini-api/docs/pricing
- Google GenAI SDK libraries page (HIGH confidence): https://ai.google.dev/gemini-api/docs/libraries
- google-genai PyPI (HIGH confidence, v1.63.0): https://pypi.org/project/google-genai/
- SQLAlchemy vs sqlite3 discussion (MEDIUM confidence): https://github.com/sqlalchemy/sqlalchemy/discussions/10350
- uv documentation (HIGH confidence): https://docs.astral.sh/uv/
- Ruff documentation (HIGH confidence): https://docs.astral.sh/ruff/
- PyMuPDF documentation (HIGH confidence): https://pymupdf.readthedocs.io
- Typer documentation (HIGH confidence): https://typer.tiangolo.com
- Rich documentation (HIGH confidence): https://rich.readthedocs.io
- Pydantic documentation (HIGH confidence): https://docs.pydantic.dev
- structlog documentation (MEDIUM confidence): https://www.structlog.org
- Perplexity Deep Research on Gemini RAG stack (MEDIUM confidence, synthesized from multiple sources)

---
*Stack research for: Semantic Search / RAG with Google Gemini File Search API*
*Researched: 2026-02-15*
