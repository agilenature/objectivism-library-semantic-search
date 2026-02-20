# CONTEXT.md — Phase 7: Interactive TUI

**Generated:** 2026-02-18
**Phase Goal:** User can interact with the library through a modern terminal UI with keyboard/mouse navigation, live search, visual browsing, split-pane views, and session management — transforming the CLI into an immersive research environment.
**Synthesis Source:** Multi-provider AI analysis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research)

---

## Overview

Phase 7 is the "Project B" milestone: a standalone TUI application that uses objlib as its backend via the `objlib.services` API (SearchService, LibraryService, SessionService). The Canon.json in objlib governs exactly how the TUI must use the library — the rules there are the contract.

The key insight across all providers: **the TUI framework choice is the single most consequential decision** because it determines how async SearchService calls integrate with the event loop, how state flows between panes, and whether mouse support works out of the box. Every other gray area depends on this choice being resolved first.

**Confidence markers:**
- ✅ **Consensus** — All providers identified this as critical
- ⚠️ **Recommended** — 2 providers identified this as important
- 🔍 **Needs Clarification** — 1 provider identified, potentially important

---

## Gray Areas Identified

### ✅ 1. TUI Framework Selection (Consensus — Blocking)

**What needs to be decided:**
Which Python TUI framework powers the event loop, widget system, and rendering.

**Why it's ambiguous:**
The existing stack (Rich + Typer) handles output formatting and CLI arguments, but neither is an interactive application framework. Rich cannot do split panes, mouse events, or input widgets. Typer cannot do event loops. A separate TUI framework is mandatory. The three candidates have meaningfully different async stories.

**Provider synthesis:**
- **Gemini:** Textual — built by the Rich author, uses asyncio natively, supports CSS grid layouts (perfect for split panes), has built-in Tree widget and Input widget. SearchService is already async; Textual runs on asyncio; no bridge needed.
- **Perplexity:** Textual — async-first design, web-inspired API, tight asyncio integration means `await search_service.search()` works inside event handlers without thread-pool wrappers.
- **OpenAI:** Textual — unanimous across all three.

**Proposed implementation decision:**
**Textual**. The alignment between Textual's asyncio-native event loop and SearchService's async interface eliminates the async bridging problem entirely. Textual also renders Rich renderables natively, allowing reuse of the existing `formatter.py` output in document preview panes.

**Open questions:**
- Textual requires a dedicated `App` subclass. The existing `objlib tui` CLI entry point needs to call `TextualApp.run()` rather than a Typer command — is the CLI entry point pattern acceptable?
- Textual CSS-style layout files or inline layout: prefer inline for this project (no separate .css files to manage)?

**Confidence:** ✅ All 3 providers — BLOCKING for all other decisions.

---

### ✅ 2. Async/Event-Loop Integration Pattern (Consensus — Blocking)

**What needs to be decided:**
How SearchService (async, 300ms–2s) and the sync services (LibraryService, SessionService) integrate with the Textual event loop without blocking rendering.

**Why it's ambiguous:**
Two distinct problems:
1. SearchService is async — Textual handles this natively via `worker` API (background tasks)
2. LibraryService and SessionService are sync — SQLite calls from the TUI main thread will briefly block rendering

**Provider synthesis:**
- **Gemini:** Use Textual's `@work` decorator / worker API to run SearchService calls off the main event loop. For sync services, this is less critical if SQLite operations are fast (sub-5ms).
- **Perplexity:** Wrap sync services with `asyncio.to_thread()` or `loop.run_in_executor()` to prevent blocking, especially for long filter queries or session saves.
- **OpenAI:** Worker pattern + cancellation tokens.

**Proposed implementation decision:**
- SearchService calls: always use `@work(exclusive=True)` Textual worker — handles cancellation and thread safety automatically
- LibraryService/SessionService: wrap with `asyncio.to_thread()` for any call that might touch disk (filter queries, session saves). Short SQLite reads can run inline.
- Never import from `objlib.search` or `objlib.session` directly — only `objlib.services` (Canon.json rule 1)

