"""Upload pipeline primitives for the Gemini File Search API.

Public API
----------
.. autoclass:: GeminiFileSearchClient
.. autoclass:: RollingWindowCircuitBreaker
.. autoclass:: AdaptiveRateLimiter
.. autoclass:: RateLimiterConfig
.. autoclass:: CircuitState
"""

from objlib.upload.circuit_breaker import CircuitState, RollingWindowCircuitBreaker
from objlib.upload.client import (
    GeminiFileSearchClient,
    PermanentError,
    RateLimitError,
    TransientError,
)
from objlib.upload.rate_limiter import AdaptiveRateLimiter, RateLimiterConfig

__all__ = [
    "AdaptiveRateLimiter",
    "CircuitState",
    "GeminiFileSearchClient",
    "PermanentError",
    "RateLimitError",
    "RateLimiterConfig",
    "RollingWindowCircuitBreaker",
    "TransientError",
]
