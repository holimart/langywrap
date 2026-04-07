# Example Usage Scenarios

## Scenario 1: First Time Setup

**Goal**: Get basic security working quickly

```bash
# Clone the repo
cd ~/tools
git clone <repo-url> llmsec
cd llmsec

# Run the orchestrator (all defaults)
./secure-run.sh

# Claude Code launches with:
#   ✓ All 5 security layers enabled
#   ✓ Default configs from configs/defaults/
#   ✓ Monitoring in background
#   ✓ Helpful messages on blocks
```

**What happens when agent tries dangerous command**:

```bash
# Agent attempts: rm -rf /tmp/somedir
# User sees:

==================================================================
❌ Recursive deletion blocked for safety

Reason: Recursive delete can cause permanent data loss

💡 Suggested Alternative:
   Instead of deleting files directly, please:
   1. Create a TODO comment: # TODO: Delete /path/to/file
   2. Or move to trash: mv /path/to/file ~/.trash/
   3. Or ask the user: "Should I delete /path/to/file?"
==================================================================

# Agent receives this message and can:
# - Create TODO comment
# - Ask user to delete manually
# - Use safer alternative
```

---

## Scenario 2: Project-Specific Rules

**Goal**: Add custom security rules for your project

```bash
# In your project
cd ~/projects/my-app

# Create config directory
mkdir -p .settings

# Create custom permissions
cat > .settings/permissions.yaml << 'YAML'
version: "1.0"

# Block production deployments (safety)
deny:
  - pattern: "kubectl:apply:production"
    reason: "Production deployments require manual review"
    message: "❌ Production deployment blocked"
    suggestion: |
      To deploy to production:
      1. Create PR with deployment manifest
      2. Get team review
      3. Use CI/CD pipeline: gh workflow run deploy-prod
    alternatives:
      - "Deploy to staging: kubectl apply -f manifest.yaml -n staging"
      - "Run dry-run: kubectl apply --dry-run=client"

# Ask before expensive operations
ask:
  - pattern: "terraform:apply"
    reason: "Infrastructure changes affect costs and availability"
    message: "⚠️  Terraform apply requires confirmation"
    prompt: |
      Apply Terraform changes?
      This will modify infrastructure and may incur costs.
      Review plan carefully before proceeding.
YAML

# Run Claude with these rules
~/tools/llmsec/secure-run.sh

# Now your project-specific rules are active!
```

**Result**:
- Agent can't accidentally deploy to production
- User must confirm infrastructure changes
- Helpful guidance provided

---

## Scenario 3: Paranoid Mode (Maximum Security)

**Goal**: Lock down everything for untrusted code generation

```bash
# Enable ALL security layers + Docker isolation
cd ~/projects/untrusted-agent

~/tools/llmsec/secure-run.sh \
  --level=maximum \
  --isolation=docker

# What's active:
#   ✓ Layer 1: Strict permission blocklists
#   ✓ Layer 2: Command interception with data theft prevention
#   ✓ Layer 3: Docker isolation (network-none, read-only)
#   ✓ Layer 4: Pre-commit hooks + Semgrep + Gitleaks
#   ✓ Layer 5: Real-time monitoring + auto-kill
```

**Additional data theft prevention**:

```yaml
# Add to .settings/permissions.yaml
data_theft_prevention:
  enabled: true  # Enable credential protection

# Now blocks:
#   ❌ Reading .env files
#   ❌ Reading .aws/ credentials
#   ❌ Reading .ssh/ keys
#   ❌ Network calls to pastebin.com
#   ❌ Base64 encoding of sensitive files
```

---

## Scenario 4: Trusted Agent (Minimal Overhead)

**Goal**: Run trusted agent with minimal security overhead

```bash
# Basic security only (fast)
cd ~/projects/trusted-work

~/tools/llmsec/secure-run.sh --level=basic

# Active layers:
#   ✓ Layer 1: Permission blocklists (essential safety)
#   ✓ Layer 5: Monitoring (awareness)

# Disabled (to reduce overhead):
#   ✗ Layer 2: Command interception
#   ✗ Layer 3: Docker isolation
#   ✗ Layer 4: Validation hooks

# Still protected from:
#   - Accidental rm -rf
#   - sudo usage
#   - System shutdowns

# But with:
#   - Minimal performance impact
#   - Fast startup
#   - No Docker overhead
```

---

## Scenario 5: Custom Agent (Non-Claude)

**Goal**: Secure your own Python/Node agent

```bash
# Secure any command
~/tools/llmsec/secure-run.sh -- python my_agent.py --task "analyze code"

# Or with specific app name
~/tools/llmsec/secure-run.sh --app=custom -- node agent.js

# All security layers apply to your custom agent!
```

**Example custom agent**:

```python
# my_agent.py
import subprocess

def run_command(cmd):
    # This goes through secure-run's interceptor
    result = subprocess.run(cmd, shell=True, capture_output=True)
    return result.stdout

# Attempting: run_command("rm -rf /")
# Result: Blocked with helpful message
```

