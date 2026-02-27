# Phase 17: RxPY Reactive Observable Pipeline for TUI Event Streams - Research

**Researched:** 2026-02-26
**Domain:** RxPY (reactivex v4) + Textual TUI integration, asyncio event loop bridging, reactive observable patterns
**Confidence:** HIGH

## Summary

Phase 17 replaces three manual async patterns in the Textual TUI (debounce timer + generation counter, `@work(exclusive=True)` stale cancellation, and scattered filter-refire logic) with a unified RxPY observable pipeline. All key APIs have been verified by running actual code against the installed packages: `reactivex==4.1.0` and `textual==8.0.0`.

The critical technical challenge is bridging RxPY's synchronous disposal model to asyncio's task cancellation. The `defer_task()` wrapper pattern has been validated -- `switch_map` correctly cancels the previous inner observable's `asyncio.Task` when a new value arrives, which satisfies UAT invariant 3 (stale cancellation). All other patterns (`BehaviorSubject` + `combine_latest`, `merge` + `distinct_until_changed`, `catch` inside `switch_map`) have been tested and confirmed working.

The project has a comprehensive existing test suite in `tests/test_tui.py` (800+ lines) using Textual's `run_test()` + `Pilot` API, which provides a direct template for the Phase 17 UAT harness. `reactivex` is NOT currently in `pyproject.toml` and must be added.

**Primary recommendation:** Follow the CONTEXT.md architecture exactly. All locked decisions have been verified as technically sound. The only open behavioral question is history navigation -- current code DOES start debounce timers on Up/Down arrow (confirmed via code analysis), but they are typically cancelled by subsequent Enter presses. The pre-UAT baseline must capture this precisely.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
1. **reactivex v4** package (not `rx` v3) -- `import reactivex as rx`, `from reactivex import operators as ops`
2. **AsyncIOScheduler** (standard, not ThreadSafe) -- constructed in `on_mount` via `asyncio.get_running_loop()`
3. **Custom `defer_task()` wrapper** for switch_map -- required to cancel asyncio.Task on dispose (RxPY disposal alone does not cancel tasks)
4. **BehaviorSubject(FilterSet())** for filter stream -- prevents combine_latest blocking on first search
5. **Two-stream merge + distinct_until_changed** for Enter key -- prevents double-submission
6. **Subject lifecycle**: Subject in `__init__`, subscription in `on_mount`, dispose in `on_unmount`
7. **catch_error inside switch_map inner observable** -- outer pipeline must survive API errors
8. **ObjlibApp owns unified pipeline** -- SearchBar owns input/enter Subjects, ObjlibApp owns filter Subject + wires combine_latest
9. **UAT harness**: Textual `run_test()` + `Pilot` with real-time waits (pilot.pause(0.35) for positive, pilot.pause(0.05) for negative)
10. **History navigation**: verify current behavior in pre-UAT baseline before deciding (may need `_navigating_history` flag)

### Claude's Discretion
- Subscription collection pattern: `list[Disposable]` recommended over `CompositeDisposable`
- UAT timing margins (specific pause durations for positive/negative assertions)
- Internal implementation details of defer_task wrapper

### Deferred Ideas (OUT OF SCOPE)
- RxPY marble testing / TestScheduler (virtual clock) -- real-time UAT only
- Thread-safe scheduler variants
- Database schema changes
- Search service interface changes
</user_constraints>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| reactivex | 4.1.0 | Observable pipeline (debounce, switch_map, combine_latest) | v4 is the current maintained release; v3 has Python 3.12 datetime deprecation issues |
| textual | 8.0.0 (installed) | TUI framework with asyncio event loop | Already the project's TUI framework |
| asyncio | stdlib | Event loop for AsyncIOScheduler | Textual runs on asyncio; no new dependency |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-asyncio | 0.24+ (installed) | Async test support | UAT tests use `async def` with Textual `run_test()` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| reactivex v4 | rx v3 | v3 has Python 3.12 timezone issues; v4 has type annotations |
| AsyncIOScheduler | AsyncIOThreadSafeScheduler | ThreadSafe only needed for cross-thread Subject emissions; adds overhead |
| list[Disposable] | CompositeDisposable | CompositeDisposable is a single class; list is more Pythonic for 1-2 subscriptions |

