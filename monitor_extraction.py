#!/usr/bin/env python3
"""Live monitoring dashboard for extraction progress."""

import sys
import time
import subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from objlib.database import Database
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.console import Console
from datetime import datetime, timedelta


def get_extraction_stats():
    """Get current extraction statistics."""
    db = Database('data/library.db')

    # Overall counts
    total_txt = db.conn.execute(
        "SELECT COUNT(*) FROM files WHERE filename LIKE '%.txt'"
    ).fetchone()[0]

    extracted = db.conn.execute(
        "SELECT COUNT(*) FROM files WHERE ai_metadata_status IN ('extracted', 'approved')"
    ).fetchone()[0]

    needs_review = db.conn.execute(
        "SELECT COUNT(*) FROM files WHERE ai_metadata_status = 'needs_review'"
    ).fetchone()[0]

    failed = db.conn.execute(
        "SELECT COUNT(*) FROM files WHERE ai_metadata_status LIKE 'failed%'"
    ).fetchone()[0]

    pending = total_txt - extracted - needs_review - failed

    # Average confidence
    avg_conf = db.conn.execute(
        "SELECT AVG(ai_confidence_score) FROM files WHERE ai_confidence_score IS NOT NULL"
    ).fetchone()[0] or 0

    # Recent activity (last 10 extractions)
    recent = db.conn.execute("""
        SELECT file_path, ai_confidence_score, ai_metadata_status
        FROM files
        WHERE ai_metadata_status IN ('extracted', 'approved', 'needs_review')
        ORDER BY rowid DESC
        LIMIT 10
    """).fetchall()

    db.close()

    return {
        'total': total_txt,
        'extracted': extracted,
        'needs_review': needs_review,
        'failed': failed,
        'pending': pending,
        'avg_confidence': avg_conf,
        'recent': recent,
        'progress_pct': (extracted + needs_review) / total_txt * 100 if total_txt > 0 else 0
    }


def get_log_tail(lines=15):
    """Get last N lines from extraction log."""
    try:
        result = subprocess.run(
            ['tail', '-n', str(lines), 'extraction_log.txt'],
            capture_output=True,
            text=True,
            timeout=1
        )
        return result.stdout if result.returncode == 0 else "Log file not found"
    except:
        return "Unable to read log"


def check_process():
    """Check if extraction process is running."""
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'extract_all_files.py'],
            capture_output=True,
            text=True
        )
        pids = result.stdout.strip().split('\n') if result.stdout.strip() else []
        return len(pids) > 0, pids
    except:
        return False, []


def create_dashboard(stats, log_lines, is_running, pids, start_time):
    """Create the monitoring dashboard layout."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="log", size=18)
    )

    # Header
    elapsed = datetime.now() - start_time
    status = "[green]RUNNING[/green]" if is_running else "[red]STOPPED[/red]"
    pid_str = f"PID: {','.join(pids)}" if pids else "No process"

    layout["header"].update(Panel(
        f"[bold cyan]Extraction Monitor[/bold cyan]  |  Status: {status}  |  {pid_str}  |  Elapsed: {str(elapsed).split('.')[0]}",
        style="bold"
    ))

    # Main stats
    layout["main"].split_row(
        Layout(name="stats"),
        Layout(name="recent")
    )

    # Stats table
    stats_table = Table(title="📊 Progress", show_header=True)
    stats_table.add_column("Metric", style="cyan", width=20)
    stats_table.add_column("Count", style="bold", width=12)
    stats_table.add_column("Progress", width=30)

    # Progress bar
    completed = stats['extracted'] + stats['needs_review']
    total = stats['total']
    pct = stats['progress_pct']
    bar_width = 20
    filled = int(bar_width * pct / 100)
    bar = "█" * filled + "░" * (bar_width - filled)

    stats_table.add_row("Total Files", f"{total:,}", "")
    stats_table.add_row("✓ Extracted", f"{stats['extracted']:,}", f"[green]{bar}[/green] {pct:.1f}%")
    stats_table.add_row("⚠ Needs Review", f"{stats['needs_review']:,}", "")
    stats_table.add_row("✗ Failed", f"{stats['failed']:,}", "")
    stats_table.add_row("⏳ Pending", f"{stats['pending']:,}", "")
    stats_table.add_row("", "", "")
    stats_table.add_row("Avg Confidence", f"{stats['avg_confidence']:.1%}", "")

    # Estimate time remaining
    if completed > 10 and stats['pending'] > 0:
        time_per_file = elapsed.total_seconds() / completed
        remaining_secs = time_per_file * stats['pending']
        eta = str(timedelta(seconds=int(remaining_secs)))
        stats_table.add_row("ETA", eta, "")

    layout["stats"].update(Panel(stats_table, border_style="cyan"))

    # Recent files
    recent_table = Table(title="🕐 Recent Extractions", show_header=False)
    recent_table.add_column("File", style="dim", max_width=35)
    recent_table.add_column("Conf", style="bold", width=6)

    for file_path, conf, status in stats['recent'][:8]:
        filename = Path(file_path).name[:32] + "..." if len(Path(file_path).name) > 35 else Path(file_path).name
        conf_color = "green" if conf >= 0.85 else "yellow" if conf >= 0.70 else "red"
        recent_table.add_row(filename, f"[{conf_color}]{conf:.0%}[/{conf_color}]")

    layout["recent"].update(Panel(recent_table, border_style="blue"))

    # Log tail
    log_panel = Panel(
        log_lines,
        title="📄 Extraction Log (live)",
        border_style="yellow",
        height=16
    )
    layout["log"].update(log_panel)

    return layout


def main():
    """Run the monitoring dashboard."""
    console = Console()
    start_time = datetime.now()

    console.print("[bold cyan]Starting extraction monitor...[/bold cyan]")
    console.print("Press Ctrl+C to exit\n")

    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                # Gather data
                stats = get_extraction_stats()
                log_lines = get_log_tail(13)
                is_running, pids = check_process()

                # Update dashboard
                dashboard = create_dashboard(stats, log_lines, is_running, pids, start_time)
                live.update(dashboard)

                # Exit if process is done and we have all files
                if not is_running and stats['pending'] == 0:
                    console.print("\n[bold green]✓ Extraction complete![/bold green]")
                    console.print("\nRun verification: [bold]python verify_metadata.py[/bold]")
                    break

                time.sleep(2)

    except KeyboardInterrupt:
        console.print("\n[yellow]Monitoring stopped[/yellow]")
        console.print("Extraction continues in background (PID: {})".format(','.join(pids) if pids else "unknown"))


if __name__ == '__main__':
    main()
