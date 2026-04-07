You are an interactive security hardening wizard. Walk the user through hardening their repository step by step.

## Steps

### 1. Detect environment
Scan the target directory (use $ARGUMENTS if provided, otherwise ask) for AI tool configs:
- `.claude/` → Claude Code
- `.cursor/` → Cursor
- `opencode.json` or `.opencode/` → OpenCode
- `.clinerules/` or `.clinerules` → Cline
- `.windsurfrules` → Windsurf
- `.git/` → Git repository

Report what you find.

### 2. Choose tools
Ask which AI tools to harden for. Pre-select any detected tools. Offer to add others.

### 3. Choose security level
Present three options:
- **Basic**: Git hooks only (pre-commit + pre-push). Works with all tools, minimal footprint.
- **Recommended**: Git hooks + tool-native hooks with audit logging. Best balance of protection and convenience.
- **Maximum**: All of the above + shell wrapper + data theft prevention deny rules. Full hardening.

### 4. Customize (optional)
Ask about:
- Custom project name for audit logs? (default: directory basename)
- Additional sensitive file patterns to protect?
- Additional blocked commands?

### 5. Preview
Run the hardening script with `--dry-run` first to show what will be created/modified:

```bash
bash "$CLAUDE_PROJECT_DIR/tools/harden/harden.sh" <TARGET_DIR> --tool <TOOL> --project <NAME> --dry-run [other flags]
```

Show the output and ask for confirmation.

### 6. Apply
Run the hardening script for real:

```bash
bash "$CLAUDE_PROJECT_DIR/tools/harden/harden.sh" <TARGET_DIR> --tool <TOOL> --project <NAME> [other flags]
```

### 7. Verify
Test the installed hooks:
- For Claude Code: pipe test JSON to the hook and verify exit code 2 for dangerous commands
- For Cursor: pipe test JSON and verify `"permission":"deny"` in output
- For Cline: pipe test JSON and verify `"cancel":true` in output
- For git hooks: check that `.githooks/` exists and `core.hooksPath` is set

### 8. Next steps
Print guidance:
- Commit the hooks to version control
- Share with team
- How to customize further
- Where audit logs are stored
