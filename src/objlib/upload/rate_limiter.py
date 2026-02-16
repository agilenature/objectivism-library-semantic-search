"""Rate limit tier configuration and adaptive throttling.

Provides tier-based request-per-minute settings for the Gemini API and
an adaptive rate limiter that adjusts inter-request delays based on
circuit breaker state.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from objlib.upload.circuit_breaker import CircuitState, RollingWindowCircuitBreaker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

RATE_LIMIT_TIERS: dict[str, dict[str, int | None]] = {
    "free": {"rpm": 5, "rpd": 100},
    "tier1": {"rpm": 20, "rpd": None},
    "tier2": {"rpm": 200, "rpd": None},
    "tier3": {"rpm": 2000, "rpd": None},
}


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass
class RateLimiterConfig:
    """Rate limiter settings derived from a named tier.

    Attributes:
        tier: One of ``free``, ``tier1``, ``tier2``, ``tier3``.
        rpm: Requests per minute for the tier.
        rpd: Requests per day (``None`` means unlimited).
        min_request_interval: Seconds between requests (``60 / rpm``).
    """

    tier: str = "tier1"
    rpm: int = field(init=False)
    rpd: int | None = field(init=False)

    def __post_init__(self) -> None:
        tier_data = RATE_LIMIT_TIERS.get(self.tier)
        if tier_data is None:
            raise ValueError(
                f"Unknown rate limit tier {self.tier!r}. "
                f"Choose from: {', '.join(RATE_LIMIT_TIERS)}"
            )
        self.rpm = tier_data["rpm"]  # type: ignore[assignment]
        self.rpd = tier_data["rpd"]  # type: ignore[assignment]

    @property
    def min_request_interval(self) -> float:
        """Minimum seconds between consecutive requests."""
        return 60.0 / self.rpm


# ---------------------------------------------------------------------------
# Adaptive rate limiter
# ---------------------------------------------------------------------------


class AdaptiveRateLimiter:
    """Throttles API calls based on tier config and circuit breaker state.

    When the circuit is:
    * **CLOSED** -- waits the base ``min_request_interval``.
    * **OPEN** -- multiplies interval by 3x.
    * **HALF_OPEN** -- multiplies interval by 1.5x.

    Also tracks observed rate limit headers for diagnostics (observation
    only; does not enforce).
    """

    def __init__(
        self,
        config: RateLimiterConfig,
        circuit_breaker: RollingWindowCircuitBreaker,
    ) -> None:
        self._config = config
        self._circuit_breaker = circuit_breaker
        self._observed_remaining: int | None = None

    async def wait_if_needed(self) -> None:
        """Sleep for the appropriate interval given the current circuit state."""
        base = self._config.min_request_interval
        state = self._circuit_breaker.state

        if state == CircuitState.OPEN:
            delay = base * 3.0
        elif state == CircuitState.HALF_OPEN:
            delay = base * 1.5
        else:
            delay = base

        if delay > 0:
            logger.debug(
                "Rate limiter: sleeping %.2fs (state=%s, base=%.2fs)",
                delay,
                state.value,
                base,
            )
            await asyncio.sleep(delay)

    def observe_headers(self, headers: dict[str, str] | None) -> None:
        """Record observed rate limit headers from an API response.

        This is observation-only -- it does not enforce limits.

        Args:
            headers: Response headers dict (or ``None``).
        """
        if headers is None:
            return
        remaining = headers.get("x-ratelimit-remaining")
        if remaining is not None:
            try:
                self._observed_remaining = int(remaining)
                logger.debug(
                    "Observed x-ratelimit-remaining: %d", self._observed_remaining
                )
            except (ValueError, TypeError):
                pass

    @property
    def observed_remaining(self) -> int | None:
        """Last observed ``x-ratelimit-remaining`` value, or ``None``."""
        return self._observed_remaining
