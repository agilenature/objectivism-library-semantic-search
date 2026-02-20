# CLARIFICATIONS-NEEDED.md

## Phase 11: Wave 3 — display_name Stability and Import Reliability

**Generated:** 2026-02-20
**Mode:** Multi-provider synthesis (Gemini Pro, Perplexity Sonar Deep Research)

---

## Decision Summary

**Total questions:** 6
**Tier 1 (Blocking):** 3 questions — Must decide before planning
**Tier 2 (Important):** 2 questions — Inform implementation
**Tier 3 (Polish):** 1 question — Document outcomes

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: What counts as "SDK source evidence" for display_name under HOSTILE distrust?

**Question:** Phase 11 SC1 says `display_name` must be confirmed via "SDK source inspection." Under HOSTILE distrust, does SDK inspection alone satisfy the gate, or is a round-trip API test also required?

**Why it matters:** SDK inspection proves the Python client *sends* the `display_name` parameter. It does not prove the Gemini API *preserves* it unmodified. If the API normalizes names and we only do SDK inspection, we ship broken citation display into Phase 12.

**Options:**

**A. SDK inspection only (find the source line, document it)**
- Satisfies the literal SC1 text
- Faster to implement
- Does NOT detect API-side normalization
- _(Proposed by: neither provider — both rejected this)_

**B. SDK inspection + round-trip verification (Recommended)**
- Find the SDK source line that serializes `display_name` into the HTTP request
- Import 10+ files with known display names, compare submitted vs returned values
- Detects normalization at the API level
- _(Proposed by: Gemini Pro, Perplexity)_

**Synthesis recommendation:** ✅ **Option B — SDK inspection + round-trip**
- HOSTILE distrust requires positive evidence, not absence of failure
- Round-trip takes minimal extra effort (10 test files, compare strings)
- If API normalizes names, we MUST know before Phase 12 or citations will break

**Sub-questions:**
- If round-trip reveals normalization, does SC1 pass (we now know the rule) or fail (display_name is not purely caller-controlled)?

---

### Q2: What is the precise start and stop point for import-to-visible lag measurement?

**Question:** SC2 says "time between `documents.import_()` returning success and the document appearing in `list_store_documents()`." Is "appearing in list_store_documents()" the correct stop point, or should we wait for a ACTIVE/INDEXED state within the API?

**Why it matters:** If we measure "time until listed" but the document is listed in a PROCESSING state (not yet searchable), the metric may undercount the real lag. But if we measure "time until searchable via semantic search," the measurement becomes much harder to operationalize.

**Options:**

**A. Stop when document appears in list_store_documents() (any state)**
- Operationally simple — just check for presence
- What the FSM actually needs (capture gemini_store_doc_id)
- May not reflect time-to-searchable
- _(Proposed by: project team based on FSM needs)_

**B. Stop when document has state == ACTIVE in list_store_documents()**
- More meaningful metric
- Requires the API to expose a state field per document
- Not confirmed whether list_store_documents() exposes state

**C. Stop when document returns in a semantic search query**
- Most meaningful for user impact
- Hardest to operationalize in a spike (query is non-deterministic)
- Too complex for Phase 11

**Synthesis recommendation:** ✅ **Option A — stop when document appears in list_store_documents()**
- The FSM transition is "store document is captured (has a doc ID)" not "store document is fully searchable"
- Phase 12 SC5 (`check_stability.py` STABLE at T=0) covers the searchability gate
- Note: if `list_store_documents()` exposes a state field, record it for context but don't block on it

---

### Q3: Which PROCESSING→INDEXED trigger strategy will the production FSM use?

**Question:** SC3 requires committing to one of three strategies. The spike must produce data and a justified decision.

**Why it matters:** This decision determines the Phase 12 upload pipeline architecture. Getting it wrong means redesigning after Phase 12 is underway.

**Options:**

**A. Polling list_store_documents() until visible, then transition (Recommended)**
- Background task polls with exponential backoff (0.5s → 10s max per interval)
- FSM stays in PROCESSING until polling confirms visibility
- Non-blocking: import returns immediately, polling happens asynchronously
- _(Proposed by: Gemini Pro "Batch Manager", Perplexity "Strategy B")_

**B. Trust API success + store-sync as eventual consistency check**
- Import success → immediately transition to INDEXED
- store-sync periodically reconciles
- Fails the HOSTILE-distrust gate (positive evidence required)
- _(Rejected by both providers)_

