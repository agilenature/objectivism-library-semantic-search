# Phase 11 Gate Evidence: display_name Stability and Import Reliability

**Phase:** 11 -- display_name Stability and Import Reliability
**Gate Type:** BLOCKING for Phase 12
**Distrust Level:** HOSTILE -- requires affirmative empirical evidence, not absence of failure
**Assessment Date:** 2026-02-20
**Verdict:** **PASS**

---

## Gate Summary

| Success Criterion | Status | Key Evidence |
|---|---|---|
| SC1: display_name is caller-controlled | **PASS** | 13/13 File.display_name exact match; SDK source: files.py:1066 |
| SC2: Import-to-visible lag measured (P50/P95/P99) | **PASS** | documents.get() P50=0.243s, P95=0.252s, P99=0.253s (N=13) |
| SC3: PROCESSING-to-INDEXED trigger strategy committed | **PASS** | TRIGGER-STRATEGY.md: single documents.get() after operation.done |
| **Overall** | **PASS** | **Phase 12 unblocked** |

---

## SC1: display_name is Confirmed Caller-Controlled

**Verdict: PASS**

### SDK Source Evidence

Inspection of google-genai 1.63.0 SDK source confirms the display_name value passes through the SDK **without any transformation**:

| File | Line(s) | Evidence |
|---|---|---|
| `google/genai/files.py` | 527 | Sync upload: `display_name=config_model.display_name` -- direct assignment from config |
| `google/genai/files.py` | 1066 | Async upload: `display_name=config_model.display_name` -- direct assignment from config |
| `google/genai/types.py` | 4763 | `File.display_name: Optional[str]` -- File model field definition |
| `google/genai/types.py` | 13128 | `Document.display_name: Optional[str]` -- Document model field definition |
| `google/genai/types.py` | 15635 | `UploadFileConfig.display_name: Optional[str]` -- Config field definition |
| `google/genai/_common.py` | 552 | `alias_generator=to_camel` -- affects JSON key naming (`display_name` -> `displayName` in HTTP), NOT the value |

The serialization chain is: `UploadFileConfig.display_name` -> direct assignment -> `File.display_name`. No normalization, truncation, or modification of the string value occurs in the SDK.

### Round-Trip Evidence

13 test files with adversarial display_name patterns were uploaded via the Files API and their returned `File.display_name` compared to the submitted value:

| Test Case | Pattern | File.display_name Match |
|---|---|---|
| Simple Test Name | Basic text | EXACT |
| lowercase_only_name | All lowercase with underscores | EXACT |
| UPPERCASE_ONLY_NAME | All uppercase with underscores | EXACT |
| MiXeD CaSe NaMe | Alternating case with spaces | EXACT |
| Name With (Parentheses) | Special chars: parentheses | EXACT |
| Name-With-Dashes-And-More | Special chars: dashes | EXACT |
| Philosophy Q&A Session | Special chars: ampersand | EXACT |
| Introduction Ch.1 Overview | Special chars: period | EXACT |
| Trailing Spaces Name__ | Trailing whitespace | EXACT |
| Ayn Rand - Atlas Shrugged (1957) | Real-world filename pattern | EXACT |
| OCON 2023 - Harry Binswanger - Q&A | Real-world filename with ampersand | EXACT |
| AAAA...A (500 chars) | Near 512-char limit | EXACT |
| Multiple___Internal___Spaces | Internal multiple spaces | EXACT |

**Result: 13/13 EXACT match.** The API preserves display_name verbatim, including mixed case, special characters, trailing whitespace, 500-character names, and multiple internal spaces.

### Document.display_name Finding (CRITICAL)

**Document.display_name is NOT the submitted display_name.** It is the Files API resource ID.

| Submitted display_name | Document.display_name | Match |
|---|---|---|
| Simple Test Name | sqowzecl39n8 | NO |
| lowercase_only_name | 0b19o5b47m2p | NO |
| UPPERCASE_ONLY_NAME | fama67oowmox | NO |
| (all 13 test cases) | (file resource IDs) | NO |

