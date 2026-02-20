#!/usr/bin/env python3
"""Phase 8 migration script -- Gemini FSM state reset + store migration.

Step 1 (schema): Resets all uploaded files to gemini_state='untracked', nulls
gemini_file_id and gemini_store_doc_id, and sets gemini_state_updated_at to the
migration timestamp. This is the DESTRUCTIVE part of the Phase 8 migration; the
non-destructive schema column additions are handled automatically by
Database._setup_schema() (V9 migration).

Step 2 (store): Creates the permanent 'objectivism-library' store, deletes the
old 'objectivism-library-test' store, and saves the new store resource name to
library_config. Search goes offline until Phase 12 completes.

CRITICAL: AI metadata (metadata_json, entity tables) is NEVER touched.
Post-migration verification confirms this.

Usage:
  python scripts/migrate_phase8.py --dry-run                    # Both steps, dry-run
  python scripts/migrate_phase8.py --yes                        # Both steps, no prompt
  python scripts/migrate_phase8.py --step schema --yes          # Schema reset only
  python scripts/migrate_phase8.py --step store --dry-run       # Store pre-flight only
  python scripts/migrate_phase8.py --step store --yes           # Store migration, no prompt
  python scripts/migrate_phase8.py --db data/library.db --yes

Exit codes:
  0  Success (or dry-run completed, or already migrated)
  1  Verification failed or precondition not met
  2  Missing API key or limbo state (manual intervention required)
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

try:
    from rich.console import Console
    from rich.panel import Panel
except ImportError:
    # Minimal fallback if rich is not installed
    class Console:  # type: ignore[no-redef]
        def print(self, *args, **kwargs):
            text = args[0] if args else ""
            if hasattr(text, "renderable"):
                text = str(text)
            # Strip basic rich markup
            import re
            text = re.sub(r"\[/?[^\]]*\]", "", str(text))
            print(text)

        def status(self, msg):
            """No-op context manager for fallback."""
            import contextlib
            return contextlib.nullcontext()

    class Panel:  # type: ignore[no-redef]
        def __init__(self, content, title="", **kwargs):
            self.renderable = f"--- {title} ---\n{content}\n---"
        def __str__(self):
            return self.renderable

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 8 migration: reset Gemini FSM state + store migration"
    )
    parser.add_argument(
        "--db",
        default=str(_REPO_ROOT / "data" / "library.db"),
        help="Path to SQLite database (default: data/library.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without executing",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    parser.add_argument(
        "--step",
        choices=["schema", "store", "all"],
        default="all",
        help="Migration step to run: schema (state reset), store (store migration), all (default: both)",
    )
    parser.add_argument(
        "--store-old",
        default="objectivism-library-test",
        help="Display name of the old store to delete (default: objectivism-library-test)",
    )
    parser.add_argument(
        "--store-new",
        default="objectivism-library",
        help="Display name of the new store to create (default: objectivism-library)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Step 1: Schema / state reset helpers
# ---------------------------------------------------------------------------

def check_preconditions(conn: sqlite3.Connection) -> bool:
    """Verify DB is at V9 and has the required columns."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 9:
        console.print(f"[red]ERROR:[/red] Database version is {version}, expected >= 9")
        console.print("Run the application once to trigger V9 auto-migration first.")
        return False

    columns = {row[1] for row in conn.execute("PRAGMA table_info(files)")}
    required = {"gemini_state", "gemini_store_doc_id", "gemini_state_updated_at"}
    missing = required - columns
    if missing:
        console.print(f"[red]ERROR:[/red] Missing columns: {missing}")
        return False

    return True


def check_already_migrated(conn: sqlite3.Connection) -> bool:
    """Return True if migration was already applied (idempotency check)."""
    # Check if any uploaded files still have non-untracked state or non-null gemini_file_id
    non_untracked = conn.execute(
        "SELECT COUNT(*) FROM files WHERE gemini_state != 'untracked' AND status = 'uploaded'"
    ).fetchone()[0]
    has_gemini_ids = conn.execute(
        "SELECT COUNT(*) FROM files WHERE gemini_file_id IS NOT NULL AND status = 'uploaded'"
    ).fetchone()[0]

    if non_untracked == 0 and has_gemini_ids == 0:
        # Also check that gemini_state_updated_at is set for uploaded files
        # (distinguishes "never migrated" from "already migrated")
        uploaded_count = conn.execute(
            "SELECT COUNT(*) FROM files WHERE status = 'uploaded'"
        ).fetchone()[0]
        if uploaded_count == 0:
            # No uploaded files at all -- nothing to migrate
            return True
        has_timestamp = conn.execute(
            "SELECT COUNT(*) FROM files WHERE status = 'uploaded' AND gemini_state_updated_at IS NOT NULL"
        ).fetchone()[0]
        if has_timestamp > 0:
            return True

    return False


