# langywrap — Architecture Synthesis

## What langywrap is

A **monorepo toolkit** that downstream AI-assisted projects install (pip/uv, edit mode, or symlink) to get:
- Execution security (wrapping, hooking, auditing)
- Output compression (RTK integration)
- Ralph loop orchestration (declarative, multi-model)
- Quality gates (ruff, mypy, pytest helpers)
- Lean theorem prover helpers
- Compound engineering (lessons learned flow)
- Project scaffolding (templates)
- HyperAgent experimentation framework
- Global config management (CLAUDE.md, settings.json, hooks)

## Proposed Directory Structure

```
langywrap/
├── README.md
├── pyproject.toml                   # pip-installable library
├── justfile                         # Developer tasks
├── CLAUDE.md                        # Meta: instructions for working ON langywrap
│
├── lib/                             # Python library (pip-installable)
│   └── langywrap/
│       ├── __init__.py
│       ├── security/                # execsec functionality as library
│       │   ├── interceptor.py       # intercept-enhanced.py refactored
│       │   ├── permissions.py       # YAML config loader + merger (FIX: merge not first-found)
│       │   ├── audit.py             # Unified audit logging
│       │   └── defaults/
│       │       ├── permissions.yaml
│       │       └── resources.yaml
│       ├── ralph/                   # Ralph loop library
│       │   ├── runner.py            # Core loop (bash→python port or bash caller)
│       │   ├── subagent.py          # run_subagent() with retry/fallback/hang detection
│       │   ├── context.py           # orient context pre-digestion
│       │   ├── quality_gate.py      # Pluggable gate interface
│       │   └── prompts/             # Default prompt templates (overridable)
│       ├── quality/                 # Quality gate helpers
│       │   ├── ruff.py
│       │   ├── mypy.py
│       │   ├── pytest_runner.py
│       │   └── lean.py              # lean-check.sh as python wrapper
│       ├── compound/                # Compound engineering helpers
│       │   ├── solutions.py         # docs/solutions/ CRUD
│       │   ├── memory.py            # .claude/memory/ management
│       │   └── propagate.py         # Push lessons upstream to langywrap
│       └── template/                # Project scaffolding
│           ├── scaffold.py          # Create new project from template
│           └── templates/           # Template files
│
├── hooks/                           # Shell hooks (installed into downstream repos)
│   ├── claude/
│   │   ├── security_hook.sh         # Template with __PROJECT_NAME__
│   │   ├── agent_research_opencode.sh
│   │   └── websearch_kimi.sh
│   ├── opencode/
│   │   └── security-guard.ts
│   ├── cursor/
│   │   └── guard.sh
│   ├── cline/
│   │   └── PreToolUse
│   ├── githooks/
│   │   ├── pre-commit
│   │   └── pre-push
│   └── shell-wrapper/
│       └── guard.sh                 # SHELL= replacement template
│
├── execwrap/                        # Universal execution wrapper
│   ├── execwrap.bash
│   ├── preload.sh
│   ├── settings.json                # Default settings template
│   ├── test.sh
│   └── README.md
│
├── rtk/                             # RTK output compression (vendored binary or submodule?)
│   └── ... (TBD — see DECISION-01)
│
├── harden/                          # Hardening installer
│   ├── harden.sh                    # Universal repo hardening
│   └── install.sh                   # System-wide langywrap install
│
├── experiments/                     # HyperAgent experiments (the evolving archive)
│   ├── archive/                     # Agent variant archive (HyperAgents pattern)
│   │   └── ...
│   ├── configs/                     # Agent configuration variants
│   │   ├── token-optimized/
│   │   ├── speed-optimized/
│   │   ├── intelligence-optimized/
│   │   └── task-specialized/
│   └── meta/                        # Meta-agent that evolves agent configs
│       └── meta_agent.py
│
├── skills/                          # Claude Code skills (symlinked globally)
│   ├── ralph-loop.md
│   ├── compound.md
│   ├── compound-engineering.md
│   ├── harden-wizard.md
│   ├── execwrap-setup.md
│   ├── validate-fix.md
│   ├── spec-driven.md
│   └── install-websearch-hook.md
│
├── agents/                          # Sub-agent definitions (Memento pattern)
│   ├── security-reviewer.md
│   ├── architecture-reviewer.md
│   ├── research-agent.md            # Uses cheap models (kimi, minimax)
│   ├── critic-agent.md              # Adversarial reviewer
│   └── meta/                        # Agent-designing-agents (Memento Skills)
│       ├── skill_library.json       # Utility-scored skill catalog
│       └── reflect_write.py         # Post-task skill creation/refinement
│
├── configs/                         # Global config templates
│   ├── claude.md.template           # Global CLAUDE.md template
│   ├── settings.json.template       # Global settings.json template
│   ├── semgrep/
│   │   └── dangerous-operations.yaml
│   └── docker/
│       ├── Dockerfile.sandbox
│       └── run-sandbox.sh
│
├── docs/                            # Documentation
│   ├── architecture.md
│   ├── quickstart.md
│   └── solutions/                   # Cross-project compound engineering hub
│       └── _template.md
│
└── tests/                           # Test suite
    ├── test_security/
    ├── test_ralph/
    ├── test_execwrap/
    ├── test_harden/
    ├── test_hooks/
    └── test_scaffold/
```

## Key Design Decisions Needed

### DECISION-01: RTK Integration Method
**Options:**
A) Git submodule — tracks upstream, but submodule friction
B) Vendor binary — download platform binary at install time (like `./just install-rtk`)
C) Cargo dependency — requires Rust toolchain
D) Optional integration — detect if `rtk` is on PATH, use if available