**0/13 match.** This is the API's designed behavior: when a file is imported into a File Search Store, the resulting Document gets the file's resource ID as its `display_name`, not the file's human-readable `display_name`.

**Impact:** Citation mapping must use `file_id` -> DB lookup. The existing objlib pipeline (`enrich_citations()` in `src/objlib/search/citations.py`) already does this correctly. Phase 12 must audit that no code path assumes `Document.display_name == File.display_name`.

### SC1 Conclusion

**File.display_name IS caller-controlled** -- confirmed by SDK source inspection (no transformation in the serialization chain) and 13/13 exact round-trip matches across adversarial test cases. Document.display_name is a separate field containing the file resource ID, which is the API's designed behavior.

---

## SC2: Import-to-Visible Lag Measured with P50/P95/P99

**Verdict: PASS**

### Sample Size

- **N = 13** successful measurements across 4 size buckets (1KB, 10KB, 50KB, 100KB).
- **1 failed measurement** (leading whitespace import hang -- excluded from latency statistics).
- Test files uploaded to and imported into a Gemini File Search Store, then immediately queried for visibility.

### Latency Data

**Overall (documents.get -- recommended method):**

| Metric | Value |
|---|---|
| P50 | 0.243s |
| P95 | 0.252s |
| P99 | 0.253s |
| Min | 0.207s |
| Max | 0.252s |
| Mean | 0.233s |
| StDev | 0.019s |

**Overall (documents.list -- alternative method):**

| Metric | Value |
|---|---|
| P50 | 0.495s |
| P95 | 0.646s |
| P99 | 0.646s |

**By size bucket (documents.get):**

| Bucket | N | P50 | Mean | Max |
|---|---|---|---|---|
| 1KB | 4 | 0.247s | 0.247s | 0.252s |
| 10KB | 4 | 0.246s | 0.246s | 0.251s |
| 50KB | 3 | 0.210s | 0.210s | 0.213s |
| 100KB | 2 | 0.210s | 0.210s | 0.212s |

**No meaningful correlation between file size and visibility lag.** The import operation duration may vary with file size, but post-import visibility is independent of file size.

### Key Finding: Immediate Visibility

Documents are visible **immediately** after the import operation completes (`operation.done == True`). The measured latency (P50 = 0.243s) is the `documents.get()` API call's network round-trip time, not an eventual consistency propagation delay. No polling loop is required -- a single `documents.get()` call confirms visibility.

### Statistical Note

With N = 13 samples, the P99 value is effectively the maximum observed value. The extremely low variance (StDev = 0.019s) indicates stable, deterministic behavior rather than a noisy measurement with hidden tail latency.

### SC2 Conclusion

Import-to-visible lag is characterized with P50/P95/P99 values. The lag is near-zero (dominated by API call round-trip) and independent of file size. The characterization is complete.

---

## SC3: PROCESSING-to-INDEXED Trigger Strategy Decided and Documented

**Verdict: PASS**

### Reference Document

Full strategy documented in `spike/phase11_spike/TRIGGER-STRATEGY.md` (committed 2026-02-20).

### Strategy Summary

**Non-blocking polling with no new FSM states** (per locked Decision 3):

1. `import_file()` is called; FSM enters PROCESSING.
2. Import operation is polled until `operation.done == True`.
3. A **single `documents.get(name=document_name)` call** confirms document visibility (P50 = 0.243s).
4. On success, FSM transitions PROCESSING -> INDEXED.
5. On 404 (never observed), fallback to polling: 0.5s initial / 1.5x backoff / 10s max / 300s timeout.
6. On timeout (300s) or non-404 error, FSM transitions PROCESSING -> FAILED.

### Data Justification

| Parameter | Value | Justification |
|---|---|---|
| Primary check | Single documents.get() | P50 = 0.243s; 13/13 succeeded on first call |
| Fallback initial interval | 0.5s | Measured P99 = 0.253s falls within first interval |
| Backoff factor | 1.5x | Standard exponential backoff |
| Max interval | 10s | Conservative upper bound |
| Absolute timeout | 300s | 1,184x safety margin over observed max |

