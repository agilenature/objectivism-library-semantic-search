# CLARIFICATIONS-NEEDED.md

## Phase 6.2: Metadata-Enriched Gemini Upload — Stakeholder Decisions Required

**Generated:** 2026-02-16
**Mode:** Multi-provider synthesis (Gemini Pro, Perplexity Deep Research)
**Source:** 2 AI providers analyzed Phase 6.2 requirements

---

## Decision Summary

**Total questions:** 5
**Tier 1 (Blocking):** 5 questions — Must answer before planning
**Tier 2 (Important):** 0 questions
**Tier 3 (Polish):** 0 questions

---

## Tier 1: Blocking Decisions (✅ Consensus)

### Q1: Metadata Flattening Strategy

**Question:** How should the complex 4-tier metadata (especially long-form Tier 4 semantic descriptions) be mapped into Gemini's flat custom_metadata format?

**Why it matters:** Gemini metadata is for filtering, not prose storage. Wrong approach bloats metadata or loses semantic value. Tier 4 summaries (500+ words) don't fit in metadata fields.

**Options identified by providers:**

**A. Split Strategy: Filtering in Metadata, Content in File Text (Recommended)**
- Store categorical/list data in custom_metadata (category, topics, aspects, entities, key_themes)
- Prepend Tier 4 summary/argument_structure to file text during upload
- Embeddings capture both AI analysis and original content
- _(Proposed by: Gemini, Perplexity)_

**B. Extract Key Terms Only**
- Store 5-10 key terms from Tier 4 in metadata
- Full semantic descriptions lost
- Simpler but potentially less accurate retrieval
- _(Proposed by: Perplexity as alternative)_

**C. Store Full Tier 4 in Metadata**
- Put 500-word summaries in metadata value fields
- May exceed character limits
- Wasteful of metadata tokens
- _(No provider recommended)_

**Synthesis recommendation:** ✅ **Option A (Split Strategy)**
- Separation of concerns: metadata for filtering, embeddings for semantic similarity
- Best of both worlds: structured filtering + rich context
- Proven pattern in semantic search systems

**Sub-questions:**
- Should key_themes be extracted algorithmically or use existing Tier 4 data?
- How to format prepended content? (Proposal: `[AI Analysis]\n{summary}\n\n[Original Content]`)
- Character limit for metadata values? (Need validation: likely 2048 bytes)

---

### Q2: Entity Dependency Management

**Question:** Should Phase 6.2 upload block until Phase 6.1 (entity extraction) completes, or upload without entities and re-upload later?

**Why it matters:** Gemini doesn't support patching metadata. Re-uploading requires delete + re-upload, doubling costs (~$4.20 → ~$8.40). Entity mentions provide significant semantic value for queries.

**Options identified by providers:**

**A. Strict Dependency: Wait for Phase 6.1 Before Upload (Recommended)**
- Upload ONLY files with both Phase 6 metadata AND Phase 6.1 entities
- Run Phase 6.1 on 434 ready files immediately (estimated 1-2 hours)
- Then upload those 434 with complete metadata
- No re-uploads, no double costs
- _(Proposed by: Gemini, Perplexity)_

**B. Stratified Upload: Upload Now, Re-Upload Later**
- Upload 434 files now without entity mentions
- Run Phase 6.1 later, then delete and re-upload with entities
- Faster initial value delivery
- Additional $3.10 cost for re-uploading
- Operational complexity (tracking which files need re-upload)
- _(Proposed by: Perplexity as alternative, not recommended)_

**C. Upload Without Entities, Never Add Them**
- Skip Phase 6.1 entirely for some files
- Inconsistent metadata quality
- Reduced semantic search accuracy
- _(No provider recommended)_

**Synthesis recommendation:** ✅ **Option A (Strict Dependency)**
- Entity mentions are high-value (disambiguate "Kant's influence" queries)
- Re-uploading is expensive and operationally complex
- Phase 6.1 extraction is fast (5-10 files/min = ~1-2 hours for 434 files)
- Better to wait 1-2 hours than pay $3+ extra and manage re-uploads

**Sub-questions:**
- How fast is Phase 6.1 extraction empirically? (Conservative: 5-10 files/min)
- Allow manual override to skip entities? (Proposal: No, strict gate)
- Re-run Phase 6.1 when canonical aliases updated? (Deferred to Phase 6.1 planning)

---

### Q3: Concurrency & Rate Limiting Configuration

**Question:** What initial concurrency (Semaphore value) and retry policy should be used for parallel uploads to avoid 429 errors?

**Why it matters:** 429 errors require exponential backoff (up to 32s delay), dramatically increasing upload time. Too aggressive = rate limit cascade. Too conservative = unnecessarily slow. Gemini rate limits not fully documented.

**Options identified by providers:**

**A. Conservative Start: Semaphore(2) + Empirical Tuning (Recommended)**
- Start with 2 concurrent uploads (conservative)
- 1 second delay between launches
- Exponential backoff on 429: 2s → 4s → 8s → 16s → 32s with jitter
- Test with 50 files, tune based on results
- _(Proposed by: Gemini, Perplexity)_

