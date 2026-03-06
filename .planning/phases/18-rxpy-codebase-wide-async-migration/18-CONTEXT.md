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

## AI Synthesis Results (2026-02-27)

**Source:** Gemini Pro (high) + Perplexity Sonar Deep Research (OpenAI timed out)
**Phase 17 status:** COMPLETE — 7/7 UATs, 470/470 tests green. Phase 18 UNBLOCKED.

**Confidence markers:**
- ✅ **Consensus** — Both providers identified this as critical
- ⚠️ **Recommended** — One provider identified, well-supported by domain context
- 🔍 **Needs Clarification** — Ambiguous, requires explicit decision

### ✅ GA-1: Migration Order Is Inverted in the Roadmap (Consensus)

**What needs to be decided:** Tier 3 → Tier 2 → Tier 1 (bottom-up) vs. Tier 1 → Tier 2 → Tier 3 (top-down as listed in ROADMAP.md plans 18-02 to 18-04).

**Why it matters:** If `orchestrator.py` (Tier 1) is migrated first to emit Observables, but `services/library.py` (Tier 3) still uses `async/await`, every service call from the orchestrator must be wrapped back into awaitables. This creates an ugly interop layer that must later be removed. Bottom-up means leaf services become Observable sources first — higher tiers consume them naturally.

**Synthesis recommendation:** ✅ **Tier 3 → Tier 2 → Tier 1** (bottom-up). ROADMAP.md lists plans as 18-02=Tier3, 18-03=Tier2, 18-04=Tier1 — this IS already correct. The tier *description* in ROADMAP.md is ordered high-to-low but the plan numbers reflect bottom-up execution. **No change needed — roadmap order (18-02=Tier3 first) is correct.**

---

### ✅ GA-2: Dynamic Concurrency — flat_map Does Not Support Dynamic max_concurrent (Consensus)

**What needs to be decided:** `orchestrator.py` dynamically resizes a `Semaphore` in response to 429 pressure. RxPY's `flat_map` takes a fixed `max_concurrent` at construction time. The `BehaviorSubject → flat_map max_concurrent` design in CONTEXT.md above is NOT natively supported.

**Options:**
- **A. Custom `dynamic_semaphore` operator** — Internal buffer + subscription to `limit` BehaviorSubject. Only pulls from upstream when `active_count < current_limit`. When limit decreases, in-flight items complete (no cancellation).
- **B. Restart-on-resize** — On each limit change, dispose and re-subscribe with new `max_concurrent`. Risk: drops in-flight uploads.
- **C. Skip dynamic resizing** — Use fixed concurrency (e.g., c=10) with `flat_map(max_concurrent=10)`. The 429 handler only adds delay, not resizes the pool.

**Synthesis recommendation:** ✅ **Option A** (custom `dynamic_semaphore` operator) — consensus. Must be one of the 5 spike patterns in 18-01.

---

### ✅ GA-3: aiosqlite Connection Lifecycle Across Rx Chains (Consensus)

**What needs to be decided:** `aiosqlite` connections must survive complex Rx chains (retry logic, `flat_map`, error recovery). If each Observable opens/closes its own connection, retry creates new connections mid-chain — risk of "Connection closed" errors.

**Synthesis recommendation:** ✅ **Singleton connection service** — aiosqlite connection managed as a shared service (already done in `state.py`), passed into operators as a dependency, NOT opened inside observables. Wrapping pattern: `rx.defer(lambda: rx.from_future(asyncio.create_task(coro)))` with externally-managed connection.

---

### ✅ GA-4: OCC Retry — Retry Must NOT Re-subscribe to Upstream (Consensus)

**What needs to be decided:** When `occ_transition` catches `OCCConflictError`, standard Rx `retry()` re-subscribes to the upstream observable — this re-triggers side effects (file re-read, new upload attempt). For OCC, only the transition *function call* should be retried, not the entire pipeline.

