# CLARIFICATIONS-NEEDED.md

## Phase 5: Incremental Updates & Offline Mode — Stakeholder Decisions Required

**Generated:** 2026-02-18
**Mode:** Multi-provider synthesis (OpenAI gpt-5.2, Gemini Pro, Perplexity Sonar Deep Research)
**Source:** 3 AI providers analyzed Phase 5 requirements

---

## Decision Summary

**Total questions:** 13
**Tier 1 (Blocking):** 6 questions — Must answer before planning
**Tier 2 (Important):** 5 questions — Should answer for quality
**Tier 3 (Polish):** 2 questions — Can defer to implementation

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: Sync Atomicity — How to Handle Delete + Re-Upload?

**Question:** When a file changes, sync must delete the old Gemini entry and upload a new one. If the process crashes between these two operations, the file is absent from search. What ordering strategy should be used?

**Why it matters:** This is the core correctness guarantee for incremental updates. Wrong choice = permanent search coverage gaps.

**Options identified:**

**A. Upload-first (safe replace)**
- Upload NEW file → if success, update SQLite → attempt delete OLD (fire-and-forget)
- If crash after upload: old ID becomes orphan, new ID is live ✅ no coverage gap
- If crash during upload: old ID still live ✅ graceful fallback
- _(Proposed by: OpenAI, Gemini, Perplexity)_

**B. Delete-first**
- Delete OLD entry → upload NEW file
- If crash between delete and upload: file absent from search ❌ coverage gap
- _(Not recommended by any provider)_

**Synthesis recommendation:** ✅ **Option A — Upload-first**
- Store `old_gemini_file_id` in SQLite before deletion attempt
- Treat deletion failures as non-critical (log as `orphaned_gemini_file_id`)
- Add `sync --cleanup-orphans` for deferred cleanup pass

**Sub-questions:**
- Can Gemini File Search store have two files with the same display_name simultaneously? (Must test)
- Should orphan cleanup happen automatically on each sync startup, or only with explicit flag?

---

### Q2: Disk Availability Detection — How to Distinguish Disconnected Drive from Deleted Files?

**Question:** How should the system detect whether the USB drive is mounted vs. disconnected? And critically — how do we prevent sync from treating a disconnected drive as "all files deleted"?

**Why it matters:** Without reliable mount detection, a single `sync` run with a disconnected drive could wipe the entire Gemini index.

**Options identified:**

**A. Mount point check + directory listing**
- `os.path.isdir('/Volumes/U32 Shadow')` + `os.listdir('/Volumes/U32 Shadow')`
- Fails fast if unmounted, catches phantom mounts
- _(Proposed by: All 3 providers)_

**B. `os.path.ismount()` check**
- More semantically precise (identifies actual mount points)
- May not work as expected for subdirectories of mount
- _(Proposed by: Gemini)_

**Synthesis recommendation:** ✅ **Option A — Multi-layer check**
- Rule: orphan cleanup (Gemini deletion) NEVER runs unless disk check returns `available`
- `sync` and `scan` fail with error if disk unavailable

**Sub-questions:**
- Should the library root path be stored in SQLite config for consistency across sessions?

---

### Q3: Sync Pipeline — Enriched or Simple Upload?

**Question:** Should `sync` use the Phase 6.2 enriched upload pipeline (AI metadata injection) or the simpler Phase 2 pipeline? Using simpler pipeline means re-uploaded files lose their AI metadata.

**Why it matters:** Creates two-tier index quality if different pipelines are used for initial upload vs. incremental updates.

**Options identified:**

**A. Always enriched**
- `sync` reuses Phase 6.2 EnrichedUploadOrchestrator
- All files have consistent AI metadata enrichment
- May be slower (requires AI metadata extraction per changed file)
- _(Proposed by: OpenAI, Gemini)_

**B. Simple by default, enriched on demand**
- `sync` uses Phase 2 pipeline; `sync --enrich` uses enriched pipeline
- Faster by default; enrichment is opt-in
- Creates temporary quality inconsistency for changed files
- _(Proposed by: Perplexity as pragmatic option)_

