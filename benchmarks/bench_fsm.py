"""FSM transition throughput benchmark for VLID-06.

Measures per-file FSM lifecycle (UNTRACKED -> UPLOADING -> PROCESSING -> INDEXED)
across 818 simulated files at concurrency=1, =10, =50 with zero and realistic
mock API latency profiles.

Reports P50/P95/P99 per timing segment, identifies bottleneck, evaluates
Threshold 1 (zero/c=10 <= 5min) and Threshold 2 (realistic/c=10 <= 6h).

Usage:
    uv run python benchmarks/bench_fsm.py           # Full run (realistic delay=2.0s, ~60min)
    uv run python benchmarks/bench_fsm.py --quick    # Quick verification (delay=0.05s, ~2min)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

# Add project src to path for FSM import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import aiosqlite
import yappi
from rich.console import Console
from rich.table import Table

from objlib.upload.fsm import create_fsm

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FILE_COUNT = 818
TRANSITIONS_PER_FILE = 4  # untracked->uploading->processing->indexed
TOTAL_TRANSITIONS = FILE_COUNT * TRANSITIONS_PER_FILE
SEED = 42  # Documented but not used (constant delay per locked decision Q3)

THRESHOLD_1_MAX_SECONDS = 300    # 5 minutes for zero profile, c=10
THRESHOLD_2_MAX_SECONDS = 21600  # 6 hours for realistic profile, c=10

CONCURRENCY_LEVELS = [1, 10, 50]
PROFILES = ["zero", "realistic"]

# Minimal schema for benchmark (matches V11 production schema)
BENCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    file_path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    metadata_json TEXT,
    metadata_quality TEXT DEFAULT 'unknown',
    is_deleted INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    gemini_file_uri TEXT,
    gemini_file_id TEXT,
    upload_timestamp TEXT,
    remote_expiration_ts TEXT,
    embedding_model_version TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    ai_metadata_status TEXT DEFAULT 'pending',
    ai_confidence_score REAL,
    entity_extraction_version TEXT,
    entity_extraction_status TEXT DEFAULT 'pending',
    upload_attempt_count INTEGER DEFAULT 0,
    last_upload_hash TEXT,
    mtime REAL,
    orphaned_gemini_file_id TEXT,
    missing_since TEXT,
    upload_hash TEXT,
    enrichment_version TEXT,
    gemini_store_doc_id TEXT,
    gemini_state TEXT NOT NULL DEFAULT 'untracked'
        CHECK(gemini_state IN ('untracked','uploading','processing','indexed','failed')),
    gemini_state_updated_at TEXT,
    version INTEGER NOT NULL DEFAULT 0,
    intent_type TEXT,
    intent_started_at TEXT,
    intent_api_calls_completed INTEGER
);

CREATE INDEX IF NOT EXISTS idx_gemini_state ON files(gemini_state);
"""

console = Console()


# ---------------------------------------------------------------------------
# Mock API adapter
# ---------------------------------------------------------------------------

@dataclass
class MockFile:
    name: str
    uri: str


@dataclass
class MockResponse:
    name: str


@dataclass
class MockOperation:
    done: bool
    error: object
    response: MockResponse


class MockApiAdapter:
    """Simulates Gemini API calls with configurable latency."""

    def __init__(self, profile: str, realistic_delay: float = 2.0) -> None:
        self.profile = profile
        self._delay = 0.0 if profile == "zero" else realistic_delay

    async def upload_file(self, file_path: str, display_name: str) -> MockFile:
        """Simulate file upload API call."""
        await asyncio.sleep(self._delay)
        return MockFile(
            name=f"files/mock_{file_path.replace('/', '_')}",
            uri=f"uri://mock_{file_path.replace('/', '_')}",
        )

    async def import_to_store(
        self, file_name: str, metadata: list
    ) -> MockOperation:
        """Simulate store import API call."""
        await asyncio.sleep(self._delay)
        return MockOperation(
            done=True,
            error=None,
            response=MockResponse(name=f"doc_{file_name}"),
        )


