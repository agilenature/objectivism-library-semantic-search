# CLARIFICATIONS-ANSWERED.md

## Phase 7: Interactive TUI — Decisions

**Generated:** 2026-02-18
**Mode:** YOLO (balanced strategy — unanimous consensus where available, best-practice recommendation otherwise)

---

## Decision Summary

**Total questions:** 8
**Tier 1 (Blocking):** 3 answered
**Tier 2 (Important):** 3 answered
**Tier 3 (Polish):** 2 answered

---

## Tier 1: Blocking Decisions

### Q1: Which TUI framework?

**YOLO DECISION:** **Textual**

**Rationale:**
- Confidence: ✅ All 3 providers unanimous
- Async-native: Textual runs on asyncio; `await search_service.search()` works directly in event handlers without any bridge code
- Rich-native: existing formatter.py renderables (panels, tables) render inside Textual widgets without modification
- Workers API: `@work(exclusive=True)` solves debounce + cancellation in one decorator
- Built-in widgets: Input, Tree, DataTable, ScrollableContainer, mouse support all included
- CSS-like grid layout: three-pane split declared in TCSS, not computed manually

**TUI entry point pattern:**
```python
# src/objlib/cli.py
@app.command()
def tui():
    """Launch interactive TUI."""
    from objlib.tui.app import ObjlibTUI
    ObjlibTUI().run()
```

---

### Q2: How do async and sync services integrate?

**YOLO DECISION:** **Textual workers for SearchService; `asyncio.to_thread()` selectively for sync services**

**Rationale:**
- Confidence: ✅ Consensus on SearchService; ⚠️ Recommended for sync wrapping
- SearchService: `@work(exclusive=True)` — non-negotiable, enforces Canon.json rule 3
- LibraryService filter queries and session saves: `asyncio.to_thread()` — these touch disk and can be slow
- LibraryService single-record reads (get_file_metadata): inline — SQLite single-row reads are sub-millisecond
- Never import `objlib.search` or `objlib.session` directly — only `objlib.services` (Canon rule 1)

