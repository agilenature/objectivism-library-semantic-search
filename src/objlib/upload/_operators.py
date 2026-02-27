"""Shared RxPY operators for async migration.

Provides reusable RxPY operators used across Tier 1-3 migrations:
- make_retrying_observable: replaces tenacity AsyncRetrying/@retry
- subscribe_awaitable: Future-based subscription for async contexts
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

import rx
from rx.core import Observable
from rx.scheduler.eventloop import AsyncIOScheduler

logger = logging.getLogger(__name__)

T = TypeVar("T")


def make_retrying_observable(
    fn: Callable[[], Awaitable[T]],
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> Observable:
    """Create an observable that retries fn() with exponential backoff.

    Replaces tenacity.AsyncRetrying / @retry patterns.

    Args:
        fn: Async callable (no arguments) to invoke.
        max_retries: Maximum number of retry attempts after the first failure.
        base_delay: Base delay in seconds; doubles each retry (exponential backoff).

    Returns:
        An Observable that emits the result of fn() or raises the last exception
        after max_retries exhausted.
    """

    async def _run() -> T:
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return await fn()
            except Exception as e:
                last_exc = e
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.debug(
                        "Retry %d/%d after %.1fs: %s",
                        attempt + 1,
                        max_retries,
                        delay,
                        e,
                    )
                    await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]

    return rx.from_future(asyncio.ensure_future(_run()))


async def subscribe_awaitable(obs: Observable) -> T:  # type: ignore[type-var]
    """Subscribe to an observable and await its result via a Future.

    This is the Future-based subscription pattern from the 18-01 spike.
    Avoids obs.run() which deadlocks in async contexts.

    Args:
        obs: Observable to subscribe to.

    Returns:
        The value emitted by the observable.

    Raises:
        Exception: If the observable emits an error.
    """
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()

    obs.subscribe(
        on_next=lambda v: future.set_result(v) if not future.done() else None,
        on_error=lambda e: future.set_exception(e) if not future.done() else None,
        on_completed=lambda: future.set_result(None) if not future.done() else None,
        scheduler=AsyncIOScheduler(loop),
    )

    return await future
