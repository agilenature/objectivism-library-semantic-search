# CLARIFICATIONS-NEEDED.md

## Phase 6: AI-Powered Metadata Enhancement — Stakeholder Decisions Required

**Generated:** 2026-02-16
**Mode:** Two-Wave Approach (Discovery → Production)
**Source:** Multi-provider synthesis (OpenAI GPT-5.2, Gemini Pro)

---

## Decision Summary

**Phase 6 uses a two-wave approach:**
- **Wave 1:** Preliminary prompt discovery using agent teams (20-50 test files, ~$20-30)
- **Wave 2:** Production processing with validated approach (446-476 files, ~$110-164)

**Total questions:** 19 (7 Wave 1 + 12 Wave 2)
**Priority:** Wave 1 decisions are blocking and must be answered first

---

## WAVE 1: Preliminary Prompt Discovery (Answer First)

These decisions are required before Wave 1 execution begins. Wave 1 validates the approach before processing all 496 files.

---

### 🚨 W1.Q1: Credit Exhaustion Handling (CRITICAL - Stakeholder Requirement)

**Question:** How should the system behave when Mixtral API credits run out during Wave 1 processing?

**Why it matters:** Wave 1 runs parallel agents testing 3 prompt strategies. If credits exhaust mid-batch, need clean pause/resume to preserve work and enable funding.

**Your stated requirement:**
> "At some point we are going to run out of credits for Mistral. I want to get consulted. You raise the issue and I get consulted so I can have the chance, while you stop the process, to fund Mistral. I can let you know it is funded so you can continue."

**Options identified by providers:**

**A. Atomic Checkpoint with Stakeholder Consultation (Recommended by Gemini + Your Requirement)**
- Save results to SQLite immediately after each file
- On credit error (402), serialize checkpoint to `wave1_checkpoint.json`
- Display clear notification with funding instructions
- Clean exit (no corruption)
- Resume command: `objlib wave1 --resume wave1_checkpoint.json`
- _(Proposed by: Gemini, matches stakeholder requirement)_

**B. Auto-Retry with Exponential Backoff**
- Retry failed requests with increasing delays
- Eventually timeout after N retries
- Risk: Wastes API calls if credits truly exhausted
- _(Not recommended for credit exhaustion)_

**C. Pre-flight Credit Check Only**
- Check credits before starting Wave 1
- No mid-batch handling
- Risk: Credits could still run out during execution
- _(Proposed by: No provider, incomplete solution)_

**Synthesis recommendation:** ✅ **Option A (Atomic Checkpoint with Consultation)**
- Matches your explicit requirement
- Preserves all work (no re-processing)
- Clear stakeholder notification
- Deterministic resume

**Sub-questions:**
- Should system also pause on rate limits (429) for consultation, or auto-retry with backoff?
- Email notification if running unattended?
- Pre-flight credit check before starting (in addition to checkpoint)?

---

### ⚠️ W1.Q2: Agent Team Structure

**Question:** How should "agent teams" be organized for prompt discovery? Competitive strategies or collaborative chains?

**Why it matters:** With 3 concurrent request limit and 60 req/min, must decide if "team" means:
- Collaborative chain (Generator → Critic → Verifier) = 3 calls per file
- Competitive strategies (Strategy A, B, C process same file) = direct comparison

**Options identified by providers:**

**A. Competitive Parallelism (Recommended by Gemini)**
- 3 distinct "Strategy Lanes" (A, B, C)
- Each lane processes same 20 test files
- Direct A/B/C comparison on identical content
- Maximizes concurrency limit (3 threads)
- Example: File 1 processed by Lane A, B, C simultaneously
- _(Proposed by: Gemini)_

**B. Collaborative Chains with Sequential Processing**
- Each file goes through Generator → Critic → Verifier
- Process 1 file at a time (3 sequential calls)
- Slower but potentially higher quality per file
- Risk: Can only test 1 prompt variation in time budget
- _(Not recommended for discovery phase)_

**C. Hybrid: Competitive Strategies with Self-Correction**
- 3 competitive strategies (primary)
- Optional: Each strategy runs self-correction pass
- Doubles API calls (6 concurrent needed)
- Exceeds concurrency limit
- _(Too expensive for Wave 1)_

**Synthesis recommendation:** ✅ **Option A (Competitive Parallelism)**
- Discovery phase needs comparison, not collaboration
- Direct A/B/C comparison on same content
- Fits within 3-concurrent constraint
- Can test multiple prompt variations within budget

**Sub-questions:**
- Should each lane have independent error tracking?
- Allow one lane to continue if another fails?

---

### ⚠️ W1.Q3: Prompt Variation Strategy

**Question:** What specific prompt variations should the 3 strategy lanes test?

**Why it matters:** Need to isolate variables that drive quality in 4-tier extraction. Random prompt changes are inefficient.

**Options identified by providers:**

**A. Structural Archetypes: Minimalist, Teacher, Reasoner (Recommended by Gemini)**
- **Lane A (Minimalist):** Zero-shot, strict JSON schema, temp=0.1, focus on speed/cost
- **Lane B (Teacher):** One-shot with perfect example, temp=0.3, focus on structure adherence
- **Lane C (Reasoner):** Chain-of-Thought instructions, temp=0.5, focus on accuracy/nuance
- Tests fundamentally different prompting approaches
- _(Proposed by: Gemini)_

