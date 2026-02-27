"""RxPY integration utilities for bridging asyncio tasks to observables.

Provides defer_task() for wrapping async coroutines as cancellable
observables, compatible with reactivex's switch_map operator.
"""

from __future__ import annotations

import asyncio

import reactivex as rx
from reactivex.disposable import Disposable


def defer_task(coro_factory, loop=None):
    """Bridge an async coroutine to an RxPY Observable with task cancellation.

    On subscribe: creates an asyncio.Task from coro_factory().
    On dispose: cancels the Task via asyncio.Task.cancel().
    CancelledError is silently absorbed -- not propagated as on_error.

    This is required because RxPY's subscription disposal does NOT
    automatically cancel asyncio.Tasks. Without this wrapper, switch_map
    would "cancel" the observable subscription but the underlying coroutine
    would continue executing.

    Args:
        coro_factory: Zero-argument callable returning a coroutine object.
        loop: Optional event loop. Defaults to asyncio.get_running_loop().

    Returns:
        Observable that emits exactly one value (the coroutine result)
        then completes, or emits an error if the coroutine raises.
    """

    def subscribe(observer, scheduler=None):
        _loop = loop or asyncio.get_running_loop()
        task = _loop.create_task(coro_factory())

        def on_done(t):
            try:
                if t.cancelled():
                    return  # switch_map cancelled us -- silent
                exc = t.exception()
                if exc:
                    observer.on_error(exc)
                else:
                    observer.on_next(t.result())
                    observer.on_completed()
            except asyncio.CancelledError:
                pass  # Race: task cancelled between checks

        task.add_done_callback(on_done)
        return Disposable(lambda: task.cancel() if not task.done() else None)

    return rx.create(subscribe)
