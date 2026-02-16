# CONTEXT.md — Phase 6: AI-Powered Metadata Enhancement

**Generated:** 2026-02-16
**Phase Goal:** Use AI to categorize and enrich metadata for 496 unknown-category files
**Synthesis Source:** Multi-provider AI analysis (OpenAI GPT-5.2, Gemini Pro)
**Note:** Perplexity provider unavailable (401 auth error) - synthesis based on 2 providers

---

## Overview

Phase 6 implements AI-powered metadata extraction using Mixtral (magistral-medium-latest) to process ~496 philosophical lecture transcripts with unknown categories. This phase uses a **4-tier hybrid metadata system** (DECIDED REQUIREMENT) that balances controlled vocabulary consistency with freeform nuance capture.

**Critical Context:** The metadata structure is ALREADY DECIDED and documented in `DECISION-HYBRID-TAXONOMY.md`. This synthesis focuses on gray areas in IMPLEMENTING that structure, not questioning it.

**Confidence markers:**
- ⚠️ **Recommended** — Both providers identified this as important (OpenAI + Gemini)
- 🔍 **Needs Clarification** — One provider identified, potentially important (OpenAI only)

---

## Phase Structure: Two-Wave Approach

Phase 6 is structured as **two sequential waves** to reduce risk and validate approach before full-scale processing:

### Wave 1: Preliminary Prompt & Verification Discovery (20-50 files)
**Goal:** Use agent teams to discover optimal prompt structure and verification process

**Approach:**
- Spawn 3 competitive strategy lanes (Minimalist, Teacher, Reasoner)
- Each strategy processes same 20 test files
- Human review validates quality and selects winning approach
- Output: Validated prompt template + verification rules for Wave 2

**Budget:** ~$20-30 for discovery
**Critical Feature:** **Pause/resume with stakeholder consultation when Mistral credits run out**

### Wave 2: Production Processing (446-476 remaining files)
**Goal:** Process remaining files using validated approach from Wave 1

**Approach:**
- Use winning prompt template from Wave 1
- Apply validated verification rules
- Full automation with confidence-based review workflow
- Cost-optimized with proven strategy

**Budget:** ~$110-164 (reduced from $130-194 due to Wave 1 optimizations)

---

## Wave 1 Gray Areas: Prompt Discovery with Agent Teams

### ⚠️ W1.1. Agent Team Structure & Concurrency (Recommended)

**What needs to be decided:**
How to map "Agent Teams" concept to hard constraints of 3 concurrent requests and 60 req/min Mixtral API limits. Should teams be collaborative chains (Generator → Critic → Verifier) or competitive strategies?

**Why it's ambiguous:**
Agent teams typically imply multi-agent collaboration per task. However, for discovery we need comparison. Running Generator+Critic chains (2 calls) for 3 strategies simultaneously hits concurrency limits immediately.

**Proposed implementation decision:**
- **Competitive Parallelism:** Treat "Teams" as **Competitive Strategies**, not collaborative chains
- **Configuration:** Define 3 distinct "Lanes" (Strategy A, B, C)
- **Execution:** Process in batches of 3 files. Lane A processes File 1, Lane B processes File 1, Lane C processes File 1
- **Rationale:** Direct A/B/C comparison on identical content while maximizing 3-thread concurrency

**Open questions:**
- Run "Self-Correction" pass (collaborative) within each strategy, or too expensive for Wave 1?
- Need separate error tracking per lane or unified?

---

### ⚠️ W1.2. Prompt Variation Strategy (Recommended)

**What needs to be decided:**
What specific variables to alter between Team A, B, and C to ensure meaningful discovery results.

**Why it's ambiguous:**
Randomly changing prompt wording is inefficient. Need to isolate variables to understand what drives quality in 4-tier extraction.

**Proposed implementation decision:**
Test 3 distinct structural archetypes:

**Team A (The Minimalist):**
- Zero-shot, strict JSON schema definition
- Temperature: 0.1
- Focus: Speed/Cost
- Hypothesis: Structured schema alone ensures compliance

**Team B (The Teacher):**
- One-shot (1 perfect example in context)
- Temperature: 0.3
- Focus: Structure adherence
- Hypothesis: Example-driven learning improves tier separation

**Team C (The Reasoner):**
- Chain-of-Thought instructions ("think about category before generating JSON")
- Temperature: 0.5
- Focus: Accuracy/Nuance
- Hypothesis: Explicit reasoning improves semantic_description quality

**Open questions:**
- Does added token cost of CoT justify potential accuracy gain for simple files?
- Should we test temperature variations within each archetype?
- Include negative examples (what NOT to do)?

---

### ⚠️ W1.3. Ground Truth & Validation Methodology (Recommended)

**What needs to be decided:**
How to determine which team "won" without pre-existing ground truth dataset.

**Why it's ambiguous:**
Cannot automate verification of prompt discovery entirely. If Team A says "category: course_transcript" and Team B says "category: qa_session", LLM judge might hallucinate winner. Need human verification to set baseline for Wave 2.

**Proposed implementation decision:**
- **Human-in-the-Loop (HITL) for Discovery:** Wave 1 is discovery phase - output side-by-side HTML/CSV report for human review
- **Metric:** "Edit Distance" - How much must human change output to make it perfect?
- **Scoring:** 0 (Perfect) to 5 (Unusable) per tier, per file
- **Aggregation:** Calculate mean edit distance per strategy across 20 files
- **Winner Selection:** Strategy with lowest mean edit distance, or hybrid combining best elements

**Open questions:**
- Trust stronger model (GPT-4o) as judge for 20 files to save human time, or violates budget constraints?
- Need inter-rater reliability if multiple humans review?
- How to weight tiers in edit distance (Tier 1-2 errors worse than Tier 3-4)?

---

### ⚠️ W1.4. Test File Selection Methodology (Recommended)

**What needs to be decided:**
How to programmatically select 20-50 "representative" files from 496 without analyzing content first.

**Why it's ambiguous:**
Random selection might pick 20 tiny files or 20 massive transcripts, skewing prompt performance data. Need balanced sample.

**Proposed implementation decision:**
**Stratified Sampling by File Characteristics:**

