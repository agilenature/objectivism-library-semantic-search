"""CLI entry point for the Objectivism Library tools.

Provides commands:
  - scan: Discover files, extract metadata, persist to SQLite
  - status: Display database statistics (counts by status and quality)
  - purge: Remove old LOCAL_DELETE records from the database
  - upload: Upload pending files to Gemini File Search store
  - search: Semantic search across the library via Gemini File Search
  - config: Manage configuration (API keys, settings)
"""

from __future__ import annotations

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

app = typer.Typer(
    help="Objectivism Library - Search, browse, and explore your philosophical library",
    rich_markup_mode="rich",
)
console = Console()

# Commands that do NOT need Gemini client initialization
_SKIP_INIT_COMMANDS = {None, "scan", "status", "purge", "upload", "config"}


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
    """Initialize shared state for search/browse/filter commands."""
    if ctx.invoked_subcommand in _SKIP_INIT_COMMANDS:
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


@app.command()
def scan(
    library_path: Annotated[
        Path | None,
        typer.Option(
            "--library",
            "-l",
            help="Path to library root directory",
            exists=True,
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
) -> None:
    """Search the library by meaning with optional metadata filters."""
    from objlib.search.citations import (
        build_metadata_filter,
        enrich_citations,
        extract_citations,
    )
    from objlib.search.client import GeminiSearchClient

    state = get_state(ctx)

    # Build AIP-160 filter
    metadata_filter = build_metadata_filter(filter) if filter else None

    search_client = GeminiSearchClient(
        state.gemini_client, state.store_resource_name
    )

    console.print(f"[dim]Searching for:[/dim] [bold]{query}[/bold]")
    if metadata_filter:
        console.print(f"[dim]Filter:[/dim] {metadata_filter}")

    try:
        response = search_client.query_with_retry(
            query, metadata_filter=metadata_filter, model=model
        )
    except Exception as e:
        console.print(f"[red]Search failed after retries:[/red] {e}")
        raise typer.Exit(code=1)

    # Extract citations from grounding metadata
    grounding = None
    if response.candidates:
        grounding = response.candidates[0].grounding_metadata

    citations = extract_citations(grounding)

    # Enrich with SQLite metadata
    with Database(state.db_path) as db:
        enrich_citations(citations, db)

    # Basic display (Plan 02 adds rich formatting)
    response_text = response.text or "(No response text)"
    console.print()
    console.print(Panel(response_text, title="Results", border_style="cyan"))

    if not citations:
        console.print("[dim]No sources cited.[/dim]")
        return

    # Basic citation list (Plan 02 replaces with three-tier display)
    console.print()
    for cite in citations[:limit]:
        meta = cite.metadata or {}
        course = meta.get("course", "")
        year = meta.get("year", "")
        score_pct = int(cite.confidence * 100)
        console.print(
            f"[yellow][{cite.index}][/yellow] [bold]{cite.title}[/bold]  "
            f"[green]{score_pct}%[/green]"
            + (f"  | {course}" if course else "")
            + (f", {year}" if year else "")
        )
        if cite.text:
            excerpt = (
                cite.text[:150].rsplit(" ", 1)[0] + "..."
                if len(cite.text) > 150
                else cite.text
            )
            console.print(f"    [dim]{excerpt}[/dim]")


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