**Installation:**
```bash
pip install reactivex
# Also add to pyproject.toml dependencies:
# "reactivex>=4.0",
```

**IMPORTANT:** `reactivex` is NOT currently in `pyproject.toml`. The `rx` v3 package (Rx 3.2.0) is installed globally but not declared as a project dependency. Phase 17 must add `reactivex>=4.0` to `pyproject.toml` `[project.dependencies]`.

---

## Architecture Patterns

### Recommended Project Structure
```
src/objlib/tui/
  app.py              # ObjlibApp -- owns pipeline, filter_subject, subscriptions
  rx_pipeline.py      # NEW: defer_task(), search_observable(), pipeline factory
  widgets/
    search_bar.py     # SearchBar -- owns input_subject, enter_subject (exposes as properties)
    filter_panel.py   # FilterPanel -- posts FilterChanged (unchanged)
```

### Pattern 1: defer_task() -- Bridge asyncio.Task to RxPY Observable
**What:** Creates an Observable from an async coroutine factory. On subscribe, launches an `asyncio.Task`. On dispose (from `switch_map` unsubscription), cancels the task.
**When to use:** Every time an RxPY pipeline needs to execute async work that must be cancellable.
**Example:**
```python
# Source: Verified against reactivex 4.1.0 + asyncio on Python 3.13
import asyncio
import reactivex as rx
from reactivex.disposable import Disposable

def defer_task(coro_factory, loop=None):
    """Create an Observable that wraps an asyncio.Task.

    On subscribe: creates a Task from coro_factory().
    On dispose: cancels the Task (asyncio.Task.cancel()).
    CancelledError is silently absorbed -- not propagated as on_error.

    Args:
        coro_factory: Zero-arg callable returning a coroutine.
        loop: Event loop for create_task. Uses running loop if None.
    """
    def subscribe(observer, scheduler=None):
        _loop = loop or asyncio.get_running_loop()
        task = _loop.create_task(coro_factory())

        def on_done(t):
            try:
                if t.cancelled():
                    return  # Intentional cancellation -- silent
                exc = t.exception()
                if exc:
                    observer.on_error(exc)
                else:
                    observer.on_next(t.result())
                    observer.on_completed()
            except asyncio.CancelledError:
                pass  # Race condition safety

        task.add_done_callback(on_done)
        return Disposable(lambda: task.cancel() if not task.done() else None)

    return rx.create(subscribe)
```

**Verified behavior:** When `switch_map` receives a new value, it disposes the previous inner subscription, which calls `task.cancel()`. The cancelled task's `on_done` callback sees `t.cancelled() == True` and returns silently. The new task runs to completion. Tested with reactivex 4.1.0 -- only the latest task's result is emitted.

### Pattern 2: Two-Stream Merge with distinct_until_changed
**What:** Separates debounced keystroke events from immediate Enter events, then deduplicates.
**When to use:** Any UI input where both "live search" (debounced typing) and "submit" (Enter) coexist.
**Example:**
```python
# Source: Verified against reactivex 4.1.0
from reactivex import operators as ops

# In ObjlibApp.on_mount:
scheduler = AsyncIOScheduler(asyncio.get_running_loop())
search_bar = self.query_one(SearchBar)

query_stream = rx.merge(
    search_bar.input_subject.pipe(ops.debounce(0.3, scheduler=scheduler)),
    search_bar.enter_subject
).pipe(ops.distinct_until_changed())
```

**Verified behavior:** When user types "hello" and hits Enter, the enter_subject emits "hello" synchronously. 300ms later, the debounce fires "hello" from input_subject. `distinct_until_changed` suppresses the duplicate. If the user types "helloX" after Enter (within 300ms), debounce fires "helloX" which passes through since it differs from "hello".

### Pattern 3: BehaviorSubject + combine_latest for Filter Integration
**What:** Uses BehaviorSubject's initial value to prevent combine_latest from blocking.
**When to use:** When one stream (filters) has a meaningful default state.
**Example:**
```python
# Source: Verified against reactivex 4.1.0
from reactivex.subject import BehaviorSubject

filter_subject = BehaviorSubject(FilterSet())  # Initial empty filter

combined = rx.combine_latest(
    query_stream,     # Only emits after user types/enters
    filter_subject    # Already has a value -> combine_latest emits immediately
)
```

