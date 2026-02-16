"""Rich hierarchical progress tracking for the upload pipeline.

Provides three-tier progress display (per locked decision #8):

* **Pipeline level** -- overall progress across all files
* **Batch level** -- progress within the current logical batch
* **Status text** -- current file name and circuit breaker state
"""

from __future__ import annotations

from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)

from rich.progress import TaskID


class UploadProgressTracker:
    """Three-tier Rich progress tracker for the upload pipeline.

    Usage::

        tracker = UploadProgressTracker(total_files=1884, total_batches=13)
        with tracker:
            tracker.start_batch(1, 150)
            tracker.file_uploaded("/path/to/file.txt")
            tracker.complete_batch(1)

    Or without context manager::

        tracker.start()
        # ... use tracker ...
        tracker.stop()
    """

    def __init__(self, total_files: int, total_batches: int) -> None:
        self._total_files = total_files
        self._total_batches = total_batches

        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            TextColumn("{task.fields[status]}", style="dim"),
        )

        self._pipeline_task: TaskID | None = None
        self._current_batch_task: TaskID | None = None
        self._prev_batch_task: TaskID | None = None

        self._stats: dict[str, int] = {
            "succeeded": 0,
            "failed": 0,
            "rate_limited": 0,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the Rich progress display."""
        self._progress.start()
        self._pipeline_task = self._progress.add_task(
            "[green]Pipeline",
            total=self._total_files,
            status="starting...",
        )

    def stop(self) -> None:
        """Stop the Rich progress display."""
        self._progress.stop()

    def __enter__(self) -> UploadProgressTracker:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Batch tracking
    # ------------------------------------------------------------------

    def start_batch(self, batch_number: int, batch_size: int) -> None:
        """Create a new batch-level progress task.

        Hides the previous batch task (if any) to keep output clean.
        """
        if self._current_batch_task is not None:
            self._prev_batch_task = self._current_batch_task
            self._progress.update(self._prev_batch_task, visible=False)

        self._current_batch_task = self._progress.add_task(
            f"[blue]Batch {batch_number}",
            total=batch_size,
            status="uploading",
        )

        if self._pipeline_task is not None:
            self._progress.update(
                self._pipeline_task,
                status=f"batch {batch_number}/{self._total_batches}",
            )

    def complete_batch(self, batch_number: int) -> None:
        """Mark the current batch as complete."""
        if self._current_batch_task is not None:
            self._progress.update(
                self._current_batch_task,
                status=f"batch {batch_number} done",
            )

    # ------------------------------------------------------------------
    # File-level events
    # ------------------------------------------------------------------

    def file_uploaded(self, file_path: str) -> None:
        """Record a successful file upload."""
        self._stats["succeeded"] += 1
        filename = _truncate_path(file_path)

        if self._pipeline_task is not None:
            self._progress.advance(self._pipeline_task, 1)
            self._progress.update(self._pipeline_task, status=filename)

        if self._current_batch_task is not None:
            self._progress.advance(self._current_batch_task, 1)
            self._progress.update(self._current_batch_task, status=filename)

    def file_failed(self, file_path: str, error: str) -> None:
        """Record a failed file upload."""
        self._stats["failed"] += 1
        filename = _truncate_path(file_path)

        if self._pipeline_task is not None:
            self._progress.advance(self._pipeline_task, 1)
            self._progress.update(
                self._pipeline_task,
                status=f"[red]FAIL[/red] {filename}",
            )

        if self._current_batch_task is not None:
            self._progress.advance(self._current_batch_task, 1)
            self._progress.update(
                self._current_batch_task,
                status=f"[red]FAIL[/red] {filename}",
            )

    def file_rate_limited(self, file_path: str) -> None:
        """Record a rate-limited file."""
        self._stats["rate_limited"] += 1

        if self._pipeline_task is not None:
            self._progress.update(
                self._pipeline_task,
                status="[yellow]Rate limited...[/yellow]",
            )

    def update_circuit_state(self, state: str, concurrency: int) -> None:
        """Update the pipeline status with circuit breaker info."""
        if self._pipeline_task is not None:
            self._progress.update(
                self._pipeline_task,
                status=f"circuit={state} concurrency={concurrency}",
            )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict[str, int]:
        """Return a copy of the current statistics."""
        return dict(self._stats)


def _truncate_path(file_path: str, max_len: int = 40) -> str:
    """Truncate a file path for display, keeping the filename."""
    if len(file_path) <= max_len:
        return file_path
    parts = file_path.rsplit("/", 1)
    if len(parts) == 2:
        name = parts[1]
        if len(name) > max_len - 3:
            return "..." + name[-(max_len - 3) :]
        return "..." + file_path[-(max_len - 3) :]
    return "..." + file_path[-(max_len - 3) :]
