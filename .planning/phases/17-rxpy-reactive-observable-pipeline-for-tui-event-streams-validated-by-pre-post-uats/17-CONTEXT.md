# CONTEXT.md — Phase 17: RxPY Reactive Observable Pipeline for TUI Event Streams

**Generated:** 2026-02-26
**Phase Goal:** Replace the TUI's manual debounce timer, generation-tracking, @work(exclusive=True) pattern, and scattered filter-refire logic with a composable RxPY observable pipeline -- producing identical user-visible behavior, validated by automated UATs executed before and after implementation.
**Synthesis Source:** Multi-provider AI analysis (Gemini Pro Thinking, Perplexity Sonar Deep Research; OpenAI partial)

---

## Overview

Phase 17 replaces three manual async patterns in the Textual TUI with a unified RxPY observable pipeline:

1. `SearchBar._debounce_timer + _debounce_gen + set_timer()` → `Subject | debounce | distinct_until_changed`
2. `@work(exclusive=True)` on `_run_search` → `switch_map` with asyncio task cancellation
3. Two call sites (`on_search_requested` + `on_filter_changed`) → `combine_latest(query$, filters$)`

The gate is behavioral parity: 7 UAT invariants must hold identically before and after the migration. This is NOT a "no crash" gate — it requires affirmative evidence of correct timing, cancellation, and error behavior.

**Confidence markers:**
- ✅ **Consensus** — Both Gemini + Perplexity identified this as critical
- ⚠️ **Recommended** — Strong single-provider finding with clear rationale
- 🔍 **Needs Clarification** — Identified but requires project-specific decision

---

## Gray Areas Identified

### ✅ 1. RxPY Package Version and Import API

**What needs to be decided:** Which RxPY package to install (`rx` vs `reactivex`) and which import API to use.

**Why it's ambiguous:**
RxPY has had two major API breaks. v1 used method chaining. v3 introduced pipe-based operators (`import rx`, `from rx import operators as ops`). v4 renamed the package to `reactivex` (`import reactivex as rx`, `from reactivex import operators as ops`) and added generic type annotations. Python 3.12+ has timezone-naive datetime deprecations that break v3 schedulers. The package name `rx` on PyPI still refers to the old API for many installations.

