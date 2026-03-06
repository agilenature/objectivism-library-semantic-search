# CLARIFICATIONS-NEEDED.md

## Phase 18: RxPY Codebase-Wide Async Migration — Stakeholder Decisions Required

**Generated:** 2026-02-27
**Mode:** Multi-provider synthesis (Gemini Pro + Perplexity Sonar Deep Research)
**Source:** 2 AI providers analyzed Phase 18 requirements (OpenAI timed out — degraded synthesis)

---

## Decision Summary

**Total questions:** 9
**Tier 1 (Blocking — 18-01 spike scope):** 5 questions — Must resolve before 18-01 begins
**Tier 2 (Important):** 2 questions — Should answer for implementation quality
**Tier 3 (Polish):** 2 questions — Can defer to implementation

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: Migration Execution Order

**Question:** The roadmap lists plans 18-02=Tier3, 18-03=Tier2, 18-04=Tier1 (bottom-up: services first, upload pipeline last). Is this confirmed as the intended execution order, or should it be inverted?

**Why it matters:** Bottom-up (Tier3→Tier2→Tier1) means leaf services become Observable sources first — higher tiers consume them naturally. Top-down would require shim operators to wrap Rx observables back into awaitables during the transition window.

**Options:**

**A. Bottom-up: Tier 3 → Tier 2 → Tier 1** _(Recommended — consensus)_
- services/search.py, services/library.py, search/client.py, sync/orchestrator.py first
- extraction pipeline second
- upload pipeline last
- No wrapping needed during transition
- _(Proposed by: Gemini, Perplexity)_

**B. Top-down: Tier 1 → Tier 2 → Tier 3**
- upload pipeline first (most critical, highest ROI)
- Requires shim operators during transition window
- _(Proposed by: neither provider)_

**Synthesis recommendation:** ✅ **Option A** — confirmed as the current roadmap order. No change needed.

---

### Q2: Dynamic Concurrency Operator Design

**Question:** `orchestrator.py` dynamically resizes a Semaphore in response to 429 API pressure. RxPY's `flat_map` takes a fixed `max_concurrent` at construction time. What is the correct design for the `dynamic_semaphore` operator?

**Why it matters:** This is the hardest algorithmic challenge in Phase 18. Getting the design wrong means silent dropped uploads or memory leaks.

**Options:**

**A. Custom `dynamic_semaphore` operator** _(Recommended — consensus)_
- Internal buffer + subscription to `limit` BehaviorSubject
- Only pulls from upstream when `active_count < current_limit`
- When limit *decreases*: in-flight items complete (no cancellation), new items blocked until count drops
- Validated in 18-01 spike before use in 18-04
- _(Proposed by: Gemini, Perplexity)_

**B. Restart-on-resize**
- Dispose and re-subscribe with new max_concurrent on each limit change
- Risk: drops in-flight uploads
- _(Not recommended by either provider)_

**C. Fixed concurrency (skip dynamic resizing)**
- Use fixed c=10 (empirically validated in Phase 14)
- 429 handler adds delay but does not resize pool
- Simpler but loses the circuit-breaker behavior
- _(Not proposed by providers, but a valid simplification)_

**Synthesis recommendation:** ✅ **Option A** (custom operator) — must be proven in 18-01 spike.

**Sub-questions:**
- When limit decreases, do we cancel in-flight immediately or let them finish? (Recommendation: let finish)
- What is the maximum queue depth for the internal buffer?

---

### Q3: OCC Retry Semantics — fn() Retry vs. Upstream Re-subscribe

**Question:** `occ_transition` operator catches `OCCConflictError`. Standard Rx `retry()` re-subscribes to the upstream observable, which re-triggers side effects. Is the intended behavior fn() retry (call the transition function again with fresh state) or upstream re-subscribe?

**Why it matters:** Re-subscribing would re-trigger file reads, new Gemini upload calls, and other side effects — catastrophic for the upload pipeline.

**Options:**

**A. fn() retry (internal retry, NOT upstream re-subscribe)** _(Recommended — consensus)_
- `occ_transition(fn, max_attempts=5, base_delay=0.1)` retries calling `fn()` internally
- `fn` is a coroutine factory that reads fresh DB state on each call
- The outer observable chain is NOT re-subscribed
- _(Proposed by: Gemini, Perplexity)_

**B. Standard `retry()` on outer observable**
- Would re-trigger all upstream side effects
- _(Not recommended — would break upload pipeline)_

**Synthesis recommendation:** ✅ **Option A** — operator contracts in 18-CONTEXT.md are correct. Validate in 18-01 spike.

---

### Q4: Shutdown Signal Design

**Question:** `asyncio.Event` allows checking `is_set()` at loop boundaries for graceful drain. `take_until` completes the stream immediately. What is the correct shutdown design for the upload pipeline?

**Why it matters:** Immediate shutdown with in-flight uploads could leave files in UPLOADING state (stuck in FSM). Graceful drain is critical.

**Options:**

**A. Two-signal system** _(Recommended — consensus)_
- `stop_accepting$` Subject: gates the input source (no new files enter pipeline)
- `force_kill$` Subject: `take_until(force_kill$)` on all active chains (immediate stop)
- Normal shutdown: fire `stop_accepting$`, await drain, then fire `force_kill$`
- Ctrl-C: fire both simultaneously
- _(Proposed by: Gemini, Perplexity)_

