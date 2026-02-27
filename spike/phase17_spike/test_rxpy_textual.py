"""Phase 17 HOSTILE Spike: RxPY + Textual Integration Validation.

5 tests validating the core integration assumptions needed before any
production TUI code is modified. Each test produces AFFIRMATIVE evidence
(specific measured values), not merely absence of errors.

All tests use real Textual App + run_test() context to prove the patterns
work inside Textual's asyncio event loop, not just standalone asyncio.

reactivex 4.1.0 imports per locked decision:
  import reactivex as rx
  from reactivex import operators as ops
  from reactivex.scheduler.eventloop import AsyncIOScheduler
  from reactivex.subject import Subject, BehaviorSubject
  from reactivex.disposable import Disposable
"""

from __future__ import annotations

import asyncio

import reactivex as rx
from reactivex import operators as ops
from reactivex.disposable import Disposable
from reactivex.scheduler.eventloop import AsyncIOScheduler
from reactivex.subject import BehaviorSubject, Subject
from textual.app import App, ComposeResult
from textual.widgets import Static


# ---------------------------------------------------------------------------
# Shared: defer_task wrapper (Pattern 1 from RESEARCH.md)
# ---------------------------------------------------------------------------


def defer_task(coro_factory, loop=None):
    """Bridge an async coroutine to an RxPY Observable with task cancellation.

    On subscribe: creates an asyncio.Task from coro_factory().
    On dispose: cancels the Task (asyncio.Task.cancel()).
    CancelledError is silently absorbed -- not propagated as on_error.

    Args:
        coro_factory: Zero-argument callable returning a coroutine object.
        loop: Optional event loop. Defaults to asyncio.get_running_loop().
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


# ---------------------------------------------------------------------------
# Test 1: AsyncIOScheduler + Textual event loop integration
# ---------------------------------------------------------------------------


class SchedulerApp(App):
    """Minimal Textual App for testing AsyncIOScheduler integration."""

    def compose(self) -> ComposeResult:
        yield Static("scheduler test")

    def on_mount(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.scheduler = AsyncIOScheduler(self.loop)
        self.received: list[str] = []
        self.loop_running: bool = self.loop.is_running()
        self.loop_id: int = id(self.loop)

        sub = Subject()
        sub.pipe(
            ops.debounce(0.1, scheduler=self.scheduler),
        ).subscribe(on_next=lambda v: self.received.append(v))

        # Emit a value
        sub.on_next("ping")


async def test_asyncio_scheduler_textual_integration():
    """AsyncIOScheduler integrates with Textual's asyncio loop without conflict.

    AFFIRMATIVE EVIDENCE:
    - loop.is_running() == True
    - loop IDs match (no second loop created)
    - Debounced value received correctly
    """
    app = SchedulerApp()
    async with app.run_test(size=(80, 24)) as pilot:
        # Wait for debounce (100ms) to fire
        await pilot.pause(0.2)

        # Verify the loop from on_mount is the current running loop
        current_loop = asyncio.get_running_loop()
        loop_ids_match = app.loop_id == id(current_loop)

        print(
            f"\n  EVIDENCE 1: loop.is_running()={app.loop_running}, "
            f"loop_ids_match={loop_ids_match}, "
            f"received={app.received}"
        )

        assert app.loop_running is True, "Event loop must be running in on_mount"
        assert loop_ids_match, "Must use the SAME event loop (no second loop)"
        assert app.received == ["ping"], f"Expected ['ping'], got {app.received}"


# ---------------------------------------------------------------------------
# Test 2: switch_map + defer_task() cancels asyncio.Task
# ---------------------------------------------------------------------------


class SwitchMapApp(App):
    """App for testing switch_map + defer_task cancellation."""

    def compose(self) -> ComposeResult:
        yield Static("switch_map test")

    def on_mount(self) -> None:
        self.received: list[str] = []
        self.task_a_cancelled: bool = False

        app_ref = self

        async def slow_search(v):
            try:
                await asyncio.sleep(0.5)
                return v
            except asyncio.CancelledError:
                if v == "A":
                    app_ref.task_a_cancelled = True
                raise

        self.subject = Subject()
        self.subject.pipe(
            ops.switch_map(
                lambda v: defer_task(lambda v=v: slow_search(v))
            ),
        ).subscribe(on_next=lambda x: self.received.append(x))

        # Emit A (starts slow_search("A"))
        self.subject.on_next("A")


async def test_switch_map_cancels_asyncio_task():
    """switch_map + defer_task() cancels the asyncio.Task of the previous inner
    observable when a new value arrives.

    AFFIRMATIVE EVIDENCE:
    - Only "B" received (not ["A", "B"])
    - A's coroutine was cancelled (task_a_cancelled flag set in finally)
    """
    app = SwitchMapApp()
    async with app.run_test(size=(80, 24)) as pilot:
        # Wait 50ms -- A is in-flight but not complete
        await pilot.pause(0.05)

        # Emit B -- should cancel A
        app.subject.on_next("B")

        # Wait for B to complete (500ms sleep + margin)
        await pilot.pause(0.6)

        print(
            f"\n  EVIDENCE 2: received={app.received}, "
            f"task_a_cancelled={app.task_a_cancelled}"
        )

        assert app.received == ["B"], f"Expected ['B'], got {app.received}"
        assert (
            app.task_a_cancelled is True
        ), "A's coroutine must have been cancelled"


# ---------------------------------------------------------------------------
# Test 3: BehaviorSubject + combine_latest emits on first query
# ---------------------------------------------------------------------------


class CombineLatestApp(App):
    """App for testing BehaviorSubject + combine_latest first-emission."""

    def compose(self) -> ComposeResult:
        yield Static("combine_latest test")

    def on_mount(self) -> None:
        self.received: list[tuple] = []

        self.filter_sub = BehaviorSubject("default")
        self.query_sub = Subject()

        rx.combine_latest(
            self.query_sub,
            self.filter_sub,
        ).subscribe(on_next=lambda pair: self.received.append(pair))

        # Emit query WITHOUT emitting on filter
        self.query_sub.on_next("hello")


async def test_behavior_subject_combine_latest_first_emission():
    """BehaviorSubject + combine_latest emits on first query without requiring
    a filter interaction.

    AFFIRMATIVE EVIDENCE:
    - Received exactly [("hello", "default")]
    - The first query triggers emission because BehaviorSubject provides initial value
    """
    app = CombineLatestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.05)

        print(f"\n  EVIDENCE 3: received={app.received}")

        assert app.received == [
            ("hello", "default")
        ], f"Expected [('hello', 'default')], got {app.received}"


# ---------------------------------------------------------------------------
# Test 4: merge + distinct_until_changed prevents double-fire
# ---------------------------------------------------------------------------


class MergeDedupeApp(App):
    """App for testing merge + distinct_until_changed deduplication."""

    def compose(self) -> ComposeResult:
        yield Static("merge dedup test")

    def on_mount(self) -> None:
        self.received: list[str] = []
        loop = asyncio.get_running_loop()
        self.scheduler = AsyncIOScheduler(loop)

        self.typing_sub = Subject()
        self.enter_sub = Subject()

        merged = rx.merge(
            self.typing_sub.pipe(ops.debounce(0.3, scheduler=self.scheduler)),
            self.enter_sub,
        ).pipe(ops.distinct_until_changed())

        merged.subscribe(on_next=lambda v: self.received.append(v))


async def test_merge_distinct_prevents_double_fire():
    """merge + distinct_until_changed prevents double-fire when Enter is pressed
    during debounce window.

    AFFIRMATIVE EVIDENCE:
    - After typing "foo" and pressing Enter: received exactly ["foo"] (not ["foo", "foo"])
    - After entering "bar": received ["foo", "bar"] (distinct value passes through)
    """
    app = MergeDedupeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        # Simulate typing "foo"
        app.typing_sub.on_next("foo")

        # Immediately simulate Enter with same value "foo"
        app.enter_sub.on_next("foo")

        # Wait past debounce (300ms + margin)
        await pilot.pause(0.5)

        print(f"\n  EVIDENCE 4a: received={app.received}")

        assert app.received == [
            "foo"
        ], f"Expected ['foo'] (one emission), got {app.received}"

        # Now emit a distinct value via enter
        app.enter_sub.on_next("bar")
        await pilot.pause(0.05)

        print(f"  EVIDENCE 4b: received={app.received}")

        assert app.received == [
            "foo",
            "bar",
        ], f"Expected ['foo', 'bar'], got {app.received}"


# ---------------------------------------------------------------------------
# Test 5: catch inside switch_map preserves pipeline after error
# ---------------------------------------------------------------------------


class ErrorResilienceApp(App):
    """App for testing catch inside switch_map error resilience."""

    def compose(self) -> ComposeResult:
        yield Static("error resilience test")

    def on_mount(self) -> None:
        self.received: list[str] = []

        async def failing_fn(v):
            await asyncio.sleep(0.01)
            if v == "fail":
                raise RuntimeError("boom")
            return v

        self.subject = Subject()
        self.subject.pipe(
            ops.switch_map(
                lambda v: defer_task(lambda v=v: failing_fn(v)).pipe(
                    ops.catch(
                        lambda err, source: rx.of(f"ERROR:{err}")
                    )
                )
            ),
        ).subscribe(on_next=lambda x: self.received.append(x))


async def test_catch_inside_switch_map_preserves_pipeline():
    """catch inside switch_map inner observable prevents pipeline termination
    on API error.

    AFFIRMATIVE EVIDENCE:
    - Received ["good1", "ERROR:boom", "good2"]
    - Pipeline survived the error and processed the third emission normally
    """
    app = ErrorResilienceApp()
    async with app.run_test(size=(80, 24)) as pilot:
        app.subject.on_next("good1")
        await pilot.pause(0.15)

        app.subject.on_next("fail")
        await pilot.pause(0.15)

        app.subject.on_next("good2")
        await pilot.pause(0.15)

        print(f"\n  EVIDENCE 5: received={app.received}")

        assert app.received == [
            "good1",
            "ERROR:boom",
            "good2",
        ], f"Expected ['good1', 'ERROR:boom', 'good2'], got {app.received}"