**C. VERIFYING intermediate FSM state**
- New state between PROCESSING and INDEXED
- FSM: PROCESSING → VERIFYING → INDEXED
- Structurally equivalent to Option A but with an extra state
- _(Mentioned but not recommended by providers)_

**Synthesis recommendation:** ✅ **Option A — non-blocking polling, no new FSM states**
- PROCESSING already covers the "waiting to confirm visibility" period
- Adding VERIFYING is unnecessary complexity when PROCESSING semantically covers it
- The lag measurement in Phase 11 must validate the 5-minute timeout is sufficient

**Sub-questions:**
- What should the polling interval strategy be? (proposed: 0.5s start, factor 1.5, max 10s)
- What is the absolute timeout before PROCESSING→FAILED? (proposed: 5 minutes)

---

## Tier 2: Important Decisions (⚠️ Recommended)

### Q4: What P99 lag threshold makes Phase 11 pass vs. fail?

**Question:** SC2 requires P50/P95/P99 to be characterized. What value of P99 constitutes an acceptable Phase 11 gate pass?

**Why it matters:** Without a threshold, Phase 11 has no gate.

**Options:**

**A. P99 ≤ 30 seconds**
- Conservative threshold (Gemini Pro's recommendation)
- May be too strict — we don't know actual P99 yet
- If P99 > 30s, Phase 11 fails before we even try Phase 12

**B. P99 ≤ 300 seconds (5 minutes) — gate passes; flag anything above 60s for monitoring**
- Generous threshold matching the polling timeout
- Phase 11 never blocks on measured lag alone
- 60s warning threshold still captures "bad behavior"
- _(Perplexity-aligned)_

**C. No threshold — just measure and document**
- Most honest approach (we don't know the right threshold pre-measurement)
- Phase 11 gate passes on empirical characterization, not on a target
- Phase 12 planning then sets the polling timeout based on actual data

**Synthesis recommendation:** ⚠️ **Option C for the gate; Option B for the polling timeout**
- Phase 11 passes as long as the measurement is complete and documented
- The polling timeout (5 minutes) is set based on known worst-case tolerance
- If P99 > 60s for small .txt files, that is documented as a risk for Phase 12

---

### Q5: How are PROCESSING state errors (API failure or timeout) handled?

**Question:** When the background polling loop detects a problem (API-reported failure or 5-minute timeout), what FSM transition fires and what is recorded?

**Why it matters:** This must be designed before Phase 11 code is written, even if it's a spike. The FSM cannot leave a file stuck in PROCESSING with no escape path.

**Options:**

**A. PROCESSING → FAILED (reuse Phase 10 FAILED state + RecoveryCrawler)**
- No new FSM states
- RecoveryCrawler on startup handles FAILED → UNTRACKED escape
- Consistent with Phase 10 design
- _(Proposed by: Gemini Pro, aligns with Phase 10 decisions)_

**B. New TIMEOUT state**
- Distinguishes "API said FAILED" from "we gave up polling"
- More observability
- More complexity; likely overkill for spike phase

**Synthesis recommendation:** ⚠️ **Option A — PROCESSING → FAILED, reuse RecoveryCrawler**
- Phase 10 designed the FAILED escape path specifically for this purpose
- RecoveryCrawler already handles FAILED → UNTRACKED
- Record error type in a field (e.g., `gemini_state_error`) for observability

---

## Tier 3: Polish (🔍 Needs Clarification)

### Q6: How should display_name normalization be handled if detected?

**Question:** If the round-trip test reveals the API normalizes display_name (e.g., lowercases, strips spaces), what is the remediation?

**Why it matters:** If our DB stores `"Sales Lecture - Week 03.txt"` but the store contains `"sales_lecture_-_week_03.txt"`, citation lookup will fail.

**Options:**

**A. Document the normalization rule; pre-apply in Phase 12 upload**
- Phase 12 uploads pre-normalize display_name before storing in DB
- DB and store are always consistent

**B. Use filename (not display_name) as the citation lookup key**
- More robust to normalization surprises
- Requires changes to citation lookup logic

**Synthesis recommendation:** 🔍 **Option A if normalization detected; no action if round-trip passes**
- This is a contingency — if SC1 passes (exact round-trip match), this is moot
- Document in Phase 11 report so Phase 12 knows what to expect

---

## Next Steps (YOLO Mode)

YOLO mode will auto-generate CLARIFICATIONS-ANSWERED.md with the synthesis recommendations above, then proceed to `/gsd:plan-phase 11`.

---

*Multi-provider synthesis: Gemini Pro + Perplexity Sonar Deep Research*
*Generated: 2026-02-20*
