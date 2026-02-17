# Failed Files Analysis - Enriched Upload
**Date:** 2026-02-17
**Total Failed:** 23 files out of 792 attempted (2.9% failure rate)

## Failure Categories

### 1. 400 INVALID_ARGUMENT (14 files) ⚠️ NEEDS INVESTIGATION

**Likely Causes:**
- Special characters in filenames (square brackets, underscores)
- File content issues
- Gemini API-side validation failures

**Affected Files:**
1. Aristotle_s Theory of Knowledge - Lesson 02 - Aristotle_s Theory of Universals.txt
2. Ayn Rand at the Ford Hall Forum - Lesson 04 - Is Atlas Shrugging_.txt
3. Episode 195 [1000108721462].txt
4. Episode 270 [1000160075681].txt
5. Episode 293 [1000169520664].txt
6. Episode 400 [1000360856092].txt
7. History of Philosophy - Lesson 02 - Thales of Miletus and the Birth of Greek Philosophy.txt
8. History of Philosophy - Lesson 41 - Immanuel Kant_ Is Reality Knowable_ The Problem Posed By David Hume.txt
9. MOTM_2022-01-16_History-of-the-Objectivist-Movement-a-personal-account-part.txt
10. MOTM_2022-07-31_New-Ideas-In-The-Esthetics-Of-Music.txt
11. MOTM_2022-09-25_More-epistemology-of-abortion-and-immigration.txt
12. MOTM_2022-10-03_Privacy.txt
13. The Objectivist Ethics HB - Part II - Class 09.txt
14. What Is Liberty_ - Lesson 01 - Politics, Liberty and Objectivism_ Part 1.txt

**Recommended Actions:**
1. Try uploading without enriched metadata (basic upload)
2. Investigate if filename sanitization is needed
3. Check if content has special characters causing issues

---

### 2. Polling Timeout (4 files) ✅ RETRY

**Cause:** Gemini API processing took longer than timeout period

**Affected Files:**
1. MOTM_2024-07-14_My-Favorite-Economic-Fallacies.txt (42 KB)
2. Episode 198 [1000109257310].txt (41 KB)
3. MOTM_2022-06-12_How-to-judge-advocacy-videos-a-case-study.txt (39 KB)
4. MOTM_2022-11-06_The-Midterm-Elections.txt (38 KB)

**Action:**
```bash
sqlite3 data/library.db "UPDATE files SET status = 'pending' WHERE error_message LIKE '%Operation did not complete%';"
python -m objlib enriched-upload --store objectivism-library-test --limit 10
```

---

### 3. 503 UNAVAILABLE (1 file) ✅ RETRY

**Cause:** Transient Gemini API service issue

**Affected File:**
- ITOE - Class 16-01.txt

**Action:**
```bash
sqlite3 data/library.db "UPDATE files SET status = 'pending' WHERE error_message LIKE '%503%';"
python -m objlib enriched-upload --store objectivism-library-test --limit 5
```

---

### 4. Oversized for Extraction (4 files) ✅ USE BASIC UPLOAD

**Cause:** Files exceed 100K token limit for AI metadata extraction

**Affected Files:**
1. Ayn Rand - Atlas Shrugged (1971).txt - 3.1 MB (~740K tokens)
2. A Companion to Ayn Rand - Gregory Salmieri - Allan Gotthelf.txt - 1.9 MB (~395K tokens)
3. Ayn Rand - Capitalism - The Unknown Ideal (1986).txt - 792 KB (~169K tokens)
4. Ayn Rand - Introduction to Objectivist Epistemology_ Expanded Second Edition-Plume (1990).txt - 581 KB (~125K tokens)

**Action:**
```bash
# Upload these with Phase 1 metadata only (no enrichment)
sqlite3 data/library.db "UPDATE files SET status = 'pending' WHERE error_message LIKE '%Oversized for extraction%';"
python -m objlib upload --store objectivism-library-test --limit 10
```

---

## Quick Fix Commands

### Retry All Recoverable Failures (9 files)
```bash
# Reset polling timeouts + 503 errors
sqlite3 data/library.db "UPDATE files SET status = 'pending' WHERE status = 'failed' AND (error_message LIKE '%503%' OR error_message LIKE '%Operation did not complete%');"

# Retry enriched upload
python -m objlib enriched-upload --store objectivism-library-test --limit 10
```

### Upload Oversized Books (4 files)
```bash
# Upload with basic metadata only
sqlite3 data/library.db "UPDATE files SET status = 'pending' WHERE error_message LIKE '%Oversized for extraction%';"
python -m objlib upload --store objectivism-library-test --limit 10
```

### Investigate 400 Errors (14 files)
```bash
# Save list for manual investigation
sqlite3 data/library.db "SELECT file_path FROM files WHERE status = 'failed' AND error_message LIKE '%400 INVALID_ARGUMENT%';" > logs/400_error_files.txt

# Try basic upload (without enrichment) as workaround
sqlite3 data/library.db "UPDATE files SET status = 'pending' WHERE error_message LIKE '%400 INVALID_ARGUMENT%';"
python -m objlib upload --store objectivism-library-test --limit 20
```

---

## Success Metrics

- **Uploaded Successfully:** 794 files (97.1%)
- **Failed:** 23 files (2.9%)
- **Potentially Recoverable:** 9 files (polling timeout + 503)
- **Alternative Upload Path:** 4 files (oversized books)
- **Needs Investigation:** 14 files (400 errors)

**Expected Recovery:** 13+ files can be recovered, bringing success rate to ~99%
