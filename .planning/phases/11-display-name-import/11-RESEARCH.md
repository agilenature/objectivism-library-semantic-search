# Phase 11: display_name Stability and Import Reliability - Research

**Researched:** 2026-02-20
**Domain:** Google Gemini File Search API -- display_name preservation, import-to-visible latency, document state lifecycle
**Confidence:** HIGH (SDK source inspected locally, API types verified)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**LOCKED: Two-fold display_name verification**
SDK inspection + round-trip verification required (not SDK alone). Find the display_name= parameter in the installed google-genai SDK source (site-packages), document exact file+line, AND run round-trip test (import 10+ files, compare submitted vs returned display_name, case-sensitive string equality). If normalization is detected, document the rule -- the gate still passes if normalization is deterministic.

**LOCKED: Definition of "Visible" for Lag Measurement**
"Visible" = document appears in list_store_documents() at all (any state). Start timer when import_() returns; stop timer when document appears in list_store_documents(). Use exponential backoff polling (0.5s start, 1.5 factor, max 10s per interval) to avoid 429s.

**LOCKED: PROCESSING-to-INDEXED Trigger Strategy**
Non-blocking polling, no new FSM states. Import returns immediately, FSM enters PROCESSING, background task polls until visible, then transitions to INDEXED. PROCESSING already covers the "waiting" period. Polling parameters: 0.5s start, 1.5x factor, max 10s interval, 5-minute absolute timeout.

**LOCKED: PROCESSING-to-FAILED on timeout or API error**
Reuse existing FAILED state + RecoveryCrawler from Phase 10. Two trigger conditions: (1) API error state exposed by list_store_documents(), (2) 5-minute absolute timeout exceeded. No new FSM states.

**Phase 11 Gate (BLOCKING for Phase 12)**
Gate passes when: (1) SDK file+line documented, (2) P50/P95/P99 measured and documented, (3) trigger strategy committed with data justification. No latency target -- characterization is the gate.

### Claude's Discretion
(No discretion areas specified -- all decisions are locked.)

### Deferred Ideas (OUT OF SCOPE)
(No deferred items specified.)
</user_constraints>

## Summary

Phase 11 is a HOSTILE-distrust measurement spike with three deliverables: (1) SDK source evidence that `display_name` is caller-controlled, (2) empirical latency data for import-to-visible lag, and (3) a documented trigger strategy decision backed by data. The research confirms all three are achievable with the installed google-genai 1.63.0 SDK and the existing project infrastructure.

The SDK source inspection is straightforward. The `display_name` flows through two distinct code paths depending on the upload method. This project uses the two-step pattern (Files API upload then store import), where `display_name` is set on the `types.File` object at `files.py:527/1066` and serialized via Pydantic's `alias_generator=to_camel` to `displayName` in the HTTP request body. The store document's `display_name` is then inherited from the imported File. The `Document` type returned by `list_store_documents()` has a `display_name` field (types.py:13128) enabling direct comparison.

A critical discovery: the `ImportFileOperation.response` has a `document_name` field (types.py:13862), meaning when the import operation completes, the document resource name is available directly from the operation response. This is relevant for the "visible" definition -- the operation completing (done=True) may coincide with or precede document visibility in `list_store_documents()`. The spike must measure both.

**Primary recommendation:** Structure the spike as `spike/phase11_spike/` following Phase 9/10 conventions. Use a dedicated test store (NOT the production `objectivism-library` store) to avoid pollution. Create 12-15 small test files with deliberately tricky display_names (mixed case, spaces, special chars, long names) to stress-test normalization. Measure both "operation done" and "list visible" timings.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| google-genai | 1.63.0 | Gemini File Search API client | Already installed, project dependency |
| aiosqlite | (installed) | Async SQLite for spike DB | Same as Phase 9/10 spikes |
| python-statemachine | 2.6.0 | FSM definitions | Phase 9 decision (not needed in Phase 11 spike directly) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| time (stdlib) | 3.13 | `time.perf_counter()` for timing | Lag measurement |
| statistics (stdlib) | 3.13 | `quantiles()` for P50/P95/P99 | Reporting |
| asyncio (stdlib) | 3.13 | `asyncio.sleep()` for backoff | Polling loop |
| tempfile (stdlib) | 3.13 | Test file creation | Test corpus |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib statistics | numpy | Overkill for 10-15 data points |
| Manual backoff loop | tenacity | Already used in client.py, but spike should be transparent |
| Dedicated test store | Production store | NEVER use production store for spike |

