#!/bin/bash
# Monitor enriched upload progress

LOG_FILE="/private/tmp/claude-501/-Users-david-projects-objectivism-library-semantic-search/tasks/beaece4.output"
MONITOR_LOG="logs/enriched_upload_monitor.log"

echo "=== Enriched Upload Monitoring Started: $(date) ===" | tee -a "$MONITOR_LOG"
echo ""

while pgrep -f "python -m objlib enriched-upload" > /dev/null 2>&1; do
    echo "=== Check at $(date) ===" | tee -a "$MONITOR_LOG"

    # Database status
    echo "File Status:" | tee -a "$MONITOR_LOG"
    sqlite3 data/library.db "
    SELECT gemini_state, COUNT(*) as count
    FROM files
    GROUP BY gemini_state
    ORDER BY gemini_state;
    " | tee -a "$MONITOR_LOG"

    echo "" | tee -a "$MONITOR_LOG"

    # Recent errors
    if tail -50 "$LOG_FILE" | grep -i "Failed to upload" > /dev/null 2>&1; then
        echo "Recent failures:" | tee -a "$MONITOR_LOG"
        tail -50 "$LOG_FILE" | grep -i "Failed to upload" | tail -3 | tee -a "$MONITOR_LOG"
    fi

    echo "" | tee -a "$MONITOR_LOG"
    sleep 300  # 5 minutes
done

echo "=== Upload Completed: $(date) ===" | tee -a "$MONITOR_LOG"
echo ""
echo "Final Status:" | tee -a "$MONITOR_LOG"
sqlite3 data/library.db "SELECT gemini_state, COUNT(*) FROM files GROUP BY gemini_state ORDER BY gemini_state;" | tee -a "$MONITOR_LOG"
