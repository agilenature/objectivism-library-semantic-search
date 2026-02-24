# CONTEXT.md — Phase 16: Full Library Upload

**Generated:** 2026-02-23
**Phase Goal:** All ~1,748 files uploaded through the FSM-managed pipeline; `[Unresolved file #N]` never appears in TUI search results — definition of done for v2.0
**Synthesis Source:** Multi-provider AI analysis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research)

---

## Overview

Phase 16 is the culminating wave of v2.0 — scaling from the 50-file proxy corpus (Phase 12) to the full 1,748-file production library. The FSM, concurrency model, store-sync contract, and stability protocol are all validated; this phase executes them at 34.96x scale and gates v2.0 completion.

Key known facts entering Phase 16:
- 5% silent failure rate at 50-file scale (query-specificity, not indexing failure — Phase 15 finding)
- Import-to-searchable lag: P50=7.3s, P95=10.1s
- store-sync role: scheduled + targeted post-run (Phase 15 decision, VLID-07 gate)
- c=10 concurrency confirmed safe (Phase 14, WAL contention irrelevant at realistic API latency)
- 7-assertion stability instrument operational (check_stability.py, Phase 15-03)
- RecoveryCrawler + retry_failed_file() provide automatic FAILED escape
- downgrade_to_failed() authorized as 7th write site (Phase 15)

**Confidence markers:**
- ✅ **Consensus** — All 3 providers identified this as critical
- ⚠️ **Recommended** — 2 providers identified this as important
- 🔍 **Needs Clarification** — 1 provider identified, potentially important

---

## Gray Areas Identified

### ✅ 1. Rate Limiting and Retry Behavior at Full Scale (Consensus)

**What needs to be decided:**
Whether the existing FSM retry infrastructure handles 429s gracefully at 1,748-file scale, or whether additional client-side throttling is required.

**Why it's ambiguous:**
The 50-file corpus likely did not trigger sustained rate limits. At 1,748 files with c=10, the upload may sustain enough QPS to trigger API-level throttling. Without explicit 429 handling, the FSM would transition files to FAILED state unnecessarily.

**Provider synthesis:**
- **OpenAI:** Token-bucket rate limiter + exponential backoff with jitter; 429s should NOT cause FAILED transitions
- **Gemini:** 429s should trigger temporary wait/retry state, not FAILED; client-side throttle at 80% of RPM limit
- **Perplexity:** Tiered retry: immediate retry for 429s (tier 1), exponential backoff 100ms–5s for timeouts (tier 2), dead letter for deterministic failures (tier 3)

**Proposed implementation decision:**
The existing FSM's `retry_failed_file()` (FAILED→UNTRACKED escape) already provides a recovery path. For the upload execution in 16-01, the orchestrator should:
- Catch 429 responses and apply exponential backoff + jitter (base 1s, max 60s) **without** transitioning to FAILED
- Use c=10 with asyncio.Semaphore (already validated in Phase 14)
- After max retries (5) on transient errors only → FAILED state → RecoveryCrawler picks up

**Confidence:** ✅ All 3 providers agree 429 handling must be retry-not-fail

---

### ✅ 2. Silent Failure Rate at Full Scale (~87 Files Expected) (Consensus)

**What needs to be decided:**
What threshold of "indexed but not searchable" files is acceptable at full scale, and what is the automated remediation path.

**Why it's ambiguous:**
5% at 50-file scale = 2.5 files. 5% at 1,748 = ~87 files. This directly violates the "zero [Unresolved file #N]" success criterion if not addressed. Phase 15 characterized this as query-specificity, not indexing failure — but the distinction matters less than the remediation plan.

**Provider synthesis:**
- **OpenAI:** Full per-doc verification + store-sync targeted repair; downgrade_to_failed() for persistent non-searchable; tolerable only if remediated automatically
- **Gemini:** Async monitoring thread checking files stuck in processing beyond P95+buffer; trigger store-sync for mismatches
- **Perplexity:** Async silent failure detector; retry policy with 4-hour deadline; target <0.1% final silent failure rate; the 5% baseline needs root cause investigation pre-Phase 16

**Proposed implementation decision:**
- After full upload, run `store-sync` targeted pass (per Phase 15 contract)
- Files still non-searchable after store-sync → `downgrade_to_failed()` → `retry_failed_file()` for a second upload pass
- Second pass clears the query-specificity failures (confirmed pattern from Phase 15)
- Success criterion: zero non-indexed files after retry pass, not zero failures during first pass
- check_stability.py Assertion 7 --sample-count 20 for Phase 16 stability checks (up from 5)

**Confidence:** ✅ All 3 providers agree remediation loop is required

---

### ✅ 3. TUI-09: top_k, Rank Display, and Citation Count (Consensus)

**What needs to be decided:**
How `top_k=20` maps to displayed results (chunks vs. files), how rank position is calculated when multiple chunks come from the same file, and how scroll hints are triggered.