**Installation:**
No additional packages needed. All dependencies already installed.

## Architecture Patterns

### Recommended Spike Structure
```
spike/phase11_spike/
    __init__.py
    sdk_inspector.py       # SC1: SDK source file+line documentation
    lag_measurement.py     # SC2: Import-to-visible latency measurement
    harness.py             # Combined evidence harness (Phase 9/10 pattern)
    test_corpus.py         # Test file generation (12-15 files with tricky names)
    tests/
        __init__.py
        conftest.py
        test_sdk_evidence.py
        test_lag_data.py
```

### Pattern 1: SDK Source Inspection (SC1)
**What:** Programmatic inspection of installed SDK source code to document exactly where `display_name` is serialized into the HTTP request body.
**When to use:** HOSTILE distrust requires file+line evidence, not API documentation.
**Key files to document:**

1. **Files API upload path (two-step method used by this project):**
   - `files.py:527` (sync) / `files.py:1066` (async): `display_name=config_model.display_name` sets the field on a `types.File` Pydantic model
   - `types.py:4763`: `File.display_name` field definition (`Optional[str]`)
   - `_common.py:552`: `alias_generator=alias_generators.to_camel` -- Pydantic serializes `display_name` to `displayName` in JSON
   - `files.py:46-49`: `_CreateFileParameters_to_mldev` puts the whole `file` object into the request dict

2. **Store document upload path (one-step alternative, not used by this project):**
   - `file_search_stores.py:253-263`: `_UploadToFileSearchStoreConfig_to_mldev` maps `display_name` -> `displayName` on the parent object

3. **Document response (what we read back):**
   - `types.py:13128`: `Document.display_name` field definition
   - `documents.py:107-127`: `_ListDocumentsResponse_from_mldev` -- raw API response deserialized through Pydantic

**Critical observation:** The SDK does NOT modify `display_name` between the user's input and the HTTP request. It performs a direct assignment (`display_name=config_model.display_name`) and relies on Pydantic's `to_camel` alias generator for JSON key naming. No truncation, normalization, or transformation occurs in the SDK layer. However, the API server could still normalize.

### Pattern 2: Exponential Backoff Polling (SC2)
**What:** Poll `list_store_documents()` with exponential backoff to detect when an imported document becomes visible.
**When to use:** Measuring import-to-visible lag per locked decision.

```python
import asyncio
import time

async def measure_visibility_lag(
    client,       # GeminiFileSearchClient
    store_name: str,
    target_doc_name: str,  # from ImportFileOperation.response.document_name
    max_wait: float = 300.0,
    initial_interval: float = 0.5,
    backoff_factor: float = 1.5,
    max_interval: float = 10.0,
) -> float | None:
    """Measure time from import completion to list_store_documents() visibility.

    Returns seconds elapsed, or None if timeout exceeded.
    """
    start = time.perf_counter()
    interval = initial_interval

    while (elapsed := time.perf_counter() - start) < max_wait:
        docs = await client.list_store_documents(store_name)
        for doc in docs:
            if getattr(doc, "name", None) == target_doc_name:
                return time.perf_counter() - start
        await asyncio.sleep(interval)
        interval = min(interval * backoff_factor, max_interval)

    return None  # Timeout
```

### Pattern 3: Round-Trip display_name Verification (SC1 part 2)
**What:** Upload files with known display_names, then verify exact match in list_store_documents().
**When to use:** Two-fold verification per locked decision.

```python
async def verify_display_name_roundtrip(
    client,
    store_name: str,
    submitted_name: str,
    document_name: str,  # from import operation response
) -> dict:
    """Verify display_name round-trip preservation."""
    docs = await client.list_store_documents(store_name)
    for doc in docs:
        if getattr(doc, "name", None) == document_name:
            returned_name = getattr(doc, "display_name", None)
            return {
                "submitted": submitted_name,
                "returned": returned_name,
                "exact_match": submitted_name == returned_name,
                "case_match": (submitted_name or "").lower() == (returned_name or "").lower(),
                "document_state": getattr(doc, "state", None),
            }
    return {"submitted": submitted_name, "returned": None, "exact_match": False, "error": "document not found in list"}
```

### Pattern 4: Test Store Isolation
**What:** Use a dedicated ephemeral store to avoid polluting production data.
**When to use:** Always for spike work.

