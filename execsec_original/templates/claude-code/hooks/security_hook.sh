#!/usr/bin/env bash
# Security hook for Claude Code PreToolUse (Bash tool)
# - Audit logs every command attempt
# - Blocks data exfiltration patterns
# - Provides helpful messages for dangerous patterns
#
# Exit codes: 0 = allow, 2 = block (message shown to Claude)
#
# Template variables:
#   __PROJECT_NAME__ - replaced with project name during installation

set -euo pipefail

# --- Read tool input from stdin ---
INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)

# Only process Bash tool calls
if [[ "$TOOL_NAME" != "Bash" ]]; then
    exit 0
fi

COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
if [[ -z "$COMMAND" ]]; then
    exit 0
fi

# --- Audit logging ---
LOG_DIR="$HOME/.llmsec/logs"
LOG_FILE="$LOG_DIR/__PROJECT_NAME___audit.log"
mkdir -p "$LOG_DIR"

TIMESTAMP=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
STATUS="ALLOWED"

log_entry() {
    echo "$TIMESTAMP | $1 | $COMMAND" >> "$LOG_FILE"
}

block() {
    STATUS="BLOCKED"
    log_entry "$STATUS"
    echo "$1" >&2
    exit 2
}

# --- Data theft prevention ---

# Exfiltration to paste/upload services
if echo "$COMMAND" | grep -qiE '(curl|wget|http).*(pastebin\.com|transfer\.sh|file\.io|paste\.ee|hastebin|0x0\.st|ix\.io)'; then
    block "BLOCKED: Data exfiltration attempt detected.
Reason: Command appears to send data to an external paste/upload service.
Suggestion: If you need to share output, write it to a local file instead.
Alternatives: Write to /tmp/output.txt or use the Write tool."
fi

# Base64 encoding of sensitive files
if echo "$COMMAND" | grep -qiE 'base64.*(\.env|credentials|_key\.pem|id_rsa|id_ed25519|\.aws)'; then
    block "BLOCKED: Encoding sensitive file detected.
Reason: Base64-encoding secrets could facilitate exfiltration.
Suggestion: Never encode credentials or keys. Use environment variables instead.
Alternatives: Reference secrets via \$ENV_VAR, don't read the files directly."
fi

# Direct access to sensitive files via cat/tar/zip
if echo "$COMMAND" | grep -qiE '(cat|tar|zip|gzip|7z)\s.*(\.env|\.ssh/|\.aws/|credentials|_key\.pem|id_rsa|id_ed25519|\.gnupg)'; then
    block "BLOCKED: Access to sensitive file detected.
Reason: Reading/archiving credentials, keys, or secrets is not permitted.
Suggestion: Use environment variables to reference secrets, never read them directly.
Alternatives: Check .env.example for variable names, use \$ENV_VAR syntax."
fi

# SCP/rsync of sensitive files
if echo "$COMMAND" | grep -qiE '(scp|rsync)\s.*(\.env|\.ssh|\.aws|credentials|_key\.pem)'; then
    block "BLOCKED: Transfer of sensitive files detected.
Reason: Copying credentials or keys to remote hosts is not permitted.
Suggestion: Use secure secret management (vault, env vars) instead.
Alternatives: Configure secrets on the target host directly."
fi

# --- Helpful blocking for dangerous patterns ---

# rm -rf / rm -r
if echo "$COMMAND" | grep -qE '(^|\s|;|&&|\|)rm\s+(-[a-zA-Z]*r[a-zA-Z]*f?|(-[a-zA-Z]*f[a-zA-Z]*)?-[a-zA-Z]*r)\s'; then
    block "BLOCKED: Recursive delete (rm -rf / rm -r) is not allowed.
Reason: Recursive deletion is destructive and hard to reverse.
Suggestion: Move files to a trash directory instead: mv <path> /tmp/trash/
Alternatives:
  - Use 'ls' first to inspect what would be deleted
  - Delete specific files by name (non-recursive)
  - Ask the user to perform the deletion manually"
fi

# sudo
if echo "$COMMAND" | grep -qE '(^|\s|;|&&|\|)sudo\s'; then
    block "BLOCKED: sudo (privilege escalation) is not allowed.
Reason: Running commands as root can cause system-wide damage.
Suggestion: Work within your current user permissions.
Alternatives:
  - Check if the operation can be done without root
  - Ask the user to run the privileged command manually"
fi

# chmod 777
if echo "$COMMAND" | grep -qE 'chmod\s+777'; then
    block "BLOCKED: chmod 777 (world-writable permissions) is not allowed.
Reason: Making files world-readable/writable is a security vulnerability.
Suggestion: Use minimal permissions: chmod 644 (files) or chmod 755 (directories).
Alternatives:
  - chmod 644 <file>  (owner read/write, others read)
  - chmod 755 <dir>   (owner full, others read/execute)
  - chmod 600 <file>  (owner read/write only, for secrets)"
fi

# dd
if echo "$COMMAND" | grep -qE '(^|\s|;|&&|\|)dd\s'; then
    block "BLOCKED: dd (disk/data duplicator) is not allowed.
Reason: dd can overwrite disks and cause irreversible data loss.
Suggestion: Use cp for file copying, or ask the user to run dd manually.
Alternatives: cp <source> <dest>"
fi

# git push --force / -f
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*(-f|--force)'; then
    block "BLOCKED: Force push is not allowed.
Reason: Force pushing overwrites remote history and can destroy others' work.
Suggestion: Use regular 'git push' or 'git push --force-with-lease' (with user approval).
Alternatives:
  - git push (regular push)
  - git push --force-with-lease (safer, only if no new remote commits)
  - Ask the user before force pushing"
fi

# --- Command allowed ---
log_entry "$STATUS"
exit 0