Scan file metadata (size, existing partial metadata) of 496 files:
- **5 Small files** (<5KB) - Likely brief Q&As or excerpts
- **5 Medium files** (5-20KB) - Typical lecture transcripts
- **5 Large files** (>20KB) - Dense philosophical treatises
- **5 Edge cases** - Files with partial metadata conflicts or unusual structure

**Total:** 20 files for primary sprint, reserve 30 more if Wave 1.5 needed

**Selection algorithm:**
```python
def select_test_set(all_files, n=20):
    bins = {
        'small': [f for f in all_files if f.size < 5000],
        'medium': [f for f in all_files if 5000 <= f.size <= 20000],
        'large': [f for f in all_files if f.size > 20000],
        'edge': [f for f in all_files if f.has_conflicts()]
    }
    return random.sample(bins['small'], 5) + \
           random.sample(bins['medium'], 5) + \
           random.sample(bins['large'], 5) + \
           random.sample(bins['edge'], 5)
```

**Open questions:**
- Exclude known empty or binary files before sampling?
- Should "edge cases" prioritize files with existing filename-derived metadata for comparison?
- Reserve specific difficult files (philosophy_comparison) or let random sampling handle?

---

### ⚠️ W1.5. Confidence Calibration Logic (Recommended)

**What needs to be decided:**
How to measure "Confidence" (0.80 threshold) when using Mixtral via API without direct access to logprobs.

**Why it's ambiguous:**
API logprobs not always available or intuitive to map to 0-1 "factuality" score. Model can be 99% confident in hallucination.

**Proposed implementation decision:**
**Self-Reported Confidence with Calibration Testing:**

1. **JSON Schema Field:** Include `confidence_score` (0.0-1.0) asking model to rate certainty based on source text ambiguity
2. **Calibration Analysis:** In Wave 1, compare self-reported confidence vs actual quality (edit distance from human review)
3. **Correlation Metric:** Calculate Pearson correlation between confidence and inverse edit distance
4. **Threshold Validation:** Test if 0.80 threshold meaningfully separates high/low quality outputs

**Expected outcomes:**
- If correlation >0.7: Self-reported confidence is reliable → Use in Wave 2
- If correlation <0.5: Self-reported confidence unreliable → Need heuristic rules (e.g., file length, tier completeness)

**Open questions:**
- Run secondary "Verifier" agent to score output? (Likely too expensive for Wave 1)
- Should confidence be tier-specific (4 scores) or composite (1 score)?
- Include "reasoning" field asking model to explain confidence rating?

---

### 🚨 W1.6. Credit Exhaustion & Pause/Resume with Stakeholder Consultation (CRITICAL)

**What needs to be decided:**
How script behaves when Mixtral credits run out mid-batch, and how to enable stakeholder consultation for funding before resuming.

**Why it's ambiguous:**
Standard scripts crash on API errors. With parallel processing, crash might corrupt result comparison. **Stakeholder requires consultation opportunity to fund Mistral before resuming.**

**Proposed implementation decision:**
**Atomic State Management with Consultation Workflow:**

**1. Atomic Transactions:**
- Save results to SQLite immediately after each file processing, not batch end
- Each lane (A/B/C) has independent checkpoint

**2. Error Detection:**
```python
def mixtral_call_with_credit_check(prompt, file_id, lane):
    try:
        response = mixtral_api.categorize(prompt)
        return response
    except MixtralAPIError as e:
        if e.status_code == 402:  # Payment Required
            raise CreditExhausted(f"Lane {lane}, File {file_id}")
        elif e.status_code == 429:  # Rate Limit
            backoff_and_retry()
        else:
            raise
```

**3. Pause & Consultation:**
```python
except CreditExhausted as e:
    # Save checkpoint
    checkpoint = {
        'lane_a_progress': lane_a_files_completed,
        'lane_b_progress': lane_b_files_completed,
        'lane_c_progress': lane_c_files_completed,
        'next_file_index': current_index,
        'timestamp': datetime.now()
    }
    save_checkpoint('wave1_checkpoint.json', checkpoint)

    # Notify stakeholder
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  ⚠️  MISTRAL CREDITS EXHAUSTED - Wave 1 Paused             ║
╚══════════════════════════════════════════════════════════════╝

Wave 1 Progress:
  Lane A (Minimalist): {lane_a_files_completed}/20 files
  Lane B (Teacher):    {lane_b_files_completed}/20 files
  Lane C (Reasoner):   {lane_c_files_completed}/20 files

Total API calls: {total_calls}
Estimated cost so far: ${estimated_cost:.2f}

ACTION REQUIRED:
1. Fund Mistral API account
2. Verify credits available
3. Resume with: objlib wave1 --resume wave1_checkpoint.json

Process will resume from file #{current_index + 1}
All completed work is saved and will not be re-processed.
    """)
    sys.exit(0)  # Clean exit
```

**4. Resume Capability:**
```bash
objlib wave1 --resume wave1_checkpoint.json
# Loads checkpoint, skips completed files, continues from last position
```

**Open questions:**
- Implement automatic "cool down" sleep on rate limits (429), or hard stop for consultation?
- Should checkpoint include partial results (mid-file) or only completed files?
- Email notification option when credits exhausted (if running unattended)?
- Pre-flight credit check before starting Wave 1?

---

### ⚠️ W1.7. Result Aggregation & Wave 2 Transition Criteria (Recommended)

**What needs to be decided:**
Exact criteria to declare Wave 1 "Complete" and ready for Wave 2. How to handle hybrid strategies.

**Why it's ambiguous:**
Might find Team A good at categories but Team B good at summaries. Need way to merge or choose. Also unclear when to trigger Wave 1.5 (re-discovery) vs proceed to Wave 2.

**Proposed implementation decision:**
**Hybrid Template Generation with Quality Gates:**

**Phase 1: Per-Strategy Analysis**
```python
# Calculate per-strategy metrics
strategy_results = {
    'A_minimalist': {
        'mean_edit_distance': 2.3,
        'confidence_correlation': 0.65,
        'tier1_accuracy': 0.95,  # Category
        'tier2_accuracy': 0.88,  # Primary topics
        'tier3_quality': 0.72,   # Topic aspects
        'tier4_quality': 0.68,   # Semantic description
        'avg_cost_per_file': 0.12
    },
    # ... similar for B and C
}
```

