---
name: search
description: Search the Objectivism Library using Gemini File Search
argument-hint: <query>
allowed-tools:
  - Bash
  - Read
---

Search the Objectivism Library using Gemini File Search for: $ARGUMENTS

Execute the following command to search the library:
```bash
python -m objlib --store objectivism-library-test search "$ARGUMENTS"
```

After receiving the results:
1. Present the synthesized answer clearly
2. Show the sources cited
3. Highlight key points from the answer
4. Offer to view full source context if the user wants more detail

The search will query 1,748 enriched files (books, lectures, courses) and return an AI-synthesized answer with citations.