```python
# Create a test store with a unique name
import uuid
test_store_name = f"phase11-spike-{uuid.uuid4().hex[:8]}"
store_resource = await client.create_store(test_store_name)

# ... run all tests ...

# Cleanup: delete the test store with force=True
await client.aio.file_search_stores.delete(
    name=store_resource,
    config={"force": True}
)
```

### Anti-Patterns to Avoid
- **Using production store for tests:** Creates orphaned documents. ALWAYS use a dedicated test store with cleanup.
- **Tight polling loops without backoff:** Will trigger 429s. Use exponential backoff per locked decision.
- **Assuming operation.done means list-visible:** The operation completing and the document appearing in `list_store_documents()` may have different timings. Measure both.
- **Using `time.time()` for measurements:** `time.perf_counter()` has better resolution and is not affected by system clock adjustments.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Percentile calculation | Custom percentile code | `statistics.quantiles(data, n=100)` | Stdlib handles edge cases for small N |
| Exponential backoff | While loop with sleep | Structured backoff function | Encapsulate interval/factor/max logic |
| Test file content | Manual file creation | `tempfile.NamedTemporaryFile` + loop | Clean, auto-cleanup |
| API error classification | Custom exception parsing | Existing `_safe_call` pattern from `client.py` | Already handles 429/5xx classification |

**Key insight:** This spike is measurement-focused, not architecture-focused. Keep it simple. The deliverables are data and documentation, not reusable production code.

## Common Pitfalls

### Pitfall 1: Conflating Two display_name Paths
**What goes wrong:** The SDK has two upload paths with different `display_name` semantics:
- **Two-step** (this project): `display_name` is set on the `File` object during Files API upload. The store document inherits it from the imported File.
- **One-step** (`upload_to_file_search_store`): `display_name` is set on `UploadToFileSearchStoreConfig` and sent directly to the store.
**Why it happens:** The SDK uses the same field name in different type classes.
**How to avoid:** The spike MUST test the two-step path since that is what the production code uses (`upload_file` -> `wait_for_active` -> `import_to_store`). Do not test the one-step path -- it would produce misleading evidence.
**Warning signs:** If the spike calls `upload_to_file_search_store` instead of `upload_file` + `import_file`.

### Pitfall 2: File Object display_name vs Document display_name
**What goes wrong:** The `File.display_name` (from Files API upload) may differ from `Document.display_name` (from store import). They are different API resources with different schemas.
**Why it happens:** The `import_file()` call imports the File into the store. The resulting Document gets its display_name from the File, but the API could apply different normalization rules at the document level.
**How to avoid:** Verify BOTH: (1) `files.get(name=file.name).display_name == submitted`, and (2) `documents listed in store have display_name == submitted`. Record both in the spike output.
**Warning signs:** File-level display_name matches but document-level does not.

### Pitfall 3: 429 Rate Limiting During Lag Measurement
**What goes wrong:** Polling `list_store_documents()` too aggressively triggers rate limits, which corrupts the latency measurements (429 retry time gets counted as lag).
**Why it happens:** `list_store_documents()` with 1700+ documents is a heavy API call.
**How to avoid:** Use exponential backoff per locked decision (0.5s start, 1.5x factor, 10s max). Use a separate test store with very few documents (only the 12-15 test files). Do NOT measure against the production store.
**Warning signs:** Latency measurements showing spikes at exactly the retry interval boundaries.

### Pitfall 4: Not Cleaning Up Test Store
**What goes wrong:** Test documents and test store persist indefinitely, just like the orphaned documents from prior upload runs (see MEMORY.md).
**Why it happens:** 48hr TTL applies to Files API files only. Store documents and stores persist forever.
**How to avoid:** Delete the test store with `force=True` at the end of the spike. Better: use a try/finally pattern.
**Warning signs:** `list_store_documents()` on the test store returning documents from prior spike runs.

### Pitfall 5: Small Sample Size for Percentile Claims
**What goes wrong:** With only 10-12 files, P99 is essentially the maximum value. Statistical significance is low.
**Why it happens:** API rate limits and costs constrain sample size.
**How to avoid:** Report honestly: "P99 from 12 samples is the maximum observed value." Consider running the test 2-3 times if variance is high. Document the sample size alongside each percentile.
**Warning signs:** P50 and P99 showing very different values with N=10.

### Pitfall 6: ImportFileOperation.response.document_name vs Visibility
**What goes wrong:** The operation response returns `document_name` when `done=True`, but the document might not yet appear in `list_store_documents()` at that moment.
**Why it happens:** Eventual consistency in distributed systems. The write (import) completes before the read (list) reflects it.
**How to avoid:** Measure both timings: (1) time from `import_file()` to `operation.done==True`, and (2) time from `import_file()` to document appearing in `list_store_documents()`. The gap between these two is the "eventual consistency window."
**Warning signs:** Operation completes instantly but list visibility takes seconds.