**Verified behavior:** First query emission immediately combines with the initial `FilterSet()` value. Filter changes re-emit with the latest query. Both directions work without blocking.

### Pattern 4: catch Inside switch_map for Error Resilience
**What:** Places error handling inside the inner observable so the outer pipeline survives API errors.
**When to use:** Any pipeline where the inner operation can fail (network calls, API errors).
**Example:**
```python
# Source: Verified against reactivex 4.1.0
combined.pipe(
    ops.switch_map(
        lambda pair: defer_task(
            lambda: search_service.search(pair[0], filters=pair[1])
        ).pipe(
            ops.catch(lambda err, source: handle_error_and_return_empty(err))
        )
    )
)

def handle_error_and_return_empty(err):
    # Log error, show notification, reset is_searching
    return rx.empty()  # Completes without emitting -- pipeline continues
```

**Verified behavior:** After an API error, the outer pipeline remains active. The next query triggers a new search normally. Tested with 3 sequential emissions: good -> error -> good. Both good results arrived; error was caught without terminating the pipeline.

### Pattern 5: Full Pipeline Assembly in ObjlibApp.on_mount
**What:** Wires all streams together in the App's `on_mount` lifecycle hook.
**Example:**
```python
# Source: Architecture from CONTEXT.md, verified API signatures
async def on_mount(self) -> None:
    # ... existing mount logic ...

    loop = asyncio.get_running_loop()  # Verified: available in on_mount
    scheduler = AsyncIOScheduler(loop)
    search_bar = self.query_one(SearchBar)

    query_stream = rx.merge(
        search_bar.input_subject.pipe(ops.debounce(0.3, scheduler=scheduler)),
        search_bar.enter_subject
    ).pipe(ops.distinct_until_changed())

    pipeline = rx.combine_latest(
        query_stream,
        self._filter_subject
    ).pipe(
        ops.switch_map(lambda pair: self._make_search_observable(pair[0], pair[1]))
    )

    self._rx_subscription = pipeline.subscribe(
        on_next=self._on_search_result,
        on_error=self._on_pipeline_error,  # Should never fire if catch is correct
    )
```

### Anti-Patterns to Avoid
- **Passing `scheduler=` to `subscribe()`:** This causes subscriber callbacks to be scheduled asynchronously via the event loop instead of running synchronously. Enter-key emissions would not appear until the next event loop tick, breaking immediate-fire behavior. Only pass `scheduler` to `debounce()` and other time-based operators.
- **Placing `catch` outside `switch_map`:** An error propagating to the outer pipeline terminates the entire subscription. All subsequent searches would silently fail. Always place `catch` inside the inner observable.
- **Using `rx.create` with `asyncio.create_task(run())` inside subscribe:** The CLARIFICATIONS-ANSWERED.md template shows creating a second task (`asyncio.create_task(run())`) inside the subscribe callback. This is unnecessary and adds a layer of indirection. The `add_done_callback` pattern (shown in Pattern 1) is simpler and handles all cases.
- **Forgetting `ops.distinct_until_changed()`:** Without it, Enter fires "foo", then debounce fires "foo" 300ms later = double search. This is a subtle bug that only manifests under specific timing.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Debounce timer management | Custom `set_timer()` + generation counter | `ops.debounce(0.3, scheduler)` | RxPY handles timer cancellation, rescheduling, and cleanup automatically |
| Stale result cancellation | `@work(exclusive=True)` + manual flag | `ops.switch_map()` + `defer_task()` | switch_map is the standard reactive pattern for latest-wins semantics |
| Multi-stream combination | Two separate message handlers checking shared state | `rx.combine_latest()` | combine_latest ensures both streams are considered on every emission |
| Double-fire prevention | Generation counter (`_debounce_gen`) | `ops.distinct_until_changed()` | Standard operator, no custom state needed |
| Subscription cleanup | Manual timer.stop() calls | `Disposable.dispose()` in `on_unmount` | Single cleanup point for all subscriptions |

**Key insight:** The current codebase has ~60 lines of manual debounce/generation/cancellation logic spread across `SearchBar` and `ObjlibApp`. The RxPY pipeline replaces this with ~15 lines of declarative pipeline code plus the `defer_task` wrapper (~20 lines). The wrapper is the only custom code; everything else is standard operators.