**Confidence:** ✅ All 3 providers — BLOCKING, determines architecture of all pane widgets.

---

### ✅ 3. Centralized State Management Architecture (Consensus — Blocking)

**What needs to be decided:**
How filter state, search results, selected citation, and session data flow between the three panes without spaghetti callbacks.

**Why it's ambiguous:**
Three panes need to share state:
- Filters pane changes → re-trigger search → update results pane
- Results pane selection → update preview pane
- Search history (TUI-05) needs to persist across queries
Without a clear pattern, widgets will directly mutate each other, creating hard-to-debug coupling.

**Provider synthesis:**
- **Gemini:** Reactive Data Store — centralized `TUIState` with Textual `Reactive` properties. Widgets post messages; watchers trigger actions. Flow: Input → `TUIState.query` → watcher → SearchService → `TUIState.results` → results widget repaints.
- **Perplexity:** Uni-directional data flow — AppState dataclass as single source of truth. Widgets dispatch messages upward, App processes them and updates state downward.
- **OpenAI:** State machine with explicit state transitions.

**Proposed implementation decision:**
Centralized `AppState` dataclass using Textual's `Reactive` properties. Pane widgets read from AppState; interactions post `Message` subclasses to the App; App updates AppState which triggers reactive re-renders. No widget-to-widget direct calls.

```python
class AppState:
    query: Reactive[str] = Reactive("")
    results: Reactive[list[Citation]] = Reactive([])
    active_filters: Reactive[FilterSet] = Reactive(FilterSet())
    selected_index: Reactive[int | None] = Reactive(None)
    search_history: Reactive[list[str]] = Reactive([])
```

**Confidence:** ✅ All 3 providers — BLOCKING for pane communication design.

---

### ⚠️ 4. Live Search Debounce Strategy (Recommended — Important)

**What needs to be decided:**
The exact debounce timing, race condition handling, and stale-result prevention for TUI-01 live search.

**Why it's ambiguous:**
SearchService takes 300ms–2s per call. If the user types "Atlas Shrugged" (13 keystrokes), without debouncing, 13 API calls fire. Worse: if request A (slow) returns after request B (fast), the UI will show stale results from A overtop of B's correct results.

**Provider synthesis:**
- **Gemini:** 300ms debounce + `current_search_id` (UUID) tracking. When a response arrives, discard if ID doesn't match the current search.
- **Perplexity:** Async debounce with task cancellation — cancel the pending Textual worker when a new keystroke arrives; start a new delayed worker.

**Proposed implementation decision:**
- Debounce: 300ms after last keystroke before firing
- Cancellation: use `@work(exclusive=True)` — Textual automatically cancels previous worker when a new one starts with the same exclusive key
- Stale prevention: exclusive worker handles this; only one search runs at a time
- While searching: show a spinner in the results pane header

**Confidence:** ⚠️ 2 providers explicitly flagged — important for UX quality.

---

### ⚠️ 5. Session & Bookmark Persistence Scope (Recommended — Important)

**What needs to be decided:**
What "save/load research session" (TUI-05) means precisely in terms of data — what is saved, what is NOT saved.

**Why it's ambiguous:**
Saving "complete UI state" (scroll position, pane focus, filter slider positions) requires serializing widget tree state, which is fragile and version-sensitive. Saving only queries gives a minimal but unsatisfying restore. The boundary between these extremes needs to be explicit.

**Provider synthesis:**
- **Gemini:** Data-only — save queries list, active filters, bookmarked files. Do NOT save scroll positions or pane sizes. On load, re-execute last search and restore bookmarks.
- **Perplexity:** Multi-table SQLite schema with `sessions`, `session_events`, `bookmarks`, `searches`, `search_results` tables. Event log enables session replay/timeline.

**Proposed implementation decision:**
Extend the existing `SessionService` (append-only) to store:
- Session name and creation timestamp
- Search history (queries + timestamps)
- Active filter state at session save time (stored as JSON blob)
- Bookmarks (file_path + notes)