## Code Examples

### SDK Source Evidence Collection Script

```python
# Source: Local SDK inspection of google-genai 1.63.0
import inspect
import importlib.util

def document_sdk_display_name_path():
    """Document the exact SDK source locations for display_name serialization."""

    # 1. Find files.py in installed SDK
    import google.genai.files as files_mod
    files_path = inspect.getfile(files_mod)

    # 2. Find types.py
    import google.genai.types as types_mod
    types_path = inspect.getfile(types_mod)

    # 3. Find _common.py for alias_generator
    import google.genai._common as common_mod
    common_path = inspect.getfile(common_mod)

    evidence = {
        "sdk_version": "1.63.0",
        "files_py": {
            "path": files_path,
            "async_upload_line": 1066,
            "sync_upload_line": 527,
            "description": "display_name=config_model.display_name (set on types.File)"
        },
        "types_py": {
            "path": types_path,
            "file_display_name_line": 4763,
            "document_display_name_line": 13128,
            "description": "File.display_name and Document.display_name field definitions"
        },
        "common_py": {
            "path": common_path,
            "alias_generator_line": 552,
            "description": "alias_generator=alias_generators.to_camel (display_name -> displayName in JSON)"
        },
        "conclusion": "SDK passes display_name to API without modification. "
                       "Pydantic to_camel only affects JSON key naming, not value."
    }
    return evidence
```

### Test File Corpus Generator

```python
# Generate test files with deliberately tricky display_names
import tempfile
import os

def create_test_corpus(base_dir: str) -> list[dict]:
    """Create 12-15 small .txt files with edge-case display_names."""
    test_cases = [
        # Basic cases
        {"display_name": "Simple Test File.txt", "content": "Basic test."},
        {"display_name": "lowercase_only.txt", "content": "Lower case."},
        {"display_name": "UPPERCASE_ONLY.TXT", "content": "Upper case."},
        # Mixed case (critical for normalization detection)
        {"display_name": "MiXeD CaSe FiLe.txt", "content": "Mixed case."},
        # Special characters
        {"display_name": "File With (Parentheses).txt", "content": "Parens."},
        {"display_name": "File - With Dashes.txt", "content": "Dashes."},
        {"display_name": "Leonard Peikoff - OPAR Ch.1.txt", "content": "Typical library file."},
        # Unicode / accented (edge case)
        {"display_name": "Rene Descartes - Meditations.txt", "content": "No accents."},
        # Long name (near 512 char limit)
        {"display_name": "A" * 500 + ".txt", "content": "Long name test."},
        # Spaces and padding
        {"display_name": "  Leading Spaces.txt", "content": "Leading spaces."},
        {"display_name": "Trailing Spaces  .txt", "content": "Trailing spaces."},
        {"display_name": "Multiple   Internal   Spaces.txt", "content": "Internal spaces."},
        # Realistic library filenames
        {"display_name": "Ayn Rand - Atlas Shrugged (1957).txt", "content": "Realistic."},
        {"display_name": "OCON 2023 - Harry Binswanger - Q&A.txt", "content": "Ampersand."},
    ]

    files = []
    os.makedirs(base_dir, exist_ok=True)
    for i, tc in enumerate(test_cases):
        # Use sanitized filename for local file, but submit original display_name to API
        safe_name = f"test_file_{i:02d}.txt"
        path = os.path.join(base_dir, safe_name)
        with open(path, "w") as f:
            f.write(tc["content"])
        files.append({
            "local_path": path,
            "display_name": tc["display_name"],
            "index": i,
        })
    return files
```

### Lag Measurement with Statistics

```python
import statistics
import time

def compute_percentiles(latencies: list[float]) -> dict:
    """Compute P50/P95/P99 from a list of latency measurements."""
    if not latencies:
        return {"error": "no data"}

    n = len(latencies)
    sorted_lat = sorted(latencies)

    # For small N, use linear interpolation
    if n >= 4:
        quantile_values = statistics.quantiles(sorted_lat, n=100)
        p50 = quantile_values[49]   # 50th percentile
        p95 = quantile_values[94]   # 95th percentile
        p99 = quantile_values[98]   # 99th percentile
    else:
        p50 = statistics.median(sorted_lat)
        p95 = sorted_lat[-1]
        p99 = sorted_lat[-1]

    return {
        "n": n,
        "min": min(sorted_lat),
        "p50": round(p50, 3),
        "p95": round(p95, 3),
        "p99": round(p99, 3),
        "max": max(sorted_lat),
        "mean": round(statistics.mean(sorted_lat), 3),
        "stdev": round(statistics.stdev(sorted_lat), 3) if n > 1 else 0,
    }
```

