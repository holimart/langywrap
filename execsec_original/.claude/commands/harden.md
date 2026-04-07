Run the llmsec repository hardening tool to install security hooks for AI coding tools.

Pass arguments through to `tools/harden/harden.sh`. The script auto-detects which AI tool is configured in the target directory and installs appropriate hooks.

```
Usage: /harden [TARGET_DIR] [OPTIONS]
  TARGET_DIR         Directory to harden (default: current directory)
  --tool TOOL        claude-code, opencode, cursor, cline, windsurf, all
  --project NAME     Project name for audit logs
  --no-hooks         Skip tool-specific hooks
  --no-git-hooks     Skip git hooks
  --no-settings      Skip settings modifications
  --with-wrapper     Install shell wrapper (fallback for tools without hooks)
  --dry-run          Preview changes
```

Run the hardening command:

```bash
bash "$CLAUDE_PROJECT_DIR/tools/harden/harden.sh" $ARGUMENTS
```

After running, report what was installed and suggest verification steps.
