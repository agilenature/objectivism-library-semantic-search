Search the Objectivism Library for: $ARGUMENTS

---

## My Query Workflow

### Phase 1: Understand the Request

Given the user's query `$ARGUMENTS`, identify:
1. **Core concept** — What is the main topic?
2. **Intent** — Definition? Examples? Historical fact? Practical application?
3. **Domain** — This is Objectivist philosophy; use philosophical precision and terminology.

---

### Phase 2: Expand the Query (CRITICAL)

Do NOT pass `$ARGUMENTS` directly. Apply the expansion template below to craft a richer semantic query.

#### Query Expansion Template

```
{CORE CONCEPT}: {brief philosophical definition or framing}

What is {CORE CONCEPT}? {alternative phrasings or related terms}

Examples of {CORE CONCEPT} in {philosophy / everyday reasoning / politics / aesthetics}.

{Causal question}: How does {CORE CONCEPT} lead to {consequence}?

{Normative question}: Why is {CORE CONCEPT} {important / an error / valid}?

{Domain vocabulary}: {2-3 Objectivist terms related to the concept}
```

#### Why this works:
- **Semantic expansion** — Gemini uses vector embeddings; related terms improve matching
- **Multiple angles** — Definition + examples + consequences = better retrieval
- **Question formation** — Explicit questions guide Gemini's synthesis
- **Domain vocabulary** — Proper Objectivist terminology improves precision

#### Example — User asks: "context dropping"

Expanded query:
```
The epistemological error of context dropping: ignoring or evading relevant
context when forming judgments or evaluating ideas.

What is context dropping? Examples of context dropping in philosophy and
everyday reasoning. How does dropping context lead to invalid conclusions?
The importance of maintaining full context in thought. Context dropping as
a form of evasion. Stolen concept and context dropping.
```

#### Example — User asks: "find where Peikoff recollects when Ayn Rand finished writing Galt's Speech"

Expanded query:
```
When did Ayn Rand finish writing Galt's Speech in Atlas Shrugged?
Leonard Peikoff's personal recollection of the date or time period when
Ayn Rand completed John Galt's speech. How long did it take to write.
Peikoff reminiscences about Ayn Rand writing process.
```

---

### Phase 3: Execute

Use the expanded query. Remember: `--store` MUST come BEFORE the `search` subcommand.

```bash
python -m objlib --store objectivism-library-test search "<expanded query>"
```

---

### Phase 4: Analyze the Response

Examine:
1. **Answer quality** — Is it comprehensive? Does it directly address the intent?
2. **Sources** — How many cited? Books vs. lectures vs. Q&A sessions?
3. **Coverage** — Are multiple sources corroborating, or is this a single-source answer?

---

### Phase 5: Present Results

1. **Lead with the synthesized answer** — Organized by key points or themes
2. **Highlight notable quotes or distinctions** from the sources
3. **Show the sources table** — File, Course, Year
4. **Offer to drill down** — "Would you like the full context from source [X]?"