**Recommendation:** B (vendor binary) with D (optional fallback). RTK is Apache 2.0, single binary, no Rust needed at runtime. `just install-rtk` downloads to `.exec/rtk`.

### DECISION-02: execsec — Copy vs Fork vs Submodule
**Options:**
A) Full copy (forget execsec exists) — user's stated preference
B) Fork on GitHub — maintain independently but track ancestry
C) Keep as submodule — contradicts user's request

**Recommendation:** A (full copy), refactored into `lib/langywrap/security/` (Python parts) and `hooks/` + `harden/` (shell parts). The merge-configs TODO gets fixed properly.

### DECISION-03: Ralph Loop — Bash or Python?
Current: 800-1200 LOC bash scripts (llmtemplate + riemann2 + crunchdao variants)
**Options:**
A) Keep bash — battle-tested, 675+ cycles proven
B) Port to Python — cleaner, testable, pip-installable
C) Hybrid — Python orchestrator calling bash for shell-specific tasks

**Recommendation:** C (hybrid). The subagent invocation, retry logic, and state management port to Python. Shell wrapping stays bash.

### DECISION-04: Downstream Coupling Method
How does a downstream project (e.g., riemann2) consume langywrap?
**Options:**
A) pip install langywrap (or uv add langywrap) — proper Python package
B) Git submodule — heavy coupling, submodule friction
C) Symlinks — `~/.local/lib/langywrap` symlinked into projects
D) pip install -e /path/to/langywrap — editable install, changes propagate immediately
E) Hybrid: pip install for library, symlinks for skills/hooks/configs

**Recommendation:** E. Library functions via `pip install -e`. Skills via symlink `~/.claude/commands/ → langywrap/skills/`. Hooks via `langywrap harden` installer. Config templates via `langywrap scaffold`.

### DECISION-05: HyperAgent Experiment Storage
Where do evolved agent configurations live?
**Options:**
A) All in langywrap/experiments/ — central archive
B) Per-project experiments, results flow back to langywrap
C) Separate experiments repo

**Recommendation:** A per user's request ("store experiments here, not in downstream repos").

### DECISION-06: Compound Engineering Hub
How do downstream projects push lessons back?
**Options:**
A) Git operations (PR to langywrap)
B) Shared filesystem (symlinked docs/solutions/)
C) CLI command: `langywrap compound push "lesson.md"` copies to langywrap/docs/solutions/
D) Automatic via finalize step in ralph loop

**Recommendation:** C+D. Manual push via CLI, automatic via ralph loop finalize step.

### DECISION-07: Global Config Management
How to handle ~/.claude/CLAUDE.md, ~/.claude/settings.json, ~/.claude/hooks/?
**Options:**
A) langywrap owns them — `langywrap install` writes/symlinks global configs
B) langywrap provides templates — user manages manually
C) Merge strategy — langywrap adds its entries without clobbering user additions

**Recommendation:** A with C fallback. `langywrap install --global` symlinks hooks, merges settings.json (additive), generates CLAUDE.md from template + user customizations.

### DECISION-08: Skill/Agent Evolution (Memento + HyperAgents)
How do skills evolve?
**Options:**
A) Manual — humans edit skill files
B) Semi-auto — after each ralph cycle, reflect step proposes skill updates
C) Full HyperAgents — meta-agent rewrites skills, archive tracks variants, selection by utility score

**Recommendation:** Start A+B, design for C. The experiments/ directory and agents/meta/ exist from day 1 but initially empty. The reflect_write.py stub exists. Full HyperAgents loop is a later milestone.

### DECISION-09: Permissions Merge (System vs Repo)
Current execsec bug: first-found wins, no merge. System rules can be overridden by repo.
**Fix options:**
A) Merge all levels, deny-at-any-level wins (most secure)
B) Merge all levels, most-specific wins (most flexible)
C) System deny always wins, repo can add but not remove (user's stated preference)

**Recommendation:** C — matches user's description "per repo is never able to override systemwide denials."

### DECISION-10: Lean Helpers Scope
Include lean-check.sh and Lean helpers?
**Options:**
A) Include — it's proven in riemann2 (675 cycles)
B) Exclude — too niche for a general toolkit
C) Optional subpackage — `pip install langywrap[lean]`

**Recommendation:** C. lean-check.sh goes to `lib/langywrap/quality/lean.py` but is an optional extra.

## Cross-Cutting Concerns

### Model Routing Architecture
All three ralph loops implement the same pattern: cheap models (kimi-k2.5, minimax) for execution, mid-range (haiku, sonnet) for planning, expensive (opus, gpt-5.2) for review. This should be a first-class abstraction:

```python
class ModelRouter:
    roles = {
        "orient": "cheap",      # haiku / kimi
        "plan": "mid",          # sonnet / haiku
        "execute": "cheap",     # kimi / minimax (free tier)
        "critic": "expensive",  # opus / gpt-5.2
        "finalize": "cheap",    # kimi
        "review": "expensive",  # opus (every Nth cycle)
    }
```

Downstream overrides per-role. HyperAgents evolve the routing table.

### Three-Layer Config Isolation (from Memento)
1. **System** (`~/.langywrap/`) — global rules, never overridable denials
2. **Project** (`.langywrap/` in repo) — project-specific additions
3. **Session** (environment vars, CLI flags) — ephemeral overrides

### Token Cost Awareness
Every component should be budget-aware:
- RTK for output compression
- Orient context pre-digestion for input compression
- Model routing for cost/quality tradeoff
- Budget parameter on ralph loops
- Peak-hour throttling
