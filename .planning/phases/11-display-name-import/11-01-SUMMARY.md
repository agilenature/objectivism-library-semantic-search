---
phase: 11-display-name-import
plan: 01
subsystem: api
tags: [gemini, file-search, display_name, import-lag, spike, measurement]

# Dependency graph
requires:
  - phase: 10-transition-atomicity
    provides: "Phase 10 gate PASSED -- Phase 11 unblocked"
provides:
  - "Empirical evidence that File.display_name is 100% caller-controlled (13/13 exact match)"
  - "Discovery that Document.display_name = file ID, not submitted name"
  - "Import-to-visible lag P50/P95/P99 data for documents.get() and documents.list()"
  - "Recommended polling parameters for Phase 12 upload FSM"
  - "Edge case: leading whitespace causes import hang"
affects: [11-02-trigger-strategy, 12-fsm-upload, upload-orchestrator, citation-mapping]

# Tech tracking
tech-stack:
  added: []
  patterns: ["SDK source inspection via inspect.getfile + regex", "exponential backoff visibility polling", "two-method visibility check (get vs list)"]

key-files:
  created:
    - spike/phase11_spike/__init__.py
    - spike/phase11_spike/sdk_inspector.py
    - spike/phase11_spike/test_corpus.py
    - spike/phase11_spike/lag_measurement.py
    - spike/phase11_spike/spike.py
    - spike/phase11_spike/RESULTS.md
  modified: []

key-decisions:
  - "File.display_name is caller-controlled: 13/13 exact round-trip match across special chars, case, spaces, long names"
  - "Document.display_name = file resource ID, NOT submitted display_name -- 0/13 match"
  - "documents.get() is 2x faster than documents.list() for visibility checks (P50: 0.243s vs 0.495s)"
  - "No exponential backoff needed for visibility -- documents are visible immediately after import completes"
  - "Leading whitespace in display_name can cause import to hang indefinitely -- defensive strip() recommended"
  - "No file size correlation with visibility lag"

patterns-established:
  - "Phase 11 spike pattern: SDK source inspection + live API round-trip measurement"
  - "Document name format: fileSearchStores/{store_id}/documents/{doc_id}"
  - "Import operation response: document_name is just doc_id, needs full path construction"

# Metrics
duration: 22min
completed: 2026-02-20
---

# Phase 11 Plan 01: display_name Import Spike Summary

**HOSTILE-distrust spike proving File.display_name is 100% caller-controlled (13/13 exact match), discovering Document.display_name is file ID (not submitted name), and measuring import-to-visible lag at P50=0.243s via documents.get()**

## Performance

- **Duration:** 22 min
- **Started:** 2026-02-20T16:03:49Z
- **Completed:** 2026-02-20T16:26:47Z
- **Tasks:** 2
- **Files created:** 6

## Accomplishments
- Collected SDK source evidence confirming display_name passes through without transformation (files.py lines 527/1066, types.py, _common.py alias_generator)
- Ran 14-file round-trip test against live Gemini API -- 13/13 successful uploads returned EXACT display_name match across all edge cases (special chars, case, spaces, 500-char names)
- Discovered that Document.display_name = file resource ID, not submitted name -- critical finding for citation mapping
- Measured import-to-visible lag: documents.get() P50=0.243s, P95=0.252s; documents.list() P50=0.495s, P95=0.646s
- Identified edge case: leading whitespace causes import to hang (import operation never completes)
- Test store created and fully cleaned up -- no production pollution

## Task Commits

Each task was committed atomically:

1. **Task 1: SDK inspector + test corpus + lag measurement modules** - `e7fec4c` (feat)
2. **Task 2: Combined spike runner + RESULTS.md** - `d29d482` (feat)

## Files Created/Modified
- `spike/phase11_spike/__init__.py` - Package init
- `spike/phase11_spike/sdk_inspector.py` - Programmatic SDK source evidence collection
- `spike/phase11_spike/test_corpus.py` - 14 test files with edge-case display_names across 4 size buckets
- `spike/phase11_spike/lag_measurement.py` - Visibility lag polling with exponential backoff + percentile computation
- `spike/phase11_spike/spike.py` - Combined 5-phase runner (SDK inspect, store setup, round-trip, stats, cleanup)
- `spike/phase11_spike/RESULTS.md` - Full empirical results document

## Decisions Made
- File.display_name is trustworthy: 13/13 exact round-trip match including parentheses, ampersands, periods, trailing spaces, 500-char names
- Document.display_name is NOT the submitted name -- it is the file resource ID. Citation mapping must use file_id -> DB lookup (which objlib already does correctly)
- documents.get() should be the primary visibility check (2x faster than list, O(1) vs paginated scan)
- No polling loop needed for visibility after import -- documents are immediately visible
- Leading whitespace in display_name should be stripped defensively before upload

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed document_name path construction**
- **Found during:** Task 2 (spike runner, first run attempt)
- **Issue:** Import operation returns document_name as just the doc ID (e.g., `abc-xyz`), but documents.get() requires the full resource path (`fileSearchStores/{store}/documents/{doc_id}`). All visibility checks timed out at 300s.
- **Fix:** Added path construction logic: if document_name lacks `/`, prepend `{store_name}/documents/`
- **Files modified:** spike/phase11_spike/spike.py
- **Verification:** Second run showed all visibility checks completing in <1s
- **Committed in:** d29d482 (Task 2 commit)

**2. [Rule 1 - Bug] Fixed document fallback matching**
- **Found during:** Task 2 (spike runner, first run investigation)
- **Issue:** Fallback listing matched on submitted display_name, but Document.display_name is actually the file ID, not the submitted name
- **Fix:** Changed fallback to match on file_id instead of display_name
- **Files modified:** spike/phase11_spike/spike.py
- **Verification:** Fallback path tested by observation of document properties in list output
- **Committed in:** d29d482 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** Both fixes were necessary for correct operation. The document_name path construction bug would have caused all 14 measurements to time out. The discovery that Document.display_name != submitted name was itself a key finding of the spike.

## Issues Encountered
- First spike run failed: all visibility measurements timed out at 300s due to incorrect document_name path. Required killing the process, cleaning up the test store, fixing the code, and re-running. Added ~7 min to total duration.
- Leading spaces test case (index 8) import operation never completed -- timed out at 120s. This is an API behavior, not a code bug. Documented as a finding in RESULTS.md.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All SC1 (display_name stability) and SC2 (import lag) data collected
- Ready for Plan 11-02: trigger strategy decision based on this measurement data
- Key parameters for Phase 12 upload FSM identified: single documents.get() for visibility, strip leading whitespace, 120s import timeout
- Document.display_name behavior documented -- citation mapping audit recommended for Phase 12

## Self-Check: PASSED

- All 7 files verified present
- Both task commits (e7fec4c, d29d482) verified in git log

---
*Phase: 11-display-name-import*
*Completed: 2026-02-20*
