# Pre-Mortem: Gemini File Search Finite State Machine
### Instantiated from: `governance/pre-mortem-framework.md`

---

## The Specification Being Pre-Mortemed

### What We're Building

A formal finite state machine (FSM) that governs the lifecycle of every file in the Objectivism Library's relationship with the Gemini File Search API — integrated with the local SQLite database so that the DB becomes a complete, faithful, and queryable mirror of Gemini's actual state.

### Why This Is Needed

**The core problem**: A single "uploaded library file" in Gemini is actually two separate objects with independent lifecycles:

1. **Raw File (Files API)** — `files/abc123`, created on upload, auto-deleted after 48 hours. Needed only for the import step.
2. **Store Document (File Search Store)** — `fileSearchStores/.../documents/abc123-xyz`, permanent, never expires. This is what makes the file searchable.

The local DB currently tracks `gemini_file_id` (the ephemeral raw file ID) but has **no column for the store document**. It cannot answer "is this file actually searchable?" without a full API scan. Every bug in the upload pipeline traces to this gap:

- **Orphaned store documents**: `_reset_existing_files()` deleted raw files but not store documents, accumulating 2,038+ orphans from a single day of re-uploads. Manifested as `[Unresolved file #N]` in search results.
- **`--reset-existing` has no safe boundary**: Applies to all eligible files regardless of `--limit N`, because reset and upload are separate operations with no shared scope.
- **`status = 'uploaded'` is a lie**: Means "the DB was told it succeeded," not "a store document exists and the file is searchable."
- **CLI pre-check diverges from reality**: Counts pending files to decide whether to proceed, but the relevant files for `--reset-existing` are uploaded files — two different queries, no unified view.
- **`store-sync` is a manual band-aid**: Reactive, expensive (1,000+ API calls per run), and rediscovered every session.

### The Proposed Solution

**A formal FSM that is the only path through which Gemini-related state changes.** Every mutation — upload intent, upload success, indexing confirmation, reset, delete — goes through the FSM. The FSM:

1. Validates that the transition is legal from the current state
2. Performs all required side effects (API calls + DB writes) as part of the transition definition
3. Records the new state in the DB, including `gemini_store_doc_id` as a first-class column
4. Surfaces inconsistencies to a reconciliation step (`store-sync`) rather than allowing silent divergence

### Proposed State Enum

```
UNTRACKED    — no Gemini presence, not yet uploaded
UPLOADING    — raw file upload in progress (Files API call in flight)
PROCESSING   — raw file uploaded, store document import in progress
INDEXED      — store document confirmed, file is searchable
STALE        — store document exists but content or metadata has changed
ORPHANED     — Gemini has a store document but DB record is inconsistent
FAILED       — a transition failed and cannot auto-retry
```

### Proposed Transition Table

```
UNTRACKED  → UPLOADING   trigger: begin_upload(file_path)
UPLOADING  → PROCESSING  trigger: upload_confirmed(file_id, op_name)
PROCESSING → INDEXED     trigger: import_confirmed(store_doc_id)
INDEXED    → STALE       trigger: metadata_changed() | content_changed()
STALE      → UPLOADING   trigger: begin_reset()          [--reset-existing path]
INDEXED    → UNTRACKED   trigger: delete_confirmed()
ORPHANED   → UNTRACKED   trigger: reconcile_delete()
*          → FAILED      trigger: api_error(non_retryable)
FAILED     → UNTRACKED   trigger: manual_reset()
```

### DB Schema Additions Required

```sql
ALTER TABLE files ADD COLUMN gemini_store_doc_id TEXT;     -- permanent store document resource name
ALTER TABLE files ADD COLUMN gemini_state       TEXT DEFAULT 'untracked';  -- FSM state enum
ALTER TABLE files ADD COLUMN gemini_state_updated_at TEXT; -- last confirmed timestamp
```

### Dependency Relationship

The FSM is not advisory. It is the **only authorized path** for mutating Gemini-related state. `AsyncUploadStateManager`'s write methods become FSM transition triggers. You cannot call `record_upload_success()` without the FSM first verifying the transition `UPLOADING → PROCESSING` is valid and recording the new state.

---

### Definition of Done — The Ultimate Validation

All the internal correctness properties — `gemini_state = 'indexed'` meaning indexed, orphan count staying at zero, `--limit N` scoping exactly N files — are intermediate. They are means, not the end.

**The solution is complete when `[Unresolved file #N]` never appears in the TUI.**

This is the only user-facing consequence that matters. Every failure mode documented in this pre-mortem — orphaned store documents, stale DB state, half-committed transitions, Gemini-side silent failures — manifests to the user as a search result that shows `[Unresolved file #N]` instead of the actual file name. The citation was returned by Gemini but could not be resolved to a record in the DB.

