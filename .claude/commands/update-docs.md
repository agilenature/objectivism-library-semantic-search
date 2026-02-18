Update the project documentation in `docs/` to reflect what changed in the most recently completed execution phase.

Optional argument: phase description override (e.g., "Phase 5 — Incremental Updates"). If omitted, auto-detect from `.planning/STATE.md`.

---

## Step 1: Identify the Completed Phase

Read `.planning/STATE.md` to find:
- Which phase just completed (e.g., "Phase 5")
- The phase name/description
- What the last plan summary says was built

Also read the most recent `SUMMARY.md` from the relevant phase directory under `.planning/phases/` to understand exactly what was added or changed.

If `$ARGUMENTS` was provided, use that as the phase label for "Last updated" footers instead.

---

## Step 2: Audit Each Doc Against the Codebase

For each of the four docs below, compare the **current doc content** against the **current source code**. Only update a doc if there is a genuine difference (new command, new table, new module, changed pipeline stage). Do not make cosmetic changes.

### `docs/user/commands-reference.md`

Read `src/objlib/cli.py` in full. Compare against the commands already documented.

Check for:
- Any new `@app.command()`, `@metadata_app.command()`, `@entities_app.command()`, `@session_app.command()`, or `@glossary_app.command()` decorators that are not yet in the reference
- Any new options on existing commands
- Any commands that were removed or renamed

If differences found: add/update/remove the relevant sections. Follow the existing format (options table + example invocations).

### `docs/architecture/data-pipeline.md`

Read `src/objlib/` — specifically:
- `upload/orchestrator.py` for upload pipeline changes
- `search/client.py`, `search/reranker.py`, `search/synthesizer.py`, `search/expansion.py` for search pipeline changes
- `scanner.py` for scan stage changes
- `extraction/batch_orchestrator.py` for metadata stage changes

Check for: new pipeline stages, changed stage ordering, new substeps within existing stages, new data flowing through the pipeline.

If differences found: update the relevant stage description. Add a new stage section if an entirely new pipeline stage was added.

### `docs/architecture/module-map.md`

Run: list all files under `src/objlib/` using Glob.

Compare against modules already documented. Check for:
- New `.py` files or subdirectories not yet in the map
- New key methods added to existing modules
- Modules that were restructured or removed

If differences found: add new module entries or update existing entries with new key methods/responsibilities.

### `docs/architecture/database-schema.md`

Read `src/objlib/database.py` — specifically `SCHEMA_SQL`, `MIGRATION_V3_SQL`, `MIGRATION_V4_SQL`, `MIGRATION_V6_SQL`, and any new `MIGRATION_VN_SQL` constants added since the last update.

Also check `_setup_schema()` for any new version blocks (e.g., `if version < 7:`).

Check for:
- New tables not yet documented
- New columns added to existing tables via ALTER TABLE
- New indexes or triggers
- A new migration version block

If differences found: add the new table/column/index documentation. Update the migration history table at the top of the schema doc.

---

## Step 3: Update "Last Updated" Footers

For every doc file you modified, update the last line:

```
_Last updated: Phase X — [brief description of what changed]_
```

Use the phase label from Step 1 (or `$ARGUMENTS` if provided).

For doc files you did NOT modify (no actual changes needed), leave their footer unchanged.

---

## Step 4: Report What Changed

After completing all edits, print a concise summary:

```
## Docs Update Complete

Phase: [phase label]

Updated:
- docs/user/commands-reference.md — [what was added/changed]
- docs/architecture/data-pipeline.md — [what was added/changed]

No changes needed:
- docs/architecture/module-map.md
- docs/architecture/database-schema.md
```

If no docs needed updating at all, say so explicitly.

---

## Step 5: Canon.json Layer 1 Audit

After updating documentation, perform a lightweight Canon governance check to detect drift between `Canon.json` and the actual codebase structure.

**If `Canon.json` exists at project root:**

1. Read Canon.json `folders` and `excludeFolders` arrays
2. Scan source directories (e.g., `src/objlib/` and its subdirectories)
3. Check for:
   - Directories in the source tree that are NOT in `folders` AND NOT in `excludeFolders` and are not `__pycache__` directories (report as "unclassified")
   - Directories in `folders` that no longer exist on the filesystem (report as "stale public folder")
4. If drift detected: add a "Canon Drift Found" section to the Step 4 report listing each issue, e.g.:
   ```
   Canon Drift Found:
   - Unclassified: src/objlib/newmodule/ (not in folders or excludeFolders)
   - Stale: src/objlib/removed/ (in folders but does not exist)
   ```
5. If no drift detected: add "Canon.json: no drift detected" to the report

**If `Canon.json` does not exist:** Skip this step silently.

This is a lightweight read-only check. It does NOT modify Canon.json. For a full audit with automatic updates, run `/canon-update`.

---

## Constraints

- Only edit the four doc files listed above. Do not touch `docs/user/README.md`, `docs/user/search-guide.md`, `docs/user/session-guide.md`, `docs/user/glossary-guide.md`, `docs/architecture/README.md`, `docs/architecture/system-overview.md`, or any file in `docs/archive/`.
- Do not restructure or reformat sections that don't need changes.
- Do not add speculative content about future phases.
- If the diff between the doc and the code is trivial (e.g., a minor wording difference with no functional meaning), do not update.
