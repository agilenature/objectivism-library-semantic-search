# CONTEXT.md — Phase 5: Incremental Updates & Offline Mode

**Generated:** 2026-02-18
**Phase Goal:** User can keep the search index current as the library grows AND query the library even when the source disk is disconnected — detecting new or changed files and updating only what changed, while enabling full query functionality without filesystem access.
**Synthesis Source:** Multi-provider AI analysis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research)

---

## Overview

Phase 5 combines two distinct capabilities: **incremental sync** (keeping Gemini index current without full re-upload) and **offline mode** (query operations work without USB disk). These interact in subtle ways — the sync architecture determines what data is locally available for offline use, and the offline detection logic must be shared across all commands.

The providers converged strongly on 6 consensus areas and diverged on nuanced questions around enrichment versioning and status modeling. The most critical decision is **sync atomicity**: Gemini's delete-then-reupload pattern creates a window where a crash leaves the file absent from the index. All 3 providers independently flagged this as the top blocker.

**Confidence markers:**
- ✅ **Consensus** — All 3 providers identified this as critical
- ⚠️ **Recommended** — 2 providers identified this as important
- 🔍 **Needs Clarification** — 1 provider identified, potentially important

---

## Gray Areas Identified

### ✅ 1. Sync Atomicity During File Re-Upload (Consensus)

**What needs to be decided:**
When a file changes, `sync` must delete the old Gemini entry and upload a new one. What happens if the process crashes between delete and upload? The file is absent from the search index during this window.

**Why it's ambiguous:**
The old entry must be deleted before or after the new upload — both orderings have failure risks. Delete-first risks losing search coverage; upload-first risks temporary duplicates.

**Provider synthesis:**
- **OpenAI:** Use transactional sequencing: upload new → update SQLite with new ID → attempt deletion of old (fire-and-forget; store `orphaned_gemini_file_id` if it fails)
- **Gemini:** "Safe Replace" — upload NEW first → if success, update SQLite → delete OLD (deletion is fire-and-forget). If crash after old deletion but before new upload, old content is gone; avoid this by always uploading first.
- **Perplexity:** WAL-style state machine: record intent in SQLite before any API call. States: `pending_upload` → `deleting_old` → `uploading` → `indexing` → `complete`. On restart, resume from last checkpoint.

**Proposed implementation decision:**
Upload-first strategy with idempotent cleanup:
1. Upload NEW file → get `new_gemini_file_id`
2. Record `new_gemini_file_id` + keep `old_gemini_file_id` in SQLite (set `status='indexed'`)
3. Attempt deletion of old ID — if fails/404, log as `orphaned_gemini_file_id` for later cleanup
4. On restart, any file with `orphaned_gemini_file_id != NULL` triggers cleanup pass

**Open questions:**
- Does Gemini File Search allow two files with the same display_name simultaneously? (If not, upload-first is blocked)
- Should there be a `sync --cleanup-orphans` command for deferred deletion?

**Confidence:** ✅ All 3 providers agreed this is blocking

---

### ✅ 2. Disk Availability Detection (Consensus)

**What needs to be decided:**
How to reliably detect whether the external USB drive is mounted on macOS — especially distinguishing "drive disconnected" from "specific file deleted."

**Why it's ambiguous:**
`os.path.exists()` returns `False` for both a missing file AND a disconnected drive. If `sync` misreads a disconnected drive as "all files deleted," it would wipe the entire Gemini index.

**Provider synthesis:**
- **OpenAI:** Define `LibraryAvailability` with states: `available`, `unavailable`, `degraded`. Check root path exists AND is readable AND can list directory contents.
- **Gemini:** Use `os.path.ismount(MOUNT_POINT)` where MOUNT_POINT = `/Volumes/U32 Shadow`. Only if mount check passes do individual file absence checks trigger orphan cleanup.
- **Perplexity:** Multi-layer check: `os.path.isdir()` + `os.listdir()` to confirm truly accessible. Catches phantom mounts and permission errors.

