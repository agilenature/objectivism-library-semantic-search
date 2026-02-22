#!/bin/bash
# Quick status check for enriched upload

echo "=== Enriched Upload Status: $(date) ==="
echo ""

# Check if process is running
if kill -0 94145 2>/dev/null; then
    echo "Upload process running (PID: 94145)"
else
    echo "Upload process not running"
fi

# Database counts
echo ""
echo "File Status (gemini_state):"
sqlite3 data/library.db "
SELECT gemini_state, COUNT(*) as Count
FROM files
GROUP BY gemini_state
ORDER BY gemini_state;
"

# Progress calculation
echo ""
echo "Progress:"
sqlite3 data/library.db "
SELECT
    printf('Indexed: %d/%d (%.1f%%)',
        SUM(CASE WHEN gemini_state = 'indexed' THEN 1 ELSE 0 END),
        COUNT(*),
        CAST(SUM(CASE WHEN gemini_state = 'indexed' THEN 1 ELSE 0 END) AS FLOAT) * 100.0 /
        COUNT(*)
    )
FROM files;
"

# Recent errors
echo ""
if grep -i "error\|failed\|exception" logs/enriched_upload_20260217_035647.log > /dev/null 2>&1; then
    echo "Recent errors in log:"
    grep -i "error\|failed\|exception" logs/enriched_upload_20260217_035647.log | tail -5
else
    echo "No errors in log"
fi

# Last log lines
echo ""
echo "=== Recent Log Activity ==="
tail -20 logs/enriched_upload_20260217_035647.log
