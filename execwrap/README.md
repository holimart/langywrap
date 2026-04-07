# ExecWrap — Universal AI Tool Execution Wrapper

ExecWrap makes any AI coding tool (Claude Code, OpenCode, Cursor, Windsurf, etc.) benefit from security hardening, env loading, command rewriting, adhoc script capture, and centralized logging — even if the tool has no native hook/permission system.

## Quick Start

```bash
# Wrap Claude Code
.exec/execwrap.bash claude

# Wrap OpenCode
.exec/execwrap.bash opencode

# Test interactively with a wrapped bash shell
.exec/execwrap.bash bash
```

---

## Security Architecture — 5 Layers

Commands pass through layers in order. A command blocked by any layer never executes.

```
Layer 1: .exec/settings.json rules       ← ALWAYS ACTIVE (JSON, edit this file)
Layer 2: .llmsec/guard.sh                ← installed by /harden-wizard --with-wrapper
Layer 3: intercept-enhanced.py           ← needs execsec/ submodule + python3
Layer 4: tool-native hooks               ← installed by /harden-wizard (per-tool)
Layer 5: git hooks                       ← installed by /harden-wizard (git level)
```

**Current status in this repo:**
- Layer 1: ✓ ACTIVE (settings.json rules — deny/allow/rewrite)
- Layer 2: ✗ not installed (run `/harden-wizard` at Maximum level)
- Layer 3: ✓ ACTIVE (execsec/ submodule present)
- Layer 4: ✗ not installed
- Layer 5: ✗ not installed

**Redundancy is intentional.** Several rules appear across multiple layers (e.g., `rm -rf` is in Layer 1, 2, and 3). Each layer provides independent protection — defence in depth.

---

## How It Works

### Launcher Mode

```bash
.exec/execwrap.bash claude
```

Sets `SHELL=execwrap.bash` and `BASH_ENV=preload.sh`, then launches the tool. Every bash command the tool runs goes through execwrap first.

### Shell Mode

When the wrapped tool calls bash internally, it calls `execwrap.bash -c "command"`. ExecWrap:
1. Loads `.env`
2. Applies local binary priority (`./just` over `just`, etc.)
3. Matches against Layer 1 rules (deny/allow/rewrite/ask)
4. Runs Layers 2 + 3 (execsec hardening)
5. Saves adhoc scripts to `scripts/adhoc/`
6. Runs Layer 4 hooks
7. Sets up log file
8. Executes (via tmux if enabled, else directly with tee)

### Check Mode

```bash
.exec/execwrap.bash --check "command"
```

Validates a command and exits 0 (allowed) or 1 (blocked) **without executing**. Used by `preload.sh`'s DEBUG trap to validate each command in a running script before bash executes it. This prevents double-execution.

---

## Configuration Reference

All behavior is controlled in `.exec/settings.json`. No bash editing required.

### Feature Flags

```json
"features": {
  "env_loading":   { "enabled": true,  "env_file": ".env" }
  "adhoc_saving":  { "enabled": true,  "dir": "scripts/adhoc" }
  "logging":       { "enabled": true,  "dir": ".log" }
  "tmux":          { "enabled": false, "default_mode": "window", "session_prefix": "execwrap" }
  "hooks":         { "enabled": true,  "dirs": [".claude/hooks", ".git/hooks"] }
  "local_priority":{ "enabled": true,  "binaries": ["just", "uv", "python", ...] }
  "debug_info":    { "enabled": true }
  "hardening":     { "enabled": true,
    "guard":       { "enabled": false, "path": ".llmsec/guard.sh" }
    "interceptor": { "enabled": true,  "path": "execsec/tools/interceptors/intercept-enhanced.py" }
  }
}
```

To disable a feature without removing it: `"enabled": false`.

### Rule Schema

```json
{
  "id": "my-rule",
  "description": "Human-readable description",
  "match": {
    "glob": "pattern *",        // shell-style glob (case-sensitive)
    "regex": "^pattern\\s"      // grep -E regex (at least one must match)
  },
  "action": "deny|allow|rewrite|ask",
  "reason": "Why this rule exists",
  "alternative": "What to do instead",
  "rewrite": {
    "prepend": "prefix",        // add before command
    "append": "suffix",         // add after command
    "replace": "new command"    // completely replace
  },
  "tmux": "window|session|none|null",  // override default tmux mode
  "enabled": true
}
```

**Rule evaluation order:**
1. Rules are matched top-to-bottom, first match wins
2. Rewrite rules apply before the next rule match
3. After a rewrite, rules are re-evaluated from the top
4. Deny rules always block immediately

### Rule Writing Guide

**Deny rule (block a command):**
```json
{
  "id": "deny-deploy-prod",
  "description": "Block direct production deployments",
  "match": { "glob": null, "regex": "deploy.*production|kubectl.*prod" },
  "action": "deny",
  "reason": "Production deployments require peer review and manual approval.",
  "alternative": "Deploy to staging first: ./deploy.sh staging — then request approval.",
  "enabled": true
}
```

**Rewrite rule (transform a command):**
```json
{
  "id": "rewrite-npm-to-pnpm",
  "description": "Use pnpm instead of npm",
  "match": { "glob": "npm *", "regex": "^npm\\s" },
  "action": "rewrite",
  "rewrite": { "replace": null, "prepend": null, "append": null }
}
```
(Use `prepend`, `append`, or `replace` — only one typically needed)

**Ask rule (prompt for confirmation):**
```json
{
  "id": "ask-database-migration",
  "description": "Ask before running migrations",
  "match": { "glob": null, "regex": "alembic.*upgrade|flask.*db.*upgrade" },
  "action": "ask",
  "enabled": true
}
```

