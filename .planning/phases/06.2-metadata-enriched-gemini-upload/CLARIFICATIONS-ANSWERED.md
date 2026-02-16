# CLARIFICATIONS-ANSWERED.md

## Phase 6.2: Metadata-Enriched Gemini Upload — Stakeholder Decisions

**Generated:** 2026-02-16
**Mode:** YOLO (balanced strategy - auto-generated)
**Source:** Multi-provider AI synthesis (Gemini Pro, Perplexity Deep Research)

---

## Decision Summary

**Total questions:** 5
**Tier 1 (Blocking):** 5 answered

**Strategy:** Balanced - Select ✅ consensus recommendations from synthesis

---

## Tier 1: Blocking Decisions

### Q1: Metadata Flattening Strategy

**Question:** How should 4-tier metadata be mapped into Gemini's flat custom_metadata format?

**YOLO DECISION:** **Option A - Split Strategy: Filtering in Metadata, Content in File Text**

**Rationale:**
- Confidence level: ✅ Consensus (both Gemini and Perplexity recommended)
- Separation of concerns: metadata for structured filtering, embeddings for semantic similarity
- Best of both worlds: categorical organization + rich context
- Proven pattern in production semantic search systems
- Strategy: Balanced (pick consensus with clean architecture)

**Implementation details:**

**Filtering Fields (custom_metadata):**
```python
custom_metadata = [
    {"key": "category", "string_value": "course"},
    {"key": "difficulty", "string_value": "introductory"},
    {"key": "topics", "string_list_value": ["epistemology", "concept_formation"]},
    {"key": "aspects", "string_list_value": ["epistemology", "metaphysics"]},
    {"key": "entities", "string_list_value": ["Ayn Rand", "Leonard Peikoff"]},
    {"key": "key_themes", "string_list_value": ["abstraction", "measurement_omission"]},
    {"key": "source_type", "string_value": "objectivism_library"},
]
```

**Content Injection (prepended to file text):**
```
[AI Analysis - Category: {category}]
Summary: {tier4_summary}

Argument Structure: {tier4_argument_structure}

Key Themes: {tier4_key_themes}

[Original Content]
{file_text}
```

**Sub-decisions:**
- **key_themes extraction:** Use existing Tier 4 `key_themes` list (already extracted by Phase 6)
- **Content format:** Structured prepend with clear delimiters for AI analysis vs original
- **Character limit:** Validate metadata values <2048 bytes (standard Gemini limit)

---

### Q2: Entity Dependency Management

**Question:** Wait for Phase 6.1 entities before upload, or upload without and re-upload later?

**YOLO DECISION:** **Option A - Strict Dependency: Wait for Phase 6.1**

**Rationale:**
- Confidence level: ✅ Consensus (both providers strongly recommended)
- Entity mentions provide high semantic value (disambiguate philosopher queries)
- Re-uploading is expensive ($3.10 additional) and operationally complex
- Phase 6.1 extraction is fast (estimated 1-2 hours for 434 files)
- Better to wait briefly than manage re-upload complexity and additional cost
- Strategy: Balanced (pick consensus with cost optimization)

**Implementation details:**

**Execution Order:**
1. Run Phase 6.1 entity extraction on 434 Phase-6-complete files
2. Upload those 434 files to Gemini with full metadata + entities (Phase 6.2a)
3. As Phase 6 completes more files → Phase 6.1 → Phase 6.2
4. Continuous pipeline: Phase 6 extraction (ongoing) → Phase 6.1 entities → Phase 6.2 upload

**Pipeline Filter Query:**
```sql
SELECT * FROM files
WHERE ai_metadata_status IN ('extracted', 'approved')
  AND entities_extracted = true
  AND upload_status = 'pending'
ORDER BY file_path
LIMIT 100;  -- Batch processing
```

**No Re-uploads:**
- Prevents ~$3.10 additional indexing cost
- Ensures all indexed files have consistent, complete metadata
- Simplifies operational state management

**Sub-decisions:**
- **Manual override:** NO (strict gate, no bypass)
- **Phase 6.1 speed estimate:** Conservative 5-10 files/min = 43-87 min for 434 files
- **Fallback if Phase 6.1 blocked:** Fix blocking issue, don't skip entities

---

### Q3: Concurrency & Rate Limiting Configuration

**Question:** Initial concurrency setting and retry policy for parallel uploads?

**YOLO DECISION:** **Option A - Conservative Start: Semaphore(2) + Empirical Tuning**