**Synthesis recommendation:** ✅ `occ_transition(fn, max_attempts=5, base_delay=0.1)` is an **operator that retries `fn()` internally** (a coroutine factory that reads fresh DB state on each call), NOT standard `retry()` on the outer observable. The operator contracts in CONTEXT.md above are correct. This MUST be validated in 18-01 spike.

---

### ✅ GA-5: Graceful vs. Force Shutdown — Two-Signal System (Consensus)

**What needs to be decided:** `take_until` is immediate — it completes the stream with no drain guarantee. Current code uses `asyncio.Event` which allows checking `is_set()` at loop boundaries (effective drain).

**Synthesis recommendation:** ✅ **Two-signal system**:
- `stop_accepting$` Subject: stops accepting new uploads into the pipeline (gates the input source)
- `force_kill$` Subject: fires `take_until(force_kill$)` on all active chains (immediate stop)
- Normal shutdown: fire `stop_accepting$`, await drain, then fire `force_kill$`
- Ctrl-C: fire both simultaneously
The `shutdown_gate` operator in CONTEXT.md above should implement `stop_accepting$` semantics, not `take_until`.

---

### ⚠️ GA-6: Tenacity Jitter Algorithm Preservation (Perplexity)

**What needs to be decided:** `tenacity`'s `wait_random_exponential` uses a specific full-jitter formula. The "zero behavior change" mandate technically requires preserving exact retry timing — but retry timing is probabilistic and not observable from the outside.

**Synthesis recommendation:** ⚠️ **Functionally equivalent backoff** (same max delay, same error conditions, same max attempts) is sufficient. Exact jitter seed matching is not required — it's not observable behavior. The `upload_with_retry` operator should document its backoff formula (full_jitter, base=1.0s, max=60s, max_attempts=5) to match tenacity's observed range.

---

### 🔍 GA-7: Behavioral Parity Testing Strategy per Tier

**What needs to be decided:** The existing pytest suite tests behavior at the unit and integration level but doesn't capture "observable output sequences" — the Rx-specific behavioral contract. Do we need additional per-module parity specs?

**Synthesis recommendation:** 🔍 **Per-module behavioral spec captured before migration**:
- For each module: document input conditions → expected DB state changes (not observable sequences)
- Use existing pytest suite as the parity gate (it already tests DB state outcomes)
- Add specific tests for new failure modes introduced by Rx (e.g., `take_until` on in-flight aiosqlite — confirm no "Connection closed" error)
- Do NOT add Rx-specific observable output recording tests — they add complexity without behavioral value

---

### Summary: Decision Checklist

**Tier 1 (Blocking — must resolve in 18-01 spike):**
- [x] Migration order confirmed: 18-02=Tier3, 18-03=Tier2, 18-04=Tier1 (already correct)
- [ ] `dynamic_semaphore` operator — prototype and validate in 18-01
- [ ] `occ_transition` retry semantics — fn() retry NOT outer observable re-subscribe
- [ ] Two-signal shutdown (stop_accepting$ + force_kill$) validated in spike
- [ ] Singleton connection service pattern confirmed with aiosqlite

**Tier 2 (Important):**
- [ ] Tenacity replacement with functionally equivalent backoff documented
- [ ] Per-module pre-migration behavioral spec strategy defined

**Tier 3 (Polish):**
- [ ] Shim operators (`from_async_iterable`, `to_async_iterable`) for transition interop
- [ ] `_operators.py` scope (upload-specific vs. shared at objlib level)

---

*Generated: 2026-02-23*
*Updated: 2026-02-27 — Added AI synthesis (Gemini Pro + Perplexity); Phase 17 COMPLETE*
*Phase predecessor: Phase 17 (RxPY TUI Reactive Pipeline)*
*Pre-mortem reference: governance/pre-mortem-gemini-fsm.md (atomicity / recovery concerns apply to 18-04)*