**Phase 2: Best-of-Breed Synthesis**
- If one strategy dominates all metrics → Use that strategy for Wave 2
- If split performance → **Hybrid Prompt:**
  - Use structure from best tier1/tier2 accuracy (controlled)
  - Use instructions from best tier3/tier4 quality (freeform)
  - Combine temperature, examples as needed

**Phase 3: Wave 2 Transition Gates**
```python
def can_proceed_to_wave2(results):
    # MUST pass all gates
    gates = {
        'tier1_accuracy': results['best']['tier1_accuracy'] >= 0.90,
        'tier2_accuracy': results['best']['tier2_accuracy'] >= 0.85,
        'confidence_calibration': results['best']['confidence_correlation'] >= 0.60,
        'cost_acceptable': results['best']['avg_cost_per_file'] <= 0.30,
        'human_usability': results['best']['mean_edit_distance'] <= 2.0
    }

    if all(gates.values()):
        return True, "Wave 2 approved"
    else:
        failed = [k for k, v in gates.items() if not v]
        return False, f"Gates failed: {failed} → Trigger Wave 1.5"
```

**Wave 1.5 Trigger (Re-Discovery):**
If any gate fails:
- Analyze failure mode (e.g., tier4_quality low across all strategies)
- Design focused experiment (e.g., test 3 semantic_description instruction variants)
- Process additional 10-20 files
- Re-evaluate gates

**Open questions:**
- Should Wave 2 transition require stakeholder sign-off, or automatic if gates pass?
- What if cost gate fails but quality gates pass (expensive but accurate)?
- Maximum iterations of Wave 1.X before escalating to manual prompt engineering?

---

## Wave 2 Gray Areas: Production Processing

These gray areas apply to Wave 2 (production processing of 446-476 remaining files) using the validated approach from Wave 1.

### ⚠️ W2.1. Prompt Engineering for 4-Tier Extraction (Recommended)

**What needs to be decided:**
How to structure the prompt to enforce strict controlled vocabulary for Tiers 1-2 (category, primary_topics) while simultaneously encouraging creative freeform extraction for Tiers 3-4 (topic_aspects, semantic_description).

**Why it's ambiguous:**
LLMs struggle with mixed constraints in a single prompt. There's high risk of:
- Hallucinating non-existent tags into `primary_topics`
- Over-constraining `topic_aspects` to match the controlled vocabulary
- Producing invalid JSON that requires complex parsing

Both providers noted this is the foundation for all other decisions.

**Provider synthesis:**

**OpenAI:** Recommends single-pass strict JSON-schema prompt with:
- System prompt: "Return ONLY valid JSON matching this schema"
- Inline controlled 40-tag vocabulary with explicit instruction
- 1-2 few-shot examples showing correct tiering
- Explicit constraints on lengths (3-8, 3-10), difficulty enum

**Gemini:** Recommends "Filter vs. Generate" instruction pattern:
- System prompt defining persona (Objectivist archivist)
- Numbered list of 40 allowed tags
- Separate instructions: "For primary_topics, select ONLY from list" vs "For topic_aspects, generate novel phrases"
- Post-processing cleanup in Python to drop invalid primary_topics

**Proposed implementation decision:**
Combine both approaches:
1. **System prompt:** "You are an Objectivist philosophy archivist. Return ONLY valid JSON matching this schema."
2. **Context injection:** Explicitly list 40 controlled tags as numbered list
3. **Instruction pattern:**
   - "For `category` (select exactly 1): [list 7 categories]"
   - "For `primary_topics` (select 3-8 ONLY from vocabulary): [40-tag list]"
   - "For `topic_aspects` (generate 3-10 novel specific concepts from text, ignore vocabulary)"
   - "For `semantic_description` (analyze arguments and positions)"
4. **Few-shot examples:** Include 1-2 complete examples with Objectivist content
5. **Post-processing:** Python validation that silently filters invalid primary_topics before database write

**Open questions:**
- Does injecting 40-tag list (~200-300 tokens) per request significantly impact budget across 496 files?
- Should we include brief definitions for the 40 tags to improve accuracy?
- Allow model to output fewer than 3 topics/aspects for very short transcripts, or enforce minimums?
- Should the prompt include "house style" requirements for summary voice (neutral, no quotes, no speaker names)?

---

### ⚠️ W2.2. Handling Mixtral's Response Format (Recommended)

**What needs to be decided:**
How to reliably extract JSON payload when Mixtral returns array format with `type: "thinking"` and `type: "text"` segments, even with JSON mode enabled.

**Why it's ambiguous:**
The response structure conflicts with JSON mode expectations. Development can block if:
- JSON is embedded inside a `text` field
- Multiple `text` segments appear
- Stray characters break parsing
- "Thinking" blocks contaminate the output

**Provider synthesis:**

**OpenAI:** Recommends response normalizer:
1. Concatenate all segments where `type == "text"` (ignore thinking)
2. Parse as JSON (strict)
3. Single repair attempt: extract first `{` to last `}` substring
4. On failure: mark as `metadata_status="failed_json"`, retry with stricter prompt

**Gemini:** Recommends regex extraction approach:
- Treat response as string
- Use regex to find last occurrence of valid JSON object (between `{` and `}`)
- Rationale: Mixtral often puts final answer at end after reasoning

**Proposed implementation decision:**
Implement robust two-phase parser:

**Phase 1 (Structured):**
```python
def parse_mixtral_response(response):
    # Try structured array parsing first
    if isinstance(response, list):
        text_segments = [seg['content'] for seg in response if seg.get('type') == 'text']
        combined = ''.join(text_segments)
        try:
            return json.loads(combined)
        except json.JSONDecodeError:
            pass  # Fall through to Phase 2

    # Phase 2 (Regex fallback)
    response_str = str(response)
    # Find last complete JSON object
    match = re.search(r'\{(?:[^{}]|(?:\{[^{}]*\}))*\}(?!.*\{)', response_str, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Phase 3 (Failed)
    raise ValueError("No valid JSON found in response")
```

