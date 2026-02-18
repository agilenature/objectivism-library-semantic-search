# Query Expansion Template for Objectivism Library Search

Use this template to expand a raw user query into a semantically rich search
query before passing it to `objlib search`. Adjust which angles to include
based on the query type (conceptual, factual, historical, applied, etc.).

---

## The Template

```
{CORE CONCEPT}: {brief philosophical definition or framing}

What is {CORE CONCEPT}? {alternative phrasings or related terms}

Examples of {CORE CONCEPT} in {philosophy / everyday reasoning / politics / aesthetics}.

{Causal question}: How does {CORE CONCEPT} lead to {consequence}?

{Normative question}: Why is {CORE CONCEPT} {important / an error / valid}?

{Domain vocabulary}: {2-3 Objectivist terms related to the concept}
```

---

## Angles to Include (pick what fits the query type)

| Angle | Use when |
|---|---|
| **Definition** | Conceptual or unfamiliar terms |
| **Examples** | Abstract concepts that benefit from grounding |
| **Causal** | Errors, fallacies, consequences |
| **Normative** | Values, virtues, principles |
| **Historical/personal** | Biographical, dates, recollections |
| **Domain vocabulary** | Always — precision matters |
| **Contrast/distinction** | When the concept is often confused with another |

---

## Examples

### Conceptual query — "context dropping"

```
The epistemological error of context dropping: ignoring or evading relevant
context when forming judgments or evaluating ideas.

What is context dropping? Examples of context dropping in philosophy and
everyday reasoning. How does dropping context lead to invalid conclusions?
The importance of maintaining full context in thought. Context dropping as
a form of evasion. Stolen concept and context dropping.
```

### Factual/biographical query — "when Peikoff recollects Ayn Rand finishing Galt's Speech"

```
When did Ayn Rand finish writing Galt's Speech in Atlas Shrugged?
Leonard Peikoff's personal recollection of the date or time period when
Ayn Rand completed John Galt's speech. How long did it take to write.
Peikoff reminiscences about Ayn Rand writing process.
```

### Applied/practical query — "how to handle disagreements with friends"

```
Handling disagreements and conflicts with friends from an Objectivist
perspective. How should a rational person respond to value conflicts with
close friends? The role of honesty, benevolence, and self-interest in
friendships. When is it appropriate to end a friendship? Ayn Rand or
Peikoff on personal relationships and conflict.
```

---

## Why This Works

1. **Semantic expansion** — Gemini uses vector embeddings; related terms improve matching
2. **Multiple angles** — Definition + examples + consequences = better retrieval
3. **Question formation** — Explicit questions guide Gemini's synthesis
4. **Domain vocabulary** — Proper Objectivist terminology improves precision
