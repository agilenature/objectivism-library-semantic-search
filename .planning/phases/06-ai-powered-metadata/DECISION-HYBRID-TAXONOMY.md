# Decision Record: Hybrid Taxonomy Approach

**Date:** 2026-02-16
**Decision:** Implement three-tier hybrid metadata structure
**Status:** Approved by stakeholder

---

## Problem Statement

Need to balance two competing requirements:
1. **Consistency:** Controlled vocabulary for reliable filtering/navigation
2. **Nuance:** Capture specific philosophical concepts and arguments that don't fit predefined tags

**Traditional approaches:**
- Option A (controlled only): Loses nuance, can't find specific concepts
- Option B (freeform only): Synonym pollution, inconsistent filtering

---

## Solution: Three-Tier Hybrid System

### Tier 1: Primary Category (Controlled)
**Purpose:** High-level content type classification
**Cardinality:** Exactly 1 per file
**Vocabulary:** 7 predefined categories
```
- course_transcript
- book_excerpt
- qa_session
- article
- philosophy_comparison
- concept_exploration
- cultural_commentary
```

### Tier 2: Primary Topics (Controlled)
**Purpose:** Consistent filtering and faceted search
**Cardinality:** 3-8 per file
**Vocabulary:** ~40 Objectivist philosophy concepts

**Core branches:**
- epistemology, metaphysics, ethics, politics, aesthetics

**Key concepts:**
- reason, volition, rational_egoism, individual_rights, capitalism, objective_reality, consciousness, existence, identity

**Contrasting concepts:**
- altruism, mysticism, collectivism, pragmatism, intrinsicism, subjectivism, determinism

**Philosophical topics:**
- concept_formation, free_will, emotions, rights_theory, art_theory, virtue_ethics

### Tier 3: Topic Aspects (Freeform)
**Purpose:** Capture nuanced philosophical concepts and specific arguments
**Cardinality:** 3-10 per file
**Vocabulary:** Unrestricted (LLM-generated)

**Examples:**
- "measurement omission principle"
- "Rand's critique of Plato's theory of forms"
- "unit-economy in concept formation"
- "hierarchical concept organization"
- "concepts of consciousness vs concepts of entities"
- "validation vs proof in epistemology"

### Tier 4: Semantic Description (Structured Freeform)
**Purpose:** Enable semantic search on arguments and positions
**Structure:**
```json
{
  "summary": "1-2 sentence overview",
  "key_arguments": [
    "Main claim or thesis",
    "Supporting reasoning",
    "Conclusions"
  ],
  "philosophical_positions": [
    "Specific positions discussed",
    "Contrasted philosophical frameworks"
  ]
}
```

---

## Complete Example

**File:** "OPAR_1985_Q2_W3_Concept_Formation.txt"

```json
{
  "category": "course_transcript",
  "difficulty": "intermediate",

  "primary_topics": [
    "epistemology",
    "concept_formation",
    "reason"
  ],

  "topic_aspects": [
    "measurement omission principle",
    "unit-economy in concept formation",
    "hierarchical concept organization",
    "concepts of consciousness vs concepts of entities"
  ],

  "semantic_description": {
    "summary": "Lecture on how humans form concepts through measurement-omission, focusing on the unit-economy principle and hierarchical concept organization.",
    "key_arguments": [
      "Concepts formed by measuring similarities and omitting measurements",
      "Unit-economy: cognitive efficiency through hierarchical concepts",
      "Difference between concepts of entities vs concepts of consciousness"
    ],
    "philosophical_positions": [
      "Rand's epistemology vs Plato's theory of forms",
      "Rejection of rationalism's innate ideas"
    ]
  },

  "confidence_score": 0.89
}
```

---

## Use Cases Enabled

### 1. Structured Filtering (Using Tier 2)
```bash
# Find all epistemology content about concept formation
objlib filter --topics epistemology,concept_formation

# Returns: 47 files with controlled tags
```

### 2. Nuanced Discovery (Using Tier 3)
```bash
# Find specific philosophical principle
objlib search "measurement omission principle"

# Returns: Files mentioning this specific concept in topic_aspects
```

### 3. Semantic Search (Using Tier 4)
```bash
# Find by argument or position
objlib search "Rand's critique of Plato"

# Returns: Files discussing this comparison in semantic_description
```

