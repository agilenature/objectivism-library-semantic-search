# CLARIFICATIONS-NEEDED.md

## Phase 1: Foundation — Stakeholder Decisions Required

**Generated:** 2026-02-15
**Mode:** Multi-provider synthesis (Gemini, Perplexity)
**Source:** 2 AI providers analyzed Phase 1 requirements

---

## Decision Summary

**Total questions:** 8
**Tier 1 (Blocking):** 5 questions — Must answer before planning
**Tier 2 (Important):** 2 questions — Should answer for quality
**Tier 3 (Polish):** 1 question — Can defer to implementation

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: Primary Key Strategy for File Tracking

**Question:** Should the database use file path or content hash as the primary key?

**Why it matters:** This decision affects how the system handles file moves and duplicate detection. FOUN-06 requests "idempotency keys using content hashes" (suggests hash as PK), but FOUN-04 requires metadata from folder structure (suggests path as PK). A file moved from `/Course/Drafts/Lecture1.txt` to `/Course/Final/Lecture1.txt` has identical content hash but different metadata.

**Options identified by providers:**

**A. File path as primary key**
- Use `file_path` (TEXT PRIMARY KEY) with `content_hash` as indexed column
- Treats file moves as metadata changes requiring re-extraction
- Enables efficient "find file by path" queries
- _(Proposed by: Gemini, Perplexity)_

**B. Content hash as primary key**
- Use `content_hash` (BLOB PRIMARY KEY) with `file_path` as indexed column
- Treats file moves as location changes, preserves upload state
- Better for deduplication
- _(Proposed by: None explicitly)_

**C. Composite approach**
- Track both path and hash separately with composite key
- Most flexible but more complex
- _(Proposed by: Perplexity)_

**Synthesis recommendation:** ✅ **Option A (File path as primary key)**
- Reflects that folder structure carries pedagogical metadata
- File move = metadata change = correct to re-extract
- Prevents duplicate content uploads via UNIQUE constraint on hash

**Sub-questions:**
- Does Gemini API allow uploading files with identical content from different paths?
- Should duplicate content (same hash, different paths) share one Gemini upload or upload separately?

---

### Q2: Metadata Storage Strategy

**Question:** Should extracted metadata use dedicated SQL columns (rigid but queryable) or JSON blob (flexible but harder to query)?

**Why it matters:** Hardcoded columns like `quarter`, `instructor` make schema rigid when patterns evolve. JSON blobs are flexible but make SQL filtering difficult. Requirements don't specify which metadata fields need SQL querying.

**Options identified by providers:**

**A. Hybrid schema (core columns + JSON blob)**
- Core columns: id, path, hash, status, timestamps
- JSON column: `metadata_json` storing all extracted fields
- Separate table: `metadata_validation_log` for quality tracking
- _(Proposed by: Gemini, Perplexity)_

**B. Fully normalized (dedicated columns)**
- Separate `folder_metadata` and `filename_metadata` tables
- All fields queryable via SQL
- Requires schema migrations for new patterns
- _(Proposed by: Perplexity)_

**C. Pure JSON (single blob)**
- All metadata in one JSON column
- Maximum flexibility
- Limited SQL querying capability
- _(Proposed by: None explicitly)_

**Synthesis recommendation:** ✅ **Option A (Hybrid schema)**
- Quick iteration on metadata extraction without schema migrations
- Efficient status queries (`WHERE status = 'PENDING'`)
- Future promotion of high-value fields to columns if needed

**Sub-questions:**
- Which metadata fields will Phase 3 query/filter most frequently?
- Should course, difficulty, or topic be promoted to columns now?

---

### Q3: Unknown Metadata Handling

**Question:** How should the scanner handle files that don't match expected naming patterns (e.g., `ReadMe.txt`, `syllabus_v2.pdf`)?

**Why it matters:** With 1,749 files, some will break conventions. Should scanner fail, skip, or store with null metadata?

**Options identified by providers:**