# ---------------------------------------------------------------------------
# Per-file lifecycle
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


async def process_file(
    file_path: str,
    version: int,
    db: aiosqlite.Connection,
    mock_adapter: MockApiAdapter,
) -> dict[str, float]:
    """Execute full 4-transition lifecycle for one file, recording timings."""
    timings: dict[str, float] = {}
    total_start = perf_counter()

    # 1. Hydrate FSM (per locked decision Q8)
    t = perf_counter()
    fsm = create_fsm("untracked")
    timings["fsm_hydrate_ms"] = (perf_counter() - t) * 1000

    # 2. Transition: untracked -> uploading
    t = perf_counter()
    fsm.start_upload()  # FSM validation only
    timings["fsm_dispatch_1_ms"] = (perf_counter() - t) * 1000

    now = _now_iso()
    new_version = version + 1
    t = perf_counter()
    cursor = await db.execute(
        """UPDATE files SET gemini_state='uploading',
           gemini_state_updated_at=?, version=?
           WHERE file_path=? AND gemini_state='untracked' AND version=?""",
        (now, new_version, file_path, version),
    )
    timings["lock_wait_1_ms"] = (perf_counter() - t) * 1000
    await db.commit()
    timings["db_write_1_ms"] = (perf_counter() - t) * 1000
    if cursor.rowcount == 0:
        raise RuntimeError(f"OCC conflict on {file_path} (untracked->uploading)")
    version = new_version

    # 3. Mock API call: upload_file
    t = perf_counter()
    file_obj = await mock_adapter.upload_file(file_path, "display")
    timings["mock_upload_ms"] = (perf_counter() - t) * 1000

    # 4. Transition: uploading -> processing
    t = perf_counter()
    fsm.complete_upload()  # FSM validation
    timings["fsm_dispatch_2_ms"] = (perf_counter() - t) * 1000

    now = _now_iso()
    new_version = version + 1
    t = perf_counter()
    cursor = await db.execute(
        """UPDATE files SET gemini_state='processing',
           gemini_file_id=?, gemini_file_uri=?,
           upload_timestamp=?, gemini_state_updated_at=?, version=?
           WHERE file_path=? AND gemini_state='uploading' AND version=?""",
        (file_obj.name, file_obj.uri, now, now, new_version, file_path, version),
    )
    timings["lock_wait_2_ms"] = (perf_counter() - t) * 1000
    await db.commit()
    timings["db_write_2_ms"] = (perf_counter() - t) * 1000
    if cursor.rowcount == 0:
        raise RuntimeError(f"OCC conflict on {file_path} (uploading->processing)")
    version = new_version

    # 5. Mock API call: import_to_store
    t = perf_counter()
    operation = await mock_adapter.import_to_store(file_obj.name, [])
    timings["mock_import_ms"] = (perf_counter() - t) * 1000

    # 6. Transition: processing -> indexed
    t = perf_counter()
    fsm.complete_processing()  # FSM validation
    timings["fsm_dispatch_3_ms"] = (perf_counter() - t) * 1000

    now = _now_iso()
    new_version = version + 1
    t = perf_counter()
    cursor = await db.execute(
        """UPDATE files SET gemini_state='indexed',
           gemini_store_doc_id=?, gemini_state_updated_at=?, version=?
           WHERE file_path=? AND gemini_state='processing' AND version=?""",
        (operation.response.name, now, new_version, file_path, version),
    )
    timings["lock_wait_3_ms"] = (perf_counter() - t) * 1000
    await db.commit()
    timings["db_write_3_ms"] = (perf_counter() - t) * 1000
    if cursor.rowcount == 0:
        raise RuntimeError(f"OCC conflict on {file_path} (processing->indexed)")

    total_ms = (perf_counter() - total_start) * 1000

    # Compute aggregate segments (per locked decision Q1)
    timings["mock_api_ms"] = timings["mock_upload_ms"] + timings["mock_import_ms"]
    timings["db_total_ms"] = (
        timings["db_write_1_ms"] + timings["db_write_2_ms"] + timings["db_write_3_ms"]
    )
    timings["lock_wait_ms"] = (
        timings["lock_wait_1_ms"] + timings["lock_wait_2_ms"] + timings["lock_wait_3_ms"]
    )
    timings["fsm_dispatch_ms"] = (
        timings["fsm_dispatch_1_ms"]
        + timings["fsm_dispatch_2_ms"]
        + timings["fsm_dispatch_3_ms"]
    )
    timings["total_wall_ms"] = total_ms
    timings["fsm_net_ms"] = total_ms - timings["mock_api_ms"]

    return timings