**B. Temperature Variations Only**
- Same prompt structure, vary temperature (0.1, 0.5, 0.9)
- Isolates temperature impact
- Risk: Misses structural improvements
- _(Not recommended, too narrow)_

**C. Instruction Granularity Variations**
- Lane A: Minimal instructions ("Extract metadata as JSON")
- Lane B: Detailed instructions (explicit tier definitions)
- Lane C: Ultra-detailed with negative examples
- Tests instruction verbosity
- _(Proposed by: OpenAI synthesis)_

**Synthesis recommendation:** ✅ **Option A (Structural Archetypes)**
- Tests fundamentally different approaches
- Each archetype has clear hypothesis
- Covers speed/quality trade-off spectrum
- Clear winner or hybrid combination

**Sub-questions:**
- Should we test temperature variations within each archetype? (9 combinations)
- Include negative examples ("what NOT to do") in any lane?

---

### ⚠️ W1.Q4: Test File Selection Methodology

**Question:** How to select 20-50 representative test files from 496 unknowns?

**Why it matters:** Random selection might pick all tiny files or all massive transcripts, skewing prompt performance data.

**Options identified by providers:**

**A. Stratified Sampling by File Size (Recommended by Gemini)**
- Scan all 496 files for size distribution
- Select:
  - 5 Small files (<5KB)
  - 5 Medium files (5-20KB)
  - 5 Large files (>20KB)
  - 5 Edge cases (conflicts, unusual structure)
- Total: 20 files for primary sprint
- Reserve 30 more for Wave 1.5 if needed
- _(Proposed by: Gemini)_

**B. Random Sampling**
- Pick 20 files randomly
- Simple, unbiased
- Risk: Might miss edge cases or size extremes
- _(Not recommended, insufficient control)_

**C. Manual Curation**
- Human selects 20 representative files
- Ensures coverage of known difficult cases
- Time-consuming, requires domain knowledge
- _(Too expensive for Wave 1)_

**D. Stratified by Existing Partial Metadata**
- Select files with different partial metadata patterns
- Example: 5 with year, 5 with topic, 5 with neither
- Tests metadata integration scenarios
- _(Proposed by: OpenAI synthesis)_

**Synthesis recommendation:** ✅ **Option A (Stratified by File Size)**
- Balances size distribution
- Includes edge cases explicitly
- Programmatic (no manual curation)
- Extensible to Wave 1.5

**Sub-questions:**
- Exclude known empty or binary files before sampling?
- Should "edge cases" prioritize files with existing filename-derived metadata?

---

### ⚠️ W1.Q5: Ground Truth Validation Methodology

**Question:** How to determine which prompt strategy "won" without pre-existing ground truth?

**Why it matters:** Cannot automate verification of prompt discovery. Need objective measurement of quality.

**Options identified by providers:**

**A. Human-in-the-Loop with Edit Distance Metric (Recommended by Gemini)**
- Generate side-by-side HTML/CSV report for 20 test files
- Human reviewer scores each strategy's output
- Metric: Edit Distance (0=Perfect to 5=Unusable) per tier
- Aggregate: Mean edit distance per strategy
- Winner: Lowest mean edit distance, or hybrid combining best elements
- _(Proposed by: Gemini)_

**B. LLM Judge (GPT-4o as Grader)**
- Use stronger model to evaluate outputs
- Faster than human review
- Risk: Judge might hallucinate quality scores
- Budget impact: Additional API costs
- _(Proposed by: Gemini with caveats)_

**C. Automated Metrics Only (No Human Review)**
- Structural validity (JSON compliance)
- Vocabulary adherence (controlled tags)
- Completeness (all tiers present)
- Risk: Misses semantic quality issues
- _(Not sufficient for discovery)_

**Synthesis recommendation:** ✅ **Option A (Human-in-the-Loop with Edit Distance)**
- Discovery phase needs human validation
- Edit distance is objective metric
- 20 files is manageable review workload (~30-45 mins)
- Establishes ground truth for Wave 2

**Sub-questions:**
- Use GPT-4o as judge to save time, or budget constraint?
- Need inter-rater reliability (multiple reviewers)?
- How to weight tiers in edit distance (Tier 1-2 errors worse than Tier 3-4)?

---

### ⚠️ W1.Q6: Confidence Calibration Testing

**Question:** How to measure whether Mixtral's confidence scores correlate with actual quality?

**Why it matters:** Wave 2 uses 0.80 confidence threshold for auto-approval. Need to validate that self-reported confidence is reliable.

**Options identified by providers:**

**A. Self-Reported Confidence with Calibration Analysis (Recommended by Gemini)**
- Include `confidence_score` (0.0-1.0) in JSON schema
- In Wave 1, compare self-reported confidence vs actual quality (edit distance)
- Calculate Pearson correlation
- If correlation >0.7: Self-reported confidence reliable → Use in Wave 2
- If correlation <0.5: Need heuristic rules instead
- _(Proposed by: Gemini)_