---

## Common Pitfalls

### Pitfall 1: AsyncIOScheduler Created Before Event Loop Runs
**What goes wrong:** `AsyncIOScheduler(asyncio.get_running_loop())` raises `RuntimeError: no running event loop` if called in `__init__`.
**Why it happens:** Textual's `__init__` runs before the asyncio event loop starts. `get_running_loop()` requires a running loop.
**How to avoid:** Create `AsyncIOScheduler` in `on_mount` (which is an async method running inside the event loop).
**Warning signs:** `RuntimeError: no running event loop` on app startup.
**Verified:** `asyncio.get_running_loop()` returns a valid, running `_UnixSelectorEventLoop` inside Textual's `on_mount`.

### Pitfall 2: subscribe(scheduler=...) Breaks Synchronous Emission
**What goes wrong:** Enter key emissions don't appear immediately; debounce dedup fails; timing-sensitive UATs become flaky.
**Why it happens:** Passing `scheduler=` to `subscribe()` causes the observer's `on_next` callback to be scheduled via `loop.call_later(0, callback)` instead of running synchronously. The callback runs on the next event loop iteration, not inline with `subject.on_next()`.
**How to avoid:** Only pass `scheduler` to time-based operators (`debounce`, `delay`, `interval`). Never pass it to `subscribe()`.
**Warning signs:** `enter_subject.on_next("foo")` doesn't immediately produce results; tests need unexpected `await asyncio.sleep()` calls.
**Verified:** Without `scheduler` on subscribe, `subject.on_next()` delivers to the observer synchronously in the same call stack.

### Pitfall 3: CancelledError Propagating as Pipeline Error
**What goes wrong:** After `switch_map` cancels a stale task, `CancelledError` propagates through `observer.on_error()`, terminating the outer pipeline.
**Why it happens:** `asyncio.Task.cancel()` raises `CancelledError` in the coroutine. If the `defer_task` wrapper doesn't catch it, it becomes an error event on the observable.
**How to avoid:** The `on_done` callback in `defer_task` must check `t.cancelled()` before checking `t.exception()`. If cancelled, return silently without calling any observer methods.
**Warning signs:** Pipeline stops working after the first stale-query cancellation.
**Verified:** Pattern 1's `on_done` callback correctly handles the `cancelled()` -> `exception()` -> `result()` priority.

### Pitfall 4: History Navigation Triggers Unintended Searches
**What goes wrong:** Pressing Up arrow cycles through history entries, each setting `self.value`, each triggering `on_input_changed`, each emitting to `_input_subject`, each starting a debounce timer.
**Why it happens:** Textual's `Input.value` setter fires the `Changed` event regardless of whether the change was programmatic or from user typing.
**How to avoid:** Either (a) accept this behavior (debounce acts as settle timer -- if user pauses 300ms on a history entry, search fires), or (b) set a `_navigating_history` flag in `on_key` handler for Up/Down arrows that suppresses `_input_subject.on_next()` in `on_input_changed`.
**Warning signs:** Rapid Up arrow presses produce debounced searches for intermediate history entries.
**Current behavior analysis:** The existing code DOES start debounce timers on history navigation (confirmed by code analysis: `self.value = ...` triggers `on_input_changed` which calls `set_timer`). However, when the user presses Enter to select a history entry, the Enter handler bumps `_debounce_gen`, which causes the pending timer's callback to see a stale generation and silently drop. In practice, history navigation almost never fires a search UNLESS the user pauses 300ms+ on an entry without pressing Enter. **The pre-UAT baseline must measure this precisely.**

### Pitfall 5: Empty Query Handling
**What goes wrong:** Empty string passes through `distinct_until_changed` and reaches `switch_map`, which calls the search API with an empty query.
**Why it happens:** Empty string `""` is a valid value that `distinct_until_changed` passes through (it differs from the previous non-empty query).
**How to avoid:** Handle empty queries in the `switch_map` lambda: if `pair[0]` is empty, clear results immediately and return `rx.empty()` instead of calling the API. OR use `ops.filter(lambda pair: bool(pair[0]))` before `switch_map` and handle the empty case separately.
**Warning signs:** API called with empty query string; or empty query clears results with a 300ms delay instead of immediately.
**Current behavior:** The existing `on_search_requested` handles empty query specially (clears immediately, no API call). The RxPY pipeline must replicate this.

