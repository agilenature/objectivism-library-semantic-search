# Commands Reference

Complete reference for all `objlib` CLI commands.

> **Important:** The `--store` option has two different positions depending on the command:
> - `search`: `python -m objlib --store NAME search "query"` (before subcommand)
> - `view --show-related`: `objlib view "file.txt" --show-related --store NAME` (after subcommand)

---

## Global Options

These options apply to commands that use the Gemini client (currently only `search`).

| Option | Default | Description |
|--------|---------|-------------|
| `--store, -s` | `objectivism-library-v1` | Gemini File Search store display name |
| `--db, -d` | `data/library.db` | Path to SQLite database |

---

## `scan`

Discover files, extract metadata from folder/filename structure, and persist to SQLite.

```bash
objlib scan [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--library, -l PATH` | _(required)_ | Path to library root directory |
| `--db, -d PATH` | `data/library.db` | Path to SQLite database |
| `--config, -c PATH` | _(none)_ | Path to scanner config JSON |
| `--verbose, -v` | `False` | Show individual file changes |

**Example:**
```bash
objlib scan --library "/Volumes/U32 Shadow/Objectivism Library" --verbose
```

**Output:** Table of new/modified/deleted/unchanged counts, then totals by status and metadata quality.

---

## `status`

Display database statistics without scanning.

```bash
objlib status [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--db, -d PATH` | `data/library.db` | Path to SQLite database |

**Example:**
```bash
objlib status
```

---

## `purge`

Remove `LOCAL_DELETE` records older than N days from the database.

```bash
objlib purge [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--older-than N` | `30` | Only purge records older than N days |
| `--yes, -y` | `False` | Skip confirmation prompt |
| `--db, -d PATH` | `data/library.db` | Path to SQLite database |

**Example:**
```bash
objlib purge --older-than 60 --yes
```

---

## `upload`

Upload pending `.txt` files to Gemini File Search (basic, without AI metadata).

```bash
objlib upload [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--store, -s NAME` | `objectivism-library-v1` | Gemini store display name |
| `--db, -d PATH` | `data/library.db` | Database path |
| `--batch-size, -b N` | `150` | Files per logical batch |
| `--concurrency, -n N` | `7` | Max concurrent uploads |
| `--dry-run` | `False` | Preview without uploading |

**Example:**
```bash
objlib upload --store objectivism-library-test --dry-run
objlib upload --store objectivism-library-test --batch-size 100
```

---

## `enriched-upload`

Upload files with enriched 4-tier AI metadata and entity mentions. Requires AI metadata extraction (Phase 6) and entity extraction (Phase 6.1) to be complete.

```bash
objlib enriched-upload [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--store, -s NAME` | `objectivism-library-test` | Gemini store display name |
| `--db, -d PATH` | `data/library.db` | Database path |
| `--batch-size, -b N` | `100` | Files per batch |
| `--concurrency, -n N` | `2` | Max concurrent uploads (conservative) |
| `--dry-run` | `False` | Preview without uploading |
| `--limit, -l N` | `0` | Max files (0 = all) |
| `--include-needs-review / --exclude-needs-review` | include | Include low-confidence files |
| `--reset-existing / --no-reset-existing` | reset | Delete and re-upload already-uploaded files |

**Three-stage testing workflow:**
```bash
objlib enriched-upload --limit 20       # Stage 1: Validate metadata schema
objlib enriched-upload --limit 100      # Stage 2: Validate search quality
objlib enriched-upload --limit 250      # Stage 3: Validate at scale
objlib enriched-upload                  # Full upload
```

---

## `sync`

Detect changes in the library directory and update the Gemini store incrementally. Requires disk access.

```bash
objlib sync [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--library, -l PATH` | _(config default)_ | Path to library root directory |
| `--store, -s NAME` | `objectivism-library-test` | Gemini store display name |
| `--db, -d PATH` | `data/library.db` | Database path |
| `--force` | `False` | Re-process all files regardless of change detection |
| `--skip-enrichment` | `False` | Use simple upload pipeline instead of enriched |
| `--dry-run` | `False` | Preview changes without executing |
| `--prune-missing` | `False` | Delete files missing >7 days from Gemini store |
| `--cleanup-orphans` | `False` | Remove orphaned Gemini entries left by interrupted uploads |