**A. Permissive extraction with quality tracking**
- Always create DB record, even if regex fails
- Store failed extractions as `null` in JSON metadata
- Add `metadata_quality` column (enum: complete, partial, minimal, none)
- Log unparsed patterns to separate `_extraction_failures` table
- _(Proposed by: Gemini, Perplexity)_

**B. Strict validation (fail on unparsed)**
- Reject files that don't match patterns
- Require manual intervention
- Ensure data consistency
- _(Proposed by: None)_

**C. Skip unparsed files**
- Silently ignore files that don't match
- Continue scanning other files
- _(Proposed by: None)_

**Synthesis recommendation:** ✅ **Option A (Permissive with quality tracking)**
- Better to have file searchable with limited metadata than missing entirely
- Quality tracking enables later review of problematic patterns

**Sub-questions:**
- Should files with zero extracted metadata be flagged for manual review?
- Are there "junk" files (`.DS_Store`, `Thumbs.db`) to explicitly ignore?

---

### Q4: 48-Hour Expiration Tracking

**Question:** How to model the 48-hour expiration in the database schema before API integration exists?

**Why it matters:** FOUN-07 mentions "prevent 48-hour expiration issues". Phase 1 is offline, but schema must support Phase 2 upload tracking.

**Options identified by providers:**

**A. Track upload timestamp + computed expiration**
- `upload_timestamp` (DATETIME, null in Phase 1)
- `remote_expiration_ts` (DATETIME, null in Phase 1)
- Set both during Phase 2 upload, check before querying
- _(Proposed by: Gemini, Perplexity)_

**B. Track expiration timestamp only**
- Single `expiration_ts` column set to `now + 48h` after upload
- Simpler but loses upload time information
- _(Proposed by: Gemini)_

**C. Dynamic computation (no storage)**
- Only store `upload_timestamp`
- Compute expiration status on read
- No redundant data
- _(Proposed by: Perplexity variant)_

**Synthesis recommendation:** ✅ **Option A (Track both timestamps)**
- Explicit tracking prevents edge cases
- Upload timestamp useful for audit trail
- Expiration timestamp enables efficient queries

**Sub-questions:**
- Does 48-hour expiration apply to raw uploaded files or vector store cache?
- Should expired status trigger automatic re-upload?

---

### Q5: Metadata Extraction Pattern Specification (BLOCKING)

**Question:** What are the exact folder naming conventions in the library?

**Why it matters:** Requirements mention `Course/Year/Quarter/Week` patterns but don't define them. Folder names might vary: "PHIL101" vs "History-of-Metaphysics" vs "Kant-Critique". Without examples, can't write reliable regex patterns.

**Options identified by providers:**

**A. Three-tier pattern matching**
1. Exact mapping config (JSON file mapping known folders to metadata)
2. Regex patterns for common conventions
3. Fallback storage of unparsed folder names
- _(Proposed by: Perplexity)_

**B. Sample-based pattern discovery**
- Scan actual library first
- Identify patterns from real data
- Build extraction rules iteratively
- _(Proposed by: Implicit in both providers)_

**C. Flexible regex with manual review**
- Permissive patterns that capture common structures
- Flag unusual patterns for review
- _(Proposed by: Gemini)_

**Synthesis recommendation:** 🔍 **Cannot finalize until examples provided**
- Requires 10-20 example file paths from actual library
- Will use three-tier approach once patterns known

**Sub-questions:**
- ❓ **BLOCKING:** Can you provide 10-20 example file paths from the actual library?
- Are there standardized course codes or conventions already in use?
- Should unmatched patterns trigger warnings or silent degradation?

---

## Tier 2: Important Decisions (⚠️ Recommended)

### Q6: File Type Allow-List

**Question:** Which file extensions should be processed during scanning?

**Why it matters:** "Recursive discovery" could mean scan everything. Library might contain images, executables, hidden system files. Hashing non-text files wastes resources.

**Options identified by providers:**

