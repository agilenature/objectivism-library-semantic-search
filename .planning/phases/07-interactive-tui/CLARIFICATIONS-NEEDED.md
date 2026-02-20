# CLARIFICATIONS-NEEDED.md

## Phase 7: Interactive TUI — Stakeholder Decisions Required

**Generated:** 2026-02-18
**Mode:** Multi-provider synthesis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research)

---

## Decision Summary

**Total questions:** 8
**Tier 1 (Blocking):** 3 — Must resolve before planning
**Tier 2 (Important):** 3 — Should resolve for quality
**Tier 3 (Polish):** 2 — Can defer to implementation

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: Which TUI framework?

**Question:** Should Phase 7 use Textual, urwid, or Rich Live as the TUI framework?

**Why it matters:** This is the highest-leverage decision in Phase 7. The framework determines how async SearchService calls integrate, how panes communicate, whether mouse works out-of-the-box, and what the widget model looks like. Every other plan in this phase depends on this choice.

**Options:**

**A. Textual** _(Proposed by: OpenAI, Gemini, Perplexity — unanimous)_
- Async-native: runs on asyncio, `await search_service.search()` works directly in handlers
- CSS-like grid layout: split panes are declarative, not manual
- Built-in: Input widget, Tree widget, DataTable, mouse support, scrollable views
- Built by the Rich author: Rich renderables render natively (reuse existing formatter.py)
- Workers API: `@work(exclusive=True)` handles debounce + cancellation automatically
- Con: newer framework (2021+), some APIs still evolving

**B. urwid** _(proposed by none as primary)_
- Most mature (2007+), battle-tested
- Con: not async-native — bridging to asyncio requires manual thread-pool wrapping for every SearchService call
- Con: more boilerplate for split-pane layout

**C. Rich Live** _(proposed by none as primary)_
- Already in the stack
- Con: not an application framework — no input widgets, no focus management, no mouse support
- Would require manually implementing everything Textual provides

**Synthesis recommendation:** ✅ **Option A: Textual**
- The async-first architecture eliminates the most dangerous integration risk
- Unanimous provider consensus

---

### Q2: How do async and sync services integrate with the TUI event loop?

**Question:** SearchService is async (300ms–2s). LibraryService and SessionService are sync. How should the TUI handle calls to each without blocking rendering?

**Why it matters:** A blocked event loop means frozen UI — no cursor, no mouse, no repaints. SearchService blocking is the critical failure mode.

**Options:**

**A. Textual workers for async, inline for sync** _(Gemini)_
- SearchService: `@work(exclusive=True)` decorator — Textual runs it off main loop, handles cancellation
- LibraryService/SessionService: call inline, accept brief blocking (SQLite is sub-5ms)
- Simplest implementation; works if SQLite calls are fast

**B. Wrap all services with async adapters** _(Perplexity)_
- Add `AsyncLibraryServiceWrapper` using `asyncio.to_thread()` for all SQLite calls
- All services are async from the TUI's perspective
- More code, but fully non-blocking

**Synthesis recommendation:** ✅ **Option A with selective Option B**
- SearchService: always `@work(exclusive=True)` — mandatory, no blocking allowed
- LibraryService filter queries (potentially slow): wrap with `asyncio.to_thread()`
- SessionService session saves: wrap with `asyncio.to_thread()`
- LibraryService single-record reads: call inline (fast enough)

---

### Q3: How does state flow between the three panes?

**Question:** When the user changes a filter, selects a result, or types in the search box, how do the three panes stay in sync without tight coupling?

**Why it matters:** If widgets reach into other widgets to update them, the code becomes unmaintainable. A clear pattern must be chosen before the pane widgets are designed.

**Options:**

**A. Centralized AppState + Reactive properties** _(all providers)_
- Single `AppState` dataclass with Textual `Reactive` fields
- Widgets post `Message` subclasses upward to App
- App updates AppState; reactive watchers trigger pane re-renders
- Unidirectional: Actions flow up, state flows down

**B. Event bus / pub-sub** _(alternative pattern)_
- Widgets subscribe to events by type
- More decoupled, but harder to reason about state consistency

**Synthesis recommendation:** ✅ **Option A: Centralized AppState + Message dispatch**
- Matches Textual's own recommended architecture
- Makes state transitions explicit and traceable

---

## Tier 2: Important Decisions (⚠️ Recommended)

