# Claude Code Configuration

This directory contains Claude Code configuration and custom skills for the Objectivism Library Semantic Search project.

## Custom Commands

### `/search` - Semantic Search Command

Search the Objectivism Library using Gemini File Search.

**Usage:**
```
/search what is context dropping?
/search explain the trader principle
/search when did Ayn Rand finish Galt's speech?
```

**What it does:**
1. Executes semantic search against 1,748 enriched library files
2. Returns AI-synthesized answer from multiple sources
3. Shows citations with metadata (course, year, relevance)
4. Allows drilling down into specific sources

**Implementation:**
- Command file: `.claude/commands/search.md`
- Uses `$ARGUMENTS` to pass your query
- Executes: `python -m objlib --store objectivism-library-test search "$ARGUMENTS"`

**Features:**
- ✅ Semantic retrieval using vector embeddings
- ✅ AI-synthesized comprehensive answers
- ✅ Multi-source citations
- ✅ Follow-up questions supported
- ✅ Can view full source context on request

---

## Project Structure

```
.claude/
├── README.md          ← This file
├── commands/
│   └── search.md      ← /search command definition
└── projects/
    └── -Users-david-projects-objectivism-library-semantic-search/
        └── memory/
            └── MEMORY.md  ← Persistent project memory
```

## How Commands Work

Claude Code looks for command definitions in:
- **Project commands**: `.claude/commands/` (this project only)
- **Global commands**: `~/.claude/commands/` (all projects)

Commands are simple Markdown files with:
- The prompt/instructions
- Optional `$ARGUMENTS` placeholder for parameters

Example: `/search what is evasion?`
→ Runs `.claude/commands/search.md` with `$ARGUMENTS = "what is evasion?"`

## Memory System

The `memory/MEMORY.md` file contains critical project knowledge that persists across conversations:
- CLI command syntax (--store parameter positions)
- Common issues and solutions
- Project structure and decisions
- Bug fixes and workarounds

Claude Code automatically loads this memory at the start of each session.

---

## Usage Tips

### Quick Search
Use `/search` for any question about Objectivist philosophy:
- Definitions and concepts
- Historical facts and dates
- Examples and applications
- Philosophical principles
- Ayn Rand's writings

### View Source Details
After a search, ask Claude to view specific sources:
```
Can you show me the full context from source [2]?
```

### Follow-up Questions
Ask related questions in the same conversation:
```
/search context dropping
[results shown]
Can you give me more examples of context dropping?
```

---

## Technical Details

**Store:** objectivism-library-test (Gemini File Search)
**Files:** 1,748 enriched transcripts, books, lectures
**Metadata:** AI-generated summaries, topics, difficulty, entities
**Database:** data/library.db (SQLite)
**API:** Google Gemini File Search API

**Search Quality:**
- Average confidence: 67%
- Multi-source synthesis
- Domain-specific vocabulary
- Hierarchical topic structure

---

## Troubleshooting

If `/search` doesn't work:
1. Check API key: `keyring get objlib-gemini api_key`
2. Verify database: `python -m objlib status`
3. Test manually: `./scripts/qsearch "test query"`

For detailed logs, see `logs/` directory.
