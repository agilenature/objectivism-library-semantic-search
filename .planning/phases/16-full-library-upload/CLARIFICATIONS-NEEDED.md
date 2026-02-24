# CLARIFICATIONS-NEEDED.md

## Phase 16: Full Library Upload — Stakeholder Decisions Required

**Generated:** 2026-02-23
**Mode:** Multi-provider synthesis (OpenAI, Gemini, Perplexity)
**Source:** 3 AI providers analyzed Phase 16 requirements

---

## Decision Summary

**Total questions:** 8
**Tier 1 (Blocking):** 4 questions — Must answer before planning
**Tier 2 (Important):** 2 questions — Should answer for quality
**Tier 3 (Polish):** 2 questions — Can defer to implementation

---

## Tier 1: Blocking Decisions

### Q1: How should the orchestrator handle 429 rate limit errors?

**Question:** Should 429 (rate limit) responses from the Gemini API cause a file to enter FAILED state, or should they trigger an in-place retry loop without a state transition?

**Why it matters:** At 1,748 files with c=10, sustained rate limit hits are likely. If 429s → FAILED, the retry pass after upload would need to re-upload potentially hundreds of files unnecessarily.

**Options:**

**A. Retry in-place (no FAILED transition)**
- Catch 429 inside the upload coroutine before any FSM transition
- Apply exponential backoff + jitter (base 1s, max 60s), max 5 attempts
- Only transition to FAILED if non-429 error or retry budget exhausted
- _(Proposed by: OpenAI, Gemini, Perplexity)_

**B. FAILED transition on all errors including 429**
- Let FSM transition to FAILED on any API error
- RecoveryCrawler + retry_failed_file() handles recovery
- Simpler FSM; retry logic centralized in recovery pass
- _(Proposed by: none — contra-indicated by all providers)_

**Synthesis recommendation:** ✅ **Option A — in-place retry for 429s**
- 429 is not a file-level failure; it's a client throttle signal
- Transitioning to FAILED inflates failed count and triggers unnecessary store-doc deletion

**Sub-questions:**
- What's the max retry count for 429s before escalating to FAILED? (Recommended: 5)
- Should the delay be jittered (random 0→delay) or deterministic (fixed delay)?

---

### Q2: What defines "success" for the upload — zero failures during upload, or zero non-indexed after remediation?

**Question:** Success criterion #1 says "all ~1,748 files have gemini_state='indexed'" — does this mean zero failures at any point during upload, or zero remaining non-indexed after the full remediation loop (store-sync + retry pass)?

**Why it matters:** A 5% silent failure rate at full scale = ~87 files that will temporarily fail before remediation. If "zero failures during upload" is required, Phase 16 will fail. If "zero non-indexed after remediation" is required, Phase 16 can pass.

**Options:**

**A. Zero non-indexed after complete remediation loop**
- Upload run → store-sync targeted pass → downgrade_to_failed → retry pass → final state check
- Phase gate: all files indexed after remediation, not after first upload pass
- Matches Phase 15 store-sync contract (targeted post-run for silent failures)
- _(Proposed by: OpenAI, Gemini, Perplexity)_

**B. Zero FAILED files at end of first upload pass**
- Store-sync and retry pass are optional cleanup, not required for gate
- Much stricter; would require silent failure investigation before Phase 16

**Synthesis recommendation:** ✅ **Option A — zero non-indexed after complete remediation loop**
- Consistent with Phase 15 store-sync contract
- Silent failure root cause is query-specificity (confirmed Phase 15); re-upload resolves it

---

### Q3: How should TUI-09 rank position be displayed — per chunk (raw API order) or per file (best chunk for each file)?

