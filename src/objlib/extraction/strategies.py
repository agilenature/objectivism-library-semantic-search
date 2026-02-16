"""Wave 1 strategy lane definitions for competitive prompt discovery.

Defines three distinct strategy archetypes (Minimalist, Teacher, Reasoner)
for A/B/C comparison on 20 stratified test files. Each strategy varies
prompt structure and temperature to discover optimal extraction approach.

NOTE on temperature: magistral-medium-latest requires temperature=1.0
for production use. Wave 1 intentionally uses lower temperatures as
experimental parameters. Lane A (0.1) and Lane B (0.3) may produce
degraded results compared to Lane C (0.5) -- this IS useful data for
understanding the model's temperature sensitivity. If all lanes show
poor quality, temperature constraints should be the first hypothesis.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StrategyConfig:
    """Configuration for a single strategy lane.

    Attributes:
        name: Strategy identifier (e.g., 'minimalist').
        system_prompt_strategy: Strategy key passed to build_system_prompt().
        temperature: Sampling temperature for the Mistral API call.
        description: Human-readable summary of the strategy approach.
    """

    name: str
    system_prompt_strategy: str
    temperature: float
    description: str


@dataclass
class StrategyLane:
    """Runtime state for a strategy lane during Wave 1 execution.

    Tracks completed/failed files, token usage, and progress for
    checkpoint/resume support.

    Attributes:
        config: The strategy configuration for this lane.
        completed_files: File paths successfully processed.
        failed_files: File paths that failed processing.
        total_tokens: Cumulative token usage across all files.
    """

    config: StrategyConfig
    completed_files: list[str] = field(default_factory=list)
    failed_files: list[str] = field(default_factory=list)
    total_tokens: int = 0

    def progress_pct(self, total: int) -> float:
        """Calculate completion percentage.

        Args:
            total: Total number of files in the test set.

        Returns:
            Completion percentage (0.0 to 100.0).
        """
        if total <= 0:
            return 0.0
        return (len(self.completed_files) / total) * 100.0


WAVE1_STRATEGIES: dict[str, StrategyConfig] = {
    "minimalist": StrategyConfig(
        name="minimalist",
        system_prompt_strategy="minimalist",
        temperature=0.1,
        description="Zero-shot strict JSON schema, lowest cost",
    ),
    "teacher": StrategyConfig(
        name="teacher",
        system_prompt_strategy="teacher",
        temperature=0.3,
        description="One-shot with example, focus on structure",
    ),
    "reasoner": StrategyConfig(
        name="reasoner",
        system_prompt_strategy="reasoner",
        temperature=0.5,
        description="Chain-of-thought, focus on accuracy/nuance",
    ),
}