### Pitfall 6: Forgetting to Dispose Subscriptions
**What goes wrong:** After the app exits (or during hot-reload in development), subscriptions continue to hold references to widgets, causing errors when callbacks try to update disposed widgets.
**Why it happens:** RxPY subscriptions are active until explicitly disposed. Unlike Textual's `@work`, they don't auto-cancel on app exit.
**How to avoid:** Store all subscriptions in `self._rx_subscription` (or a list) and call `.dispose()` in `on_unmount`.
**Warning signs:** Errors referencing widgets "after unmount" or "no longer in DOM" during app shutdown.
**Verified:** `on_unmount` handler is called when the app exits via `run_test()` context manager.

---

## Code Examples

### Complete defer_task Wrapper
```python
# Source: Verified against reactivex 4.1.0 + Python 3.13 asyncio
import asyncio
import reactivex as rx
from reactivex.disposable import Disposable


def defer_task(coro_factory, loop=None):
    """Bridge an async coroutine to an RxPY Observable with task cancellation.

    Creates an asyncio.Task on subscribe. Cancels the task on dispose.
    This ensures switch_map properly cancels stale async operations.

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
```

### SearchBar Subject Properties
```python
# Source: Based on existing search_bar.py structure + CONTEXT.md decisions
from reactivex.subject import Subject


class SearchBar(Input):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Search the library... (Ctrl+F to focus)",
            id="search-bar",
        )
        self._input_subject = Subject()   # Emits every keystroke value (str)
        self._enter_subject = Subject()   # Emits input value on Enter key (str)
        self._history: list[str] = []
        self._history_index: int = -1

    @property
    def input_subject(self) -> Subject:
        return self._input_subject

    @property
    def enter_subject(self) -> Subject:
        return self._enter_subject

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input is not self:
            return
        query = event.value.strip()
        self._input_subject.on_next(query)

    def on_key(self, event) -> None:
        if event.key == "enter":
            query = self.value.strip()
            if query:
                self._enter_subject.on_next(query)
                # History recording
                if not self._history or self._history[-1] != query:
                    self._history.append(query)
                self._history_index = -1
            event.prevent_default()
        elif event.key == "up" and self._history:
            # ... existing history logic ...
            pass
        elif event.key == "down" and self._history_index >= 0:
            # ... existing history logic ...
            pass
```

### ObjlibApp Pipeline Wiring
```python
# Source: CONTEXT.md architecture + verified API signatures
import asyncio
import reactivex as rx
from reactivex import operators as ops
from reactivex.subject import BehaviorSubject
from reactivex.scheduler.eventloop import AsyncIOScheduler


class ObjlibApp(App):
    def __init__(self, search_service=None, **kwargs):
        super().__init__()
        self.search_service = search_service
        self._filter_subject = BehaviorSubject(FilterSet())
        self._rx_subscription = None  # Set in on_mount

    async def on_mount(self) -> None:
        # ... existing mount logic ...

        if self.search_service is not None:
            loop = asyncio.get_running_loop()
            scheduler = AsyncIOScheduler(loop)
            search_bar = self.query_one(SearchBar)

            query_stream = rx.merge(
                search_bar.input_subject.pipe(
                    ops.debounce(0.3, scheduler=scheduler)
                ),
                search_bar.enter_subject,
            ).pipe(ops.distinct_until_changed())

            pipeline = rx.combine_latest(
                query_stream,
                self._filter_subject,
            ).pipe(
                ops.switch_map(lambda pair: self._search_observable(pair[0], pair[1]))
            )

            self._rx_subscription = pipeline.subscribe(
                on_next=self._on_search_result,
            )

    def _search_observable(self, query, filter_set):
        """Create observable for a single search, with error handling."""
        if not query:
            # Empty query: clear results immediately
            self._clear_results()
            return rx.empty()

        self.is_searching = True
        filters = None if filter_set.is_empty() else filter_set.to_filter_strings()

        return defer_task(
            lambda: self.search_service.search(query, filters=filters, top_k=20)
        ).pipe(
            ops.catch(lambda err, source: self._handle_search_error(err))
        )

    def on_filter_changed(self, event) -> None:
        self.active_filters = event.filters
        self._filter_subject.on_next(event.filters)

    def on_unmount(self) -> None:
        if self._rx_subscription:
            self._rx_subscription.dispose()
```

