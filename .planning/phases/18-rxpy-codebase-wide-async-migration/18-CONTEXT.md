# CONTEXT.md — Phase 18: RxPY Codebase-Wide Async Migration

**Generated:** 2026-02-23
**Phase Goal:** Migrate all remaining async code outside `src/objlib/tui/` to a uniform RxPY reactive paradigm — zero behavior change, full test suite + UAT gates before and after
**Blocked on:** Phase 17 complete

---

## Overview

Phase 17 (RxPY TUI Reactive Pipeline) replaced the TUI's manual debounce/generation-tracking with RxPY observables, scoped to `src/objlib/tui/` only. Phase 18 extends the same reactive paradigm to every other async module in the codebase.

This phase is structured as:
- **18-01**: Spike — validate the hardest operator patterns before committing to migration
- **18-02**: Tier 3 — low-complexity services/search modules (to_thread, simple retry)
- **18-03**: Tier 2 — medium-complexity extraction pipelines (semaphore+gather, rate limiting, polling)
- **18-04**: Tier 1 — high-complexity upload pipeline (fan-outs, OCC, dynamic concurrency, shutdown)
- **18-05**: Post-migration validation + Canon update

**Hard constraint inherited from v2.0:** AI-enriched metadata (metadata_json, entity tables) is sacred. No migration step may alter DB schema or data — only async control flow changes.

**Migration principle:** Zero behavior change. The observable pipeline must produce identical results to the asyncio primitives it replaces. Behavioral verification is the gate, not test coverage.

---

## What Phase 17 Already Covers (Do Not Duplicate)

- `src/objlib/tui/` only: SearchBar debounce, `_run_search @work`, `on_filter_changed` re-fire
- Pre/post UAT with 7 behavioral invariants
- RxPY + Textual + asyncio integration proof

Phase 18 inherits the Phase 17 spike result: `AsyncIOScheduler` integrates cleanly with asyncio. The 18-01 spike focuses on patterns specific to the upload/extraction pipelines that were not covered by Phase 17.

---

## Modules to Migrate

### Tier 1 — Upload Pipeline (highest complexity)

| Module | Async Patterns Present |
|---|---|
| `src/objlib/upload/orchestrator.py` | `asyncio.Semaphore` + `gather` fan-outs, staggered launches, `asyncio.Event` shutdown, in-place 429 retry loops, batch retry passes, dynamic semaphore resizing |
| `src/objlib/upload/client.py` | `AsyncRetrying` (tenacity) in `wait_for_active` and `poll_operation`, exponential backoff, `TryAgain` pattern |
| `src/objlib/upload/state.py` | `aiosqlite` async CRUD, OCC-guarded transitions, batch tracking |
| `src/objlib/upload/recovery.py` | `asyncio.wait_for` timeout guard, three-phase sequential recovery |

### Tier 2 — Extraction Pipeline (medium complexity)

| Module | Async Patterns Present |
|---|---|
| `src/objlib/extraction/batch_orchestrator.py` | `asyncio.Semaphore`, `AsyncLimiter`, `gather`, polling loop |
| `src/objlib/extraction/orchestrator.py` | `asyncio.Semaphore`, `AsyncLimiter`, wave 1/2 validation, checkpoint |

### Tier 3 — Services / Search (low complexity)

| Module | Async Patterns Present |
|---|---|
| `src/objlib/services/search.py` | `asyncio.to_thread` wrappers (3 instances) |
| `src/objlib/services/library.py` | `asyncio.to_thread` wrappers (6+ instances) |
| `src/objlib/search/client.py` | sync `@retry` decorator (tenacity) |
| `src/objlib/sync/orchestrator.py` | light async usage |

---

## Operator Design Decisions

The 18-01 spike must validate and document these mappings before any migration begins.

