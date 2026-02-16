#!/usr/bin/env python3
"""Extract metadata for ALL .txt files in the library (not just unknown category)."""

import asyncio
import sys
import logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from objlib.database import Database
from objlib.extraction.client import MistralClient
from objlib.extraction.orchestrator import ExtractionOrchestrator, ExtractionConfig
from objlib.extraction.checkpoint import CheckpointManager
from objlib.config import get_mistral_api_key
import json
from rich.console import Console
from rich.panel import Panel

# Configure logging to show INFO level messages
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)


async def extract_all():
    """Run extraction on all .txt files."""
    console = Console()

    # Setup
    api_key = get_mistral_api_key()
    client = MistralClient(api_key)
    db = Database('data/library.db')
    checkpoint = CheckpointManager()
    config = ExtractionConfig()

    # Get ALL .txt files that haven't been processed yet
    # (Check if ai_metadata_status is NULL or 'pending')
    files = db.conn.execute('''
        SELECT file_path, filename, file_size
        FROM files
        WHERE filename LIKE '%.txt'
        AND (ai_metadata_status IS NULL OR ai_metadata_status = 'pending')
        ORDER BY file_size ASC
    ''').fetchall()

    file_dicts = [
        {'file_path': f[0], 'filename': f[1], 'file_size': f[2]}
        for f in files
    ]

    total_files = len(file_dicts)

    # Also count files by category status
    unknown_count = db.conn.execute('''
        SELECT COUNT(*) FROM files
        WHERE filename LIKE '%.txt'
        AND json_extract(metadata_json, '$.category') = 'unknown'
        AND (ai_metadata_status IS NULL OR ai_metadata_status = 'pending')
    ''').fetchone()[0]

    known_count = total_files - unknown_count

    console.print(Panel.fit(
        f"[bold cyan]Full Library Extraction[/bold cyan]\n\n"
        f"Total files to process: [bold]{total_files:,}[/bold]\n"
        f"  • Files needing categories: [yellow]{unknown_count:,}[/yellow]\n"
        f"  • Files with categories (need tiers 2-4): [green]{known_count:,}[/green]\n\n"
        f"Strategy: [bold]minimalist[/bold]\n"
        f"Estimated cost: [bold]${total_files * 0.0647:.2f}[/bold]\n"
        f"Estimated time: [bold]{total_files * 12 / 60:.0f} minutes[/bold]",
        title="📚 Extraction Plan"
    ))

    # Confirm (unless --yes flag)
    if '--yes' not in sys.argv:
        response = input("\n▶ Proceed with full extraction? [y/N]: ")
        if response.lower() != 'y':
            console.print("[yellow]Extraction cancelled[/yellow]")
            db.close()
            return
    else:
        console.print("\n[bold green]--yes flag detected, proceeding automatically[/bold green]")

    console.print("\n[bold green]Starting extraction...[/bold green]\n")

    # Load strategy
    with open('data/wave1_selection.json') as f:
        selection = json.load(f)
        strategy = selection['strategy']

    # Run extraction
    orchestrator = ExtractionOrchestrator(client, db, checkpoint, config)
    result = await orchestrator.run_production(file_dicts, strategy)

    # Display results
    console.print("\n" + "="*80)
    console.print("[bold green]✓ Extraction Complete[/bold green]")
    console.print("="*80)
    console.print(f"Extracted: [green]{result.get('extracted', 0):,}[/green]")
    console.print(f"Needs Review: [yellow]{result.get('needs_review', 0):,}[/yellow]")
    console.print(f"Failed: [red]{result.get('failed', 0):,}[/red]")
    console.print(f"Total Tokens: [cyan]{result.get('total_tokens', 0):,}[/cyan]")
    console.print(f"Estimated Cost: [cyan]${result.get('estimated_cost', 0):.2f}[/cyan]")
    console.print(f"Avg Latency: [cyan]{result.get('avg_latency_ms', 0):.0f}ms[/cyan]")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. python verify_metadata.py  -- Run verification")
    console.print("  2. python -m objlib metadata stats  -- Check stats")
    console.print("  3. python -m objlib metadata approve --min-confidence 0.85  -- Auto-approve")

    db.close()


if __name__ == '__main__':
    asyncio.run(extract_all())
