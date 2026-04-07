# Secure-Run Orchestrator Guide

**One command to secure them all.**

## Overview

`secure-run.sh` is the universal orchestrator that applies **all 5 security layers** to any AI agent (Claude Code, OpenCode, or custom) with a single command.

## Quick Start

```bash
# Clone the repository
git clone <repo-url> llmsec
cd llmsec

# Run Claude Code with all security enabled
./secure-run.sh

# That's it! Claude launches with full protection.
```

## Philosophy

### All Security On By Default

Every security layer is **enabled by default**. You explicitly turn off what you don't need:

```bash
# Default: Everything enabled
./secure-run.sh

# Turn off specific layers
./secure-run.sh --no-docker        # Skip Docker isolation
./secure-run.sh --no-monitoring    # Skip monitoring
```

### Helpful, Not Hostile

When commands are blocked, the agent receives **polite, constructive feedback**:

❌ **Bad**: "Command blocked"

✅ **Good**:
```
❌ Recursive deletion blocked for safety

Reason: Recursive delete can cause permanent data loss

💡 Suggested Alternative:
   Instead of deleting files directly, please:
   1. Create a TODO comment: # TODO: Delete /path/to/file
   2. Or move to trash: mv /path/to/file ~/.trash/
   3. Or ask the user: "Should I delete /path/to/file?"

✓ Safe Alternatives:
   • Create deletion marker file
   • Add to .gitignore if unwanted
   • Ask user for confirmation
```

### Configuration Hierarchy

Configurations are discovered automatically in this order (most restrictive wins):

