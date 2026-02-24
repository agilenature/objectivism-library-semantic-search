# CONTEXT.md — Phase 15: Wave 7 — FSM Consistency and store-sync Contract

**Generated:** 2026-02-22
**Phase Goal:** Import-to-searchable lag is empirically characterized, and store-sync's ongoing role relative to the FSM is explicitly defined and documented.
**Synthesis Source:** Multi-provider AI analysis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research)

---

## Overview

Phase 15 has two plans:
- **15-01:** Import-to-searchable lag measurement (20 test imports, P50/P95/P99, targeted queries)
- **15-02:** store-sync contract definition, FSM/store-sync reconciliation policy, temporal stability verification

The core engineering challenge is the gap between "a document is listed in the store" and "a document is actually searchable via semantic query." All 3 providers independently identified this as the blocking gray area. The user has added a critical constraint: **Plan 15-01 must run targeted queries against the specific content of the 20 test files — not the default check_stability.py query — to verify actual searchability, not just listing.**

**Confidence markers:**
- ✅ **Consensus** — All 3 providers identified this as critical
- ⚠️ **Recommended** — 2 providers identified this as important
- 🔍 **Needs Clarification** — 1 provider identified, potentially important

---

## Gray Areas Identified

### ✅ 1. Definition of "Searchable" vs. "Listed" (Consensus)

**What needs to be decided:**
What "searchable" means technically for the lag measurement. list_store_documents() confirms metadata propagation, not embedding/index readiness.

**Why it's ambiguous:**
A document can appear in list_store_documents() before the embedding pipeline completes. The Gemini File Search indexing pipeline has three stages: (1) raw file stored, (2) chunked + embeddings generated, (3) vector index updated. Stage completion times differ and the API only reports "done" for stage 1/2. Stage 3 (index integration) is asynchronous and opaque.

**Provider synthesis:**
- **OpenAI:** "Searchable" = search returns the expected document in top-10 for a unique exact-quote query. Sentinel strings guarantee deterministic measurement.
- **Gemini:** "Searchable" = `models.generate_content` with File Search tool returns a unique UUID/token embedded in the test file. Propose a deterministic prompt: "Find the unique code in file [name] and return ONLY that code."
- **Perplexity:** Distinguish "direct assertion" queries (targeting specific terminology in the file) vs. "contextual discovery" queries (semantic equivalents). Both must succeed for full searchability confidence. "Done=true" from upload API reflects metadata ingestion, not embedding completion.

**Proposed implementation decision:**
"Searchable" = a targeted natural language query against the specific content of a test file returns that file among the results, using the same search path as the end-user CLI. We use the existing Phase 12 50-file corpus (select 20 files) and craft per-file queries from their actual content — unique phrases, titles, or key concepts from each file. This is the user-specified constraint: no sentinel injection, no generic queries.

**Open questions (answered in CLARIFICATIONS-ANSWERED.md):**
- Should "searchable" require top-1, top-5, or top-10 placement?
- Do we use CLI search path or raw API call?

---

### ✅ 2. Lag Measurement: Clock, Polling, and Timing Protocol (Consensus)

**What needs to be decided:**
Exact T=0 (clock start), polling strategy, max observation window, and whether to upload sequentially or concurrently.

**Why it's ambiguous:**
"Import completes" could mean: (a) upload API returns HTTP 200, (b) FSM transitions to PROCESSING, (c) operations.get() returns done=true, (d) list_store_documents() shows the doc. Each point measures something different.

**Provider synthesis:**
- **OpenAI:** T=0 = FSM writes state; sequential imports (c=2 or c=1) to avoid rate-limit confounding; exponential backoff polling (0.25s → 0.5s → 1s → 2s → 4s) with jitter; hard timeout 10 minutes.
- **Gemini:** T=0 = upload API completes. Sequential: upload File 1 → poll until searchable → record → upload File 2. Backoff: 1s → 2s → 4s → 8s.
- **Perplexity:** Three-phase timestamps: T_import (upload initiation), T_listed (first in list_store_documents()), T_searchable (first search query hit). Lag = T_searchable - T_import. Also capture T_listed to characterize the listing-vs-searchable gap.

**Proposed implementation decision:**
- T=0 = when upload + import API call returns success (or FSM transitions to PROCESSING)
- Sequential: upload one file, start polling for searchability, record T_searchable, then upload next
- Polling: 1s → 2s → 4s → 8s → 16s (cap at 30s intervals) with a 5-minute hard timeout
- Also record T_listed (when list_store_documents() first shows it) to characterize the listing gap
- Three timestamps per file: T_import, T_listed, T_searchable

