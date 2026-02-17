#!/bin/bash
# Monitor AI metadata extraction progress

DB_PATH="data/library.db"

while true; do
    clear
    echo "=== AI Metadata Extraction Progress ==="
    echo "$(date)"
    echo ""

    # Status breakdown
    sqlite3 "$DB_PATH" "
    SELECT
        ai_metadata_status,
        COUNT(*) as count
    FROM files
    WHERE status = 'uploaded'
    GROUP BY ai_metadata_status
    ORDER BY count DESC;
    "

    echo ""
    echo "=== Recent Log Tail ==="
    tail -10 logs/full_extraction_*.log 2>/dev/null | tail -10

    echo ""
    echo "Press Ctrl+C to stop monitoring"
    sleep 30
done
