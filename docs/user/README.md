# User Documentation

This directory contains end-user documentation for the Objectivism Library CLI (`objlib`).

## Quick Start

```bash
# 1. Install and configure
pip install -e .
objlib config set-api-key YOUR_GEMINI_KEY
objlib config set-mistral-key YOUR_MISTRAL_KEY

# 2. Scan your library
objlib scan --library "/Volumes/U32 Shadow/Objectivism Library"

# 3. Search
python -m objlib --store objectivism-library-test search "What is the Objectivist view of rights?"
```

## Contents

| File | Description |
|------|-------------|
| [commands-reference.md](commands-reference.md) | Complete CLI reference — all commands, options, and examples |
| [search-guide.md](search-guide.md) | In-depth guide to search features: expansion, reranking, synthesis, filters |
| [session-guide.md](session-guide.md) | Research sessions: starting, tracking, exporting |
| [glossary-guide.md](glossary-guide.md) | Objectivist terminology glossary for query expansion |

## Command Groups at a Glance

| Group | Purpose |
|-------|---------|
| _(root)_ | `scan`, `status`, `purge`, `upload`, `enriched-upload`, `search`, `view`, `browse`, `filter` |
| `config` | API key management |
| `metadata` | AI metadata extraction and review |
| `entities` | Person entity extraction |
| `session` | Research session management |
| `glossary` | Query expansion glossary |

## Key Notes

- The `--store` option position matters: **before** the subcommand for `search`, **after** for `view --show-related`. See [commands-reference.md](commands-reference.md) for details.
- API keys are stored in the system keyring, never in config files.
- Use `python -m objlib` (or `objlib` after install) to invoke the CLI.

---

_Last updated: Phase 4 — Session manager, reranking, synthesis, query expansion_