**Disk required:** sync checks disk availability at startup and aborts with a clear error if the library disk is disconnected.

**Change detection:** mtime-optimized — skips SHA-256 hash for files whose filesystem timestamp is unchanged. On hash change, uploads new version first (upload-first atomicity), then removes old store entry.

**Missing files:** deleted files are marked `status='missing'` with a `missing_since` timestamp — not auto-deleted from Gemini. Use `--prune-missing` to delete entries older than 7 days.

**Library config:** on first sync, stores the store display name in SQLite. Subsequent syncs abort if the store name changes (prevents accidental cross-store operations).

**Examples:**
```bash
objlib sync --dry-run                                          # Preview changes
objlib sync --library "/Volumes/U32 Shadow/Objectivism Library"  # Full sync
objlib sync --force                                             # Re-process all files
objlib sync --skip-enrichment                                   # Simple metadata only
objlib sync --prune-missing                                     # Clean up old missing entries
objlib sync --dry-run --cleanup-orphans                         # Preview orphan cleanup
```

---

## `search`

Semantic search across the library.

```bash
python -m objlib --store STORE_NAME search QUERY [OPTIONS]
```

> **Note:** `--store` must come **before** `search` in the command.

| Option | Default | Description |
|--------|---------|-------------|
| `QUERY` | _(required)_ | Search query (positional argument) |
| `--filter, -f FIELD:VALUE` | _(none)_ | Metadata filter (repeatable) |
| `--limit, -l N` | `10` | Max results to display |
| `--model, -m NAME` | `gemini-2.5-flash` | Gemini model for search |
| `--synthesize` | `False` | Generate multi-document synthesis |
| `--rerank / --no-rerank` | `--rerank` | Rerank with Gemini Flash |
| `--expand / --no-expand` | `--expand` | Expand query with synonyms |
| `--track-evolution` | `False` | Group by difficulty progression |
| `--mode learn\|research` | `learn` | Result ordering mode |
| `--debug` | `False` | Write debug log to `~/.objlib/debug.log` |

**Filterable fields:** `category`, `course`, `difficulty`, `quarter`, `date`, `year`, `week`, `quality_score`

**Examples:**
```bash
# Basic search
python -m objlib --store objectivism-library-test search "What is the Objectivist view of rights?"

# With synthesis
python -m objlib --store objectivism-library-test search "free will" --synthesize

# With metadata filter
python -m objlib --store objectivism-library-test search "causality" --filter "course:OPAR"

# Multiple filters
python -m objlib --store objectivism-library-test search "egoism" \
  --filter "difficulty:introductory" --filter "category:course"

# Research mode (pure relevance)
python -m objlib --store objectivism-library-test search "stolen concept" --mode research

# Track how concept develops
python -m objlib --store objectivism-library-test search "volition" --track-evolution

# Debug expansion
python -m objlib --store objectivism-library-test search "altruism" --debug
```

---

## `view`

View detailed metadata about a document by filename.

```bash
objlib view FILENAME [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `FILENAME` | _(required)_ | Filename (e.g., `Introduction to Objectivism.txt`) |
| `--full` | `False` | Show full document text |
| `--show-related` | `False` | Find semantically related documents |
| `--limit, -l N` | `5` | Max related results |
| `--model, -m NAME` | `gemini-2.5-flash` | Gemini model |
| `--db, -d PATH` | `data/library.db` | Database path |
| `--store, -s NAME` | `objectivism-library-v1` | Store name (for `--show-related` only) |

> **Note:** `--store` comes **after** `view` (not before).

**Examples:**
```bash
# Basic view (metadata only, fast, no API)
objlib view "OPAR Lecture 4 - The Nature of Reason.txt"

# View full document text
objlib view "OPAR Lecture 4 - The Nature of Reason.txt" --full