## Critical SDK Findings

### Finding 1: display_name Flow in Two-Step Upload (HIGH confidence -- local SDK source)

The project uses the two-step upload pattern defined in `client.py`:

1. **Step 1: `upload_file(file_path, display_name)`** calls `client.aio.files.upload(file=file_path, config={"display_name": display_name[:512]})`.
   - SDK file: `files.py:1066` -- `display_name=config_model.display_name` set on `types.File` object
   - The File object is a Pydantic model with `alias_generator=to_camel` (`_common.py:552`)
   - JSON serialization: `display_name` Python field -> `displayName` JSON key
   - **No value transformation occurs** -- the string value is passed through unchanged

2. **Step 2: `import_to_store(file_name, metadata)`** calls `client.aio.file_search_stores.import_file(file_search_store_name=..., file_name=..., config={"custom_metadata": ...})`.
   - SDK file: `file_search_stores.py:1117-1190` (async) / `623-696` (sync)
   - The import only references `file_name` (the Gemini file resource name), NOT `display_name`
   - `display_name` is NOT a parameter of `ImportFileConfig` (types.py:13786-13798)
   - The store Document inherits `display_name` from the imported File

3. **Response: `Document.display_name`** on listed documents
   - SDK file: `types.py:13128` -- `display_name: Optional[str]`
   - This comes from the API response, deserialized by Pydantic `Document._from_response()`

**Conclusion:** `display_name` is set once (step 1, on the File object), inherited by the Document (step 2), and read back from `Document.display_name`. The SDK does not transform the value. Whether the API server transforms it is what the round-trip test must verify.

### Finding 2: ImportFileOperation Returns document_name (HIGH confidence -- local SDK source)

The `ImportFileOperation` type (types.py:13883) extends `Operation` and has a `response` field of type `ImportFileResponse`. When the operation completes (`done=True`), the response includes:

- `parent`: The store resource name
- `document_name`: The resource name of the created document (e.g., `fileSearchStores/abc/documents/def`)

This is parsed from the API response by `_ImportFileResponse_from_mldev` (`_operations_converters.py:288-304`), which maps `documentName` -> `document_name`.

**Implication for Phase 11:** The spike can capture `document_name` from the completed operation, then use it to find the specific document in `list_store_documents()` for display_name comparison. This avoids scanning all documents.

### Finding 3: DocumentState Enum (HIGH confidence -- local SDK source)

`types.py:820-824`:
```python
class DocumentState(_common.CaseInSensitiveEnum):
    STATE_UNSPECIFIED = 'STATE_UNSPECIFIED'
    STATE_PENDING = 'STATE_PENDING'
    STATE_ACTIVE = 'STATE_ACTIVE'
```

The `Document` type has a `state: Optional[DocumentState]` field (types.py:13132). Only three states are defined. The locked decision says "visible" = appears in list at all (any state). The spike should record the `state` value on first visibility for future reference.

**Notable absence:** There is no `STATE_FAILED` or `STATE_PROCESSING` in the DocumentState enum. If a document import fails, the document may simply never appear in the list, or it may appear with `STATE_PENDING` indefinitely. The 5-minute timeout handles this.

### Finding 4: list_store_documents() API Call Structure (HIGH confidence -- local SDK source)

`documents.py:504-532` (async list method):
- Calls `{parent}/documents` endpoint (e.g., `fileSearchStores/abc123/documents`)
- Returns `AsyncPager[types.Document]` -- paginated
- Each `Document` has: `name`, `display_name`, `state`, `size_bytes`, `mime_type`, `create_time`, `custom_metadata`, `update_time`
- No server-side filtering by document name or ID -- must iterate all pages

**Performance implication:** For a test store with only 12-15 documents, pagination is irrelevant. For the production store with 1700+ documents, listing is expensive. Use the test store.

### Finding 5: display_name Truncation in Existing Code (HIGH confidence -- project source)

The existing `upload/orchestrator.py` already truncates `display_name` to 512 characters:
- Line 313: `display_name = file_info.get("filename", os.path.basename(file_path))[:512]`
- Line 906: Same in `_upload_enriched_file`

