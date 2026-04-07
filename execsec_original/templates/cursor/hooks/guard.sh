#!/usr/bin/env bash
# Security hook for Cursor's beforeShellExecution
# Receives JSON on stdin: {"command":"...","workingDirectory":"..."}
# Returns JSON on stdout:
#   Allow:  {"permission":"allow"}
#   Block:  {"permission":"deny","agentMessage":"...","userMessage":"..."}
#
# Template variables:
#   __PROJECT_NAME__ - replaced with project name during installation

set -euo pipefail

# --- Read hook input from stdin ---
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.command // empty' 2>/dev/null)
if [[ -z "$COMMAND" ]]; then
    echo '{"permission":"allow"}'
    exit 0
fi

# --- Audit logging ---
LOG_DIR="$HOME/.llmsec/logs"
LOG_FILE="$LOG_DIR/__PROJECT_NAME___audit.log"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

log_entry() {
    echo "$TIMESTAMP | $1 | $COMMAND" >> "$LOG_FILE"
}

allow() {
    log_entry "ALLOWED"
    echo '{"permission":"allow"}'
    exit 0
}

block() {
    local agent_msg="$1"
    local user_msg="${2:-$1}"
    log_entry "BLOCKED"
    # Escape for JSON
    agent_msg=$(echo "$agent_msg" | sed 's/"/\\"/g' | tr '\n' ' ')
    user_msg=$(echo "$user_msg" | sed 's/"/\\"/g' | tr '\n' ' ')
    echo "{\"permission\":\"deny\",\"agentMessage\":\"$agent_msg\",\"userMessage\":\"$user_msg\"}"
    exit 0
}

# --- Data theft prevention ---

if echo "$COMMAND" | grep -qiE '(curl|wget|http).*(pastebin\.com|transfer\.sh|file\.io|paste\.ee|hastebin|0x0\.st|ix\.io)'; then
    block "BLOCKED: Data exfiltration attempt. Write output to a local file instead." \
          "Security hook blocked data upload to external service."
fi

if echo "$COMMAND" | grep -qiE 'base64.*(\.env|credentials|_key\.pem|id_rsa|id_ed25519|\.aws)'; then
    block "BLOCKED: Encoding sensitive file. Use environment variables instead." \
          "Security hook blocked base64 encoding of sensitive file."
fi

if echo "$COMMAND" | grep -qiE '(cat|tar|zip|gzip|7z)\s.*(\.env|\.ssh/|\.aws/|credentials|_key\.pem|id_rsa|id_ed25519|\.gnupg)'; then
    block "BLOCKED: Access to sensitive file. Use environment variables instead." \
          "Security hook blocked access to credentials/keys."
fi

if echo "$COMMAND" | grep -qiE '(scp|rsync)\s.*(\.env|\.ssh|\.aws|credentials|_key\.pem)'; then
    block "BLOCKED: Transfer of sensitive files. Use secure secret management." \
          "Security hook blocked transfer of credential files."
fi

# --- Dangerous patterns ---

if echo "$COMMAND" | grep -qE '(^|\s|;|&&|\|)rm\s+(-[a-zA-Z]*r[a-zA-Z]*f?|(-[a-zA-Z]*f[a-zA-Z]*)?-[a-zA-Z]*r)\s'; then
    block "BLOCKED: Recursive delete. Move to trash instead: mv <path> /tmp/trash/" \
          "Security hook blocked recursive file deletion."
fi

if echo "$COMMAND" | grep -qE '(^|\s|;|&&|\|)sudo\s'; then
    block "BLOCKED: sudo not allowed. Work within current user permissions." \
          "Security hook blocked privilege escalation (sudo)."
fi

if echo "$COMMAND" | grep -qE 'chmod\s+777'; then
    block "BLOCKED: chmod 777 not allowed. Use chmod 644 or 755 instead." \
          "Security hook blocked insecure permissions (777)."
fi

if echo "$COMMAND" | grep -qE '(^|\s|;|&&|\|)dd\s'; then
    block "BLOCKED: dd not allowed. Use cp for file copying." \
          "Security hook blocked dd command."
fi

if echo "$COMMAND" | grep -qE 'git\s+push\s+.*(-f|--force)'; then
    block "BLOCKED: Force push not allowed. Use regular git push." \
          "Security hook blocked force push."
fi

# --- Command allowed ---
allow