### UAT Test Template (from existing test_tui.py patterns)
```python
# Source: Based on tests/test_tui.py existing patterns
from unittest.mock import AsyncMock
import pytest
from objlib.tui.app import ObjlibApp
from objlib.tui.widgets import SearchBar


async def test_debounce_fires_once_after_300ms(mock_search_service):
    """UAT Invariant 1: rapid typing fires exactly 1 search after 300ms pause."""
    app = ObjlibApp(search_service=mock_search_service)
    async with app.run_test(size=(120, 40)) as pilot:
        search_bar = app.query_one(SearchBar)
        search_bar.focus()

        # Type rapidly
        await pilot.press("h", "e", "l", "l", "o")

        # Before debounce: no search yet
        await pilot.pause(0.05)
        mock_search_service.search.assert_not_called()

        # After debounce: exactly 1 search
        await pilot.pause(0.35)
        assert mock_search_service.search.call_count == 1
        assert mock_search_service.search.call_args[0][0] == "hello"


async def test_enter_fires_immediately(mock_search_service):
    """UAT Invariant 2: Enter fires immediately, cancels debounce."""
    app = ObjlibApp(search_service=mock_search_service)
    async with app.run_test(size=(120, 40)) as pilot:
        search_bar = app.query_one(SearchBar)
        search_bar.focus()

        await pilot.press("h", "e", "l", "l", "o")
        await pilot.press("enter")

        # Immediate check: search should have fired
        await pilot.pause(0.05)
        assert mock_search_service.search.call_count == 1

        # After debounce would have fired: still only 1 (deduped)
        await pilot.pause(0.4)
        assert mock_search_service.search.call_count == 1


async def test_error_containment(mock_search_service):
    """UAT Invariant 7: API error shows notification, pipeline continues."""
    mock_search_service.search.side_effect = [
        Exception("API failure"),
        AsyncMock(return_value=SearchResult(...))(),  # Second call succeeds
    ]
    app = ObjlibApp(search_service=mock_search_service)
    async with app.run_test(size=(120, 40), notifications=True) as pilot:
        search_bar = app.query_one(SearchBar)
        search_bar.focus()

        # First search: triggers error
        await pilot.press("f", "a", "i", "l")
        await pilot.pause(0.5)
        assert app.is_searching is False  # Reset after error

        # Check notification was posted
        error_notifs = [n for n in app._notifications if n.severity == "error"]
        assert len(error_notifs) >= 1

        # Second search: should work
        # ... clear and type new query ...
```

### message_hook for Capturing Messages in UATs
```python
# Source: Verified against textual 8.0.0
from objlib.tui.messages import SearchRequested

async def test_with_message_hook(mock_search_service):
    """Use message_hook to capture SearchRequested messages."""
    captured_searches = []

    def hook(msg):
        if isinstance(msg, SearchRequested):
            captured_searches.append(msg.query)

    app = ObjlibApp(search_service=mock_search_service)
    async with app.run_test(message_hook=hook, size=(120, 40)) as pilot:
        # ... test actions ...
        pass

    assert len(captured_searches) == expected_count
```

---

## State of the Art

| Old Approach (Current Code) | Current Approach (RxPY) | When Changed | Impact |
|---------------------------|----------------------|------------|--------|
| `set_timer()` + `_debounce_gen` counter | `ops.debounce(0.3, scheduler)` | RxPY standard since v1 | Eliminates ~20 lines of timer management |
| `@work(exclusive=True)` | `ops.switch_map()` + `defer_task()` | Reactive pattern, not version-dependent | Explicit cancellation instead of Textual worker magic |
| `on_filter_changed` calling `_run_search` | `rx.combine_latest(query$, filter$)` | Reactive pattern | Both streams unified in one pipeline |
| `_debounce_gen` counter for Enter dedup | `ops.distinct_until_changed()` | Reactive pattern | Standard operator replaces custom counter |