| Pattern | Current Implementation | RxPY Target | Risk |
|---|---|---|---|
| `asyncio.gather` fan-out | List of coroutines | `flat_map(max_concurrent=N)` | Low |
| `asyncio.Semaphore` | Context manager | `flat_map` concurrency param | Low |
| `asyncio.to_thread` | Thread wrapper | `rx.from_callable(...).pipe(ops.observe_on(AsyncIOScheduler()))` | Low |
| Tenacity `AsyncRetrying` | `with attempt:` + `TryAgain` | `retry_when` + `delay_when` | Low |
| `asyncio.sleep` (stagger) | `await sleep(N)` | `delay` / `zip(rx.interval(...))` | Medium |
| `asyncio.Event` (shutdown) | `event.is_set()` polling | `Subject` + `take_until` | Medium |
| OCC conflict retry | Manual check + raise `OCCConflictError` | Custom `occ_transition` operator | High |
| Dynamic semaphore resize | Mutate `Semaphore._value` | Circuit-breaker `Subject` → `flat_map` `max_concurrent` | High |
| Polling loop (batch job) | `asyncio.sleep` + `while not done:` | `rx.interval(period).pipe(ops.take_while(not_done))` | Medium |
| `asyncio.wait_for` timeout | `await asyncio.wait_for(coro, timeout=N)` | `.pipe(ops.timeout(N))` | Low |

---

## Critical Integration Concerns (from 18-01 Spike)

### 1. RxPY `AsyncIOScheduler` + aiosqlite co-existence
Phase 17 confirmed `AsyncIOScheduler` integrates with Textual's event loop. The upload pipeline uses `aiosqlite` in the same asyncio event loop. The spike must confirm that observable streams driving aiosqlite calls produce no connection-sharing violations or event loop conflicts.

### 2. OCC-guarded transitions as a custom retry observable
`AsyncUploadStateManager` uses Optimistic Concurrency Control: it checks `gemini_state` before writing and raises `OCCConflictError` if another coroutine beat it. The current pattern uses `while True: try: ... except OCCConflictError: await sleep(backoff)`. The RxPY target is a reusable `occ_transition(fn, max_attempts=5)` operator that retries on `OCCConflictError` with configurable backoff. This must be validated as a standalone operator before migration.

### 3. Dynamic concurrency (circuit-breaker Subject)
`orchestrator.py` dynamically resizes a `Semaphore` in response to API pressure signals. The RxPY equivalent is a `BehaviorSubject` emitting the current concurrency limit N, which drives a `flat_map(max_concurrent=N)` — but RxPY's `flat_map` does not support dynamic `max_concurrent`. The spike must investigate the correct approach (likely: a `window` or `merge` with custom backpressure, or a restructured `flat_map` that re-subscribes when N changes).

### 4. Shutdown broadcast: `asyncio.Event` → Subject with `take_until`
The orchestrator uses `asyncio.Event` to signal all in-flight coroutines to stop. In RxPY: a `Subject` fires once on shutdown; all observable chains include `.pipe(ops.take_until(shutdown$))`. The spike must verify `take_until` works correctly when upstream is a long-lived aiosqlite operation (the observable should complete cleanly, not leave a dangling subscription).

### 5. Tenacity `AsyncRetrying` replacement
`client.py:poll_operation` uses the `TryAgain` pattern (fixed in Phase 16: `raise TryAgain` inside `with attempt:` to trigger tenacity retry). The RxPY equivalent is `retry_when(error_obs => error_obs.pipe(ops.delay(backoff)))` or `delay_when`. The spike must validate that the observable retry correctly handles both `TryAgain`-style internal retry signals and actual exception-based retries.

---

## Operator Contracts (to be finalized in 18-01)

Each contract will be documented in `18-01-SUMMARY.md` and referenced by 18-02 through 18-04.

