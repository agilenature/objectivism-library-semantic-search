# CLARIFICATIONS-NEEDED.md

## Phase 15: Wave 7 — FSM Consistency and store-sync Contract

**Generated:** 2026-02-22
**Mode:** Multi-provider synthesis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research)
**Source:** 3 AI providers analyzed Phase 15 requirements

---

## Decision Summary

**Total questions:** 8
**Tier 1 (Blocking):** 4 — Must answer before planning
**Tier 2 (Important):** 3 — Should answer for quality
**Tier 3 (Polish):** 1 — Can defer to implementation

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: What does "searchable" mean operationally?

**Question:** Does "searchable" mean the document appears in list_store_documents(), or that a targeted semantic search query returns it?

**Why it matters:** The entire lag measurement is built on this definition. If we use list_store_documents(), we're measuring metadata ingestion lag (Phase 11 already proved this is fast). If we use actual search queries, we measure the full end-to-end pipeline including embedding generation and index integration — which may be substantially longer and is what users actually experience.

**Options:**

**A. list_store_documents() presence (fast, cheap)**
- Phase 11 measured this: P99=0.253s
- Does NOT verify embeddings or search functionality
- Insufficient for VLID-07 ("import-to-searchable lag")

**B. Targeted semantic search query returns target file (recommended)** ✅
- Uses same code path as end-user CLI search
- Verifies that the document is actually findable by meaning
- Per-file queries crafted from actual file content (user constraint)
- More expensive: requires 20 search API calls per measurement run
- _(Proposed by: all 3 providers)_

**Synthesis recommendation:** ✅ Option B. "Searchable" = targeted semantic query returns the target file.
Sub-decision: top-N threshold for "returns the file" → top-10 is standard; top-5 is stricter; top-1 is unrealistic for semantic search.

---

### Q2: What is T=0 for the lag measurement?

**Question:** When does the lag clock start — at upload API call, at FSM state transition, or elsewhere?

**Why it matters:** Different T=0 choices measure different things. The gap between them may be significant and should be characterized rather than hidden.

**Options:**

**A. When upload + import API returns HTTP 200/success (recommended)** ✅
- Clean, observable moment in code
- Represents "the system accepted the file" from the caller's perspective
- _(Proposed by: Gemini, Perplexity)_

**B. When FSM writes state PROCESSING**
- Captures FSM overhead but adds ~1-2ms
- Harder to extract from existing code
- _(Proposed by: OpenAI)_

**C. When upload is initiated (includes upload transfer time)**
- Measures full user-perceived latency including network transfer
- Would conflate upload speed with indexing speed
- _(Proposed by: Perplexity as T_import)_

**Synthesis recommendation:** ✅ Option A: T=0 = when upload+import API call returns success. Also capture T_listed (list_store_documents() first shows it) and T_searchable (search query hit) to characterize all three stages.

---

### Q3: When is a file declared a "silent failure" vs. "slow to index"?

**Question:** What is the hard timeout after which we declare a file permanently unsearchable (silent failure) rather than continuing to wait?

**Why it matters:** Without a hard cutoff, the measurement script can hang indefinitely. The cutoff also defines what goes into percentile stats vs. failure rate.

**Options:**

**A. 300 seconds (5 minutes)** ✅
- Reasonable for a vector indexing pipeline
- Phase 11 measured P99=0.253s for listing visibility — 300s gives 1200x headroom
- _(Proposed by: Gemini, Perplexity)_

**B. 600 seconds (10 minutes)**
- More conservative, lower false failure rate
- _(Proposed by: OpenAI)_

**C. 60 seconds**
- Faster measurement runs
- Risk of false failures if Gemini infrastructure has transient slowness

**Synthesis recommendation:** ✅ Option A: 300s timeout = silent failure. Counted separately from lag measurements; not included in percentile calculations. Report failure_rate alongside P50/P95/empirical max.

---

### Q4: When FSM says INDEXED but store-sync can't verify searchability, which wins?

**Question:** If check_stability.py finds a file is INDEXED in the DB but a targeted search query doesn't return it, what is the resolution?

**Why it matters:** This is the core FSM/store-sync contract. An undefined resolution policy means the system has no authoritative answer and divergence accumulates silently.

**Options:**

**A. Store-sync (empirical searchability) is authoritative** ✅
- INDEXED means "actually searchable," not just "upload succeeded"
- Downgrade FSM state to FAILED; existing retry_failed_file() handles recovery
- _(Proposed by: all 3 providers)_

**B. FSM is authoritative; store-sync files an alert only**
- Less disruptive to running system
- Risk: files remain INDEXED but actually unsearchable
- Violates the definition of done ("no [Unresolved file #N]")

**C. Quarantine state — neither FSM nor store-sync modifies state**
- Human review required
- Complex to implement; adds new FSM states
- _(Proposed by: OpenAI)_