**A. Strict allow-list with defaults**
- Extensions: `{'.txt', '.md', '.pdf', '.epub', '.docx', '.html'}`
- Skip hidden files (starting with `.`)
- Minimum file size: 1 KB
- Log skipped files for review
- _(Proposed by: Gemini, Perplexity)_

**B. Permissive (scan all text-like files)**
- Detect MIME types dynamically
- Process anything that looks like text
- _(Proposed by: None)_

**C. User-configurable with no defaults**
- Require explicit configuration
- No assumptions about file types
- _(Proposed by: None)_

**Synthesis recommendation:** ⚠️ **Option A (Strict allow-list)**
- Architectural best practice to avoid processing non-content files
- Configurable for future expansion

**Sub-questions:**
- What file types actually exist in the library?
- Should image files (scanned manuscripts) be included?

---

### Q7: Orphaned Database Records

**Question:** What happens to DB records when a file is deleted from disk?

**Why it matters:** Scanner finds current files, but deleted files remain in DB as "ghosts". Should they be deleted immediately or marked for cleanup?

**Options identified by providers:**

**A. Soft delete with cleanup workflow**
1. Scanner compares disk files vs. DB records
2. Missing files marked `status = 'LOCAL_DELETE'`
3. Preserve record until Phase 2 confirms Gemini cleanup
4. Add `purge` command to remove old LOCAL_DELETE records
- _(Proposed by: Gemini, Perplexity)_

**B. Immediate hard delete**
- Remove DB record as soon as file missing
- Simpler but loses Gemini ID for cleanup
- _(Proposed by: None)_

**C. Separate tracking table**
- Move deleted files to `deleted_files` table
- Preserve history separate from active files
- _(Proposed by: Perplexity variant)_

**Synthesis recommendation:** ⚠️ **Option A (Soft delete)**
- Standard pattern for distributed system cleanup
- Need `gemini_id` to send delete command to API in Phase 2

**Sub-questions:**
- Should purge be automatic after successful Gemini deletion or manual?

---

## Tier 3: Implementation Details

### Q8: Symlink Handling Strategy

**Question:** Should symbolic links be followed, ignored, or treated as special cases?

**Why it matters:** Philosophical libraries might use symlinks for cross-referencing. Following symlinks could create infinite loops. Ignoring them could miss content.

**Options identified by providers:**

**A. Follow symlinks with cycle detection**
- Track `visited_inodes` (device + inode pairs)
- Skip symlinks pointing to already-visited targets
- Log circular references as warnings
- _(Proposed by: Perplexity)_

**B. Ignore all symlinks**
- Skip symlinks entirely
- Simplest, safest approach
- _(Proposed by: None explicitly)_

**C. Follow once (no recursion)**
- Follow symlinks but don't traverse further
- Middle ground approach
- _(Proposed by: None)_

**Synthesis recommendation:** 🔍 **Option A (Follow with cycle detection)**
- Safe default with cycle protection
- Can be configured if not needed

**Sub-questions:**
- Are symlinks used intentionally in the library?
- Should symlink resolution use actual file path or symlink path in metadata?

---

## Next Steps (Non-YOLO Mode)

**✋ PAUSED — Awaiting Your Decisions**

1. **Review these 8 questions**
2. **Provide answers** (create CLARIFICATIONS-ANSWERED.md manually, or tell Claude your decisions)
3. **Then run:** `/gsd:plan-phase 1` to create execution plan

---

## Alternative: YOLO Mode

If you want Claude to auto-generate reasonable answers:

```bash
/meta-gsd:discuss-phase-ai 1 --yolo
```

This will:
- Auto-select recommended options (marked ✅ ⚠️ above)
- Generate CLARIFICATIONS-ANSWERED.md automatically
- Proceed to planning without pause

---

*Multi-provider synthesis: Gemini + Perplexity (OpenAI connection issue)*
*Generated: 2026-02-15*
*Non-YOLO mode: Human input required*