**Proposed implementation decision:**
```python
def check_disk_availability(library_root: str) -> str:
    """Returns: 'available', 'unavailable', 'degraded'"""
    mount_point = "/Volumes/U32 Shadow"
    if not os.path.isdir(mount_point):
        return 'unavailable'
    try:
        os.listdir(mount_point)  # Confirm accessible
    except OSError:
        return 'unavailable'
    if not os.path.isdir(library_root):
        return 'degraded'  # Volume mounted but path wrong
    return 'available'
```

Guard rule: `sync`/`scan`/`upload` only run orphan cleanup when disk returns `available`. Never trigger deletions when disk is `unavailable`.

**Open questions:**
- Should the library root path be stored in SQLite (config table) for cross-session consistency?
- If `/Volumes/U32 Shadow 1` appears (duplicate mount), should we warn?

**Confidence:** ✅ All 3 providers agreed this is blocking

---

### ✅ 3. Sync Pipeline: Enriched vs. Simple Upload (Consensus)

**What needs to be decided:**
Should `sync` use the enriched upload pipeline (Phase 6.2 — injects AI metadata content) or the simpler Phase 2 upload pipeline? This affects search quality for updated files.

**Why it's ambiguous:**
Using simple pipeline for `sync` means re-uploaded files lose AI metadata enrichment, creating a two-tier index (some files enriched, some not). Using enriched pipeline means `sync` triggers LLM calls for metadata, adding cost and latency.

**Provider synthesis:**
- **OpenAI:** Force enriched pipeline for `sync` since it's the right long-term approach; deprecate basic upload for maintenance
- **Gemini:** Force enriched pipeline — any file modified triggers full AI metadata generation + injection. Add `--fast` flag option for sync that skips enrichment if needed.
- **Perplexity:** Pragmatic middle ground: enriched pipeline for full re-index (`--force`), deferred enrichment for incremental sync with background maintenance task. OR use enriched always — cost is acceptable ($0.15/1M tokens).

