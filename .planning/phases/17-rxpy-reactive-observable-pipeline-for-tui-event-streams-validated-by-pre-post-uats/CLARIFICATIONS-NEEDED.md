# CLARIFICATIONS-NEEDED.md

## Phase 17: RxPY Reactive Observable Pipeline — Decisions Required

**Generated:** 2026-02-26
**Mode:** Multi-provider synthesis (Gemini Pro Thinking + Perplexity Sonar Deep Research)
**Source:** AI analysis of Phase 17 requirements and current TUI codebase

---

## Decision Summary

**Total questions:** 9
**Tier 1 (Blocking):** 4 — must answer before spike (plan 17-01)
**Tier 2 (Important):** 3 — should answer for implementation quality
**Tier 3 (Polish):** 2 — can defer to implementation

---

## Tier 1: Blocking Decisions

### Q1: RxPY Package Version

**Question:** Install `rx` (v3) or `reactivex` (v4)? What import API?

**Why it matters:** v3 uses `import rx, from rx import operators as ops`. v4 uses `import reactivex as rx, from reactivex import operators as ops`. They are NOT drop-in compatible. Debounce takes seconds in v4 (`ops.debounce(0.3)`), not milliseconds. Python 3.12 compatibility issues exist in v3.

**Options:**

**A. reactivex v4 (Recommended)**
- `pip install reactivex`
- `import reactivex as rx` / `from reactivex import operators as ops`
- Python 3.11+ compatible, generic type annotations, no timezone deprecations
- _(Proposed by: Gemini + Perplexity)_

