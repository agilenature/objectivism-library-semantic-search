"""Exception types for Phase 10 transition atomicity spike.

Reuses Phase 9 exception types and adds Phase 10-specific ones.
"""

from spike.phase9_spike.exceptions import (
    GuardRejectedError,
    StaleTransitionError,
    TransitionNotAllowedError,
)

__all__ = [
    "GuardRejectedError",
    "StaleTransitionError",
    "TransitionNotAllowedError",
]
