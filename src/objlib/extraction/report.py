"""Wave 1 comparison report generator.

Reads wave1_results from the database, computes per-strategy metrics
(tokens, latency, confidence, validation pass rate), and displays
Rich terminal tables with color-coded best/worst per column.

Also supports single-file side-by-side comparison (3 panels) and
CSV export for offline analysis.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from objlib.extraction.schemas import ExtractedMetadata

if TYPE_CHECKING:
    from objlib.database import Database


def generate_wave1_report(db: "Database") -> dict:
    """Compute per-strategy metrics from wave1_results table.

    For each strategy, calculates: total_files, avg_tokens, avg_latency_ms,
    avg_confidence, validation_pass_rate, and failed_count.

    Args:
        db: Database instance to query.

    Returns:
        Dict mapping strategy name to metrics dict:
        {strategy_name: {total_files, avg_tokens, avg_latency_ms,
         avg_confidence, validation_pass_rate, failed_count}}
    """
    rows = db.conn.execute(
        """SELECT strategy, metadata_json, token_count, latency_ms,
                  confidence_score
           FROM wave1_results
           ORDER BY strategy"""
    ).fetchall()

    # Group by strategy
    by_strategy: dict[str, list[dict]] = {}
    for row in rows:
        strategy = row["strategy"]
        if strategy not in by_strategy:
            by_strategy[strategy] = []
        by_strategy[strategy].append({
            "metadata_json": row["metadata_json"],
            "token_count": row["token_count"] or 0,
            "latency_ms": row["latency_ms"] or 0,
            "confidence_score": row["confidence_score"] or 0.0,
        })

    report: dict[str, dict] = {}
    for strategy, entries in by_strategy.items():
        total = len(entries)
        total_tokens = sum(e["token_count"] for e in entries)
        total_latency = sum(e["latency_ms"] for e in entries)
        total_confidence = sum(e["confidence_score"] for e in entries)

        # Validation pass rate: parse metadata_json and validate against ExtractedMetadata
        valid_count = 0
        failed_count = 0
        for entry in entries:
            try:
                metadata_str = entry["metadata_json"]
                if not metadata_str or metadata_str in ("null", "{}"):
                    failed_count += 1
                    continue
                metadata_dict = json.loads(metadata_str)
                ExtractedMetadata.model_validate(metadata_dict)
                valid_count += 1
            except (json.JSONDecodeError, ValidationError, TypeError):
                failed_count += 1

        report[strategy] = {
            "total_files": total,
            "avg_tokens": round(total_tokens / total) if total else 0,
            "avg_latency_ms": round(total_latency / total) if total else 0,
            "avg_confidence": round(total_confidence / total, 3) if total else 0.0,
            "validation_pass_rate": round(valid_count / total, 3) if total else 0.0,
            "failed_count": failed_count,
        }

    return report


def display_wave1_report(report: dict, console: Console) -> None:
    """Display Rich table comparing strategy metrics with color coding.

    Best metric per column is highlighted green, worst is highlighted red.

    Args:
        report: Dict from generate_wave1_report().
        console: Rich Console for output.
    """
    if not report:
        console.print("[yellow]No Wave 1 results found in database.[/yellow]")
        return

    strategies = list(report.keys())

    # Determine best/worst per metric
    # For avg_tokens and avg_latency_ms: lower is better
    # For avg_confidence and validation_pass_rate: higher is better
    # For failed_count: lower is better
    metrics_higher_better = {"avg_confidence", "validation_pass_rate"}
    metrics_lower_better = {"avg_tokens", "avg_latency_ms", "failed_count"}

    def _best_worst(metric: str) -> tuple[str, str]:
        """Return (best_strategy, worst_strategy) for a metric."""
        vals = {s: report[s][metric] for s in strategies}
        if metric in metrics_higher_better:
            best = max(vals, key=vals.get)  # type: ignore[arg-type]
            worst = min(vals, key=vals.get)  # type: ignore[arg-type]
        else:
            best = min(vals, key=vals.get)  # type: ignore[arg-type]
            worst = max(vals, key=vals.get)  # type: ignore[arg-type]
        return best, worst

    def _style(strategy: str, metric: str) -> str:
        """Return Rich style for a strategy/metric combination."""
        best, worst = _best_worst(metric)
        if strategy == best:
            return "green bold"
        if strategy == worst:
            return "red"
        return ""

    def _fmt(value: object, metric: str, strategy: str) -> str:
        """Format a metric value with Rich style markup."""
        style = _style(strategy, metric)
        if metric == "validation_pass_rate":
            text = f"{value:.0%}" if isinstance(value, float) else str(value)
        elif metric == "avg_confidence":
            text = f"{value:.3f}" if isinstance(value, float) else str(value)
        elif metric in ("avg_tokens", "avg_latency_ms"):
            text = f"{value:,}"
        else:
            text = str(value)
        if style:
            return f"[{style}]{text}[/{style}]"
        return text

    table = Table(title="Wave 1 Strategy Comparison", show_header=True)
    table.add_column("Strategy", style="cyan bold")
    table.add_column("Files", justify="right")
    table.add_column("Avg Tokens", justify="right")
    table.add_column("Avg Latency (ms)", justify="right")
    table.add_column("Avg Confidence", justify="right")
    table.add_column("Validation %", justify="right")
    table.add_column("Failed", justify="right")

    for strategy in strategies:
        m = report[strategy]
        table.add_row(
            strategy,
            str(m["total_files"]),
            _fmt(m["avg_tokens"], "avg_tokens", strategy),
            _fmt(m["avg_latency_ms"], "avg_latency_ms", strategy),
            _fmt(m["avg_confidence"], "avg_confidence", strategy),
            _fmt(m["validation_pass_rate"], "validation_pass_rate", strategy),
            _fmt(m["failed_count"], "failed_count", strategy),
        )

    console.print(table)

    # Show recommendation
    best_strategy, best_score = _compute_best_strategy(report)
    console.print(
        f"\n[bold]Recommendation:[/bold] [green bold]{best_strategy}[/green bold] "
        f"(composite score: {best_score:.4f})"
    )


def display_file_comparison(
    db: "Database", file_path: str, console: Console
) -> None:
    """Display side-by-side 3-strategy comparison for a single file.

    Shows category, difficulty, primary_topics, topic_aspects (first 3),
    and confidence for each strategy in Rich Panels.

    Args:
        db: Database instance to query.
        file_path: File path to compare across strategies.
        console: Rich Console for output.
    """
    rows = db.conn.execute(
        """SELECT strategy, metadata_json, confidence_score, token_count, latency_ms
           FROM wave1_results
           WHERE file_path = ?
           ORDER BY strategy""",
        (file_path,),
    ).fetchall()

    if not rows:
        # Try matching by filename
        rows = db.conn.execute(
            """SELECT w.strategy, w.metadata_json, w.confidence_score,
                      w.token_count, w.latency_ms
               FROM wave1_results w
               JOIN files f ON w.file_path = f.file_path
               WHERE f.filename = ?
               ORDER BY w.strategy""",
            (file_path,),
        ).fetchall()

    if not rows:
        console.print(f"[yellow]No Wave 1 results for: {file_path}[/yellow]")
        return

    panels = []
    for row in rows:
        strategy = row["strategy"]
        confidence = row["confidence_score"] or 0.0
        tokens = row["token_count"] or 0
        latency = row["latency_ms"] or 0

        try:
            metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        except json.JSONDecodeError:
            metadata = {}

        lines = []
        lines.append(f"[bold]Category:[/bold] {metadata.get('category', 'N/A')}")
        lines.append(f"[bold]Difficulty:[/bold] {metadata.get('difficulty', 'N/A')}")

        topics = metadata.get("primary_topics", [])
        if topics:
            lines.append(f"[bold]Topics:[/bold] {', '.join(topics[:5])}")

        aspects = metadata.get("topic_aspects", [])
        if aspects:
            lines.append(f"[bold]Aspects:[/bold] {', '.join(aspects[:3])}")

        lines.append(f"[bold]Confidence:[/bold] {confidence:.2f}")
        lines.append(f"[dim]Tokens: {tokens:,} | Latency: {latency:,}ms[/dim]")

        panels.append(
            Panel(
                "\n".join(lines),
                title=f"[bold]{strategy}[/bold]",
                border_style="cyan",
                width=40,
            )
        )

    console.print(f"\n[bold]File:[/bold] {file_path}\n")
    console.print(Columns(panels, equal=True, expand=True))


def export_wave1_csv(db: "Database", output_path: Path) -> None:
    """Export all wave1_results to CSV for offline analysis.

    CSV columns: file_path, strategy, category, difficulty, primary_topics,
    topic_aspects_count, confidence_score, tokens, latency_ms.

    Args:
        db: Database instance to query.
        output_path: Path for the CSV output file.
    """
    rows = db.conn.execute(
        """SELECT file_path, strategy, metadata_json, token_count,
                  latency_ms, confidence_score
           FROM wave1_results
           ORDER BY strategy, file_path"""
    ).fetchall()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "file_path", "strategy", "category", "difficulty",
            "primary_topics", "topic_aspects_count", "confidence_score",
            "tokens", "latency_ms",
        ])

        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            except json.JSONDecodeError:
                metadata = {}

            writer.writerow([
                row["file_path"],
                row["strategy"],
                metadata.get("category", ""),
                metadata.get("difficulty", ""),
                "|".join(metadata.get("primary_topics", [])),
                len(metadata.get("topic_aspects", [])),
                row["confidence_score"] or 0.0,
                row["token_count"] or 0,
                row["latency_ms"] or 0,
            ])

    console = Console()
    console.print(f"[green]Exported {len(rows)} results to:[/green] {output_path}")


def _compute_best_strategy(report: dict) -> tuple[str, float]:
    """Compute the best strategy by composite score.

    Composite score = validation_pass_rate * avg_confidence.

    Args:
        report: Dict from generate_wave1_report().

    Returns:
        Tuple of (strategy_name, composite_score).
    """
    best_name = ""
    best_score = -1.0
    for strategy, metrics in report.items():
        score = metrics["validation_pass_rate"] * metrics["avg_confidence"]
        if score > best_score:
            best_score = score
            best_name = strategy
    return best_name, best_score
