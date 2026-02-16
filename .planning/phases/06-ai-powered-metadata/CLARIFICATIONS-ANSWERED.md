# CLARIFICATIONS-ANSWERED.md

## Phase 6: AI-Powered Metadata Enhancement — Stakeholder Decisions

**Generated:** 2026-02-16
**Mode:** YOLO (balanced strategy - auto-generated)
**Source:** Synthesis recommendations from multi-provider analysis

---

## Decision Summary

**Phase 6 uses a two-wave approach:**
- **Wave 1:** Preliminary prompt discovery (20 files, ~$20-30)
- **Wave 2:** Production processing (446-476 files, ~$110-164)

**Total decisions:** 19 (7 Wave 1 + 12 Wave 2)
**Strategy:** Auto-selected recommended options from synthesis

---

## WAVE 1: Preliminary Prompt Discovery — YOLO Decisions

### 🚨 W1.A1: Credit Exhaustion Handling

**YOLO DECISION:** ✅ **Option A - Atomic Checkpoint with Stakeholder Consultation**

**Rationale:**
- Confidence level: ✅ Consensus (Gemini + Stakeholder explicit requirement)
- Matches stakeholder's explicit requirement for consultation
- Preserves all work with checkpoint-based resume
- Clean notification and deterministic resume process
- Strategy: Required (stakeholder-mandated feature)

**Implementation:**
```python
# On credit exhaustion (HTTP 402):
1. Save checkpoint to wave1_checkpoint.json
2. Display funding notification with clear instructions
3. Clean exit (no corruption)
4. Resume: objlib wave1 --resume wave1_checkpoint.json
```

