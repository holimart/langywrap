# Architecture Overview

## System Design

The LLM Security Toolkit implements a **defense-in-depth** architecture with 5 independent but complementary security layers.

### Design Principles

1. **Defense in Depth**: Multiple overlapping security controls
2. **Fail Secure**: Default deny, explicit allow
3. **Least Privilege**: Minimum necessary permissions
4. **Separation of Concerns**: Each layer addresses specific threats
5. **Transparency**: All security decisions are logged

---

## Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ USER / AI AGENT                                              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ LAYER 1: INPUT FILTERING                                     │
│ ─────────────────────────────────────────────────────────────│
│ • Prompt injection detection                                 │
│ • Malicious input blocking                                   │
│ • Permission-based filtering (settings.json)                 │
│                                                              │
│ Tools: Claude permissions, input validators                  │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ LAYER 2: TOOL INTERCEPTION                                   │
│ ─────────────────────────────────────────────────────────────│
│ • Command pattern analysis (intercept.py)                    │
│ • Network egress control (agentsh)                           │
│ • PII detection                                              │
│ • User confirmation prompts                                  │
│                                                              │
│ Tools: intercept.py, agentsh, safe-bash.sh                   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ LAYER 3: EXECUTION ISOLATION                                 │
│ ─────────────────────────────────────────────────────────────│
│ • OS-level sandboxing (bubblewrap)                           │
│ • Container isolation (Docker)                               │
│ • Syscall interception (gVisor)                              │
│ • MicroVM isolation (Firecracker)                            │
│                                                              │
│ Tools: Docker, gVisor, Firecracker, bubblewrap               │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ LAYER 4: OUTPUT VALIDATION                                   │
│ ─────────────────────────────────────────────────────────────│
│ • Static code analysis (Semgrep)                             │
│ • Secret detection (Gitleaks)                                │
│ • Vulnerability scanning                                     │
│ • Pre-commit hooks                                           │
│                                                              │
│ Tools: Semgrep, Gitleaks, pre-commit hooks                   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ LAYER 5: MONITORING & RESPONSE                               │
│ ─────────────────────────────────────────────────────────────│
│ • Real-time process monitoring                               │
│ • Anomaly detection                                          │
│ • Emergency kill switch                                      │
│ • Audit logging                                              │
│                                                              │
│ Tools: claude-monitor.sh, kill-claude.sh, auditd             │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ HOST SYSTEM / RESOURCES                                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Threat Model

### Primary Threats

#### 1. System Harm
**Threat**: AI agent executes destructive commands
**Mitigated by**:
- Layer 1: Permission blocklists
- Layer 2: Command pattern detection
- Layer 3: Isolated execution environment
- Layer 5: Auto-kill on suspicious activity

**Examples**:
- `rm -rf /`
- `dd if=/dev/zero of=/dev/sda`
- `mkfs.ext4 /dev/sda`
- Fork bombs

#### 2. Data Exfiltration
**Threat**: AI agent leaks sensitive data to external services
**Mitigated by**:
- Layer 1: File read restrictions
- Layer 2: Network egress control, PII detection
- Layer 3: Credential isolation, network restrictions
- Layer 4: Secret scanning
- Layer 5: Network monitoring

**Examples**:
- Reading `~/.ssh/id_rsa` and uploading to pastebin
- Encoding secrets and DNS tunneling
- Copying `.env` files to external services

#### 3. Privilege Escalation
**Threat**: AI agent gains elevated privileges
**Mitigated by**:
- Layer 1: Block sudo/su commands
- Layer 3: Non-root container users
- Layer 5: Process monitoring

**Examples**:
- `sudo rm -rf /`
- Exploiting SUID binaries
- Container escape attempts

#### 4. Resource Exhaustion
**Threat**: AI agent consumes excessive resources
**Mitigated by**:
- Layer 1: Resource limits (ulimit)
- Layer 3: Container resource constraints
- Layer 5: Resource monitoring

**Examples**:
- Fork bombs: `:(){ :|:& };:`
- Infinite loops
- Large file creation

#### 5. Prompt Injection
**Threat**: Malicious instructions embedded in data
**Mitigated by**:
- Layer 1: Input filtering
- Layer 2: Command validation
- Layer 4: Output scanning

**Examples**:
- Hidden instructions in files
- Malicious package.json scripts
- Trojan source code

---

## Component Architecture

### Configuration Layer

```
configs/
├── claude/
│   └── settings.json          # Permission rules
├── docker/
│   ├── Dockerfile.sandbox     # Container definition
│   └── run-sandbox.sh         # Container launcher
├── semgrep/
│   └── dangerous-operations.yaml  # Code scan rules
└── policies/
    └── agentsh-policy.yaml    # Network policies
```

### Execution Layer

```
tools/
├── interceptors/
│   └── intercept.py           # Command interceptor
├── monitors/
│   └── claude-monitor.sh      # Process monitor
└── validators/
    └── [future validators]
```

### Installation Layer

```
scripts/
├── phase1/
│   └── setup.sh               # Quick wins installer
├── phase2/
│   └── [tool interception setup]
├── phase3/
│   └── [isolation setup]
├── phase4/
│   └── [validation setup]
└── phase5/
    └── [monitoring setup]
```