**Synthesis recommendation:** ✅ **Option A — Always enriched (with `--skip-enrichment` escape hatch)**
- Library files rarely change, so cost is negligible
- Consistent index quality is worth the occasional extra latency

**Sub-questions:**
- If AI metadata extraction fails for a changed file, should sync fall back to raw upload or skip the file entirely?

---

### Q4: Orphan Deletion Policy — When to Delete Gemini Entries for Removed Files?

**Question:** When sync detects a file in SQLite that no longer exists on disk, how quickly should it delete the Gemini entry? Immediate deletion risks catastrophic loss if disk was just disconnected.

**Why it matters:** Aggressive deletion = data loss risk. No deletion = Gemini index grows stale.

**Options identified:**

**A. Grace period (mark-then-delete)**
- Mark as `status='missing'` on first detection; delete from Gemini only after N days or explicit flag
- Safe from transient disconnects; requires monitoring `missing_since` column
- _(Proposed by: OpenAI, Perplexity)_

**B. Immediate with confirmation**
- Delete immediately from Gemini on first detection but require `--prune-missing` flag explicitly
- Unambiguous but requires manual step; no automatic cleanup
- _(Proposed by: Gemini — implied by mount-check-first approach)_

**C. Dry-run first**
- `sync` shows what would be deleted but never deletes automatically
- User runs `sync --prune-missing` to actually delete

**Synthesis recommendation:** ✅ **Option A + C combined**
- Mark as `missing`, never auto-delete
- Require explicit `sync --prune-missing` flag
- Default N = 7 days for `--prune-missing` auto-mode
- Always support `sync --dry-run` to preview deletions

---

### Q5: Partial Sync Failure — How to Resume After Crash?

**Question:** If sync processes 50 of 100 files and crashes, how does the system recover? What state should the database be in and how should restart work?

**Why it matters:** Without proper recovery, restarting sync wastes time re-processing files or creates duplicates.

**Options identified:**

**A. Per-file commit (existing pattern)**
- SQLite committed after each successful file (already done in Phase 2 upload pipeline)
- On restart: files with `status='indexed'` + same `content_hash` are skipped
- Files with `status='pending_upload'` or `status='error'` are retried
- _(Proposed by: All 3 providers)_

**B. Sync session tracking**
- Separate `sync_sessions` table records batch progress with checkpoint
- More auditable but adds schema complexity
- _(Proposed by: Perplexity)_

**Synthesis recommendation:** ✅ **Option A — Reuse per-file commit pattern (Phase 2 approach)**
- Per-file SQLite commits already proven in upload pipeline
- Errors → mark `status='error'`, continue batch, report summary at end
- Add sync session ID to log output for debugging

---

### Q6: Gemini 48-Hour TTL — How to Handle Stale File References?

**Question:** When sync tries to delete an old Gemini file ID, the raw file may have already expired (48h TTL). Does a 404 mean the indexed data is also gone? Should we treat 404 as success?

**Why it matters:** Wrong handling could leave stale indexed data in the search store, or fail unnecessarily on already-expired entries.

**Options identified:**

**A. Treat 404 on deletion as success (raw file expired)**
- `try/except NotFound` — proceed as if deletion succeeded
- But verify: does raw file expiry auto-remove File Search Store entry?
- _(Proposed by: All 3 providers)_

**B. Always use store-level deletion API (not raw file delete)**
- Call File Search Store document deletion endpoint directly
- Independent of raw file TTL
- _(Proposed by: OpenAI, Perplexity)_

**Synthesis recommendation:** ✅ **Option B preferred; Option A as fallback**
- Use store-document deletion API if available in google-genai SDK
- Wrap in `try/except NotFound` — 404 is acceptable (already gone)
- Test: does raw file expiry auto-remove store entry?

---

## Tier 2: Important Decisions (⚠️ Recommended)

