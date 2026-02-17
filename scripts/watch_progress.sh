#!/bin/bash
# Real-time upload progress tracker

echo "🚀 Enriched Upload Progress Tracker"
echo "===================================="
echo ""

while kill -0 94145 2>/dev/null; do
    clear
    echo "🚀 Enriched Upload Progress - $(date '+%Y-%m-%d %H:%M:%S')"
    echo "=============================================="
    echo ""

    # Get current counts
    sqlite3 data/library.db "
    SELECT
        SUM(CASE WHEN status = 'uploaded' THEN 1 ELSE 0 END) as uploaded,
        SUM(CASE WHEN status = 'uploading' THEN 1 ELSE 0 END) as uploading,
        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
        SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) as skipped,
        COUNT(*) as total
    FROM files;
    " | while IFS='|' read uploaded uploading failed pending skipped total; do
        active=$((total - skipped))
        progress=$(echo "scale=1; $uploaded * 100 / $active" | bc)

        echo "📊 Status:"
        echo "  ✅ Uploaded:  $uploaded files"
        echo "  🔄 Uploading: $uploading files (active)"
        echo "  ❌ Failed:    $failed files"
        echo "  ⏳ Pending:   $pending files"
        echo "  ⏭️  Skipped:   $skipped files (.epub/.pdf)"
        echo ""
        echo "📈 Progress: $progress% ($uploaded/$active files)"
        echo ""

        # Progress bar
        bars=$((uploaded * 50 / active))
        printf "["
        for ((i=0; i<bars; i++)); do printf "█"; done
        for ((i=bars; i<50; i++)); do printf "░"; done
        printf "]\n"
    done

    echo ""
    echo "💾 Recent Activity:"
    tail -5 logs/enriched_upload_20260217_035647.log 2>/dev/null | grep -v "^$"

    echo ""
    echo "Press Ctrl+C to stop monitoring (upload will continue)"
    sleep 5
done

echo ""
echo "✨ Upload process completed!"
./check_status.sh