**Open questions (answered in CLARIFICATIONS-ANSWERED.md):**
- Should T=0 be upload return or FSM state write?

---

### ✅ 3. Silent Failure Classification (Consensus)

**What needs to be decided:**
At what point a file is declared a "silent failure" vs. "slow to index," and how these are counted in percentile stats.

**Why it's ambiguous:**
Phase 11 measured P99=0.253s for list_store_documents() visibility, but searchability via semantic query may take longer. Without a hard cutoff, measurement scripts can hang indefinitely.

**Provider synthesis:**
- **OpenAI:** 10-minute timeout = silent failure; treat TIMEOUT as lag = timeout_seconds in percentile computation; report failure_rate separately.
- **Gemini:** 300s (5 min) hard timeout = silent failure category (separate from lag spike).
- **Perplexity:** Three failure types: (A) listed but never searchable, (B) searchable at T=0 but gone by T+4h/T+24h (regression), (C) partial (searchable for some queries, not others). Follow-up verification queries at T+5min, T+30min, T+2h post T_searchable to catch Type B.

**Proposed implementation decision:**
- 300s (5 min) hard timeout = silent failure (Type A)
- Silent failures excluded from percentile calculations but reported separately with failure_rate
- P50/P95 computed on successful measurements; empirical max also reported
- T+4h and T+24h stability checks catch Type B regressions (via check_stability.py temporal protocol)

---

### ✅ 4. FSM/store-sync Disagreement Resolution Policy (Consensus)

**What needs to be decided:**
When FSM says INDEXED but store-sync cannot verify searchability, which system is authoritative and what happens.

**Why it's ambiguous:**
FSM transitions to INDEXED when the Gemini import operation reports success — but "success" means the file was accepted, not that embeddings are complete and search queries will hit it. Store-sync performs empirical verification. If they disagree, an explicit policy is needed.

**Provider synthesis:**
- **OpenAI:** Six-tier triage: VERIFY_FAILED state, ORPHAN_REMOTE quarantine, REMOTE_MISSING re-import. No auto-deletes; require CLI confirmation.
- **Gemini:** "Gemini API is truth." If store-sync cannot verify: downgrade FSM to FAILED. Do not auto-re-upload. Log inconsistency. Report only, FSM handles retry.
- **Perplexity:** Store-sync overrides FSM state for critical systems. Options: (1) store-sync overrides → UNTRACKED, (2) alert-only, (3) auto-reset with backoff, (4) quarantine. For Phase 15: establish the policy before encountering real disagreements.

**Proposed implementation decision:**
- Store-sync (empirical searchability) is authoritative over FSM state
- Resolution: if FSM=INDEXED but targeted search query fails after 300s → log as INCONSISTENT; downgrade FSM to FAILED
- FAILED files are handled by existing retry_failed_file() path (Phase 12 design)
- No new FSM states needed; FAILED + retry is the existing escape path
- No auto-deletes; store-sync reports orphans, operator runs store-sync --no-dry-run to purge

---

### ⚠️ 5. Test File Selection and Query Design (Recommended)

**What needs to be decided:**
Which 20 files to use from the Phase 12 50-file corpus, and how to craft per-file queries that unambiguously verify searchability of those specific files.

**Why it's ambiguous:**
The user constraint prohibits sentinel injection and generic queries. We must use existing file content. Poorly chosen queries may match multiple files (ambiguous) or fail to match the target file even when it is indexed (false negative).

**Provider synthesis:**
- **OpenAI:** Select files with unique content; embed sentinel string (but user has disallowed this); alternatively, use existing unique phrases.
- **Gemini:** Synthetic files with UUID tokens — but since we use real corpus, adapt: find unique phrases in each file that don't appear elsewhere. "The query targets unique content in that specific file."
- **Perplexity:** "Direct assertion" queries (specific terminology from the document) paired with "contextual discovery" queries (semantic equivalents). Both must succeed for full confidence.

**Proposed implementation decision:**
- Select 20 files from Phase 12 corpus that have distinct, philosophically specific content
- For each file: read first 500 chars, extract a unique phrase or concept name (Objectivist-specific terminology tends to be highly unique)
- Craft a query: "What does [file] say about [unique concept/phrase]?" — this tests actual retrieval of specific content
- Pre-validate queries manually: run each query against existing indexed store, confirm the target file appears in results
- Document each file → query mapping in the lag measurement script

---

### ⚠️ 6. P50/P95/P99 with n=20 (Recommended)

**What needs to be decided:**
Whether P99 is meaningful with n=20, how to compute percentiles, and what to report.

**Why it's ambiguous:**
With only 20 measurements, P99 is not statistically valid (requires >100 samples). Phase 15 success criteria explicitly requires P99.