**Provider synthesis:**
- **Gemini:** Use RxPY v4+ with AsyncIOScheduler; debounce takes seconds not milliseconds (`ops.debounce(0.3)` not `300`)
- **Perplexity:** Confirmed — v4 (`reactivex`) recommended for Python 3.11+; v3 has known Python 3.12 compatibility issues (issue #705); import is `import reactivex as rx` not `import rx`

**Proposed implementation decision:**
Install `reactivex` (v4+). Use `import reactivex as rx` and `from reactivex import operators as ops`. The spike (plan 17-01) must confirm this works with the existing venv and Textual version. If the package is already installed as `rx` v3, upgrade before the spike.

**Open questions:**
- Is `rx` or `reactivex` currently in `pyproject.toml`? Which version?
- Does `reactivex` have `Subject`, `AsyncIOScheduler`, `switch_map`, `combine_latest` all available in the version pinned?

**Confidence:** ✅ Both providers agreed this is a critical pre-spike check

---

### ✅ 2. AsyncIOScheduler + Textual Event Loop Integration

**What needs to be decided:** How to create and wire AsyncIOScheduler to Textual's running event loop without creating a second loop or causing thread violations.

**Why it's ambiguous:**
The HOSTILE spike requirement says this must be confirmed with affirmative evidence. It's not obvious whether `AsyncIOScheduler` takes the current loop at construction time or at subscription time. If constructed in `__init__` before the Textual app is running, it may capture a stale or non-running loop. If constructed after the app starts, it must be done within a running-loop context.

**Provider synthesis:**
- **Gemini:** `AsyncIOScheduler` must be constructed within a running asyncio context. Use `on_mount` (not `__init__`). Store as `self._scheduler`. `AsyncIOScheduler` does NOT create a new loop — it schedules on the provided loop via `loop.call_later`.
- **Perplexity:** Confirmed — `AsyncIOScheduler(loop=asyncio.get_running_loop())` inside `on_mount`. Also: use `AsyncIOThreadSafeScheduler` only if Subject emissions come from background threads; for pure Textual message handlers, regular `AsyncIOScheduler` is correct.

**Proposed implementation decision:**
- `Subject` instances: created in `__init__` (stateless, no loop dependency)
- `AsyncIOScheduler`: created in `on_mount` via `asyncio.get_running_loop()`
- Subscriptions: established in `on_mount`, stored as `self._subscriptions: list[Disposable]`
- Cleanup: `on_unmount` calls `d.dispose()` for each in `self._subscriptions`

**Critical spike test:** The 17-01 spike must run concurrent observable streams inside a Textual `App.run()` context and confirm: (a) no second event loop created, (b) no "attached to a different loop" errors, (c) no thread violations logged.

**Open questions:**
- Does Textual's `on_mount` guarantee `asyncio.get_running_loop()` is available (vs `asyncio.get_event_loop()`)?
- If `SearchBar` widget is remounted (e.g., tab switch), does it re-run `on_mount` and accumulate subscriptions?

**Confidence:** ✅ Both providers agreed — this is the primary spike risk

---

### ✅ 3. Enter Key vs Debounce Double-Submission Problem

**What needs to be decided:** How to structure the observable topology so that pressing Enter fires immediately while not causing a double-search when the pending debounce timer subsequently fires.

**Why it's ambiguous:**
In the current code, `_debounce_gen` is a generation counter that makes the pending timer stale when Enter is pressed. In RxPY, standard `debounce` resets whenever a new value arrives on the same Subject. If Enter emits to the same Subject, it resets the debounce timer rather than bypassing it. If Enter emits to a separate Subject merged after debounce, the debounce timer fires 300ms later with the same query — double submission.

**Provider synthesis:**
- **Gemini:** Use **two-stream merge + distinct_until_changed** architecture:
  - Stream A: `input_changes$ | debounce(0.3)`
  - Stream B: `enter_pressed$ | map(lambda _: current_input_value)`
  - Pipeline: `merge(A, B) | distinct_until_changed() | switch_map(...)`
  - When Enter fires "foo", distinct_until_changed suppresses the subsequent debounce emission of "foo"
- **Perplexity:** Confirmed this pattern is standard in reactive search implementations

**Proposed implementation decision:**
Two Subjects: `_input_subject` (receives every keystroke value) and `_enter_subject` (receives input value on Enter). Merge after respective processing. `distinct_until_changed` is the gatekeeper preventing double-fire.

**Risk to verify in spike:**
If the user types "foo", hits Enter (Stream B emits "foo"), then CHANGES the text to "foobar" within 300ms (Stream A debounce fires "foobar"), distinct_until_changed correctly allows "foobar" through since it differs from "foo". This is the correct behavior — verify in spike.

**Open questions:**
- Where does `_enter_subject` emit? In `SearchBar.on_key` (Enter handler)? Or in `App._run_search` call site?
- Should history navigation (Up arrow sets `self.value`) also emit to `_enter_subject`, or only actual Enter keypress?

**Confidence:** ✅ Both providers identified this as a non-obvious integration challenge

---

### ✅ 4. switch_map and asyncio Task Cancellation (Critical for UAT Invariant 3)

**What needs to be decided:** Whether RxPY's `switch_map` actually cancels the underlying `asyncio.Task` when it unsubscribes from the previous observable, or merely disposes the subscription without cancelling the coroutine.

**Why it's ambiguous:**
RxPY is fundamentally synchronous. `switch_map` cancels previous observables by disposing their subscription. However, disposing an RxPY subscription does NOT automatically call `task.cancel()` on the underlying `asyncio.Task`. If the search coroutine keeps running after "cancellation," it may still call `self.results = ...` on the UI after the newer search has already displayed results — violating UAT invariant 3 (stale cancellation).

**Provider synthesis:**
- **Gemini:** RxPY subscription disposal does NOT cancel asyncio tasks. Must implement `defer_task()` custom wrapper:
  ```python
  def defer_task(coro_factory):
      def subscribe(observer, scheduler):
          task = asyncio.create_task(coro_factory())
          # on dispose:
          return lambda: task.cancel() if not task.done() else None
      return rx.create(subscribe)
  ```
- **Perplexity:** Confirmed the same risk. Wrapping `create_task` with explicit `task.cancel()` on disposal is the standard pattern. Also: `CancelledError` from the task must be caught silently inside the wrapper.

**Proposed implementation decision:**
The `run_search_observable(query)` function passed to `switch_map` must:
1. Create an asyncio Task from the search coroutine
2. Return an Observable that emits the result
3. Register a disposal hook that calls `task.cancel()`
4. Catch `asyncio.CancelledError` silently (not propagate to pipeline error handler)

This is the single most critical implementation detail. Without it, UAT invariant 3 cannot be satisfied.

**Open questions:**
- Does Textual's `@work` worker use `asyncio.Task` cancellation internally? If yes, does removing `@work` mean we must replicate this in the RxPY wrapper?
- Should the custom wrapper also handle Textual UI updates (call `self.call_from_thread` if needed)?

**Confidence:** ✅ Both providers flagged this as a blocking implementation risk

---

### ✅ 5. Subject Lifecycle and Subscription Disposal

**What needs to be decided:** Where to create Subject instances, where to subscribe, and where to dispose — aligned with Textual's widget lifecycle.

**Why it's ambiguous:**
Textual widgets have a clear lifecycle: `__init__` → `compose` → `on_mount` → (running) → `on_unmount`. Subscriptions created in `on_mount` but not disposed in `on_unmount` will attempt to update DOM widgets after unmounting, causing crashes. If `SearchBar` widget is in the compose tree permanently (not dynamically mounted/unmounted), this is lower risk — but must still be confirmed.

**Provider synthesis:**
- **Gemini:** Subject in `__init__`, subscription in `on_mount`, dispose in `on_unmount`. This is mount/unmount symmetry.
- **Perplexity:** Confirmed. Use `CompositeDisposable` to collect multiple subscriptions for single-call cleanup. Confirmed that `on_mount` is the right lifecycle hook (not `compose`, which runs before the event loop is available for scheduling).

**Proposed implementation decision:**
```python
def __init__(self):
    self._input_subject = Subject()
    self._enter_subject = Subject()
    self._filter_subject = BehaviorSubject(FilterSet())
    self._subscriptions = []

def on_mount(self):
    scheduler = AsyncIOScheduler(asyncio.get_running_loop())
    subscription = rx.merge(...).pipe(...).subscribe(...)
    self._subscriptions.append(subscription)

def on_unmount(self):
    for sub in self._subscriptions:
        sub.dispose()
    self._subscriptions.clear()
```

**Open questions:**
- Should `_filter_subject` live on `ObjlibApp` (since `FilterPanel` emits `FilterChanged` to the App) or on `SearchBar`?
- Is `ObjlibApp` ever unmounted in the current usage? (Single-screen TUI, likely not — but still implement cleanup for correctness)

**Confidence:** ✅ Both providers agreed on this pattern

---

### ✅ 6. Automated UAT Harness for Timing-Dependent Invariants

**What needs to be decided:** How to write automated tests that verify "debounce fires exactly once after 300ms" and "stale response never appears" without making the suite flaky or slow.

**Why it's ambiguous:**
RxPY's marble testing uses a virtual clock (TestScheduler) that can advance time without real-world delays. But marble testing only verifies the Rx operators in isolation — it cannot verify that Textual's event loop, RxPY's AsyncIOScheduler, and the actual search pipeline integrate correctly. Textual's `run_test()` / `Pilot` API allows headless integration tests but requires real-time waits.

**Provider synthesis:**
- **Gemini:** Use **black-box real-time testing** for UATs. Use `await pilot.pause(0.35)` (>300ms) for positive assertions (search happened). Use `await pilot.pause(0.1)` (<300ms) for negative assertions (search not yet fired). Do NOT use virtual clock — the UAT must prove the real AsyncIOScheduler integration works.
- **Perplexity:** Confirmed — Textual's `run_test()` async context manager + `Pilot` is the right infrastructure. For stale-response testing, mock the search service to introduce controllable delays and verify response ordering. Real-time waits add ~1-2 seconds to the suite total — acceptable for a 7-invariant UAT.

**Proposed implementation decision:**
- UAT script uses `run_test()` + `Pilot`
- Pre-UAT script runs against the live app with `search_service` mocked (or real corpus for integration fidelity)
- Timing: `pilot.pause(0.05)` for "not yet" assertions, `pilot.pause(0.4)` for "should have fired" assertions
- Stale-response test: mock `search_service.search()` to sleep 0.5s for call 1, 0s for call 2 — verify results reflect call 2
- Results of pre-UAT captured verbatim as the contract (exact counts, exact strings, not just "pass/fail")

**Open questions:**
- Are there existing Textual tests in the project that can serve as templates?
- Should the UAT script mock the search service (faster, deterministic) or use the real Gemini search (slower, tests full stack)?

**Confidence:** ✅ Both providers agreed on this approach

---

### ⚠️ 7. History Navigation — Stateful vs Reactive

**What needs to be decided:** Whether Up/Down arrow history navigation should suppress the RxPY pipeline (avoid unintended searches while scrolling) or route through it normally (allowing debounced history searches).

**Why it's ambiguous:**
History navigation is stateful: the current history index and list are maintained in `SearchBar`. When Up arrow sets `self.value`, it triggers `on_input_changed`, which would emit to `_input_subject`. If the user scrolls through 10 history entries, 10 events fire. If they pause >300ms on an intermediate entry, a search fires.

**Provider synthesis:**
- **Gemini:** Allow debounced history search — do NOT suppress. Rationale: if the user pauses on a history entry for 300ms, they likely want to search it. Complexity of distinguishing "programmatic change" vs "user typing" in Textual is high and brittle.

**Proposed implementation decision:**
Allow `on_input_changed` to feed the Subject regardless of whether the change came from typing or history navigation. The 300ms debounce already acts as a "scroll settle" timer. If the user scrolls quickly through history, intermediate entries won't trigger searches. If they pause, the search is intentional.

**Risk:** History navigation currently does NOT trigger a new search in the existing code (it only updates `self.value`). Changing this behavior would violate the behavioral parity goal — UAT invariant 5 (history navigation) must test that Up/Down arrows cycle history WITHOUT firing searches for each intermediate step.

**Resolution:** Keep history navigation in `SearchBar.on_key` setting `self.value` directly. This already emits `on_input_changed`. Pre-UAT baseline must capture whether history navigation currently fires searches — if not, the RxPY pipeline must suppress history-navigation emissions (e.g., via a `_is_history_navigation` flag that briefly suppresses Subject emissions during `set_value` calls from arrow keys).

**Open questions:**
- Does current history navigation (Up arrow) trigger a search? Test this in pre-UAT baseline before implementing.
- If it does NOT currently trigger a search, what mechanism prevents it? (Possibly: the debounce timer is cancelled by Enter when the user selects from history, never actually firing)

**Confidence:** ⚠️ Strong Gemini finding — needs verification against current behavior

---

### ⚠️ 8. combine_latest Initialization — BehaviorSubject for Filters

**What needs to be decided:** Whether to use Subject or BehaviorSubject for the filters stream, which controls whether `combine_latest` blocks until the user changes a filter.

**Why it's ambiguous:**
`combine_latest(query$, filters$)` only emits after BOTH streams have emitted at least once. If `filters$` is a plain Subject (no initial value), the first search query won't execute until the user changes a filter — breaking UAT invariant 1 (first search should fire after debounce, no filter interaction required).

**Provider synthesis:**
- **Perplexity:** Use `BehaviorSubject(initial_value=FilterSet())` for filters so `combine_latest` emits immediately when the first query arrives. Regular Subject would block all searches until a filter change.

**Proposed implementation decision:**
`_filter_subject = BehaviorSubject(FilterSet())` — initial value is the default empty `FilterSet`. This ensures `combine_latest` emits as soon as the first debounced query arrives, not waiting for a filter interaction.

**Open questions:**
- Should `_filter_subject` emit the full `FilterSet` object or a derived filter string? (Keep it as `FilterSet` for type safety, convert to filter strings in the switch_map lambda)

**Confidence:** ⚠️ Perplexity-primary — critical correctness detail, easy to overlook

---

### ⚠️ 9. Error Handling — catch_error Placement Inside vs Outside switch_map

**What needs to be decided:** Whether `catch_error` should be placed inside the `switch_map` inner observable or outside on the main pipeline.

**Why it's ambiguous:**
If `catch_error` is placed OUTSIDE `switch_map` and the search API raises an exception, the error propagates through the main pipeline and terminates the entire Subject stream. After one API error, no further searches execute — violating UAT invariant 7 (error containment). If placed INSIDE (in the `run_search_observable` factory), each API call handles its own errors locally and the main pipeline continues.

**Provider synthesis:**
- **Gemini:** Error must be caught inside `switch_map`'s inner observable using `catch_error` so the outer pipeline continues operating
- **Perplexity:** Confirmed — insert `catch_error` after `switch_map` or inside the observable factory, transforming errors into empty results or error signals rather than terminating the stream

**Proposed implementation decision:**
Inside `run_search_observable(query)`, wrap the API call in try/except (or use `rx.catch`). On error: log the error, update ResultsList status with error message, call `self.notify()`, return empty result — do NOT propagate to outer pipeline. UAT invariant 7 test: trigger an API error, confirm `is_searching` goes to False, confirm a second search query executes normally afterward.

**Open questions:**
- Does `CancelledError` (from task.cancel() in switch_map) need to be caught by this same handler, or separately?

**Confidence:** ⚠️ Both providers — critical for UAT invariant 7

---

## Summary: Decision Checklist

### Tier 1 (Blocking — must decide before spike):
- [ ] RxPY package version: `rx` v3 vs `reactivex` v4 — confirm current installation and upgrade if needed
- [ ] AsyncIOScheduler construction location — confirm `on_mount` works with `asyncio.get_running_loop()`
- [ ] switch_map + asyncio task cancellation — custom `defer_task()` wrapper required
- [ ] BehaviorSubject for filters — prevents combine_latest blocking on first search

### Tier 2 (Important — resolve in spike or plan 17-02):
- [ ] Enter key double-submission — merge-then-distinct architecture confirmed
- [ ] Subject lifecycle — mount/unmount symmetry pattern
- [ ] catch_error placement — inside switch_map inner observable
- [ ] History navigation current behavior — does Up arrow currently trigger a search?

### Tier 3 (Implementation detail):
- [ ] UAT timing values: pilot.pause(0.05) vs pilot.pause(0.4) — confirm adequate margins
- [ ] CompositeDisposable vs list for subscription management
- [ ] ObjlibApp vs SearchBar ownership of filter Subject

---

## Next Steps (YOLO Mode)

1. ✅ CONTEXT.md created
2. ✅ CLARIFICATIONS-NEEDED.md created
3. ✅ CLARIFICATIONS-ANSWERED.md auto-generated (YOLO mode)
4. ⏭ Proceed to `/gsd:plan-phase 17`

---

*Multi-provider synthesis by: Gemini Pro Thinking, Perplexity Sonar Deep Research (OpenAI partial — model detection only)*
*Generated: 2026-02-26*
*Mode: YOLO — auto-answers generated*