**B. Secondary Verifier Agent Scores Output**
- Run separate LLM to score quality
- High cost (doubles API calls)
- More objective than self-report
- _(Too expensive for Wave 1)_

**C. Heuristic Confidence Rules**
- Base confidence on: file length, tier completeness, parsing success
- No model involvement
- Less accurate, but deterministic
- _(Fallback if self-report fails)_

**Synthesis recommendation:** ✅ **Option A (Self-Reported with Calibration)**
- Test self-report reliability in Wave 1
- Low cost (single field in response)
- Data-driven decision for Wave 2
- Fallback to heuristics if correlation poor

**Sub-questions:**
- Should confidence be tier-specific (4 scores) or composite (1 score)?
- Include "reasoning" field asking model to explain confidence rating?

---

### ⚠️ W1.Q7: Wave 2 Transition Criteria

**Question:** What criteria trigger transition from Wave 1 to Wave 2? When is "good enough"?

**Why it matters:** Might find no single strategy perfect, or all strategies fail quality gates. Need clear decision rules.

**Options identified by providers:**

**A. Quality Gates with Hybrid Template Generation (Recommended by Gemini)**
- Define pass/fail gates:
  - Tier 1 accuracy ≥ 90%
  - Tier 2 accuracy ≥ 85%
  - Confidence calibration ≥ 0.60
  - Cost per file ≤ $0.30
  - Mean edit distance ≤ 2.0
- If all gates pass: Proceed to Wave 2
- If split performance: Generate hybrid prompt (best of each strategy)
- If all fail: Trigger Wave 1.5 (re-discovery with focused experiments)
- _(Proposed by: Gemini)_

**B. Best Strategy Wins (No Hybrid)**
- Pick single strategy with highest score
- Simpler, but might miss optimization opportunities
- _(Not recommended, leaves value on table)_

**C. Manual Stakeholder Approval**
- Present results to stakeholder
- Stakeholder decides Wave 2 readiness
- Most conservative, but subjective
- _(Proposed by: Gemini as option)_

**Synthesis recommendation:** ✅ **Option A (Quality Gates with Hybrid)**
- Objective, data-driven criteria
- Allows hybrid prompt combining best elements
- Wave 1.5 safety net if all strategies fail
- Can add stakeholder approval as final check

**Sub-questions:**
- Should Wave 2 transition require stakeholder sign-off, or automatic if gates pass?
- What if cost gate fails but quality gates pass (expensive but accurate)?
- Maximum iterations of Wave 1.X before escalating to manual prompt engineering?

---

## WAVE 2: Production Processing (Answer During/After Wave 1)

These decisions can be informed by Wave 1 results and answered during Wave 1 execution or after Wave 1 completes.

**Note:** Wave 2 questions presented in summary form. Full details available in 06-CONTEXT.md (Gray Areas W2.1-W2.12).

---

### Tier 1: Blocking Decisions (Must Decide Before Wave 2 Execution)

**W2.Q1: Prompt Structure** - Use Wave 1 winner template, or combine approaches?
**W2.Q2: Response Parsing** - Two-phase parser (structured + regex fallback)?
**W2.Q3: Validation Strategy** - Hard fail for controlled tiers, soft warn for freeform?
**W2.Q4: Database Schema** - Hybrid approach (junction table + JSON columns)?

### Tier 2: Important Decisions (Should Decide Before Wave 2)

**W2.Q5: Context Window** - Adaptive chunking (head-tail windowing for long files)?
**W2.Q6: CLI Review Workflow** - Progressive disclosure with Rich panels?
**W2.Q7: Confidence Scoring** - Multi-dimensional weighted average (refined by Wave 1 calibration)?
**W2.Q8: Rate Limiting** - Asyncio with token bucket (3 concurrent, 60/min)?

### Tier 3: Polish Decisions (Can Defer to Wave 2 Execution)

**W2.Q9: Partial Extraction** - Accept partial (required tiers only) with status flag?
**W2.Q10: Prompt Versioning** - Semantic versioning with config hashing?
**W2.Q11: Security/Privacy** - Privacy-by-default (redact logs, chunking, opt-in debug)?
**W2.Q12: Incremental Updates** - Smart triggers (preserve approved, re-extract on change)?

**Synthesis Recommendations:** All Wave 2 questions have provider-recommended solutions documented in 06-CONTEXT.md. Can auto-generate YOLO answers or refine based on Wave 1 results.

---

## Next Steps

**Current Mode:** YOLO (auto-answer enabled)

The system will:

1. ✅ Generate CLARIFICATIONS-ANSWERED.md with balanced YOLO decisions
2. ⏭ Await stakeholder review before proceeding to planning
3. 📋 Wave 1 execution requires stakeholder decisions confirmed

**Note:** Wave 1 questions (W1.Q1-W1.Q7) are **blocking** and must be answered before Wave 1 can execute. Wave 2 questions can be answered during/after Wave 1 based on discovery results.

---

*Multi-provider synthesis: OpenAI GPT-5.2 + Gemini Pro*
*Generated: 2026-02-16*
*Mode: YOLO (auto-answer follows)*