### Q7: File Identity for Renames/Moves

**Question:** If a file in the library is renamed or moved to a different subfolder, should sync treat it as the same document (continuity) or as delete+add (new entry)?

**Synthesis recommendation:** ⚠️ **Delete+add (treat rename as delete of old path + new file)**
- Path is the primary key in SQLite — renames create new records
- Library files almost never rename after initial scan
- Simplest implementation

---

### Q8: What Content is Hashed for Change Detection?

**Question:** Should `content_hash` track raw file bytes OR enriched content? Should enrichment prompt changes trigger re-upload of unchanged source files?

**Synthesis recommendation:** ⚠️ **Two hashes**
- Keep `content_hash` = SHA-256 of raw file bytes (existing behavior)
- Add `upload_hash` = SHA-256 of enriched bytes actually uploaded
- Add `enrichment_version` = short hash of enrichment config
- Sync re-uploads if `source_hash` OR `enrichment_version` changed

---

### Q9: Offline Metadata — Is SQLite `metadata_json` Sufficient?

**Question:** For `view` (metadata-only mode) to work offline, does `metadata_json` in the files table contain everything needed? Or is some metadata only stored in Gemini (injected content)?

**Why it matters:** If metadata lives only in Gemini-injected content, offline metadata view is impossible without fetching from API.

**Synthesis recommendation:** ⚠️ **Verify before planning**
- Phase 6 should have stored extracted metadata in `metadata_json`
- Must confirm `view` command reads from SQLite not Gemini for metadata display
- If gap found, add schema migration to populate missing metadata in SQLite

---

### Q10: Offline Scope — Disk-Offline Only, or Also Network-Offline?

**Question:** Phase 5 says "Gemini + SQLite only" for offline mode — meaning Gemini API is still available. Should Phase 5 also handle the case where Gemini is unreachable?

**Synthesis recommendation:** ⚠️ **Disk-offline only for Phase 5**
- "Offline mode" = USB drive not connected but internet/Gemini available
- Network-offline graceful degradation is out of scope (existing error handling covers it)
- Document clearly: "offline" means disk-offline

---

### Q11: mtime Hybrid Optimization

**Question:** Should sync use a hybrid mtime+hash strategy to skip full SHA-256 computation for files that haven't changed by mtime? Potentially faster for 1,749-file scans.

**Synthesis recommendation:** ⚠️ **Implement mtime optimization**
- Store `mtime` in SQLite alongside `content_hash`
- If `mtime` matches: skip hash computation (assume unchanged)
- If `mtime` differs: compute hash (confirm actual change)
- APFS/HFS+ on macOS: mtime is reliable

---

## Tier 3: Polish Decisions (🔍 Needs Clarification)

### Q12: Enrichment Configuration Versioning

**Question:** Should sync track which enrichment version was used per file and re-upload when enrichment config changes?

**Synthesis recommendation:** 🔍 **Implement `enrichment_version` column**
- Hash of (prompt template + model + injection schema)
- `--force` flag already handles full re-enrichment as manual override
- Can be added as optional enhancement in Phase 5 or deferred

---

### Q13: Gemini Store Consistency Guard

**Question:** Should the system validate that the CLI's configured store name matches the stored store name in SQLite before running destructive operations?

**Synthesis recommendation:** 🔍 **Add store name to SQLite config table**
- Prevents accidental operations against wrong Gemini store
- Fail with clear error: "Store mismatch: CLI configured 'X' but SQLite records 'Y'"
- High safety value for low implementation cost

---

## Next Steps (YOLO Mode — Auto-Answers Generated)

CLARIFICATIONS-ANSWERED.md will be auto-generated using synthesis recommendations above.
Then proceed to `/gsd:plan-phase 5`.

---

*Multi-provider synthesis: OpenAI gpt-5.2 + Gemini Pro + Perplexity Sonar Deep Research*
*Generated: 2026-02-18*
*YOLO mode: Auto-answers will be generated*
