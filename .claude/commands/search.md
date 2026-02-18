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

Do NOT pass `$ARGUMENTS` directly. First, read the template file:

```
.claude/commands/query-expansion-template.md
```

Then apply it to craft a richer semantic query.

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
