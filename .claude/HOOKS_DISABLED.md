# Hooks disabled in .claude/settings.json

Disabled 2026-04-18. JSON does not support comments, so notes live here.

## Previously configured (project-level PreToolUse)

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/rtk-rewrite.sh"
          }
        ]
      }
    ]
  }
}
```

## Why disabled

The relative path `bash .claude/hooks/rtk-rewrite.sh` fails with
`No such file or directory` because Claude Code hooks do not always run with
CWD = project root. The script itself exists at
`.claude/hooks/rtk-rewrite.sh` — only the invocation path is wrong.

## How to fix and re-enable

Replace the command with an absolute path using `$CLAUDE_PROJECT_DIR`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/rtk-rewrite.sh"
          }
        ]
      }
    ]
  }
}
```

## Interaction with global hook

As of 2026-04-18, the global `~/.claude/settings.json` now runs rtk-rewrite.sh
from `$HOME/.claude/hooks/rtk-rewrite.sh`. That global hook already fires on
every Bash tool call in every project (including this one) and already has the
`__EXECWRAP_ACTIVE` guard.

**Do not also re-enable the project-level rtk-rewrite.sh** — it would run the
exact same rewrite logic twice per Bash call. Re-enable the project hook only
if it is changed to do something different from the global one.

The global security_hook.sh is still disabled — see `~/.claude/HOOKS_DISABLED.md`.