# Find related documents
objlib view "OPAR Lecture 4 - The Nature of Reason.txt" --show-related --store objectivism-library-test
```

---

## `browse`

Navigate the library structure hierarchically.

```bash
objlib browse [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--category, -c NAME` | _(none)_ | Filter by category (`course`, `book`, `motm`, etc.) |
| `--course NAME` | _(none)_ | Show files in a specific course |
| `--year, -y YEAR` | _(none)_ | Filter by year (within a course) |
| `--db, -d PATH` | `data/library.db` | Database path |

**Progressive drill-down:**
```bash
objlib browse                              # Show top-level categories
objlib browse --category course            # List all courses with file counts
objlib browse --course "OPAR"              # Show files in OPAR
objlib browse --course "OPAR" --year 2023  # Filter by year
objlib browse --category book              # Show all books
```

---

## `filter`

List files matching metadata filters (SQLite only, no Gemini API call).

```bash
objlib filter FIELD:VALUE [FIELD:VALUE ...] [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `FIELD:VALUE` | _(required)_ | One or more filters (positional) |
| `--limit, -l N` | `50` | Max results |
| `--db, -d PATH` | `data/library.db` | Database path |

**Comparison operators:** `field:value` (exact), `field:>value`, `field:>=value`, `field:<value`, `field:<=value`

**Filterable fields:** `category`, `course`, `difficulty`, `quarter`, `date`, `year`, `week`, `quality_score`

**Examples:**
```bash
objlib filter course:OPAR
objlib filter course:OPAR year:2023
objlib filter year:>=2020 difficulty:introductory
objlib filter quality_score:>=75
```

---

## `config` Commands

Manage API keys stored in the system keyring.

```bash
objlib config set-api-key KEY        # Store Gemini API key
objlib config get-api-key            # Show masked Gemini API key
objlib config remove-api-key         # Delete Gemini API key

objlib config set-mistral-key KEY    # Store Mistral API key
objlib config get-mistral-key        # Show masked Mistral API key
objlib config remove-mistral-key     # Delete Mistral API key
```

Keyring service names: `objlib-gemini` (Gemini), `objlib-mistral` (Mistral).

---

## `metadata` Commands

Manage AI-extracted metadata from Mistral Batch API.

### `metadata batch-extract`

**Preferred method.** Submits all pending files as a single Mistral Batch API job. 50% cheaper than synchronous, no rate limiting.

```bash
objlib metadata batch-extract [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--max, -n N` | _(all)_ | Max files to process |
| `--name NAME` | _(auto)_ | Descriptive job name |
| `--poll, -p SECS` | `30` | Seconds between status checks |
| `--db, -d PATH` | `data/library.db` | Database path |

```bash
objlib metadata batch-extract
objlib metadata batch-extract --max 50
```

### `metadata extract`

Synchronous Wave 2 production extraction (rate-limited). Use `batch-extract` instead.

```bash
objlib metadata extract [--resume] [--dry-run] [--set-pending]
```

### `metadata review`

Review AI-extracted metadata.

```bash
objlib metadata review [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--status STATUS` | _(all)_ | Filter: `extracted`, `needs_review`, `approved` |
| `--interactive, -i` | `False` | Interactive review (Accept/Edit/Rerun/Skip/Quit) |
| `--limit, -l N` | `50` | Max files to display |

```bash
objlib metadata review
objlib metadata review --status needs_review --interactive
```

### `metadata approve`

Auto-approve extracted metadata above a confidence threshold.

```bash
objlib metadata approve [--min-confidence 0.85] [--yes]
```

### `metadata stats`

Show extraction status distribution and coverage percentage.

```bash
objlib metadata stats
```

### `metadata show` / `update` / `batch-update`

Manual metadata management for individual files or batches.

```bash
objlib metadata show "filename.txt"
objlib metadata update "filename.txt" --category course --course OPAR
objlib metadata batch-update '%Q and A%' --category qa_session --set-pending
```

### Wave 1 Commands (strategy evaluation)

```bash
objlib metadata extract-wave1 [--resume]    # Run 3 strategies x 20 test files
objlib metadata wave1-report                # Compare strategy results
objlib metadata wave1-select STRATEGY       # Choose winning strategy
```

---

## `entities` Commands

Extract and manage person entity mentions.

### `entities extract`

```bash
objlib entities extract [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--mode MODE` | `pending` | `pending`, `backfill`, `force`, `upgrade` |
| `--limit, -l N` | `500` | Max files |
| `--library-root PATH` | `/Volumes/U32 Shadow/Objectivism Library` | Library root |
| `--use-llm` | `False` | Enable Mistral LLM fallback for 80–91 fuzzy range |

```bash
objlib entities extract
objlib entities extract --mode force --limit 100
```

### `entities stats`

Show entity extraction coverage, person frequency table, error counts.

```bash
objlib entities stats
```

### `entities report`

Report on entity mentions for a specific person, or review low-confidence entities.

```bash
objlib entities report "Leonard Peikoff"
objlib entities report Peikoff
objlib entities report --low-confidence
```

---

## `session` Commands

Manage research sessions.

### `session start`

```bash
objlib session start [NAME]
```

Creates a new session and prints the UUID. Set `OBJLIB_SESSION` to auto-attach searches.

### `session list`

```bash
objlib session list
```

### `session resume`

```bash
objlib session resume SESSION_ID_PREFIX
```

Displays the full timeline of a past session.

### `session note`

```bash
objlib session note "Your observation"
```

Requires `OBJLIB_SESSION` env var to be set.

### `session export`

```bash
objlib session export SESSION_ID_PREFIX [--output path/to/file.md]
```

---

## `glossary` Commands

Manage the query expansion glossary.

### `glossary list`

```bash
objlib glossary list
```

### `glossary add`

```bash
objlib glossary add "TERM" "synonym1" "synonym2"
```

### `glossary suggest`

```bash
objlib glossary suggest "TERM"
```

Uses Gemini Flash to suggest synonyms (requires Gemini API key).

---

## `tui`

Launch the interactive Textual terminal UI for live search, browsing, and session management.

```bash
objlib tui
```

No options — uses the default store (`objectivism-library-test`) and database (`data/library.db`). Requires the Gemini API key to be set in the system keyring (`objlib config set-api-key`).

**Keyboard shortcuts inside the TUI:**

| Key | Action |
|-----|--------|
| `/` | Focus search bar |
| `Escape` | Clear search / close modal |
| `Enter` | Select result / confirm |
| `↑` / `↓` | Navigate results / history |
| `Ctrl+P` | Open command palette |
| `Ctrl+B` | Toggle bookmark on selected result |
| `Ctrl+N` | New session |
| `Ctrl+S` | Save session |
| `Ctrl+L` | Load last session |
| `Ctrl+Y` | Synthesize results (multi-doc answer) |
| `q` / `Ctrl+Q` | Quit |

---

## `logs`

Browse TUI session logs from the `logs/` directory.

```bash
objlib logs [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--trace, -t TEXT` | _(none)_ | Filter to a specific trace ID (prefix match) |
| `--level, -l TEXT` | _(none)_ | Minimum log level (DEBUG, INFO, WARNING, ERROR) |
| `--since, -s DATE` | _(none)_ | Show logs from this date onward (YYYY-MM-DD) |
| `--tail, -n N` | `0` (all) | Show only the last N entries |

Reads all JSON-lines log files matching `logs/tui-*.log`. Renders a Rich table with columns: **Timestamp**, **Level**, **Trace** (first 8 chars), **Message**.

**Examples:**
```bash
objlib logs                          # All log entries
objlib logs --level ERROR            # Errors only
objlib logs --trace abcd1234         # One trace
objlib logs --since 2026-02-18       # Today's entries
objlib logs --tail 50                # Last 50 entries
```

**Log format:** Each line in `logs/tui-YYYYMMDD.log` is a JSON object:
```json
{"ts": "2026-02-18T12:34:56", "level": "INFO", "logger": "objlib.tui", "trace": "...", "span": "...", "msg": "search requested query='virtue'"}
```

---

_Last updated: Phase 7 — tui (interactive terminal UI) and logs (JSON-lines log viewer) commands_