1. **Project**: `.settings/` (your project's specific rules)
2. **Project**: `.claude/` (Claude Code config)
3. **Project**: `.opencode/` (OpenCode config)
4. **User**: `~/.llmsec/defaults/` (your personal defaults)
5. **Bundled**: `llmsec/configs/defaults/` (fallback defaults)

## Usage

### Basic Usage

```bash
# Run Claude Code with all security
./secure-run.sh

# Run OpenCode with all security
./secure-run.sh --app=opencode

# Run custom agent
./secure-run.sh -- python my-agent.py
```

### Security Presets

```bash
# Basic: Layers 1 + 5 (permissions + monitoring)
./secure-run.sh --level=basic

# Recommended: Layers 1 + 2 + 3 + 5 (all except validation)
./secure-run.sh --level=recommended

# Maximum: All 5 layers
./secure-run.sh --level=maximum
```

### Layer Control

```bash
# Disable specific layers
./secure-run.sh --no-input-filter    # No permission blocklists
./secure-run.sh --no-interceptor     # No command interception
./secure-run.sh --no-isolation       # No Docker/sandbox
./secure-run.sh --no-validation      # No pre-commit hooks
./secure-run.sh --no-monitoring      # No process monitoring
```

### Isolation Methods

```bash
# Auto-detect best method (default)
./secure-run.sh

# Force specific method
./secure-run.sh --isolation=docker
./secure-run.sh --isolation=bubblewrap
./secure-run.sh --isolation=none
```

### Project Directory

```bash
# Use current directory (default)
./secure-run.sh

# Specify project directory
./secure-run.sh --project-dir=/path/to/project
```

## Configuration

### Creating Project-Specific Rules

```bash
# In your project directory
mkdir -p .settings

# Create permissions config
cat > .settings/permissions.yaml << 'EOF'
version: "1.0"

# Add project-specific denies
deny:
  - pattern: "deploy:production"
    message: "❌ Production deployment blocked"
    suggestion: "Use staging environment for testing first"

# Add project-specific asks
ask:
  - pattern: "npm:publish"
    message: "⚠️  NPM publish requires confirmation"
    prompt: "Publish to NPM registry?"
EOF
```

### Customizing Messages

Each rule can have:

```yaml
- pattern: "rm:-rf"              # What to match
  reason: "Prevents data loss"    # Why it's blocked
  message: "❌ Deletion blocked"  # What agent sees
  suggestion: |                   # How to do it safely
    Instead of deleting:
    - Create TODO marker
    - Move to trash
    - Ask user
  alternatives:                   # Quick alternatives list
    - "Mark for deletion"
    - "Add to .gitignore"
```

### Resource Limits

```bash
# Create .settings/resources.yaml
cat > .settings/resources.yaml << 'EOF'
version: "1.0"

cpu:
  max_time: 600       # 10 minutes
  cpus: 4            # 4 cores

memory:
  max_virtual: 8000000000  # 8GB

filesystem:
  max_file_size: 2000000000  # 2GB
EOF
```

## Examples

### Example 1: Basic Protection for Trusted Project

```bash
# Only essential protection
./secure-run.sh --level=basic

# Enables:
#   ✓ Layer 1: Permission blocklists
#   ✓ Layer 5: Monitoring
# Skips:
#   ✗ Interceptor (trusting the agent)
#   ✗ Docker (overhead not needed)
#   ✗ Validation (manual review instead)
```

### Example 2: Maximum Security for Untrusted Code

```bash
# All layers, full isolation
./secure-run.sh --level=maximum --isolation=docker

# Enables:
#   ✓ Layer 1: Permission blocklists
#   ✓ Layer 2: Command interception
#   ✓ Layer 3: Docker isolation
#   ✓ Layer 4: Pre-commit hooks + Semgrep
#   ✓ Layer 5: Real-time monitoring
```

### Example 3: Custom Configuration Per Project

```bash
# Project directory structure
my-project/
├── .settings/
│   ├── permissions.yaml    # Project-specific rules
│   └── resources.yaml      # Custom resource limits
├── src/
└── ...

# Run from project directory
cd my-project
/path/to/llmsec/secure-run.sh

# secure-run automatically finds and applies .settings/ configs
```

### Example 4: Running Non-Claude Agents

```bash
# Secure any Python agent
./secure-run.sh -- python my_agent.py --verbose

# Secure any command
./secure-run.sh -- node agent.js
```

## What Gets Protected

### Layer 1: Input Filtering

**Blocks immediately**:
- `rm -rf` (recursive delete)
- `sudo` (privilege escalation)
- `shutdown` (system control)
- `chmod 777` (insecure permissions)

**Asks for confirmation**:
- `npm install` (package installation)
- `git push` (publishing code)
- `docker run` (resource usage)

**Allows automatically**:
- `cat`, `grep`, `find` (reading)
- `ls`, `pwd`, `cd` (navigation)
- `git status`, `git log` (git queries)

### Layer 2: Command Interception

**Analyzes every command** for:
- Dangerous patterns (regex-based)
- Data exfiltration attempts
- Suspicious network activity
- Credential access

**Provides helpful feedback** when blocking.

### Layer 3: Execution Isolation

**Isolates execution** using:
- Docker containers (network isolated)
- Bubblewrap (filesystem sandbox)
- Resource limits (ulimit)

**Prevents**:
- Breaking out of project directory
- Accessing system files
- Consuming unlimited resources

### Layer 4: Output Validation

**Scans generated code** for:
- Dangerous patterns (Semgrep)
- Secrets and credentials (Gitleaks)
- Vulnerable dependencies

**Blocks commits** with security issues.

### Layer 5: Monitoring

**Watches in real-time** for:
- CPU/memory spikes
- Suspicious processes
- Dangerous command patterns

**Logs everything** for audit.

## Helpful Blocking Messages

### Example: Blocked rm -rf

```
==================================================================
❌ Recursive deletion blocked for safety

Reason: Recursive delete can cause permanent data loss

💡 Suggested Alternative:
   Instead of deleting files directly, please:
   1. Create a TODO comment: # TODO: Delete /path/to/file
   2. Or move to trash: mv /path/to/file ~/.trash/
   3. Or ask the user: "Should I delete /path/to/file?"

✓ Safe Alternatives:
   • Create deletion marker file
   • Add to .gitignore if unwanted
   • Ask user for confirmation
==================================================================
```

### Example: Ask for npm install

```
==================================================================
⚠️  Package installation requires confirmation

Install npm package?
Package: express
Reason: Package installation can introduce vulnerabilities
Security: Package will be scanned for known vulnerabilities

Command: npm install express
Reason: Package installation can introduce vulnerabilities
==================================================================

Proceed? [y/N]: _
```

## Logging

All activity is logged:

```bash
# View intercept log
tail -f ~/.llmsec/logs/intercept.log

# View monitor log
tail -f ~/.llmsec/logs/claude-monitor.log

# View session log
tail -f ~/.llmsec/logs/secure-run-<timestamp>.log
```

Log format:
```
[2026-02-08T10:30:00] [BLOCKED] rm -rf /tmp/file | Reason: Recursive delete
[2026-02-08T10:30:15] [ALLOWED] cat README.md | Reason: Reading files is safe
[2026-02-08T10:30:30] [APPROVED_BY_USER] npm install express | User confirmed
```

## Emergency Stop

If something goes wrong:

```bash
# Kill switch (from another terminal)
/path/to/llmsec/tools/kill-claude.sh

# Or use keyboard interrupt
Ctrl+C  # In secure-run terminal
```

## Troubleshooting

### "Config file not found"

```bash
# Check search paths
./secure-run.sh --verbose

# Create default config
mkdir -p .settings
cp /path/to/llmsec/configs/defaults/permissions.yaml .settings/
```

### "Docker not found"

```bash
# Use different isolation
./secure-run.sh --isolation=bubblewrap

# Or disable isolation
./secure-run.sh --no-isolation
```

### "Too many blocks"

```bash
# Use less restrictive preset
./secure-run.sh --level=basic

# Or customize .settings/permissions.yaml
```

### "Want to see what's happening"

```bash
# Verbose mode
./secure-run.sh --verbose

# Check logs in real-time
tail -f ~/.llmsec/logs/secure-run-*.log
```

## Advanced Usage

### Chaining Multiple Configs

Most restrictive wins:

```yaml
# .settings/permissions.yaml (project-specific)
deny:
  - pattern: "deploy:*"
    message: "No deployments from this project"

# ~/.llmsec/defaults/permissions.yaml (user defaults)
deny:
  - pattern: "rm:*"
    message: "No deletions ever"

# Result: Both rules apply (merged)
```

### Custom Messages Per Rule

```yaml
deny:
  - pattern: "dangerous-script.sh"
    message: "❌ This script is deprecated"
    suggestion: |
      Use the new version instead:
        ./scripts/safe-script.sh

      Documentation: docs/migration-guide.md
    alternatives:
      - "safe-script.sh --mode=compatibility"
      - "Ask in #dev-help for migration assistance"
```

### Testing Your Configuration

```bash
# Test without actually running
./secure-run.sh --dry-run

# Test specific command
/path/to/llmsec/tools/interceptors/intercept-enhanced.py "rm -rf /tmp"
# Should show helpful block message
```

## Best Practices

1. **Start with defaults**: Don't customize until you need to
2. **Use project-specific configs**: Keep rules with the project
3. **Document your rules**: Add comments explaining WHY
4. **Test interactively**: Run once and see what gets blocked
5. **Iterate**: Adjust based on actual workflow
6. **Keep logs**: Review periodically for anomalies

## Integration

### CI/CD

```yaml
# .github/workflows/secure-dev.yml
name: Secure Development
on: [push]
jobs:
  secure-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run with security
        run: |
          git clone https://github.com/you/llmsec
          ./llmsec/secure-run.sh --level=maximum -- ./run-tests.sh
```

### VS Code Integration

```json
// .vscode/tasks.json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Secure Claude",
      "type": "shell",
      "command": "/path/to/llmsec/secure-run.sh",
      "problemMatcher": []
    }
  ]
}
```

## Using Interceptors as Validators

All interceptors (`guard.sh`, `intercept.py`, `intercept-enhanced.py`) default to
**check-only mode**: they validate a command and return exit 0 (allowed) or exit 1
(blocked) without executing the command.

This makes them composable pre-checks. A caller can validate first, then execute
independently — no double-execution risk.

```bash
# Check-only (default) — validate, don't execute
guard.sh -c "ls /tmp"              # → exit 0, no output
guard.sh -c "rm -rf /"             # → exit 1, BLOCKED message

python3 intercept.py "echo hello"  # → exit 0, no output
python3 intercept.py "rm -rf /"    # → exit 1, BLOCKED message

python3 intercept-enhanced.py "sudo whoami"  # → exit 1
python3 intercept-enhanced.py "ls /tmp"      # → exit 0, no output
```

Use `--exec` (first argument) to check AND execute:

```bash
guard.sh --exec -c "echo hello"              # → exit 0, prints "hello"
python3 intercept.py --exec "echo hello"     # → exit 0, prints "hello"
python3 intercept-enhanced.py --exec "ls /"  # → exit 0, shows output
```

### Shell replacements

Two wrappers always run in exec mode (for use as `$SHELL`):

- `.llmsec/guard-exec.sh` — installed by harden-wizard, calls `guard.sh --exec`
- `tools/interceptors/intercept-wrapper.sh` — calls `intercept-enhanced.py --exec`

```bash
# Direct AI tool use (checks + executes):
SHELL=.llmsec/guard-exec.sh claude-code

# Via secure-run.sh (uses intercept-wrapper.sh internally):
./secure-run.sh
```

### ASK rules in check-only mode

When an ASK-rule command is checked in check-only mode, the prompt is deferred:
the interceptor logs `ALLOWED_ASK_DEFERRED` and exits 0. When the caller later
runs the command with `--exec`, the prompt fires normally.

This prevents the annoyance of double-prompts when using interceptors as
pre-validators before execution.

## See Also

- [Configuration Reference](CONFIG_REFERENCE.md)
- [Security Architecture](ARCHITECTURE.md)
- [Customization Guide](CUSTOMIZATION.md)