When the FSM is working correctly:
- Every file Gemini returns as a citation has `gemini_state = 'indexed'` in the DB
- That state guarantees a valid `gemini_store_doc_id` that links the citation back to a DB record
- The DB record resolves to a file name, author, topics, and metadata
- The TUI displays the actual file name in every citation, every time

The acceptance test for the entire implementation is therefore not a unit test, not a store-sync dry-run count, and not an API call log. It is: **run a search in the TUI and confirm that every citation in every result displays a real file name.** If any result shows `[Unresolved file #N]`, the FSM has not solved the problem.

This criterion must survive Wave 7's council gate. If `[Unresolved file #N]` can still appear after the FSM is implemented — due to Gemini-side indexing lag, API silent failures, or any other cause — the implementation is incomplete regardless of how clean the DB state looks internally.

---
---

# PRE-MORTEM EXECUTION
## Framework: `governance/pre-mortem-framework.md`

---

## Step 1: The Pre-Mortem Session

**Premise given to all participants:**

> *"It is six weeks from now. The Gemini FSM has been implemented and deployed. It has made things worse — the upload pipeline is unreliable, search results are still broken, and the system is harder to reason about than before. What happened?"*

---

### Failure Stories

---

**Story A: "The Async Trap"**

We chose `python-statemachine` because it was the most Pythonic and best-documented FSM library. It worked beautifully in unit tests. Then we tried to integrate it with the upload pipeline. The entire pipeline is `async` — Typer callbacks call `asyncio.run()`, the orchestrator uses `aiosqlite`, everything is awaitable. `python-statemachine` is synchronous. Every transition that touched the DB or Gemini API required `asyncio.run()` inside the transition callback, which caused "event loop already running" errors. We tried running transitions in a `ThreadPoolExecutor`, but aiosqlite connections can't be shared across threads (Pitfall 5 — we already knew this). We rewrote the connection handling. Then the circuit breaker stopped working because it lived in the async context but the FSM callbacks ran in threads. We spent two weeks in async/sync hell and ended up with code more complex than what we started with.

---

**Story B: "display_name Was Never Stable"**

The entire canonical detection strategy for `store-sync` — and the new `gemini_store_doc_id` migration — depended on `display_name` being a stable, unique identifier that matched our DB's `gemini_file_id` values. It worked in our tests. But after a routine google-genai SDK upgrade (1.x → 2.x), `display_name` started being set to the full resource name instead of the plain file ID. All 873 existing `gemini_store_doc_id` values in the DB no longer matched anything Gemini returned. Every file transitioned to `ORPHANED` state. We had to write an emergency re-migration script and re-run the full store population. The FSM had a recovery path (`ORPHANED → UNTRACKED → re-upload`), but it required touching all 1,748 files. We lost two days of search availability.

---

**Story C: "Half-Committed Transitions"**

The FSM transition `INDEXED → STALE → UPLOADING` (the `--reset-existing` path) required three side effects in sequence: (1) call `delete_store_document()` in Gemini API, (2) call `delete_file()` for the raw file (probably expired anyway), (3) update DB: set `gemini_state = 'uploading'`, clear `gemini_store_doc_id`. In production, step 1 succeeded for 841 files. Steps 2-3 then hit an aiosqlite write contention error on file 842. The pipeline crashed. We now had 841 files where Gemini had no store document but the DB still said `INDEXED`. The FSM's own guard (`INDEXED → STALE` is only valid if `gemini_store_doc_id` is set) refused to re-run the transition because the DB still showed `INDEXED`. The files were stuck. We had to write a manual SQL repair script to force-reset them. The FSM had created a class of "locked" states that its own transition rules couldn't escape.

---

**Story D: "store-sync Didn't Go Away"**

We implemented the FSM perfectly. States were correct, transitions were atomic, `gemini_store_doc_id` was tracked. We ran the upload pipeline with full FSM enforcement for three weeks. Then we ran `store-sync` out of habit and found 47 orphaned documents. We investigated: the Gemini `file_search_stores.documents.import_()` API was returning success (HTTP 200, operation name returned) but the document was silently failing to appear in `list_store_documents()` — apparently an intermittent Gemini-side bug we couldn't reproduce on demand. The FSM had transitioned these 47 files to `PROCESSING` and then `INDEXED` based on the API response. But the store never actually indexed them. The FSM's belief and Gemini's reality had diverged through no fault of our code. `store-sync` was still necessary. Now we had two systems to maintain — the FSM and the reconciliation layer — instead of just the reconciliation layer.