def create_backup(db_path: str, conn: sqlite3.Connection) -> str:
    """Flush WAL, close connection, copy DB, reopen, verify integrity."""
    backup_path = str(Path(db_path).with_suffix("")) + ".bak-phase8"

    # Flush WAL to main file
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    # Copy the database file
    shutil.copy2(db_path, backup_path)
    console.print(f"[green]Backup created:[/green] {backup_path}")

    # Reopen and verify integrity
    new_conn = sqlite3.connect(db_path)
    integrity = new_conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        console.print(f"[red]INTEGRITY CHECK FAILED:[/red] {integrity}")
        new_conn.close()
        sys.exit(1)

    return backup_path, new_conn  # type: ignore[return-value]


def get_pre_snapshot(conn: sqlite3.Connection) -> dict:
    """Capture pre-migration state for verification."""
    uploaded = conn.execute(
        "SELECT COUNT(*) FROM files WHERE status='uploaded'"
    ).fetchone()[0]

    null_metadata = conn.execute(
        "SELECT COUNT(*) FROM files WHERE metadata_json IS NULL"
    ).fetchone()[0]

    metadata_samples = conn.execute(
        "SELECT file_path, LENGTH(metadata_json) as mlen "
        "FROM files WHERE metadata_json IS NOT NULL LIMIT 5"
    ).fetchall()

    entity_count = conn.execute(
        "SELECT COUNT(*) FROM transcript_entity"
    ).fetchone()[0]

    return {
        "uploaded": uploaded,
        "null_metadata": null_metadata,
        "metadata_samples": [(r[0], r[1]) for r in metadata_samples],
        "entity_count": entity_count,
    }


def execute_reset(conn: sqlite3.Connection) -> tuple[int, str]:
    """Execute MIGR-04 state reset. Returns (rows_affected, migration_ts)."""
    migration_ts = datetime.now(timezone.utc).isoformat()

    cursor = conn.execute(
        "UPDATE files SET gemini_state='untracked', gemini_store_doc_id=NULL, "
        "gemini_file_id=NULL, gemini_state_updated_at=? WHERE status='uploaded'",
        (migration_ts,),
    )
    conn.commit()
    return cursor.rowcount, migration_ts


