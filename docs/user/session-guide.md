# Research Sessions Guide

Research sessions let you track your exploration of the library: every search, document view, and synthesis is logged automatically so you can review your work, add notes, and export a report.

## What Sessions Are For

When researching a philosophical topic across multiple searches, it's easy to lose track of what you found. Sessions solve this by:

- Automatically logging every search query, its results, and any synthesis generated
- Letting you add free-text notes ("This passage contradicts what I read earlier")
- Providing a timeline you can review when you resume later
- Exporting your entire research trail to a Markdown file for sharing or archiving

## Starting a Session

```bash
# Auto-generated name ("Session 2026-02-18 14:30")
objlib session start

# Named session
objlib session start "Free Will Research"
```

Output:
```
╭─ Session Created ─────────────────────────────────────────────────╮
│ Session ID: a1b2c3d4-...                                           │
│ Name: Free Will Research                                           │
│                                                                    │
│ To auto-attach searches:                                           │
│ export OBJLIB_SESSION=a1b2c3d4-...                                 │
╰───────────────────────────────────────────────────────────────────╯
```

## Auto-Attaching Searches

Set the `OBJLIB_SESSION` environment variable so all subsequent searches are automatically logged to your session:

```bash
export OBJLIB_SESSION=a1b2c3d4-e5f6-...

# All searches now log to this session automatically
python -m objlib --store objectivism-library-test search "rational self-interest"
python -m objlib --store objectivism-library-test search "egoism" --synthesize
```

You don't need to do anything else — logging happens silently in the background. If session logging fails for any reason, the search still completes normally.

## What Gets Logged Automatically

| Event Type | Triggered By | Data Stored |
|------------|-------------|-------------|
| `search` | Any `search` command | query, expanded query, result count, top doc IDs |
| `synthesize` | `search --synthesize` | query, number of synthesis claims |
| `view` | `view` command (when session is active) | filename viewed |
| `note` | `session note` | your note text |
| `error` | Internal errors | error message (best-effort) |

## Adding Notes

Add a free-text note to the active session at any time:

```bash
objlib session note "The OPAR lecture 4 passage on volition is the clearest explanation I've found"
objlib session note "Question: how does this relate to the metaphysics of free will?"
```

Requires `OBJLIB_SESSION` to be set. Notes appear in the timeline with a timestamp.

## Listing Sessions

```bash
objlib session list
```

Output:
```
╭─ Research Sessions ───────────────────────────────────────────────╮
│ ID       │ Name                │ Created    │ Events               │
│ a1b2c3d4 │ Free Will Research  │ 2026-02-18 │ 12                   │
│ b2c3d4e5 │ Ethics Overview     │ 2026-02-17 │ 8                    │
╰───────────────────────────────────────────────────────────────────╯
```

The ID column shows only the first 8 characters — you can use this prefix to identify sessions.

## Resuming a Session

Display the full timeline of a past session:

```bash
# Using ID prefix (first 8+ chars)
objlib session resume a1b2c3d4

# Using full UUID
objlib session resume a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

The timeline shows each event with timestamp, type, and key details:

```
╭─ Free Will Research ──────────────────────────────────────────────╮
│ 2026-02-18 14:30  search    "What is volition?" → 8 results       │
│ 2026-02-18 14:31  note      "OPAR lecture is clearest"            │
│ 2026-02-18 14:35  search    "free will determinism" → 6 results   │
│ 2026-02-18 14:36  synthesize "free will determinism" 5 claims     │
╰───────────────────────────────────────────────────────────────────╯
```

After reviewing the timeline, re-export the `OBJLIB_SESSION` variable to continue adding to the session:
```bash
export OBJLIB_SESSION=a1b2c3d4-e5f6-...
```

## Exporting to Markdown

Export a session as a Markdown document for sharing or archiving:

```bash
# Auto-named output file (e.g., session-a1b2c3d4.md)
objlib session export a1b2c3d4

# Specify output path
objlib session export a1b2c3d4 --output ~/research/free-will-notes.md
```

The exported Markdown includes the session name, all events in chronological order, and your notes formatted as callout blocks.

## Tips

- **One session per research topic.** Keep separate sessions for "Free Will," "Concept Formation," "Ethics Overview" etc. so timelines stay focused.
- **Add notes immediately.** The best time to note an insight is right after finding it.
- **Export before a long break.** The Markdown export is a portable record that doesn't depend on the database.
- **Sessions are append-only.** Events can never be deleted — this is intentional for research integrity.

---

_Last updated: Phase 4 — Session manager with CRUD, event logging, timeline, Markdown export_
