#!/bin/bash
# Real-time upload progress tracker

echo "Enriched Upload Progress Tracker"
echo "===================================="
echo ""

while kill -0 94145 2>/dev/null; do
    clear
    echo "Enriched Upload Progress - $(date '+%Y-%m-%d %H:%M:%S')"
    echo "=============================================="
    echo ""

    # Get current counts
    sqlite3 data/library.db "
    SELECT
        SUM(CASE WHEN gemini_state = 'indexed' THEN 1 ELSE 0 END) as indexed,
        SUM(CASE WHEN gemini_state = 'uploading' THEN 1 ELSE 0 END) as uploading,
        SUM(CASE WHEN gemini_state = 'failed' THEN 1 ELSE 0 END) as failed,
        SUM(CASE WHEN gemini_state = 'untracked' THEN 1 ELSE 0 END) as untracked,
        COUNT(*) as total
    FROM files;
    " | while IFS='|' read indexed uploading failed untracked total; do
        progress=$(echo "scale=1; $indexed * 100 / $total" | bc)

        echo "Status:"
        echo "  Indexed:    $indexed files"
        echo "  Uploading:  $uploading files (active)"
        echo "  Failed:     $failed files"
        echo "  Untracked:  $untracked files"
        echo ""
        echo "Progress: $progress% ($indexed/$total files)"
        echo ""

        # Progress bar
        bars=$((indexed * 50 / total))
        printf "["
        for ((i=0; i<bars; i++)); do printf "#"; done
        for ((i=bars; i<50; i++)); do printf "."; done
        printf "]\n"
    done

    echo ""
    echo "Recent Activity:"
    tail -5 logs/enriched_upload_20260217_035647.log 2>/dev/null | grep -v "^$"

    echo ""
    echo "Press Ctrl+C to stop monitoring (upload will continue)"
    sleep 5
done

echo ""
echo "Upload process completed!"
./check_status.sh