**Provider synthesis:**
- **OpenAI:** Use nearest-rank method; for P99 report "P95 + empirical max"; label it as "empirical max" not P99 to avoid false precision.
- **Perplexity:** Validate reproducibility by running the 50-file protocol twice, one week apart; stability = P50 within 10%, P95 within 15%.

**Proposed implementation decision:**
- Compute P50 and P95 using nearest-rank method on n=20
- Report empirical max labeled as "P99/max (n=20, interpret as empirical bound)"
- Acknowledge statistical limitations in documentation
- VLID-07 requirement says "at least 20 test imports" — treat this as the minimum; 20 is acceptable for Phase 15

---

### ⚠️ 7. store-sync Ongoing Role Classification (Recommended)

**What needs to be decided:**
Classify store-sync as: (a) routine after every upload, (b) scheduled periodic, or (c) emergency-only.

**Why it's ambiguous:**
The known blocker is orphan accumulation during fsm-upload retry pass. This argues for (a). But routine store-sync adds latency. Phase 15 measurements must inform this decision.

**Provider synthesis:**
- **OpenAI:** Scheduled + targeted post-run: lightweight targeted verifier after each fsm-upload run + full store-sync on schedule. Escalate to routine-after-upload only if failure rate > 1% or P95 > 60s.
- **Gemini:** Post-test cleanup only for measurement; store-sync at end of phase.
- **Perplexity:** Hybrid: lightweight routine (one targeted query per newly imported doc, ~100-200ms) + comprehensive scheduled store-sync outside peak hours.

**Proposed implementation decision:**
- Recommendation: **scheduled + targeted post-run** (not routine after every single file, not emergency-only)
- After each fsm-upload batch run: run store-sync to clear retry-path orphans (the known blocker)
- Periodic comprehensive store-sync: after any significant upload batch (>50 files)
- Emergency store-sync: when check_stability.py reports UNSTABLE
- Decision is justified by Phase 15 measurements: if silent failure rate > 0, escalate to routine

---

### 🔍 8. Temporal Stability Protocol for Phase 15 (Clarification Needed)

**What needs to be decided:**
Whether T+4h and T+24h checks require fresh Claude sessions (as Phase 12 required) or whether stateless standalone scripts suffice.

**Why it's ambiguous:**
Phase 12's fresh-session requirement was about Claude's memory bias during HOSTILE-distrust checks. Phase 15 is SKEPTICAL distrust (weaker). The protocol concern is different: ensuring check_stability.py produces verdicts from script output alone, not from Claude's memory.

**Provider synthesis:**
- **Gemini:** Stateless standalone script approach — check_stability.py spins up fresh, connects to existing DB, creates new API client, runs verification, exits. No 24h running process.
- **Perplexity:** Fresh sessions prevent state accumulation in language model inference and index cache warming effects.

**Proposed implementation decision:**
- check_stability.py is already stateless (Phase 8 design) — new process, new DB connection, new API client each run
- T+4h and T+24h checks: run check_stability.py as standalone process; fresh Claude session not required (SKEPTICAL distrust, not HOSTILE)
- Document: "SKEPTICAL posture — script output is authoritative; Claude reads and reports verbatim"

---

## Key User Constraint (from phase invocation)

> **Implication for Plan 15-01:** The lag measurement script must run targeted queries against the specific content of the 20 test files — not rely on the default check_stability.py query — to verify those files are actually searchable, not just listed.

This is a design constraint on the lag measurement script:
- It must NOT use check_stability.py's built-in query (which tests general search, not specific file searchability)
- It MUST craft per-file queries that target the actual content of each test file
- Per-file queries must be pre-validated: confirm they return the target file before using them in lag measurement

---

## Summary: Decision Checklist

**Tier 1 (Blocking):**
- [ ] Define "searchable" operationally (Q1) → targeted search query returns target file in top-N
- [ ] Define lag clock: T=0 and T_searchable (Q2) → upload success → first search hit
- [ ] Silent failure threshold (Q3) → 300s timeout
- [ ] FSM/store-sync resolution policy (Q4) → search is truth, downgrade to FAILED

**Tier 2 (Important):**
- [ ] Test file selection and per-file query design (Q5) → 20 files from Phase 12 corpus, unique-content queries
- [ ] P99 with n=20 (Q6) → report as empirical max
- [ ] store-sync role classification (Q7) → scheduled + targeted post-run

**Tier 3 (Polish):**
- [ ] Temporal stability ceremony requirements (Q8) → stateless script, SKEPTICAL posture

---

*Multi-provider synthesis by: OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research*
*Generated: 2026-02-22*