**Allow rule (explicitly permit something):**
```json
{
  "id": "allow-known-safe-script",
  "description": "Allow this specific script that matches a deny pattern",
  "match": { "glob": "bash scripts/safe-thing.sh", "regex": null },
  "action": "allow",
  "enabled": true
}
```
Place allow rules ABOVE the deny rules they override.

---

## tmux Integration

When `features.tmux.enabled: true` (requires tmux installed), commands run in a named tmux window:

```bash
# Watch all wrapped commands live
tmux attach -t execwrap

# Commands in their own windows
.exec/execwrap.bash bash
# → tmux session: execwrap
# → new window:   143512_12345 (timestamp_pid)
```

**Per-rule override:**
```json
{ "id": "my-rule", ..., "tmux": "window" }   // own window (default)
{ "id": "my-rule", ..., "tmux": "session" }  // own session (full isolation)
{ "id": "my-rule", ..., "tmux": null }        // inherit default
```

To enable: install tmux, then set `"features.tmux.enabled": true` in settings.json.

---

## Adhoc Script Pool

When a command like `bash -c 'complex script'` or `python -c 'code'` runs, execwrap saves the inline script to `scripts/adhoc/` for later analysis:

```
scripts/adhoc/
  20260223_143512_12345.sh   # bash -c '...' captured here
  20260223_143600_12346.py   # python -c '...' captured here
```

Each file has a header comment showing the original command and timestamp. This is useful for:
- Reviewing what the AI tool ran
- Turning one-off scripts into proper files
- Auditing command history

The `scripts/adhoc/` directory is gitignored (scripts themselves are transient). The directory is kept in git.

---

## Logging

All command output is tee'd to `.log/` (also gitignored):

```
.log/
  20260223_143512_12345_python_script_py.log
  20260223_143600_12346_just_test.log
```

Format: `<timestamp>_<pid>_<sanitized-command>.log`

To disable: `"features.logging.enabled": false`

---

## Layer Configuration

### Layer 2: guard.sh (not installed)

Install with:
```bash
/harden-wizard   # select Maximum security level
```

This runs `execsec/tools/harden/harden.sh --with-wrapper` which:
- Instantiates `execsec/templates/shell-wrapper/guard.sh` into `.llmsec/guard.sh`
- Creates `.llmsec/guard-exec.sh` (shell replacement for direct $SHELL use)
- Installs git hooks, Claude Code hooks, etc.

After installation, set `"features.hardening.guard.enabled": true` in settings.json.

### Layer 3: intercept-enhanced.py (active)

Requires python3 and PyYAML:
```bash
pip install pyyaml   # or: ./uv pip install pyyaml
```

The 57-rule YAML config is at `execsec/configs/defaults/permissions.yaml`.

To customize rules, create `.settings/permissions.yaml` (takes precedence over defaults):
```yaml
version: "1.0"
deny:
  - pattern: "my-dangerous-command"
    reason: "Why it's dangerous"
    suggestion: "What to do instead"
```

---

## Extending: Adding New Rules

1. Open `.exec/settings.json`
2. Add a rule to the `"rules"` array (before the first deny that would catch it)
3. Use `jq . .exec/settings.json` to validate JSON
4. Restart the wrapped tool (feature flags are cached at launch)

No bash editing required. All behavior is data-driven from settings.json.

---

## Troubleshooting

**`jq` not found:**
```bash
sudo apt install jq    # Ubuntu/Debian
brew install jq        # macOS
```

**`tmux` not available:**
Set `"features.tmux.enabled": false` in settings.json (already done). Install tmux and re-enable when ready.

**Layer 3 blocked a legitimate command:**
Check `execsec/configs/defaults/permissions.yaml` for the rule. Add an allow rule to `.settings/permissions.yaml`:
```yaml
allow:
  - pattern: "the-command-here"
    reason: "Legitimate use in this project"
```

**guard.sh shows `__REAL_SHELL__` warning:**
The template was not instantiated. Run `/harden-wizard` to fix.

**`python3` blocked by .claude/settings.json:**
This repo's .claude/settings.json denies `Bash(python3:*)` to enforce `./uv run python`. ExecWrap's rewrite rules handle this automatically: `python3 foo.py` → `uv run python3 foo.py` → `./uv run python3 foo.py`.

**Command runs twice:**
The DEBUG trap in preload.sh uses `--check` mode (validates only, no execution). If you see double execution, check that execwrap.bash is on PATH or called with full path in BASH_ENV.

**preload.sh DEBUG trap fires on builtins:**
The trap skips common builtins (`local`, `export`, `declare`, etc.). If a specific builtin triggers false positives, add it to the `case "$cmd" in` skip list in preload.sh.

---

## AI Tool Config Translation

The following were imported from `.claude/settings.json`:

| Original Rule | ExecWrap Rule ID | Notes |
|---------------|------------------|-------|
| `Bash(rm -rf:*)` | `deny-rm-rf` | Covered by default rule |
| `Bash(uv:*)` | `translated-claude-deny-bare-uv` | local_priority handles this automatically |
| `Bash(just:*)` | `translated-claude-deny-bare-just` | local_priority handles this automatically |
| `Bash(python:*)` | `translated-claude-deny-bare-python` | rewrite-python-to-uv fires first |
| `Bash(python3:*)` | `translated-claude-deny-bare-python3` | rewrite-python-to-uv fires first |

The local_priority feature (`./uv` over `uv`, `./just` over `just`) handles most of these automatically. The deny rules are safety nets.