**Deprecated/outdated:**
- `rx` v3 package: Has Python 3.12 timezone deprecation issues. Use `reactivex` v4+ instead.
- `ops.catch_error`: Does not exist in reactivex v4. The operator is named `ops.catch`.
- `ops.filter_`: Does not exist in reactivex v4. The operator is named `ops.filter`.

---

## Textual-Specific Integration Details

### asyncio.get_running_loop() in on_mount
**Verified:** Returns a valid, running `_UnixSelectorEventLoop` inside Textual 8.0's `on_mount`. Loop is running (`loop.is_running() == True`).

### Textual @work Internals
**Verified:** Textual's `@work` decorator creates an `asyncio.Task` via `asyncio.create_task(self._run(app))`. The `Worker.cancel()` method calls `self._task.cancel()`. This is exactly what `defer_task()` replicates -- the RxPY wrapper is a direct replacement for the cancellation semantics of `@work(exclusive=True)`.

### Pilot API for UATs
| Method | Signature | Use Case |
|--------|-----------|----------|
| `pilot.press(*keys)` | `async def press(self, *keys: str)` | Simulate individual key presses, including character typing |
| `pilot.pause(delay)` | `async def pause(self, delay: float = None)` | Wait for specified time (real-time); `None` = wait for CPU idle |
| `pilot.click(widget)` | `async def click(self, widget=None, ...)` | Click a widget |
| `pilot.resize_terminal(w, h)` | `async def resize_terminal(self, w, h)` | Change terminal size |

**Key Pilot behaviors verified:**
- `pilot.press("h", "e", "l", "l", "o")` types "hello" into a focused Input widget
- `pilot.press("enter")` sends Enter key
- `pilot.press("up")` sends Up arrow key
- `pilot.pause(0.35)` waits 350ms real time (adequate for 300ms debounce)
- `pilot.pause(0.05)` waits 50ms (less than debounce -- for negative assertions)

### run_test Parameters
```python
app.run_test(
    size=(120, 40),           # Terminal dimensions
    notifications=True,       # Enable notification capture (app._notifications)
    message_hook=hook_fn,     # Callback for every message at every pump
)
```

### Notification Capture
**Verified:** With `notifications=True`, `app._notifications` contains `Notification` objects with `.severity` and `.message` attributes. This enables testing UAT invariant 7 (error containment notification).

---

## Existing Test Infrastructure

The project has `tests/test_tui.py` with 800+ lines of Textual UATs. Key patterns:

### Fixtures (template for Phase 17 UATs)
```python
@pytest.fixture
def mock_search_service(sample_citations) -> AsyncMock:
    svc = AsyncMock()
    svc.search.return_value = SearchResult(
        response_text="...", citations=sample_citations,
        query="test query", metadata_filter=None,
    )
    return svc

def make_app(search_service=None, library_service=None, session_service=None):
    return ObjlibApp(
        search_service=search_service,
        library_service=library_service,
        session_service=session_service,
    )
```

### Test Pattern (template for Phase 17 UATs)
```python
async def test_search_triggers_service_call(mock_search_service, mock_library_service):
    app = make_app(search_service=mock_search_service, library_service=mock_library_service)
    async with app.run_test(size=(120, 40)) as pilot:
        app.post_message(SearchRequested(query="virtue"))
        await pilot.pause(0.5)
        mock_search_service.search.assert_called_once()
```

**Note:** Existing tests use `app.post_message(SearchRequested(...))` to bypass the SearchBar entirely. Phase 17 UATs must use `pilot.press()` to drive the full pipeline through the SearchBar Subjects.

### pytest Configuration
```toml
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
asyncio_mode = "auto"  # No @pytest.mark.asyncio needed
```

---

## Critical Behavioral Analysis: History Navigation

### Current Code Path (search_bar.py lines 111-137)
1. User presses Up arrow
2. `on_key` sets `self.value = self._history[self._history_index]`
3. Setting `self.value` triggers `on_input_changed` (verified: Textual fires Changed on programmatic value set)
4. `on_input_changed` cancels any existing debounce timer, bumps `_debounce_gen`, starts new timer
5. If user presses Enter within 300ms, Enter handler bumps `_debounce_gen` again, making the timer stale
6. If user does NOT press Enter within 300ms, the timer fires and calls `_fire_search`

