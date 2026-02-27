"""Tests for shared RxPY operators (_operators.py).

Tests the make_retrying_observable operator that replaces tenacity @retry:
- Succeeds on first try
- Retries on transient error then succeeds
- Raises after max retries exhausted
"""

from __future__ import annotations

import asyncio

import pytest

from objlib.upload._operators import make_retrying_observable, subscribe_awaitable


@pytest.fixture
def event_loop():
    """Create a fresh event loop for each test."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestMakeRetryingObservable:
    """Tests for make_retrying_observable operator."""

    def test_succeeds_on_first_try(self, event_loop):
        """Observable emits result when fn succeeds immediately."""

        async def success_fn():
            return 42

        async def run():
            obs = make_retrying_observable(success_fn, max_retries=3, base_delay=0.01)
            result = await subscribe_awaitable(obs)
            return result

        result = event_loop.run_until_complete(run())
        assert result == 42

    def test_retries_on_transient_error(self, event_loop):
        """Observable retries and emits result after transient failures."""
        call_count = 0

        async def flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError(f"Transient error (attempt {call_count})")
            return "recovered"

        async def run():
            obs = make_retrying_observable(flaky_fn, max_retries=3, base_delay=0.01)
            result = await subscribe_awaitable(obs)
            return result

        result = event_loop.run_until_complete(run())
        assert result == "recovered"
        assert call_count == 3  # Failed twice, succeeded on third

    def test_raises_after_max_retries(self, event_loop):
        """Observable raises last exception after all retries exhausted."""
        call_count = 0

        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError(f"Permanent failure (attempt {call_count})")

        async def run():
            obs = make_retrying_observable(
                always_fails, max_retries=2, base_delay=0.01
            )
            return await subscribe_awaitable(obs)

        with pytest.raises(ValueError, match="Permanent failure \\(attempt 3\\)"):
            event_loop.run_until_complete(run())

        assert call_count == 3  # 1 initial + 2 retries

    def test_exponential_backoff_timing(self, event_loop):
        """Verify that retries use exponential backoff (at least approximate)."""
        import time

        timestamps: list[float] = []

        async def timed_fail():
            timestamps.append(time.monotonic())
            raise RuntimeError("fail")

        async def run():
            obs = make_retrying_observable(
                timed_fail, max_retries=2, base_delay=0.05
            )
            return await subscribe_awaitable(obs)

        with pytest.raises(RuntimeError):
            event_loop.run_until_complete(run())

        assert len(timestamps) == 3
        # First retry delay: ~0.05s (base_delay * 2^0)
        # Second retry delay: ~0.10s (base_delay * 2^1)
        gap1 = timestamps[1] - timestamps[0]
        gap2 = timestamps[2] - timestamps[1]
        assert gap1 >= 0.04  # Allow some timing tolerance
        assert gap2 >= 0.08  # Second gap should be ~2x first


class TestSubscribeAwaitable:
    """Tests for subscribe_awaitable helper."""

    def test_returns_single_value(self, event_loop):
        """subscribe_awaitable returns the emitted value."""
        import rx

        async def run():
            obs = rx.of(99)
            return await subscribe_awaitable(obs)

        result = event_loop.run_until_complete(run())
        assert result == 99

    def test_propagates_error(self, event_loop):
        """subscribe_awaitable propagates observable errors."""
        import rx

        async def run():
            obs = rx.throw(RuntimeError("boom"))
            return await subscribe_awaitable(obs)

        with pytest.raises(RuntimeError, match="boom"):
            event_loop.run_until_complete(run())