---

**Story E: "The Migration Hole"**

We wrote the migration to add `gemini_store_doc_id` and populate it for all 873 existing `uploaded` files by calling `list_store_documents()` and matching on `display_name`. 841 matched cleanly. 32 didn't. Investigation: those 32 files had been uploaded before we added the `display_name` tracking fix (the compound name bug from the previous session). Their store documents had `display_name` set to an old format, or empty. We couldn't populate `gemini_store_doc_id` for those 32 files programmatically. So we left them with `gemini_state = 'untracked'` to force re-upload. But `get_files_to_reset_for_enriched_upload()` didn't know about `gemini_state` — it still keyed on `status IN ('uploaded', 'failed')`. So the FSM said "untracked" but the legacy query said "uploaded." Two state systems running simultaneously with no coordination. Every transition that checked FSM state got a different answer than every query that used the old `status` column.

---

**Story F: "The Library Dependency Tax"**

We picked `transitions` (the most popular Python FSM library). It worked fine. But 8 months later, a routine `pip install --upgrade` broke everything: `transitions` 0.9.2 changed how it serialized state for persistence, and our `gemini_state` column values (which we'd stored as `transitions` internal state machine state names) stopped deserializing correctly. Every file showed `gemini_state = None` after the upgrade. We hadn't written tests for state deserialization — we'd assumed the library would be stable. We now owned a dependency on a third-party library's internal serialization format for our most critical database column.

---

**Story G: "Performance Cliff Under Batch Upload"**

The FSM added guard checks and DB reads before every transition. Under normal single-file operations, this was imperceptible. Under the batch upload pipeline (818 files, concurrency 2), every transition required a DB read to verify current state, an API call, and a DB write to update state. The WAL mode handled concurrent reads fine but serialized writes. With 818 files transitioning through `UPLOADING → PROCESSING → INDEXED`, we had 818 × 3 = 2,454 sequential DB writes. Throughput dropped from 45 files/min to 12 files/min. A full upload run went from 20 minutes to 75 minutes. The FSM's correctness guarantees had a 4× performance cost we hadn't measured.

---

### Assumption Extraction

From the failure stories, the following assumptions are being treated as true but have not been verified:

| # | Assumption | Category | Story |
|---|---|---|---|
| A1 | An FSM library exists that is compatible with our async/aiosqlite/asyncio stack | Technical Integration | A |
| A2 | `display_name` is a stable, unique identifier across google-genai SDK versions | Technical Integration | B, E |
| A3 | FSM transitions can be made effectively atomic (API call + DB write fail together) | Technical Integration | C |
| A4 | The FSM's local belief will remain consistent with Gemini's actual state without constant polling | Domain Understanding | D |
| A5 | All 873 existing `uploaded` files can have `gemini_store_doc_id` populated via `list_store_documents()` + `display_name` match | Environmental | E |
| A6 | We can run one state system (FSM `gemini_state`) and retire the legacy `status` column cleanly | Scope | E |
| A7 | The FSM library's internal state representation is stable across versions and safe to persist | Technical Integration | F |
| A8 | The FSM's transition overhead is acceptable under batch upload conditions | Technical Integration | G |
| A9 | The FSM eliminates (or drastically reduces) the need for `store-sync` | Scope | D |
| A10 | The Gemini API's import operation is reliable enough that "API returned success" = "document is indexed" | Technical Integration | D |

---

### Risk Ranking

| # | Assumption | Uncertainty (1-5) | Impact (1-5) | Risk Score | Distrust Level |
|---|---|---|---|---|---|
| A3 | Transitions can be made effectively atomic | 5 | 5 | **25** | HOSTILE |
| A1 | FSM library is async-compatible | 5 | 4 | **20** | HOSTILE |
| A2 | `display_name` is stable across SDK versions | 4 | 5 | **20** | HOSTILE |
| A4 | FSM belief stays consistent with Gemini reality | 4 | 4 | **16** | SKEPTICAL |
| A10 | "API success" = "document actually indexed" | 4 | 4 | **16** | SKEPTICAL |
| A5 | All 873 files can be migrated via display_name match | 3 | 5 | **15** | SKEPTICAL |
| A6 | Legacy `status` column can be retired cleanly | 4 | 3 | **12** | CAUTIOUS |
| A7 | FSM library state serialization is stable across versions | 3 | 4 | **12** | CAUTIOUS |
| A8 | Transition overhead is acceptable under batch load | 3 | 4 | **12** | CAUTIOUS |
| A9 | `store-sync` becomes unnecessary | 4 | 2 | **8** | WATCHFUL |

---

## Step 2: Planning (Driven by the Pre-Mortem)

**The shift**: We are not planning "how to build the FSM." We are planning "which assumptions must be validated before we commit to any architecture."

### Wave Sequence

| Wave | Assumption(s) | Risk Score | Distrust Level | Spike Goal |
|---|---|---|---|---|
| 1 | A1: Async-compatible FSM library | 20 | HOSTILE | Find and prove a library (or hand-rolled design) that works natively with asyncio + aiosqlite |
| 2 | A3: Effective atomicity for transitions | 25 | HOSTILE | Prove a write-ahead intent pattern (already used in state.py) works for the two-API-call transition problem |
| 3 | A2 + A10: `display_name` stability + import reliability | 20+16 | HOSTILE | Verify display_name format is contractual, verify that import success = searchable |
| 4 | A5: Migration coverage | 15 | SKEPTICAL | Run the actual migration against the 873 existing files, measure match rate |
| 5 | A6 + A7: State column retirement + library serialization | 12 | CAUTIOUS | Verify the legacy `status` column can be deprecated without breaking queries, and that state persists across library upgrades |
| 6 | A8: Batch performance | 12 | CAUTIOUS | Benchmark FSM overhead under simulated 818-file batch |
| 7 | A4 + A9: Consistency maintenance + store-sync necessity | 16+8 | SKEPTICAL | Determine whether `store-sync` is still needed and what the reconciliation contract looks like |

---

## Step 3: Wave Execution + Council Gates

---

### WAVE 1 — Assumption A1: An FSM Library Exists That Is Async-Compatible

**Assumption Statement:**
> We assume that a Python FSM library (or a minimal hand-rolled FSM) exists that integrates cleanly with our async pipeline: `asyncio`, `aiosqlite`, `Typer`, without requiring thread pools, event loop workarounds, or synchronous-to-async bridges that would compromise connection sharing.

**Distrust Level: HOSTILE** (Risk Score: 20)

**The Spike (smallest possible test):**

Write a minimal async FSM harness that:
1. Defines three states (`A → B → C`) using the candidate library
2. Wraps a transition in an `async def` that awaits a mock aiosqlite write
3. Runs it inside `asyncio.run()` from a Typer command
4. Confirms no "event loop already running" errors, no thread leakage, no connection sharing violations

Test candidates:
- `transitions` (most popular, but primarily sync)
- `python-statemachine` (Pythonic, but sync)
- `aiomachine` or similar async-native options
- Hand-rolled FSM (~150 lines): a simple class with a state dict, guard checks, and async transition methods

**Evaluation Window:** 2-4 hours

**Council Gate:**

```
RESULTS AGENT must answer:
  - Which library (if any) ran cleanly in the async harness?
  - Were there any event loop conflicts, thread violations, or
    connection-sharing issues?
  - Did the hand-rolled alternative outperform all libraries?
  - EVIDENCE GAP ANALYSIS: what did we not test?
    (concurrent transitions, high-volume transitions, error paths)
  - DISTRUST CHALLENGE: articulate the strongest reason to not
    believe the spike result is valid in production conditions.

RISK AGENT must answer:
  - What is the betrayal probability for each gap identified?
  - Does the library have active maintenance? What is its release
    cadence vs. our dependency ecosystem?
  - Is there hidden coupling between the library's state management
    and our aiosqlite WAL transaction boundaries?

STRATEGY AGENT must offer:
  - Option A: Proceed with best library, but build transition
    methods as thin wrappers (swap-out-ready abstraction)
  - Option B: Hand-roll the FSM now, even if a library "works"
    (eliminate external dependency entirely)
  - Option C: Deepen with adversarial concurrent-transition tests
    before committing to any approach
  - NOTE: No option may assume library stability without a
    lock-file strategy and upgrade test coverage.

NEXT-STEP AGENT scorecard:
  ✓/✗ Positive evidence of async compatibility (not just "no errors")
  ✓/✗ Reproducible under realistic conditions (Typer + asyncio.run)
  ✓/✗ Boundary tested (concurrent transitions, error paths)
  ✓/✗ Risk acceptance (dependency maintenance, upgrade stability)
  ✓/✗ Confidence trajectory: does this give us a foundation?
```

**Gate Passage Criteria:**
The wave passes when we have **affirmative, reproducible evidence** that a specific approach (library or hand-rolled) runs concurrent async transitions with no event loop or connection-sharing issues. "No errors thrown" is not sufficient — we need positive evidence of correct async behavior under concurrent load.

---

### WAVE 2 — Assumption A3: Transitions Can Be Made Effectively Atomic

**Assumption Statement:**
> We assume that FSM transitions — which require both an external Gemini API call and a local DB write — can be made atomic enough that a mid-transition failure leaves the system in a recoverable, not stuck, state.

**Distrust Level: HOSTILE** (Risk Score: 25)

**Background:**
This is the highest-risk assumption. True atomicity across a network API and a local DB is impossible without distributed transactions. The question is whether "effective atomicity" via the write-ahead intent pattern (already used in `state.py`) can be extended to cover the two-API-call transition case (`delete_store_document()` + `delete_file()` + DB update).

The existing pattern:
1. Write intent to DB BEFORE the API call (`status = 'uploading'`)
2. Make the API call
3. Write result to DB AFTER the API call (`status = 'uploaded'`)
4. If crash between 2 and 3: recovery finds `status = 'uploading'` and retries

The FSM extension needed for `INDEXED → UPLOADING` (the `--reset-existing` path):
1. Write intent: `gemini_state = 'resetting'` (new state?) + record `old_store_doc_id`
2. Call `delete_store_document(old_store_doc_id)` — may succeed or fail
3. Call `delete_file(gemini_file_id)` — may fail if already expired (expected)
4. Write result: `gemini_state = 'untracked'`, clear `gemini_store_doc_id`
5. If crash between 2 and 4: what is the recovery path?

**The Spike:**

Write a test that:
1. Implements the extended WAL pattern for a two-API-call transition
2. Simulates mid-transition crashes (kill process after step 2, before step 4)
3. Verifies that the recovery path can correctly determine state from the DB intent record
4. Specifically tests: what if `delete_store_document()` succeeds but the DB write fails?

**Council Gate:**

```
RESULTS AGENT must answer:
  - Does the write-ahead intent pattern cover the two-API-call case?
  - What states can a file be left in after each crash point?
  - For each stuck state: does a clear recovery path exist?
  - EVIDENCE GAPS: what crash scenarios were not tested?
  - DISTRUST CHALLENGE: what is the hardest stuck state to recover from?

RISK AGENT must answer:
  - Are there stuck states that the FSM's own transition rules
    cannot escape? (Requiring manual SQL intervention)
  - What is the probability of a mid-transition crash in production?
    (Consider: network timeouts, process kills, OOM, SIGTERM from OS)
  - Is the compensation logic (saga pattern) simpler or more complex
    than the problem we're solving?

STRATEGY AGENT must offer:
  - Option A: Extended WAL with recovery crawler (poll for
    'resetting' state on startup, re-attempt recovery)
  - Option B: Design transitions to be idempotent — calling them
    twice produces the same result as calling them once
  - Option C: Accept that some stuck states require `store-sync`
    as the recovery mechanism (FSM + reconciliation, not FSM alone)
  - NOTE: Option C directly challenges Assumption A9 (store-sync
    eliminated). Council must acknowledge this explicitly.

NEXT-STEP AGENT scorecard:
  ✓/✗ Every crash point has an identified recovery path
  ✓/✗ No stuck states require manual SQL to escape
  ✓/✗ Recovery is tested, not just designed
  ✓/✗ The recovery logic complexity is less than the problem's complexity
  ✓/✗ Confidence in the approach for the worst-case scenario
```

**Gate Passage Criteria:**
Every identified crash point must have a **tested, automatic recovery path** that does not require manual SQL intervention. "It probably won't happen" is not acceptable at HOSTILE distrust.

---

### WAVE 3 — Assumptions A2 + A10: `display_name` Stability + Import Reliability

**Assumption Statement A2:**
> We assume that `doc.display_name` (the plain file ID, e.g., `eafkmpzjs39o`) is a stable, contractual identifier that the google-genai SDK will continue to set in the same format across SDK versions.

**Assumption Statement A10:**
> We assume that when `file_search_stores.documents.import_()` returns a success response (or an operation name), the document is reliably indexed and will appear in `list_store_documents()` within a predictable window.

**Distrust Level: HOSTILE** (Risk Score: 20 / 16)

These are combined because both are facts about Gemini API behavior that we discovered empirically (not from documentation) and have been burned by before.

**The Spike:**

For A2:
1. Inspect the google-genai SDK source for how `display_name` is set during `documents.import_()`
2. Check if it's set by the caller (us) or inferred by the SDK/API
3. Check the SDK changelog for versions 1.x through current for any `display_name` behavior changes
4. Upload a test file, verify `display_name` matches what we set, re-list after SDK version bump in a venv

For A10:
1. Upload 10 test files via the import pipeline
2. After import operation succeeds, immediately call `list_store_documents()` — do the files appear?
3. Measure the lag between "import success" and "document visible in list"
4. Test: what happens if you search for the document before it's visible in the list?

**Council Gate:**

```
RESULTS AGENT must answer:
  - Is display_name set by our code (display_name parameter in the
    import call) or inferred by the API?
  - What does the SDK source say about display_name?
  - Is there a Gemini API contract (docs, changelog) that defines
    display_name format?
  - What is the measured lag between import success and list visibility?
  - DISTRUST CHALLENGE: we discovered the compound-name bug empirically.
    What else might we be wrong about regarding document naming?

RISK AGENT must answer:
  - If display_name is set by our code (display_name= parameter),
    is it guaranteed to be stored and returned as-is?
  - What is the worst-case lag for import visibility? Is it bounded?
  - What does the FSM's PROCESSING state mean if "import confirmed"
    can be true but the document isn't yet searchable?
  - Should PROCESSING and INDEXED be the same state, or do they
    need to be distinct with a polling mechanism between them?

STRATEGY AGENT must offer:
  - Option A: Store display_name in DB at import time (we control it),
    don't rely on API returning it consistently
  - Option B: Use document resource name (not display_name) as the
    canonical identifier, accept that it's compound and handle parsing
  - Option C: Add a VERIFYING state between PROCESSING and INDEXED
    that polls list_store_documents() until the document appears
  - Option D: Accept import lag and treat INDEXED as "import reported
    success" with store-sync as the eventual consistency check

NEXT-STEP AGENT scorecard:
  ✓/✗ We control display_name (we set it, we know its value)
  ✓/✗ Import-to-visible lag is measured and bounded
  ✓/✗ The PROCESSING → INDEXED transition has a reliable trigger
  ✓/✗ Naming scheme is not SDK-version-dependent
  ✓/✗ Evidence from SDK source, not just empirical observation
```

---

### WAVE 4 — Assumption A5: Migration Coverage for Existing Files

**Assumption Statement:**
> We assume that all 873 currently-uploaded files in the DB can have their `gemini_store_doc_id` column populated by matching against `list_store_documents()` results, and that no files will be left with an unmatchable state.

**Distrust Level: SKEPTICAL** (Risk Score: 15)

**The Spike:**

Run the actual migration against the real DB and real Gemini store:
1. Call `list_store_documents()` and collect all documents with their `display_name` and `name`
2. For each of the 873 files with `status = 'uploaded'`, attempt to match via `display_name` → `gemini_file_id`
3. Measure: how many match? How many don't?
4. For non-matching files: investigate why (format differences, historical upload runs, etc.)
5. For non-matching files: what is the correct FSM state to assign?

**Council Gate:**

```
RESULTS AGENT must answer:
  - Match rate: N/873 files matched
  - For unmatched files: what are the characteristics? (upload date,
    file type, which pipeline run?)
  - Can unmatched files be manually recovered, or must they be re-uploaded?
  - DISTRUST CHALLENGE: the match rate in dev may differ from
    production if we have orphans we haven't discovered yet.

RISK AGENT must answer:
  - What is the acceptable match rate? Is 95% good enough, or must
    it be 100% before we can retire the legacy status column?
  - What is the blast radius if we misassign gemini_state to a file
    during migration? (e.g., mark as UNTRACKED when it's actually INDEXED)
  - Does the migration need to be run in a dry-run mode first?

STRATEGY AGENT must offer:
  - Option A: Require 100% match before proceeding; handle
    unmatched files by forcing re-upload
  - Option B: Proceed with partial match; unmatched files get
    gemini_state = 'untracked' and are queued for re-upload
  - Option C: Run migration as a two-pass operation: first populate
    what we can, then schedule a reconciliation pass for the rest
  - NOTE: Any option must address what happens to the legacy
    status column during the migration window.

NEXT-STEP AGENT scorecard:
  ✓/✗ Match rate measured on real data (not estimated)
  ✓/✗ Unmatched files have a defined, safe state assignment
  ✓/✗ Migration is reversible (can roll back gemini_state column)
  ✓/✗ Migration does not break existing queries during the transition
  ✓/✗ Confidence that the migration covers all historical upload patterns
```

---

### WAVE 5 — Assumptions A6 + A7: State Column Retirement + Library Serialization Stability

**Assumption Statement A6:**
> We assume that the legacy `status` column (`pending`, `uploading`, `uploaded`, `failed`) can be deprecated and eventually dropped, with all queries migrated to use `gemini_state` instead.

**Assumption Statement A7:**
> We assume that if we use an FSM library, its state serialization format is stable enough to persist in a DB column across library version upgrades.

**Distrust Level: CAUTIOUS** (Risk Score: 12)

**The Spike:**

For A6:
1. Grep all query sites that read from `status` column
2. Verify each can be mapped to an equivalent `gemini_state` query
3. Check for any external consumers (tests, TUI, browse/filter commands) that would break

For A7 (if a library was chosen in Wave 1):
1. Persist FSM state as the library serializes it
2. Upgrade the library to the next major version in a venv
3. Attempt to deserialize the persisted states
4. Verify no corruption

**Council Gate:**

```
RESULTS AGENT must answer:
  - Complete list of query sites using `status` column
  - Which can be directly mapped to gemini_state equivalents?
  - Which require behavioral changes (not just column renaming)?
  - For library serialization: did the upgrade test pass or fail?

RISK AGENT must answer:
  - Can both columns coexist during a migration window without
    creating dual-write inconsistencies?
  - What is the risk of a library upgrade breaking serialized state?
    (If we hand-rolled the FSM, this risk is zero — flag this.)

STRATEGY AGENT must offer:
  - Option A: Run both columns for 30 days, write to both, then
    drop status after confirmed stability
  - Option B: Store gemini_state as a plain string enum (not
    library-native format) to be independent of library internals
  - Option C: Keep status column permanently as a derived field
    (always written from gemini_state, never written directly)

NEXT-STEP AGENT scorecard:
  ✓/✗ All status query sites inventoried and mapped
  ✓/✗ Library serialization stable across one major version jump
  ✓/✗ Migration window strategy defined and reversible
  ✓/✗ No query breakage identified in TUI or CLI commands
```

---

### WAVE 6 — Assumption A8: Batch Performance Under Load

**Assumption Statement:**
> We assume that the FSM's transition overhead — guard checks, DB reads, state writes — does not degrade batch upload throughput to an unacceptable level under the expected workload of 818+ files with concurrency 2.

**Distrust Level: CAUTIOUS** (Risk Score: 12)

**The Spike:**

Benchmark the FSM transition overhead in isolation:
1. Simulate 818 sequential transitions (`UNTRACKED → UPLOADING → PROCESSING → INDEXED`) against a local test DB
2. Measure: transitions/second, total time, P95 latency per transition
3. Identify the bottleneck: is it the guard check (read), the state write, or the API mock latency?
4. Compare against baseline: current pipeline without FSM overhead

**Council Gate:**

```
RESULTS AGENT must answer:
  - Measured throughput: transitions/second under simulated load
  - Baseline vs. FSM overhead comparison (% degradation)
  - Which operation is the bottleneck?
  - DISTRUST CHALLENGE: lab benchmark may not reflect production
    because we're mocking API calls. What is the real overhead?

RISK AGENT must answer:
  - At what file count does the FSM overhead become the bottleneck
    vs. API call latency?
  - Is the bottleneck avoidable (e.g., batch DB writes instead of
    per-transition commits)?
  - What is the user-facing impact of a 4× slowdown? (818 files
    at 12/min = 68 min vs. 20 min — is that acceptable?)

STRATEGY AGENT must offer:
  - Option A: Accept the overhead; correctness > throughput for
    this use case
  - Option B: Batch state writes — accumulate transitions and
    commit every N files instead of per-transition
  - Option C: Make transitions fire-and-forget for the write
    path (async state write doesn't block the upload)
  - Option D: Reserve FSM overhead for the reset path only;
    keep the happy-path upload lean

NEXT-STEP AGENT scorecard:
  ✓/✗ Overhead measured, not estimated
  ✓/✗ Bottleneck identified and has a mitigation option
  ✓/✗ Acceptable throughput defined (what is "acceptable"?)
  ✓/✗ Mitigation option tested, not just proposed
```

---

### WAVE 7 — Assumptions A4 + A9: FSM Consistency vs. Gemini Reality + store-sync Necessity

**Assumption Statement A4:**
> We assume that the FSM's local belief (stored in `gemini_state`) will remain consistent with Gemini's actual state over time without constant polling.

**Assumption Statement A9:**
> We assume that implementing the FSM eliminates (or drastically reduces) the need for `store-sync` as a routine operation.

**Distrust Level: SKEPTICAL** (Risk Score: 16 + 8)

**Background:**
Story D revealed that Gemini's import API can return success but silently fail to index. This means the FSM can believe `INDEXED` while Gemini has nothing. If `store-sync` is still needed, the question becomes: what is the FSM's role relative to `store-sync`? Are they complementary or redundant?

**The Spike:**

1. Measure: after a successful import operation, how often does the document appear in `list_store_documents()` within 5 seconds? 30 seconds? 5 minutes?
2. Design an adversarial test: complete an import, immediately add the file to the FSM as INDEXED, then run a search — does the file appear in results?
3. Determine empirically: is `store-sync` still needed for routine operation, or only for exceptional cases (API bugs, crashes, external deletions)?

**Council Gate:**

```
RESULTS AGENT must answer:
  - Import-to-searchable lag: measured distribution (P50, P95, P99)
  - Adversarial test: did FSM=INDEXED always mean actually searchable?
  - How many times (out of N tests) did "import success" not result
    in a visible, searchable document?
  - DISTRUST CHALLENGE: the sample size may be too small to surface
    intermittent Gemini-side indexing failures.

RISK AGENT must answer:
  - If store-sync is still needed: what is the FSM's value over the
    current system? Is it enough to justify the implementation cost?
  - What is the risk of the FSM and store-sync disagreeing?
    (FSM says INDEXED, store-sync says orphaned — who wins?)
  - Is the reconciliation contract (FSM owns writes, store-sync
    owns reads for verification) coherent and implementable?

STRATEGY AGENT must offer:
  - Option A: FSM + mandatory post-upload store-sync (automatic,
    not manual). FSM prevents accumulation; store-sync catches
    Gemini-side failures.
  - Option B: FSM + VERIFYING state with polling before INDEXED.
    Eliminates the "import success but not actually indexed" case.
  - Option C: Accept that store-sync is permanent infrastructure,
    not a band-aid. Redesign it as a first-class reconciliation
    service that runs on a schedule.
  - Option D: Re-evaluate the entire FSM proposal. If store-sync
    is still needed, has the FSM earned its complexity cost?

NEXT-STEP AGENT scorecard:
  ✓/✗ Import-to-searchable lag is measured and bounded
  ✓/✗ Gemini-side silent failures are characterized (frequency, conditions)
  ✓/✗ store-sync's ongoing role is explicitly defined
  ✓/✗ The FSM's value is positive even if store-sync remains
  ✓/✗ Option D (reconsidering the FSM) has been seriously evaluated
```

---

## Open Questions for Planning

These questions cannot be resolved by pre-mortem analysis alone — they require spike evidence from the waves above:

1. **Hand-rolled vs. library**: If the hand-rolled FSM passes Wave 1 comparably to any library, the dependency is eliminated at low cost. Wave 1 must produce a recommendation.

2. **State count**: The 7-state enum may be too many or too few once the migration data from Wave 4 is in hand. States may need to collapse (`STALE → UPLOADING` may not need a distinct STALE if the trigger is always re-upload) or expand (a `VERIFYING` state between PROCESSING and INDEXED may be required by Wave 3 findings).

3. **The dual-column transition window**: The period where both `status` and `gemini_state` are written is the riskiest migration moment. Wave 5 must define exactly how long this window lasts and what the rollback procedure is.

4. **`store-sync` contract**: This must be answered before implementation begins. Is `store-sync` (a) a routine automatic step after every upload run, (b) a scheduled job that runs regardless of uploads, or (c) an emergency tool only? Wave 7 determines this.

5. **The `FAILED` state recovery path**: Story C revealed that stuck states can be impossible to escape via FSM transition rules alone. The recovery path for every path into `FAILED` must be designed as part of Wave 2, not discovered post-implementation.

---

## Anti-Patterns This Pre-Mortem Anticipates

**"The FSM will prevent all future issues"** — The FSM prevents *state mutation bugs*. It does not prevent API unreliability (Story D), SDK version incompatibility (Story B, F), or performance degradation (Story G). It is one layer of defense, not a complete solution.

**"The async compatibility issue is obvious"** — Story A killed two weeks of work on a real project. The fact that it's obvious in retrospect doesn't mean it won't happen here. Wave 1 exists specifically to prove it won't.

**"We'll handle stuck states in the exception handler"** — Exception handlers are not state machines. Every stuck state needs a *designed* recovery path, not a catch-all. Wave 2 enforces this.

**"display_name has always worked"** — We discovered the compound-name bug empirically. Wave 3 exists because empirical knowledge is not the same as contractual knowledge.

**"We can deprecate status later"** — "Later" is never. The dual-column window must have a defined end date before the migration begins. Wave 5 enforces this.

**"store-sync will go away"** — The highest-risk assumption is that the FSM is a complete replacement. Wave 7 must honestly assess whether this is true before we commit the architecture.

---

*Document created: 2026-02-19*
*Specification source: Discussion in session 1cf6d12f-aa46-4eb8-aeb2-b0511cde339f*
*Framework: `governance/pre-mortem-framework.md`*
*Status: Ready for planning handoff*
