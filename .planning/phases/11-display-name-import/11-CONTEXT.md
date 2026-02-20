# CONTEXT.md — Phase 11: Wave 3 — display_name Stability and Import Reliability

**Generated:** 2026-02-20
**Phase Goal:** `display_name` is confirmed caller-controlled (not API-inferred), import-to-visible lag is measured and bounded, and the PROCESSING-to-INDEXED trigger strategy is decided
**Synthesis Source:** Multi-provider AI analysis (Gemini Pro, Perplexity Sonar Deep Research)
**Note:** OpenAI response truncated at model-detection stage; synthesis based on 2 of 3 providers (sufficient per policy)

---

## Overview

Phase 11 is a HOSTILE-distrust spike: every assumption about how the Gemini File Search store behaves must be proven, not guessed. The three success criteria are each a distinct investigation:

1. **SDK source inspection** — prove `display_name` is set by our code and not modified by the API
2. **Empirical lag measurement** — characterize the delay between `import_()` returning and the document appearing in `list_store_documents()`
3. **Trigger strategy decision** — commit to one of three strategies for the PROCESSING→INDEXED FSM transition, justified by the measured data

Both providers converged strongly on the key decisions. The synthesis reflects high confidence on the critical path.

**Confidence markers:**
- ✅ **Consensus** — Both providers identified this as critical (2/2)
- ⚠️ **Recommended** — One provider identified this, strong rationale
- 🔍 **Needs Clarification** — One provider identified, potentially important

---

## Gray Areas Identified

### ✅ 1. SDK Verification Is Not Sufficient Alone (Consensus)

**What needs to be decided:**
The success criterion says `display_name` must be confirmed via "SDK source inspection." But SDK source inspection only proves the Python client *sends* the field — it does not prove the API *preserves* it unmodified. The HOSTILE standard requires both.

**Why it's ambiguous:**
Google APIs frequently normalize file names (lowercase, strip special chars, enforce length limits). The SDK might faithfully pass `display_name="My File.txt"` and the API might store `"my_file.txt"`. SDK inspection would pass; round-trip would fail. Only testing both catches this.

**Provider synthesis:**
- **Gemini:** "Finding the line in the SDK proves the Python client *sends* the data. It does not prove the API *accepts* it without modification. Google APIs frequently sanitize file names." Recommends two-fold: static analysis + round-trip confirmation.
- **Perplexity:** "SDK source inspection alone is insufficient. Verify through code inspection AND empirical testing that `display_name` is truly immutable." Notes the `name` vs `display_name` parameter distinction across API paths as a red flag.

**Proposed implementation decision:**
**Two-fold verification:**
1. Locate the `display_name=` parameter in the installed `google-genai` SDK source (site-packages) and confirm it is serialized into the HTTP request body without modification — record the specific file and line.
2. Run a round-trip test: import 10+ files with known `display_name` values, then verify `list_store_documents()` returns the exact values submitted (case-sensitive string equality). If any mismatch is found, document the normalization rule.

**Open questions:**
- Does the API normalize `display_name` (e.g., lowercase, strip spaces)?
- Is the `name` field from `files.upload()` different from the `display_name` on the store document?

**Confidence:** ✅ Both providers agreed

---

### ✅ 2. "Visible" Must Be Precisely Defined for Lag Measurement (Consensus)

**What needs to be decided:**
The lag measurement requires a precise start point and a precise stop point. "Visible" is ambiguous in the Gemini API.

**Why it's ambiguous:**
"Visible" can mean:
- (a) The document ID appears in `list_store_documents()` (existence)
- (b) The document has `state == ACTIVE` (processed and vectorized)
- (c) The document actually returns in semantic search results (searchable)

Measuring (a) when (b) is what the FSM needs produces meaningless metrics.

