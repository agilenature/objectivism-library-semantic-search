# PROCESSING-to-INDEXED Trigger Strategy

**Phase:** 11 -- display_name Stability and Import Reliability
**Decision Date:** 2026-02-20
**Status:** COMMITTED
**Data Source:** `spike/phase11_spike/RESULTS.md` (Plan 11-01 empirical measurements)

---

## 1. Strategy Decision

**Committed strategy: Non-blocking polling with no new FSM states.**

Per locked Decision 3 (from Phase 11 clarifications), the PROCESSING-to-INDEXED trigger uses non-blocking polling without introducing new FSM states (no VERIFYING state).

### Flow

1. Upload pipeline calls `import_file()` on the Gemini File Search Store.
2. FSM transitions file to **PROCESSING** state.
3. The `import_file()` operation is polled until `operation.done == True` (this is the real bottleneck -- can take 5-30s for larger files).
4. Once `operation.done == True`, a **single `documents.get()` call** confirms the document is visible in the store.
5. On successful visibility confirmation, FSM transitions to **INDEXED**.

### Key Insight from Empirical Data

The measured import-to-visible lag is **near-zero** (P50 = 0.243s). Documents are visible **immediately** after the import operation completes. The measured latency is the API call round-trip time itself, not an eventual consistency delay. This eliminates the need for a long-running background polling loop -- a single `documents.get()` call after `operation.done == True` is sufficient.

PROCESSING is a legitimate long-running state, but its duration is bounded by the import operation itself, not by a visibility delay.

---

## 2. Measured Lag Data

All data from `spike/phase11_spike/RESULTS.md`. N = 13 successful measurements (1 failed: leading whitespace import hang, excluded from latency statistics).

### Overall Import-to-Visible Latency

| Method | N | P50 | P95 | P99 | Min | Max | Mean | StDev |
|---|---|---|---|---|---|---|---|---|
| documents.get() | 13 | 0.243s | 0.252s | 0.253s | 0.207s | 0.252s | 0.233s | 0.019s |
| documents.list() | 13 | 0.495s | 0.646s | 0.646s | 0.424s | 0.646s | 0.532s | 0.076s |

**documents.get() is 2x faster than documents.list()** and is the recommended visibility check method.

### Latency by File Size Bucket (documents.get)

| Bucket | N | P50 | Mean | Max |
|---|---|---|---|---|
| 1KB | 4 | 0.247s | 0.247s | 0.252s |
| 10KB | 4 | 0.246s | 0.246s | 0.251s |
| 50KB | 3 | 0.210s | 0.210s | 0.213s |
| 100KB | 2 | 0.210s | 0.210s | 0.212s |

**No meaningful correlation between file size and visibility lag.** Larger files showed slightly lower latency (within noise). The import operation duration itself may vary with file size, but post-import visibility is constant.

### Statistical Note

With N = 13 samples, P99 is effectively the maximum observed value. The extremely low variance (StDev = 0.019s for documents.get()) indicates this is not a noisy measurement -- all 13 files became visible within approximately the same time window.

---

## 3. Polling Parameters (Validated)

### Locked Parameters (from Phase 11 clarifications)

| Parameter | Value | Status |
|---|---|---|
| Initial interval | 0.5s | Confirmed adequate |
| Backoff factor | 1.5x | Confirmed adequate |
| Max interval | 10s | Confirmed adequate |
| Absolute timeout | 300s (5 min) | Confirmed adequate |

### Validation Against Empirical Data

- **Measured P99 = 0.253s** -- documents are visible within the **first** poll interval (0.5s).
- The 300s timeout provides a **1,184x safety margin** over the observed maximum (0.253s).
- Even the most conservative scenario (documents.list() P95 = 0.646s) falls within the first poll interval.

### Recommended Implementation

**Primary path (expected 100% of the time):**
After `import_file()` returns `operation.done == True`, issue a single `documents.get(name=document_name)` call. This confirms visibility in P50 = 0.243s. Transition immediately to INDEXED.

**Fallback path (defensive, for unexpected API behavior):**
If the single `documents.get()` returns 404 (document not yet visible -- never observed in testing, but defensively handled):
1. Wait 0.5s (initial interval).
2. Retry `documents.get()`.
3. On subsequent 404s, apply 1.5x exponential backoff up to 10s max interval.
4. If 300s absolute timeout is exceeded, transition to FAILED.

This makes the common case O(1) (single API call) while retaining the full polling loop as a safety net.

---

## 4. Visibility Check Method

### Recommended: documents.get(name=document_name)

| Criterion | documents.get() | documents.list() |
|---|---|---|
| Latency (P50) | 0.243s | 0.495s |
| Complexity | O(1) -- single document lookup | O(N) -- paginated scan |
| Requires | document_name (from ImportFileOperation.response) | store_name only |
| Reliability | 13/13 successful | 13/13 successful |

**Decision: Use `documents.get()` as the primary visibility check.**

The `document_name` is available from `ImportFileOperation.response.document_name` after the import operation completes. This is a direct O(1) lookup rather than a paginated scan, and is 2x faster at P50.

### Eventual Consistency

**No eventual consistency gap was observed.** All 13 test files were visible in the first `documents.get()` call after `operation.done == True`. The measured latency is the API call's network round-trip time, not a propagation delay. This means:

- No "wait and retry" pattern is needed for the common case.
- The PROCESSING state duration is governed by the import operation, not by a visibility delay.
- The polling loop is purely defensive -- it handles theoretical edge cases, not observed behavior.

