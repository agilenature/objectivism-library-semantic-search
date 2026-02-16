"""Rolling-window circuit breaker for Gemini API rate limit detection.

Tracks 429 error rate over a sliding window of requests and transitions
through CLOSED -> OPEN -> HALF_OPEN states to protect the upload pipeline
from cascading rate limit failures.

Hand-rolled instead of pybreaker because pybreaker's ``fail_max``
consecutive-failure model does not fit rolling-window 429-rate tracking.
"""

from __future__ import annotations

import collections
import logging
import time
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker state machine states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RollingWindowCircuitBreaker:
    """Circuit breaker using a rolling window of recent requests.

    Monitors the 429 (rate limit) error rate over the last *window_size*
    requests.  When the rate exceeds *error_threshold* **or** more than
    *consecutive_threshold* consecutive 429 errors occur, the breaker
    trips to OPEN state.

    After *cooldown_seconds* the breaker transitions to HALF_OPEN,
    allowing a limited number of probe requests.  A successful probe
    closes the breaker; a 429 during probing re-opens it.

    Concurrency recommendations scale with breaker state:
    * CLOSED  -- full concurrency (``max_concurrency``)
    * OPEN    -- halved concurrency (min 3)
    * HALF_OPEN -- gradual ramp based on consecutive successes since
      recovery, incremented by +1 every *recovery_increment* successes.
    """

    def __init__(
        self,
        window_size: int = 100,
        error_threshold: float = 0.05,
        consecutive_threshold: int = 3,
        cooldown_seconds: float = 300,
        recovery_increment: int = 20,
    ) -> None:
        self._window: collections.deque[bool] = collections.deque(maxlen=window_size)
        self._window_size = window_size
        self._error_threshold = error_threshold
        self._consecutive_threshold = consecutive_threshold
        self._cooldown_seconds = cooldown_seconds
        self._recovery_increment = recovery_increment

        self._state = CircuitState.CLOSED
        self._opened_at: float | None = None
        self._consecutive_429s = 0
        self._success_since_recovery = 0

    # ------------------------------------------------------------------
    # Public recording methods
    # ------------------------------------------------------------------

    def record_success(self) -> None:
        """Record a successful API call."""
        self._window.append(True)
        self._consecutive_429s = 0
        self._success_since_recovery += 1

        if self._state == CircuitState.HALF_OPEN:
            logger.info(
                "Circuit breaker HALF_OPEN -> CLOSED after successful probe "
                "(successes since recovery: %d)",
                self._success_since_recovery,
            )
            self._state = CircuitState.CLOSED
            self._window.clear()
            self._success_since_recovery = 0

    def record_429(self) -> None:
        """Record a 429 rate-limit response."""
        self._window.append(False)
        self._consecutive_429s += 1

        if self._should_trip():
            self._trip()

    def record_error(self) -> None:
        """Record a non-429 API error (does not trip the circuit)."""
        # Non-rate-limit errors are tracked for observability but do not
        # affect the circuit breaker state machine.  We reset the
        # consecutive 429 counter since this was a different error.
        self._consecutive_429s = 0
        logger.debug("Circuit breaker recorded non-429 error (state=%s)", self._state)

    # ------------------------------------------------------------------
    # State properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """Current circuit state, with automatic OPEN -> HALF_OPEN transition."""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            elapsed = time.time() - self._opened_at
            if elapsed >= self._cooldown_seconds:
                logger.info(
                    "Circuit breaker OPEN -> HALF_OPEN after %.1fs cooldown",
                    elapsed,
                )
                self._state = CircuitState.HALF_OPEN
                self._success_since_recovery = 0
        return self._state

    @property
    def error_rate(self) -> float:
        """Fraction of 429 errors in the current rolling window."""
        if not self._window:
            return 0.0
        return sum(1 for x in self._window if not x) / len(self._window)

    # ------------------------------------------------------------------
    # Concurrency recommendation
    # ------------------------------------------------------------------

    def get_recommended_concurrency(self, max_concurrency: int = 10) -> int:
        """Return the recommended upload concurrency for the current state.

        * CLOSED: full *max_concurrency*
        * OPEN: ``max(3, max_concurrency // 2)``
        * HALF_OPEN: starts at ``max(3, max_concurrency // 2)`` and
          increases by +1 every *recovery_increment* successes, up to
          *max_concurrency*.
        """
        current = self.state  # triggers OPEN -> HALF_OPEN check

        if current == CircuitState.CLOSED:
            return max_concurrency

        base = max(3, max_concurrency // 2)

        if current == CircuitState.OPEN:
            return base

        # HALF_OPEN: gradual ramp
        bonus = self._success_since_recovery // self._recovery_increment
        return min(base + bonus, max_concurrency)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _should_trip(self) -> bool:
        """Check whether the breaker should transition to OPEN."""
        return (
            self.error_rate > self._error_threshold
            or self._consecutive_429s >= self._consecutive_threshold
        )

    def _trip(self) -> None:
        """Transition to OPEN state."""
        prev = self._state
        self._state = CircuitState.OPEN
        self._opened_at = time.time()
        self._success_since_recovery = 0
        logger.warning(
            "Circuit breaker %s -> OPEN (error_rate=%.2f, consecutive_429s=%d)",
            prev,
            self.error_rate,
            self._consecutive_429s,
        )