**Provider synthesis:**
- **Gemini:** "Measure Time-to-INDEXED. Stop timer when document is found AND its state is `ACTIVE`. If state is `PROCESSING` during a poll, the timer continues." Warns that tight polling loops (100ms) may trigger 429s.
- **Perplexity:** "Does `list_store_documents()` support server-side filtering by ID? If we have to fetch the whole page of 1,749 files to check for one, the measurement methodology changes drastically." Notes the operation's `done` field transitions only from false to true — no intermediate states exposed.

**Proposed implementation decision:**
**"Visible" = appears in `list_store_documents()` at all** — regardless of any state field. The mere presence in the list is the stop point for lag measurement, since that is what our DB/FSM needs to record (`gemini_store_doc_id` captured). Whether the document is *searchable* is tested separately in Phase 12 (SC5). Use exponential backoff for polling (start 0.5s, factor 1.5, max 10s per poll) to avoid 429s.

**Open questions:**
- Does `list_store_documents()` expose a document state field (PROCESSING/ACTIVE/FAILED)?
- Does the API support filtering by document ID, or must we list all and search locally?

**Confidence:** ✅ Both providers agreed on the ambiguity; implementation decision is Phase 11-specific

---

### ✅ 3. PROCESSING→INDEXED Trigger Strategy Must Be Committed (Consensus)

**What needs to be decided:**
Which of the three strategies governs the FSM's PROCESSING→INDEXED transition for production use in Phase 12+:

- **(a) Polling:** Background task polls `list_store_documents()` until visible, then transitions
- **(b) Trust API:** Import success → immediately INDEXED; store-sync provides eventual reconciliation
- **(c) VERIFYING state:** New intermediate FSM state for the visibility-check period

**Why it's ambiguous:**
Option (b) is ruled out by HOSTILE-distrust stance (positive evidence required). Options (a) and (c) are structurally similar but have architectural implications. The choice must be justified by the lag data.

**Provider synthesis:**
- **Gemini:** "Implement Strategy A (Polling) with a Batch Manager. Do NOT hold the UI/CLI thread waiting for INDEXED. Implement a `ConsistencyCheck` routine that queries the API for all items currently marked PROCESSING in the DB."
- **Perplexity:** "Strategy B (polling) offers the best balance of synchronous confirmation and simplicity. Production systems often deploy Strategy A (trusting API success) for latency + asynchronous Strategy B verification for correctness."

**Proposed implementation decision:**
**Strategy B (non-blocking polling):** Import returns immediately, FSM enters PROCESSING, background task polls with exponential backoff until visible, then transitions to INDEXED. No new FSM states needed — PROCESSING already exists. The polling loop respects the Phase 10 write-ahead intent pattern.

The key constraint: FSM transition to INDEXED happens in the background poller, not inline in the upload pipeline. This means PROCESSING is a legitimate long-running state (minutes, not seconds).

**Confidence:** ✅ Both providers converged on non-blocking polling

---

### ⚠️ 4. P99 Lag Acceptance Threshold Must Be Defined (Recommended)

**What needs to be decided:**
What P99 latency value makes Phase 11 pass vs. fail? And what happens if P99 exceeds the threshold?

**Why it's ambiguous:**
The success criteria say "characterized with P50/P95/P99 latencies" but don't define the acceptance threshold. Without a threshold, Phase 11 cannot have a pass/fail gate.

**Provider synthesis:**
- **Gemini:** "For the test of 10+ files, if the P99 exceeds 30 seconds, fail the Phase. The system needs to be responsive enough for a personal library." Also recommends varying file sizes to detect size-correlation.
- **Perplexity:** Estimates P50 1-30s and P99 60-120s for typical files based on distributed systems patterns. Recommends P99 × 1.5 as timeout threshold.

**Proposed implementation decision:**
Phase 11 gate: measure empirically, report all three values. Gate **passes** if P99 ≤ 300 seconds (5 minutes). The polling loop timeout is set to 5 minutes. If P99 exceeds 60 seconds for small .txt files, log a warning and document for Phase 12 planning, but do not block the gate unless P99 > 300s. The Phase 11 report must include the actual measured values — these inform the Phase 12 upload design.

