"""Checkpoint management for Wave 1 extraction with credit exhaustion handling.

Provides atomic checkpoint save/load for pause/resume capability when
Mistral credits are exhausted (HTTP 402). State is written atomically
(write to .tmp then rename) to avoid corruption from crashes.

The CreditExhaustionHandler displays a Rich notification panel with
progress per lane, total API calls, and instructions for the stakeholder
to fund and resume.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


class CheckpointManager:
    """Manages atomic checkpoint save/load for Wave 1 extraction.

    Checkpoints are JSON files containing per-lane progress, enabling
    resume after credit exhaustion or interruption.

    Args:
        checkpoint_dir: Directory to store checkpoint file.
                       Defaults to 'data/'.
        filename: Checkpoint filename. Defaults to 'wave1_checkpoint.json'.
    """

    def __init__(
        self,
        checkpoint_dir: Path = Path("data"),
        filename: str = "wave1_checkpoint.json",
    ) -> None:
        self._checkpoint_dir = Path(checkpoint_dir)
        self._checkpoint_path = self._checkpoint_dir / filename

    @property
    def path(self) -> Path:
        """Return the checkpoint file path."""
        return self._checkpoint_path

    @property
    def exists(self) -> bool:
        """Check if a checkpoint file exists."""
        return self._checkpoint_path.exists()

    def save(self, state: dict) -> None:
        """Atomically save checkpoint state.

        Writes to a temporary file first, then renames to the final
        path. This ensures the checkpoint is never in a partial state
        if the process is interrupted during writing.

        Args:
            state: Checkpoint state dict containing:
                - wave (str): Wave identifier (e.g., 'wave1')
                - lanes (dict): Per-lane progress
                    {lane_name: {completed: [str], failed: [str], tokens: int}}
                - next_file_index (int): Index of next file to process
                - timestamp (str): ISO 8601 timestamp
                - prompt_version (str): Prompt version for reproducibility
        """
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # Add timestamp if not present
        if "timestamp" not in state:
            state["timestamp"] = datetime.now(tz=timezone.utc).isoformat()

        tmp_path = self._checkpoint_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(state, indent=2, default=str))
        tmp_path.rename(self._checkpoint_path)

    def load(self) -> dict | None:
        """Load checkpoint state from file.

        Returns:
            Checkpoint state dict, or None if no checkpoint exists.
        """
        if not self._checkpoint_path.exists():
            return None
        return json.loads(self._checkpoint_path.read_text())

    def clear(self) -> None:
        """Delete the checkpoint file if it exists."""
        if self._checkpoint_path.exists():
            self._checkpoint_path.unlink()


class CreditExhaustionHandler:
    """Displays Rich notification when Mistral credits are exhausted.

    Provides a formatted panel showing Wave 1 progress per lane,
    total API calls, estimated cost, and instructions for the
    stakeholder to fund and resume.
    """

    def display_pause_notification(
        self,
        lanes: dict[str, dict],
        total_calls: int,
        estimated_cost: float,
        total_files: int = 20,
    ) -> None:
        """Display credit exhaustion notification with progress summary.

        Args:
            lanes: Per-lane progress dict.
                {lane_name: {completed: [str], failed: [str], tokens: int}}
            total_calls: Total API calls made before exhaustion.
            estimated_cost: Estimated cost in USD so far.
            total_files: Total number of test files per lane.
        """
        console = Console()

        # Build lane progress table
        table = Table(show_header=True, header_style="bold")
        table.add_column("Lane", style="cyan")
        table.add_column("Completed", justify="right")
        table.add_column("Failed", justify="right", style="red")
        table.add_column("Tokens", justify="right")

        for lane_name, lane_data in lanes.items():
            completed = len(lane_data.get("completed", []))
            failed = len(lane_data.get("failed", []))
            tokens = lane_data.get("tokens", 0)
            table.add_row(
                lane_name,
                f"{completed}/{total_files}",
                str(failed),
                f"{tokens:,}",
            )

        # Build notification panel
        console.print()
        console.print(
            Panel(
                "\n".join([
                    "[bold yellow]MISTRAL CREDITS EXHAUSTED - Wave 1 Paused[/bold yellow]",
                    "",
                ]),
                title="[bold red]PAUSED[/bold red]",
                border_style="red",
                padding=(0, 2),
            )
        )

        console.print("\n[bold]Wave 1 Progress:[/bold]")
        console.print(table)

        console.print(f"\n  Total API calls: [bold]{total_calls:,}[/bold]")
        console.print(
            f"  Estimated cost so far: [bold]${estimated_cost:.2f}[/bold]"
        )

        console.print("\n[bold yellow]ACTION REQUIRED:[/bold yellow]")
        console.print("  1. Fund Mistral API account")
        console.print("  2. Verify credits available")
        console.print("  3. Resume with: [bold]objlib extract wave1 --resume[/bold]")
        console.print(
            "\n  All completed work is saved and will not be re-processed.\n"
        )
