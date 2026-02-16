#!/usr/bin/env python3
"""Verify metadata quality across all extracted files."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from objlib.database import Database
from objlib.extraction.schemas import CONTROLLED_VOCABULARY
import json
from rich.console import Console
from rich.table import Table
from rich.panel import Panel


def verify_metadata():
    """Run comprehensive metadata verification."""
    console = Console()
    db = Database('data/library.db')

    console.print("\n[bold cyan]Metadata Quality Verification[/bold cyan]\n")

    # 1. Coverage Check
    console.print("[bold]1. Coverage Analysis[/bold]")
    total_txt = db.conn.execute(
        "SELECT COUNT(*) FROM files WHERE filename LIKE '%.txt'"
    ).fetchone()[0]

    extracted = db.conn.execute(
        "SELECT COUNT(*) FROM files WHERE ai_metadata_status IN ('extracted', 'approved', 'needs_review')"
    ).fetchone()[0]

    pending = db.conn.execute(
        "SELECT COUNT(*) FROM files WHERE ai_metadata_status IS NULL OR ai_metadata_status = 'pending'"
    ).fetchone()[0]

    failed = db.conn.execute(
        "SELECT COUNT(*) FROM files WHERE ai_metadata_status LIKE 'failed%'"
    ).fetchone()[0]

    coverage_pct = (extracted / total_txt * 100) if total_txt > 0 else 0

    table = Table(title="Coverage")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="bold")
    table.add_column("%", style="green")

    table.add_row("Total .txt files", f"{total_txt:,}", "100%")
    table.add_row("✓ Extracted", f"{extracted:,}", f"{coverage_pct:.1f}%")
    table.add_row("⏳ Pending", f"{pending:,}", f"{pending/total_txt*100:.1f}%")
    table.add_row("✗ Failed", f"{failed:,}", f"{failed/total_txt*100:.1f}%")

    console.print(table)
    print()

    # 2. Tier Completeness
    console.print("[bold]2. Tier Completeness Check[/bold]")

    # Sample 100 random extracted files
    samples = db.conn.execute('''
        SELECT m.metadata_json, f.ai_confidence_score
        FROM file_metadata_ai m
        JOIN files f ON m.file_path = f.file_path
        WHERE m.is_current = 1
        ORDER BY RANDOM()
        LIMIT 100
    ''').fetchall()

    if not samples:
        console.print("[yellow]No extracted metadata found yet[/yellow]\n")
        db.close()
        return

    tier_issues = {
        'missing_category': 0,
        'missing_difficulty': 0,
        'insufficient_topics': 0,  # < 3 topics
        'insufficient_aspects': 0,  # < 3 aspects
        'short_summary': 0,  # < 50 chars
        'no_arguments': 0,
    }

    for metadata_json, confidence in samples:
        metadata = json.loads(metadata_json)

        # Check each tier
        if not metadata.get('category'):
            tier_issues['missing_category'] += 1
        if not metadata.get('difficulty'):
            tier_issues['missing_difficulty'] += 1

        topics = metadata.get('primary_topics', [])
        if len(topics) < 3:
            tier_issues['insufficient_topics'] += 1

        aspects = metadata.get('topic_aspects', [])
        if len(aspects) < 3:
            tier_issues['insufficient_aspects'] += 1

        desc = metadata.get('semantic_description', {})
        summary = desc.get('summary', '')
        if len(summary) < 50:
            tier_issues['short_summary'] += 1

        args = desc.get('key_arguments', [])
        if len(args) == 0:
            tier_issues['no_arguments'] += 1

    issue_table = Table(title=f"Quality Issues (sample of {len(samples)} files)")
    issue_table.add_column("Issue", style="yellow")
    issue_table.add_column("Count", style="bold")
    issue_table.add_column("%", style="red")

    for issue, count in tier_issues.items():
        pct = count / len(samples) * 100
        color = "green" if pct < 5 else "yellow" if pct < 10 else "red"
        issue_table.add_row(
            issue.replace('_', ' ').title(),
            str(count),
            f"[{color}]{pct:.1f}%[/{color}]"
        )

    console.print(issue_table)
    print()

    # 3. Confidence Distribution
    console.print("[bold]3. Confidence Score Distribution[/bold]")

    conf_ranges = db.conn.execute('''
        SELECT
            CASE
                WHEN ai_confidence_score >= 0.90 THEN '90-100%'
                WHEN ai_confidence_score >= 0.80 THEN '80-89%'
                WHEN ai_confidence_score >= 0.70 THEN '70-79%'
                WHEN ai_confidence_score >= 0.60 THEN '60-69%'
                ELSE '<60%'
            END as range,
            COUNT(*) as count
        FROM files
        WHERE ai_confidence_score IS NOT NULL
        GROUP BY range
        ORDER BY range DESC
    ''').fetchall()

    conf_table = Table(title="Confidence Ranges")
    conf_table.add_column("Range", style="cyan")
    conf_table.add_column("Count", style="bold")

    for range_name, count in conf_ranges:
        color = "green" if range_name in ('90-100%', '80-89%') else "yellow" if range_name == '70-79%' else "red"
        conf_table.add_row(range_name, f"[{color}]{count:,}[/{color}]")

    console.print(conf_table)
    print()

    # 4. Vocabulary Compliance
    console.print("[bold]4. Controlled Vocabulary Compliance[/bold]")

    # Check if all primary_topics are in CONTROLLED_VOCABULARY
    invalid_topics = []
    for metadata_json, _ in samples[:50]:  # Check 50 samples
        metadata = json.loads(metadata_json)
        topics = metadata.get('primary_topics', [])
        for topic in topics:
            if topic not in CONTROLLED_VOCABULARY and topic not in invalid_topics:
                invalid_topics.append(topic)

    if invalid_topics:
        console.print(f"[yellow]⚠ Found {len(invalid_topics)} invalid topics:[/yellow]")
        for topic in invalid_topics[:10]:
            console.print(f"  • {topic}")
        if len(invalid_topics) > 10:
            console.print(f"  ... and {len(invalid_topics) - 10} more")
    else:
        console.print("[green]✓ All primary_topics comply with controlled vocabulary[/green]")

    print()

    # 5. Overall Assessment
    console.print("[bold]5. Overall Assessment[/bold]")

    avg_confidence = db.conn.execute(
        'SELECT AVG(ai_confidence_score) FROM files WHERE ai_confidence_score IS NOT NULL'
    ).fetchone()[0] or 0

    quality_score = 100
    if coverage_pct < 95:
        quality_score -= 10
    if avg_confidence < 0.80:
        quality_score -= 15
    if tier_issues['insufficient_topics'] > len(samples) * 0.1:
        quality_score -= 10
    if tier_issues['short_summary'] > len(samples) * 0.1:
        quality_score -= 10

    status = "Excellent" if quality_score >= 90 else "Good" if quality_score >= 75 else "Needs Review"
    color = "green" if quality_score >= 90 else "yellow" if quality_score >= 75 else "red"

    console.print(Panel.fit(
        f"[bold]Coverage:[/bold] {coverage_pct:.1f}%\n"
        f"[bold]Avg Confidence:[/bold] {avg_confidence:.1%}\n"
        f"[bold]Quality Score:[/bold] [{color}]{quality_score}/100[/{color}]\n"
        f"[bold]Status:[/bold] [{color}]{status}[/{color}]",
        title="📊 Summary",
        border_style=color
    ))

    db.close()


if __name__ == '__main__':
    verify_metadata()
