"""Stratified test file selector for Wave 1 competitive discovery.

Selects a balanced sample of files from the database, stratified by
file size and podcast/non-podcast distribution, for use as the test
set across competing strategy lanes.

Uses deterministic random seed (42) for reproducibility.
"""

from __future__ import annotations

import json
import random
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from objlib.database import Database

# Size bucket definitions (adjusted from research: only 2 files <5KB,
# so using <10KB as "small" instead of <5KB)
_BUCKETS: list[tuple[str, int, int, int]] = [
    # (name, min_bytes, max_bytes, target_count)
    ("small", 0, 10_000, 4),
    ("medium", 10_000, 30_000, 6),
    ("large", 30_000, 100_000, 6),
    ("very_large", 100_000, float("inf"), 4),  # type: ignore[arg-type]
]


def select_test_files(db: "Database", n: int = 20) -> list[dict]:
    """Select stratified test files from the database for Wave 1 discovery.

    Queries for TXT files with unknown category, stratifies by file size
    into 4 buckets, and balances podcast vs non-podcast distribution
    within each bucket.

    Args:
        db: Database instance to query.
        n: Target number of files to select (default 20).

    Returns:
        List of dicts with keys: file_path, filename, file_size,
        is_podcast (bool), bucket (str).
    """
    random.seed(42)

    # Query all unknown-category TXT files
    rows = db.conn.execute(
        """SELECT file_path, filename, file_size, metadata_json
           FROM files
           WHERE json_extract(metadata_json, '$.category') = 'unknown'
             AND filename LIKE '%.txt'
             AND NOT is_deleted
           ORDER BY file_path""",
    ).fetchall()

    # Parse into candidate list with podcast detection
    candidates: list[dict] = []
    for row in rows:
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        is_podcast = metadata.get("series") == "Peikoff Podcast"
        candidates.append({
            "file_path": row["file_path"],
            "filename": row["filename"],
            "file_size": row["file_size"],
            "is_podcast": is_podcast,
            "metadata": metadata,
        })

    # Assign candidates to size buckets
    buckets: dict[str, list[dict]] = {name: [] for name, *_ in _BUCKETS}
    for candidate in candidates:
        size = candidate["file_size"]
        for name, min_bytes, max_bytes, _ in _BUCKETS:
            if min_bytes <= size < max_bytes:
                buckets[name].append(candidate)
                break

    # Calculate target counts per bucket
    targets = {name: target for name, _, _, target in _BUCKETS}

    # Select from each bucket with podcast balancing
    selected: list[dict] = []
    deficit = 0

    for bucket_name, _, _, target in _BUCKETS:
        pool = buckets[bucket_name]
        actual_target = target + deficit
        deficit = 0

        if len(pool) <= actual_target:
            # Take all available, carry deficit forward
            for item in pool:
                item["bucket"] = bucket_name
            selected.extend(pool)
            deficit = actual_target - len(pool)
        else:
            # Balance podcast vs non-podcast within bucket
            podcasts = [f for f in pool if f["is_podcast"]]
            non_podcasts = [f for f in pool if not f["is_podcast"]]

            bucket_selected: list[dict] = []

            # Ensure at least 1 podcast per bucket where available
            if podcasts and actual_target >= 2:
                podcast_pick = random.sample(podcasts, min(1, len(podcasts)))
                bucket_selected.extend(podcast_pick)
                remaining_target = actual_target - len(podcast_pick)
                remaining_pool = non_podcasts + [
                    p for p in podcasts if p not in podcast_pick
                ]
            else:
                remaining_target = actual_target
                remaining_pool = pool

            if remaining_target > 0 and remaining_pool:
                additional = random.sample(
                    remaining_pool,
                    min(remaining_target, len(remaining_pool)),
                )
                bucket_selected.extend(additional)

            for item in bucket_selected:
                item["bucket"] = bucket_name
            selected.extend(bucket_selected)

    # Trim to exact n if over-selected due to redistribution
    if len(selected) > n:
        selected = selected[:n]

    # Remove internal metadata field before returning
    result = []
    for item in selected:
        result.append({
            "file_path": item["file_path"],
            "filename": item["filename"],
            "file_size": item["file_size"],
            "is_podcast": item["is_podcast"],
            "bucket": item["bucket"],
        })

    # Print selection summary
    _print_summary(result, targets, len(candidates))

    return result


def _print_summary(
    selected: list[dict],
    targets: dict[str, int],
    total_candidates: int,
) -> None:
    """Print a Rich table summarizing the test file selection.

    Args:
        selected: The selected test files.
        targets: Target counts per bucket.
        total_candidates: Total number of candidates available.
    """
    console = Console()

    console.print(
        f"\n[bold]Test File Selection[/bold]: "
        f"{len(selected)} files from {total_candidates} candidates\n"
    )

    table = Table(title="Stratified Sample Distribution")
    table.add_column("Bucket", style="cyan")
    table.add_column("Target", justify="right")
    table.add_column("Selected", justify="right")
    table.add_column("Podcasts", justify="right", style="green")
    table.add_column("Non-Podcast", justify="right")

    for bucket_name, _, _, target in _BUCKETS:
        bucket_files = [f for f in selected if f["bucket"] == bucket_name]
        podcast_count = sum(1 for f in bucket_files if f["is_podcast"])
        non_podcast_count = len(bucket_files) - podcast_count
        table.add_row(
            bucket_name,
            str(target),
            str(len(bucket_files)),
            str(podcast_count),
            str(non_podcast_count),
        )

    total_podcasts = sum(1 for f in selected if f["is_podcast"])
    table.add_row(
        "[bold]Total[/bold]",
        str(sum(targets.values())),
        f"[bold]{len(selected)}[/bold]",
        f"[bold]{total_podcasts}[/bold]",
        f"[bold]{len(selected) - total_podcasts}[/bold]",
        style="bold",
    )

    console.print(table)