---

## 5. Error Handling

### PROCESSING-to-FAILED Trigger Conditions

Per locked Decision 4, two conditions trigger the PROCESSING-to-FAILED transition:

**Condition 1: API Error State**
If `documents.get()` returns a non-404 error (e.g., 500, 403, or a document with an error state), the file transitions to FAILED. Specific cases:
- HTTP 4xx/5xx errors on the `documents.get()` call (excluding 404).
- The document exists but is in an error state reported by the API.

**Condition 2: Absolute Timeout**
If the document is not visible within 300 seconds (5 minutes) of the import operation completing, the file transitions to FAILED. This timeout is 1,184x the observed P99 and should never trigger under normal conditions.

### Recovery Path

Both FAILED conditions feed into the existing **RecoveryCrawler** from Phase 10:
- RecoveryCrawler detects files in FAILED state on startup.
- Recovery uses the write-ahead intent pattern (Phase 10 proven) for safe state transitions.
- FAILED files can be retried via `retry_failed_file()` (FAILED -> UNTRACKED escape path).

### Import Operation Timeout

The import operation itself (before `operation.done == True`) has a separate timeout of 120s (per RESULTS.md spike configuration). This is the real bottleneck for large files. If the import operation times out:
- The FSM remains in PROCESSING state.
- The 300s visibility timeout does NOT start (it only starts after `operation.done == True`).
- The import operation timeout should be treated as PROCESSING-to-FAILED as well.

---

## 6. CRITICAL FINDING: Document.display_name != Submitted Name

### Discovery

During Plan 11-01 round-trip testing, a critical finding was made:

| Field | Contains | Example |
|---|---|---|
| **File.display_name** | The submitted human-readable name | `Ayn Rand - Atlas Shrugged (1957)` |
| **Document.display_name** | The Files API resource ID | `sqowzecl39n8` |

**0/13 Document.display_name values matched the submitted display_name.** This is the API's designed behavior, not a bug.

### Impact on Phase 12

- Phase 12 must **NOT** rely on `Document.display_name` for citation mapping or human-readable display.
- The existing objlib citation pipeline correctly uses `gemini_file_id` -> DB lookup (see `enrich_citations()` in `src/objlib/search/citations.py`).
- **Audit required:** Phase 12 must verify that no code path assumes `Document.display_name == File.display_name`.

### Correct Citation Mapping Chain

```
Search result -> Gemini file_id -> DB files.gemini_file_id -> files.filename -> display
```

This chain is already implemented in objlib. The finding confirms it is the **only** correct approach.

---

## 7. Leading Whitespace Warning

### Finding

Test case #8 (`"  Leading Spaces Name"`, with 2 leading spaces) uploaded to the Files API successfully but the subsequent import operation to the File Search Store **never completed** -- it timed out at 120s.

### Affected vs. Unaffected Cases

| Pattern | Result |
|---|---|
| Leading spaces (`"  Leading Spaces Name"`) | Import HANG (120s timeout) |
| Trailing spaces (`"Trailing Spaces Name  "`) | OK -- exact round-trip match |
| Internal multiple spaces (`"Multiple   Internal   Spaces"`) | OK -- exact round-trip match |
| Mixed case, parentheses, dashes, ampersands, periods | OK -- exact round-trip match |
| 500-character name | OK -- exact round-trip match |

### Recommendation

Apply `display_name.strip()` (or at minimum `display_name.lstrip()`) before upload as a defensive measure. This is a LOW risk in practice (real filenames rarely have leading whitespace), but the failure mode is severe (silent hang, wasted API quota).

Phase 12 implementation **must** include this sanitization in the upload preprocessing step.

---

## 8. Implications for Phase 12

### What Phase 12 Must Implement

1. **Post-import visibility check:** After `import_file()` returns `operation.done == True`, call `documents.get(name=document_name)`. On success, transition PROCESSING -> INDEXED.
2. **Fallback polling loop:** If `documents.get()` returns 404 (never observed, but defensive), poll with 0.5s initial / 1.5x backoff / 10s max / 300s timeout.
3. **display_name sanitization:** Apply `strip()` to display_name before upload to prevent import hangs.
4. **Citation mapping audit:** Verify no code path assumes `Document.display_name == File.display_name`.
5. **Error handling:** Non-404 errors on `documents.get()` and 300s timeout both trigger PROCESSING -> FAILED.

### Key Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Leading whitespace causes import hang | LOW (rare in real filenames) | `strip()` before upload |
| Document.display_name misunderstanding | MEDIUM (incorrect assumption could break citations) | Audit all code paths in Phase 12 |
| N=13 sample size | LOW (consistent results, low variance) | Monitor first 50-file batch for anomalies |

### Sample Size Representativeness

The N=13 sample is small but internally consistent (StDev = 0.019s for documents.get()). The findings should hold for the 50-file Phase 12 batch and the full 1,748-file upload because:
- Visibility lag is independent of file size (confirmed by size-bucket analysis).
- The lag is fundamentally the API call round-trip, not a content-dependent operation.
- The low variance suggests stable, deterministic behavior.

Phase 12 should monitor the first 50-file batch for any anomalies (visibility delays > 1s, import failures) and escalate if observed.

---

*Strategy committed: 2026-02-20*
*Data source: spike/phase11_spike/RESULTS.md*
*Phase 11 Plan 02, Task 1*