**Rationale:**
- Confidence level: ✅ Consensus (both providers recommended conservative start)
- Configuration that prevents 429s is superior to one that recovers from them
- Easy to increase after empirical validation (2 → 3 → 4)
- Hard to recover from rate limit cascade (exponential backoff delays)
- 50-file test batch provides data for safe tuning decisions
- Strategy: Balanced (pick consensus with safety-first approach)

**Implementation details:**

**Initial Configuration:**
```python
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

UPLOAD_SEMAPHORE = asyncio.Semaphore(2)  # Conservative: 2 concurrent
LAUNCH_DELAY = 1.0  # 1 second between launch attempts
MAX_RETRIES = 3

@retry(
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=2, max=32),  # 2s, 4s, 8s, 16s, 32s
    retry=retry_if_exception_type(RateLimitError),
    reraise=True
)
async def upload_file_with_retry(file_path):
    async with UPLOAD_SEMAPHORE:
        await asyncio.sleep(LAUNCH_DELAY)  # Rate limiting
        return await upload_to_gemini(file_path)
```

**Exponential Backoff with Jitter:**
- Attempt 1: Immediate
- Fail 429: Wait 2s + random(0-0.5s)
- Fail 429: Wait 4s + random(0-1s)
- Fail 429: Wait 8s + random(0-2s)
- Fail 429: Wait 16s + random(0-4s)
- Fail 429: Mark `failed`, continue batch

**Tuning Process:**
1. Upload 50-file test batch with Semaphore(2)
2. Monitor: 429 error rate, response latencies, total time
3. **If zero 429s AND latency <10s per file:** Increase to Semaphore(3), re-test
4. **If any 429s OR latency >30s:** Keep Semaphore(2), document as empirical limit
5. Document findings for future reference

**Sub-decisions:**
- **RPM limit discovery:** Empirical testing (contact Google support if needed)
- **Adaptive throttling:** Not implemented initially (add if response headers provide quota info)
- **Filesize throttling:** Not implemented initially (add if large files cause timeouts)

---

### Q4: State Management Schema

**Question:** How to track upload lifecycle in SQLite for crash recovery and idempotency?

**YOLO DECISION:** **Option A - Extend files Table with Upload Tracking**

**Rationale:**
- Confidence level: ✅ Consensus (both providers recommended table extension)
- Simpler queries than separate table (no JOINs required)
- Clear state machine for lifecycle tracking
- Supports crash recovery, retry logic, idempotency
- Checkpoint-based progress saves prevent data loss
- Strategy: Balanced (pick consensus with operational simplicity)

**Implementation details:**

**Schema Migration:**
```sql
-- Add upload tracking columns to files table
ALTER TABLE files ADD COLUMN upload_status TEXT DEFAULT 'pending'
  CHECK(upload_status IN ('pending', 'uploading', 'uploaded', 'failed'));

ALTER TABLE files ADD COLUMN gemini_file_id TEXT;
ALTER TABLE files ADD COLUMN gemini_uri TEXT;
ALTER TABLE files ADD COLUMN upload_timestamp TEXT;
ALTER TABLE files ADD COLUMN upload_error TEXT;
ALTER TABLE files ADD COLUMN upload_attempt_count INTEGER DEFAULT 0;
ALTER TABLE files ADD COLUMN last_upload_hash TEXT;  -- Hash of metadata+content

CREATE INDEX idx_upload_status ON files(upload_status);
CREATE INDEX idx_gemini_file_id ON files(gemini_file_id);
```

**State Machine:**
```
pending → uploading (before API call)
uploading → uploaded (on success, store file_id + URI)
uploading → failed (on error, store error message)
failed → uploading (retry, increment attempt_count)
```

**Idempotency Check:**
```python
def needs_upload(file_record):
    current_hash = hash_metadata_and_content(file_record)
    return (
        file_record.upload_status != 'uploaded'
        or file_record.last_upload_hash != current_hash
    )
```

**Checkpointing (Every 50 Uploads):**
```python
async def upload_batch_with_checkpoints(files, checkpoint_interval=50):
    uploaded_count = 0

    for file in files:
        try:
            result = await upload_file_with_retry(file.path)
            update_upload_status(file.id, 'uploaded', result.file_id, result.uri)
            uploaded_count += 1

            if uploaded_count % checkpoint_interval == 0:
                commit_checkpoint(uploaded_count)
        except Exception as e:
            update_upload_status(file.id, 'failed', error=str(e))
```