**Synthesis recommendation:** ✅ Option A. Store-sync is authoritative. Resolution: log INCONSISTENT, downgrade to FAILED, let existing retry path handle re-upload. No new FSM states needed. No auto-deletes.

---

## Tier 2: Important Decisions (⚠️ Recommended)

### Q5: How to select 20 test files and craft per-file queries?

**Question:** Which 20 files from the Phase 12 50-file corpus, and how to construct queries that unambiguously prove those specific files are searchable?

**Why it matters:** Poorly designed queries either produce false positives (query matches multiple files) or false negatives (query fails to retrieve the target even when indexed). The per-file query design is the heart of the lag measurement.

**Options:**

**A. Select 20 files with philosophically-specific content, craft queries from unique terms** ✅
- Use actual Objectivist terminology that appears in specific files (unique in the corpus)
- Pre-validate: run each query against live store and confirm target file in results
- No modifications to files; uses existing content
- _(Proposed by: implicit from all 3 providers given the user's no-sentinel constraint)_

**B. Upload 20 fresh synthetic files with injected unique tokens**
- Maximally deterministic
- Requires separate upload; doesn't test the actual 50-file corpus
- Violates user constraint
- _(Proposed by: OpenAI, Gemini — but not applicable given user's constraint)_

**Synthesis recommendation:** ✅ Option A. Select 20 files from Phase 12 corpus, read first 500 chars of each, identify unique phrases/concept names, craft a query per file, pre-validate before measurement run.

---

### Q6: How to report P50/P95/P99 with n=20?

**Question:** P99 requires >100 samples to be statistically valid. VLID-07 requires P50/P95/P99. How to handle this tension?

**Options:**

**A. Report P50/P95/empirical max with explicit caveat (recommended)** ✅
- "P99/max (n=20, interpret as empirical bound, not statistical P99)"
- Nearest-rank method for P50 and P95
- Honest about sample size limitations
- _(Proposed by: OpenAI)_

**B. Report P50/P95 only; skip P99**
- Simpler; avoids misleading statistic
- Doesn't fully satisfy VLID-07 wording

**Synthesis recommendation:** ✅ Option A. Report all three with the caveat. VLID-07 is satisfied by clear documentation of the measurement.

---

### Q7: What is store-sync's ongoing role?

**Question:** Classify store-sync as: (a) routine after every upload, (b) scheduled periodic reconciliation, or (c) emergency-only.

**Why it matters:** The known blocker (orphan accumulation during retry pass) must be addressed. This decision determines the operational workflow going forward.

**Options:**

**A. Routine after every single file upload**
- Maximum safety; no orphan accumulation window
- High latency and API cost
- Overkill if silent failure rate is < 0.1%

**B. Scheduled + targeted post-run** ✅
- After each fsm-upload batch: run store-sync to clear retry-path orphans
- Comprehensive store-sync periodically (e.g., after batches >50 files)
- Escalate to routine-after-upload if failure rate > 1%
- _(Proposed by: OpenAI, Perplexity)_

**C. Emergency-only (triggered by check_stability.py UNSTABLE or operator)**
- Minimal cost; requires robust passive monitoring
- Risk: orphan window between emergency triggers

**Synthesis recommendation:** ✅ Option B. Scheduled + targeted post-run. Justified by Phase 15 measurements: if any silent failures are observed, reconsider. If failure rate is zero or near-zero, Option C is acceptable.

---

## Tier 3: Polish Decisions (🔍 Clarification)

### Q8: Does the temporal stability protocol require fresh Claude sessions?

**Question:** Phase 12 required fresh Claude sessions for T+4h/T+24h checks (HOSTILE distrust). Does Phase 15 require the same ceremony?

**Options:**

**A. Stateless standalone script, SKEPTICAL posture (recommended)** ✅
- check_stability.py is already stateless: new process, new DB connection, new API client
- SKEPTICAL distrust (not HOSTILE): script output is authoritative
- Claude reads and reports verbatim; no bias concern at SKEPTICAL level
- _(Proposed by: Gemini)_

**B. Fresh Claude sessions required (same as Phase 12)**
- Consistent with Phase 12 HOSTILE ceremony
- Overkill for SKEPTICAL-level distrust
- _(Proposed by: Perplexity)_

**Synthesis recommendation:** ✅ Option A. SKEPTICAL posture; standalone script is sufficient. Document: "T+4h and T+24h: run check_stability.py as standalone process; fresh session not required."

---

## Next Steps

Proceeding in YOLO mode — answers auto-generated in CLARIFICATIONS-ANSWERED.md.

---

*Multi-provider synthesis: OpenAI gpt-5.2 + Gemini Pro + Perplexity Sonar Deep Research*
*Generated: 2026-02-22*
