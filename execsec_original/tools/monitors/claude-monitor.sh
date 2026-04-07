#!/bin/bash
# Monitor Claude Code for suspicious activity
# Part of Phase 5: Monitoring & Kill Switch

WATCH_PATTERNS="rm|dd|mkfs|chmod|chown|shutdown|reboot|curl.*bash|wget.*sh"
LOGFILE="$HOME/.claude-monitor.log"
PID_FILE="$HOME/.claude-monitor.pid"

echo $$ > "$PID_FILE"

log() {
    echo "$(date -Iseconds) $1" | tee -a "$LOGFILE"
}

cleanup() {
    log "🛑 Monitor stopped"
    rm -f "$PID_FILE"
    exit 0
}

trap cleanup SIGINT SIGTERM

log "🔍 Monitor started (PID: $$)"
log "📝 Logging to: $LOGFILE"
log "🎯 Watching patterns: $WATCH_PATTERNS"

while true; do
    CLAUDE_PIDS=$(pgrep -f "claude|node.*anthropic" 2>/dev/null)

    for pid in $CLAUDE_PIDS; do
        if [ -d "/proc/$pid" ]; then
            CMDLINE=$(cat "/proc/$pid/cmdline" 2>/dev/null | tr '\0' ' ')

            if echo "$CMDLINE" | grep -qE "$WATCH_PATTERNS"; then
                log "⚠️  SUSPICIOUS: PID $pid: $CMDLINE"
                # Uncomment to auto-kill:
                # kill -9 $pid && log "🛑 KILLED: PID $pid"
            fi
        fi
    done

    # Resource monitoring
    HIGH_CPU=$(ps aux | awk '$3 > 90 {print $2, $11}' | grep -E "claude|node" 2>/dev/null)
    [ -n "$HIGH_CPU" ] && log "⚠️  HIGH CPU: $HIGH_CPU"

    HIGH_MEM=$(ps aux | awk '$4 > 50 {print $2, $11}' | grep -E "claude|node" 2>/dev/null)
    [ -n "$HIGH_MEM" ] && log "⚠️  HIGH MEMORY: $HIGH_MEM"

    sleep 1
done