**Open questions:**
- Can Mixtral SDK be configured to suppress thinking entirely?
- Should we store raw responses for audit/debug (cost/storage implications)?
- Should we save the "thinking" block to log for debugging low-confidence scores?
- How many retries are acceptable before human review is required?

---

### ⚠️ W2.3. Validation Strategy for Hybrid Tiers (Recommended)

**What needs to be decided:**
Whether validation should only check controlled fields (Tiers 1-2) or also enforce quality/coherence checks on freeform tiers (Tiers 3-4).

**Why it's ambiguous:**
"Validate controlled tiers, skip freeform tiers" is the stated approach, but freeform tiers can still break UX if they're empty, nonsensical, or contradict controlled tags. Standard validation tools don't handle this heterogeneity well.

**Provider synthesis:**

**OpenAI:** Recommends two-level validation:
- **Level A (hard fail):** category ∈ 7 allowed, difficulty ∈ enum, primary_topics 3-8 from vocab, confidence_score 0-1, summary non-empty
- **Level B (soft warnings):** topic_aspects length 3-10, key_arguments/positions non-empty arrays, cross-tier heuristics
- Store warnings for CLI review, don't block ingestion

**Gemini:** Recommends strict vs heuristic split:
- **Tier 1-2 (Strict):** Use Pydantic enums; if <3 valid primary_topics after filtering, mark failed
- **Tier 3-4 (Heuristic):** topic_aspects ≥3 and not identical to primary_topics; summary >50 chars
- Retry strict failures; flag heuristic failures for manual review (don't retry to save cost)

**Proposed implementation decision:**
Implement tiered validation with explicit status codes:

```python
# Hard validation (blocks acceptance)
HARD_RULES = {
    'category': lambda v: v in CATEGORIES,
    'difficulty': lambda v: v in ['intro', 'intermediate', 'advanced'],
    'primary_topics': lambda v: 3 <= len(v) <= 8 and all(t in VOCAB_40 for t in v),
    'confidence_score': lambda v: 0 <= float(v) <= 1,
}

# Soft validation (warns but accepts)
SOFT_RULES = {
    'topic_aspects': lambda v: 3 <= len(v) <= 10,
    'semantic_description.summary': lambda v: len(v) >= 50,
    'semantic_description.key_arguments': lambda v: len(v) >= 1,
    'semantic_description.philosophical_positions': lambda v: len(v) >= 0,  # Optional
}
```

**Statuses:**
- `extracted` - Passes hard validation
- `needs_review` - Passes hard, fails soft (still indexed with lower priority)
- `failed_validation` - Fails hard validation → retry once with schema reminder
- `failed_json` - JSON parse failed → retry once with stricter prompt

**Open questions:**
- Is empty `key_arguments` acceptable for short transcripts, or trigger re-run?
- Should we enforce minimum "semantic_description completeness score"?
- Allow second LLM "grader" pass for quality validation, or rules only?
- What cross-tier consistency checks are valuable? (e.g., category=qa_session but summary mentions "lecture")

---

### ⚠️ W2.4. Database Schema for Hybrid Metadata (Recommended)

**What needs to be decided:**
How to store 4-tier metadata in SQLite to support filtering (controlled vocab) and search (freeform) without over-engineering.

**Why it's ambiguous:**
- `primary_topics` need fast filtering → suggests junction table
- `topic_aspects` are unique per file, rarely exact-match filtered → suggests JSON blob
- `semantic_description` is display-only
SQLite JSON1 extension vs normalized tables trade-offs unclear.

**Provider synthesis:**

**OpenAI:** Recommends hybrid schema:
1. `files` table: core identity, path, hash, timestamps, category, difficulty, confidence_score, metadata_status
2. `file_metadata` table: file_id, metadata_json (full structure), model, model_version, prompt_version, created_at
3. `file_topics` junction: file_id, topic_tag (indexed on topic_tag, file_id)

**Gemini:** Recommends similar approach:
- Columns: category (indexed), difficulty (indexed), metadata_blob (JSON for aspects/description)
- Junction table `content_tags`: file_id → tag_id for primary_topics
- Consider FTS5 virtual table for topic_aspects if searchable

**Proposed implementation decision:**
Adopt hybrid schema with explicit versioning:

```sql
-- Core file identity
CREATE TABLE files (
    file_id INTEGER PRIMARY KEY,
    filepath TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    -- ... existing columns ...
    category TEXT,                    -- Tier 1 (indexed)
    difficulty TEXT,                  -- Tier 1 (indexed)
    confidence_score REAL,
    metadata_status TEXT,             -- extracted/needs_review/failed_*
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_category ON files(category);
CREATE INDEX idx_difficulty ON files(difficulty);
CREATE INDEX idx_metadata_status ON files(metadata_status);

-- Versioned metadata storage
CREATE TABLE file_metadata (
    metadata_id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,      -- Full 4-tier structure
    model TEXT NOT NULL,               -- 'magistral-medium-latest'
    model_version TEXT,                -- API-provided build
    prompt_version TEXT NOT NULL,      -- Semantic version
    extraction_config_hash TEXT,       -- sha256(temp+timeout+schema)
    is_current BOOLEAN DEFAULT 1,      -- Latest version flag
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES files(file_id)
);
CREATE INDEX idx_metadata_current ON file_metadata(file_id, is_current);

-- Fast filtering on controlled vocabulary
CREATE TABLE file_primary_topics (
    file_id INTEGER NOT NULL,
    topic_tag TEXT NOT NULL,           -- From controlled 40-tag vocab
    PRIMARY KEY (file_id, topic_tag),
    FOREIGN KEY (file_id) REFERENCES files(file_id)
);
CREATE INDEX idx_primary_topic ON file_primary_topics(topic_tag);

-- Optional: Full-text search on freeform aspects
CREATE VIRTUAL TABLE file_aspects_fts USING fts5(
    file_id UNINDEXED,
    topic_aspects,                     -- Concatenated from JSON array
    semantic_summary
);
```

**Open questions:**
- Query `topic_aspects` textually in SQL, or only via Gemini semantic search?
- Store `semantic_description.summary` redundantly in files table for quick display?
- Enable FTS5 on topic_aspects for fast keyword search?
- Keep full metadata history (multiple rows) or overwrite-in-place?

---

### ⚠️ W2.5. Context Window Strategy (Recommended)

**What needs to be decided:**
How much transcript text to send to Mixtral per file, given timeouts (240s), token limits, cost, and the need for complete `semantic_description` with key arguments.

**Why it's ambiguous:**
Transcripts vary widely in length. Full-text maximizes quality but may exceed context or cause timeouts. Truncating risks missing conclusions needed for Tier 4 extraction.

**Provider synthesis:**

**OpenAI:** Recommends hybrid input strategy:
- If transcript ≤ N tokens (e.g., 12k), send full text
- Else: Extract first ~1k + last ~1k + 3-5 evenly spaced ~600-token windows
- Include file header (if present) and "Week/Topic" metadata
- Instruct: "Base outputs only on provided excerpts; if uncertain, lower confidence"

**Gemini:** Recommends start+end concatenation:
- Token limit: 20k tokens max
- If >20k: Send first 15k + last 5k (with separator)
- Rationale: Captures intro (definitions) and conclusion (synthesis) for key_arguments

**Proposed implementation decision:**
Implement adaptive chunking with quality preservation:

```python
def prepare_transcript_input(transcript_text, max_tokens=18000):
    token_count = estimate_tokens(transcript_text)

    if token_count <= max_tokens:
        return transcript_text

    # Extract header metadata (Year/Quarter/Week/Title)
    header = extract_header_metadata(transcript_text)

    # Adaptive strategy based on length
    if token_count <= max_tokens * 1.5:
        # Slightly over: send start + end
        start_tokens = int(max_tokens * 0.7)
        end_tokens = int(max_tokens * 0.3)
        start = get_first_n_tokens(transcript_text, start_tokens)
        end = get_last_n_tokens(transcript_text, end_tokens)
        return f"{header}\n\n[START]\n{start}\n\n[...]\n\n[END]\n{end}"
    else:
        # Very long: windowed sampling
        start = get_first_n_tokens(transcript_text, 3000)
        end = get_last_n_tokens(transcript_text, 3000)
        middle_windows = extract_evenly_spaced_windows(
            transcript_text,
            num_windows=3,
            tokens_per_window=600
        )
        return f"{header}\n\n[START]\n{start}\n\n[EXCERPTS]\n{middle_windows}\n\n[END]\n{end}"
```

Include in prompt: "If working from excerpts, base ALL metadata on provided text only. If insufficient context for complete semantic_description, reduce confidence_score accordingly."

**Open questions:**
- What is actual max context for magistral-medium-latest?
- Do transcripts have consistent headers (date/week/title) to parse and always include?
- Acceptable that Tier 4 may miss arguments not in excerpts?
- Does Mixtral handle context jumps (concatenated start/end) effectively, or hallucinate connections?

---

### ⚠️ W2.6. CLI Review Workflow for 4 Tiers (Recommended)

**What needs to be decided:**
How to display and interact with 4-tier metadata in Rich/Typer CLI without overwhelming users or making review too slow.

**Why it's ambiguous:**
Previous phases reviewed simple key-value pairs. Now we have:
- Arrays of strings (primary_topics, topic_aspects)
- Nested objects (semantic_description)
- Quality varies by confidence score
A raw JSON dump is unreadable for quick verification.

**Provider synthesis:**

**OpenAI:** Recommends `meta review` command with:
- List view: file, category, difficulty, top 3 primary_topics, confidence, status
- Detail view: collapsible Rich Panels for each tier
- Actions: approve (sets approved status), rerun, edit-controlled (constrained), edit-freeform ($EDITOR on JSON)

**Gemini:** Recommends Rich terminal rendering:
- Header: Category | Difficulty | Confidence
- Row 1: Primary Topics (green pills/tags)
- Row 2: Topic Aspects (bulleted list)
- Row 3: Summary (text wrap)
- Interaction: Auto-accept if confidence >0.85, else prompt [A]ccept/[E]dit/[S]kip
- Editing: Open JSON in $EDITOR (no inline editing)

**Proposed implementation decision:**
Implement tiered review workflow:

```bash
# List view (default)
objlib meta review
# Shows table: File | Category | Difficulty | Topics (3) | Conf | Status

# Detail view (interactive)
objlib meta review --interactive
# Shows Rich panels:
┌─ File: OPAR_1985_Q2_W3.txt ─────────────────────────────┐
│ Category: course_transcript | Difficulty: intermediate   │
│ Confidence: 89% | Status: needs_review                  │
├─ Primary Topics (Tier 2) ──────────────────────────────┤
│ • epistemology  • concept_formation  • reason          │
├─ Topic Aspects (Tier 3) ───────────────────────────────┤
│ • measurement omission principle                       │
│ • unit-economy in concept formation                    │
│ • hierarchical concept organization                    │
├─ Semantic Description (Tier 4) ────────────────────────┤
│ Summary: Lecture on how humans form concepts...        │
│ Key Arguments:                                         │
│   1. Concepts formed by measuring similarities...      │
│   2. Unit-economy: cognitive efficiency...             │
│ Positions:                                             │
│   • Rand's epistemology vs Plato's theory of forms    │
└────────────────────────────────────────────────────────┘

Actions: [A]ccept  [E]dit JSON  [R]erun extraction  [S]kip  [Q]uit
```

**Auto-approval logic:**
- confidence ≥ 0.85 → Auto-approve (skip interactive review)
- 0.70 ≤ confidence < 0.85 → Interactive review
- confidence < 0.70 → Flag for mandatory review

**Bulk actions:**
```bash
# Approve all high-confidence files
objlib meta approve --min-confidence 0.85

# Review only failures
objlib meta review --status needs_review

# Export for external review
objlib meta export --format csv --status needs_review
```

**Open questions:**
- Display `key_arguments` in CLI view, or hide to keep review fast?
- Is human review mandatory for low confidence, or optional?
- Track edits with audit log (who/when/why)?
- Support bulk approve for high-confidence batches?

---

### 🔍 W2.7. Confidence Scoring Definition (Needs Clarification)

**What needs to be decided:**
How `confidence_score` is computed given 4 heterogeneous tiers, and what it represents operationally.

**Why it's ambiguous:**
Requirements specify single scalar 0-1, but don't define:
- Is it category certainty only, overall extraction quality, or weakest tier?
- Model self-reported vs rule-based computed?
- How to weight controlled (objective) vs freeform (subjective) tiers?

**Provider synthesis:**

**OpenAI only:** Recommends composite scoring:
- Base = model-provided confidence
- Apply rule-based penalties:
  - -0.25 if hard validation needed repair
  - -0.10 per soft warning (max -0.30)
  - -0.15 if short transcript (<800 chars) but many claims (hallucination risk)
- Clamp to [0,1]

**Proposed implementation decision:**
Implement multi-dimensional confidence with composite score:

```python
def calculate_confidence(response, validation_results, transcript_length):
    # Start with model's self-assessment (if provided)
    base = response.get('confidence_score', 0.75)

    # Tier-specific confidence components
    tier1_conf = 1.0 if validation_results['category_valid'] else 0.3
    tier2_conf = len(validation_results['valid_primary_topics']) / 8  # Normalize to [0,1]
    tier3_conf = 0.8 if validation_results['aspects_count'] >= 3 else 0.5
    tier4_conf = 0.9 if validation_results['summary_length'] >= 50 else 0.6

    # Weighted average (bias toward controlled tiers)
    weighted = (tier1_conf * 0.3 + tier2_conf * 0.4 + tier3_conf * 0.15 + tier4_conf * 0.15)

    # Apply penalties
    penalties = 0
    penalties += 0.25 if validation_results['repairs_needed'] else 0
    penalties += 0.10 * len(validation_results['soft_warnings'])
    penalties += 0.15 if transcript_length < 800 and tier4_conf > 0.7 else 0

    final = max(0.0, min(1.0, weighted - penalties))
    return round(final, 2)
```

**Open questions:**
- Should low confidence block indexing or only affect ranking?
- What cutoff triggers "needs review" (e.g., <0.70)?
- Confidence monotonic with transcript length, or independent?
- Store tier-specific confidences in metadata_json for debugging?

---

### 🔍 W2.8. Parallel Processing + Rate Limit Coordination (Needs Clarification)

**What needs to be decided:**
How to enforce 60 req/min across 3 concurrent agents without exceeding limits, and how backoff/retry works under throttling.

**Why it's ambiguous:**
"3 concurrent agents" could mean threads, processes, async tasks, or separate workers. Without shared limiter, they can collectively violate 60/min global limit.

**Provider synthesis:**

**OpenAI only:** Recommends central token-bucket rate limiter:
- Use `asyncio` with semaphore for concurrency=3
- Global limiter set to 60/min (1 req/sec average) with jittered sleep
- On 429/503: exponential backoff with full jitter, max retries=5
- If multi-process: store limiter state in SQLite or Redis

**Proposed implementation decision:**
Implement asyncio-based rate-limited processor:

```python
import asyncio
from aiolimiter import AsyncLimiter

class MixtralProcessor:
    def __init__(self, concurrency=3, rate_limit=60):
        self.semaphore = asyncio.Semaphore(concurrency)
        self.rate_limiter = AsyncLimiter(rate_limit, 60)  # 60 requests per 60 seconds

    async def process_file(self, file_path):
        async with self.semaphore:  # Limit concurrency
            async with self.rate_limiter:  # Enforce rate limit
                return await self._call_mixtral(file_path)

    async def _call_mixtral(self, file_path):
        for retry in range(5):
            try:
                response = await mixtral_api.categorize(file_path)
                return response
            except RateLimitError:
                backoff = (2 ** retry) + random.uniform(0, 1)  # Exponential + jitter
                await asyncio.sleep(backoff)
            except Exception as e:
                if retry == 4:
                    raise
        raise MaxRetriesExceeded()
```

**Open questions:**
- Must "3 agents" be separate processes (fault isolation) or can use async tasks?
- Separate limits for input tokens/output tokens, or only request count?
- Should retries preserve ordering or allow out-of-order completion?
- Need to coordinate across multiple machines, or single-machine only?

---

### 🔍 W2.9. Error Handling for Partial Extraction (Needs Clarification)

**What needs to be decided:**
What happens when Mixtral returns valid JSON but missing fields (e.g., no philosophical_positions) or wrong types.

**Why it's ambiguous:**
"Error handling for partial tier extraction" is called out as a gray area, but acceptance criteria for partial data are undefined. This blocks deterministic pipeline behavior.

**Provider synthesis:**

**OpenAI only:** Recommends explicit status state machine:
- Statuses: `pending`, `extracted`, `needs_review`, `failed_json`, `failed_validation`, `retry_scheduled`, `approved`
- JSON parse failure → `failed_json` + auto retry (max 2)
- Hard validation failure → `failed_validation` + retry with "schema reminder" prompt
- Soft warnings only → `needs_review` but still indexed with lower confidence

**Proposed implementation decision:**
Define status transitions and partial acceptance rules:

```python
class MetadataStatus(Enum):
    PENDING = "pending"
    EXTRACTED = "extracted"              # All tiers present, passes hard validation
    PARTIAL_EXTRACTED = "partial"        # Some tiers missing (e.g., no Tier 4)
    NEEDS_REVIEW = "needs_review"        # Soft warnings present
    FAILED_JSON = "failed_json"          # Parse error
    FAILED_VALIDATION = "failed_validation"  # Hard validation failed
    RETRY_SCHEDULED = "retry_scheduled"
    APPROVED = "approved"                # Human or auto-approved

# Partial extraction rules
def handle_partial_extraction(metadata):
    required_tiers = ['category', 'difficulty', 'primary_topics']
    optional_tiers = ['topic_aspects', 'semantic_description']

    # Check required tiers
    missing_required = [t for t in required_tiers if not metadata.get(t)]
    if missing_required:
        return MetadataStatus.FAILED_VALIDATION, f"Missing: {missing_required}"

    # Check optional tiers
    missing_optional = [t for t in optional_tiers if not metadata.get(t)]
    if missing_optional:
        # Accept but flag as partial
        metadata['_partial_reason'] = f"Missing: {missing_optional}"
        return MetadataStatus.PARTIAL_EXTRACTED, "Accepted with missing optional tiers"

    return MetadataStatus.EXTRACTED, "Complete extraction"
```

**Retry strategy:**
- JSON parse failure: Retry with stricter prompt (max 2 attempts)
- Hard validation failure: Retry with schema reminder + example (max 1 attempt)
- Partial extraction: No retry, accept with reduced confidence

**Open questions:**
- Include `partial` files in search by default, or require flag?
- After max retries, allow "unknown category" to persist or block release?
- Support "fallback minimal metadata" mode (only Tier 1-2) if Tier 4 repeatedly fails?

---

### 🔍 W2.10. Prompt Versioning and Reproducibility (Needs Clarification)

**What needs to be decided:**
How to track which prompt/model produced which metadata, and how to re-run safely when prompts evolve without corrupting prior work.

**Why it's ambiguous:**
Phase 6 executed out of order; later phases may depend on stable metadata. Without versioning, can't compare improvements or roll back bad batches.

**Provider synthesis:**

**OpenAI only:** Recommends comprehensive versioning:
- Store: `model`, `model_build`, `prompt_version` (semantic version), `extraction_config` (temp/timeout/schema hash)
- Keep history rows in `file_metadata` (append-only), mark latest as `is_current=1`
- Enables controlled iteration and auditability

**Proposed implementation decision:**
Implement semantic versioning with config hashing:

```python
# Prompt version tracking
PROMPT_VERSION = "1.0.0"  # Increment on breaking changes

# Config hashing for reproducibility
def hash_extraction_config(config):
    canonical = {
        'temperature': config['temperature'],
        'timeout': config['timeout'],
        'schema_version': config['schema_version'],
        'vocabulary_hash': hashlib.sha256(
            json.dumps(CONTROLLED_VOCAB, sort_keys=True).encode()
        ).hexdigest()[:8]
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True).encode()
    ).hexdigest()[:16]

# Metadata insertion with versioning
def save_metadata(file_id, metadata, config):
    config_hash = hash_extraction_config(config)

    # Mark previous versions as not current
    db.execute(
        "UPDATE file_metadata SET is_current = 0 WHERE file_id = ? AND is_current = 1",
        (file_id,)
    )

    # Insert new version
    db.execute("""
        INSERT INTO file_metadata
        (file_id, metadata_json, model, model_version, prompt_version, extraction_config_hash, is_current)
        VALUES (?, ?, ?, ?, ?, ?, 1)
    """, (file_id, json.dumps(metadata), config['model'], config.get('model_build'),
          PROMPT_VERSION, config_hash))
```

**Prompt evolution workflow:**
```bash
# Show impact of prompt change before running
objlib meta preview-update --prompt-version 1.1.0
# Output: "Would re-extract 342 files (154 approved, 188 needs_review)"

# Re-extract with new prompt (preserves old versions)
objlib meta update --prompt-version 1.1.0 --status needs_review
# Only updates files with needs_review status

# Compare prompt versions
objlib meta diff-versions --file "OPAR_1985_Q2_W3.txt" --versions 1.0.0,1.1.0
```

**Open questions:**
- Auto re-extract all 496 unknowns when prompt changes, or manual trigger?
- Should "approved" metadata be immutable unless explicitly overridden?
- Need CLI diff tool between versions?
- How long to retain old metadata versions (storage implications)?

---

### 🔍 W2.11. Security/Privacy of Mixtral API Calls (Needs Clarification)

**What needs to be decided:**
Whether transcripts can be sent to Mixtral as-is, what to log, and how to handle potentially copyrighted/sensitive content.

**Why it's ambiguous:**
Objectivist lecture transcripts may be copyrighted. Requirements mention retention for Gemini uploads but not Mixtral calls. Legal/privacy implications unclear.

**Provider synthesis:**

**OpenAI only:** Recommends data minimization:
- Send only excerpt necessary for extraction (per context window strategy)
- Don't store full transcript in metadata tables (only file path + hash)
- Store model output JSON and minimal debug info
- Redact transcript content from logs by default
- Add `--debug-store-raw` flag gated behind explicit user opt-in

**Proposed implementation decision:**
Implement privacy-by-default with opt-in debugging:

```python
class PrivacyConfig:
    SEND_FULL_TRANSCRIPT = False  # Use adaptive chunking instead
    LOG_TRANSCRIPT_SNIPPETS = False
    STORE_RAW_RESPONSES = False
    REDACT_ERRORS = True  # Remove transcript text from error messages

def log_extraction_event(file_path, event_type, **kwargs):
    if PrivacyConfig.REDACT_ERRORS and 'error' in kwargs:
        # Remove any transcript content from error messages
        kwargs['error'] = redact_content(kwargs['error'])

    if not PrivacyConfig.LOG_TRANSCRIPT_SNIPPETS:
        kwargs.pop('transcript_excerpt', None)

    logger.info(f"{event_type}: {file_path}", extra=kwargs)

# Opt-in debugging mode
@click.option('--debug-store-raw', is_flag=True,
              help='Store raw API responses (includes transcript excerpts)')
def categorize(debug_store_raw):
    if debug_store_raw:
        PrivacyConfig.STORE_RAW_RESPONSES = True
        click.confirm('This will store transcript excerpts in the database. Continue?', abort=True)
```

**Data retention:**
- Metadata JSON: Stored indefinitely (needed for search/display)
- Raw API responses: Deleted after successful extraction (unless debug mode)
- Logs: Rotate after 30 days, redacted by default
- SQLite DB: Only file paths + hashes, never full transcript content

**Open questions:**
- Are there licensing constraints prohibiting sending full text to third-party LLMs?
- Is local-only inference (running Mixtral locally) an eventual requirement?
- Who has access to SQLite DB and logs in production deployment?
- Need explicit user consent before first API call?

---

### 🔍 W2.12. Interaction with Incremental Updates (Needs Clarification)

**What needs to be decided:**
When to trigger metadata re-extraction: only unknown categories, when transcript changes, when prompt/model changes, or all three?

**Why it's ambiguous:**
Core pillar #3 is incremental updates, but Phase 6 re-run triggers aren't defined. Can cause unnecessary cost or stale metadata depending on policy.

**Provider synthesis:**

**OpenAI only:** Recommends trigger-based re-extraction:
- Trigger when: file content hash changed, prompt_version changed (optional, only non-approved), model changed (only unknown/low-confidence unless forced)
- Maintain `metadata_input_hash = sha256(transcript_hash + prompt_version + model_id + extraction_config_hash)`
- Detect staleness automatically

**Proposed implementation decision:**
Implement smart re-extraction triggers:

```python
def should_reextract_metadata(file_record, current_config):
    # Always extract if no metadata exists
    if file_record.metadata_status == 'pending':
        return True, "No metadata exists"

    # Check content hash change
    if file_record.content_hash != compute_file_hash(file_record.filepath):
        return True, "File content changed"

    # Check config changes
    old_config_hash = file_record.extraction_config_hash
    new_config_hash = hash_extraction_config(current_config)

    if old_config_hash != new_config_hash:
        # Only re-extract if not human-approved
        if file_record.metadata_status != 'approved':
            return True, f"Config changed and status={file_record.metadata_status}"
        else:
            return False, "Approved metadata preserved despite config change"

    # Check if stuck in failed state too long
    if file_record.metadata_status.startswith('failed'):
        days_since_update = (datetime.now() - file_record.updated_at).days
        if days_since_update > 7:
            return True, "Retry failed extraction after 7 days"

    return False, "Metadata current"

# Batch re-extraction workflow
@click.command()
@click.option('--trigger', type=click.Choice(['content', 'config', 'status', 'all']))
@click.option('--dry-run', is_flag=True)
def reextract(trigger, dry_run):
    """Re-extract metadata based on triggers"""
    files_to_process = []

    for file_record in db.query_all_files():
        should_extract, reason = should_reextract_metadata(file_record, current_config)
        if should_extract:
            files_to_process.append((file_record, reason))

    if dry_run:
        click.echo(f"Would re-extract {len(files_to_process)} files:")
        for file_record, reason in files_to_process[:10]:
            click.echo(f"  {file_record.filepath}: {reason}")
        if len(files_to_process) > 10:
            click.echo(f"  ... and {len(files_to_process) - 10} more")

        estimated_cost = estimate_extraction_cost(len(files_to_process))
        click.echo(f"\nEstimated cost: ${estimated_cost:.2f}")
        click.echo(f"Estimated time: {estimate_time(len(files_to_process))}")
    else:
        # Actual re-extraction
        process_batch(files_to_process)
```

**Open questions:**
- Should "approved" metadata be auto-regenerated when prompts improve, or require manual override?
- What's acceptable staleness window (allow old prompt versions)?
- Need dry-run cost/time report before re-extraction?
- Handle schema changes that make old metadata incompatible?

---

## Summary: Decision Checklist

Before planning Phase 6 implementation, confirm decisions for **both waves**:

### Wave 1 Decisions (Prompt Discovery - Must Decide Before Wave 1 Execution)

**Critical:**
- [ ] **W1.6: Credit exhaustion handling** - Pause/resume with stakeholder consultation (REQUIRED)
- [ ] **W1.2: Prompt variation strategy** - 3 archetypes (Minimalist, Teacher, Reasoner)
- [ ] **W1.4: Test file selection** - Stratified sampling methodology (20 files)

**Important:**
- [ ] **W1.1: Agent team structure** - Competitive lanes vs collaborative chains
- [ ] **W1.3: Ground truth validation** - Human review with edit distance metric
- [ ] **W1.5: Confidence calibration** - Self-reported vs heuristic measurement
- [ ] **W1.7: Wave 2 transition criteria** - Quality gates and hybrid template generation

**Total Wave 1 Gray Areas:** 7

---

### Wave 2 Decisions (Production Processing - Decide During/After Wave 1)

**Tier 1 (Blocking - Must Decide Before Wave 2):**
- [ ] **W2.1: Prompt structure** for 4-tier extraction (informed by Wave 1 winner)
- [ ] **W2.2: Response parsing** strategy for Mixtral array format
- [ ] **W2.3: Validation rules** for hard vs soft failures
- [ ] **W2.4: Database schema** with hybrid storage approach

**Tier 2 (Important - Should Decide Before Wave 2):**
- [ ] **W2.5: Context window** strategy for long transcripts
- [ ] **W2.6: CLI review workflow** for 4-tier display
- [ ] **W2.7: Confidence scoring** algorithm
- [ ] **W2.8: Rate limiting** implementation for 3 concurrent agents

**Tier 3 (Polish - Can Defer to Wave 2 Execution):**
- [ ] **W2.9: Partial extraction** acceptance rules
- [ ] **W2.10: Prompt versioning** and history tracking
- [ ] **W2.11: Privacy/security** policies for API calls
- [ ] **W2.12: Incremental update** triggers

**Total Wave 2 Gray Areas:** 12

---

**Overall:** 19 gray areas across 2 waves (7 Wave 1 + 12 Wave 2)

---

## Next Steps

**✅ YOLO MODE ACTIVE**

Since this synthesis was run with `--yolo` flag, the system will:

1. ✅ Auto-generate CLARIFICATIONS-ANSWERED.md using synthesis recommendations
2. ⏭ Proceed to planning (or await user confirmation based on config)

**Files Generated:**
- `.planning/phases/06-ai-powered-metadata/06-CONTEXT.md` (this file)
- `.planning/phases/06-ai-powered-metadata/CLARIFICATIONS-NEEDED.md` (next)
- `.planning/phases/06-ai-powered-metadata/CLARIFICATIONS-ANSWERED.md` (YOLO auto-generated)

---

**Note on Provider Availability:**
- ✅ OpenAI GPT-5.2: Available
- ✅ Gemini Pro: Available
- ❌ Perplexity Deep Research: Unavailable (401 auth error)

Synthesis based on 2 of 3 providers. Quality remains high as both providers showed strong agreement on core gray areas.

---

*Multi-provider synthesis by: OpenAI GPT-5.2, Gemini Pro*
*Generated: 2026-02-16*
*Mode: YOLO (auto-answer enabled)*