### Q4: What is the live search debounce strategy?

**Question:** How should TUI-01 (live search updates as you type) handle rapid keystrokes and slow Gemini responses?

**Why it matters:** Without debouncing, each keystroke triggers an API call. Without stale-result prevention, a slow response from an old query can overwrite a fast response from a newer query.

**Options:**

**A. Debounce timer + exclusive worker** _(recommended)_
- 300ms idle before firing search
- `@work(exclusive=True)`: Textual auto-cancels previous worker when new one starts
- Spinner shown during search
- Stale results impossible because only one search runs at a time

**B. Manual UUID tracking + task cancellation** _(Gemini variant)_
- Each search gets a UUID; ignore responses with old UUIDs
- More code; no advantage over Option A when using Textual workers

**Synthesis recommendation:** ⚠️ **Option A**

---

### Q5: What exactly gets saved/restored in a research session?

**Question:** TUI-05 says "save and load research sessions." What data is persisted, and what is NOT?

**Why it matters:** Attempting to save widget tree state (scroll position, pane focus) is fragile and version-sensitive. Data-only persistence is simpler and more reliable. This decision affects both the session schema and the restore UX.

**Options:**

**A. Data-only session persistence** _(recommended by both providers)_
- Saved: query history list, active filter state (JSON), bookmark list (file paths + notes)
- NOT saved: scroll position, pane widths, current focus, selected result index
- On restore: rebuild filter state, show bookmarks, offer "re-run last query?" prompt
- Existing SessionService extended with a metadata JSON column for filter state

**B. Full UI snapshot** _(not recommended)_
- Serialize Textual widget tree to JSON
- Fragile, breaks on widget API changes, complex to implement
- No provider recommended this

**Synthesis recommendation:** ⚠️ **Option A: Data-only**

---

### Q6: How does "click [1] to jump to source" work in the document viewer?

**Question:** TUI-06 requires citation link navigation ("click [1] to jump to source"). The Gemini File Search API returns text excerpt snippets but NOT byte offsets or line numbers within the source file. How is jump-to-location implemented?

**Why it matters:** Without a position signal, the TUI cannot programmatically scroll to the exact line. This must be resolved before the document viewer is designed.

**Options:**

**A. Text-search fallback** _(recommended)_
- Load full document via `LibraryService.get_file_content(file_path)`
- Search for Citation.text excerpt string within the document
- Scroll viewer to first match; highlight all query term occurrences
- Works for 95% of cases; fails only if excerpt appears multiple times with identical text

**B. Require line offset from SearchService** _(Gemini raised as blocker)_
- Would need Gemini File Search to return character/line positions
- Not currently available in the API; would block TUI-06 indefinitely

**C. Highlight-only, no scroll-to** _(fallback)_
- Open document at top, highlight all query term occurrences
- Simpler than Option A; user scrolls manually to find highlighted terms

**Synthesis recommendation:** ⚠️ **Option A: Text-search fallback**
- Pragmatic; avoids waiting on API feature
- Degrade gracefully to Option C if excerpt text matching fails

---

## Tier 3: Polish Decisions (🔍 Single Provider)

### Q7: How does the layout adapt to narrow terminals?

**Question:** TUI-03 specifies a three-pane layout. What happens when the terminal is < 120 columns wide?

**Options:**
- **Wide (140+ cols):** Full three-pane (nav 20% | results 33% | preview 47%)
- **Medium (80–139 cols):** Two-pane (nav+results | preview)
- **Narrow (< 80 cols):** Single-pane stacked, Tab to switch

**Synthesis recommendation:** 🔍 **Three-mode responsive layout via Textual resize events**

---

### Q8: How do users access infrequently-used CLI commands through the TUI?

**Question:** TUI-08 requires all CLI functionality accessible from TUI. How without duplicating every command as a dedicated TUI screen?

**Options:**
- **Command palette (Ctrl+P):** Fuzzy-searchable list of all commands — power-user friendly
- **Context footer:** Show 4-5 relevant actions for the currently focused widget
- **Both** _(recommended)_: footer for frequent ops, palette for everything else

**Synthesis recommendation:** 🔍 **Both: context footer + Ctrl+P command palette**

---

*Multi-provider synthesis: OpenAI gpt-5.2 + Gemini Pro + Perplexity Sonar Deep Research*
*Generated: 2026-02-18*
