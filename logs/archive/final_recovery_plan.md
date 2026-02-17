# Final Recovery Plan

## Current Status
- **Uploaded:** 1,599 files (84.9% of library)  
- **Failed:** 150 files
- **Skipped:** 135 files (.epub/.pdf)

## Failure Breakdown
1. **Polling Timeouts (101 files):** Upload started but import operation didn't complete in time
   - **Likely cause:** Gemini API slow processing
   - **Action:** Check if operations completed on Gemini side
   
2. **400 INVALID_ARGUMENT (46 files):** Gemini rejected these files
   - **Likely cause:** Special characters, malformed content, or metadata issues
   - **Action:** Manual investigation needed

3. **503/500 Errors (3 files):** Server-side errors
   - **Action:** Simple retry

## Recommended Actions

### 1. Retry Service Errors (3 files) ✅ SAFE
```bash
sqlite3 data/library.db "UPDATE files SET status = 'pending', error_message = NULL WHERE error_message LIKE '%503%' OR error_message LIKE '%500%';"
python -m objlib upload --store objectivism-library-test --batch-size 10
```

### 2. Investigate Polling Timeouts (101 files) ⚠️ NEEDS VERIFICATION
These files may have actually completed on Gemini's side. Need to:
- Check Gemini File Search store for these files
- If found, mark as uploaded in database
- If not found, retry upload

### 3. Document 400 Errors (46 files) 📝 MANUAL REVIEW
Export list for manual investigation:
```bash
sqlite3 data/library.db "SELECT file_path FROM files WHERE status = 'failed' AND error_message LIKE '%400 INVALID_ARGUMENT%' ORDER BY file_path;" > logs/400_errors_final.txt
```

Common patterns in 400 errors:
- Square brackets in filenames: `Episode 195 [1000108721462].txt`
- Underscores: `MOTM_2022-01-16_...txt`
- Special characters: `__1`, `__6`, `__12`

## Success Rate
- Current: 1,599 / 1,749 text files = **91.4% success**
- After service error retry: ~1,602 / 1,749 = **91.6%**
- Polling timeouts uncertain (may already be uploaded)