**B. rx v3**
- `pip install rx`
- `import rx` / `from rx import operators as ops`
- May work, but Python 3.12 timezone issues documented (issue #705)
- _(Not recommended)_

**Synthesis recommendation:** ✅ **Option A — reactivex v4**
- Rationale: Python 3.11+ environment, forward-compatible, type-safe

---

### Q2: AsyncIOScheduler Thread Safety Model

**Question:** Should the observable pipeline use `AsyncIOScheduler` or `AsyncIOThreadSafeScheduler`?

**Why it matters:** If Subject.on_next() is ever called from a background thread (e.g., a Textual worker), the regular AsyncIOScheduler may cause race conditions. The ThreadSafe variant is required for cross-thread Subject emissions.

**Options:**

**A. AsyncIOScheduler (Recommended)**
- Simpler, works when all Subject emissions occur in Textual message handlers (main event loop)
- Current `on_input_changed`, `on_key`, `on_filter_changed` all run in main loop
- _(Proposed by: Perplexity)_

**B. AsyncIOThreadSafeScheduler**
- Required only if RxPY operations are triggered from background threads or Textual workers
- Overkill for current architecture where message handlers are main-loop callbacks
- _(Proposed by: Perplexity — but only if worker threads are involved)_

**Synthesis recommendation:** ✅ **Option A — AsyncIOScheduler**
- Rationale: All Textual message handlers run in the main event loop; no background thread emissions in current design

---

### Q3: switch_map + asyncio Task Cancellation Strategy

**Question:** How to ensure that when switch_map cancels the previous search, the underlying asyncio.Task is actually cancelled (not just the RxPY subscription disposed)?

**Why it matters:** RxPY subscription disposal does NOT automatically call `task.cancel()` on the underlying asyncio coroutine. Without explicit cancellation, stale search tasks continue running and may overwrite newer search results — violating UAT invariant 3.

**Options:**

**A. Custom defer_task() wrapper (Recommended)**
```python
def defer_task(coro_factory):
    def subscribe(observer, scheduler=None):
        task = asyncio.create_task(coro_factory())
        async def run():
            try:
                result = await task
                observer.on_next(result)
                observer.on_completed()
            except asyncio.CancelledError:
                pass  # Silent cancellation — not an error
            except Exception as e:
                observer.on_error(e)
        asyncio.create_task(run())
        return lambda: task.cancel() if not task.done() else None
    return rx.create(subscribe)
```
- Explicit bridge from RxPY disposal to asyncio Task.cancel()
- CancelledError caught silently
- _(Proposed by: Gemini + Perplexity)_

**B. Trust RxPY switch_map disposal**
- Simpler but incorrect — stale tasks continue running
- Violates UAT invariant 3
- _(Not recommended)_

**Synthesis recommendation:** ✅ **Option A — Custom defer_task() wrapper**
- This is non-negotiable for UAT invariant 3 (stale cancellation) to pass

---

### Q4: BehaviorSubject vs Subject for Filter Stream

**Question:** Should the filter stream use `BehaviorSubject(FilterSet())` or plain `Subject()`?

**Why it matters:** `combine_latest(query$, filters$)` only emits after BOTH streams have emitted at least once. If filters use plain Subject, no search fires until the user changes a filter — breaking all search functionality for users who never touch filters (most usage).

**Options:**

**A. BehaviorSubject(FilterSet()) (Recommended)**
- Initial value emitted immediately upon subscription
- combine_latest fires on first query without requiring filter interaction
- _(Proposed by: Perplexity)_

**B. Plain Subject() for filters, startWith(FilterSet()) operator**
- Equivalent effect, but adds operator overhead
- Less explicit about "there is always a current filter state"
- _(Possible alternative)_

**Synthesis recommendation:** ✅ **Option A — BehaviorSubject(FilterSet())**
- Rationale: More semantically correct (filters always have a current value: "no filter")

---

## Tier 2: Important Decisions

### Q5: Enter Key Architecture — Double-Submission Prevention

**Question:** How to structure the pipeline so Enter fires immediately but the pending debounce timer doesn't cause a second search 300ms later?

**Options:**

**A. Two-stream merge + distinct_until_changed (Recommended)**
- Stream A: `input_changes$ | debounce(0.3)`
- Stream B: `enter_pressed$ | map(current_value)`
- Pipeline: `merge(A, B) | distinct_until_changed() | switch_map(...)`
- distinct_until_changed suppresses Stream A's "foo" emission after Stream B already emitted "foo"
- _(Proposed by: Gemini)_

**B. Single stream, Enter bumps a skip counter**
- Replicates current _debounce_gen pattern in RxPY using a filter operator
- More complex, less idiomatic
- _(Not recommended)_

**Synthesis recommendation:** ✅ **Option A — Two-stream merge + distinct_until_changed**

---

### Q6: History Navigation Behavior

**Question:** Should Up/Down arrow history navigation suppress the RxPY pipeline to avoid firing unintended searches?

**Context:** Current code sets `self.value` on Up/Down which triggers `on_input_changed` → debounce. If the user pauses on a history entry >300ms, a search fires. This may or may not be the current behavior.

**Options:**

**A. Allow debounced history search (No suppression)**
- Simplest implementation — no special-casing
- If user pauses on history entry >300ms, search fires (may be intentional)
- _(Proposed by: Gemini)_

**B. Suppress history navigation from pipeline via flag**
- `_navigating_history` flag set during Up/Down, blocks Subject emission
- Preserves exact current behavior regardless of whether Up/Down currently triggers searches
- _(More conservative)_

**Synthesis recommendation:** ⚠️ **Verify current behavior first (pre-UAT baseline)**
- If Up/Down currently triggers debounced search: Option A (allow it, matches existing behavior)
- If Up/Down currently does NOT trigger search: Option B (preserve existing behavior via flag)
- **This must be captured in the pre-UAT baseline before any implementation**

---

### Q7: catch_error Placement for API Errors

**Question:** Should API error handling be inside the switch_map inner observable or outside the main pipeline?

**Options:**

**A. Inside run_search_observable() — local error handling (Recommended)**
- Each search API call handles its own errors; outer pipeline continues
- On error: log + notify + emit empty result
- UAT invariant 7 satisfied: error shows notification, is_searching resets, next search works
- _(Proposed by: Gemini + Perplexity)_

**B. Outside switch_map — global catch_error**
- One API error terminates the entire search pipeline permanently
- Violates UAT invariant 7
- _(Not recommended)_

**Synthesis recommendation:** ✅ **Option A — Inside run_search_observable()**

---

## Tier 3: Polish Decisions

### Q8: Subscription Collection Pattern

**Question:** Use `list[Disposable]` or `CompositeDisposable` for subscription cleanup?

**Options:**
- **A. CompositeDisposable** — single `dispose()` call cleans all subscriptions
- **B. list[Disposable]** — iterate and dispose in on_unmount

**Synthesis recommendation:** Either works. CompositeDisposable is more idiomatic RxPY. Use whichever is cleaner in implementation.

---

### Q9: Filter Subject Ownership

**Question:** Should `_filter_subject` live on `ObjlibApp` or `SearchBar`?

**Options:**
- **A. ObjlibApp** — FilterPanel's FilterChanged messages are handled by ObjlibApp. ObjlibApp emits to filter Subject and owns the pipeline.
- **B. SearchBar** — SearchBar owns the entire search pipeline.

**Synthesis recommendation:** **Option A — ObjlibApp** owns the unified pipeline. SearchBar owns the input Subjects. ObjlibApp wires them via combine_latest in its on_mount.

---

## Next Steps

1. Review CONTEXT.md for full gray area analysis
2. Answer questions above (or use YOLO auto-answers in CLARIFICATIONS-ANSWERED.md)
3. Run `/gsd:plan-phase 17`

---

*Generated by discuss-phase-ai YOLO mode — answers auto-generated in CLARIFICATIONS-ANSWERED.md*
*Multi-provider synthesis: Gemini Pro Thinking + Perplexity Sonar Deep Research*
*Generated: 2026-02-26*
