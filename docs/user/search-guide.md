# Search Guide

A guide to the `objlib search` command and all its features.

## How Semantic Search Works

`objlib search` sends your query to Google Gemini File Search, which performs dense vector similarity search across all 1,721 indexed documents. Unlike keyword search, it matches _meaning_: searching for "happiness as the moral purpose of life" also finds documents discussing "flourishing," "well-being," and "the standard of value" — even if those exact words aren't in your query.

Results are returned as passages with source citations. Gemini identifies the most relevant text excerpts and which documents they came from.

## Basic Usage

```bash
python -m objlib --store objectivism-library-test search "What is the Objectivist view of rights?"
```

## Query Expansion

**What it does:** Before sending your query to Gemini, `objlib` checks it against a curated glossary of Objectivist terminology (`synonyms.yml`). If any terms match, synonyms are appended to the query to improve recall.

**Example:** Searching for `"egoism"` automatically expands to `"egoism rational self-interest selfishness"`, catching documents that use the synonymous phrasing.

**How to check it:** The CLI prints the expansion inline:
```
Expanded: egoism -> rational self-interest, selfishness
```

**To disable:** Use `--no-expand`
```bash
python -m objlib --store objectivism-library-test search "egoism" --no-expand
```

**The glossary covers:** metaphysics (existence, identity, causality, free will), epistemology (concept formation, objectivity, axioms), ethics (rational self-interest, altruism, virtue, pride, rights), politics (capitalism, individualism, property rights), aesthetics (romantic realism, sense of life), common errors (mysticism, determinism, stolen concept), and key works (OPAR, ITOE, Atlas Shrugged).

## Reranking

**What it does:** After Gemini returns raw results, an LLM reranker (Gemini Flash) scores each passage from 0–10 for relevance to your specific query. Passages are reordered by score. This corrects cases where Gemini's raw ranking doesn't match conceptual relevance.

**Default:** On. Disable with `--no-rerank` if you want pure Gemini ordering or faster results.

```bash
python -m objlib --store objectivism-library-test search "concept formation" --no-rerank
```

## Difficulty-Aware Ordering (`--mode`)

Results are ordered based on difficulty level metadata extracted from each document.

| Mode | Description |
|------|-------------|
| `learn` (default) | Introductory content first, then intermediate, then advanced |
| `research` | Pure relevance ordering (rerank scores only) |

**Example — learning a concept from scratch:**
```bash
python -m objlib --store objectivism-library-test search "free will" --mode learn
```

**Example — deep research without difficulty filtering:**
```bash
python -m objlib --store objectivism-library-test search "free will" --mode research
```

## Synthesis (`--synthesize`)

**What it does:** Generates a multi-paragraph prose answer synthesizing information from the top results, with inline citations (`[1]`, `[2]`, etc.) tracing every claim back to a specific source passage. Uses Gemini Flash with structured output and validates that cited quotes appear in the source text.

**When to use it:** When you want a direct, readable answer rather than a list of excerpts. Good for concept overviews.

**Graceful degradation:** If fewer than 5 sources are available, synthesis is skipped and standard results are shown.

```bash
python -m objlib --store objectivism-library-test search "What is the relationship between reason and emotion?" --synthesize
```

Output looks like:
```
╭─ Synthesis ──────────────────────────────────────────────────────╮
│ Objectivism holds that reason is man's only valid cognitive       │
│ faculty [1]. Emotions are not tools of cognition but automatic   │
│ responses to one's value judgments [2]. ...                       │
╰──────────────────────────────────────────────────────────────────╯
[1] OPAR Lecture 4 - The Nature of Reason.txt
[2] Introduction to Objectivism - Week 3.txt
```

## Concept Evolution (`--track-evolution`)

**What it does:** Groups results by difficulty level to show how a concept develops across the curriculum — from first introduction in introductory courses through intermediate elaboration to advanced treatment.

```bash
python -m objlib --store objectivism-library-test search "concept formation" --track-evolution
```

Output shows three sections: Introductory Treatment, Intermediate Development, Advanced Analysis.

## Metadata Filtering (`--filter`)

Restrict results to documents matching specific metadata. Filters are applied server-side in Gemini before results are returned.

**Syntax:** `--filter field:value`

**Filterable fields:**

| Field | Example Values |
|-------|----------------|
| `category` | `course`, `book`, `motm`, `qa_session`, `philosophy_comparison` |
| `course` | `OPAR`, `ITOE`, `History of Philosophy`, `ARI_Seminars` |
| `difficulty` | `introductory`, `intermediate`, `advanced` |
| `year` | `2020`, `2021`, `2022`, `2023` |
| `week` | `1`, `2`, `10` |
| `quality_score` | `>=75`, `>=90` |

**Examples:**

```bash
# Only OPAR transcripts
python -m objlib --store objectivism-library-test search "causality" --filter "course:OPAR"

# Introductory content only
python -m objlib --store objectivism-library-test search "concept formation" --filter "difficulty:introductory"

# Multiple filters (AND logic)
python -m objlib --store objectivism-library-test search "free will" --filter "course:OPAR" --filter "difficulty:intermediate"

# Year range
python -m objlib --store objectivism-library-test search "rights" --filter "year:>=2020"
```

## Debug Mode

Writes a detailed log to `~/.objlib/debug.log` including query expansion decisions, reranking scores, and citation lookup results.

```bash
python -m objlib --store objectivism-library-test search "egoism" --debug
cat ~/.objlib/debug.log
```

## Worked Examples

### 1. Starting to learn about Objectivist ethics

```bash
python -m objlib --store objectivism-library-test search "What is the Objectivist standard of value?" --mode learn
```

Shows introductory treatments of the standard of value (man's life) before more advanced discussions.

### 2. Getting a synthesized overview of a topic

```bash
python -m objlib --store objectivism-library-test search "What is rational self-interest?" --synthesize
```

Returns a cited prose answer drawing from multiple sources.

### 3. Finding OPAR content on a topic

```bash
python -m objlib --store objectivism-library-test search "concept formation and measurement omission" --filter "course:OPAR"
```

Restricts to OPAR lectures where Peikoff covers the measurement omission theory.

### 4. Researching how a concept evolved across courses

```bash
python -m objlib --store objectivism-library-test search "volition and free will" --track-evolution
```

Shows development from basic introduction through advanced philosophical treatment.

### 5. Finding who discussed a philosopher

```bash
python -m objlib --store objectivism-library-test search "Kant's theory of knowledge" --filter "category:course"
```

Finds course lectures that critique or discuss Kantian epistemology.

### 6. Advanced research with all features

```bash
python -m objlib --store objectivism-library-test search "the primacy of existence" \
  --synthesize \
  --filter "difficulty:advanced" \
  --mode research \
  --debug
```

---

_Last updated: Phase 4 — Reranking, synthesis, query expansion, difficulty ordering_
