#!/bin/bash
# Monitor enriched upload progress every 2 minutes

LOG_FILE="logs/enriched_upload_20260217_035647.log"
MONITOR_LOG="logs/upload_monitor.log"
PID=94145

echo "=== Upload Monitoring Started: $(date) ===" | tee -a "$MONITOR_LOG"
echo "Process PID: $PID" | tee -a "$MONITOR_LOG"
echo "Log file: $LOG_FILE" | tee -a "$MONITOR_LOG"
echo "" | tee -a "$MONITOR_LOG"

while kill -0 $PID 2>/dev/null; do
    echo "=== Check at $(date) ===" | tee -a "$MONITOR_LOG"

    # Show last 30 lines of upload log
    echo "--- Last 30 lines of upload log ---" | tee -a "$MONITOR_LOG"
    tail -30 "$LOG_FILE" | tee -a "$MONITOR_LOG"
    echo "" | tee -a "$MONITOR_LOG"

    # Check for errors
    if grep -i "error\|failed\|exception" "$LOG_FILE" > /dev/null 2>&1; then
        echo "ERRORS DETECTED - Recent errors:" | tee -a "$MONITOR_LOG"
        grep -i "error\|failed\|exception" "$LOG_FILE" | tail -10 | tee -a "$MONITOR_LOG"
        echo "" | tee -a "$MONITOR_LOG"
    else
        echo "No errors detected" | tee -a "$MONITOR_LOG"
    fi

    # Database status
    echo "--- Database Status ---" | tee -a "$MONITOR_LOG"
    sqlite3 data/library.db "SELECT gemini_state, COUNT(*) as count FROM files GROUP BY gemini_state ORDER BY gemini_state;" 2>/dev/null | tee -a "$MONITOR_LOG"
    echo "" | tee -a "$MONITOR_LOG"

    sleep 120  # 2 minutes
done

echo "=== Upload Process Completed: $(date) ===" | tee -a "$MONITOR_LOG"
echo "Final log output:" | tee -a "$MONITOR_LOG"
tail -50 "$LOG_FILE" | tee -a "$MONITOR_LOG"
