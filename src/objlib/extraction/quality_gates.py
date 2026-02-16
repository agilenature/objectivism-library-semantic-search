"""Quality gate evaluation for Wave 1 to Wave 2 transition.

Evaluates the best strategy from Wave 1 results against quality thresholds
(accuracy, cost, confidence, validation rate) to determine readiness for
Wave 2 production processing.

Gate thresholds per W1.A7 decision:
- tier1_accuracy: validation_pass_rate >= 0.90
- cost_per_file: estimated cost <= $0.30
- mean_confidence: avg_confidence >= 0.70
- validation_rate: validation_pass_rate >= 0.85
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


@dataclass
class GateResult:
    """Result of evaluating a single quality gate.

    Attributes:
        name: Gate identifier (e.g., 'tier1_accuracy').
        threshold: Required minimum/maximum value.
        actual: Observed value from Wave 1 results.
        passed: Whether actual meets or exceeds threshold.
    """

    name: str
    threshold: float
    actual: float
    passed: bool


def evaluate_quality_gates(report: dict) -> tuple[bool, list[GateResult]]:
    """Evaluate quality gates for the best Wave 1 strategy.

    Finds the best strategy by composite score (validation_pass_rate *
    avg_confidence), then evaluates four quality gates against thresholds.

    Args:
        report: Dict from generate_wave1_report() mapping strategy name
                to metrics dict.

    Returns:
        Tuple of (all_passed: bool, gate_results: list[GateResult]).
    """
    # Find best strategy by composite score
    best_strategy = ""
    best_score = -1.0
    for strategy, metrics in report.items():
        score = metrics["validation_pass_rate"] * metrics["avg_confidence"]
        if score > best_score:
            best_score = score
            best_strategy = strategy

    best = report[best_strategy]

    # Evaluate gates
    gates: list[GateResult] = []

    # Gate 1: Tier 1 accuracy (validation_pass_rate >= 0.90)
    gates.append(GateResult(
        name="tier1_accuracy",
        threshold=0.90,
        actual=best["validation_pass_rate"],
        passed=best["validation_pass_rate"] >= 0.90,
    ))

    # Gate 2: Cost per file (avg_tokens / 1000 * 0.007 <= 0.30)
    # magistral pricing: ~$0.007 per 1K tokens combined
    cost_per_file = (best["avg_tokens"] / 1000) * 0.007
    gates.append(GateResult(
        name="cost_per_file",
        threshold=0.30,
        actual=round(cost_per_file, 4),
        passed=cost_per_file <= 0.30,
    ))

    # Gate 3: Mean confidence (avg_confidence >= 0.70)
    gates.append(GateResult(
        name="mean_confidence",
        threshold=0.70,
        actual=best["avg_confidence"],
        passed=best["avg_confidence"] >= 0.70,
    ))

    # Gate 4: Validation rate (validation_pass_rate >= 0.85)
    gates.append(GateResult(
        name="validation_rate",
        threshold=0.85,
        actual=best["validation_pass_rate"],
        passed=best["validation_pass_rate"] >= 0.85,
    ))

    all_passed = all(g.passed for g in gates)
    return all_passed, gates


def display_gate_results(
    gates: list[GateResult], console: Console
) -> None:
    """Display quality gate evaluation as a Rich table.

    Green checkmark for passed gates, red X for failed gates.
    If all passed: green panel approving Wave 2. If any failed:
    yellow panel indicating Wave 1.5 re-discovery needed.

    Args:
        gates: List of GateResult from evaluate_quality_gates().
        console: Rich Console for output.
    """
    table = Table(title="Quality Gate Evaluation", show_header=True)
    table.add_column("Gate", style="bold")
    table.add_column("Threshold", justify="right")
    table.add_column("Actual", justify="right")
    table.add_column("Status", justify="center")

    for gate in gates:
        if gate.name == "cost_per_file":
            threshold_str = f"<= ${gate.threshold:.2f}"
            actual_str = f"${gate.actual:.4f}"
        else:
            threshold_str = f">= {gate.threshold:.2f}"
            actual_str = f"{gate.actual:.3f}"

        status = "[green]PASS[/green]" if gate.passed else "[red]FAIL[/red]"
        table.add_row(gate.name, threshold_str, actual_str, status)

    console.print(table)

    all_passed = all(g.passed for g in gates)
    if all_passed:
        console.print(
            Panel(
                "[bold green]WAVE 2 APPROVED[/bold green] - Ready for production processing",
                border_style="green",
            )
        )
    else:
        failed_gates = [g.name for g in gates if not g.passed]
        console.print(
            Panel(
                "[bold yellow]WAVE 1.5 NEEDED[/bold yellow] - Focused re-discovery required\n\n"
                f"Failed gates: {', '.join(failed_gates)}",
                border_style="yellow",
            )
        )


def recommend_strategy(report: dict) -> str:
    """Recommend a strategy based on Wave 1 results.

    Returns the strategy with the highest composite score
    (validation_pass_rate * avg_confidence), or "hybrid" if split
    performance is detected (one strategy wins on validation but
    another wins on confidence by >10%).

    Args:
        report: Dict from generate_wave1_report().

    Returns:
        Strategy name string, or "hybrid" if split performance detected.
    """
    if not report:
        return "unknown"

    # Find best by validation_pass_rate
    best_validation = max(report, key=lambda s: report[s]["validation_pass_rate"])

    # Find best by avg_confidence
    best_confidence = max(report, key=lambda s: report[s]["avg_confidence"])

    # Check for split performance: different winners AND confidence gap > 10%
    if best_validation != best_confidence:
        val_confidence = report[best_validation]["avg_confidence"]
        conf_confidence = report[best_confidence]["avg_confidence"]
        confidence_gap = abs(conf_confidence - val_confidence)

        if confidence_gap > 0.10:
            return "hybrid"

    # No split: return best composite score
    best_strategy = max(
        report,
        key=lambda s: report[s]["validation_pass_rate"] * report[s]["avg_confidence"],
    )
    return best_strategy