```
occ_transition(fn, max_attempts=5, base_delay=0.1)
  Input: coroutine factory fn() → awaitable
  Retry condition: fn() raises OCCConflictError
  Backoff: exponential with jitter, base=base_delay, max=1.0
  Terminal: raises OCCConflictError after max_attempts exhausted
  Returns: Observable<T> where T = fn() return value

upload_with_retry(file_record, upload_fn, max_attempts=5)
  Input: file_record, upload coroutine factory
  Retry condition: 429 response (HTTP status or specific exception)
  Backoff: exponential with full jitter, base=1.0s, max=60s
  Terminal: emits error after max_attempts (triggers FSM FAILED transition)
  Returns: Observable<UploadResult>

shutdown_gate(obs, shutdown$)
  Wraps any observable to complete when shutdown$ fires
  Equivalent to: obs.pipe(ops.take_until(shutdown$))
  Guarantees: in-flight items complete before shutdown (no force-kill)
  Returns: Observable<T> (same type as obs)
```

---

## What 18-01 Must Produce

Before any migration code is written:
1. `spike/phase18_spike/` — working test harness for each of the 5 high-risk patterns
2. `spike/phase18_spike/design_doc.md` — operator contracts, go/no-go verdict, confirmed pattern mappings
3. **Go/no-go gate**: If any pattern cannot be cleanly mapped to RxPY without hidden complexity, the phase is redesigned before 18-02 begins

---

## Success Criteria (Phase 18 overall)

1. `pytest` — all existing tests pass after migration (no behavior regression)
2. New UNTRACKED lectures (added for Phase 18 testing) upload successfully through the migrated pipeline — no files stuck in UPLOADING/PROCESSING; some FAILED states are acceptable and handled by RecoveryCrawler
3. Pre-existing indexed corpus (~1,748 files) is not touched — no `--reset-existing`, no state mutations on already-indexed files
4. `python -m objlib store-sync` — 0 new orphaned documents produced by new-lecture uploads
5. `python -m objlib --store objectivism-library search "Rand epistemology"` — citations resolve correctly (no `[Unresolved file #N]`)
6. Pre/post UAT behavioral invariants from Phase 17 still hold for TUI (regression check)
7. Canon.json updated to index all migrated modules

---

## Files Modified by This Phase

| File | Change |
|---|---|
| `src/objlib/upload/orchestrator.py` | Replace asyncio primitives with RxPY operators |
| `src/objlib/upload/client.py` | Replace tenacity AsyncRetrying with retry_when |
| `src/objlib/upload/state.py` | Wrap aiosqlite calls in observables |
| `src/objlib/upload/recovery.py` | Replace wait_for with timeout operator |
| `src/objlib/extraction/batch_orchestrator.py` | Replace semaphore+gather with flat_map |
| `src/objlib/extraction/orchestrator.py` | Replace semaphore+limiter with flat_map+throttle |
| `src/objlib/services/search.py` | Replace to_thread with observe_on |
| `src/objlib/services/library.py` | Replace to_thread with observe_on |
| `src/objlib/search/client.py` | Replace @retry with retry operators |
| `src/objlib/sync/orchestrator.py` | Light async → observable |
| `spike/phase18_spike/` | New spike harness + design doc |
| `.planning/phases/18-*/` | Phase folder + context + plans |
| `Canon.json` | Index migrated modules |

---

## Dependency on Phase 17

Phase 18 is BLOCKED on Phase 17 gate passing. Specifically:
- Phase 17 produces the `AsyncIOScheduler` + Textual integration proof — Phase 18 inherits this
- Phase 17's post-UAT confirms 7 behavioral invariants — Phase 18 uses these as the TUI regression suite
- Phase 17 must be fully complete (all 4 plans done, post-UAT passed) before 18-01 begins

---

*Generated: 2026-02-23*
*Phase predecessor: Phase 17 (RxPY TUI Reactive Pipeline)*
*Pre-mortem reference: governance/pre-mortem-gemini-fsm.md (atomicity / recovery concerns apply to 18-04)*