Do NOT persist: scroll position, pane focus, pane widths, widget state.

On load: restore filter state, restore bookmark list, offer to re-execute last query.

Check existing `SessionService` schema — if it only supports search events and not UI filter state, a minor schema extension is needed (adding a metadata JSONB column to sessions).

**Confidence:** ⚠️ 2 providers raised — important before planning session management plans.

---

### ⚠️ 6. Search Hit Location Data for Document Viewer (Recommended — Important)

**What needs to be decided:**
Whether TUI-06 ("citation linking — click [1] to jump to source") can be implemented with current SearchService output, or whether a gap exists.

**Why it's ambiguous:**
Gemini File Search returns passage text excerpts (via `Citation.text`) but does NOT return byte offsets or line numbers within the source file. The TUI document preview pane needs to scroll to the relevant section. Without an offset, it must fall back to text search within the loaded document.

**Provider synthesis:**
- **Gemini:** This is a blocking gap — "jump to section" (TUI-06) is impossible without line/byte offset metadata from SearchService. Requires either (a) API offset support, or (b) text-search fallback.
- **Perplexity:** Virtual viewer with lazy loading; apply regex highlighting to visible buffer only.

**Proposed implementation decision:**
**Text-search fallback** (pragmatic): When the user clicks a citation link:
1. Load full document via `LibraryService.get_file_content(file_path)`
2. Search for the Citation.text excerpt in the document
3. Scroll viewer to first match, highlight all matches of query terms

This works for the 95% case. Exact offset jump is deferred to v2 if Gemini API exposes it.

**Confidence:** ⚠️ Gemini raised as potential blocker — needs explicit plan to avoid TUI-06 implementation stall.

---

### 🔍 7. Responsive Layout Breakpoints (Needs Clarification — Polish)

**What needs to be decided:**
How the three-pane layout degrades when the terminal is narrow (< 120 columns).

**Why it's ambiguous:**
A terminal researcher might run this in a narrow window or half-screen. Three 33%-width panes at 80 columns each get 26 characters of usable width — unreadable.

**Proposed implementation decision:**
Three layout modes:
- **Wide (140+ cols):** Full three-pane (nav 20% | results 33% | preview 47%)
- **Medium (80–139 cols):** Two-pane (nav+results 45% | preview 55%)
- **Narrow (< 80 cols):** Single-pane stacked with Tab to switch active pane

Detect terminal resize events (Textual supports this natively) and switch layout mode automatically.

**Confidence:** 🔍 Perplexity raised — important for quality, not blocking.

---

### 🔍 8. Command Dispatch / CLI-to-TUI Mapping (Needs Clarification — Polish)

**What needs to be decided:**
How TUI-08 ("all existing CLI functionality accessible") is implemented without duplicating all command logic.

**Proposed implementation decision:**
Command palette (Ctrl+P) that lists registered commands by name/description with fuzzy search. Context-sensitive footer shows the 4-5 most relevant actions for the current focused widget. This avoids re-implementing every CLI command as a dedicated TUI screen.

**Confidence:** 🔍 Raised once — important for TUI-08 completeness.

---

## Summary: Decision Checklist

**Tier 1 (Blocking — must resolve before planning):**
- [x] TUI framework: **Textual** ✅
- [x] Async integration: **Textual `@work` + `asyncio.to_thread` for sync services** ✅
- [x] State management: **Centralized `AppState` with Textual Reactives + Message dispatch** ✅

**Tier 2 (Important — plan must address):**
- [x] Debounce strategy: **300ms + `exclusive=True` worker (auto-cancellation)**
- [x] Session scope: **Data-only (queries, filters, bookmarks) — no widget state**
- [x] Search hit location: **Text-search fallback (find excerpt in loaded document)**

**Tier 3 (Polish — plan should address):**
- [x] Responsive layout: **Three breakpoints (140+, 80–139, <80)**
- [x] Command dispatch: **Command palette (Ctrl+P) + context footer**

---

*Multi-provider synthesis by: OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research*
*Generated: 2026-02-18*
