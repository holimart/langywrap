#!/usr/bin/env bash
# Universal shell wrapper for AI coding tools without native hooks
# Usage: guard.sh [-c "cmd"] [--exec -c "cmd"]
#
# Default (check-only): validates command, exits 0 (allowed) or 1 (blocked), does NOT execute.
# With --exec:          validates AND executes the command if allowed.
#
# This makes guard.sh composable as a pre-check validator. Callers that need
# execution (e.g. secure-run.sh $SHELL wrapper, harden-wizard guard-exec.sh) use --exec.
#
# Template variables:
#   __PROJECT_NAME__ - replaced with project name during installation
#   __REAL_SHELL__   - replaced with path to real shell (e.g., /bin/bash)

REAL_SHELL="__REAL_SHELL__"

# --- Flag parsing ---
EXEC_MODE=false
if [[ "${1:-}" == "--exec" ]]; then EXEC_MODE=true; shift; fi

# --- Audit logging ---
LOG_DIR="$HOME/.llmsec/logs"
LOG_FILE="$LOG_DIR/__PROJECT_NAME___audit.log"
mkdir -p "$LOG_DIR" 2>/dev/null || true

TIMESTAMP=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

log_entry() {
    echo "$TIMESTAMP | $1 | ${COMMAND:-$*}" >> "$LOG_FILE" 2>/dev/null || true
}

block() {
    log_entry "BLOCKED"
    echo "$1" >&2
    exit 1
}

# If not called with -c, pass through directly (interactive shell, etc.)
if [[ "${1:-}" != "-c" ]]; then
    exec "$REAL_SHELL" "$@"
fi

# Extract the command from -c argument
shift  # remove -c
COMMAND="$*"

if [[ -z "$COMMAND" ]]; then
    exec "$REAL_SHELL" -c ""
fi

# --- Data theft prevention ---

if echo "$COMMAND" | grep -qiE '(curl|wget|http).*(pastebin\.com|transfer\.sh|file\.io|paste\.ee|hastebin|0x0\.st|ix\.io)'; then
    block "BLOCKED: Data exfiltration attempt. Write output to a local file instead."
fi

if echo "$COMMAND" | grep -qiE 'base64.*(\.env|credentials|_key\.pem|id_rsa|id_ed25519|\.aws)'; then
    block "BLOCKED: Encoding sensitive file. Use environment variables instead."
fi

if echo "$COMMAND" | grep -qiE '(cat|tar|zip|gzip|7z)\s.*(\.env|\.ssh/|\.aws/|credentials|_key\.pem|id_rsa|id_ed25519|\.gnupg)'; then
    block "BLOCKED: Access to sensitive file. Use environment variables instead."
fi

if echo "$COMMAND" | grep -qiE '(scp|rsync)\s.*(\.env|\.ssh|\.aws|credentials|_key\.pem)'; then
    block "BLOCKED: Transfer of sensitive files. Use secure secret management."
fi

# --- Dangerous patterns ---

if echo "$COMMAND" | grep -qE '(^|\s|;|&&|\|)rm\s+(-[a-zA-Z]*r[a-zA-Z]*f?|(-[a-zA-Z]*f[a-zA-Z]*)?-[a-zA-Z]*r)\s'; then
    block "BLOCKED: Recursive delete (rm -rf / rm -r) is not allowed.
Suggestion: Move files to trash: mv <path> /tmp/trash/"
fi

if echo "$COMMAND" | grep -qE '(^|\s|;|&&|\|)sudo\s'; then
    block "BLOCKED: sudo (privilege escalation) is not allowed.
Suggestion: Work within current user permissions."
fi

if echo "$COMMAND" | grep -qE 'chmod\s+777'; then
    block "BLOCKED: chmod 777 is not allowed.
Suggestion: Use chmod 644 (files) or chmod 755 (directories)."
fi

if echo "$COMMAND" | grep -qE '(^|\s|;|&&|\|)dd\s'; then
    block "BLOCKED: dd (disk/data duplicator) is not allowed.
Suggestion: Use cp for file copying."
fi

if echo "$COMMAND" | grep -qE 'git\s+push\s+.*(-f|--force)'; then
    block "BLOCKED: Force push is not allowed.
Suggestion: Use regular 'git push' or --force-with-lease."
fi

# --- Command allowed ---
log_entry "ALLOWED"
[[ "$EXEC_MODE" == "true" ]] && exec "$REAL_SHELL" -c "$COMMAND"
exit 0   # check-only: allowed, caller executes