**B. Moderate Start: Semaphore(3)**
- Start with 3 concurrent uploads (middle of 3-5 range)
- Higher throughput but more risk of 429s
- _(Proposed by: Perplexity as alternative)_

**C. Aggressive: Semaphore(5)**
- Maximum parallelism from user's 3-5 estimate
- High risk of rate limit cascade
- _(No provider recommended)_

**Synthesis recommendation:** ✅ **Option A (Conservative Start)**
- Configuration that prevents 429s is superior to one that recovers from them
- Easy to increase after validation (2 → 3 → 4)
- Hard to recover from rate limit cascade
- 50-file test batch provides empirical data for tuning

**Sub-questions:**
- What is Gemini File Search actual RPM limit? (Not documented, needs testing)
- Should we contact Google support for rate limit specs?
- Implement adaptive throttling based on response headers? (If available)

---

### Q4: State Management Schema

**Question:** How should SQLite track file upload lifecycle and prevent duplicate uploads during continuous processing?

**Why it matters:** Phase 6 extraction continues while Phase 6.2 uploads. Need to differentiate: extracted but not uploaded, uploaded successfully, upload failed. Without clear state tracking, files may be skipped or uploaded twice.

**Options identified by providers:**

**A. Extend files Table with Upload Tracking Columns (Recommended)**
- Add: `upload_status` (pending/uploading/uploaded/failed)
- Add: `gemini_file_id`, `gemini_uri`, `upload_timestamp`, `upload_error`, `upload_attempt_count`
- State machine: pending → uploading → uploaded/failed
- Idempotency via `last_upload_hash` (hash of metadata+content)
- _(Proposed by: Gemini, Perplexity)_

**B. Separate upload_tracking Table**
- Keep files table clean, upload state in separate table
- More normalized but requires JOIN queries
- _(No provider recommended)_

**Synthesis recommendation:** ✅ **Option A (Extend files Table)**
- Simpler queries (no JOINs)
- Clear state machine
- Supports idempotency, crash recovery, retry logic
- Checkpoint every 50 uploads for atomic progress

**Sub-questions:**
- Should we track Gemini async indexing completion? (Proposal: Yes, poll operation status)
- Handle files deleted from local disk? (Out of scope for Phase 6.2)
- Store upload failure stack traces? (Proposal: Yes, in upload_error TEXT field)

---

### Q5: Testing & Validation Strategy

**Question:** What testing approach should validate metadata schema and upload pipeline before committing ~$4.20 to index all 1,749 files?

**Why it matters:** If metadata schema is rejected after uploading all files, must delete and re-upload (doubling cost). Need high-confidence validation before full commitment. Testing budget ~$0.06 is cheap insurance.

**Options identified by providers:**

**A. Three-Stage Validation Before Full Upload (Recommended)**
- Stage 1 (20 docs, <$0.01): Metadata schema validation, test filter queries
- Stage 2 (100 docs, <$0.05): Semantic search quality, precision@10 ≥0.7
- Stage 3 (250 docs, $0.10-0.20): Upload pipeline, concurrency, error recovery
- Total cost: ~$0.06 (1.3% of full deployment)
- Decision gates: proceed only if previous stage passes
- _(Proposed by: Gemini, Perplexity)_

**B. Golden Set Only (10 files)**
- Minimal testing, faster to production
- Higher risk of discovering issues post-deployment
- _(Proposed by: Gemini as minimum viable)_

**C. No Testing (YOLO)**
- Upload all 1,749 files immediately
- Maximum risk
- _(No provider recommended)_

**Synthesis recommendation:** ✅ **Option A (Three-Stage)**
- $0.06 is 1.3% of $4.20 full cost - excellent insurance policy
- Validates schema, quality, AND pipeline before commitment
- Clear success criteria at each stage
- Risk: discoverable issues remain, but drastically reduced

**Sub-questions:**
- What precision@10 threshold is acceptable? (Proposal: ≥0.7)
- Should we test with real anticipated queries? (Proposal: Yes, prepare 10-20 test queries)
- How many attempts before declaring failure? (Proposal: 3 attempts with exponential backoff)

---

## Next Steps (Non-YOLO Mode)

**✋ PAUSED — Awaiting Your Decisions**

1. **Review these 5 questions** (all Tier 1 blocking)
2. **Provide answers** (create CLARIFICATIONS-ANSWERED.md manually, or tell Claude your decisions)
3. **Then run:** `/gsd:plan-phase 6.2` to create execution plan

---

## Alternative: YOLO Mode

If you want Claude to auto-generate reasonable answers:

```bash
/gsd:discuss-phase-ai 6.2 --yolo
```

This will:
- Auto-select recommended options (marked ✅ above)
- Generate CLARIFICATIONS-ANSWERED.md automatically
- Proceed to planning without pause

---

*Multi-provider synthesis: Gemini Pro + Perplexity Deep Research*
*Generated: 2026-02-16*
*YOLO mode active: Auto-generating answers...*
