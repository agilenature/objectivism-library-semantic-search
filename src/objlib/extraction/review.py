"""Rich 4-tier metadata display and interactive review workflow.

Provides display functions for AI-extracted metadata using Rich panels
and tables, plus an interactive review loop for Accept/Edit/Rerun/Skip/Quit
actions on extraction results.

Tier 1: Category + Difficulty (header)
Tier 2: Primary Topics (tag list)
Tier 3: Topic Aspects (bullet points)
Tier 4: Semantic Description (summary, key arguments, positions)
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from objlib.database import Database


def _confidence_style(confidence: float) -> str:
    """Return Rich color style based on confidence threshold.

    Args:
        confidence: Confidence value 0.0-1.0.

    Returns:
        Rich style string: green (>=0.85), yellow (0.70-0.84), red (<0.70).
    """
    if confidence >= 0.85:
        return "green"
    elif confidence >= 0.70:
        return "yellow"
    else:
        return "red"


def _difficulty_style(difficulty: str) -> str:
    """Return Rich color style based on difficulty level.

    Args:
        difficulty: Difficulty string (intro, intermediate, advanced).

    Returns:
        Rich style string.
    """
    styles = {
        "intro": "green",
        "intermediate": "yellow",
        "advanced": "red",
    }
    return styles.get(difficulty, "dim")


def display_metadata_panel(
    file_path: str,
    metadata: dict,
    confidence: float,
    status: str,
    console: Console,
) -> None:
    """Display a Rich 4-tier metadata panel for a single file.

    Layout:
    - Header: category, difficulty, confidence %, status
    - Tier 2: Primary topics as space-separated tags
    - Tier 3: Topic aspects as bullet points
    - Tier 4: Semantic description (summary, key arguments, positions)

    Args:
        file_path: Path to the file (used for panel title).
        metadata: Parsed metadata dict from file_metadata_ai.
        confidence: Confidence score 0.0-1.0.
        status: AI metadata status string.
        console: Rich Console instance for output.
    """
    filename = Path(file_path).name

    # Build header line
    category = metadata.get("category", "unknown")
    difficulty = metadata.get("difficulty", "unknown")
    conf_pct = int(confidence * 100)
    conf_style = _confidence_style(confidence)
    diff_style = _difficulty_style(difficulty)

    lines: list[str] = []

    # Header: Category + Difficulty + Confidence + Status
    lines.append(
        f"Category: [bold cyan]{category}[/bold cyan] | "
        f"Difficulty: [{diff_style}]{difficulty}[/{diff_style}] | "
        f"Confidence: [{conf_style}]{conf_pct}%[/{conf_style}] | "
        f"Status: {status}"
    )

    # Tier 2: Primary Topics
    topics = metadata.get("primary_topics", [])
    if topics:
        topic_tags = "  ".join(f"[green]{t}[/green]" for t in topics)
        lines.append("")
        lines.append(f"[bold]Primary Topics (Tier 2):[/bold]  {topic_tags}")

    # Tier 3: Topic Aspects
    aspects = metadata.get("topic_aspects", [])
    if aspects:
        lines.append("")
        lines.append("[bold]Topic Aspects (Tier 3):[/bold]")
        for aspect in aspects:
            lines.append(f"  * {aspect}")

    # Tier 4: Semantic Description
    sem_desc = metadata.get("semantic_description", {})
    if sem_desc:
        lines.append("")
        lines.append("[bold]Semantic Description (Tier 4):[/bold]")

        summary = sem_desc.get("summary", "")
        if summary:
            lines.append(f"  Summary: {summary}")

        key_args = sem_desc.get("key_arguments", [])
        if key_args:
            lines.append("  Key Arguments:")
            for i, arg in enumerate(key_args, 1):
                lines.append(f"    {i}. {arg}")

        positions = sem_desc.get("philosophical_positions", [])
        if positions:
            lines.append("  Positions:")
            for pos in positions:
                lines.append(f"    * {pos}")

    panel_content = "\n".join(lines)
    console.print(Panel(
        panel_content,
        title=f"File: {filename}",
        border_style="cyan",
        padding=(1, 2),
    ))


def display_review_table(
    files: list[dict],
    console: Console,
) -> None:
    """Display a Rich table summarizing multiple file extractions.

    Columns: File, Category, Difficulty, Topics (first 3), Confidence %, Status.
    Confidence is color-coded: green (>=85%), yellow (70-84%), red (<70%).
    Filenames truncated to 40 chars.

    Args:
        files: List of dicts with file_path/filename, metadata, confidence, status.
        console: Rich Console instance for output.
    """
    table = Table(title="AI Metadata Extractions", show_header=True)
    table.add_column("File", style="cyan", max_width=40, no_wrap=True)
    table.add_column("Category", style="bold")
    table.add_column("Difficulty")
    table.add_column("Topics (first 3)", max_width=40)
    table.add_column("Confidence", justify="right")
    table.add_column("Status")

    for f in files:
        filename = f.get("filename", Path(f.get("file_path", "")).name)
        if len(filename) > 40:
            filename = filename[:37] + "..."

        metadata = f.get("metadata", {})
        category = metadata.get("category", "")
        difficulty = metadata.get("difficulty", "")
        topics = metadata.get("primary_topics", [])
        topics_str = ", ".join(topics[:3])
        if len(topics) > 3:
            topics_str += f" (+{len(topics) - 3})"

        confidence = f.get("ai_confidence_score", 0.0) or 0.0
        conf_pct = int(confidence * 100)
        conf_style = _confidence_style(confidence)
        status = f.get("ai_metadata_status", "")

        diff_style = _difficulty_style(difficulty)

        table.add_row(
            filename,
            category,
            f"[{diff_style}]{difficulty}[/{diff_style}]",
            topics_str,
            f"[{conf_style}]{conf_pct}%[/{conf_style}]",
            status,
        )

    console.print(table)


def interactive_review(
    db: Database,
    console: Console,
    status_filter: str | None = None,
) -> dict:
    """Run interactive review loop for AI-extracted metadata.

    For each file matching the filter:
    1. Display metadata panel
    2. Prompt: [A]ccept  [E]dit JSON  [R]erun  [S]kip  [Q]uit
    3. Process action and update database

    Args:
        db: Database instance.
        console: Rich Console instance.
        status_filter: Optional ai_metadata_status to filter by.
            If None, shows all non-approved files.

    Returns:
        Summary dict: {approved: int, edited: int, rerun: int, skipped: int}
    """
    summary = {"approved": 0, "edited": 0, "rerun": 0, "skipped": 0}

    if status_filter:
        files = db.get_files_by_ai_status(status_filter, limit=500)
    else:
        # Show all non-approved files
        files = db.get_files_by_ai_status("extracted", limit=500)
        files.extend(db.get_files_by_ai_status("needs_review", limit=500))

    if not files:
        console.print("[yellow]No files to review.[/yellow]")
        return summary

    console.print(f"\n[bold]Reviewing {len(files)} file(s)[/bold]\n")

    for i, f in enumerate(files):
        file_path = f["file_path"]
        metadata = f.get("metadata", {})
        confidence = f.get("ai_confidence_score", 0.0) or 0.0
        status = f.get("ai_metadata_status", "")

        console.print(f"\n[dim]--- File {i + 1}/{len(files)} ---[/dim]")
        display_metadata_panel(file_path, metadata, confidence, status, console)

        # Prompt for action
        while True:
            console.print(
                "\n[bold][A][/bold]ccept  "
                "[bold][E][/bold]dit JSON  "
                "[bold][R][/bold]erun  "
                "[bold][S][/bold]kip  "
                "[bold][Q][/bold]uit"
            )
            action = input("> ").strip().lower()

            if action in ("a", "accept"):
                db.set_ai_metadata_status(file_path, "approved")
                summary["approved"] += 1
                console.print("[green]Approved.[/green]")
                break

            elif action in ("e", "edit"):
                # Open metadata in editor
                edited = _edit_metadata_json(metadata, console)
                if edited is not None:
                    # Save edited metadata back
                    _save_edited_metadata(db, file_path, edited)
                    summary["edited"] += 1
                    console.print("[green]Metadata updated.[/green]")
                else:
                    console.print("[yellow]Edit cancelled (no changes).[/yellow]")
                break

            elif action in ("r", "rerun"):
                db.set_ai_metadata_status(file_path, "retry_scheduled")
                summary["rerun"] += 1
                console.print("[yellow]Marked for re-extraction.[/yellow]")
                break

            elif action in ("s", "skip"):
                summary["skipped"] += 1
                break

            elif action in ("q", "quit"):
                console.print("\n[bold]Review session ended.[/bold]")
                _print_review_summary(summary, console)
                return summary

            else:
                console.print("[red]Invalid action. Use A/E/R/S/Q.[/red]")

    console.print("\n[bold]Review complete.[/bold]")
    _print_review_summary(summary, console)
    return summary


def _edit_metadata_json(metadata: dict, console: Console) -> dict | None:
    """Open metadata JSON in an external editor.

    Creates a temporary file with pretty-printed JSON, opens the user's
    $EDITOR (or vi as fallback), reads back the edited content.

    Args:
        metadata: Current metadata dict.
        console: Rich Console for status messages.

    Returns:
        Edited metadata dict, or None if unchanged or edit failed.
    """
    import os

    editor = os.environ.get("EDITOR", "vi")
    original_json = json.dumps(metadata, indent=2)

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix="objlib_metadata_",
        delete=False,
    ) as tmp:
        tmp.write(original_json)
        tmp_path = tmp.name

    try:
        console.print(f"[dim]Opening {editor}...[/dim]")
        result = subprocess.run([editor, tmp_path])
        if result.returncode != 0:
            console.print(f"[red]Editor exited with code {result.returncode}[/red]")
            return None

        edited_json = Path(tmp_path).read_text()
        if edited_json == original_json:
            return None

        edited = json.loads(edited_json)
        return edited

    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON after editing: {e}[/red]")
        return None
    except Exception as e:
        console.print(f"[red]Edit error: {e}[/red]")
        return None
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _save_edited_metadata(db: Database, file_path: str, metadata: dict) -> None:
    """Save edited metadata back to the database.

    Updates file_metadata_ai (marks old as not current, inserts new)
    and sets ai_metadata_status to 'approved'.

    Args:
        db: Database instance.
        file_path: File path to update.
        metadata: Edited metadata dict.
    """
    metadata_json = json.dumps(metadata)

    with db.conn:
        # Mark old versions as not current
        db.conn.execute(
            "UPDATE file_metadata_ai SET is_current = 0 "
            "WHERE file_path = ? AND is_current = 1",
            (file_path,),
        )

        # Insert edited version
        db.conn.execute(
            """INSERT INTO file_metadata_ai
               (file_path, metadata_json, model, prompt_version,
                extraction_config_hash, is_current)
               VALUES (?, ?, 'human_edited', 'manual', 'manual', 1)""",
            (file_path, metadata_json),
        )

        # Update status to approved
        db.conn.execute(
            "UPDATE files SET ai_metadata_status = 'approved' WHERE file_path = ?",
            (file_path,),
        )


def _print_review_summary(summary: dict, console: Console) -> None:
    """Print a summary of the review session.

    Args:
        summary: Dict with approved, edited, rerun, skipped counts.
        console: Rich Console instance.
    """
    table = Table(title="Review Summary")
    table.add_column("Action", style="bold")
    table.add_column("Count", justify="right")

    table.add_row("Approved", f"[green]{summary['approved']}[/green]")
    table.add_row("Edited", f"[cyan]{summary['edited']}[/cyan]")
    table.add_row("Rerun", f"[yellow]{summary['rerun']}[/yellow]")
    table.add_row("Skipped", f"[dim]{summary['skipped']}[/dim]")

    console.print(table)