**Proposed implementation decision:**
Use enriched pipeline by default for `sync`. Rationale: the library is static (files don't change frequently), so enrichment cost on changed files is negligible. Add `--skip-enrichment` flag for emergency fast sync. This maintains index consistency and avoids a two-tier quality problem.

**Open questions:**
- If AI metadata extraction fails for a changed file during sync, should sync fall back to raw upload or skip the file?
- Does the existing enriched-upload code support per-file incremental operation or only batch?

**Confidence:** ✅ All 3 providers agreed on enriched pipeline; method of delivery differs

---

### ✅ 4. Orphan Detection Safety and Deletion Policy (Consensus)

**What needs to be decided:**
When `sync` finds files in SQLite that no longer exist on disk, how aggressively should it delete them from Gemini? Immediate deletion risks catastrophic data loss if the disk was merely disconnected.

**Why it's ambiguous:**
A file "missing from disk" could mean: (a) actually deleted, (b) disk disconnected (caught by check #2), (c) file moved/renamed, (d) permissions issue. Only (a) warrants Gemini deletion.

**Provider synthesis:**
- **OpenAI:** Two-phase deletion: mark as `missing` on first detection, only delete from Gemini after N days (default 7) OR explicit `--prune-missing` flag. Prevents catastrophic deletion from transient disconnects.
- **Gemini:** Only trigger orphan cleanup after mount check confirms disk is available. File absence then definitely means deletion, not disconnection.
- **Perplexity:** Two-level orphan detection — lightweight after each sync batch (recently indexed files only), full scan as separate maintenance command `sync --cleanup-orphans`.

**Proposed implementation decision:**
- Phase 1 safety: Never auto-delete from Gemini during regular sync. Mark as `status='missing'` with `missing_since` timestamp.
- Only delete from Gemini when: (a) `sync --prune-missing` flag used, OR (b) `missing_since` > 7 days (configurable)
- Add dry-run: `sync --dry-run` shows what would be deleted without doing it

**Open questions:**
- Should `--force` imply deletion of missing files too, or keep deletion policy unchanged?
- Should there be a `sync --prune-missing --dry-run` safety preview?

**Confidence:** ✅ All 3 providers agreed this is blocking

---

### ✅ 5. Partial Sync Failure Recovery (Consensus)

**What needs to be decided:**
If `sync` processes 50 of 100 changed files and then crashes or hits a rate limit, how does the system recover? What database state exists and how does restart work?

**Why it's ambiguous:**
Without durable progress tracking, restarting sync from scratch would re-process already-uploaded files (wasteful, possibly creating duplicates). The current upload pipeline has resume capability but sync adds new complexity.

**Provider synthesis:**
- **OpenAI:** Explicit status model: `indexed`, `pending_upload`, `uploading`, `error`, `missing`, `deleted`, `orphan_cleanup_needed`. Each transition committed to SQLite before API call.
- **Gemini:** Atomic per-file processing — commit SQLite immediately after each successful file. Rate limit (429) → exponential backoff and retry. Error → mark `status='error'` and continue batch.
- **Perplexity:** Sync session table in SQLite tracking `last_checkpoint_file_id`. On restart, query session and resume from checkpoint. Idempotent operations prevent duplicate uploads.

**Proposed implementation decision:**
Per-file SQLite commits (already done in Phase 2 upload pipeline — reuse this pattern). Add `sync_session` tracking: on restart, files with `status='pending_upload'` or `status='error'` are retried. Files with `status='indexed'` and unchanged `content_hash` are skipped.

**Open questions:**
- Should errors block the whole sync or continue and report at end? (Recommend: continue, report summary)
- How many retries per file before marking `status='error'` and moving on?

**Confidence:** ✅ All 3 providers agreed this is blocking

---

### ✅ 6. Gemini 48-Hour TTL Interaction (Consensus)

**What needs to be decided:**
When `sync` tries to delete an old Gemini file entry for re-upload, the raw file may have already auto-expired (48-hour TTL). Does a 404 on deletion mean the indexed data is also gone?

**Why it's ambiguous:**
Gemini has two layers: raw File object (expires in 48h) and File Search Store entry (persists indefinitely). Deleting the raw file may or may not remove the store entry. A 404 on deletion doesn't confirm the indexed content is removed.

**Provider synthesis:**
- **OpenAI:** `try/except` deletion calls — 404 = raw file already expired, treat as success for raw file but verify store entry separately.
- **Gemini:** Use vector store-specific deletion API if available, not just generic file delete. Verify behavior: does deleting raw file auto-remove store entry?
- **Perplexity:** Delete from File Search Store documents collection directly (not just the raw File object). Treat 404 during deletion as acceptable — raw file expired but check if store entry remains.

**Proposed implementation decision:**
```python
def delete_gemini_entry(gemini_file_id: str, store_name: str):
    try:
        # Delete from File Search Store (persists indefinitely)
        client.delete_file_from_store(store_name, gemini_file_id)
    except NotFound:
        pass  # Already gone — acceptable
    # Note: raw file (48h TTL) may already be gone; that's fine
```
Always use store-level deletion (not raw file deletion) for index cleanup. Test whether raw file expiry auto-removes store entry.

**Open questions:**
- Does the Gemini File Search API expose separate `delete_from_store` vs `delete_file` endpoints in the google-genai SDK?
- If raw file expires before we do a planned re-upload, does the store entry become stale/searchable-but-empty?

**Confidence:** ✅ All 3 providers agreed on handling this

---

### ⚠️ 7. File Identity for Change Detection (Recommended)

**What needs to be decided:**
How does the system identify "the same file" across sync runs — especially when files are renamed or moved within the library? Is rename treated as delete+add, or is there continuity?

**Why it's ambiguous:**
Using absolute path as primary key means renames create orphan + new entry. Using relative path (relative to library root) is slightly better but still treats moves as delete+add. No inode-based tracking is implemented.

**Provider synthesis:**
- **OpenAI:** Library-root-relative path as primary identity key. Renames/moves = delete+add. Simple, deterministic, avoids macOS inode complexity.
- **Perplexity:** Agreed — for 1,749 files on a personal research tool, rename = delete+add is acceptable. Not worth complexity of inode tracking.

**Proposed implementation decision:**
Keep existing absolute path as primary key. Treat rename/move as delete+add. Document this behavior clearly. Library files rarely rename after initial scan.

**Confidence:** ⚠️ 2 providers agreed

---

### ⚠️ 8. What Exactly is Hashed for Change Detection (Recommended)

**What needs to be decided:**
Should `content_hash` track (a) raw file bytes on disk, or (b) the enriched content that was uploaded to Gemini? If enrichment changes (new prompt version), should that trigger re-upload even if the source file didn't change?

**Why it's ambiguous:**
Phase 6.2 enrichment modifies content before upload. If hash tracks raw bytes, enrichment changes are invisible to change detection. If hash tracks enriched bytes, enrichment prompt changes force full re-upload of unchanged files.

**Provider synthesis:**
- **OpenAI:** Two hashes: `source_hash` (raw file bytes) and `upload_hash` (SHA-256 of exact bytes uploaded). Change detection uses `source_hash`; enrichment config versioning handles prompt changes separately.
- **Perplexity:** Track `source_hash` for raw file. Use separate `enrichment_version` to detect when enrichment config changed.

**Proposed implementation decision:**
Keep existing `content_hash` as raw file SHA-256. Add `upload_hash` column for the enriched bytes actually uploaded. Add `enrichment_version` as a short hash of enrichment config. Sync triggers re-upload if `source_hash` OR `enrichment_version` differs from stored values.

**Confidence:** ⚠️ 2 providers agreed

---

### ⚠️ 9. Offline Mode: What Data is Available Without Disk (Recommended)

**What needs to be decided:**
`view` without `--full` should work offline. But what metadata is available? The current schema stores enriched metadata as injected file content in Gemini — not necessarily in SQLite. Is `metadata_json` in the files table sufficient for offline view?

**Why it's ambiguous:**
Phase 6.2 stores AI metadata in Gemini (injected into file content) but it's unclear if the SQLite `metadata_json` column captures the same 4-tier structured metadata for offline display.

**Provider synthesis:**
- **Gemini:** This is potentially the biggest blocker for OFFL-01/02. If metadata was only injected into Gemini upload content but not saved to SQLite, offline metadata view is impossible.
- **Perplexity:** SQLite must contain sufficient metadata for basic offline operations. Cache document summaries/key segments locally for offline view.

**Proposed implementation decision:**
Verify Phase 6 metadata (`metadata_json` column) is sufficient for offline `view`. It should be — Phase 6 extracts metadata from files and stores it in SQLite before injecting into Gemini. Confirm that `view` (metadata-only mode) reads from `metadata_json`, not from Gemini.

**Confidence:** ⚠️ 2 providers flagged this — needs verification

---

### ⚠️ 10. Disk Offline vs. Network Offline: Two Distinct Failure Modes (Recommended)

**What needs to be decided:**
"Offline mode" means disk unavailable but internet/Gemini available. Should the tool also handle "network offline" (Gemini unreachable)? These require different behavior.

**Why it's ambiguous:**
OFFL requirements say "Gemini + SQLite only" — implying Gemini API is still available. But users may interpret "offline" as fully disconnected.

**Provider synthesis:**
- **OpenAI:** Define two independent capabilities: disk offline and network offline. If disk offline + network online: semantic search works via Gemini. If network offline + disk online: view --full works but search fails. If both offline: browse/filter SQLite only.
- **Perplexity:** Layered resource availability check — `ResourceAvailability` class checks both disk and API, commands query it as guard clause.

**Proposed implementation decision:**
Implement `DiskAvailability` check (per gray area #2) and separate `APIAvailability` check (try Gemini ping). Phase 5 only needs to handle disk offline — network offline graceful degradation is out of scope (existing commands already fail gracefully on API errors). Document that "offline mode" means disk-offline, not network-offline.

**Confidence:** ⚠️ 2 providers recommended

---

### ⚠️ 11. mtime Hybrid Optimization for Change Detection Performance (Recommended)

**What needs to be decided:**
SHA-256 hashing 1,749 files on a USB drive on every `sync` may be slow (USB latency). Should `sync` use a hybrid mtime+hash strategy to skip hashing unchanged files?

**Why it's ambiguous:**
mtime on external USB drives can be unreliable (depends on filesystem). But full hash of every file may add 10-30 seconds of USB I/O on every sync.

**Provider synthesis:**
- **Gemini:** Hybrid mtime+hash: if `mtime` unchanged → skip hashing (assume no change). If `mtime` differs → compute hash. If hash unchanged (file was touched not modified) → update `mtime` only.
- **Perplexity:** For 1,749 files, full hashing is fast enough on typical hardware. mtime optimization is optional.

**Proposed implementation decision:**
Implement hybrid mtime+hash as optimization. Store `mtime` in SQLite alongside `content_hash`. If `mtime` matches → skip hash computation. On macOS with HFS+ or APFS, mtime is reliable.

**Confidence:** ⚠️ Gemini recommended; Perplexity considered optional

---

### 🔍 12. Enrichment Configuration Versioning (Needs Clarification)

**What needs to be decided:**
If the enrichment prompt, model, or injection format changes, should all files be re-enriched even if their source content didn't change?

**Why it's ambiguous:**
No existing mechanism tracks which enrichment version was used per file.

**Provider synthesis:**
- **OpenAI:** Add `enrichment_version` (hash of prompt template + model + schema + app version) to files table. Sync triggers re-upload if `enrichment_version` differs.

**Proposed implementation decision:**
Defer to Phase 5 planning. Likely add `enrichment_version` column. For now, `sync --force` handles full re-enrichment as manual override.

**Confidence:** 🔍 1 provider (OpenAI) recommended

---

### 🔍 13. Gemini Store Consistency Guard (Needs Clarification)

**What needs to be decided:**
Should the system prevent destructive operations (`sync`, `upload`) if the configured Gemini store name doesn't match the SQLite-recorded store name? Prevents accidentally wiping wrong index.

**Provider synthesis:**
- **OpenAI:** Persist `gemini_store_name` in SQLite config table. Verify configured store matches on startup. Abort if mismatch.

**Proposed implementation decision:**
Worth implementing as a safety check in sync. Store `gemini_store_name` in a library config table. Fail with clear error if store mismatch detected.

**Confidence:** 🔍 1 provider (OpenAI) recommended — but high-value safety measure

---

## Summary: Decision Checklist

Before planning, confirm:

**Tier 1 (Blocking):**
- [ ] Sync atomicity: upload-first strategy with orphaned ID tracking
- [ ] Disk detection: multi-layer mount check, never orphan-clean without confirmed disk
- [ ] Sync pipeline: enriched by default, `--skip-enrichment` flag for speed
- [ ] Orphan deletion policy: mark-missing first, delete only with explicit flag or age threshold
- [ ] Partial failure: per-file SQLite commits, resume from non-indexed files
- [ ] 48hr TTL: use store-level deletion, treat 404 as success

**Tier 2 (Important):**
- [ ] File identity: path-based, rename = delete+add
- [ ] Hash strategy: `source_hash` + `upload_hash` + `enrichment_version`
- [ ] Offline metadata: verify SQLite `metadata_json` sufficient for offline `view`
- [ ] Offline scope: disk-offline mode only (not network-offline) for Phase 5
- [ ] mtime hybrid optimization for sync performance

**Tier 3 (Polish):**
- [ ] Enrichment version tracking per file
- [ ] Gemini store consistency guard in SQLite config

---

## Next Steps (YOLO Mode)

CLARIFICATIONS-ANSWERED.md will be auto-generated. Proceed to `/gsd:plan-phase 5`.

---

*Multi-provider synthesis by: OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research*
*Generated: 2026-02-18*