### 4. Related Content (Using All Tiers)
```bash
# View file and find related content
objlib view "OPAR_Concept_Formation.txt" --show-related

# Shows: Files with overlapping primary_topics AND topic_aspects
```

---

## Benefits

✅ **Consistency:** Primary topics use controlled 40-tag vocabulary (no synonym pollution)
✅ **Nuance:** Topic aspects capture specific concepts beyond predefined tags
✅ **Discovery:** Semantic descriptions enable argument-based search
✅ **Fully automated:** No human vocabulary curation required
✅ **Best of both worlds:** Structured filtering + rich semantic search

## Trade-offs

**Cost:** ~5-10% token increase
- Primary topics: Already planned (no cost)
- Topic aspects: +100-200 tokens per file
- Semantic description: +150-300 tokens per file
- **Total:** ~$130 → $137-143 per 496-file batch

**Complexity:** Slightly more complex prompt and validation
- LLM must generate 4 metadata tiers instead of 2
- Validation only checks controlled tiers (aspects/descriptions unrestricted)
- Net impact: Minimal (prompt engineering handles this)

**Storage:** ~2-3x metadata size per file
- Before: ~200 bytes per file
- After: ~500-600 bytes per file
- For 1,749 files: ~350KB → ~1MB total (negligible)

---

## Implementation Notes

**Prompt structure:**
```python
"""
Extract metadata in 4 tiers:

1. CATEGORY (select exactly 1):
   [7 categories listed]

2. PRIMARY TOPICS (select 3-8):
   [40 controlled tags listed]

3. TOPIC ASPECTS (extract 3-10 freeform):
   Specific philosophical concepts, arguments, named principles.
   Examples: "measurement omission principle", "Rand's critique of X"

4. SEMANTIC DESCRIPTION:
   - summary: 1-2 sentence overview
   - key_arguments: Main claims and reasoning
   - philosophical_positions: Positions/frameworks discussed

Return JSON with all 4 tiers.
"""
```

**Validation:**
- Tier 1 (category): Must be in Enum → Retry if invalid
- Tier 2 (primary_topics): Must be from controlled vocabulary → Retry if invalid
- Tier 3 (topic_aspects): Freeform → No validation
- Tier 4 (semantic_description): Freeform → No validation

**Database schema:**
```sql
ALTER TABLE file_metadata ADD COLUMN primary_topics TEXT;      -- JSON array
ALTER TABLE file_metadata ADD COLUMN topic_aspects TEXT;       -- JSON array
ALTER TABLE file_metadata ADD COLUMN semantic_description TEXT; -- JSON object
```

---

## Future Enhancements (Optional)

**Phase 6.1 (optional):** Vocabulary evolution
- After processing all files, analyze topic_aspects for recurring concepts
- Concepts appearing ≥20 times could be promoted to controlled vocabulary
- Example: "unit_economy" appears 43 times → Add to primary_topics for future batches

**Phase 6.2 (optional):** Aspect consolidation
- Group semantically similar aspects via embeddings
- Example: "measurement-omission" ≈ "omission of measurements" ≈ "measurement omission principle"
- Normalize to canonical forms for better search

**Phase 7 (TUI):** Visual tag cloud
- Display primary_topics as structured filters
- Display topic_aspects as tag cloud sized by frequency
- Click aspect → Find all files discussing that concept

---

## Decision Rationale

**Why this beats traditional approaches:**

| Approach | Filtering | Discovery | Maintenance | Chosen? |
|----------|-----------|-----------|-------------|---------|
| Controlled only | ✅ Excellent | ❌ Misses nuance | ✅ Low effort | ❌ |
| Freeform only | ❌ Inconsistent | ✅ Great recall | ❌ High effort | ❌ |
| **Hybrid (chosen)** | ✅ Excellent | ✅ Great recall | ✅ Low effort | **✅** |

**Stakeholder requirement:** "I don't want to participate" (fully automated)
- No human vocabulary curation required
- No manual tag consolidation
- LLM handles both controlled selection AND freeform extraction
- System gets best of both worlds automatically

---

**Approved by:** Stakeholder (2026-02-16)
**Implemented in:** Phase 6 planning
**Next step:** Update CLARIFICATIONS-NEEDED.md Q1 to reflect this decision