**Confidence:** ⚠️ Perplexity primary; Gemini had a stricter threshold (30s) but that may be too aggressive before measurement

---

### ⚠️ 5. PROCESSING State Error Handling (Recommended)

**What needs to be decided:**
If the Gemini API reports an error during async processing (not "not yet visible" but a real failure), which FSM transition fires and where is the error stored?

**Why it's ambiguous:**
The `import_()` call returns HTTP 200 (success). But vectorization/indexing happens asynchronously. The API might accept the file and then silently fail the embedding step. When polling, we might get an error state or a document that never appears.

**Provider synthesis:**
- **Gemini:** "Add a dead-end FAILED state. If polling detects `state == FAILED` in the API, FSM transitions PROCESSING → FAILED. This error must be persisted with the API's error message."
- **Perplexity:** Recommends circuit breaker and permanent-invisibility detection (5-minute timeout → FAILED).

**Proposed implementation decision:**
Reuse the existing FAILED state from Phase 10. Two failure modes:
1. **API reports failure** (if list_store_documents() exposes a FAILED/ERROR state for the document) → immediate PROCESSING→FAILED transition
2. **Polling timeout** (document never appears in 5 minutes) → PROCESSING→FAILED transition with timeout error recorded

The existing RecoveryCrawler from Phase 10 handles FAILED→UNTRACKED escape. No new FSM states needed.

**Confidence:** ⚠️ Gemini primary; aligns well with Phase 10 design

---

### ⚠️ 6. display_name Normalization Risk (Recommended)

**What needs to be decided:**
If the API silently normalizes `display_name` (lowercases, truncates, strips special chars), what is the plan?

**Why it's ambiguous:**
Our filenames contain spaces, slashes, periods, and mixed case. If the API normalizes any of these, the `display_name` stored in our DB won't match what Gemini stores, breaking citation lookup.

**Provider synthesis:**
- **Perplexity:** Notes the `name` vs `display_name` parameter naming inconsistency across API paths as evidence that field semantics may vary. Recommends recording submitted vs returned values and tracking discrepancy frequency.
- **Gemini:** "Does the API throw an error for invalid display_name characters, or does it silently sanitize them?" Recommends confirming round-trip equality.

**Proposed implementation decision:**
Phase 11 spike records: for each of the 10+ test files, the exact `display_name` submitted AND the exact value returned by `list_store_documents()`. If they differ, document the transformation rule. If the API normalizes names, Phase 12 uploads must pre-apply the same normalization before storing in DB, so DB and store are always consistent.

**Confidence:** ⚠️ Perplexity primary; important for citation correctness

---

## Summary: Decision Checklist

**Tier 1 (Blocking — must decide before plan is written):**
- [ ] Two-fold `display_name` verification: SDK source location + round-trip test design
- [ ] Definition of "visible" for lag measurement stop point
- [ ] PROCESSING→INDEXED trigger strategy (non-blocking polling confirmed)

**Tier 2 (Important — inform implementation):**
- [ ] P99 lag acceptance threshold for Phase 11 gate
- [ ] PROCESSING→FAILED error handling (API failure + polling timeout)

**Tier 3 (Polish — document outcomes):**
- [ ] display_name normalization handling if API transforms submitted values

---

## Spike Scope for Phase 11

This phase is a **measurement and verification spike** — no production code changes. The deliverables are:
1. A Python spike script that inspects SDK source and runs the lag measurement
2. A document recording exact SDK file/line for `display_name` serialization
3. Empirical P50/P95/P99 latency data from 10+ test imports
4. Written decision on trigger strategy with data justification

All findings are committed before Phase 12 begins (Phase 11 gate is BLOCKING).

---

*Multi-provider synthesis by: Gemini Pro, Perplexity Sonar Deep Research*
*Note: OpenAI response truncated at model detection; synthesis from 2/3 providers*
*Generated: 2026-02-20*