---

## Data Flow

### Normal Operation

```
User Input → Layer 1 Filter → Layer 2 Intercept → Layer 3 Execute
                                                        ↓
                                                  Layer 4 Validate
                                                        ↓
                                                  Layer 5 Monitor → Output
```

### Blocked Command

```
User Input → Layer 1 Filter → ❌ BLOCKED
                                   ↓
                               Log & Alert
```

```
User Input → Layer 1 Filter → Layer 2 Intercept → ❌ BLOCKED
                                                      ↓
                                                  Log & Alert
```

### Data Exfiltration Attempt

```
User Input → Layers 1-2 Pass → Layer 3 Execute → Network Call
                                                        ↓
                                                Layer 2 Network Policy → ❌ BLOCKED
                                                        ↓
                                                    Log & Alert
```

---

## Security Guarantees

### What We Prevent

✅ **Guaranteed Prevention** (with all layers enabled):
- Accidental destructive commands
- Common data exfiltration techniques
- Resource exhaustion
- Basic privilege escalation
- Known malware patterns

⚠️ **Best Effort** (defense in depth):
- Sophisticated prompt injection
- Zero-day exploits
- Advanced obfuscation techniques
- Social engineering

❌ **Not Protected** (out of scope):
- Physical access attacks
- Supply chain compromises (malicious dependencies)
- Vulnerabilities in the LLM itself
- User explicitly bypassing protections

### Performance Impact

| Layer | Overhead | Latency |
|-------|----------|---------|
| 1 - Input Filter | <1% | <1ms |
| 2 - Interception | ~1% | ~5ms |
| 3 - Container | ~2-5% | ~50ms startup |
| 3 - gVisor | ~5-10% | ~100ms startup |
| 3 - Firecracker | ~10-15% | ~200ms startup |
| 4 - Validation | Varies | Async (pre-commit) |
| 5 - Monitoring | ~1% | <1ms |

**Overall**: ~10-20% overhead with all layers (gVisor)

---

## Deployment Models

### 1. Development (Basic)
- Layer 1: Input filtering
- Layer 2: Command interception
- Layer 5: Basic monitoring

**Use case**: Local development, trusted environments
**Setup time**: 30 minutes

### 2. Production (Recommended)
- Layer 1: Input filtering
- Layer 2: Full interception + network control
- Layer 3: Docker containers
- Layer 4: Pre-commit hooks + CI/CD
- Layer 5: Full monitoring

**Use case**: Production deployments, untrusted code
**Setup time**: 2-3 hours

### 3. Maximum Security
- All layers with gVisor/Firecracker
- Optional: Data theft prevention
- Optional: File access auditing

**Use case**: Multi-tenant, high-security environments
**Setup time**: 4-8 hours

---

## Extensibility

### Adding Custom Rules

**Command Patterns** (Layer 2):
```python
# In tools/interceptors/intercept.py
BLOCKED_COMMANDS['your-cmd'] = ['dangerous-arg']
```

**Semgrep Rules** (Layer 4):
```yaml
# In configs/semgrep/
rules:
  - id: your-custom-rule
    pattern: dangerous_function(...)
    message: "Description"
    severity: ERROR
```

**Network Policies** (Layer 2):
```yaml
# In configs/policies/agentsh-policy.yaml
network_rules:
  - name: block-your-domain
    destinations: ["malicious.com"]
    decision: deny
```

### Plugin Architecture (Future)

```
plugins/
├── input-filters/
├── command-interceptors/
├── validators/
└── monitors/
```

---

## Logging & Auditing

### Log Locations

| Component | Log File |
|-----------|----------|
| Command Intercept | `~/.claude-intercept.log` |
| Process Monitor | `~/.claude-monitor.log` |
| Network Monitor | `~/.claude-network.log` |
| DNS Monitor | `~/.dns-monitor.log` |
| System Audit | `/var/log/audit/audit.log` |

### Log Format

```
TIMESTAMP [STATUS] COMMAND
2026-02-08T10:30:00 [BLOCKED-HARM] rm -rf /
2026-02-08T10:30:15 [EXECUTED] ls -la
2026-02-08T10:30:30 [CANCELLED] pip install malicious-pkg
```

### Audit Events

- All blocked commands
- All executed commands
- Permission changes
- Configuration changes
- Monitoring alerts

---

## Future Enhancements

### Planned Features

1. **ML-based Anomaly Detection**: Detect unusual patterns
2. **Distributed Monitoring**: Multi-host coordination
3. **Cloud Integration**: AWS/GCP/Azure native support
4. **Compliance Reporting**: SOC2, HIPAA audit trails
5. **Web Dashboard**: Real-time monitoring UI
6. **Policy as Code**: Version-controlled security policies

### Research Areas

- LLM-specific prompt injection defenses
- Behavioral analysis for agent actions
- Automated policy generation
- Integration with SIEM systems
- Hardware security (TPM, secure enclaves)

---

## References

See [docs/AI_AGENT_SECURITY_RESEARCH.md](AI_AGENT_SECURITY_RESEARCH.md) for detailed research and sources.