### Implication for RxPY Pipeline
- History navigation WILL emit to `_input_subject` via `on_input_changed`
- The debounce operator handles the "settle timer" behavior automatically
- If the user rapidly cycles through history (< 300ms per entry), debounce only fires for the last entry
- If the user pauses 300ms+ on an entry, debounce fires a search
- Enter after history navigation fires immediately via `_enter_subject`; `distinct_until_changed` may suppress the subsequent debounce if the value matches

**The pre-UAT baseline (plan 17-02) must capture the exact behavior for each scenario:**
1. Up arrow x3, then Enter -- how many searches fire?
2. Up arrow, wait 500ms -- does a search fire?
3. Up arrow x5 rapidly, wait 500ms -- one search or five?

---

## Open Questions

1. **History navigation flag decision**
   - What we know: Current code starts debounce timers on history navigation, but they are almost always cancelled by subsequent Enter.
   - What's unclear: Whether the "pause 300ms on history entry triggers search" behavior is intentional or accidental. Pre-UAT baseline must determine.
   - Recommendation: Capture pre-UAT baseline first. If history-nav searches never fire in practice (because users always press Enter), no flag needed. If they do fire, replicate exactly.

2. **Widget remounting**
   - What we know: SearchBar is in the permanent compose tree and is not dynamically mounted/unmounted.
   - What's unclear: Whether any edge case (screen switch, command palette) causes remounting that would re-run `on_mount` and duplicate subscriptions.
   - Recommendation: Guard `on_mount` with `if self._rx_subscription is not None: return` or dispose-before-resubscribe.

3. **Empty query timing**
   - What we know: Current code fires `SearchRequested(query="")` immediately (no debounce) when input is cleared. The RxPY pipeline's debounce would add a 300ms delay.
   - What's unclear: Whether the 300ms delay for empty-query clearing is acceptable.
   - Recommendation: Handle empty query as a special case: in `on_input_changed`, if query is empty, call the clear handler directly instead of emitting to `_input_subject`. OR emit empty string and handle in `switch_map` lambda.

---

## Sources

### Primary (HIGH confidence -- direct code execution)
- `reactivex==4.1.0` installed and all APIs verified by running Python code
- `textual==8.0.0` installed; `App.run_test()`, `Pilot`, `on_mount` lifecycle verified
- `src/objlib/tui/app.py` (697 lines) -- current ObjlibApp implementation read in full
- `src/objlib/tui/widgets/search_bar.py` (157 lines) -- current SearchBar implementation read in full
- `src/objlib/tui/widgets/filter_panel.py` (111 lines) -- current FilterPanel implementation read in full
- `src/objlib/tui/messages.py` (66 lines) -- message types read in full
- `src/objlib/tui/state.py` (54 lines) -- FilterSet dataclass read in full
- `tests/test_tui.py` (800+ lines) -- existing test patterns read in full
- `pyproject.toml` -- dependency list and test config read in full
- `Worker` class source inspected for `asyncio.create_task` and `task.cancel()` usage

### Secondary (HIGH confidence -- verified by test execution)
- `defer_task()` pattern: switch_map cancellation verified (only latest task's result emitted)
- `BehaviorSubject + combine_latest`: immediate emission verified
- `merge + distinct_until_changed`: deduplication verified
- `catch inside switch_map`: error resilience verified (pipeline survives errors)
- `asyncio.get_running_loop()` in `on_mount`: verified returns running loop
- `pilot.press()` for character typing: verified
- `app._notifications` capture: verified with `notifications=True`
- `message_hook` for message interception: verified
- `on_unmount` lifecycle: verified it fires on app exit

### Tertiary (MEDIUM confidence -- code analysis without execution)
- History navigation behavior: analyzed from code (not tested in running TUI with full service stack)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- reactivex 4.1.0 installed and all imports verified
- Architecture: HIGH -- all patterns tested with actual code execution
- Pitfalls: HIGH -- each pitfall discovered through testing (not theoretical)
- UAT infrastructure: HIGH -- existing test suite provides direct templates
- History navigation: MEDIUM -- code analysis only, not tested with real search service

**Research date:** 2026-02-26
**Valid until:** 2026-03-26 (stable libraries, no breaking changes expected)