**Question:** `grounding_chunks` is ordered by relevance (chunk index = rank). When multiple chunks come from the same file, should the TUI show each chunk separately (e.g., chunks #3 and #7 are both from `file.txt`) or group chunks by file and show the best rank?

**Why it matters:** This determines whether the TUI shows up to 20 citation entries (one per chunk) or fewer entries grouped by file. TUI-09 requirement says "rank position per citation" — "citation" here means each individual chunk/grounding result.

**Options:**

**A. Show each chunk individually (flat list, up to 20 entries)**
- Rank = chunk position (1-based), shown as "3 / 20"
- Multiple citations from the same file appear separately
- User sees the full citation picture; consistent with ROADMAP's "grounding_chunks is ordered by relevance"
- _(Proposed by: OpenAI, Perplexity)_

**B. Group chunks by file (collapsed list, fewer entries)**
- Group chunks by file_id; show best rank + citation count per file
- e.g., "file.txt — Rank: 3 — 2 citations"
- More intuitive document-level view; fewer entries to scroll through
- _(Proposed by: Gemini)_

**Synthesis recommendation:** ⚠️ **Option A — flat list per chunk**
- ROADMAP explicitly says "each citation shows its retrieval rank" and "grounding_chunks ordered by relevance" — consistent with per-chunk display
- The existing citation model in the TUI appears to show individual chunks already
- Grouping is a future enhancement if users find the flat list noisy

**Sub-questions:**
- Should citations from the same file be visually grouped (indented) even in the flat list?

---

### Q4: What should Assertion 7's --sample-count be for Phase 16 stability checks?

**Question:** check_stability.py Assertion 7 currently defaults to 5 random indexed files. At 1,748 files, 5 samples = 0.29% coverage. Should the sample count be increased for Phase 16?

**Why it matters:** Statistical confidence in "searchability stable" is much weaker at 5/1748 than 5/90 (Phase 15 corpus). With 5% query-specificity gap, there's a high probability of missing systematic issues.

**Options:**

**A. Increase to 20 samples for Phase 16 checks**
- Coverage: 1.1% of corpus (from 5.6% on Phase 15 corpus)
- Existing tolerance max(1, 20//5) = 4 misses (matches 5-20% query-specificity gap)
- Moderate API cost for stability checks
- _(Proposed by: Gemini, Perplexity)_

**B. Keep at 5 samples (Phase 15 default)**
- Minimal API cost
- Very low coverage; may miss systematic regressions

**C. Increase to 50 samples**
- 2.9% coverage; stronger confidence
- Higher API cost per stability check

**Synthesis recommendation:** ⚠️ **Option A — 20 samples**
- Balances cost vs. coverage
- No code change required — just pass `--sample-count 20` in Phase 16 check commands

---

## Tier 2: Important Decisions

### Q5: When should store-sync run relative to upload completion?

**Question:** Should there be an explicit cooldown between upload completion and the T=0 store-sync + stability check, and should store-sync be run before or after the first check_stability call?

**Why it matters:** Import-to-searchable lag (P50=7.3s, P95=10.1s) means running check_stability immediately after upload will show Assertion 7 failures that resolve within seconds. store-sync running during the upload could cause false orphan detections.

**Options:**

**A. 60s cooldown → store-sync dry-run → check_stability → store-sync actual if needed**
- Allows all in-flight imports to become searchable
- store-sync confirms clean state before stability check
- _(Proposed by: Gemini, project Phase 15 contract)_

**B. check_stability immediately → then store-sync**
- Shows raw T=0 state including transient issues
- Less representative of actual steady-state

**Synthesis recommendation:** ⚠️ **Option A — 60s cooldown then store-sync then check_stability**
- Consistent with import-to-searchable lag characterization from Phase 15

---

### Q6: Should 16-01 explicitly call RecoveryCrawler at startup to handle any files stuck in uploading/processing?

**Question:** If the Phase 16 upload run is started on a DB that has files in `uploading` or `processing` state (e.g., from a partial prior run), should RecoveryCrawler be called automatically at startup or manually as a prerequisite step?

**Why it matters:** Without RecoveryCrawler at startup, stuck files would block correctly and need manual recovery, undermining the "just re-run to resume" design.

**Options:**

**A. RecoveryCrawler called automatically at start of upload command**
- Re-run is idempotent: stuck files are recovered before new uploads begin
- _(Proposed by: Gemini, Perplexity — consistent with Phase 10/12 design)_

**B. RecoveryCrawler is a separate prerequisite step**
- Manual `objlib recover` before `objlib fsm-upload`
- Explicit but adds friction to resume flow

**Synthesis recommendation:** ⚠️ **Option A — automatic at startup**
- RecoveryCrawler is already designed as a startup recovery mechanism (Phase 10)

---

## Tier 3: Polish Decisions

### Q7: Should Phase 07-07 TUI smoke test be automated or manual?

**Question:** Phase 07-07 is the deferred TUI integration smoke test. For Phase 16, should this be an automated Textual pilot test or a structured manual walkthrough?

**Options:**

**A. Structured manual walkthrough (5+ queries, recorded verbatim)**
- Consistent with existing Phase 12 TUI validation approach
- No test infrastructure required
- _(Proposed by: project pattern)_

**B. Automated Textual pilot tests**
- Reproducible; fast to re-run
- Significant infrastructure cost for personal-use tool
- _(Proposed by: Perplexity)_

**Synthesis recommendation:** 🔍 **Option A — structured manual walkthrough**
- Matches Phase 12 TUI validation approach
- Automation cost not justified for personal-use tool

---

### Q8: How should the exact file count denominator be established for success criterion #1?

**Question:** Success criterion #1 requires "all ~1,748 files have gemini_state='indexed'". What is the exact denominator?

**Options:**

**A. Run `objlib status` at start of 16-01 to record exact UNTRACKED count**
- Scanner-derived count is the authoritative denominator
- Record in SUMMARY.md for success criterion verification
- _(Proposed by: project context — scanner already defines scope)_

**B. Use hardcoded 1,748 as denominator**
- Simple but may drift from actual library state

**Synthesis recommendation:** 🔍 **Option A — record exact count at start**
- One `objlib status` command; record count in 16-01 SUMMARY.md

---

## Next Steps (YOLO Mode)

YOLO mode active — CLARIFICATIONS-ANSWERED.md will be auto-generated with synthesis recommendations.

---

*Multi-provider synthesis: OpenAI + Gemini + Perplexity*
*Generated: 2026-02-23*
*YOLO mode: Auto-answers in progress*
