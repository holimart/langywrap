#!/usr/bin/env bash
# =============================================================================
# RTK PreToolUse hook for Claude Code
# =============================================================================
# Rewrites Bash commands through RTK for 60-90% token savings.
# All rewrite logic is in `rtk rewrite` (src/discover/registry.rs).
# This hook is a thin JSON adapter for Claude Code's PreToolUse protocol.
#
# Exit code protocol from `rtk rewrite`:
#   0 + stdout  Rewrite found → auto-allow the rewritten command
#   1           No RTK equivalent → pass through unchanged
#   2           Deny rule matched → defer to Claude Code
#   3 + stdout  Ask rule matched → rewrite but let Claude Code prompt
# =============================================================================

# Require jq for JSON manipulation
if ! command -v jq &>/dev/null; then
  exit 0
fi

# Resolve RTK binary: .exec/rtk (project-local), then PATH
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RTK_BIN=""
if [ -x "$SCRIPT_DIR/.exec/rtk" ]; then
  RTK_BIN="$SCRIPT_DIR/.exec/rtk"
elif command -v rtk &>/dev/null; then
  RTK_BIN="$(command -v rtk)"
fi

if [ -z "$RTK_BIN" ]; then
  exit 0
fi

# Read the hook input (JSON on stdin)
INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -z "$CMD" ]; then
  exit 0
fi

# Delegate to RTK rewrite engine
REWRITTEN=$("$RTK_BIN" rewrite "$CMD" 2>/dev/null)
EXIT_CODE=$?

case $EXIT_CODE in
  0)
    # Rewrite found — auto-allow if changed
    [ "$CMD" = "$REWRITTEN" ] && exit 0
    ;;
  1|2)
    # No equivalent or deny — pass through
    exit 0
    ;;
  3)
    # Ask rule — rewrite but don't auto-allow
    ;;
  *)
    exit 0
    ;;
esac

ORIGINAL_INPUT=$(echo "$INPUT" | jq -c '.tool_input')
UPDATED_INPUT=$(echo "$ORIGINAL_INPUT" | jq --arg cmd "$REWRITTEN" '.command = $cmd')

if [ "$EXIT_CODE" -eq 3 ]; then
  # Ask: rewrite command, omit permissionDecision
  jq -n \
    --argjson updated "$UPDATED_INPUT" \
    '{
      "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "updatedInput": $updated
      }
    }'
else
  # Allow: rewrite and auto-allow
  jq -n \
    --argjson updated "$UPDATED_INPUT" \
    '{
      "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": "RTK auto-rewrite for token savings",
        "updatedInput": $updated
      }
    }'
fi