**B. Single `take_until` signal**
- Simpler but no drain guarantee
- Acceptable if RecoveryCrawler handles stuck states on next run
- _(Not recommended for graceful shutdown)_

**Synthesis recommendation:** ✅ **Option A** — `shutdown_gate` operator should implement `stop_accepting$` semantics. Validate in 18-01 spike.

---

### Q5: aiosqlite Connection Lifecycle

**Question:** Should aiosqlite connections be opened inside Observables (per-operation) or managed as a singleton service external to the Rx chains?

**Why it matters:** `retry()` and `flat_map` may re-subscribe to observables mid-chain. If connection is opened inside the observable, retry creates new connections — risk of "Connection closed" errors on the original connection.

**Options:**

**A. Singleton connection service** _(Recommended — consensus)_
- `aiosqlite` connection managed by `AsyncUploadStateManager` (already the case in state.py)
- Observable wrappers use `rx.defer(lambda: rx.from_future(asyncio.create_task(coro)))` with externally-managed connection
- No new connection opens inside Rx chains
- _(Proposed by: Gemini, Perplexity)_

**B. Per-operation connection (context manager inside Observable)**
- Each `rx.defer` opens and closes its own connection
- Simpler subscription model but high connection churn on retry
- _(Not recommended for retry-heavy pipelines)_

**Synthesis recommendation:** ✅ **Option A** — validate connection survival across retry in 18-01 spike.

---

## Tier 2: Important Decisions

### Q6: Tenacity Backoff Algorithm Preservation

**Question:** The "zero behavior change" mandate requires preserving tenacity's retry behavior. Does this require exact jitter seed preservation, or is functionally equivalent backoff (same max delay, same error conditions, same max attempts) sufficient?

**Why it matters:** Exact jitter matching is not possible without mocking random seeds. If exact is required, the upload_with_retry operator must use the exact same algorithm as tenacity's wait_random_exponential.

**Options:**

**A. Functionally equivalent backoff** _(Recommended — Perplexity)_
- Same max delay (60s), same error conditions (429, transient errors), same max attempts (5)
- Full-jitter formula: `random.uniform(0, min(cap, base * 2^attempt))`
- Retry timing is probabilistic — not observable behavior
- Document formula in operator docstring

**B. Exact tenacity algorithm cloning**
- Import and reuse tenacity's wait functions inside the operator
- Preserves exact algorithm but maintains tenacity dependency in the Rx pipeline
- _(Proposed by: neither provider as required)_

**Synthesis recommendation:** ⚠️ **Option A** — functionally equivalent is sufficient for behavioral parity. Document the formula.

---

### Q7: Per-Module Behavioral Parity Testing Strategy

**Question:** Should each migrated module have explicit pre-migration behavioral specs capturing input → DB state outcomes? Or is the existing pytest suite sufficient as the parity gate?

**Why it matters:** The existing pytest suite tests DB state outcomes well but doesn't capture timing-sensitive behavior (debounce, polling intervals). Additional per-module specs may catch regressions the suite misses.

**Options:**

**A. Existing pytest suite as parity gate** _(Recommended)_
- pytest exits 0 before migration, must exit 0 after each tier
- Add targeted tests for Rx-specific failure modes (connection closed on retry, take_until with in-flight DB ops)
- No Rx-specific observable output recording tests (adds complexity without behavioral value)

**B. Full per-module behavioral specs + observable output recording**
- Capture exact observable emission sequences before migration
- Verify identical sequences after migration
- High effort, may add false positives from timing differences

**Synthesis recommendation:** ⚠️ **Option A** — add targeted Rx-failure-mode tests per tier, but don't add observable output recording.

---

## Tier 3: Polish Decisions

### Q8: Shim Operators for Transition Interop

**Question:** During the transition (e.g., Tier 3 migrated, Tier 1 not yet), should `_operators.py` include shim operators (`from_async_iterable`, `to_async_iterable`) for wrapping Rx outputs back into awaitables for unconverted callers?

**Options:**
**A. Include shims** — easier incremental testing, removed when all tiers done
**B. No shims** — migrate each tier completely before using its new interface from callers

**Synthesis recommendation:** 🔍 **Option B** (no shims) — each tier plan completes the tier before the next tier starts. No partial migration state needed between plans.

---

### Q9: `_operators.py` Scope

**Question:** Should custom operators live in `src/objlib/upload/_operators.py` only (upload-specific) or in a shared `src/objlib/_operators.py` accessible to extraction and services tiers?

**Options:**
**A. Upload-specific**: `upload/occ_transition`, `upload/upload_with_retry`, `upload/shutdown_gate`
**B. Shared**: `objlib/_operators.py` with all reusable operators; tiers import from shared module

**Synthesis recommendation:** 🔍 **Option A initially** — ASYNC-RX-02 specifies `upload/_operators.py`. If extraction tier needs shared operators (e.g., retry logic), create `objlib/_rx_operators.py` in 18-03 when the need is concrete.

---

## Next Steps (Non-YOLO Mode)

**✋ PAUSED — Awaiting Your Decisions**

1. Review these 9 questions
2. Create CLARIFICATIONS-ANSWERED.md with your decisions
3. Then run: `/gsd:plan-phase 18` to create the execution plan

---

## Alternative: YOLO Mode

```bash
/meta-gsd:discuss-phase-ai 18 --yolo
```

---

*Multi-provider synthesis: Gemini Pro + Perplexity Sonar Deep Research*
*Generated: 2026-02-27*
*Non-YOLO mode: Human input required*
