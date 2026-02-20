# Glossary Guide

The glossary is a curated list of Objectivist philosophy terms and their synonyms. It is used by the `search` command to automatically expand queries with related terminology, improving recall without requiring the user to know all synonyms.

## How the Glossary Works

When you search for a term like `"egoism"`, the glossary engine:
1. Scans your query for known terms (longest phrases first, to avoid partial matches)
2. Appends the top 2 synonyms for each matched term
3. Sends the expanded query to Gemini

The original matched term is also boosted (appears twice in the expanded query) to ensure it remains the primary focus.

**Example:**
- Your query: `"What is egoism?"`
- Expanded: `"What is egoism? egoism rational self-interest selfishness"`

The CLI shows the expansion inline: `Expanded: egoism -> rational self-interest, selfishness`

## Viewing the Glossary

```bash
objlib glossary list
```

Output shows all terms and their synonyms in a table:

```
╭─ Query Expansion Glossary ────────────────────────────────────────╮
│ Term                   │ Synonyms                                  │
│ altruism               │ self-sacrifice, selflessness              │
│ atlas shrugged         │ Atlas Shrugged, Who is John Galt          │
│ axioms                 │ axiomatic concepts, self-evident truths   │
│ capitalism             │ laissez-faire, free market                │
│ ...                    │ ...                                       │
╰───────────────────────────────────────────────────────────────────╯
```

## Current Glossary Terms

The glossary covers five categories:

### Metaphysics & Epistemology
- `existence` → being, reality
- `identity` → law of identity, A is A
- `consciousness` → awareness, cognition
- `causality` → causation, cause and effect
- `epistemology` → theory of knowledge, cognition
- `reason` → rationality, rational faculty
- `concept formation` → abstraction, unit economy
- `objectivity` → objective knowledge, volitional adherence to reality
- `free will` → volition, volitional consciousness
- `axioms` → axiomatic concepts, self-evident truths

### Ethics
- `rational self-interest` → egoism, ethical egoism
- `egoism` → rational self-interest, selfishness
- `altruism` → self-sacrifice, selflessness
- `virtue` → moral virtue, moral character
- `pride` → moral ambitiousness, self-esteem
- `justice` → moral judgment, judging character
- `honesty` → refusal to fake reality, integrity
- `independence` → independent judgment, intellectual independence
- `productiveness` → productive work, productive achievement
- `integrity` → loyalty to values, moral consistency
- `selfishness` → rational self-interest, egoism
- `happiness` → moral purpose, flourishing
- `rights` → individual rights, natural rights

### Politics & Economics
- `capitalism` → laissez-faire, free market
- `individualism` → individual sovereignty, individual rights
- `collectivism` → statism, socialism
- `property rights` → right to property, private property
- `government` → proper government, limited government
- `force` → coercion, initiation of force
- `trader principle` → voluntary exchange, mutual benefit

### Aesthetics
- `romantic realism` → Objectivist aesthetics, art as sense of life
- `sense of life` → metaphysical value-judgments, subconscious philosophy

### Errors & Fallacies
- `mysticism` → faith-based belief, irrationalism
- `determinism` → causal determinism, fatalism
- `subjectivism` → relativism, emotionalism
- `intrinsicism` → intrinsic value theory, intrinsic theory
- `context dropping` → evasion, stolen concept
- `stolen concept` → fallacy of the stolen concept, concept stealing
- `package dealing` → false alternative, false dichotomy
- `primacy of consciousness` → consciousness primacy, idealism
- `primacy of existence` → existence primacy, metaphysical realism

### Key Works
- `OPAR` → Objectivism: The Philosophy of Ayn Rand, Peikoff
- `ITOE` → Introduction to Objectivist Epistemology, concept formation
- `the virtue of selfishness` → Objectivist ethics, rational selfishness
- `atlas shrugged` → Atlas Shrugged, Who is John Galt
- `the fountainhead` → The Fountainhead, Howard Roark

## Adding Terms

```bash
objlib glossary add "TERM" "synonym1" "synonym2" "synonym3"
```

**Example — adding a new term:**
```bash
objlib glossary add "measurement omission" "abstraction" "concept formation" "unit economy"
```

Terms are automatically lowercased. The glossary file (`src/objlib/search/synonyms.yml`) is updated in place.

**Important:** Keep synonyms philosophically precise. Avoid over-broad synonyms that could cause semantic drift (e.g., don't map "reason" to "logic" without verifying the philosophical usage matches).

## Getting AI Suggestions

Use Gemini Flash to suggest synonyms for a term you want to add:

```bash
objlib glossary suggest "measurement omission"
```

Output:
```
╭─ Suggestions for: measurement omission ───────────────────────────╮
│   abstraction                                                      │
│   concept formation                                                │
│   unit economy                                                     │
│   epistemological reduction                                        │
╰───────────────────────────────────────────────────────────────────╯

To add: objlib glossary add "measurement omission" "abstraction" "concept formation"
```

Review the suggestions and add only the ones that are accurate for Objectivist philosophy. The `suggest` command provides a starting point, not a final answer.

## Disabling Expansion

If you want to search with exact terms only (no expansion), use `--no-expand`:

```bash
python -m objlib --store objectivism-library-test search "egoism" --no-expand
```

---

_Last updated: Phase 4 — Query expansion engine with curated glossary_