---

## Scenario 6: Per-Developer Defaults

**Goal**: Each developer has their own default security preferences

```bash
# Developer A: Paranoid
mkdir -p ~/.llmsec/defaults
cat > ~/.llmsec/defaults/permissions.yaml << 'YAML'
version: "1.0"
mode: "paranoid"

deny:
  - pattern: "*:production"
    message: "❌ No production access for me"
  - pattern: "curl:*"
    message: "❌ No external network calls"
YAML

# Developer B: Relaxed
cat > ~/.llmsec/defaults/permissions.yaml << 'YAML'
version: "1.0"
mode: "permissive"

ask:  # Ask instead of block
  - pattern: "*:production"
    message: "⚠️  Production operation - confirm"
YAML

# Both run same project, different rules apply!
```

---

## Scenario 7: Emergency Situation

**Goal**: Something going wrong, need to stop immediately

```bash
# Terminal 1: Agent is running
~/tools/llmsec/secure-run.sh
# ... agent doing work ...
# ... something suspicious ...

# Terminal 2: Emergency stop
~/tools/llmsec/tools/kill-claude.sh

# Output:
🛑 EMERGENCY STOP - Killing Claude Code and children...
✅ Done. Check with: ps aux | grep -E 'claude|node|npm|python'

# All processes terminated immediately
```

**Automatic monitoring detection**:

```bash
# Monitor sees dangerous pattern
# From ~/.llmsec/logs/claude-monitor.log:

[2026-02-08T10:30:00] [INFO] Monitor started
[2026-02-08T10:35:00] [WARN] SUSPICIOUS: PID 1234: rm -rf /
[2026-02-08T10:35:01] [INFO] KILLED: PID 1234 (dangerous pattern)

# Auto-kill feature (when enabled) stops dangerous processes
```

---

## Scenario 8: Code Review with Security Validation

**Goal**: Validate generated code before committing

```bash
cd ~/projects/my-app

# Run with validation enabled
~/tools/llmsec/secure-run.sh --level=maximum

# Agent writes code...
# User attempts git commit...

# Pre-commit hook runs:
Running security scan...
  semgrep: Scanning for dangerous operations...
  ✓ No issues found

  gitleaks: Scanning for secrets...
  ✗ Found potential secret in config.js:
    Line 10: api_key = "sk-1234..."

❌ Commit blocked. Please remove secrets.

# Commit prevented, secret not committed!
```

---

## Scenario 9: Monitoring and Logging

**Goal**: Track all agent activity for audit

```bash
# Run with monitoring
~/tools/llmsec/secure-run.sh

# In another terminal, watch logs
tail -f ~/.llmsec/logs/intercept.log

# Output shows all commands:
[2026-02-08T10:30:00] [ALLOWED] cat README.md | Reading files is safe
[2026-02-08T10:30:15] [BLOCKED] rm -rf /tmp | Recursive delete
[2026-02-08T10:30:30] [APPROVED_BY_USER] npm install express | User confirmed
[2026-02-08T10:31:00] [ALLOWED] git commit -m "Add feature" | Safe git operation
```

**Analysis**:

```bash
# Count blocks
grep BLOCKED ~/.llmsec/logs/intercept.log | wc -l

# Find most blocked commands
grep BLOCKED ~/.llmsec/logs/intercept.log | cut -d']' -f3 | sort | uniq -c | sort -rn

# Example output:
   5 rm -rf
   3 sudo apt
   2 chmod 777
```

---

## Scenario 10: Testing Configuration Changes

**Goal**: Test new security rules before applying

```bash
# Create test config
cat > .settings/permissions.yaml << 'YAML'
deny:
  - pattern: "deploy:*"
    message: "Test: Blocking all deploys"
YAML

# Test without running full agent
~/tools/llmsec/tools/interceptors/intercept-enhanced.py "deploy staging"

# Output:
==================================================================
❌ Test: Blocking all deploys
...
==================================================================

# Rule works! Now run full agent
~/tools/llmsec/secure-run.sh
```

---

## Summary Table

| Scenario | Command | Use Case |
|----------|---------|----------|
| 1. Quick Start | `./secure-run.sh` | First time, all defaults |
| 2. Project Rules | `./secure-run.sh` + `.settings/` | Custom per-project |
| 3. Paranoid | `--level=maximum --isolation=docker` | Untrusted code |
| 4. Trusted | `--level=basic` | Minimal overhead |
| 5. Custom Agent | `-- python my_agent.py` | Non-Claude agents |
| 6. Per-Developer | `~/.llmsec/defaults/` | Personal preferences |
| 7. Emergency | `tools/kill-claude.sh` | Stop immediately |
| 8. Validation | `--level=maximum` | Pre-commit checks |
| 9. Monitoring | Logs in `~/.llmsec/logs/` | Audit trail |
| 10. Testing | `intercept-enhanced.py` | Test rules |

---

**Next**: See [ORCHESTRATOR_GUIDE.md](docs/ORCHESTRATOR_GUIDE.md) for full reference
