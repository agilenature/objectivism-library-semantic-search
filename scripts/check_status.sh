#!/bin/bash
# Quick status check for enriched upload

echo "=== Enriched Upload Status: $(date) ==="
echo ""

# Check if process is running
if kill -0 94145 2>/dev/null; then
    echo "✅ Upload process running (PID: 94145)"
else
    echo "❌ Upload process not running"
fi

# Database counts
echo ""
echo "File Status:"
sqlite3 data/library.db "
SELECT
    CASE status
        WHEN 'uploaded' THEN '✅ Uploaded'
        WHEN 'uploading' THEN '🔄 Uploading'
        WHEN 'failed' THEN '❌ Failed'
        WHEN 'pending' THEN '⏳ Pending'
        WHEN 'skipped' THEN '⏭️  Skipped'
        ELSE status
    END as Status,
    COUNT(*) as Count
FROM files
GROUP BY status
ORDER BY status;
"

# Progress calculation
echo ""
echo "Progress:"
sqlite3 data/library.db "
SELECT
    printf('Uploaded: %d/%d (%.1f%%)',
        SUM(CASE WHEN status = 'uploaded' THEN 1 ELSE 0 END),
        COUNT(*) - SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END),
        CAST(SUM(CASE WHEN status = 'uploaded' THEN 1 ELSE 0 END) AS FLOAT) * 100.0 /
        (COUNT(*) - SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END))
    )
FROM files;
"

# Recent errors
echo ""
if grep -i "error\|failed\|exception" logs/enriched_upload_20260217_035647.log > /dev/null 2>&1; then
    echo "⚠️  Recent errors in log:"
    grep -i "error\|failed\|exception" logs/enriched_upload_20260217_035647.log | tail -5
else
    echo "✅ No errors in log"
fi

# Last log lines
echo ""
echo "=== Recent Log Activity ==="
tail -20 logs/enriched_upload_20260217_035647.log