# ---------------------------------------------------------------------------
# Concurrency runner
# ---------------------------------------------------------------------------

async def run_benchmark(
    concurrency: int,
    profile: str,
    db_path: str,
    realistic_delay: float = 2.0,
) -> list[dict[str, float]]:
    """Run 818 files through full lifecycle at given concurrency and profile."""
    sem = asyncio.Semaphore(concurrency)

    async def worker(file_path: str, version: int) -> dict[str, float]:
        async with sem:
            async with aiosqlite.connect(db_path) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA synchronous=NORMAL")
                mock = MockApiAdapter(profile, realistic_delay=realistic_delay)
                return await process_file(file_path, version, db, mock)

    tasks = [
        worker(f"/bench/file_{i:04d}.txt", 0) for i in range(FILE_COUNT)
    ]
    results = await asyncio.gather(*tasks)
    return list(results)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def percentile(values: list[float], pct: float) -> float:
    """Compute percentile from sorted values using nearest-rank method."""
    sorted_vals = sorted(values)
    idx = int(pct * len(sorted_vals))
    idx = min(idx, len(sorted_vals) - 1)
    return sorted_vals[idx]


def compute_segment_stats(
    all_timings: list[dict[str, float]], segment: str
) -> dict[str, float]:
    """Compute P50/P95/P99 for a given timing segment."""
    values = [t[segment] for t in all_timings]
    return {
        "p50": round(percentile(values, 0.50), 4),
        "p95": round(percentile(values, 0.95), 4),
        "p99": round(percentile(values, 0.99), 4),
        "mean": round(sum(values) / len(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


REPORT_SEGMENTS = [
    "mock_api_ms",
    "db_total_ms",
    "lock_wait_ms",
    "fsm_dispatch_ms",
    "fsm_net_ms",
    "total_wall_ms",
]

# Segments in fsm_net breakdown (excludes mock_api_ms)
FSM_NET_SEGMENTS = ["db_total_ms", "lock_wait_ms", "fsm_dispatch_ms"]


# ---------------------------------------------------------------------------
# WAL measurement
# ---------------------------------------------------------------------------

def get_wal_size(db_path: str) -> int:
    """Get WAL file size in bytes (0 if not present)."""
    wal_path = db_path + "-wal"
    try:
        return os.path.getsize(wal_path)
    except FileNotFoundError:
        return 0


# ---------------------------------------------------------------------------
# Database setup and reset
# ---------------------------------------------------------------------------

async def create_bench_db(db_path: str) -> None:
    """Create benchmark database with 818 simulated file rows."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.executescript(BENCH_SCHEMA)

        for i in range(FILE_COUNT):
            file_path = f"/bench/file_{i:04d}.txt"
            await db.execute(
                """INSERT INTO files (file_path, content_hash, filename, file_size,
                   gemini_state, version)
                   VALUES (?, ?, ?, ?, 'untracked', 0)""",
                (file_path, f"hash_{i:04d}", f"file_{i:04d}.txt", 1024),
            )
        await db.commit()

    console.print(f"  Created benchmark DB with {FILE_COUNT} files at {db_path}")


async def reset_files(db_path: str) -> None:
    """Reset all files to untracked/version=0 for next configuration run."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(
            """UPDATE files SET
               gemini_state='untracked',
               gemini_state_updated_at=NULL,
               gemini_file_id=NULL,
               gemini_file_uri=NULL,
               gemini_store_doc_id=NULL,
               upload_timestamp=NULL,
               version=0"""
        )
        await db.commit()


async def verify_all_indexed(db_path: str) -> int:
    """Return count of files in 'indexed' state."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM files WHERE gemini_state='indexed'"
        )
        row = await cursor.fetchone()
        return row[0]


# ---------------------------------------------------------------------------
# Rich table output
# ---------------------------------------------------------------------------

def print_results_table(configs: list[dict]) -> None:
    """Print benchmark results as a Rich table."""
    table = Table(title="FSM Benchmark Results (818 files, 3272 transitions)")

    table.add_column("C", justify="right", style="cyan")
    table.add_column("Profile", style="magenta")
    table.add_column("Elapsed", justify="right")
    table.add_column("Trans/s", justify="right", style="green")
    table.add_column("db P50", justify="right")
    table.add_column("db P95", justify="right", style="yellow")
    table.add_column("lock P95", justify="right")
    table.add_column("fsm_d P95", justify="right")
    table.add_column("net P50", justify="right")
    table.add_column("net P95", justify="right", style="yellow")
    table.add_column("WAL delta", justify="right")
    table.add_column("Verdict", justify="center")

    for cfg in configs:
        seg = cfg["segments"]
        elapsed = cfg["elapsed_seconds"]
        tps = cfg["transitions_per_second"]

        verdict = ""
        if cfg.get("threshold_1_verdict"):
            verdict = cfg["threshold_1_verdict"]
        elif cfg.get("threshold_2_verdict"):
            verdict = cfg["threshold_2_verdict"]

        verdict_style = "green" if verdict == "PASS" else "red" if verdict == "FAIL" else ""

        wal_delta = cfg["wal_size_end_bytes"] - cfg["wal_size_start_bytes"]

        table.add_row(
            str(cfg["concurrency"]),
            cfg["profile"],
            f"{elapsed:.2f}s",
            f"{tps:.1f}",
            f'{seg["db_total_ms"]["p50"]:.2f}',
            f'{seg["db_total_ms"]["p95"]:.2f}',
            f'{seg["lock_wait_ms"]["p95"]:.2f}',
            f'{seg["fsm_dispatch_ms"]["p95"]:.2f}',
            f'{seg["fsm_net_ms"]["p50"]:.2f}',
            f'{seg["fsm_net_ms"]["p95"]:.2f}',
            f"{wal_delta:+d}B",
            f"[{verdict_style}]{verdict}[/{verdict_style}]" if verdict else "",
        )

    console.print(table)


def print_bottleneck(bottleneck: dict) -> None:
    """Print bottleneck identification."""
    console.print()
    console.rule("[bold]Bottleneck Identification")
    console.print(
        f"  Segment: [bold yellow]{bottleneck['segment']}[/bold yellow]"
    )
    console.print(f"  Evidence: {bottleneck['evidence']}")
    console.print()


def print_thresholds(configs: list[dict]) -> None:
    """Print threshold verdicts prominently."""
    console.print()
    console.rule("[bold]Threshold Verdicts")
    for cfg in configs:
        if cfg.get("threshold_1_verdict"):
            v = cfg["threshold_1_verdict"]
            style = "green" if v == "PASS" else "red"
            console.print(
                f"  Threshold 1 (zero, c=10, <=5min): "
                f"[bold {style}]{v}[/bold {style}] "
                f"({cfg['elapsed_seconds']:.2f}s / {THRESHOLD_1_MAX_SECONDS}s)"
            )
        if cfg.get("threshold_2_verdict"):
            v = cfg["threshold_2_verdict"]
            style = "green" if v == "PASS" else "red"
            console.print(
                f"  Threshold 2 (realistic, c=10, <=6h): "
                f"[bold {style}]{v}[/bold {style}] "
                f"({cfg['elapsed_seconds']:.2f}s / {THRESHOLD_2_MAX_SECONDS}s)"
            )
    console.print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="FSM transition throughput benchmark")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick verification mode (realistic delay=0.05s instead of 2.0s)",
    )
    parser.add_argument(
        "--realistic-delay",
        type=float,
        default=None,
        help="Override realistic profile delay in seconds (default: 2.0, --quick sets 0.05)",
    )
    return parser.parse_args()


async def main() -> None:
    """Run all 6 benchmark configurations and report results."""
    args = parse_args()
    realistic_delay = 2.0
    if args.quick:
        realistic_delay = 0.05
    if args.realistic_delay is not None:
        realistic_delay = args.realistic_delay

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    console.rule("[bold blue]FSM Transition Throughput Benchmark")
    console.print(f"  Files: {FILE_COUNT}")
    console.print(f"  Transitions per file: {TRANSITIONS_PER_FILE}")
    console.print(f"  Total transitions: {TOTAL_TRANSITIONS}")
    console.print(f"  Concurrency levels: {CONCURRENCY_LEVELS}")
    console.print(f"  Profiles: {PROFILES}")
    console.print(f"  Realistic delay: {realistic_delay}s" + (" (quick mode)" if args.quick else ""))
    console.print(f"  Seed: {SEED} (constant delay, seed documented only)")
    console.print()

    # Create temp DB
    tmp_dir = tempfile.mkdtemp(prefix="bench_fsm_")
    db_path = os.path.join(tmp_dir, "bench.db")
    await create_bench_db(db_path)

    # Start yappi profiling
    yappi.set_clock_type("wall")
    yappi.start()

    all_configs: list[dict] = []
    # Order: fast configs first (zero profiles, then realistic high-concurrency),
    # slowest config (c=1 realistic ~55min) last
    run_order = [
        (1, "zero"), (10, "zero"), (50, "zero"),
        (50, "realistic"), (10, "realistic"), (1, "realistic"),
    ]

    for idx, (concurrency, profile) in enumerate(run_order):
        console.print(
            f"  [{idx + 1}/{len(run_order)}] Running c={concurrency}, "
            f"profile={profile}..."
        )

        # Reset files to untracked for this run
        if idx > 0:
            await reset_files(db_path)

        # WAL measurement before
        wal_start = get_wal_size(db_path)

        # Run benchmark
        bench_start = perf_counter()
        all_timings = await run_benchmark(
            concurrency, profile, db_path, realistic_delay=realistic_delay
        )
        elapsed = perf_counter() - bench_start

        # WAL measurement after
        wal_end = get_wal_size(db_path)

        # Verify all 818 files reached indexed
        indexed_count = await verify_all_indexed(db_path)
        if indexed_count != FILE_COUNT:
            console.print(
                f"  [bold red]ERROR: Only {indexed_count}/{FILE_COUNT} "
                f"files reached indexed state![/bold red]"
            )
            sys.exit(1)

        # Compute segment stats
        segments = {}
        for seg_name in REPORT_SEGMENTS:
            segments[seg_name] = compute_segment_stats(all_timings, seg_name)

        tps = TOTAL_TRANSITIONS / elapsed

        # WAL contention verdict
        p95_lock = segments["lock_wait_ms"]["p95"]
        p95_db = segments["db_total_ms"]["p95"]
        if p95_db > 0 and p95_lock > 0.05 * p95_db:
            wal_verdict = f"CONTENTION (lock P95={p95_lock:.2f}ms > 5% of db P95={p95_db:.2f}ms)"
        else:
            wal_verdict = "CLEAN"

        cfg_result: dict = {
            "concurrency": concurrency,
            "profile": profile,
            "elapsed_seconds": round(elapsed, 4),
            "transitions_per_second": round(tps, 2),
            "segments": segments,
            "wal_size_start_bytes": wal_start,
            "wal_size_end_bytes": wal_end,
            "wal_contention_verdict": wal_verdict,
            "indexed_count": indexed_count,
        }

        # Threshold evaluation
        if concurrency == 10 and profile == "zero":
            cfg_result["threshold_1_verdict"] = (
                "PASS" if elapsed <= THRESHOLD_1_MAX_SECONDS else "FAIL"
            )
        if concurrency == 10 and profile == "realistic":
            cfg_result["threshold_2_verdict"] = (
                "PASS" if elapsed <= THRESHOLD_2_MAX_SECONDS else "FAIL"
            )

        all_configs.append(cfg_result)
        console.print(
            f"    Done in {elapsed:.2f}s ({tps:.1f} trans/s), "
            f"indexed={indexed_count}/{FILE_COUNT}"
        )

    # Stop yappi
    yappi.stop()

    # Identify bottleneck: highest P95 in fsm_net breakdown at c=10 zero
    bottleneck_cfg = next(
        (c for c in all_configs if c["concurrency"] == 10 and c["profile"] == "zero"),
        None,
    )
    if bottleneck_cfg:
        max_seg = ""
        max_p95 = -1.0
        for seg_name in FSM_NET_SEGMENTS:
            p95 = bottleneck_cfg["segments"][seg_name]["p95"]
            if p95 > max_p95:
                max_p95 = p95
                max_seg = seg_name
        bottleneck = {
            "segment": max_seg,
            "evidence": (
                f"Highest P95 in fsm_net breakdown at concurrency=10 "
                f"zero profile: {max_seg} P95={max_p95:.4f}ms"
            ),
        }
    else:
        bottleneck = {"segment": "unknown", "evidence": "c=10 zero config not found"}

    # Output results
    console.print()
    print_results_table(all_configs)
    print_thresholds(all_configs)
    print_bottleneck(bottleneck)

    # Save JSON results
    bench_dir = Path(__file__).resolve().parent
    json_path = bench_dir / f"results-{timestamp}.json"
    output = {
        "timestamp": timestamp,
        "seed": SEED,
        "file_count": FILE_COUNT,
        "transitions_per_file": TRANSITIONS_PER_FILE,
        "total_transitions": TOTAL_TRANSITIONS,
        "realistic_delay_seconds": realistic_delay,
        "quick_mode": args.quick,
        "configurations": all_configs,
        "bottleneck": bottleneck,
    }
    json_path.write_text(json.dumps(output, indent=2))
    console.print(f"  Results saved to: {json_path}")

    # Save yappi stats
    yappi_path = bench_dir / f"yappi-{timestamp}.txt"
    stats = yappi.get_func_stats()
    stats.save(str(yappi_path), type="pstat")
    console.print(f"  yappi profile saved to: {yappi_path}")

    # Print top 20 yappi functions
    console.print()
    console.rule("[bold]Top 20 Functions by Wall Time (yappi)")
    stats.sort("ttot", "desc")
    # Print top 20 to stdout
    top_count = 0
    for stat in stats:
        if top_count >= 20:
            break
        console.print(
            f"  {stat.ttot:.4f}s  {stat.ncall:>8d} calls  "
            f"{stat.name} ({stat.module}:{stat.lineno})"
        )
        top_count += 1

    # Cleanup
    try:
        os.unlink(db_path)
        wal_path = db_path + "-wal"
        shm_path = db_path + "-shm"
        if os.path.exists(wal_path):
            os.unlink(wal_path)
        if os.path.exists(shm_path):
            os.unlink(shm_path)
        os.rmdir(tmp_dir)
        console.print(f"\n  Cleaned up temp directory: {tmp_dir}")
    except OSError as e:
        console.print(f"\n  Warning: cleanup failed: {e}")

    console.print()
    console.rule("[bold green]Benchmark Complete")


if __name__ == "__main__":
    asyncio.run(main())