The SDK also documents the 512-char limit: `types.py:4765`: "The display name must be no more than 512 characters in length."

The existing client.py also truncates: `client.py:169`: `config={"display_name": display_name[:512]}`

This means double truncation occurs (orchestrator truncates, then client truncates again). Not a bug for Phase 11, but worth noting.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `google-generativeai` package | `google-genai` (unified) | 2025 | New SDK with different module structure |
| No File Search store concept | `file_search_stores` sub-API | 2025+ | Documents, stores, import/upload |
| Single-step upload only | Two-step (upload + import) supported | google-genai 1.x | Enables custom_metadata on import |

**Deprecated/outdated:**
- `google-generativeai` package: Replaced by `google-genai`. Different API surface entirely.
- `corpora` / `corpus` API: The old RAG API. Replaced by `file_search_stores`.

## Open Questions

1. **Does the API normalize display_name values?**
   - What we know: The SDK does NOT normalize. The File type docs say "max 512 chars."
   - What's unclear: Whether the API server lowercases, strips whitespace, replaces special characters, or performs other transformations. No documentation found on this.
   - Recommendation: This is exactly what the round-trip test must answer. Test edge cases (leading/trailing spaces, special chars, mixed case).

2. **What is the actual import-to-visible lag?**
   - What we know: The operation is "long-running" (aip.dev/151). No documented typical duration.
   - What's unclear: Whether lag is seconds, tens of seconds, or minutes for small .txt files (~1-10KB).
   - Recommendation: The spike must measure this empirically. Expect P50 in the 1-10s range based on general distributed systems knowledge (LOW confidence estimate).

3. **Does operation.done coincide with list visibility?**
   - What we know: `ImportFileOperation` returns `document_name` when done. `list_store_documents()` returns documents with state.
   - What's unclear: Whether there is a gap between operation completing and document appearing in list.
   - Recommendation: Measure both timings: (a) time to operation.done, (b) time to list visibility. Record the delta.

4. **Can documents.get() be used instead of list for visibility check?**
   - What we know: `AsyncDocuments.get(name=...)` exists (documents.py:332-391). If we have the `document_name` from the operation response, we could call `get()` directly instead of listing all documents.
   - What's unclear: Whether `get()` returns immediately for a just-imported document, or whether it has the same eventual consistency behavior as `list()`.
   - Recommendation: Try `documents.get()` as an alternative visibility check in the spike. If it works, it is dramatically more efficient than listing all documents.

## Sources

### Primary (HIGH confidence)
- **Local SDK source:** `google-genai` 1.63.0 installed at `/Users/david/.pyenv/versions/3.13.5/lib/python3.13/site-packages/google/genai/`
  - `files.py` -- Files API upload with display_name (lines 527, 1066)
  - `file_search_stores.py` -- import_file, upload_to_file_search_store, list, documents sub-module
  - `documents.py` -- Document CRUD (get, delete, list)
  - `types.py` -- File (line 4756), Document (line 13120), DocumentState (line 820), ImportFileConfig (line 13786), ImportFileResponse (line 13852), ImportFileOperation (line 13883), UploadToFileSearchStoreConfig (line 13683)
  - `_common.py` -- BaseModel with alias_generator=to_camel (line 552)
  - `_operations_converters.py` -- ImportFileResponse deserialization with document_name (line 288-304)
- **Project source:** `src/objlib/upload/client.py` -- existing GeminiFileSearchClient wrapper
- **Project source:** `src/objlib/upload/orchestrator.py` -- existing upload pipeline with display_name handling
- **Project source:** `spike/phase10_spike/` -- harness pattern, recovery crawler, states

### Secondary (MEDIUM confidence)
- **Google AI official docs** (https://ai.google.dev/gemini-api/docs/file-search) -- confirms display_name is caller-set, no specifics on normalization behavior

### Tertiary (LOW confidence)
- **General distributed systems knowledge** -- P50 latency estimate of 1-10s for import-to-visible is based on typical eventually-consistent systems, not Gemini-specific data

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries verified installed, versions confirmed
- Architecture: HIGH -- SDK source fully inspected locally, code paths traced
- Pitfalls: HIGH -- based on direct code reading and known project history (MEMORY.md orphaned documents)
- Lag estimates: LOW -- no empirical data exists; this is what Phase 11 spike measures

**Research date:** 2026-02-20
**Valid until:** 2026-03-20 (SDK version-pinned; API behavior may change with SDK updates)
