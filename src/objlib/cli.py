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

    # Three-tier Rich display
    from objlib.search.formatter import display_search_results

    response_text = response.text or "(No response text)"
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

    # --full: read and display the actual file content
    if full:
        source_path = Path(file_path)
        if source_path.exists():
            try:
                content = source_path.read_text(encoding="utf-8")
                display_full_document(filename, content, terminal_width)
            except Exception as e:
                console.print(f"[red]Error reading file:[/red] {e}")
        else:
            console.print(
                f"[yellow]Warning:[/yellow] Source file not found on disk: {file_path}\n"
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
            enrich_citations(related_citations, db)

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
