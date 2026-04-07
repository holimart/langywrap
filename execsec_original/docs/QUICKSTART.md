# Quick Start Guide

Get basic AI agent security protection running in under 10 minutes.

## Prerequisites

- Linux or macOS
- Bash or Zsh shell
- Git
- Optional: Docker (for container isolation)

## Installation

### 1. Clone the Repository

```bash
cd ~/projects  # or your preferred location
git clone <your-repo-url> llmsec
cd llmsec
```

### 2. Run Phase 1 Setup (5 minutes)

This installs the most critical protections:

```bash
./scripts/phase1/setup.sh
```

**What it does:**
- ✅ Creates emergency kill switch
- ✅ Configures resource limits
- ✅ Sets up Claude Code permission blocklist
- ✅ Blocks dangerous commands (`rm -rf`, `dd`, etc.)

### 3. Reload Your Shell

```bash
# For Bash
source ~/.bashrc

# For Zsh
source ~/.zshrc
```

### 4. Test the Installation

```bash
# Test the kill switch
~/bin/kill-claude.sh

# Verify intercept tool
~/bin/intercept.py "echo 'test'"  # Should work
~/bin/intercept.py "rm -rf /"     # Should block
```

## Usage

### Run Claude Code Securely

Instead of running `claude` directly, use:

```bash
claude-safe
```

This applies resource limits:
- Max 4GB memory
- Max 300 seconds CPU time
- Max 1GB file size

### Emergency Stop

If something goes wrong:

```bash
~/bin/kill-claude.sh
```

Or use the keyboard shortcut (if configured).

### Monitor Activity

```bash
# Start monitoring in background
~/bin/claude-monitor.sh &

# View logs
tail -f ~/.claude-monitor.log
```

## What's Protected

After Phase 1 setup, you're protected against:

| Threat | Protected |
|--------|-----------|
| `rm -rf /` and similar destructive commands | ✅ Yes |
| Filesystem damage (`dd`, `mkfs`, etc.) | ✅ Yes |
| System shutdown/reboot | ✅ Yes |
| Privilege escalation (`sudo`, `su`) | ✅ Yes |
| Resource exhaustion (fork bombs, etc.) | ✅ Yes |
| Data exfiltration | ⚠️ Optional (Phase 2) |
| Network attacks | ⚠️ Optional (Phase 3) |

## Next Steps

### Add More Protection Layers

**Phase 2: Tool Interception** (~2 hours)
- Command pattern analysis
- Container isolation
- Network egress control

```bash
./scripts/phase2/setup.sh
```

**Phase 3: Execution Isolation** (~4-8 hours)
- MicroVM isolation (Firecracker/gVisor)
- Syscall interception
- Credential isolation

```bash
./scripts/phase3/setup.sh
```

**Phase 4: Output Validation** (~1 hour)
- Pre-commit hooks
- Static code analysis
- Secret scanning

```bash
./scripts/phase4/setup.sh
```

**Phase 5: Monitoring** (~1 hour)
- Real-time monitoring dashboard
- Automated alerting
- File access auditing

```bash
./scripts/phase5/setup.sh
```

### Enable Data Theft Prevention

Add to your shell config:

```bash
export ENABLE_DATA_THEFT_PREVENTION=true
```

This blocks access to:
- `~/.ssh/`, `~/.aws/`, `~/.kube/`
- `.env` files
- Credential files
- Private keys

### Customize Blocked Commands

Edit `configs/claude/settings.json` to add your own patterns:

```json
{
  "permissions": {
    "deny": [
      "Bash(your-dangerous-command:*)"
    ]
  }
}
```

## Troubleshooting

### "Permission denied" when running scripts

```bash
chmod +x ~/bin/kill-claude.sh
chmod +x tools/monitors/claude-monitor.sh
chmod +x tools/interceptors/intercept.py
```

### Claude still runs dangerous commands

1. Check if settings are loaded:
```bash
cat ~/.claude/settings.json
```

2. Ensure Claude Code sandbox is enabled:
- Run `/sandbox` in Claude Code
- Select "Sandbox with network restrictions"

### Monitor not starting

```bash
# Check if already running
ps aux | grep claude-monitor

# Kill existing monitor
kill $(cat ~/.claude-monitor.pid)

# Start fresh
~/bin/claude-monitor.sh &
```

## Configuration Files

| File | Purpose |
|------|---------|
| `~/.claude/settings.json` | Claude Code permissions |
| `~/.claude-intercept.log` | Command intercept logs |
| `~/.claude-monitor.log` | Process monitor logs |
| `~/bin/kill-claude.sh` | Emergency stop script |

## Getting Help

- **Documentation**: See `docs/` directory
- **Issues**: GitHub Issues
- **Security**: See SECURITY.md

## Verification

Verify your setup is working:

```bash
# 1. Check settings are in place
test -f ~/.claude/settings.json && echo "✅ Settings configured" || echo "❌ Settings missing"

# 2. Check kill switch exists
test -x ~/bin/kill-claude.sh && echo "✅ Kill switch ready" || echo "❌ Kill switch missing"

# 3. Check alias exists
alias | grep claude-safe && echo "✅ Safe alias configured" || echo "❌ Alias missing (reload shell)"

# 4. Test intercept (should block)
python3 tools/interceptors/intercept.py "rm -rf /" 2>&1 | grep -q "BLOCKED" && echo "✅ Intercept working" || echo "❌ Intercept not working"
```

All checks should show ✅.

---

**You're now protected!** The basic security layer is active and will block the most common threats.
