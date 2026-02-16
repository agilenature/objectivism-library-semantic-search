"""Upload pipeline for the Gemini File Search API.

Public API
----------
.. autoclass:: GeminiFileSearchClient
.. autoclass:: RollingWindowCircuitBreaker
.. autoclass:: AdaptiveRateLimiter
.. autoclass:: RateLimiterConfig
.. autoclass:: CircuitState
.. autoclass:: AsyncUploadStateManager
.. autoclass:: UploadOrchestrator
.. autoclass:: UploadProgressTracker
.. autoclass:: RecoveryManager
.. autoclass:: RecoveryResult
"""

from objlib.upload.circuit_breaker import CircuitState, RollingWindowCircuitBreaker
from objlib.upload.client import (
    GeminiFileSearchClient,
    PermanentError,
    RateLimitError,
    TransientError,
)
from objlib.upload.orchestrator import UploadOrchestrator
from objlib.upload.progress import UploadProgressTracker
from objlib.upload.rate_limiter import AdaptiveRateLimiter, RateLimiterConfig
from objlib.upload.recovery import RecoveryManager, RecoveryResult, RecoveryTimeoutError
from objlib.upload.state import AsyncUploadStateManager

__all__ = [
    "AdaptiveRateLimiter",
    "AsyncUploadStateManager",
    "CircuitState",
    "GeminiFileSearchClient",
    "PermanentError",
    "RateLimitError",
    "RateLimiterConfig",
    "RecoveryManager",
    "RecoveryResult",
    "RecoveryTimeoutError",
    "RollingWindowCircuitBreaker",
    "TransientError",
    "UploadOrchestrator",
    "UploadProgressTracker",
]
