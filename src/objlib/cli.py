"""CLI entry point for the Objectivism Library tools.

Provides commands:
  - scan: Discover files, extract metadata, persist to SQLite
  - status: Display database statistics (counts by status and quality)
  - purge: Remove old LOCAL_DELETE records from the database
  - upload: Upload pending files to Gemini File Search store
  - search: Semantic search across the library via Gemini File Search
  - view: View detailed info about a document by filename
  - browse: Hierarchical exploration of library structure
  - filter: Metadata-only file queries against SQLite
  - config: Manage configuration (API keys, settings)
  - entities: Extract and manage person entity mentions in transcripts
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import keyring
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from objlib.config import ScannerConfig, load_config
from objlib.database import Database
from objlib.metadata import MetadataExtractor
from objlib.scanner import FileScanner

if TYPE_CHECKING:
    from objlib.models import AppState

logger = logging.getLogger(__name__)

# Offline mode constants: default external library disk paths
DEFAULT_LIBRARY_ROOT = "/Volumes/U32 Shadow/Objectivism Library"
DEFAULT_MOUNT_POINT = "/Volumes/U32 Shadow"

app = typer.Typer(
    help="Objectivism Library - Search, browse, and explore your philosophical library",
    rich_markup_mode="rich",
)
console = Console()

# Commands that NEED Gemini client initialization via callback
# All other commands (scan, status, purge, upload, config, view, browse, filter)
# either don't need Gemini or handle their own initialization.
_GEMINI_COMMANDS = {"search"}


@app.callback(invoke_without_command=True)
def app_callback(
    ctx: typer.Context,
    store: Annotated[
        str,
        typer.Option("--store", "-s", help="Gemini File Search store display name"),
    ] = "objectivism-library-v1",
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
) -> None:
    """Initialize shared state for search commands."""
    if ctx.invoked_subcommand not in _GEMINI_COMMANDS:
        # Skip AppState init for commands that don't need Gemini
        return

    # Skip initialization when --help is requested (Typer runs callback before subcommand)
    if "--help" in sys.argv or "-h" in sys.argv:
        return

    import shutil

    from google import genai

    from objlib.config import get_api_key
    from objlib.models import AppState as AppStateClass
    from objlib.search.client import GeminiSearchClient

    try:
        api_key = get_api_key()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    client = genai.Client(api_key=api_key)

    # Resolve store display name to resource name
    try:
        resource_name = GeminiSearchClient.resolve_store_name(client, store)
    except Exception as e:
        console.print(f"[red]Failed to resolve store '{store}':[/red] {e}")
        raise typer.Exit(code=1)

    ctx.obj = AppStateClass(
        gemini_client=client,
        store_resource_name=resource_name,
        db_path=str(db_path),
        terminal_width=shutil.get_terminal_size().columns,
    )


def get_state(ctx: typer.Context) -> AppState:
    """Type-safe accessor for AppState from Typer context."""
    if ctx.obj is None:
        console.print(
            "[red]Application state not initialized. "
            "Is the Gemini API key configured?[/red]"
        )
        raise typer.Exit(code=1)
    return ctx.obj

# Config command group
config_app = typer.Typer(help="Manage configuration (API keys, settings)")
app.add_typer(config_app, name="config")

# Metadata command group
metadata_app = typer.Typer(help="Manage file metadata (categories, courses, difficulty)")
app.add_typer(metadata_app, name="metadata")

# Entity extraction command group
entities_app = typer.Typer(help="Extract and manage person entity mentions in transcripts")
app.add_typer(entities_app, name="entities")

# Session management command group
session_app = typer.Typer(help="Manage research sessions (start, list, resume, note, export)")
app.add_typer(session_app, name="session")

# Glossary management command group
glossary_app = typer.Typer(help="Manage query expansion glossary")
app.add_typer(glossary_app, name="glossary")


@app.command()
def scan(
    library_path: Annotated[
        Path | None,
        typer.Option(
            "--library",
            "-l",
            help="Path to library root directory",
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
    db_path: Annotated[
        Path,
        typer.Option(
            "--db",
            "-d",
            help="Path to SQLite database file",
        ),
    ] = Path("data/library.db"),
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to scanner config JSON",
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show individual file changes"),
    ] = False,
) -> None:
    """Scan a library directory for files, extract metadata, and persist to SQLite."""
    # Build config: from file if it exists, otherwise defaults
    config: ScannerConfig
    if config_path and config_path.exists():
        try:
            config = load_config(config_path)
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Failed to load config: {e}")
            console.print("[dim]Using default configuration.[/dim]")
            config = ScannerConfig(library_path=library_path or Path("."))
    else:
        config = ScannerConfig(library_path=library_path or Path("."))

    # CLI library_path overrides config
    if library_path is not None:
        config.library_path = library_path

    # Check disk availability for external drives (OFFL-03)
    library_str = str(config.library_path)
    if library_str.startswith("/Volumes/"):
        from objlib.sync.disk import check_disk_availability, disk_error_message

        # Derive mount point from library path: /Volumes/<volume_name>
        parts = library_str.split("/")
        mount_point = "/".join(parts[:3]) if len(parts) >= 3 else DEFAULT_MOUNT_POINT

        availability = check_disk_availability(library_str, mount_point=mount_point)
        if availability != "available":
            msg = disk_error_message(availability, library_str, "scan")
            console.print(f"[red]Error:[/red] {msg}")
            raise typer.Exit(code=1)

    # Validate library path exists
    if not config.library_path.exists():
        console.print(
            f"[red]Error:[/red] Library path does not exist: {config.library_path}"
        )
        raise typer.Exit(code=1)

    if not config.library_path.is_dir():
        console.print(
            f"[red]Error:[/red] Library path is not a directory: {config.library_path}"
        )
        raise typer.Exit(code=1)

    # Override db_path from CLI
    config.db_path = db_path

    # Run scan
    with Database(config.db_path) as db:
        extractor = MetadataExtractor()
        scanner = FileScanner(config, db, extractor)

        console.print(
            Panel(
                f"Scanning: [bold]{config.library_path}[/bold]",
                title="Objectivism Library Scanner",
            )
        )

        changes = scanner.scan()

        # Results table
        table = Table(title="Scan Results")
        table.add_column("Category", style="bold")
        table.add_column("Count", justify="right")

        table.add_row("New files", f"[green]{len(changes.new)}[/green]")
        table.add_row("Modified files", f"[yellow]{len(changes.modified)}[/yellow]")
        table.add_row("Deleted files", f"[red]{len(changes.deleted)}[/red]")
        table.add_row("Unchanged files", f"{len(changes.unchanged)}")
        console.print(table)

        # Verbose: show individual files
        if verbose:
            if changes.new:
                console.print("\n[green]New files:[/green]")
                for fp in sorted(changes.new):
                    console.print(f"  + {fp}")
            if changes.modified:
                console.print("\n[yellow]Modified files:[/yellow]")
                for fp in sorted(changes.modified):
                    console.print(f"  ~ {fp}")
            if changes.deleted:
                console.print("\n[red]Deleted files:[/red]")
                for fp in sorted(changes.deleted):
                    console.print(f"  - {fp}")

        # Summary statistics
        total = db.get_file_count()
        status_counts = db.get_status_counts()
        quality_counts = db.get_quality_counts()

        console.print(f"\n[bold]Total files in database:[/bold] {total}")

        if status_counts:
            console.print("[bold]By status:[/bold]")
            for s, count in sorted(status_counts.items()):
                console.print(f"  {s}: {count}")

        if quality_counts:
            console.print("[bold]By metadata quality:[/bold]")
            for q, count in sorted(quality_counts.items()):
                console.print(f"  {q}: {count}")


@app.command()
def status(
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database file"),
    ] = Path("data/library.db"),
) -> None:
    """Display database statistics: file counts by status and metadata quality."""
    if not db_path.exists():
        console.print(
            f"[yellow]Database not found:[/yellow] {db_path}\n"
            "Run [bold]objlib scan --library /path/to/library[/bold] first."
        )
        raise typer.Exit(code=1)

    with Database(db_path) as db:
        total = db.get_file_count()
        status_counts = db.get_status_counts()
        quality_counts = db.get_quality_counts()

        # Last scan timestamp
        row = db.conn.execute(
            "SELECT MAX(updated_at) as last_scan FROM files"
        ).fetchone()
        last_scan = row["last_scan"] if row and row["last_scan"] else "Never"

        console.print(
            Panel(
                f"Database: [bold]{db_path}[/bold]",
                title="Library Status",
            )
        )

        # Status table
        status_table = Table(title="Files by Status")
        status_table.add_column("Status", style="bold")
        status_table.add_column("Count", justify="right")

        for s, count in sorted(status_counts.items()):
            style = {
                "pending": "yellow",
                "uploading": "blue",
                "uploaded": "green",
                "failed": "red",
                "LOCAL_DELETE": "dim",
            }.get(s, "")
            status_table.add_row(s, f"[{style}]{count}[/{style}]" if style else str(count))

        console.print(status_table)

        # Quality table
        quality_table = Table(title="Files by Metadata Quality")
        quality_table.add_column("Quality", style="bold")
        quality_table.add_column("Count", justify="right")

        for q, count in sorted(quality_counts.items()):
            style = {
                "complete": "green",
                "partial": "yellow",
                "minimal": "yellow",
                "none": "red",
                "unknown": "dim",
            }.get(q, "")
            quality_table.add_row(q, f"[{style}]{count}[/{style}]" if style else str(count))

        console.print(quality_table)

        console.print(f"\n[bold]Total files:[/bold] {total}")
        console.print(f"[bold]Last scan:[/bold] {last_scan}")


@app.command()
def purge(
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database file"),
    ] = Path("data/library.db"),
    older_than_days: Annotated[
        int,
        typer.Option(
            "--older-than",
            help="Only purge LOCAL_DELETE records older than N days",
        ),
    ] = 30,
    confirm: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt"),
    ] = False,
) -> None:
    """Remove LOCAL_DELETE records older than N days from the database."""
    if not db_path.exists():
        console.print(
            f"[yellow]Database not found:[/yellow] {db_path}\n"
            "Nothing to purge."
        )
        raise typer.Exit(code=1)

    with Database(db_path) as db:
        # Query LOCAL_DELETE records older than N days
        rows = db.conn.execute(
            """SELECT file_path FROM files
               WHERE status = 'LOCAL_DELETE'
               AND updated_at < strftime('%Y-%m-%dT%H:%M:%f',
                   'now', ? || ' days')""",
            (f"-{older_than_days}",),
        ).fetchall()

        count = len(rows)

        if count == 0:
            console.print(
                f"[green]No LOCAL_DELETE records older than {older_than_days} days.[/green]"
            )
            return

        console.print(
            f"Found [bold]{count}[/bold] LOCAL_DELETE record(s) "
            f"older than {older_than_days} days."
        )

        if not confirm:
            proceed = typer.confirm("Proceed with purge?")
            if not proceed:
                console.print("[yellow]Purge cancelled.[/yellow]")
                return

        # Hard delete
        paths = [row["file_path"] for row in rows]
        with db.conn:
            db.conn.executemany(
                "DELETE FROM files WHERE file_path = ?",
                [(p,) for p in paths],
            )

        console.print(f"[green]Purged {count} record(s).[/green]")


@app.command("store-sync")
def store_sync(
    store_name: Annotated[
        str,
        typer.Option("--store", "-s", help="Gemini File Search store display name"),
    ] = "objectivism-library-test",
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database file"),
    ] = Path("data/library.db"),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Preview what would be deleted without making changes (default: on)"),
    ] = True,
    confirm: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt when --no-dry-run is set"),
    ] = False,
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", help="Pause briefly after every N deletions for rate limiting"),
    ] = 20,
) -> None:
    """Remove orphaned/duplicate documents from the Gemini File Search store.

    Compares every document in the store against the local DB's canonical
    ``gemini_file_id`` records. Documents whose file ID is not the canonical
    one tracked in the DB are deleted.

    This fixes two classes of orphans:

    \\b
    - Duplicate uploads: the same file was uploaded in multiple pipeline runs,
      creating multiple Gemini file IDs. Only the most recent ID is in the DB.
    - Pre-filter uploads: old PDFs/EPUBs uploaded before the .txt-only filter.
      These have no ``gemini_file_id`` in the DB (status='skipped').

    Always run with [bold]--dry-run[/bold] first (the default) to verify what
    would be deleted before committing to [bold]--no-dry-run[/bold].
    """
    import asyncio

    from rich.table import Table

    if not db_path.exists():
        console.print(f"[red]Database not found:[/red] {db_path}")
        raise typer.Exit(code=1)

    from objlib.config import get_api_key

    try:
        api_key = get_api_key()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    # Step 1: Get canonical file ID suffixes from DB
    with Database(db_path) as db:
        canonical_suffixes = db.get_canonical_gemini_file_id_suffixes()

    console.print(f"[dim]Canonical uploaded file IDs in DB:[/dim] {len(canonical_suffixes)}")

    # Step 2: Initialize Gemini upload client
    from objlib.upload.circuit_breaker import RollingWindowCircuitBreaker
    from objlib.upload.client import GeminiFileSearchClient
    from objlib.upload.rate_limiter import AdaptiveRateLimiter, RateLimiterConfig

    circuit_breaker = RollingWindowCircuitBreaker()
    rate_limiter = AdaptiveRateLimiter(RateLimiterConfig(), circuit_breaker)
    client = GeminiFileSearchClient(api_key, circuit_breaker, rate_limiter)

    async def run_sync() -> None:
        # Resolve and connect to store
        await client.get_or_create_store(store_name)

        # List all store documents
        console.print("[dim]Listing store documents (this may take a moment)...[/dim]")
        documents = await client.list_store_documents()
        console.print(f"[dim]Total store documents:[/dim] {len(documents)}")

        # Classify each document as canonical or orphaned
        orphaned = []  # list of (doc, suffix, display_name)
        canonical_count = 0

        for doc in documents:
            doc_name = getattr(doc, "name", "") or ""
            # display_name holds the plain file ID (e.g. "eafkmpzjs39o") set at
            # import time. The document resource name suffix is a compound key
            # (e.g. "eafkmpzjs39o-<chunkId>") and does NOT match DB file IDs.
            display_name = getattr(doc, "display_name", "") or ""

            if display_name in canonical_suffixes:
                canonical_count += 1
            else:
                orphaned.append((doc, display_name, display_name))

        console.print(f"[green]Canonical documents:[/green] {canonical_count}")
        console.print(f"[yellow]Orphaned documents:[/yellow] {len(orphaned)}")

        if not orphaned:
            console.print("[green]Store is clean — nothing to purge.[/green]")
            return

        # Show a sample of what would be deleted
        sample_table = Table(show_header=True, header_style="bold")
        sample_table.add_column("Document Resource Name", no_wrap=True)
        sample_table.add_column("Display Name")
        sample_table.add_column("File ID Suffix")
        for doc, suffix, display_name in orphaned[:15]:
            sample_table.add_row(
                getattr(doc, "name", ""),
                display_name[:55],
                suffix,
            )
        if len(orphaned) > 15:
            sample_table.add_row(f"... and {len(orphaned) - 15} more", "", "")
        console.print(sample_table)

        if dry_run:
            console.print(
                f"\n[yellow]DRY RUN[/yellow] — {len(orphaned)} documents would be deleted.\n"
                "Re-run with [bold]--no-dry-run[/bold] to perform the actual deletion."
            )
            return

        if not confirm:
            proceed = typer.confirm(
                f"\nDelete {len(orphaned)} orphaned documents from store '{store_name}'?"
            )
            if not proceed:
                console.print("[yellow]Purge cancelled.[/yellow]")
                return

        # Delete orphaned documents in batches
        deleted = 0
        failed = 0
        for i, (doc, suffix, _display) in enumerate(orphaned):
            doc_name = getattr(doc, "name", "")
            ok = await client.delete_store_document(doc_name)
            if ok:
                deleted += 1
            else:
                failed += 1
            if (i + 1) % batch_size == 0:
                console.print(f"[dim]  {i + 1}/{len(orphaned)} processed...[/dim]")
                await asyncio.sleep(1.0)  # Gentle rate limiting between batches

        console.print(f"\n[green]Done:[/green] {deleted} deleted, {failed} failed.")

    asyncio.run(run_sync())


@app.command()
def upload(
    store_name: Annotated[
        str,
        typer.Option("--store", "-s", help="Gemini File Search store display name"),
    ] = "objectivism-library-v1",
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database file"),
    ] = Path("data/library.db"),
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", "-b", help="Files per logical batch (100-200)"),
    ] = 150,
    max_concurrent: Annotated[
        int,
        typer.Option("--concurrency", "-n", help="Max concurrent uploads (3-10)"),
    ] = 7,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be uploaded without uploading"),
    ] = False,
) -> None:
    """Upload pending files to Gemini File Search store with progress tracking.

    The Gemini API key is read from the system keyring (service: objlib-gemini).
    To set it:  keyring set objlib-gemini api_key
    """
    # Check disk availability for source files (OFFL-03)
    from objlib.sync.disk import check_disk_availability, disk_error_message

    availability = check_disk_availability(DEFAULT_LIBRARY_ROOT)
    if availability != "available":
        msg = disk_error_message(availability, DEFAULT_LIBRARY_ROOT, "upload")
        console.print(f"[red]Error:[/red] {msg}")
        raise typer.Exit(code=1)

    # Validate database exists
    if not db_path.exists():
        console.print(
            f"[red]Error:[/red] Database not found: {db_path}\n"
            "Run [bold]objlib scan --library /path/to/library[/bold] first."
        )
        raise typer.Exit(code=1)

    # Dry-run mode: show pending files without uploading
    if dry_run:
        with Database(db_path) as db:
            pending = db.get_pending_files(limit=10000)
            count = len(pending)

            if count == 0:
                console.print("[green]No pending files to upload.[/green]")
                return

            console.print(
                Panel(
                    f"[bold]{count}[/bold] files pending upload to "
                    f"[bold]{store_name}[/bold]",
                    title="Dry Run",
                )
            )

            # Show first 20 files in a table
            preview_table = Table(title=f"Pending Files (showing first {min(20, count)})")
            preview_table.add_column("File Path", style="cyan", no_wrap=True)
            preview_table.add_column("Size", justify="right")
            preview_table.add_column("Quality", style="green")

            for row in pending[:20]:
                size_kb = row["file_size"] / 1024
                size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
                # Extract quality from metadata if available
                quality = "unknown"
                try:
                    cursor = db.conn.execute(
                        "SELECT metadata_quality FROM files WHERE file_path = ?",
                        (row["file_path"],),
                    )
                    qrow = cursor.fetchone()
                    if qrow:
                        quality = qrow["metadata_quality"]
                except Exception:
                    pass
                preview_table.add_row(row["file_path"], size_str, quality)

            if count > 20:
                preview_table.add_row(
                    f"... and {count - 20} more", "", ""
                )

            console.print(preview_table)

            console.print(
                f"\nRun [bold]objlib upload --store {store_name} --db {db_path}[/bold] "
                "to start uploading."
            )
        return

    # Get API key from system keyring
    try:
        from objlib.config import get_api_key_from_keyring

        api_key = get_api_key_from_keyring()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    # Import upload modules here to keep CLI startup fast for scan/status
    import asyncio

    from objlib.models import UploadConfig
    from objlib.upload.circuit_breaker import RollingWindowCircuitBreaker
    from objlib.upload.client import GeminiFileSearchClient
    from objlib.upload.orchestrator import UploadOrchestrator
    from objlib.upload.progress import UploadProgressTracker
    from objlib.upload.rate_limiter import AdaptiveRateLimiter, RateLimiterConfig
    from objlib.upload.state import AsyncUploadStateManager

    # Build configuration
    config = UploadConfig(
        store_name=store_name,
        api_key=api_key,
        max_concurrent_uploads=max_concurrent,
        batch_size=batch_size,
        db_path=str(db_path),
    )

    # Get pending file count for progress tracker
    with Database(db_path) as db:
        pending_count = len(db.get_pending_files(limit=10000))

    if pending_count == 0:
        console.print("[green]No pending files to upload.[/green]")
        return

    total_batches = (pending_count + batch_size - 1) // batch_size

    console.print(
        Panel(
            f"Uploading [bold]{pending_count}[/bold] files to "
            f"[bold]{store_name}[/bold]\n"
            f"Batches: {total_batches} x {batch_size} | "
            f"Concurrency: {max_concurrent}",
            title="Upload Pipeline",
        )
    )

    # Create components
    circuit_breaker = RollingWindowCircuitBreaker()
    rate_limiter_config = RateLimiterConfig(tier=config.rate_limit_tier)
    rate_limiter = AdaptiveRateLimiter(rate_limiter_config, circuit_breaker)
    client = GeminiFileSearchClient(
        api_key=api_key,
        circuit_breaker=circuit_breaker,
        rate_limiter=rate_limiter,
    )
    progress = UploadProgressTracker(
        total_files=pending_count, total_batches=total_batches
    )

    async def _run_upload() -> dict[str, int]:
        async with AsyncUploadStateManager(str(db_path)) as state:
            orchestrator = UploadOrchestrator(
                client=client,
                state=state,
                circuit_breaker=circuit_breaker,
                config=config,
                progress=progress,
            )
            return await orchestrator.run(store_name)

    result = asyncio.run(_run_upload())

    # Print final summary
    summary_table = Table(title="Upload Summary")
    summary_table.add_column("Metric", style="bold")
    summary_table.add_column("Count", justify="right")

    summary_table.add_row("Total files", str(result["total"]))
    summary_table.add_row("Succeeded", f"[green]{result['succeeded']}[/green]")
    summary_table.add_row("Failed", f"[red]{result['failed']}[/red]")
    summary_table.add_row("Skipped", f"[yellow]{result['skipped']}[/yellow]")
    summary_table.add_row("Pending", str(result["pending"]))

    console.print(Panel(summary_table, title="Upload Complete"))


@app.command("enriched-upload")
def enriched_upload(
    store_name: Annotated[
        str,
        typer.Option("--store", "-s", help="Gemini File Search store display name"),
    ] = "objectivism-library-test",
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database file"),
    ] = Path("data/library.db"),
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", "-b", help="Files per logical batch"),
    ] = 100,
    max_concurrent: Annotated[
        int,
        typer.Option("--concurrency", "-n", help="Max concurrent uploads (default 2)"),
    ] = 2,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be uploaded without uploading"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Max files to upload (0 = no limit). Use for staged testing."),
    ] = 0,
    include_needs_review: Annotated[
        bool,
        typer.Option("--include-needs-review/--exclude-needs-review", help="Include low-confidence files"),
    ] = True,
    reset_existing: Annotated[
        bool,
        typer.Option("--reset-existing/--no-reset-existing", help="Delete and re-upload already-uploaded files"),
    ] = True,
) -> None:
    """Upload files with enriched 4-tier AI metadata to Gemini File Search.

    Requires AI metadata extraction (Phase 6) and entity extraction (Phase 6.1)
    to be complete. Files missing either are excluded by the strict entity gate.

    The Gemini API key is read from the system keyring (service: objlib-gemini).

    Three-stage testing approach:
      Stage 1: objlib enriched-upload --limit 20       # Validate metadata schema
      Stage 2: objlib enriched-upload --limit 100      # Validate search quality
      Stage 3: objlib enriched-upload --limit 250      # Validate pipeline at scale
      Full:    objlib enriched-upload                   # All enriched files
    """
    # Check disk availability for source files (OFFL-03)
    from objlib.sync.disk import check_disk_availability, disk_error_message

    availability = check_disk_availability(DEFAULT_LIBRARY_ROOT)
    if availability != "available":
        msg = disk_error_message(availability, DEFAULT_LIBRARY_ROOT, "enriched-upload")
        console.print(f"[red]Error:[/red] {msg}")
        raise typer.Exit(code=1)

    import json as json_mod

    # Validate database exists
    if not db_path.exists():
        console.print(
            f"[red]Error:[/red] Database not found: {db_path}\n"
            "Run [bold]objlib scan --library /path/to/library[/bold] first."
        )
        raise typer.Exit(code=1)

    # Dry-run mode: show enriched pending files without uploading
    if dry_run:
        import asyncio

        from objlib.upload.state import AsyncUploadStateManager

        async def _dry_run() -> list[dict]:
            async with AsyncUploadStateManager(str(db_path)) as state:
                return await state.get_enriched_pending_files(
                    limit=limit if limit > 0 else 10000,
                    include_needs_review=include_needs_review,
                )

        pending = asyncio.run(_dry_run())
        count = len(pending)

        if count == 0:
            console.print(
                "[yellow]No enriched pending files to upload.[/yellow]\n"
                "Ensure AI metadata extraction and entity extraction have run:\n"
                "  [cyan]objlib metadata extract[/cyan]\n"
                "  [cyan]objlib entities extract[/cyan]"
            )
            return

        console.print(
            Panel(
                f"[bold]{count}[/bold] files ready for enriched upload to "
                f"[bold]{store_name}[/bold]",
                title="Dry Run - Enriched Upload",
            )
        )

        # Show first 20 files in a table
        preview_table = Table(title=f"Enriched Pending Files (showing first {min(20, count)})")
        preview_table.add_column("Filename", style="cyan", no_wrap=True)
        preview_table.add_column("Entities", justify="right", style="green")
        preview_table.add_column("AI Category", style="bold")
        preview_table.add_column("Topics", style="dim")

        for row in pending[:20]:
            ai_meta = json_mod.loads(row.get("ai_metadata_json") or "{}")
            entities = row.get("entity_names", [])
            topics = ai_meta.get("primary_topics", [])
            preview_table.add_row(
                row.get("filename", ""),
                str(len(entities)),
                ai_meta.get("category", "unknown"),
                ", ".join(topics[:3]) if topics else "",
            )

        if count > 20:
            preview_table.add_row(f"... and {count - 20} more", "", "", "")

        console.print(preview_table)

        console.print(
            f"\nRun [bold]objlib enriched-upload --store {store_name} --db {db_path}[/bold] "
            "to start uploading."
        )
        return

    # Get API key from system keyring
    try:
        from objlib.config import get_api_key_from_keyring

        api_key = get_api_key_from_keyring()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    # Import upload modules here to keep CLI startup fast
    import asyncio

    from objlib.models import UploadConfig
    from objlib.upload.circuit_breaker import RollingWindowCircuitBreaker
    from objlib.upload.client import GeminiFileSearchClient
    from objlib.upload.orchestrator import EnrichedUploadOrchestrator
    from objlib.upload.progress import UploadProgressTracker
    from objlib.upload.rate_limiter import AdaptiveRateLimiter, RateLimiterConfig
    from objlib.upload.state import AsyncUploadStateManager

    # Build configuration
    config = UploadConfig(
        store_name=store_name,
        api_key=api_key,
        max_concurrent_uploads=max_concurrent,
        batch_size=batch_size,
        db_path=str(db_path),
        rate_limit_tier="tier1",
    )

    # Get enriched file counts for progress tracker.
    # When --reset-existing is set, also count reset-eligible files so the
    # pre-check doesn't exit early when there are 0 currently-pending files.
    async def _get_counts() -> tuple[int, int]:
        async with AsyncUploadStateManager(str(db_path)) as state:
            pending = await state.get_enriched_pending_files(
                limit=limit if limit > 0 else 10000,
                include_needs_review=include_needs_review,
            )
            reset_count = 0
            if reset_existing:
                reset_files = await state.get_files_to_reset_for_enriched_upload()
                cap = limit if limit > 0 else len(reset_files)
                reset_count = min(len(reset_files), cap)
            return len(pending), reset_count

    pending_count, reset_count = asyncio.run(_get_counts())
    total_count = pending_count + reset_count

    if total_count == 0:
        console.print(
            "[yellow]No enriched files to upload.[/yellow]\n"
            "Ensure AI metadata extraction and entity extraction have run:\n"
            "  [cyan]objlib metadata extract[/cyan]\n"
            "  [cyan]objlib entities extract[/cyan]"
        )
        return

    total_batches = (total_count + batch_size - 1) // batch_size

    console.print(
        Panel(
            f"Uploading [bold]{total_count}[/bold] enriched files to "
            f"[bold]{store_name}[/bold]\n"
            f"Batches: {total_batches} x {batch_size} | "
            f"Concurrency: {max_concurrent}\n"
            f"Reset existing: {reset_existing} | "
            f"Include needs-review: {include_needs_review}",
            title="Enriched Upload Pipeline",
        )
    )

    # Create components
    circuit_breaker = RollingWindowCircuitBreaker()
    rate_limiter_config = RateLimiterConfig(tier=config.rate_limit_tier)
    rate_limiter = AdaptiveRateLimiter(rate_limiter_config, circuit_breaker)
    client = GeminiFileSearchClient(
        api_key=api_key,
        circuit_breaker=circuit_breaker,
        rate_limiter=rate_limiter,
    )
    progress = UploadProgressTracker(
        total_files=total_count, total_batches=total_batches
    )

    async def _run_enriched_upload() -> dict[str, int]:
        async with AsyncUploadStateManager(str(db_path)) as state:
            orchestrator = EnrichedUploadOrchestrator(
                client=client,
                state=state,
                circuit_breaker=circuit_breaker,
                config=config,
                progress=progress,
                reset_existing=reset_existing,
                include_needs_review=include_needs_review,
                file_limit=limit,
            )
            return await orchestrator.run_enriched(store_name)

    result = asyncio.run(_run_enriched_upload())

    # Print final summary
    summary_table = Table(title="Enriched Upload Summary")
    summary_table.add_column("Metric", style="bold")
    summary_table.add_column("Count", justify="right")

    summary_table.add_row("Total files", str(result["total"]))
    summary_table.add_row("Succeeded", f"[green]{result['succeeded']}[/green]")
    summary_table.add_row("Failed", f"[red]{result['failed']}[/red]")
    summary_table.add_row("Skipped (idempotent)", f"[yellow]{result['skipped']}[/yellow]")
    summary_table.add_row("Reset (re-uploaded)", f"[cyan]{result['reset']}[/cyan]")
    if result.get("retried", 0) > 0:
        summary_table.add_row("Retried (successful)", f"[magenta]{result['retried']}[/magenta]")
    summary_table.add_row("Pending", str(result["pending"]))

    console.print(Panel(summary_table, title="Enriched Upload Complete"))


@app.command()
def sync(
    library_path: Annotated[
        Path | None,
        typer.Option(
            "--library",
            "-l",
            help="Path to library root directory",
        ),
    ] = None,
    store_name: Annotated[
        str,
        typer.Option("--store", "-s", help="Gemini File Search store display name"),
    ] = "objectivism-library-test",
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database file"),
    ] = Path("data/library.db"),
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-process all files regardless of change detection"),
    ] = False,
    skip_enrichment: Annotated[
        bool,
        typer.Option("--skip-enrichment", help="Use simple upload pipeline instead of enriched"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview changes without executing"),
    ] = False,
    prune_missing: Annotated[
        bool,
        typer.Option("--prune-missing", help="Delete missing files (>7 days) from Gemini"),
    ] = False,
    cleanup_orphans: Annotated[
        bool,
        typer.Option("--cleanup-orphans", help="Remove orphaned Gemini entries"),
    ] = False,
) -> None:
    """Incremental sync: detect changes, upload new/modified, mark missing.

    Detects new, modified, and missing files by comparing the library disk
    against the SQLite database. New and modified files are uploaded to
    Gemini File Search with enriched metadata by default.

    Disk availability is checked before any filesystem operations.
    Library config (store name) is verified on startup to prevent
    accidental cross-store operations.

    Examples:
      objlib sync --dry-run                        # Preview changes
      objlib sync --library "/path/to/lib"         # Full sync
      objlib sync --force                          # Re-process all files
      objlib sync --skip-enrichment                # Simple metadata only
      objlib sync --prune-missing                  # Clean up old missing files
    """
    import asyncio

    from objlib.sync.disk import check_disk_availability, disk_error_message

    # Resolve library path
    lib_root = str(library_path) if library_path else "/Volumes/U32 Shadow/Objectivism Library"

    # Check disk availability
    availability = check_disk_availability(lib_root)
    err_msg = disk_error_message(availability, lib_root, "objlib sync")
    if err_msg:
        console.print(f"[red]{err_msg}[/red]")
        raise typer.Exit(code=1)

    # Validate database exists
    if not db_path.exists():
        console.print(
            f"[red]Error:[/red] Database not found: {db_path}\n"
            "Run [bold]objlib scan --library /path/to/library[/bold] first."
        )
        raise typer.Exit(code=1)

    # Get API key from system keyring (skip for dry-run)
    api_key = ""
    if not dry_run:
        try:
            from objlib.config import get_api_key_from_keyring

            api_key = get_api_key_from_keyring()
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1)

    # Import sync and upload modules (deferred for fast CLI startup)
    from objlib.config import ScannerConfig
    from objlib.sync.orchestrator import SyncOrchestrator
    from objlib.upload.circuit_breaker import RollingWindowCircuitBreaker
    from objlib.upload.client import GeminiFileSearchClient
    from objlib.upload.rate_limiter import AdaptiveRateLimiter, RateLimiterConfig

    # Build scanner config
    config = ScannerConfig(library_path=Path(lib_root), db_path=db_path)

    # Initialize database
    db = Database(str(db_path))

    # Create Gemini client only when needed (dry-run doesn't call API)
    client = None
    if not dry_run:
        circuit_breaker = RollingWindowCircuitBreaker()
        rate_limiter_config = RateLimiterConfig(tier="tier1")
        rate_limiter = AdaptiveRateLimiter(rate_limiter_config, circuit_breaker)
        client = GeminiFileSearchClient(
            api_key=api_key,
            circuit_breaker=circuit_breaker,
            rate_limiter=rate_limiter,
        )

    async def _run_sync() -> dict[str, int]:
        # Ensure store exists (needed for uploads and document management)
        if client is not None and not dry_run:
            await client.get_or_create_store(store_name)

        orchestrator = SyncOrchestrator(
            db=db,
            client=client,
            config=config,
            api_key=api_key,
            console=console,
            store_name=store_name,
        )
        return await orchestrator.run(
            force=force,
            skip_enrichment=skip_enrichment,
            dry_run=dry_run,
            prune_missing=prune_missing,
            cleanup_orphans=cleanup_orphans,
        )

    try:
        result = asyncio.run(_run_sync())
    finally:
        db.close()

    if not dry_run:
        console.print(
            Panel(
                f"[green]Sync complete.[/green] "
                f"New: {result['new_uploaded']}, "
                f"Modified: {result['modified_replaced']}, "
                f"Missing: {result['marked_missing']}, "
                f"Errors: {result['errors']}",
                title="Sync Results",
            )
        )


@app.command()
def search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Semantic search query")],
    filter: Annotated[
        list[str] | None,
        typer.Option(
            "--filter",
            "-f",
            help="Metadata filter (field:value). Filterable: category, course, difficulty, quarter, date, year, week, quality_score",
        ),
    ] = None,
    limit: Annotated[
        int, typer.Option("--limit", "-l", help="Max results to display")
    ] = 10,
    model: Annotated[
        str, typer.Option("--model", "-m", help="Gemini model for search")
    ] = "gemini-2.5-flash",
    synthesize: Annotated[
        bool, typer.Option("--synthesize", help="Generate multi-document synthesis with citations")
    ] = False,
    rerank: Annotated[
        bool, typer.Option("--rerank/--no-rerank", help="Rerank results with Gemini Flash (default: on)")
    ] = True,
    expand: Annotated[
        bool, typer.Option("--expand/--no-expand", help="Expand query with philosophical synonyms (default: on)")
    ] = True,
    track_evolution: Annotated[
        bool, typer.Option("--track-evolution", help="Group results by difficulty progression")
    ] = False,
    mode: Annotated[
        str, typer.Option("--mode", help="Result ordering: 'learn' (intro-first) or 'research' (pure relevance)")
    ] = "learn",
    debug: Annotated[
        bool, typer.Option("--debug", help="Write debug log to ~/.objlib/debug.log")
    ] = False,
) -> None:
    """Search the library by meaning with optional metadata filters."""
    import hashlib
    import uuid

    from objlib.search.citations import (
        build_metadata_filter,
        enrich_citations,
        extract_citations,
    )
    from objlib.search.client import GeminiSearchClient
    from objlib.search.expansion import expand_query as _expand_query
    from objlib.search.formatter import display_search_results

    state = get_state(ctx)

    # Validate mode
    if mode not in ("learn", "research"):
        console.print("[red]--mode must be 'learn' or 'research'[/red]")
        raise typer.Exit(code=1)

    # Debug logging setup
    if debug:
        import logging as _logging
        debug_dir = Path.home() / ".objlib"
        debug_dir.mkdir(exist_ok=True)
        fh = _logging.FileHandler(debug_dir / "debug.log")
        fh.setLevel(_logging.DEBUG)
        _logging.getLogger("objlib").addHandler(fh)

    # --- Stage 1: Query Expansion ---
    display_query = query
    search_query = query
    if expand:
        try:
            search_query, expansions = _expand_query(query)
            if expansions:
                console.print(f"[dim]Expanded:[/dim] {' + '.join(expansions)}")
        except Exception:
            pass  # Expansion failure: use original query

    console.print(f"[dim]Searching for:[/dim] [bold]{display_query}[/bold]")

    # Build AIP-160 filter
    metadata_filter = build_metadata_filter(filter) if filter else None
    if metadata_filter:
        console.print(f"[dim]Filter:[/dim] {metadata_filter}")

    # --- Stage 2: Gemini File Search ---
    search_client = GeminiSearchClient(state.gemini_client, state.store_resource_name)
    try:
        response = search_client.query_with_retry(
            search_query, metadata_filter=metadata_filter, model=model
        )
    except Exception as e:
        console.print(f"[red]Search failed after retries:[/red] {e}")
        raise typer.Exit(code=1)

    # Extract citations from grounding metadata
    grounding = None
    if response.candidates:
        grounding = response.candidates[0].grounding_metadata

    citations = extract_citations(grounding)

    # --- Stage 3: Enrich and cache passages ---
    with Database(state.db_path) as db:
        enrich_citations(citations, db, state.gemini_client)

        # Cache passages in SQLite for citation stability (passage_id = UUID5 of file+text)
        for citation in citations:
            if citation.text:
                try:
                    content_hash = hashlib.sha256(citation.text.encode()).hexdigest()
                    file_id = citation.file_path or citation.title or ""
                    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
                    passage_id = str(uuid.uuid5(namespace, f"{file_id}:{content_hash}"))
                    db.upsert_passage(passage_id, file_id, content_hash, citation.text)
                except Exception:
                    pass  # Passage caching is best-effort

    # --- Stage 4: Reranking ---
    if rerank and len(citations) > 1:
        try:
            from objlib.search.reranker import rerank_passages
            reranked = rerank_passages(state.gemini_client, display_query, citations)
            if reranked is not None:
                citations = reranked
        except Exception:
            console.print("[yellow]Reranking unavailable -- showing Gemini ranking[/yellow]")

    # --- Stage 5: Difficulty ordering ---
    try:
        from objlib.search.reranker import apply_difficulty_ordering
        citations = apply_difficulty_ordering(citations, mode=mode)
    except Exception:
        pass  # Ordering failure: use current order

    # --- Stage 6: Session logging ---
    try:
        from objlib.session.manager import SessionManager
        active_session_id = SessionManager.get_active_session_id()
        if active_session_id:
            with Database(state.db_path) as db:
                mgr = SessionManager(db.conn)
                mgr.add_event(active_session_id, "search", {
                    "query": display_query,
                    "expanded_query": search_query if expand else None,
                    "result_count": len(citations),
                    "doc_ids": [c.file_path or c.title for c in citations[:10]],
                })
    except Exception:
        pass  # Session logging is best-effort

    response_text = response.text or "(No response text)"

    # --- Stage 7: Display branch ---
    if track_evolution:
        try:
            from objlib.search.formatter import display_concept_evolution
            display_concept_evolution(citations, display_query, state.gemini_client, console)
        except Exception:
            console.print("[yellow]Evolution display failed -- showing standard results[/yellow]")
            display_search_results(response_text, citations, state.terminal_width, limit=limit)
    elif synthesize:
        try:
            from objlib.search.synthesizer import apply_mmr_diversity, synthesize_answer
            from objlib.search.formatter import display_synthesis
            diverse = apply_mmr_diversity(citations)
            synthesis = synthesize_answer(state.gemini_client, display_query, diverse)
            if synthesis is None:
                console.print("[yellow]Synthesis unavailable -- showing source excerpts[/yellow]")
                display_search_results(response_text, citations, state.terminal_width, limit=limit)
            else:
                display_synthesis(synthesis, diverse, console)
                # Session: log synthesis event
                try:
                    from objlib.session.manager import SessionManager
                    active_session_id = SessionManager.get_active_session_id()
                    if active_session_id:
                        with Database(state.db_path) as db:
                            mgr = SessionManager(db.conn)
                            mgr.add_event(active_session_id, "synthesize", {
                                "query": display_query,
                                "claim_count": len(synthesis.claims),
                            })
                except Exception:
                    pass
        except Exception:
            console.print("[yellow]Synthesis pipeline error -- showing standard results[/yellow]")
            display_search_results(response_text, citations, state.terminal_width, limit=limit)
    else:
        display_search_results(response_text, citations, state.terminal_width, limit=limit)


@app.command()
def view(
    ctx: typer.Context,
    filename: Annotated[
        str,
        typer.Argument(help="Filename to view (e.g., 'Introduction to Objectivism.txt')"),
    ],
    full: Annotated[
        bool, typer.Option("--full", help="Show full document text")
    ] = False,
    show_related: Annotated[
        bool,
        typer.Option("--show-related", help="Show related documents via semantic similarity"),
    ] = False,
    limit: Annotated[
        int, typer.Option("--limit", "-l", help="Max related results")
    ] = 5,
    model: Annotated[
        str, typer.Option("--model", "-m", help="Gemini model")
    ] = "gemini-2.5-flash",
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
    store: Annotated[
        str,
        typer.Option("--store", "-s", help="Gemini File Search store display name"),
    ] = "objectivism-library-v1",
) -> None:
    """View detailed information about a document by filename.

    Copy the filename from search results and pass it here. No session state needed.
    """
    import shutil

    from objlib.models import Citation
    from objlib.search.formatter import (
        display_detailed_view,
        display_full_document,
        display_search_results,
    )

    terminal_width = shutil.get_terminal_size().columns

    if not db_path.exists():
        console.print(
            f"[red]Error:[/red] Database not found: {db_path}\n"
            "Run [bold]objlib scan --library /path/to/library[/bold] first."
        )
        raise typer.Exit(code=1)

    # Look up file by filename in SQLite
    with Database(db_path) as db:
        lookup = db.get_file_metadata_by_filenames([filename])

    if not lookup or filename not in lookup:
        console.print(
            f"[red]Error:[/red] File not found: [bold]{filename}[/bold]\n"
            "Check the filename spelling. Use [bold]objlib search[/bold] to find files."
        )
        raise typer.Exit(code=1)

    match = lookup[filename]
    file_path = match["file_path"]
    metadata = match["metadata"] or {}

    # Build a Citation object for the formatter
    citation = Citation(
        index=1,
        title=filename,
        uri=None,
        text="",  # No passage text for direct view
        document_name=None,
        confidence=metadata.get("quality_score", 0) / 100.0 if metadata.get("quality_score") else 0.0,
        file_path=file_path,
        metadata=metadata,
    )

    # Show detailed view
    display_detailed_view(citation, terminal_width)

    # --full: read and display the actual file content (OFFL-02)
    if full:
        source_path = Path(file_path)
        if source_path.exists():
            try:
                content = source_path.read_text(encoding="utf-8")
                display_full_document(filename, content, terminal_width)
            except Exception as e:
                console.print(f"[red]Error reading file:[/red] {e}")
        else:
            # Distinguish disk disconnection from actual file deletion
            from objlib.sync.disk import check_disk_availability

            availability = check_disk_availability(DEFAULT_LIBRARY_ROOT)
            if availability != "available":
                console.print(
                    f"[yellow]Source disk not connected.[/yellow] Full document text requires "
                    f"the library disk at [dim]{DEFAULT_MOUNT_POINT}[/dim].\n"
                    f"Showing metadata only. Connect the disk and retry with [bold]--full[/bold]."
                )
            else:
                console.print(
                    f"[yellow]Warning:[/yellow] Source file not found on disk: [dim]{file_path}[/dim]\n"
                    "[dim]The file may have been moved or deleted.[/dim]"
                )

    # --show-related: query Gemini for similar documents
    if show_related:
        from objlib.config import get_api_key
        from objlib.search.citations import enrich_citations, extract_citations
        from objlib.search.client import GeminiSearchClient

        try:
            api_key = get_api_key()
        except RuntimeError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1)

        from google import genai

        client = genai.Client(api_key=api_key)

        try:
            resource_name = GeminiSearchClient.resolve_store_name(client, store)
        except Exception as e:
            console.print(f"[red]Failed to resolve store '{store}':[/red] {e}")
            raise typer.Exit(code=1)

        search_client = GeminiSearchClient(client, resource_name)

        # Read a brief excerpt from the file for the similarity query
        excerpt = ""
        source_path = Path(file_path)
        if source_path.exists():
            try:
                content = source_path.read_text(encoding="utf-8")
                excerpt = content[:500]
            except Exception:
                pass

        if not excerpt:
            excerpt = filename  # Fallback to filename as query

        console.print("\n[dim]Finding related documents...[/dim]")

        try:
            response = search_client.query_with_retry(
                f"Find documents related to this content: {excerpt}",
                model=model,
            )
        except Exception as e:
            console.print(f"[red]Related document search failed:[/red] {e}")
            raise typer.Exit(code=1)

        # Extract and enrich citations
        grounding = None
        if response.candidates:
            grounding = response.candidates[0].grounding_metadata

        related_citations = extract_citations(grounding)

        with Database(db_path) as db:
            enrich_citations(related_citations, db, client)

        response_text = response.text or "(Related documents)"
        console.print()
        console.print(Panel("[bold]Related Documents[/bold]", border_style="magenta"))
        display_search_results(
            response_text, related_citations, terminal_width, limit=limit
        )


@app.command()
def browse(
    category: Annotated[
        str | None,
        typer.Option("--category", "-c", help="Filter by category (course, motm, book, etc.)"),
    ] = None,
    course: Annotated[
        str | None,
        typer.Option("--course", help="Show files within a specific course"),
    ] = None,
    year: Annotated[
        str | None,
        typer.Option("--year", "-y", help="Filter by year (within a course)"),
    ] = None,
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
) -> None:
    """Browse the library structure: categories, courses, and files.

    Progressive drill-down:
      objlib browse                              # Show categories
      objlib browse --category course            # Show courses
      objlib browse --course "OPAR"              # Show files in OPAR
      objlib browse --course "OPAR" --year 2023  # Filter by year
    """
    if not db_path.exists():
        console.print(
            f"[yellow]Database not found:[/yellow] {db_path}\n"
            "Run [bold]objlib scan --library /path/to/library[/bold] first."
        )
        raise typer.Exit(code=1)

    with Database(db_path) as db:
        # Level 3: Course specified -- show files within course
        if course is not None:
            files = db.get_files_by_course(course, year=year)

            if not files:
                msg = f"No files found for course '{course}'"
                if year:
                    msg += f" in year {year}"
                console.print(f"[yellow]{msg}[/yellow]")
                return

            title = f"Files in {course}"
            if year:
                title += f" ({year})"

            table = Table(title=title, show_header=True)
            table.add_column("Filename", style="cyan", no_wrap=True)
            table.add_column("Year", justify="right", style="green")
            table.add_column("Quarter", justify="right")
            table.add_column("Week", justify="right")
            table.add_column("Difficulty", style="dim")

            for f in files:
                meta = f["metadata"]
                table.add_row(
                    f["filename"],
                    str(meta.get("year", "")),
                    str(meta.get("quarter", "")),
                    str(meta.get("week", "")),
                    str(meta.get("difficulty", "")),
                )

            console.print(table)
            console.print(f"\n[dim]Found {len(files)} file(s)[/dim]")
            return

        # Level 2: Category specified
        if category is not None:
            if category == "course":
                # Show course listing
                courses = db.get_courses_with_counts()

                if not courses:
                    console.print("[yellow]No courses found.[/yellow]")
                    return

                table = Table(title="Courses", show_header=True)
                table.add_column("Course", style="bold cyan")
                table.add_column("Files", justify="right", style="green")

                for name, count in courses:
                    table.add_row(name or "unnamed", str(count))

                console.print(table)
                console.print(
                    "\n[dim]Drill down: objlib browse --course <name>[/dim]"
                )
            else:
                # Show files in non-course category
                items = db.get_items_by_category(category)

                if not items:
                    console.print(
                        f"[yellow]No files found in category '{category}'[/yellow]"
                    )
                    return

                table = Table(title=f"Files in '{category}'", show_header=True)
                table.add_column("Filename", style="cyan", no_wrap=True)
                table.add_column("Year", justify="right", style="green")
                table.add_column("Difficulty", style="dim")

                for item in items:
                    meta = item["metadata"]
                    table.add_row(
                        item["filename"],
                        str(meta.get("year", "")),
                        str(meta.get("difficulty", "")),
                    )

                console.print(table)
                console.print(f"\n[dim]Found {len(items)} file(s)[/dim]")
            return

        # Level 1: No filters -- show top-level categories
        categories = db.get_categories_with_counts()

        if not categories:
            console.print(
                "[yellow]No files with metadata found in database.[/yellow]"
            )
            return

        table = Table(title="Library Structure", show_header=True)
        table.add_column("Category", style="bold cyan")
        table.add_column("Files", justify="right", style="green")

        for cat, count in categories:
            table.add_row(cat or "uncategorized", str(count))

        console.print(table)
        console.print("\n[dim]Drill down: objlib browse --category <name>[/dim]")


@app.command(name="filter")
def filter_cmd(
    filters: Annotated[
        list[str],
        typer.Argument(
            help="Metadata filters as field:value pairs (e.g., course:OPAR year:2023)"
        ),
    ],
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Max results"),
    ] = 50,
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
) -> None:
    """List files matching metadata filters (no semantic search).

    Queries local SQLite database only -- does not call Gemini API.
    Supports fields: category, course, difficulty, quarter, date, year, week, quality_score.
    Comparison operators: field:>value, field:>=value, field:<value, field:<=value.

    Examples:
      objlib filter course:OPAR
      objlib filter course:OPAR year:2023
      objlib filter year:>=2020 difficulty:introductory
    """
    if not db_path.exists():
        console.print(
            f"[yellow]Database not found:[/yellow] {db_path}\n"
            "Run [bold]objlib scan --library /path/to/library[/bold] first."
        )
        raise typer.Exit(code=1)

    # Parse filter strings into dict
    filters_dict: dict[str, str] = {}
    for f in filters:
        if ":" not in f:
            console.print(
                f"[red]Error:[/red] Invalid filter format: '{f}'\n"
                "Expected format: field:value (e.g., course:OPAR)"
            )
            raise typer.Exit(code=1)
        field, value = f.split(":", 1)
        filters_dict[field] = value

    with Database(db_path) as db:
        try:
            results = db.filter_files_by_metadata(filters_dict, limit=limit)
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

    if not results:
        console.print("[yellow]No files match the given filters.[/yellow]")
        return

    # Display results as Rich table
    filter_desc = ", ".join(f"{k}={v}" for k, v in filters_dict.items())
    table = Table(title=f"Filter: {filter_desc}", show_header=True)
    table.add_column("Filename", style="cyan", no_wrap=True)
    table.add_column("Course", style="bold")
    table.add_column("Year", justify="right", style="green")
    table.add_column("Difficulty", style="dim")
    table.add_column("Category")

    for r in results:
        meta = r["metadata"]
        table.add_row(
            r["filename"],
            str(meta.get("course", "")),
            str(meta.get("year", "")),
            str(meta.get("difficulty", "")),
            str(meta.get("category", "")),
        )

    console.print(table)
    console.print(f"\n[dim]Found {len(results)} file(s) matching filters.[/dim]")


@config_app.command("set-api-key")
def set_api_key(
    key: Annotated[
        str,
        typer.Argument(help="Gemini API key to store in system keyring"),
    ],
) -> None:
    """Store the Gemini API key in the system keyring (service: objlib-gemini)."""
    # Validate key is not empty
    if not key or key.strip() == "":
        console.print("[red]Error:[/red] API key cannot be empty")
        raise typer.Exit(code=1)

    try:
        keyring.set_password("objlib-gemini", "api_key", key)
        console.print(
            "[green]✓[/green] API key stored successfully in system keyring "
            "(service: objlib-gemini)"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to store API key: {e}")
        raise typer.Exit(code=1)


@config_app.command("get-api-key")
def show_api_key() -> None:
    """Retrieve and display the stored Gemini API key (masked)."""
    api_key = keyring.get_password("objlib-gemini", "api_key")
    if not api_key:
        console.print(
            "[yellow]No API key found in keyring.[/yellow]\n"
            "Set it with: [bold]objlib config set-api-key YOUR_KEY[/bold]"
        )
        raise typer.Exit(code=1)

    # Mask all but first 8 characters
    if len(api_key) > 8:
        masked = api_key[:8] + "*" * (len(api_key) - 8)
    else:
        masked = api_key[:2] + "*" * max(1, len(api_key) - 2)

    console.print(f"[green]API key:[/green] {masked}")
    console.print("[dim](stored in service: objlib-gemini)[/dim]")


@config_app.command("remove-api-key")
def remove_api_key() -> None:
    """Delete the stored Gemini API key from the system keyring."""
    try:
        # Check if key exists first
        existing = keyring.get_password("objlib-gemini", "api_key")
        if not existing:
            console.print(
                "[yellow]Warning:[/yellow] No API key found in keyring.\n"
                "Nothing to remove."
            )
            return

        keyring.delete_password("objlib-gemini", "api_key")
        console.print(
            "[green]✓[/green] API key removed from system keyring "
            "(service: objlib-gemini)"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to remove API key: {e}")
        raise typer.Exit(code=1)


@config_app.command("set-mistral-key")
def set_mistral_key(
    key: Annotated[
        str,
        typer.Argument(help="Mistral API key to store in system keyring"),
    ],
) -> None:
    """Store the Mistral API key in the system keyring (service: objlib-mistral)."""
    if not key or key.strip() == "":
        console.print("[red]Error:[/red] API key cannot be empty")
        raise typer.Exit(code=1)

    try:
        keyring.set_password("objlib-mistral", "api_key", key)
        console.print(
            "[green]OK[/green] Mistral API key stored successfully in system keyring "
            "(service: objlib-mistral)"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to store Mistral API key: {e}")
        raise typer.Exit(code=1)


@config_app.command("get-mistral-key")
def show_mistral_key() -> None:
    """Retrieve and display the stored Mistral API key (masked)."""
    api_key = keyring.get_password("objlib-mistral", "api_key")
    if not api_key:
        console.print(
            "[yellow]No Mistral API key found in keyring.[/yellow]\n"
            "Set it with: [bold]objlib config set-mistral-key YOUR_KEY[/bold]"
        )
        raise typer.Exit(code=1)

    # Mask all but first 8 characters
    if len(api_key) > 8:
        masked = api_key[:8] + "*" * (len(api_key) - 8)
    else:
        masked = api_key[:2] + "*" * max(1, len(api_key) - 2)

    console.print(f"[green]Mistral API key:[/green] {masked}")
    console.print("[dim](stored in service: objlib-mistral)[/dim]")


@config_app.command("remove-mistral-key")
def remove_mistral_key() -> None:
    """Delete the stored Mistral API key from the system keyring."""
    try:
        existing = keyring.get_password("objlib-mistral", "api_key")
        if not existing:
            console.print(
                "[yellow]Warning:[/yellow] No Mistral API key found in keyring.\n"
                "Nothing to remove."
            )
            return

        keyring.delete_password("objlib-mistral", "api_key")
        console.print(
            "[green]OK[/green] Mistral API key removed from system keyring "
            "(service: objlib-mistral)"
        )
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to remove Mistral API key: {e}")
        raise typer.Exit(code=1)


@metadata_app.command("show")
def metadata_show(
    filename: Annotated[
        str,
        typer.Argument(help="Filename to show metadata for"),
    ],
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
) -> None:
    """Show current metadata for a file."""
    import json
    
    with Database(db_path) as db:
        row = db.conn.execute(
            "SELECT filename, metadata_json, status FROM files WHERE filename = ?",
            [filename],
        ).fetchone()
        
        if not row:
            console.print(f"[red]Error:[/red] File not found: {filename}")
            raise typer.Exit(code=1)
        
        meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        
        # Display metadata in a panel
        lines = [f"[bold]File:[/bold] {row['filename']}", f"[bold]Status:[/bold] {row['status']}", ""]
        
        if meta:
            lines.append("[bold]Metadata:[/bold]")
            for key in sorted(meta.keys()):
                value = meta[key]
                if value:  # Skip empty values
                    lines.append(f"  {key}: {value}")
        else:
            lines.append("[dim]No metadata available[/dim]")
        
        console.print(Panel("\n".join(lines), title="File Metadata", border_style="cyan"))


@metadata_app.command("update")
def metadata_update(
    filename: Annotated[
        str,
        typer.Argument(help="Filename to update metadata for"),
    ],
    category: Annotated[
        str | None,
        typer.Option("--category", "-c", help="Update category (e.g., course, book, motm, qa_session)"),
    ] = None,
    course: Annotated[
        str | None,
        typer.Option("--course", help="Update course name"),
    ] = None,
    difficulty: Annotated[
        str | None,
        typer.Option("--difficulty", help="Update difficulty (introductory, intermediate, advanced)"),
    ] = None,
    topic: Annotated[
        str | None,
        typer.Option("--topic", help="Update topic"),
    ] = None,
    year: Annotated[
        int | None,
        typer.Option("--year", help="Update year"),
    ] = None,
    quarter: Annotated[
        str | None,
        typer.Option("--quarter", help="Update quarter"),
    ] = None,
    set_pending: Annotated[
        bool,
        typer.Option("--set-pending", help="Set status to pending for re-upload"),
    ] = False,
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
) -> None:
    """Update metadata fields for a specific file.
    
    Examples:
      objlib metadata update "file.txt" --category course --course OPAR
      objlib metadata update "file.txt" --difficulty intermediate --set-pending
    """
    import json
    
    # Collect updates
    updates = {}
    if category is not None:
        updates["category"] = category
    if course is not None:
        updates["course"] = course
    if difficulty is not None:
        updates["difficulty"] = difficulty
    if topic is not None:
        updates["topic"] = topic
    if year is not None:
        updates["year"] = year
    if quarter is not None:
        updates["quarter"] = quarter
    
    if not updates and not set_pending:
        console.print("[yellow]No updates specified. Use --category, --course, etc.[/yellow]")
        raise typer.Exit(code=1)
    
    with Database(db_path) as db:
        # Get current metadata
        row = db.conn.execute(
            "SELECT filename, metadata_json FROM files WHERE filename = ?",
            [filename],
        ).fetchone()
        
        if not row:
            console.print(f"[red]Error:[/red] File not found: {filename}")
            raise typer.Exit(code=1)
        
        # Update metadata
        meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        meta.update(updates)
        
        # Save back to database
        update_query = "UPDATE files SET metadata_json = ?"
        params = [json.dumps(meta)]
        
        if set_pending:
            update_query += ", status = ?"
            params.append("pending")
        
        update_query += " WHERE filename = ?"
        params.append(filename)
        
        db.conn.execute(update_query, params)
        db.conn.commit()
        
        # Show what was updated
        console.print(f"[green]✓[/green] Updated metadata for: {filename}")
        for key, value in updates.items():
            console.print(f"  {key}: [bold]{value}[/bold]")
        
        if set_pending:
            console.print("\n[dim]Status set to 'pending' - run 'objlib upload' to sync with Gemini[/dim]")


@metadata_app.command("batch-update")
def metadata_batch_update(
    pattern: Annotated[
        str,
        typer.Argument(help="Filename pattern to match (SQL LIKE syntax, e.g., '%Stoicism%')"),
    ],
    category: Annotated[
        str | None,
        typer.Option("--category", "-c", help="Update category for all matches"),
    ] = None,
    course: Annotated[
        str | None,
        typer.Option("--course", help="Update course for all matches"),
    ] = None,
    difficulty: Annotated[
        str | None,
        typer.Option("--difficulty", help="Update difficulty for all matches"),
    ] = None,
    set_pending: Annotated[
        bool,
        typer.Option("--set-pending", help="Set status to pending for re-upload"),
    ] = False,
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
) -> None:
    """Update metadata for multiple files matching a pattern.
    
    Uses SQL LIKE syntax: % matches any characters, _ matches single character.
    
    Examples:
      objlib metadata batch-update '%Stoicism%' --category philosophy_comparison
      objlib metadata batch-update '%Q and A%' --category qa_session --set-pending
      objlib metadata batch-update 'Ben Bayer%' --course ARI_Seminars
    """
    import json
    
    # Collect updates
    updates = {}
    if category is not None:
        updates["category"] = category
    if course is not None:
        updates["course"] = course
    if difficulty is not None:
        updates["difficulty"] = difficulty
    
    if not updates and not set_pending:
        console.print("[yellow]No updates specified. Use --category, --course, etc.[/yellow]")
        raise typer.Exit(code=1)
    
    with Database(db_path) as db:
        # Find matching files
        rows = db.conn.execute(
            "SELECT filename, metadata_json FROM files WHERE filename LIKE ?",
            [pattern],
        ).fetchall()
        
        if not rows:
            console.print(f"[yellow]No files match pattern:[/yellow] {pattern}")
            raise typer.Exit(code=0)
        
        console.print(f"Found {len(rows)} matching file(s):")
        for row in rows:
            console.print(f"  - {row['filename']}")
        
        # Confirm
        if not typer.confirm("\nProceed with update?"):
            console.print("Cancelled.")
            raise typer.Exit(code=0)
        
        # Update each file
        for row in rows:
            meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            meta.update(updates)
            
            update_query = "UPDATE files SET metadata_json = ?"
            params = [json.dumps(meta)]
            
            if set_pending:
                update_query += ", status = ?"
                params.append("pending")
            
            update_query += " WHERE filename = ?"
            params.append(row["filename"])
            
            db.conn.execute(update_query, params)
        
        db.conn.commit()
        
        # Show what was updated
        console.print(f"\n[green]✓[/green] Updated {len(rows)} file(s)")
        for key, value in updates.items():
            console.print(f"  {key}: [bold]{value}[/bold]")

        if set_pending:
            console.print("\n[dim]Status set to 'pending' - run 'objlib upload' to sync with Gemini[/dim]")


@metadata_app.command("extract-wave1")
def extract_wave1(
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume from checkpoint after credit exhaustion"),
    ] = False,
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
    debug_store_raw: Annotated[
        bool,
        typer.Option("--debug-store-raw", help="Store raw API responses for debugging"),
    ] = False,
) -> None:
    """Run Wave 1 competitive discovery: 3 strategies x 20 test files.

    Executes three prompt strategies (Minimalist, Teacher, Reasoner)
    against a stratified sample of 20 test files. Results are saved
    to the wave1_results table for comparison.

    If credits are exhausted during execution, a checkpoint is saved
    automatically. Use --resume to continue from where it left off.

    After completion, run 'objlib metadata wave1-report' to compare results.
    """
    import asyncio
    import time as time_mod

    from objlib.config import get_mistral_api_key
    from objlib.extraction.checkpoint import CheckpointManager
    from objlib.extraction.client import MistralClient
    from objlib.extraction.orchestrator import ExtractionConfig, ExtractionOrchestrator
    from objlib.extraction.sampler import select_test_files
    from objlib.extraction.strategies import WAVE1_STRATEGIES

    # Load Mistral API key
    try:
        api_key = get_mistral_api_key()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {db_path}")
        raise typer.Exit(code=1)

    checkpoint = CheckpointManager()

    with Database(db_path) as db:
        # Determine test files
        if resume and checkpoint.exists:
            checkpoint_data = checkpoint.load()
            if checkpoint_data:
                console.print(
                    Panel(
                        f"[bold]Resuming Wave 1[/bold] from checkpoint\n"
                        f"Saved: {checkpoint_data.get('timestamp', 'unknown')}\n"
                        f"Prompt version: {checkpoint_data.get('prompt_version', 'unknown')}",
                        title="Resume",
                        border_style="yellow",
                    )
                )
                # Show per-lane progress
                for lane_name, lane_data in checkpoint_data.get("lanes", {}).items():
                    completed = len(lane_data.get("completed", []))
                    failed = len(lane_data.get("failed", []))
                    console.print(
                        f"  {lane_name}: {completed} completed, {failed} failed"
                    )
            # Still need full test file list for the orchestrator
            test_files = select_test_files(db, n=20)
        else:
            if resume:
                console.print(
                    "[yellow]No checkpoint found. Starting fresh Wave 1 run.[/yellow]"
                )
            test_files = select_test_files(db, n=20)

        if not test_files:
            console.print("[yellow]No eligible test files found in database.[/yellow]")
            raise typer.Exit(code=1)

        # Display selection summary
        console.print(
            Panel(
                f"[bold]Wave 1 Discovery[/bold]\n"
                f"Test files: {len(test_files)}\n"
                f"Strategies: {', '.join(WAVE1_STRATEGIES.keys())}\n"
                f"Total API calls: ~{len(test_files) * len(WAVE1_STRATEGIES)}",
                title="Extraction",
                border_style="cyan",
            )
        )

        # Create orchestrator
        client = MistralClient(api_key=api_key)
        config = ExtractionConfig()
        orchestrator = ExtractionOrchestrator(
            client=client, db=db, checkpoint=checkpoint, config=config
        )

        # Run Wave 1
        start_time = time_mod.monotonic()
        summary = asyncio.run(
            orchestrator.run_wave1(test_files, WAVE1_STRATEGIES)
        )
        elapsed = time_mod.monotonic() - start_time

        # Display summary
        console.print("\n")
        summary_table = Table(title="Wave 1 Execution Summary")
        summary_table.add_column("Strategy", style="cyan bold")
        summary_table.add_column("Completed", justify="right", style="green")
        summary_table.add_column("Failed", justify="right", style="red")
        summary_table.add_column("Total Tokens", justify="right")
        summary_table.add_column("Avg Latency (ms)", justify="right")

        total_tokens_all = 0
        for name, data in summary.items():
            summary_table.add_row(
                name,
                str(data.get("completed", 0)),
                str(data.get("failed", 0)),
                f"{data.get('total_tokens', 0):,}",
                f"{data.get('avg_latency_ms', 0):,.0f}",
            )
            total_tokens_all += data.get("total_tokens", 0)

        console.print(summary_table)

        # Cost estimate
        estimated_cost = (total_tokens_all / 1000) * 0.007
        console.print(f"\n  Total tokens: [bold]{total_tokens_all:,}[/bold]")
        console.print(f"  Estimated cost: [bold]${estimated_cost:.2f}[/bold]")
        console.print(f"  Time elapsed: [bold]{elapsed:.1f}s[/bold]")

        console.print(
            "\n[bold]Next step:[/bold] Run [cyan]objlib metadata wave1-report[/cyan] "
            "to compare results"
        )


@metadata_app.command("wave1-report")
def wave1_report(
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
    export_csv: Annotated[
        Path | None,
        typer.Option("--export-csv", help="Export results to CSV file"),
    ] = None,
    file: Annotated[
        str | None,
        typer.Option("--file", "-f", help="Show single file comparison across strategies"),
    ] = None,
) -> None:
    """Compare Wave 1 strategy results with metrics and quality gate evaluation.

    Shows a comparison table of all strategies with metrics: avg tokens,
    avg latency, avg confidence, validation pass rate, and failed count.

    Quality gates are evaluated against the best strategy to determine
    Wave 2 readiness.

    Use --file to see side-by-side comparison for a specific file.
    Use --export-csv to export all results for detailed offline analysis.
    """
    from objlib.extraction.quality_gates import (
        display_gate_results,
        evaluate_quality_gates,
        recommend_strategy,
    )
    from objlib.extraction.report import (
        display_file_comparison,
        display_wave1_report,
        export_wave1_csv,
        generate_wave1_report,
    )

    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {db_path}")
        raise typer.Exit(code=1)

    with Database(db_path) as db:
        if file:
            display_file_comparison(db, file, console)
            return

        # Generate and display main report
        report = generate_wave1_report(db)

        if not report:
            console.print(
                "[yellow]No Wave 1 results found.[/yellow]\n"
                "Run [bold]objlib metadata extract-wave1[/bold] first."
            )
            raise typer.Exit(code=1)

        display_wave1_report(report, console)

        # Quality gates
        console.print()
        all_passed, gates = evaluate_quality_gates(report)
        display_gate_results(gates, console)

        # Strategy recommendation
        rec = recommend_strategy(report)
        console.print(
            f"\n[bold]Recommended strategy:[/bold] [green bold]{rec}[/green bold]"
        )

        # Export CSV if requested
        if export_csv:
            export_wave1_csv(db, export_csv)

        # Next step guidance
        console.print()
        if all_passed:
            console.print(
                "[bold]Quality gates PASSED.[/bold] Select strategy:\n"
                f"  [cyan]objlib metadata wave1-select {rec}[/cyan]"
            )
        else:
            console.print(
                "[bold yellow]Quality gates FAILED.[/bold yellow] "
                "Consider Wave 1.5 or manual adjustments."
            )


@metadata_app.command("wave1-select")
def wave1_select(
    strategy: Annotated[
        str,
        typer.Argument(help="Strategy to use for Wave 2 (minimalist, teacher, reasoner, or hybrid)"),
    ],
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
) -> None:
    """Select the winning strategy for Wave 2 production processing.

    After reviewing Wave 1 results with 'wave1-report', select the
    strategy to use for processing all remaining files.

    Valid strategies: minimalist, teacher, reasoner, hybrid.
    If 'hybrid' is selected, a combined template will be constructed
    from the best elements of each strategy during Wave 2 setup.
    """
    import json as json_mod
    from datetime import datetime, timezone

    from objlib.extraction.prompts import PROMPT_VERSION

    valid_strategies = {"minimalist", "teacher", "reasoner", "hybrid"}
    if strategy not in valid_strategies:
        console.print(
            f"[red]Error:[/red] Invalid strategy: '{strategy}'\n"
            f"Valid options: {', '.join(sorted(valid_strategies))}"
        )
        raise typer.Exit(code=1)

    if strategy == "hybrid":
        console.print(
            "[yellow]Hybrid selected:[/yellow] A combined template will be "
            "constructed from the best elements of each strategy during "
            "Wave 2 setup."
        )

    # Save selection to JSON
    selection = {
        "strategy": strategy,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "prompt_version": PROMPT_VERSION,
    }

    selection_path = Path("data/wave1_selection.json")
    selection_path.parent.mkdir(parents=True, exist_ok=True)
    selection_path.write_text(json_mod.dumps(selection, indent=2))

    console.print(
        f"\n[green]OK[/green] Strategy [bold]'{strategy}'[/bold] selected "
        f"for Wave 2 production processing."
    )
    console.print(f"[dim]Saved to: {selection_path}[/dim]")
    console.print(
        "\n[bold]Next step:[/bold] Run [cyan]objlib metadata extract[/cyan] "
        "to process remaining files with the selected strategy."
    )


@metadata_app.command("extract")
def extract_production(
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume from checkpoint after credit exhaustion"),
    ] = False,
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show file count and cost estimate without processing"),
    ] = False,
    set_pending: Annotated[
        bool,
        typer.Option("--set-pending", help="Set upload status to pending for re-upload with enriched metadata"),
    ] = False,
) -> None:
    """Run Wave 2 production extraction on remaining unknown files.

    Processes ~453 files with the winning strategy selected via 'wave1-select'.
    Uses validated prompt template, two-level validation, multi-dimensional
    confidence scoring, and versioned metadata persistence.

    Use --dry-run to preview file count and estimated cost.
    Use --resume to continue after credit exhaustion.
    Use --set-pending to mark extracted files for re-upload with enriched metadata.
    """
    import asyncio
    import json as json_mod
    import time as time_mod

    from objlib.config import get_mistral_api_key
    from objlib.extraction.checkpoint import CheckpointManager
    from objlib.extraction.client import MistralClient
    from objlib.extraction.orchestrator import ExtractionConfig, ExtractionOrchestrator

    # Load Mistral API key
    try:
        api_key = get_mistral_api_key()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {db_path}")
        raise typer.Exit(code=1)

    # Load winning strategy
    selection_path = Path("data/wave1_selection.json")
    if not selection_path.exists():
        console.print(
            "[red]Error:[/red] No strategy selected.\n"
            "Run [bold]objlib metadata extract-wave1[/bold] and "
            "[bold]objlib metadata wave1-select[/bold] first."
        )
        raise typer.Exit(code=1)

    selection = json_mod.loads(selection_path.read_text())
    strategy_name = selection["strategy"]

    with Database(db_path) as db:
        # Get pending extraction files
        checkpoint = CheckpointManager()
        config = ExtractionConfig()
        client = MistralClient(api_key=api_key)
        orchestrator = ExtractionOrchestrator(
            client=client, db=db, checkpoint=checkpoint, config=config
        )

        pending_files = orchestrator._get_pending_extraction_files()
        count = len(pending_files)

        if count == 0:
            console.print("[green]No pending files for extraction.[/green]")
            return

        # Dry-run mode
        if dry_run:
            estimated_cost = count * 0.02
            estimated_time = count * 3  # ~3 seconds per file average
            console.print(
                Panel(
                    f"[bold]{count}[/bold] files pending extraction\n"
                    f"Strategy: [cyan]{strategy_name}[/cyan]\n"
                    f"Estimated cost: [yellow]${estimated_cost:.2f}[/yellow]\n"
                    f"Estimated time: ~{estimated_time // 60} min {estimated_time % 60} sec",
                    title="Dry Run",
                    border_style="yellow",
                )
            )
            return

        # Production extraction
        console.print(
            Panel(
                f"Processing [bold]{count}[/bold] files with "
                f"strategy [cyan]'{strategy_name}'[/cyan]\n"
                f"Prompt version: {selection.get('prompt_version', 'unknown')}",
                title="Wave 2 Production Extraction",
                border_style="green",
            )
        )

        start_time = time_mod.monotonic()
        summary = asyncio.run(
            orchestrator.run_production(pending_files, strategy_name)
        )
        elapsed = time_mod.monotonic() - start_time

        # Display summary
        summary_table = Table(title="Extraction Summary")
        summary_table.add_column("Metric", style="bold")
        summary_table.add_column("Value", justify="right")

        summary_table.add_row("Extracted", f"[green]{summary.get('extracted', 0)}[/green]")
        summary_table.add_row("Needs Review", f"[yellow]{summary.get('needs_review', 0)}[/yellow]")
        summary_table.add_row("Failed", f"[red]{summary.get('failed', 0)}[/red]")
        summary_table.add_row("Total Tokens", f"{summary.get('total_tokens', 0):,}")
        summary_table.add_row("Estimated Cost", f"${summary.get('estimated_cost', 0):.2f}")
        summary_table.add_row("Avg Latency", f"{summary.get('avg_latency_ms', 0):,.0f} ms")
        summary_table.add_row("Time Elapsed", f"{elapsed:.1f}s")

        console.print(summary_table)

        # Set pending for re-upload if requested
        if set_pending:
            with db.conn:
                cursor = db.conn.execute(
                    "UPDATE files SET status = 'pending' "
                    "WHERE ai_metadata_status IN ('extracted', 'approved')"
                )
                pending_count = cursor.rowcount
            console.print(
                f"\n[green]Set {pending_count} file(s) to pending for re-upload.[/green]"
            )

        console.print(
            "\n[bold]Next steps:[/bold]\n"
            "  Run [cyan]objlib metadata review[/cyan] to check results\n"
            "  Run [cyan]objlib metadata approve --min-confidence 0.85[/cyan] to auto-approve"
        )


@metadata_app.command("review")
def review_metadata(
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
    status: Annotated[
        str | None,
        typer.Option("--status", "-s", help="Filter by ai_metadata_status"),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", "-i", help="Interactive review with Accept/Edit/Rerun/Skip/Quit"),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Max files to display"),
    ] = 50,
) -> None:
    """Review AI-extracted metadata with Rich 4-tier panels.

    Non-interactive mode shows a summary table. Interactive mode lets you
    Accept, Edit, Rerun, Skip, or Quit for each file.

    Use --status to filter: extracted, needs_review, approved, failed_validation.
    """
    from objlib.extraction.review import (
        display_review_table,
        interactive_review,
    )

    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {db_path}")
        raise typer.Exit(code=1)

    with Database(db_path) as db:
        if interactive:
            interactive_review(db, console, status_filter=status)
            return

        # Non-interactive: display table
        if status:
            files = db.get_files_by_ai_status(status, limit=limit)
        else:
            # Show all extracted + needs_review
            files = db.get_files_by_ai_status("extracted", limit=limit)
            files.extend(db.get_files_by_ai_status("needs_review", limit=limit))

        if not files:
            console.print("[yellow]No files to review.[/yellow]")
            return

        display_review_table(files, console)

        # Show stats
        stats = db.get_ai_metadata_stats()
        if stats:
            console.print("\n[bold]AI Metadata Status:[/bold]")
            for s, count in sorted(stats.items()):
                console.print(f"  {s}: {count}")


@metadata_app.command("approve")
def approve_metadata(
    min_confidence: Annotated[
        float,
        typer.Option("--min-confidence", "-c", help="Minimum confidence for auto-approval"),
    ] = 0.85,
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt"),
    ] = False,
) -> None:
    """Auto-approve extracted metadata above a confidence threshold.

    Files with confidence >= threshold are set to 'approved' status.
    Default threshold is 0.85 (85%).
    """
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {db_path}")
        raise typer.Exit(code=1)

    with Database(db_path) as db:
        # Preview count
        preview = db.conn.execute(
            "SELECT COUNT(*) as cnt FROM files "
            "WHERE ai_metadata_status IN ('extracted', 'needs_review') "
            "AND ai_confidence_score >= ?",
            (min_confidence,),
        ).fetchone()
        preview_count = preview["cnt"] if preview else 0

        if preview_count == 0:
            console.print(
                f"[yellow]No files with confidence >= {min_confidence:.0%} "
                f"to approve.[/yellow]"
            )
            return

        console.print(
            f"Found [bold]{preview_count}[/bold] file(s) with confidence "
            f">= {min_confidence:.0%} ready for approval."
        )

        if not yes:
            proceed = typer.confirm("Proceed with approval?")
            if not proceed:
                console.print("[yellow]Approval cancelled.[/yellow]")
                return

        count = db.approve_files_by_confidence(min_confidence)
        console.print(
            f"[green]Approved {count} file(s) with confidence "
            f">= {min_confidence:.0%}.[/green]"
        )


@metadata_app.command("stats")
def extraction_stats(
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
) -> None:
    """Show comprehensive AI metadata extraction statistics.

    Displays status distribution, confidence metrics, and coverage percentage.
    """
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {db_path}")
        raise typer.Exit(code=1)

    with Database(db_path) as db:
        summary = db.get_extraction_summary()
        stats = db.get_ai_metadata_stats()

        # Status table
        status_table = Table(title="AI Metadata Status Distribution")
        status_table.add_column("Status", style="bold")
        status_table.add_column("Count", justify="right")

        status_styles = {
            "extracted": "green",
            "approved": "bold green",
            "needs_review": "yellow",
            "pending": "dim",
            "failed_validation": "red",
            "failed_json": "red",
            "retry_scheduled": "yellow",
        }

        for s, count in sorted(stats.items()):
            style = status_styles.get(s, "")
            if style:
                status_table.add_row(s, f"[{style}]{count}[/{style}]")
            else:
                status_table.add_row(s, str(count))

        console.print(status_table)

        # Summary panel
        total_processed = summary["extracted"] + summary["approved"] + summary["needs_review"]
        total_unknown = summary["total_unknown_txt"]
        coverage = (total_processed / total_unknown * 100) if total_unknown > 0 else 0.0

        console.print(
            Panel(
                f"Total unknown TXT files: [bold]{total_unknown}[/bold]\n"
                f"Processed: [bold]{total_processed}[/bold] "
                f"([green]{coverage:.1f}%[/green] coverage)\n"
                f"Pending: {summary['pending']}\n"
                f"Failed: [red]{summary['failed']}[/red]\n"
                f"\n"
                f"Confidence (extracted/approved/needs_review):\n"
                f"  Average: [bold]{summary['avg_confidence']:.0%}[/bold]\n"
                f"  Min: {summary['min_confidence']:.0%}  "
                f"Max: {summary['max_confidence']:.0%}",
                title="Extraction Summary",
                border_style="cyan",
            )
        )


@metadata_app.command("batch-extract")
def batch_extract_metadata(
    max_files: Annotated[
        int | None,
        typer.Option("--max", "-n", help="Maximum files to process (default: all pending)"),
    ] = None,
    job_name: Annotated[
        str | None,
        typer.Option("--name", help="Descriptive name for batch job"),
    ] = None,
    poll_interval: Annotated[
        int,
        typer.Option("--poll", "-p", help="Seconds between status checks"),
    ] = 30,
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
) -> None:
    """Extract metadata using Mistral Batch API (50% cost savings, no rate limits).

    Uses Mistral's async Batch API for bulk extraction:
    - 50% lower cost than synchronous extraction
    - Zero rate limiting issues (perfect for 116-1,093 pending files)
    - Submits all requests as one batch job
    - Polls for completion (typically 20-60 minutes)
    - Updates database with results
    - Tracks failed requests for retry

    Examples:
        # Extract all pending files
        objlib metadata batch-extract

        # Extract first 50 files
        objlib metadata batch-extract --max 50

        # Custom job name
        objlib metadata batch-extract --name "unknown-files-batch-1"
    """
    import asyncio

    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {db_path}")
        raise typer.Exit(code=1)

    # Load API key from keyring
    try:
        import keyring

        api_key = keyring.get_password("objlib-mistral", "api_key")
        if not api_key:
            console.print(
                "[red]Error:[/red] Mistral API key not found in keyring.\n\n"
                "Store your API key using:\n"
                "[bold]keyring set objlib-mistral api_key[/bold]"
            )
            raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to load API key: {e}")
        raise typer.Exit(code=1)

    # Initialize batch client and orchestrator
    from objlib.extraction.batch_client import MistralBatchClient
    from objlib.extraction.batch_orchestrator import BatchExtractionOrchestrator

    console.print("[bold]Mistral Batch API Extraction[/bold]")
    console.print(f"[dim]Database: {db_path}[/dim]")
    console.print(f"[dim]Poll interval: {poll_interval}s[/dim]\n")

    with Database(db_path) as db:
        client = MistralBatchClient(api_key=api_key)
        orchestrator = BatchExtractionOrchestrator(
            db=db,
            client=client,
            strategy_name="minimalist",  # Use winning Wave 1 strategy
        )

        # Run batch extraction
        console.print("[cyan]Starting batch extraction...[/cyan]")

        try:
            print("DEBUG: About to call asyncio.run()", flush=True)
            summary = asyncio.run(
                orchestrator.run_batch_extraction(
                    max_files=max_files,
                    job_name=job_name,
                    poll_interval=poll_interval,
                )
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted by user[/yellow]")
            raise typer.Exit(code=130)
        except Exception as e:
            console.print(f"\n[red]Batch extraction failed:[/red] {e}")
            raise typer.Exit(code=1)

    # Display results
    console.print("\n[bold green]✓ Batch Extraction Complete[/bold green]")

    result_table = Table(title="Batch Summary")
    result_table.add_column("Metric", style="bold")
    result_table.add_column("Value", justify="right")

    result_table.add_row("Batch ID", summary["batch_id"] or "N/A")
    result_table.add_row("Total Files", str(summary["total"]))
    result_table.add_row("Succeeded", f"[green]{summary['succeeded']}[/green]")
    result_table.add_row("Failed", f"[red]{summary['failed']}[/red]")
    result_table.add_row(
        "Processing Time",
        f"{summary['processing_time_seconds']:.1f}s ({summary['processing_time_seconds']/60:.1f}m)",
    )

    console.print(result_table)

    if summary["failed_files"]:
        console.print(f"\n[yellow]⚠ {len(summary['failed_files'])} files failed:[/yellow]")
        for file_path in summary["failed_files"][:10]:  # Show first 10
            console.print(f"  [dim]• {Path(file_path).name}[/dim]")
        if len(summary["failed_files"]) > 10:
            console.print(f"  [dim]... and {len(summary['failed_files']) - 10} more[/dim]")

        console.print(
            "\n[bold]Failed files marked in database:[/bold] "
            "ai_metadata_status='failed_validation'\n"
            "Review errors and retry with [cyan]objlib metadata batch-extract[/cyan]"
        )

    # Show oversized files (too large for Mistral, will use Gemini File Search only)
    if summary.get("oversized_files"):
        console.print(f"\n[blue]ℹ {len(summary['oversized_files'])} files too large for extraction:[/blue]")
        for file_path in summary["oversized_files"][:10]:  # Show first 10
            console.print(f"  [dim]• {Path(file_path).name}[/dim]")
        if len(summary["oversized_files"]) > 10:
            console.print(f"  [dim]... and {len(summary['oversized_files']) - 10} more[/dim]")

        console.print(
            "\n[bold]Oversized files marked as skipped:[/bold]\n"
            "These files exceed Mistral's context window (~100K tokens).\n"
            "They are uploaded to Gemini File Search without enriched metadata extraction.\n"
            "Gemini File Search (2M token context) handles them natively."
        )

    if not summary["failed_files"] and not summary.get("oversized_files"):
        console.print("\n[bold green]✓ All files processed successfully![/bold green]")

    console.print(
        "\n[bold]Next:[/bold] Run [cyan]objlib metadata stats[/cyan] "
        "to see updated extraction progress"
    )


# ---- Entity extraction commands (Phase 6.1) ----


@entities_app.command("extract")
def entities_extract(
    mode: Annotated[
        str,
        typer.Option(
            "--mode", "-m",
            help="Extraction mode: pending (default), backfill, force, upgrade",
        ),
    ] = "pending",
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum files to process"),
    ] = 500,
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
    library_root: Annotated[
        Path,
        typer.Option(
            "--library-root",
            help="Path to library root directory",
        ),
    ] = Path("/Volumes/U32 Shadow/Objectivism Library"),
    use_llm: Annotated[
        bool,
        typer.Option("--use-llm", help="Enable LLM fallback for 80-91 fuzzy range"),
    ] = False,
) -> None:
    """Extract person entities from transcript files.

    Runs deterministic-first entity extraction (exact match, alias match,
    RapidFuzz fuzzy match) against the canonical registry of 15 Objectivist
    philosophers and ARI instructors.

    Modes:
      pending   - Files not yet extracted (default)
      backfill  - Already-uploaded files missing entity data
      force     - All .txt files, re-extracting everything
      upgrade   - Files extracted with an older version
    """
    # Deferred imports for fast CLI startup
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

    from objlib.entities.extractor import EntityExtractor
    from objlib.entities.registry import PersonRegistry

    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {db_path}")
        raise typer.Exit(code=1)

    with Database(db_path) as db:
        # Initialize registry and extractor
        registry = PersonRegistry(db)

        mistral_client = None
        if use_llm:
            try:
                api_key = keyring.get_password("objlib-mistral", "api_key")
                if api_key:
                    from objlib.extraction.client import MistralClient
                    mistral_client = MistralClient(api_key=api_key)
                    console.print("[dim]LLM fallback enabled (Mistral)[/dim]")
                else:
                    console.print(
                        "[yellow]Warning:[/yellow] --use-llm requested but no Mistral API key found. "
                        "Continuing without LLM fallback."
                    )
            except Exception as e:
                console.print(f"[yellow]Warning:[/yellow] LLM init failed: {e}. Continuing without.")

        extractor = EntityExtractor(registry, mistral_client=mistral_client)

        # Query files to process
        try:
            files = db.get_files_needing_entity_extraction(mode, limit)
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=1)

        if not files:
            console.print(f"[green]No files to process in '{mode}' mode.[/green]")
            return

        console.print(
            Panel(
                f"Mode: [cyan]{mode}[/cyan]\n"
                f"Files to process: [bold]{len(files)}[/bold]\n"
                f"Library root: {library_root}\n"
                f"LLM fallback: {'enabled' if mistral_client else 'disabled'}",
                title="Entity Extraction",
                border_style="cyan",
            )
        )

        succeeded = 0
        failed = 0
        skipped = 0
        # Track person mentions across the batch for summary
        batch_persons: dict[str, int] = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Extracting entities...", total=len(files))

            for file_info in files:
                fp = file_info["file_path"]
                fn = file_info["filename"]
                progress.update(task, description=f"[cyan]{fn[:50]}[/cyan]")

                try:
                    # Read file content
                    source_path = library_root / fp
                    if not source_path.exists():
                        logger.warning("File not found: %s", source_path)
                        # Mark as error in database
                        from objlib.entities.models import EntityExtractionResult
                        error_result = EntityExtractionResult(
                            file_path=fp,
                            entities=[],
                            status="error",
                        )
                        db.save_transcript_entities(fp, error_result)
                        skipped += 1
                        progress.advance(task)
                        continue

                    text = source_path.read_text(encoding="utf-8")

                    # Extract entities
                    result = extractor.extract(text, fp)
                    db.save_transcript_entities(fp, result)
                    succeeded += 1

                    # Track persons for batch summary
                    for entity in result.entities:
                        batch_persons[entity.canonical_name] = (
                            batch_persons.get(entity.canonical_name, 0) + 1
                        )

                except Exception as e:
                    logger.error("Entity extraction failed for %s: %s", fp, e)
                    try:
                        from objlib.entities.models import EntityExtractionResult
                        error_result = EntityExtractionResult(
                            file_path=fp,
                            entities=[],
                            status="blocked_entity_extraction",
                        )
                        db.save_transcript_entities(fp, error_result)
                    except Exception:
                        pass
                    failed += 1

                progress.advance(task)

        # Print summary
        console.print()
        summary_table = Table(title="Extraction Summary")
        summary_table.add_column("Metric", style="bold")
        summary_table.add_column("Count", justify="right")

        summary_table.add_row("Processed", str(succeeded + failed + skipped))
        summary_table.add_row("Succeeded", f"[green]{succeeded}[/green]")
        summary_table.add_row("Failed", f"[red]{failed}[/red]")
        summary_table.add_row("Skipped (not found)", f"[yellow]{skipped}[/yellow]")

        console.print(summary_table)

        # Top-5 most mentioned persons
        if batch_persons:
            top_persons = sorted(batch_persons.items(), key=lambda x: x[1], reverse=True)[:5]
            console.print("\n[bold]Top mentioned persons (this batch):[/bold]")
            for name, count in top_persons:
                console.print(f"  {name}: {count} transcript(s)")


@entities_app.command("stats")
def entities_stats(
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
) -> None:
    """Show entity extraction coverage, person frequency, and error counts."""
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {db_path}")
        raise typer.Exit(code=1)

    with Database(db_path) as db:
        stats = db.get_entity_stats()

        total_txt = stats["total_txt"]
        done = stats["entities_done"]
        pending = stats["pending"]
        errors = stats["errors"]
        coverage = (done / total_txt * 100) if total_txt > 0 else 0.0

        # Coverage panel
        console.print(
            Panel(
                f"Total .txt files: [bold]{total_txt}[/bold]\n"
                f"Entities extracted: [green]{done}[/green] "
                f"([green]{coverage:.1f}%[/green] coverage)\n"
                f"Pending: [yellow]{pending}[/yellow]\n"
                f"Errors: [red]{errors}[/red]\n"
                f"\n"
                f"Total mentions: [bold]{stats['total_mentions']}[/bold]\n"
                f"Unique persons: [bold]{stats['unique_persons']}[/bold]",
                title="Entity Extraction Coverage",
                border_style="cyan",
            )
        )

        # Person frequency table
        if stats["person_frequency"]:
            freq_table = Table(title="Person Frequency")
            freq_table.add_column("Person", style="bold cyan")
            freq_table.add_column("Transcripts", justify="right", style="green")
            freq_table.add_column("Total Mentions", justify="right")

            for name, transcript_count, total_mentions in stats["person_frequency"]:
                freq_table.add_row(name, str(transcript_count), str(total_mentions))

            console.print(freq_table)
        else:
            console.print("[dim]No entity data yet. Run 'objlib entities extract' first.[/dim]")


@entities_app.command("report")
def entities_report(
    person: Annotated[
        str,
        typer.Argument(help="Person name or alias to report on"),
    ] = "",
    low_confidence: Annotated[
        bool,
        typer.Option(
            "--low-confidence",
            help="Show entities with confidence < 0.7",
        ),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", "-l", help="Maximum results"),
    ] = 50,
    db_path: Annotated[
        Path,
        typer.Option("--db", "-d", help="Path to SQLite database"),
    ] = Path("data/library.db"),
) -> None:
    """Report on entity mentions: per-person transcripts or low-confidence review.

    Examples:
      objlib entities report "Leonard Peikoff"
      objlib entities report Peikoff
      objlib entities report --low-confidence
    """
    if not db_path.exists():
        console.print(f"[red]Error:[/red] Database not found: {db_path}")
        raise typer.Exit(code=1)

    with Database(db_path) as db:
        if person:
            # Resolve to person_id
            person_id = db.get_person_by_name_or_alias(person)
            if not person_id:
                console.print(
                    f"[red]Error:[/red] Person not found: [bold]{person}[/bold]\n"
                    "Run [cyan]objlib entities stats[/cyan] to see valid person names."
                )
                raise typer.Exit(code=1)

            # Get canonical name for display
            row = db.conn.execute(
                "SELECT canonical_name FROM person WHERE person_id = ?",
                (person_id,),
            ).fetchone()
            canonical_name = row["canonical_name"] if row else person_id

            transcripts = db.get_transcripts_by_person(person_id, limit)

            if not transcripts:
                console.print(
                    f"[yellow]No transcripts found mentioning {canonical_name}.[/yellow]"
                )
                return

            console.print(
                Panel(
                    f"[bold]{canonical_name}[/bold] -- {len(transcripts)} transcript(s)",
                    title="Person Report",
                    border_style="cyan",
                )
            )

            report_table = Table(show_header=True)
            report_table.add_column("Filename", style="cyan", max_width=50)
            report_table.add_column("Mentions", justify="right", style="bold")
            report_table.add_column("Confidence", justify="right")
            report_table.add_column("Evidence", max_width=60)

            for t in transcripts:
                conf = t["max_confidence"] or 0.0
                if conf >= 0.9:
                    conf_style = "[green]"
                elif conf >= 0.7:
                    conf_style = "[yellow]"
                else:
                    conf_style = "[red]"
                conf_str = f"{conf_style}{conf:.0%}[/{conf_style[1:]}"

                evidence = (t["evidence_sample"] or "")[:60]

                report_table.add_row(
                    t["filename"],
                    str(t["mention_count"]),
                    conf_str,
                    evidence,
                )

            console.print(report_table)

        elif low_confidence:
            # Query low-confidence entities
            rows = db.conn.execute(
                """SELECT f.filename, te.person_id, p.canonical_name,
                          te.max_confidence, te.evidence_sample
                   FROM transcript_entity te
                   JOIN files f ON te.transcript_id = f.file_path
                   JOIN person p ON te.person_id = p.person_id
                   WHERE te.max_confidence < 0.7
                   ORDER BY te.max_confidence ASC
                   LIMIT ?""",
                (limit,),
            ).fetchall()

            if not rows:
                console.print("[green]No low-confidence entities found.[/green]")
                return

            console.print(
                Panel(
                    f"[bold]{len(rows)}[/bold] entities with confidence < 0.7",
                    title="Low Confidence Review",
                    border_style="yellow",
                )
            )

            lc_table = Table(show_header=True)
            lc_table.add_column("Filename", style="cyan", max_width=40)
            lc_table.add_column("Person", style="bold")
            lc_table.add_column("Confidence", justify="right", style="red")
            lc_table.add_column("Evidence", max_width=50)

            for row in rows:
                evidence = (row["evidence_sample"] or "")[:50]
                lc_table.add_row(
                    row["filename"],
                    row["canonical_name"],
                    f"{row['max_confidence']:.0%}",
                    evidence,
                )

            console.print(lc_table)

        else:
            console.print(
                "[yellow]Usage:[/yellow] Provide a person name or use --low-confidence\n\n"
                "Examples:\n"
                "  objlib entities report \"Leonard Peikoff\"\n"
                "  objlib entities report Peikoff\n"
                "  objlib entities report --low-confidence"
            )


# ---- Session Commands ----


@session_app.command("start")
def session_start(
    name: Annotated[str | None, typer.Argument(help="Session name (auto-generated if omitted)")] = None,
    db_path: Annotated[Path, typer.Option("--db", help="Database path")] = Path("data/library.db"),
) -> None:
    """Start a new research session."""
    from objlib.session.manager import SessionManager
    with Database(db_path) as db:
        mgr = SessionManager(db.conn)
        sid = mgr.create(name)
        session = mgr.get_session(sid)
        console.print(Panel(
            f"[bold]Session ID:[/bold] {sid}\n"
            f"[bold]Name:[/bold] {session['name']}\n\n"
            f"[dim]To auto-attach searches:[/dim]\n"
            f"[bold cyan]export OBJLIB_SESSION={sid}[/bold cyan]",
            title="Session Created",
            border_style="cyan",
        ))


@session_app.command("list")
def session_list(
    db_path: Annotated[Path, typer.Option("--db", help="Database path")] = Path("data/library.db"),
) -> None:
    """List all research sessions."""
    from objlib.session.manager import SessionManager
    with Database(db_path) as db:
        mgr = SessionManager(db.conn)
        sessions = mgr.list_sessions()
    if not sessions:
        console.print("[dim]No sessions found. Run 'objlib session start' to create one.[/dim]")
        return
    table = Table(title="Research Sessions", border_style="cyan")
    table.add_column("ID", style="dim", width=10)
    table.add_column("Name", style="bold")
    table.add_column("Created")
    table.add_column("Events", justify="right")
    for s in sessions:
        table.add_row(s["id"][:8], s["name"] or "(unnamed)", s["created_at"][:19], str(s["event_count"]))
    console.print(table)


@session_app.command("resume")
def session_resume(
    session_id: Annotated[str, typer.Argument(help="Session ID or prefix")],
    db_path: Annotated[Path, typer.Option("--db", help="Database path")] = Path("data/library.db"),
) -> None:
    """Resume a session -- display its saved timeline."""
    from objlib.session.manager import SessionManager
    with Database(db_path) as db:
        mgr = SessionManager(db.conn)
        session = mgr.find_by_prefix(session_id) or mgr.get_session(session_id)
        if not session:
            console.print(f"[red]Session not found:[/red] {session_id}")
            raise typer.Exit(code=1)
        mgr.display_timeline(session["id"], console)


@session_app.command("note")
def session_note(
    text: Annotated[str, typer.Argument(help="Note text to add")],
    db_path: Annotated[Path, typer.Option("--db", help="Database path")] = Path("data/library.db"),
) -> None:
    """Add a note to the active session (requires OBJLIB_SESSION env var)."""
    from objlib.session.manager import SessionManager
    sid = SessionManager.get_active_session_id()
    if not sid:
        console.print("[red]No active session.[/red] Set OBJLIB_SESSION or use 'session start'.")
        raise typer.Exit(code=1)
    with Database(db_path) as db:
        mgr = SessionManager(db.conn)
        mgr.add_event(sid, "note", {"text": text})
    console.print("[green]Note added to session.[/green]")


@session_app.command("export")
def session_export(
    session_id: Annotated[str, typer.Argument(help="Session ID or prefix")],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output file path")] = None,
    db_path: Annotated[Path, typer.Option("--db", help="Database path")] = Path("data/library.db"),
) -> None:
    """Export a session as a Markdown file."""
    from objlib.session.manager import SessionManager
    with Database(db_path) as db:
        mgr = SessionManager(db.conn)
        session = mgr.find_by_prefix(session_id) or mgr.get_session(session_id)
        if not session:
            console.print(f"[red]Session not found:[/red] {session_id}")
            raise typer.Exit(code=1)
        out_path = mgr.export_markdown(session["id"], output)
    console.print(f"[green]Exported to:[/green] [bold]{out_path}[/bold]")


# ---- Glossary Commands ----


@glossary_app.command("list")
def glossary_list() -> None:
    """List all terms in the query expansion glossary."""
    from objlib.search.expansion import load_glossary
    glossary = load_glossary()
    table = Table(title="Query Expansion Glossary", border_style="blue")
    table.add_column("Term", style="bold")
    table.add_column("Synonyms")
    for term, synonyms in sorted(glossary.items()):
        table.add_row(term, ", ".join(synonyms))
    console.print(table)


@glossary_app.command("add")
def glossary_add(
    term: Annotated[str, typer.Argument(help="Term to add")],
    synonyms: Annotated[list[str], typer.Argument(help="Synonyms for the term")],
) -> None:
    """Add a term and its synonyms to the glossary."""
    from objlib.search.expansion import add_term
    add_term(term, synonyms)
    console.print(f"[green]Added:[/green] [bold]{term}[/bold] -> {', '.join(synonyms)}")


@glossary_app.command("suggest")
def glossary_suggest(
    term: Annotated[str, typer.Argument(help="Term to get synonym suggestions for")],
) -> None:
    """Use Gemini Flash to suggest synonyms for a term (requires API key)."""
    from google import genai
    from google.genai import types
    from objlib.config import get_api_key
    try:
        api_key = get_api_key()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    client = genai.Client(api_key=api_key)
    prompt = (
        f"In Objectivist philosophy, what are 3-5 synonyms or closely related terms for '{term}'? "
        "List only the terms, one per line, without explanation."
    )
    try:
        resp = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        suggestions = [line.strip().strip("-").strip() for line in (resp.text or "").split("\n") if line.strip()]
        console.print(Panel(
            "\n".join(f"  {s}" for s in suggestions if s),
            title=f"Suggestions for: {term}",
            border_style="blue",
        ))
        if suggestions:
            console.print(
                f"\n[dim]To add:[/dim] objlib glossary add \"{term}\" "
                + " ".join(f'"{s}"' for s in suggestions[:2])
            )
    except Exception as e:
        console.print(f"[red]Suggestion failed:[/red] {e}")
        raise typer.Exit(code=1)


@app.command()
def tui() -> None:
    """Launch the interactive TUI for library exploration."""
    from objlib.tui import run_tui

    run_tui()


@app.command(name="logs")
def logs_cmd(
    trace: Annotated[
        str | None,
        typer.Option("--trace", "-t", help="Filter to a specific trace ID (prefix match)"),
    ] = None,
    level: Annotated[
        str | None,
        typer.Option(
            "--level",
            "-l",
            help="Minimum log level to show (DEBUG, INFO, WARNING, ERROR)",
        ),
    ] = None,
    since: Annotated[
        str | None,
        typer.Option("--since", "-s", help="Show logs from this date onward (YYYY-MM-DD)"),
    ] = None,
    tail: Annotated[
        int,
        typer.Option("--tail", "-n", help="Show only the last N entries (0 = all)"),
    ] = 0,
) -> None:
    """Browse TUI session logs from the logs/ directory.

    Reads all JSON-lines log files matching ``logs/tui-*.log`` and renders
    them as a Rich table. Supports filtering by trace ID, log level, and date.

    Examples:

    \\b
      objlib logs                          # all log entries
      objlib logs --level ERROR            # errors only
      objlib logs --trace abcd1234         # one trace
      objlib logs --since 2026-02-18       # today's entries
      objlib logs --tail 50                # last 50 entries
    """
    import json as _json
    from pathlib import Path

    _LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}

    min_level_int = 0
    if level:
        level_upper = level.upper()
        if level_upper not in _LEVEL_ORDER:
            console.print(
                f"[red]Unknown level '{level}'. Choose from: DEBUG, INFO, WARNING, ERROR[/red]"
            )
            raise typer.Exit(1)
        min_level_int = _LEVEL_ORDER[level_upper]

    log_files = sorted(Path("logs").glob("tui-*.log")) if Path("logs").exists() else []
    if not log_files:
        console.print("[dim]No TUI log files found in logs/[/dim]")
        return

    # Parse all matching lines
    rows: list[dict] = []
    parse_errors = 0
    for log_file in log_files:
        with log_file.open(encoding="utf-8") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = _json.loads(raw_line)
                except _json.JSONDecodeError:
                    parse_errors += 1
                    continue

                # --since filter (compare ISO date prefix)
                if since and entry.get("ts", "") < since:
                    continue

                # --level filter
                entry_level = entry.get("level", "INFO")
                if _LEVEL_ORDER.get(entry_level, 0) < min_level_int:
                    continue

                # --trace filter (prefix match)
                if trace and not entry.get("trace", "").startswith(trace):
                    continue

                rows.append(entry)

    if not rows:
        console.print("[dim]No log entries matched the given filters.[/dim]")
        return

    # --tail
    if tail > 0:
        rows = rows[-tail:]

    # Render table
    table = Table(
        show_header=True,
        header_style="bold",
        expand=True,
        show_lines=False,
    )
    table.add_column("Timestamp", style="dim", no_wrap=True, min_width=19)
    table.add_column("Level", no_wrap=True, min_width=7)
    table.add_column("Trace", style="dim", no_wrap=True, min_width=8)
    table.add_column("Message", overflow="fold")

    _LEVEL_STYLES = {
        "DEBUG": "dim",
        "INFO": "green",
        "WARNING": "yellow",
        "ERROR": "bold red",
        "CRITICAL": "bold red on white",
    }

    for entry in rows:
        lvl = entry.get("level", "")
        trace_short = entry.get("trace", "")[:8]
        # Dim the zero-trace prefix so real traces stand out
        if trace_short == "00000000":
            trace_short = "[dim]--------[/dim]"
        table.add_row(
            entry.get("ts", ""),
            f"[{_LEVEL_STYLES.get(lvl, '')}]{lvl}[/{_LEVEL_STYLES.get(lvl, '')}]",
            trace_short,
            entry.get("msg", ""),
        )

    console.print(table)
    console.print(
        f"[dim]{len(rows)} entries from {len(log_files)} file(s)"
        + (f" — {parse_errors} parse error(s) skipped" if parse_errors else "")
        + "[/dim]"
    )