**Sub-decisions:**
- **Async indexing tracking:** YES (poll Gemini operation status after upload)
- **Deletion handling:** Out of scope for Phase 6.2 (Phase 5 concern)
- **Stack trace storage:** YES (full error message + stack in `upload_error` TEXT field)

---

### Q5: Testing & Validation Strategy

**Question:** Testing approach before $4.20 full deployment?

**YOLO DECISION:** **Option A - Three-Stage Validation**

**Rationale:**
- Confidence level: ✅ Consensus (both providers recommended staged testing)
- $0.06 total cost is 1.3% of $4.20 deployment - excellent insurance
- Validates schema correctness, search quality, AND operational pipeline
- Clear success criteria enable go/no-go decisions at each gate
- Prevents expensive mistakes (schema rejected after full upload)
- Strategy: Balanced (pick consensus with risk mitigation)

**Implementation details:**

**Stage 1: Metadata Schema Validation (Cost: <$0.01, 20 docs)**

Upload: 20 representative documents (2 from each category)

Test Queries:
```python
test_queries = [
    "category='course'",
    "category='course' AND difficulty='introductory'",
    "topics='epistemology'",
    "aspects='ethics' AND entities='Ayn Rand'",
    "entities='Leonard Peikoff' AND category='book'",
]
```

Success Criteria:
- [ ] All metadata fields accepted without schema errors
- [ ] All test queries return expected results (100% accuracy)
- [ ] No character limit violations
- [ ] Filter syntax works as expected

**Stage 2: Semantic Search Quality (Cost: <$0.05, 100 docs)**

Upload: 100 documents (10-15 from each major category)

Test Queries:
```python
semantic_queries = [
    "epistemological approaches in Objectivism",
    "Kant's influence on modern philosophy",
    "concept formation and abstraction",
    "ethics of rational self-interest",
    "political philosophy and individual rights",
]
```

Success Criteria:
- [ ] Precision@10 ≥ 0.7 for all test queries
- [ ] Embeddings capture both AI analysis and original content
- [ ] Entity mentions improve retrieval accuracy
- [ ] Query latency < 2 seconds

**Stage 3: Upload Pipeline Validation (Cost: $0.10-0.20, 250 docs)**

Upload: 250 documents (15% of corpus) with full production pipeline

Tests:
- Concurrency: Run with Semaphore(2), monitor 429 error rate
- Rate limiting: Validate exponential backoff works correctly
- Error recovery: Inject network failures, verify resumption from checkpoint
- State tracking: Verify SQLite state reflects actual upload results
- Idempotency: Re-run pipeline, verify already-uploaded files skipped

Success Criteria:
- [ ] ≤5% of requests encounter 429 errors
- [ ] All 429s eventually succeed with exponential backoff
- [ ] Crash recovery works (resume from last checkpoint)
- [ ] Zero duplicate uploads (idempotency works)
- [ ] End-to-end time: <30 minutes for 250 files

**Decision Gates:**
- Proceed to Stage 2 ONLY if Stage 1 passes all criteria
- Proceed to Stage 3 ONLY if Stage 2 passes all criteria
- Proceed to full deployment ONLY if Stage 3 passes all criteria

**Sub-decisions:**
- **Precision@10 threshold:** 0.7 (70% of top-10 results relevant)
- **Real query testing:** YES (prepare 10-20 anticipated use-case queries)
- **Failure retry limit:** 3 attempts with exponential backoff before declaring failure

---

## Summary: Implementation Checklist

**Must Implement (Tier 1):**
- [x] Split metadata strategy (filtering in metadata, content in file text)
- [x] Strict entity dependency (wait for Phase 6.1 before upload)
- [x] Conservative concurrency (Semaphore(2), exponential backoff, empirical tuning)
- [x] Extended state management (upload_status columns in files table)
- [x] Three-stage validation (schema → quality → pipeline, $0.06 cost)

---

## Next Steps

**✅ YOLO Mode Complete** - All 5 questions answered with balanced strategy

**Proceed to Planning:**
1. Run `/gsd:plan-phase 6.2` to create detailed execution plan
2. Plan will break down into 3-5 executable steps
3. Each step verified before execution

---

*Auto-generated by /gsd:discuss-phase-ai 6.2 --yolo (balanced strategy)*
*Human review recommended before final implementation*
*Generated: 2026-02-16*
