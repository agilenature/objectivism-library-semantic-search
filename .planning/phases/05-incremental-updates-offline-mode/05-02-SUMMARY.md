---
phase: 05-incremental-updates-offline-mode
plan: 02
subsystem: api, upload
tags: [gemini, file-search-stores, documents-api, store-management]

requires:
  - phase: 02-upload-pipeline
    provides: GeminiFileSearchClient with upload/import/delete_file methods
provides:
  - delete_store_document() for removing indexed entries from search store
  - list_store_documents() for discovering document resource names
  - find_store_document_name() for file-to-document lookup
affects: [05-03, 05-04, sync-orchestrator, orphan-cleanup]

tech-stack:
  added: []
  patterns:
    - "404-as-success pattern for idempotent deletion (locked decision #6)"
    - "AsyncPager iteration via _safe_call + async for"

key-files:
  created: []
  modified:
    - src/objlib/upload/client.py

key-decisions:
  - "list_store_documents wraps initial list() call in _safe_call for circuit breaker; pagination fetches bypass circuit breaker (acceptable tradeoff)"
  - "find_store_document_name checks display_name and name attributes based on actual Document type schema (not hypothetical file_name/source_file)"
  - "delete_store_document catches exceptions broadly then inspects string for 404/NOT_FOUND patterns (SDK may raise various exception types)"

patterns-established:
  - "Store document management via file_search_stores.documents.{delete,list} endpoints"
  - "Idempotent deletion: 404/NOT_FOUND returns True (not exception)"

duration: 2min
completed: 2026-02-18
---

# Phase 5 Plan 2: Store Document Management Summary

**Three new GeminiFileSearchClient methods for store-level document deletion, listing, and lookup via file_search_stores.documents API**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-18T11:16:06Z
- **Completed:** 2026-02-18T11:18:04Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Added `delete_store_document()` with 404=success handling per locked decision #6
- Added `list_store_documents()` with async pagination via SDK's AsyncPager
- Added `find_store_document_name()` for O(n) scan-based file-to-document lookup
- Updated `delete_file()` docstring to clearly distinguish raw file deletion from indexed store document removal

## Task Commits

Each task was committed atomically:

1. **Task 1: Add store document management methods** - `adb5c4f` (feat)

## Files Created/Modified
- `src/objlib/upload/client.py` - Added delete_store_document(), list_store_documents(), find_store_document_name() methods; updated delete_file() docstring

## Decisions Made
- Used `_safe_call` for both `delete` and `list` API calls to maintain circuit breaker integration
- Inspected actual SDK `Document` type: has `name`, `display_name`, `state`, `size_bytes`, `mime_type`, `create_time`, `custom_metadata`, `update_time` -- no `file_name` or `source_file` attributes
- Adjusted `find_store_document_name` to check `display_name` and `name` (matching actual SDK schema) instead of hypothetical attributes from plan

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected find_store_document_name attribute checks**
- **Found during:** Task 1 (implementation)
- **Issue:** Plan specified checking `file_name`, `source_file` attributes on Document objects, but SDK inspection showed Document type only has `name`, `display_name`, `state`, etc.
- **Fix:** Changed attribute checks to `display_name` and `name` (actual Document attributes)
- **Files modified:** src/objlib/upload/client.py
- **Verification:** Confirmed via `inspect.getsource(Document)` that these are the correct attributes
- **Committed in:** adb5c4f (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential correction based on actual SDK inspection. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Store document management methods ready for sync orchestrator (05-03)
- `delete_store_document()` enables orphan cleanup and file pruning workflows
- `list_store_documents()` enables store inventory comparison with local database

---
*Phase: 05-incremental-updates-offline-mode*
*Completed: 2026-02-18*