**Sub-decisions:**
- Thread pool: default `ThreadPoolExecutor`, no custom sizing needed for personal use
- Timeout: no explicit timeout needed (SQLite on local disk won't hang)

---

### Q3: How does state flow between the three panes?

**YOLO DECISION:** **Centralized `AppState` with Textual Reactives and Message dispatch**

**Rationale:**
- Confidence: ✅ All 3 providers recommended this pattern
- Uni-directional: widgets post Messages upward to App; App updates AppState; reactive watchers trigger re-renders
- No widget-to-widget calls

**AppState design:**
```python
@dataclass
class AppState:
    query: str = ""
    results: list[Citation] = field(default_factory=list)
    filters: FilterSet = field(default_factory=FilterSet)
    selected_result_index: int | None = None
    search_history: list[str] = field(default_factory=list)
    bookmarks: set[str] = field(default_factory=set)
    is_searching: bool = False
    current_session_id: str | None = None
```

**Message types:**
- `SearchRequested(query, filters)` — fired by search input widget
- `ResultSelected(index)` — fired by results pane on keyboard/mouse selection
- `FilterChanged(filters)` — fired by filter pane
- `BookmarkToggled(file_path)` — fired by any pane
- `SessionSaveRequested` / `SessionLoadRequested(session_id)` — from menu/palette

---

## Tier 2: Important Decisions

### Q4: Live search debounce strategy?

**YOLO DECISION:** **300ms debounce + Textual `@work(exclusive=True)`**

**Rationale:**
- Confidence: ⚠️ Both providers recommended debounce; Textual workers eliminate stale-result problem automatically
- 300ms matches the minimum Gemini response time — no point firing faster
- `exclusive=True` means Textual cancels any running worker before starting a new one — stale results impossible
- Spinner visible in results pane header while `is_searching = True`

**Sub-decisions:**
- Minimum query length to trigger search: 2 characters (avoid firing on single letters)
- Empty query: revert to full browse mode (LibraryService.list_files())
- Debounce implemented via `asyncio.sleep(0.3)` at start of worker before calling SearchService

---

### Q5: What exactly gets saved/restored in a research session?

**YOLO DECISION:** **Data-only session persistence**

**Rationale:**
- Confidence: ⚠️ Both providers recommended data-only; full UI state serialization is fragile
- The existing `SessionService` (append-only events) is extended with a UI metadata column

**Saved:**
- Session name (auto-generated from first query if not named)
- Search history (query strings + timestamps)
- Filter state at save time (serialized as JSON: `{"course": "OPAR", "year_gte": 2020, "difficulty": "advanced"}`)
- Bookmarks (list of file_paths + optional note strings)

**NOT saved:**
- Scroll position in document viewer
- Pane sizes / focus state
- Currently selected result index
- In-progress search

**Restore behavior:**
- Rebuild filter controls from saved filter JSON
- Show bookmark list in nav pane
- Prompt: "Resume session: re-run last query '[query]'?" (yes / no)

**Schema extension needed:**
- Add `ui_metadata TEXT` column to sessions table (JSON blob for filter state + bookmark paths)
- This is a minor migration; existing session events continue unchanged

---

### Q6: Citation link / document jump implementation?

**YOLO DECISION:** **Text-search fallback (find excerpt in loaded document)**

**Rationale:**
- Confidence: ⚠️ Gemini flagged as potential blocker; text-search fallback is the pragmatic resolution
- Gemini File Search API does not return byte offsets — blocking on the API is not viable

**Implementation:**
1. User clicks `[1]` or presses Enter on a citation in results pane
2. Load full document: `LibraryService.get_file_content(citation.file_path)`
3. Search for `citation.text` excerpt string in document (exact match first; fuzzy substring fallback)
4. Scroll document viewer to first match position
5. Highlight all occurrences of query terms in visible buffer (regex-based)

**Graceful degradation:**
- If excerpt not found (truncated, normalized differently): open document at top, show all query term highlights
- Note displayed: "Jump to exact passage not available — showing term highlights"

---

## Tier 3: Polish Decisions

### Q7: Responsive layout for narrow terminals?

**YOLO DECISION:** **Three-mode layout with automatic resize detection**

- **Wide (140+ cols):** `HorizontalGroup(NavPane[20%], ResultsPane[33%], PreviewPane[47%])`
- **Medium (80–139 cols):** `HorizontalGroup(NavPane[40%], PreviewPane[60%])` with results embedded in nav
- **Narrow (< 80 cols):** Single pane stack; `Tab` cycles between Search / Results / Preview modes

Textual resize events: `on_resize()` handler switches between layout classes.

---

### Q8: CLI command access from TUI?

**YOLO DECISION:** **Context footer + Ctrl+P command palette**

- **Footer:** Always shows 4–5 context-relevant actions (e.g., when a document is focused: `[B]ookmark  [V]iew full  [C]opy path  [/]Search`)
- **Command palette (Ctrl+P):** Fuzzy-searchable list of all operations — maps to existing CLI commands

Commands registered in a `CommandRegistry`; each entry has `(name, description, handler, context_predicate)`. The palette shows all registered commands; the footer shows those where `context_predicate()` returns True.

---

## Architecture Summary

```
src/objlib/tui/
  __init__.py
  app.py          — ObjlibTUI(App): main Textual app, AppState, message handlers
  state.py        — AppState dataclass, FilterSet, Message subclasses
  panes/
    search.py     — SearchPane: Input widget + filter controls
    results.py    — ResultsPane: DataTable of Citations
    preview.py    — PreviewPane: document viewer with highlights
    nav.py        — NavPane: tree browser (category→course→file)
  widgets/
    search_input.py   — debounced input that posts SearchRequested
    citation_table.py — citation list with click-to-select
    doc_viewer.py     — scrollable viewer with text-search highlight
    filter_panel.py   — checkboxes/sliders for category, difficulty, year
  commands.py     — CommandRegistry, command palette implementation
  sessions.py     — session save/load bridge to SessionService
```

---

## Next Steps

1. ✅ Clarifications answered (YOLO mode — all 8 decisions made)
2. ⏭ Proceed to `/gsd:plan-phase 7`
3. 📋 Review YOLO decisions — particularly Q5 (session schema extension) and Q6 (citation jump) before implementation

---

*Auto-generated by discuss-phase-ai --yolo (balanced strategy)*
*All 3 providers unanimous on Tier 1. Human review recommended for Q5 and Q6.*
*Generated: 2026-02-18*