def verify_post_migration(conn: sqlite3.Connection, pre: dict) -> bool:
    """Verify sacred data is untouched. Returns True if all checks pass."""
    ok = True

    # Check metadata_json NULL count unchanged
    post_null = conn.execute(
        "SELECT COUNT(*) FROM files WHERE metadata_json IS NULL"
    ).fetchone()[0]
    if post_null != pre["null_metadata"]:
        console.print(
            f"[red]FAIL:[/red] metadata_json NULL count changed: "
            f"{pre['null_metadata']} -> {post_null}"
        )
        ok = False

    # Check entity count unchanged
    post_entities = conn.execute(
        "SELECT COUNT(*) FROM transcript_entity"
    ).fetchone()[0]
    if post_entities != pre["entity_count"]:
        console.print(
            f"[red]FAIL:[/red] transcript_entity count changed: "
            f"{pre['entity_count']} -> {post_entities}"
        )
        ok = False

    # Check metadata_json LENGTH for sample files
    for file_path, expected_len in pre["metadata_samples"]:
        row = conn.execute(
            "SELECT LENGTH(metadata_json) as mlen FROM files WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        if row is None:
            console.print(f"[red]FAIL:[/red] Sample file missing: {file_path}")
            ok = False
        elif row[0] != expected_len:
            console.print(
                f"[red]FAIL:[/red] metadata_json length changed for {file_path}: "
                f"{expected_len} -> {row[0]}"
            )
            ok = False

    # Check all uploaded files are now untracked
    untracked = conn.execute(
        "SELECT COUNT(*) FROM files WHERE gemini_state='untracked'"
    ).fetchone()[0]
    if untracked < pre["uploaded"]:
        console.print(
            f"[red]FAIL:[/red] untracked count ({untracked}) < "
            f"pre-uploaded count ({pre['uploaded']})"
        )
        ok = False

    # Check no uploaded files retain gemini_file_id
    stale = conn.execute(
        "SELECT COUNT(*) FROM files WHERE gemini_file_id IS NOT NULL AND status='uploaded'"
    ).fetchone()[0]
    if stale != 0:
        console.print(
            f"[red]FAIL:[/red] {stale} uploaded files still have gemini_file_id"
        )
        ok = False

    return ok


def run_schema_step(args: argparse.Namespace) -> int:
    """Run schema/state reset (step 1). Returns exit code."""
    if not Path(args.db).exists():
        console.print(f"[red]ERROR:[/red] Database not found: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)

    # Trigger V9 migration by importing Database and opening it
    from objlib.database import Database
    temp_db = Database(args.db)
    temp_db.close()

    conn = sqlite3.connect(args.db)

    if not check_preconditions(conn):
        conn.close()
        return 1

    # Check idempotency
    if check_already_migrated(conn):
        console.print("[green]Schema migration already applied.[/green] Nothing to do.")
        conn.close()
        return 0

    # Get pre-migration snapshot
    pre = get_pre_snapshot(conn)

    # Show summary
    console.print(f"\n[bold]Files to reset:[/bold] {pre['uploaded']} (status='uploaded')")
    console.print("[bold]Columns affected:[/bold] gemini_state, gemini_store_doc_id, "
                  "gemini_file_id, gemini_state_updated_at")
    console.print("[bold]Columns PRESERVED:[/bold] metadata_json, entity tables, all other columns")
    console.print(f"[bold]Entity records:[/bold] {pre['entity_count']} (will be verified intact)")

    if args.dry_run:
        console.print("\n[yellow]DRY RUN -- no changes made[/yellow]")
        conn.close()
        return 0

    # Confirm
    if not args.yes:
        try:
            response = input("\nProceed with schema reset? Type 'yes' to confirm: ")
        except EOFError:
            console.print("[yellow]Aborted (non-interactive environment).[/yellow]")
            return 0
        if response != "yes":
            console.print("[yellow]Aborted.[/yellow]")
            conn.close()
            return 0

    # Create backup
    backup_path, conn = create_backup(args.db, conn)

    # Execute reset
    rows_affected, migration_ts = execute_reset(conn)

    # Verify
    if not verify_post_migration(conn, pre):
        console.print("\n[red bold]VERIFICATION FAILED[/red bold]")
        console.print(f"Backup available at: {backup_path}")
        conn.close()
        return 1

    # Print summary
    summary_text = (
        f"{rows_affected} files reset to gemini_state='untracked'\n"
        f"gemini_file_id nulled for all uploaded files\n"
        f"AI metadata verified intact: {pre['entity_count']} entity records, "
        f"metadata_json unchanged\n"
        f"Migration timestamp: {migration_ts}\n"
        f"Backup at: {backup_path}"
    )
    console.print(Panel(summary_text, title="Schema Migration Complete", border_style="green"))

    conn.close()
    return 0


# ---------------------------------------------------------------------------
# Step 2: Store migration helpers
# ---------------------------------------------------------------------------

def run_store_step(args: argparse.Namespace) -> int:
    """Run store migration (step 2). Returns exit code."""
    import keyring

    # 1. Load API key from keyring
    api_key = keyring.get_password("objlib-gemini", "api_key")
    if not api_key:
        console.print(
            "[red]ERROR:[/red] No API key in keyring. "
            "Run: python -m objlib setup"
        )
        return 2

    # 2. Resolve existing stores by display name
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    old_store = None
    new_store = None
    with console.status("Scanning existing stores..."):
        for store in client.file_search_stores.list():
            dn = getattr(store, "display_name", None)
            if dn == args.store_old:
                old_store = store
            elif dn == args.store_new:
                new_store = store

    # 3. Recovery logic (4 states)
    if not old_store and new_store:
        # Migration already complete
        console.print(
            f"[green]Store migration already done.[/green] "
            f"'{args.store_new}' exists ({new_store.name})."
        )
        return 0

    if not old_store and not new_store:
        # Limbo -- manual intervention required
        console.print(
            f"[red]ERROR:[/red] Migration partially failed. "
            f"Neither '{args.store_old}' nor '{args.store_new}' found. "
            f"Create '{args.store_new}' manually."
        )
        return 2

    # old_store exists (with or without new_store)
    # old_store and new_store: step 1 done (creation), skip to deletion
    # old_store and not new_store: normal path -- full migration

    # 4. Pre-flight check
    # a. Get document count
    old_store_info = client.file_search_stores.get(name=old_store.name)
    doc_count = getattr(old_store_info, "active_documents_count", None)
    if doc_count is None:
        with console.status("Counting store documents..."):
            docs = list(client.file_search_stores.documents.list(parent=old_store.name))
        doc_count = len(docs)

    # b. Get DB uploaded count
    conn_check = sqlite3.connect(args.db)
    uploaded_count = conn_check.execute(
        "SELECT COUNT(*) FROM files WHERE status='uploaded'"
    ).fetchone()[0]
    conn_check.close()

    # c. Check for raw file resources (warn only -- non-critical)
    raw_warning = ""
    try:
        raw_files = list(client.files.list())
        if raw_files:
            raw_warning = (
                f"\n  Warning: {len(raw_files)} raw file resources found "
                f"(auto-expire in 48hr)"
            )
    except Exception as exc:
        raw_warning = f"\n  Warning: Could not list raw files ({exc})"

    # d. Display pre-flight panel
    panel_text = (
        f"Store '{args.store_old}': {doc_count} documents\n"
        f"DB: {uploaded_count} files with status='uploaded' "
        f"(already reset to 'untracked')\n"
        f"\n"
        f"AI metadata (metadata_json, entities): PRESERVED\n"
        f"\n"
        f"This operation is IRREVERSIBLE.\n"
        f"Search will be offline until Phase 12 completes."
        + (f"\n{raw_warning}" if raw_warning else "")
    )
    console.print(Panel(panel_text, title="Pre-flight Check", border_style="yellow"))

    # e. Dry-run exit (before confirmation prompt)
    if args.dry_run:
        console.print("\n[yellow]DRY RUN -- store migration not executed[/yellow]")
        return 0

    # f. Confirmation (unless --yes)
    if not args.yes:
        try:
            response = input("Proceed? Type 'yes' to confirm: ")
        except EOFError:
            console.print("[yellow]Aborted (non-interactive environment).[/yellow]")
            return 0
        if response.strip() != "yes":
            console.print("[yellow]Aborted.[/yellow]")
            return 0

    # 5. Step 1: Create new store (only if new_store is None)
    if new_store is None:
        console.print(f"Creating store '{args.store_new}'...")
        created = client.file_search_stores.create(
            config={"display_name": args.store_new}
        )
        assert created.name, "Store creation failed: empty resource name"
        new_store_name = created.name
        console.print(f"  Created: {new_store_name}")
    else:
        new_store_name = new_store.name
        console.print(
            f"[green]Store '{args.store_new}' already exists:[/green] {new_store_name}"
        )

    # 6. Step 2: Delete old store (old_store is guaranteed to exist here)
    console.print(f"Deleting store '{args.store_old}' (force=True)...")
    client.file_search_stores.delete(
        name=old_store.name,
        config=types.DeleteFileSearchStoreConfig(force=True),
    )
    console.print(f"  Deleted: {old_store.name}")

    # 7. Save new store resource name to library_config
    conn_save = sqlite3.connect(args.db)
    conn_save.execute(
        "INSERT OR REPLACE INTO library_config (key, value, updated_at) "
        "VALUES ('gemini_store_name', ?, strftime('%Y-%m-%dT%H:%M:%f', 'now'))",
        (new_store_name,),
    )
    conn_save.commit()
    conn_save.close()
    console.print(f"  Saved store name to library_config: {new_store_name}")

    # 8. Verify (post-migration)
    verify_store = client.file_search_stores.get(name=new_store_name)
    assert verify_store.display_name == args.store_new, (
        f"New store display_name mismatch: expected '{args.store_new}', "
        f"got '{verify_store.display_name}'"
    )

    old_still_exists = False
    for store in client.file_search_stores.list():
        if getattr(store, "display_name", None) == args.store_old:
            old_still_exists = True
            break
    assert not old_still_exists, (
        f"Old store '{args.store_old}' still exists after deletion!"
    )

    # 9. Print store migration summary
    summary_text = (
        f"Created store '{args.store_new}': {new_store_name}\n"
        f"Deleted store '{args.store_old}': {old_store.name}\n"
        f"Old store had {doc_count} documents (all deleted with force=True)\n"
        f"New store resource name saved to library_config\n"
        f"Search is now OFFLINE until Phase 12 completes"
    )
    console.print(Panel(summary_text, title="Store Migration Complete", border_style="green"))

    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    # Check DB exists (needed by both steps)
    if not Path(args.db).exists():
        console.print(f"[red]ERROR:[/red] Database not found: {args.db}")
        return 1

    if args.step == "schema":
        return run_schema_step(args)

    if args.step == "store":
        return run_store_step(args)

    # --step all: run both sequentially
    assert args.step == "all"

    console.print("[bold]Phase 8 Migration -- Step 1: Schema/State Reset[/bold]\n")
    rc = run_schema_step(args)
    if rc != 0:
        return rc

    console.print("\n[bold]Phase 8 Migration -- Step 2: Store Migration[/bold]\n")
    rc = run_store_step(args)
    return rc


if __name__ == "__main__":
    sys.exit(main())
