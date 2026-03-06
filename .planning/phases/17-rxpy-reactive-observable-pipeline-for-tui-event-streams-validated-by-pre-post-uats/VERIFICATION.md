# VERIFICATION.md — Phase 17: RxPY Reactive Observable Pipeline

**Verified:** 2026-02-26 (re-verification after blocker fixes)
**Plans checked:** 4 (17-01, 17-02, 17-03, 17-04)
**Verifier:** gsd-plan-checker (goal-backward analysis)
**Status:** PASSED

---

## VERIFICATION PASSED

**Phase:** 17-rxpy-reactive-observable-pipeline-for-tui-event-streams-validated-by-pre-post-uats
**Plans verified:** 4
**Status:** All blockers resolved. Plan 17-03 clean to execute.

---

## Re-verification Summary (Plan 17-03)

The two blockers identified in the initial verification pass have been resolved. The following confirms each fix.

### Blocker 1 RESOLVED: pytest -x trap removed

**Original issue:** Task 2 `<verify>` ran `pytest tests/test_tui.py -v -x` and claimed "existing tests pass." The `-x` flag would halt at the first SearchRequested-based failure, risking the executor spending context trying to fix test_tui.py inside Plan 17-03.

**Fix confirmed:** Plan 17-03 Task 2 `<verify>` (lines 498-501) now reads:

```
Run: python -m pytest tests/test_tui.py -v -- most tests pass. NOTE: Tests that
drive search via app.post_message(SearchRequested(...)) will fail here by design
(on_search_requested handler is removed). These will be fixed in Plan 17-04 Task 1.
Do NOT use -x; do NOT block on SearchRequested-based test failures at this step.
```

The `-x` flag is gone. The explicit "Do NOT use -x" instruction is present. The plan-level `<verification>` section (lines 523-532) uses the same `python -m pytest tests/test_tui.py -v` (no `-x`) and states "SearchRequested-based tests fail by design (fixed in 17-04)."

Additionally, `must_haves.truths` now includes (line 23):
> "tests/test_tui.py tests NOT using post_message(SearchRequested) pass against refactored code"

This is the behavioral parity truth that was missing in the initial pass (also resolves Warning 3 from the original report).

---

### Blocker 2 RESOLVED: Empty-query subscription tracked and disposed

**Original issue:** `on_mount` created two subscriptions but only tracked `self._rx_subscription`. The empty-query subscription was untracked and never disposed in `on_unmount`, violating Locked Decision 6 and creating a latent crash risk.

**Fix confirmed at three locations:**

**`__init__` (lines 302-308):**
```python
self._filter_subject = BehaviorSubject(FilterSet())
self._rx_subscription = None       # Set in on_mount
self._rx_clear_subscription = None  # Set in on_mount (empty-query clear)
```

**`on_mount` (lines 341-347):**
```python
# IMPORTANT: Store the subscription so on_unmount can dispose it.
self._rx_clear_subscription = search_bar.input_subject.pipe(
    ops.filter(lambda q: q == ""),
).subscribe(
    on_next=lambda _: self._clear_results(),
)
```

**`on_unmount` (lines 465-475):**
```python
def on_unmount(self) -> None:
    """Dispose RxPY subscriptions on app shutdown."""
    if self._rx_subscription is not None:
        self._rx_subscription.dispose()
        self._rx_subscription = None
    if self._rx_clear_subscription is not None:
        self._rx_clear_subscription.dispose()
        self._rx_clear_subscription = None
```

`must_haves.truths` line 22 also asserts:
> "Both _rx_subscription and _rx_clear_subscription are disposed in on_unmount"

`<done>` criteria (line 516) confirms:
> "on_unmount disposes both _rx_subscription and _rx_clear_subscription"

Locked Decision 6 is now fully satisfied.

---

## Remaining Open Item (Warning — not a blocker)

### [task_completeness] OTel tracing span silently dropped from search path

**Plan:** 17-03, Task 2

The original `_run_search` wrapped the search API call in `with self.telemetry.span("tui.search")` recording `search.query`, `search.has_filters`, and `search.result_count`. The new `_search_observable` has no span. This regression is unacknowledged in the plan's `<done>` criteria or `must_haves`.

This is not a behavioral invariant (not in the 7 UATs), not an explicit Phase 17 success criterion, and was classified as a warning (not a blocker) in the original report. The plan does not need to resolve this before execution. If the span is needed, it can be addressed in a future phase or added to Plan 17-03's `<done>` criteria as an acknowledged known regression.

**Status:** Open — acceptable for execution.

---

## Coverage Summary

| Phase Requirement (from ROADMAP.md) | Plans | Status |
|--------------------------------------|-------|--------|
| SC1: RxPY + AsyncIOScheduler integration confirmed with affirmative spike | 17-01 | Covered |
| SC2: Manual debounce/generation-tracking removed, RxPY operators in place | 17-03 | Covered |
| SC3: @work(exclusive=True) replaced by switch_map + defer_task | 17-03 | Covered |
| SC4: Two call sites unified into combine_latest pipeline | 17-03 | Covered |
| SC5: Pre-UAT baseline captured; post-UAT all 7 pass identically | 17-02, 17-04 | Covered |
| SC6: No gemini_state writes, no schema changes, TUI-layer only | 17-03 (by omission) | Covered |
| Locked Decision 1: reactivex v4 imports | 17-01, 17-03 | Covered |
| Locked Decision 2: AsyncIOScheduler in on_mount | 17-01, 17-03 | Covered |
| Locked Decision 3: defer_task() wrapper | 17-01, 17-03 | Covered |
| Locked Decision 4: BehaviorSubject(FilterSet()) | 17-03 | Covered |
| Locked Decision 5: merge + distinct_until_changed | 17-01, 17-03 | Covered |
| Locked Decision 6: Subject lifecycle (init/mount/unmount) | 17-03 | **Covered** |
| Locked Decision 7: ops.catch inside switch_map | 17-01, 17-03 | Covered |
| Locked Decision 8: ObjlibApp owns pipeline, SearchBar owns Subjects | 17-03 | Covered |
| Locked Decision 9: UAT with pilot.pause() real-time waits | 17-02 | Covered |
| Locked Decision 10: History nav verified in pre-UAT before deciding | 17-02 (captures delta) | Covered |
| Deferred: marble testing / TestScheduler | Not present in any plan | Compliant |
| Deferred: database schema changes | Not present | Compliant |
| Deferred: search service interface changes | Not present | Compliant |

---

## Plan Summary

| Plan | Tasks | Files | Wave | Scope | Status |
|------|-------|-------|------|-------|--------|
| 17-01 | 1 auto + 1 checkpoint | 1 | 1 | Within budget | Valid |
| 17-02 | 1 auto | 1 | 2 | Within budget | Valid |
| 17-03 | 2 auto | 4 | 3 | Within budget (high action density, manageable) | Valid |
| 17-04 | 2 auto | 1 | 4 | Within budget | Valid |

---

## Dependency Graph

```
17-01 (wave 1, no deps)
  |
  v
17-02 (wave 2, depends: 17-01)
  |
  v
17-03 (wave 3, depends: 17-01, 17-02)
  |
  v
17-04 (wave 4, depends: 17-02, 17-03)
```

No cycles. All referenced plans exist. Wave numbers are consistent with dependency depths.

---

## Recommendation

All blockers resolved. Run `/gsd:execute-phase 17` to proceed.