**Why it's ambiguous:**
Gemini File Search returns `grounding_chunks` (passages), not documents. `top_k=20` means up to 20 chunks — which may be fewer than 20 unique files. The rank position per citation (per ROADMAP: "grounding_chunks is ordered by relevance, index 0 = most relevant") is chunk-level, not file-level.

**Provider synthesis:**
- **OpenAI:** Display `DocRank=N, Citation M/K` per chunk; group chunks by file for results list; deduplicate by file; show best rank + chunk count per file
- **Gemini:** Group by file; display minimum rank (best chunk position) + citation count (total chunks for that file); `top_k=20` is chunks, UI list < 20 after grouping
- **Perplexity:** Custom `SearchResultItem` widget showing rank + citation_count; scroll hints when results exceed visible area

**Proposed implementation decision:**
- `GeminiFileSearchClient.query()` adds `top_k=20` parameter (already specified in TUI-09)
- `--top-k N` CLI flag as override
- TUI displays chunks individually (not grouped by file) — rank = chunk index (0-based → display as 1-based)
- Each citation shows: rank (e.g., "3 / 20"), file title, snippet
- "20 citations retrieved" banner at top of results pane
- Scroll hint ("↑/↓ to scroll, PgUp/PgDn") appears when citations exceed visible viewport height (detect via VerticalScroll's `scroll_y` threshold or total height > viewport)

**Confidence:** ✅ All 3 providers agree on chunk-based ranking; display logic needs one concrete decision

---

### ✅ 4. Temporal Stability Protocol at 1,748-File Scale (Consensus)

**What needs to be decided:**
Whether the existing T=0/T+4h/T+24h/T+36h protocol and 7-assertion check_stability.py instrument are sufficient at full scale, or if thresholds/sample sizes need adjustment.

**Why it's ambiguous:**
Phase 12's temporal protocol was validated at 50 files. At 34.96x scale, Assertion 7's 5-file sample provides weaker statistical confidence. The T=0 stability check may also need to occur after a cooldown window (import-to-searchable lag affects immediate T=0 results).

**Provider synthesis:**
- **OpenAI:** Stratified 200-file sample (or 10%) for stability; "0 failures" budget; T+36h as final gate
- **Gemini:** N=50 random + 5 most recently modified as Assertion 7 sample; same T=0/T+4h/T+24h/T+36h cadence
- **Perplexity:** Explicit temporal checkpoints with drift detection (P95 latency ≤1.5x baseline, failure rate ≤+2pp from baseline)

**Proposed implementation decision:**
- Increase Assertion 7 --sample-count to 20 for Phase 16 (from default 5)
- Run T=0 check_stability.py **after** a 60-second cooldown following upload completion (allows import-to-searchable lag to resolve)
- Keep existing tolerance: max(1, N//5) misses per Phase 15 design (4/20 = 4 miss tolerance)
- Same T+4h/T+24h/T+36h cadence with fresh session each time (Phase 12 temporal protocol)
- STABLE = 7 assertions pass; count invariant = ~1,748 ± scanner-derived exact count

**Confidence:** ✅ All 3 providers agree sample size needs to increase for scale

---

### ⚠️ 5. store-sync Timing and Orphan Prevention During Upload (Recommended)

**What needs to be decided:**
Whether store-sync should be disabled during the upload run, and when the first post-upload store-sync should be triggered.

**Why it's ambiguous:**
If store-sync runs concurrently with the upload, it may flag in-progress files as orphans or cause state thrashing. Phase 15 established "targeted post-run" as the store-sync role, but doesn't specify the exact timing relative to upload completion.

**Provider synthesis:**
- **Gemini:** Disable automated store-sync during active upload; run manually after upload concludes
- **Perplexity:** Store-sync should reconcile after batch; test pagination handling for ~2,000 files (not yet tested at Phase 12 scale)

**Proposed implementation decision:**
- No automated store-sync during upload (Phase 15 contract: targeted post-run)
- Sequence: upload completes → 60s cooldown → check_stability (T=0) → store-sync dry-run → store-sync actual if orphans found → re-run check_stability → proceed to T+4h
- test `list_store_documents()` pagination at full scale before running (1,748 → ~2,000 documents, may need page iteration)

**Confidence:** ⚠️ 2 providers flagged; consistent with Phase 15 store-sync contract

---

### ⚠️ 6. Resume Capability for Interrupted Upload (Recommended)

**What needs to be decided:**
Whether the current FSM + SQLite design provides sufficient resume capability for a multi-hour upload interrupted mid-run.

**Why it's ambiguous:**
A 2-4 hour upload has non-trivial probability of interruption. The FSM stores per-file state in SQLite — but the exact behavior on restart needs to be confirmed: do `uploading`/`processing` files get recovered or re-uploaded?

**Provider synthesis:**
- **Gemini:** Auto-skip `indexed` files on restart; auto-reset `processing` files via RecoveryCrawler
- **Perplexity:** File-level SQLite checkpointing already provides resume; just re-run the same command; RecoveryCrawler handles stuck-state recovery

**Proposed implementation decision:**
The FSM already provides this via RecoveryCrawler + existing state tracking:
- `indexed` files: skipped by FSM guard (gemini_state guard in transition_to_uploading)
- `uploading`/`processing` files: recovered by RecoveryCrawler at startup
- `failed` files: skipped unless `--retry-failed` flag passed
- Simply re-running `objlib fsm-upload` resumes correctly — no additional checkpointing needed
- Confirm RecoveryCrawler is called at startup of 16-01 execution script

**Confidence:** ⚠️ 2 providers flagged; FSM design already handles this per Phase 10/12

---

### ⚠️ 7. Assertion 7 Sampling Strategy at Scale (Recommended)

**What needs to be decided:**
Whether to increase the default --sample-count and whether stratified sampling (by folder/year/course) provides better coverage than pure random sampling.

**Why it's ambiguous:**
At 1,748 files, the existing 5-file random sample provides only ~0.29% coverage. The 5% silent failure rate means a 5-file sample may have a ~77% chance of missing all silent failures if they're randomly distributed.

**Provider synthesis:**
- **Gemini:** N=50 random + 5 most recently modified; statistical sampling approach
- **Perplexity:** Stratified by file type/folder for better coverage

**Proposed implementation decision:**
- Increase to --sample-count 20 for Phase 16 stability checks (from default 5)
- Keep pure random sampling (stratified adds complexity without clear benefit given query-specificity is the failure mode, not folder-based)
- Existing tolerance max(1, N//5) = 4 misses on 20 samples (matches known 5-20% query-specificity gap from Phase 15)
- No change to check_stability.py code — just pass `--sample-count 20` in Phase 16

**Confidence:** ⚠️ 2 providers flagged; sample size increase is clearly warranted

---

### 🔍 8. Phase 07-07 TUI Smoke Test Structure (Needs Clarification)

**What needs to be decided:**
Whether Phase 07-07 is an automated test suite or a structured manual walkthrough, and what specific assertions it must make.

**Why it's ambiguous:**
Phase 07-07 was deferred from v1.0 and incorporated as plan 16-03. Its original scope (TUI integration smoke test against full corpus) was designed before TUI-09 requirements were added.

**Provider synthesis:**
- **Perplexity:** Automated Textual pilot tests + manual visual verification; specific assertions: render, search execution, result rendering, scroll behavior, error handling

**Proposed implementation decision:**
- Phase 07-07 is a structured manual walkthrough (TUI is interactive; full automation adds significant test infrastructure cost not justified for personal-use tool)
- 5+ diverse search queries run manually in TUI, results recorded verbatim (matches Phase 12 TUI validation protocol)
- Specific assertions: (1) search returns results, (2) no `[Unresolved file #N]` in any result, (3) citations show rank + count (TUI-09), (4) scroll works beyond visible area, (5) error notification on failed search does not crash TUI
- Canon.json updated to reflect TUI module after 07-07 passes

**Confidence:** 🔍 1 provider detailed; approach matches existing project validation patterns

---

### 🔍 9. Upload Scope: Exact File Enumeration (Needs Clarification)

**What needs to be decided:**
Whether the scanner's existing enumeration logic matches the "~1,748 files" expectation, and whether edge cases (hidden files, non-.txt, etc.) will cause a count mismatch.

**Why it's ambiguous:**
PROJECT.md says "1,749 text files" but success criteria says "~1,748". The scanner is already built and has been operating since v1.0.

**Provider synthesis:**
- **OpenAI:** Define manifest-driven scope; exclude hidden, `.DS_Store`, zero-byte files

**Proposed implementation decision:**
The scanner and database already define the scope (Phase 1, Phase 5 incremental updates). The "~" in "~1,748" acknowledges that the exact count is whatever the scanner finds. Run `objlib status` at the start of 16-01 to confirm the exact UNTRACKED count and record it as the denominator for success criteria #1. The scanner already excludes non-.txt files (v1 constraint).

**Confidence:** 🔍 1 provider flagged; existing scanner handles this

---

## Summary: Decision Checklist

Before planning, confirm:

**Tier 1 (Blocking):**
- [ ] 429 retry behavior: retry-not-fail for transient errors (GA-1)
- [ ] Silent failure remediation loop: store-sync → downgrade_to_failed → retry pass (GA-2)
- [ ] TUI-09 chunk-level rank display: rank = chunk index + 1 (GA-3)
- [ ] Assertion 7 sample count: 20 for Phase 16 checks (GA-4)

**Tier 2 (Important):**
- [ ] store-sync timing: after upload + 60s cooldown, before T=0 check (GA-5)
- [ ] Resume: confirm RecoveryCrawler called at startup of 16-01 (GA-6)

**Tier 3 (Polish):**
- [ ] Phase 07-07: structured manual walkthrough, not automated test suite (GA-8)
- [ ] File count: record exact scanner count at start of 16-01 as denominator (GA-9)

---

*Multi-provider synthesis by: OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research*
*Generated: 2026-02-23*