**Sub-decisions:**
- **Rate limit (429) handling:** Auto-retry with exponential backoff (don't pause for consultation)
- **Email notification:** Not needed (CLI displays clear message)
- **Pre-flight credit check:** Yes, add as supplementary check before starting

---

### ⚠️ W1.A2: Agent Team Structure

**YOLO DECISION:** ✅ **Option A - Competitive Parallelism**

**Rationale:**
- Confidence level: ✅ Recommended (Gemini)
- Discovery phase needs comparison, not collaboration
- Fits within 3-concurrent constraint
- Enables direct A/B/C testing on identical content
- Strategy: Balanced (pick recommended option)

**Implementation:**
- 3 distinct Strategy Lanes (Minimalist, Teacher, Reasoner)
- Each lane processes same 20 test files
- Parallel execution: File 1 → Lane A, B, C simultaneously
- Independent result tracking per lane

**Sub-decisions:**
- **Independent error tracking:** Yes, each lane tracks errors separately
- **Continue if one lane fails:** Yes, other lanes proceed (preserve partial results)

---

### ⚠️ W1.A3: Prompt Variation Strategy

**YOLO DECISION:** ✅ **Option A - Structural Archetypes (Minimalist, Teacher, Reasoner)**

**Rationale:**
- Confidence level: ✅ Recommended (Gemini)
- Tests fundamentally different prompting approaches
- Each archetype has clear hypothesis (speed vs structure vs accuracy)
- Covers full spectrum of trade-offs
- Strategy: Balanced (pick recommended option)

**Implementation:**
- **Lane A (Minimalist):** Zero-shot, JSON schema, temp=0.1, focus=speed/cost
- **Lane B (Teacher):** One-shot with example, temp=0.3, focus=structure
- **Lane C (Reasoner):** Chain-of-Thought, temp=0.5, focus=accuracy/nuance

**Sub-decisions:**
- **Temperature variations within archetypes:** No (avoid 9-combination complexity for Wave 1)
- **Negative examples:** No (add in Wave 1.5 if needed)

---

### ⚠️ W1.A4: Test File Selection Methodology

**YOLO DECISION:** ✅ **Option A - Stratified Sampling by File Size**

**Rationale:**
- Confidence level: ✅ Recommended (Gemini)
- Balances size distribution programmatically
- Explicitly includes edge cases
- Extensible to Wave 1.5 (30 files reserved)
- Strategy: Balanced (pick recommended option)

**Implementation:**
```python
def select_wave1_test_set():
    all_files = scan_496_unknowns()
    return {
        'small': random.sample([f for f in all_files if f.size < 5000], 5),
        'medium': random.sample([f for f in all_files if 5000 <= f.size <= 20000], 5),
        'large': random.sample([f for f in all_files if f.size > 20000], 5),
        'edge': random.sample([f for f in all_files if f.has_conflicts()], 5)
    }
# Total: 20 files
```

**Sub-decisions:**
- **Exclude empty/binary files:** Yes, pre-filter before sampling
- **Edge case priority:** Yes, prioritize files with partial filename-derived metadata (enables integration testing)

---

### ⚠️ W1.A5: Ground Truth Validation Methodology

**YOLO DECISION:** ✅ **Option A - Human-in-the-Loop with Edit Distance Metric**

**Rationale:**
- Confidence level: ✅ Recommended (Gemini)
- Discovery phase requires human validation baseline
- Edit distance is objective and measurable
- 20 files is manageable workload (~30-45 min review)
- Establishes ground truth for Wave 2 calibration
- Strategy: Balanced (pick recommended option)

**Implementation:**
```
1. Generate HTML/CSV report with side-by-side comparison
2. Human scores each strategy's output:
   - Edit Distance: 0 (Perfect) to 5 (Unusable) per tier
3. Aggregate: Mean edit distance per strategy across 20 files
4. Winner: Lowest mean edit distance, or hybrid combining best elements
```

**Sub-decisions:**
- **GPT-4o as judge:** No (budget constraint + avoid hallucinated scores)
- **Inter-rater reliability:** No (single reviewer sufficient for Wave 1)
- **Tier weighting in edit distance:** Yes, Tier 1-2 errors count double (controlled vocab is critical)

---

### ⚠️ W1.A6: Confidence Calibration Testing

**YOLO DECISION:** ✅ **Option A - Self-Reported Confidence with Calibration Analysis**

**Rationale:**
- Confidence level: ✅ Recommended (Gemini)
- Test reliability in Wave 1 with minimal cost
- Data-driven decision for Wave 2 threshold
- Fallback to heuristics if correlation <0.5
- Strategy: Balanced (pick recommended option)

**Implementation:**
```python
# In Wave 1:
1. Include confidence_score (0.0-1.0) in JSON schema
2. Compare self-reported confidence vs actual edit distance
3. Calculate Pearson correlation:
   - If r >0.7: Self-report reliable → Use in Wave 2
   - If 0.5 ≤ r ≤ 0.7: Use with caution, supplement with heuristics
   - If r <0.5: Fallback to heuristic confidence rules

# Heuristic fallback (if needed):
confidence = 0.5 * structural_validity +
             0.3 * tier_completeness +
             0.2 * file_length_score
```

**Sub-decisions:**
- **Tier-specific vs composite:** Composite single score (simplicity for Wave 1)
- **Include reasoning field:** No (avoid prompt bloat, test in Wave 1.5 if calibration fails)

---

### ⚠️ W1.A7: Wave 2 Transition Criteria

**YOLO DECISION:** ✅ **Option A - Quality Gates with Hybrid Template Generation**

**Rationale:**
- Confidence level: ✅ Recommended (Gemini)
- Objective, data-driven criteria
- Allows hybrid prompt optimization
- Wave 1.5 safety net if all strategies fail
- Strategy: Balanced (pick recommended option)

**Implementation:**
```python
# Quality gates (all must pass):
gates = {
    'tier1_accuracy': best_strategy['tier1_accuracy'] >= 0.90,
    'tier2_accuracy': best_strategy['tier2_accuracy'] >= 0.85,
    'confidence_calibration': best_strategy['correlation'] >= 0.60,
    'cost_per_file': best_strategy['avg_cost'] <= 0.30,
    'mean_edit_distance': best_strategy['edit_distance'] <= 2.0
}

if all(gates.values()):
    # Check for hybrid opportunities
    if split_performance_across_tiers():
        generate_hybrid_prompt()  # Combine best of each
    else:
        use_winner_prompt()
    proceed_to_wave2()
else:
    trigger_wave_1_5(failed_gates)  # Focused re-discovery
```

**Sub-decisions:**
- **Stakeholder sign-off for Wave 2:** Yes, present results for approval (final gate)
- **Cost vs quality trade-off:** If cost gate fails but quality gates pass, proceed (quality > cost)
- **Max Wave 1.X iterations:** 2 iterations (Wave 1.5, possibly Wave 1.6), then escalate to manual engineering

---

## WAVE 2: Production Processing — YOLO Decisions

### Tier 1: Blocking Decisions

---

### W2.A1: Prompt Structure

**YOLO DECISION:** ✅ **Use Wave 1 Winner Template (or Hybrid if Split Performance)**

**Rationale:**
- Informed by Wave 1 empirical results
- If single strategy dominates: Use that template
- If split performance: Hybrid combining best elements
- Strategy: Data-driven (deferred to Wave 1 results)

**Note:** Final prompt template determined by Wave 1 outcome. YOLO default if Wave 1 inconclusive: Use Lane B (Teacher) template with one-shot example.

---

### W2.A2: Response Parsing

**YOLO DECISION:** ✅ **Two-Phase Parser (Structured + Regex Fallback)**

**Rationale:**
- Confidence level: ⚠️ Recommended (OpenAI + Gemini)
- Handles Mistral magistral array format robustly
- Deterministic with fallback strategy
- Strategy: Balanced (pick recommended option)

**Implementation:**
```python
def parse_mistral_response(response):
    # Phase 1: Structured array parsing
    if isinstance(response, list):
        text_segments = [s['content'] for s in response if s.get('type') == 'text']
        try:
            return json.loads(''.join(text_segments))
        except JSONDecodeError:
            pass  # Fall through

    # Phase 2: Regex fallback (last JSON object)
    match = re.search(r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}(?!.*\{)', str(response), re.DOTALL)
    if match:
        return json.loads(match.group(0))

    # Phase 3: Failed
    raise ValueError("No valid JSON found")
```

---

### W2.A3: Validation Strategy

**YOLO DECISION:** ✅ **Two-Level Validation (Hard Fail + Soft Warnings)**

**Rationale:**
- Confidence level: ⚠️ Recommended (OpenAI + Gemini)
- Hard validation blocks on controlled tiers
- Soft validation warns on freeform quality
- Prevents false positives while ensuring quality
- Strategy: Balanced (pick recommended option)

**Implementation:**
```python
# Hard validation (reject + retry):
- category ∈ {7 allowed categories}
- difficulty ∈ {intro, intermediate, advanced}
- primary_topics: 3 ≤ len ≤ 8 and all ∈ controlled_vocab
- confidence_score: 0 ≤ value ≤ 1

# Soft validation (warn + needs_review):
- topic_aspects: 3 ≤ len ≤ 10 (warn if outside)
- semantic_description.summary: len ≥ 50 chars
- semantic_description.key_arguments: len ≥ 1

# Statuses:
- extracted: Passes all hard + soft
- needs_review: Passes hard, fails soft (still indexed)
- failed_validation: Fails hard → retry once
```

---

### W2.A4: Database Schema

**YOLO DECISION:** ✅ **Hybrid Schema (Junction Table + JSON Columns + Versioning)**

**Rationale:**
- Confidence level: ⚠️ Recommended (OpenAI + Gemini)
- Fast filtering on controlled vocabulary (junction)
- Flexible storage for freeform tiers (JSON)
- Versioning enables reproducibility
- Strategy: Balanced (pick recommended option)

**Implementation:** Use schema from 06-CONTEXT.md W2.4 (files table + file_metadata + file_primary_topics junction + optional FTS5)

---

### Tier 2: Important Decisions

---

### W2.A5: Context Window Strategy

**YOLO DECISION:** ✅ **Adaptive Chunking (Head-Tail Windowing)**

**Rationale:**
- Confidence level: ⚠️ Recommended (OpenAI + Gemini)
- Balances quality and cost
- Preserves intro + conclusion (critical for Tier 4)
- Strategy: Balanced (pick recommended option)

**Implementation:** Use adaptive strategy from 06-CONTEXT.md W2.5 (≤18K: full text; >18K: 70% start + 30% end)

---

### W2.A6: CLI Review Workflow

**YOLO DECISION:** ✅ **Progressive Disclosure with Rich Panels**

**Rationale:**
- Confidence level: ⚠️ Recommended (OpenAI + Gemini)
- Compact list view + detailed panels
- Auto-approve ≥0.85, interactive 0.70-0.84
- Strategy: Balanced (pick recommended option)

**Implementation:** Use Rich panel layout from 06-CONTEXT.md W2.6

---

### W2.A7: Confidence Scoring

**YOLO DECISION:** ✅ **Multi-Dimensional Weighted Average (Refined by Wave 1 Calibration)**

**Rationale:**
- Confidence level: 🔍 Identified by OpenAI
- Tier-specific weighting balances controlled vs freeform
- Wave 1 calibration informs final weights
- Strategy: Balanced (pick recommended option)

**Implementation:**
```python
# Weights (may be refined by Wave 1):
weighted = (tier1_conf * 0.30 +  # Category validity
            tier2_conf * 0.40 +  # Primary topics
            tier3_conf * 0.15 +  # Topic aspects
            tier4_conf * 0.15)   # Semantic description

# Apply penalties for validation failures
final = max(0.0, min(1.0, weighted - penalties))
```

---

### W2.A8: Rate Limiting

**YOLO DECISION:** ✅ **Asyncio with Token Bucket (3 concurrent, 60/min)**

**Rationale:**
- Confidence level: 🔍 Identified by OpenAI
- Precise rate control
- Exponential backoff on 429 errors
- Strategy: Balanced (pick recommended option)

**Implementation:** Use AsyncLimiter from 06-CONTEXT.md W2.8

---

### Tier 3: Polish Decisions

---

### W2.A9: Partial Extraction Handling

**YOLO DECISION:** ✅ **Accept Partial with Status Flags**

**Rationale:**
- Required tiers: category, difficulty, primary_topics
- Optional tiers: topic_aspects, semantic_description
- Missing optional → partial_extracted status
- Strategy: Pragmatic (preserve valid Tier 1-2 data)

---

### W2.A10: Prompt Versioning

**YOLO DECISION:** ✅ **Semantic Versioning with Config Hashing**

**Rationale:**
- Track: model, prompt_version, extraction_config_hash
- Keep history with is_current flag
- Enables A/B comparison
- Strategy: Best practice (recommended by OpenAI)

---

### W2.A11: Security/Privacy

**YOLO DECISION:** ✅ **Privacy-by-Default with Opt-in Debug**

**Rationale:**
- Use adaptive chunking (don't send full transcript)
- Redact transcript from logs
- Store only metadata JSON
- Optional --debug-store-raw flag
- Strategy: Conservative (privacy-first)

---

### W2.A12: Incremental Updates

**YOLO DECISION:** ✅ **Smart Triggers with Approved Preservation**

**Rationale:**
- Re-extract on: file content hash changed, prompt changed (if not approved)
- Preserve approved metadata
- Strategy: Balanced (avoid waste, respect approvals)

---

## Phase Completion Checklist

**Wave 1:**
- [ ] 20 test files selected via stratified sampling
- [ ] 3 strategy lanes configured (Minimalist, Teacher, Reasoner)
- [ ] Credit exhaustion checkpoint implemented
- [ ] Human review with edit distance scoring
- [ ] Confidence calibration analysis completed
- [ ] Quality gates evaluated
- [ ] Stakeholder approval for Wave 2 transition

**Wave 2:**
- [ ] Winner/hybrid prompt template finalized
- [ ] Two-phase response parser implemented
- [ ] Two-level validation rules configured
- [ ] Hybrid database schema deployed
- [ ] Adaptive chunking strategy applied
- [ ] CLI review workflow operational
- [ ] Confidence scoring algorithm calibrated
- [ ] Rate limiting enforced (3 concurrent, 60/min)
- [ ] Partial extraction handling enabled
- [ ] Prompt versioning tracking active
- [ ] Privacy-by-default configuration set
- [ ] Incremental update triggers configured

---

## Next Steps

1. ✅ CLARIFICATIONS-ANSWERED.md complete (YOLO mode)
2. ⏭ Proceed to `/gsd:plan-phase 6` to create execution plan
3. 📋 Wave 1 executes first, informs Wave 2 configuration

---

*Auto-generated by YOLO mode: Balanced strategy using synthesis recommendations*
*Human review recommended before final implementation*
*Generated: 2026-02-16*