The strategy is data-justified: measured P99 = 0.253s means documents are visible within the first poll interval (0.5s). The 300s timeout provides a 1,184x safety margin. No long-running background polling loop is required.

### Error Conditions

Two PROCESSING-to-FAILED triggers (per locked Decision 4):
1. **API error state:** Non-404 error from `documents.get()`.
2. **Timeout:** 300s absolute timeout exceeded without visibility confirmation.

Both feed into the existing RecoveryCrawler (Phase 10) for automatic recovery.

### SC3 Conclusion

PROCESSING-to-INDEXED trigger strategy is committed with data-backed rationale. The strategy accounts for the measured near-zero eventual consistency window and provides a 1,184x safety margin on the timeout. Strategy is documented in TRIGGER-STRATEGY.md.

---

## Overall Gate Verdict

### **PASS -- Phase 12 is UNBLOCKED.**

All three success criteria pass with affirmative empirical evidence at HOSTILE distrust level:

- **SC1:** SDK source + 13/13 round-trip match confirms File.display_name is caller-controlled.
- **SC2:** P50/P95/P99 measured (0.243s/0.252s/0.253s) -- near-zero visibility lag, no eventual consistency delay.
- **SC3:** Trigger strategy committed in TRIGGER-STRATEGY.md with data-justified parameters.

---

## Additional Findings (Not Success Criteria)

These findings are not part of the formal gate assessment but are important for Phase 12 implementation.

### Document.display_name = File Resource ID

`Document.display_name` contains the Files API resource ID (e.g., `sqowzecl39n8`), NOT the human-readable name submitted during upload. 0/13 matches between `Document.display_name` and submitted `display_name`. Phase 12 must audit all code paths to confirm none assume `Document.display_name == File.display_name`.

### Leading Whitespace Causes Import Hang

A display_name with leading whitespace (`"  Leading Spaces Name"`) uploaded successfully to the Files API but the import operation to the File Search Store never completed (timed out at 120s). Trailing spaces and internal spaces work fine. Phase 12 must apply `display_name.strip()` before upload.

---

## Phase 12 Readiness

### What Phase 12 Can Rely On

1. **File.display_name is caller-controlled.** Whatever string is passed to `display_name=` in the upload call is preserved exactly by the API (verified across special chars, case, spaces, 500-char names).
2. **Import-to-visible lag is near-zero.** After `import_file()` completes, a single `documents.get()` call confirms visibility (P50 = 0.243s). No polling loop needed for the common case.
3. **Polling parameters are validated.** 0.5s initial / 1.5x backoff / 10s max / 300s timeout provides a 1,184x safety margin over observed maximum latency.
4. **documents.get() is the preferred visibility check.** 2x faster than documents.list(), O(1) complexity, document_name available from ImportFileOperation.response.
5. **PROCESSING-to-FAILED conditions defined.** API error state OR 300s timeout triggers FAILED, with RecoveryCrawler recovery.

### Caveats and Risks for Phase 12

1. **Leading whitespace sanitization required.** Apply `strip()` to display_name before upload. Failure mode: silent import hang.
2. **Document.display_name audit required.** Verify no code path assumes Document.display_name = File.display_name. The correct citation chain is `file_id` -> DB lookup.
3. **N=13 sample size.** Findings are internally consistent (low variance) but the 50-file Phase 12 batch should be monitored for anomalies (visibility delays > 1s, unexpected import failures).
4. **Import operation timeout.** The import operation itself (before `operation.done == True`) can take 5-30s for larger files. The 120s import timeout from the spike may need adjustment for production file sizes.

---

*Gate assessment completed: 2026-02-20*
*Data source: spike/phase11_spike/RESULTS.md*
*Strategy reference: spike/phase11_spike/TRIGGER-STRATEGY.md*
*Phase 11 Plan 02, Task 2*
