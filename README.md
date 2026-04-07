# langywrap

Universal AI agent orchestration toolkit. Execution security, ralph loops,
hyperagent evolution, compound engineering, project scaffolding.

## Quick Start

```bash
# Install (interactive wizard)
./install.sh

# Couple a downstream project
./just couple /path/to/my-project

# Create a new project from template
langywrap scaffold new /path/to/parent my-project
```

## Installation

### Interactive Wizard (recommended)

```bash
./install.sh
```

The wizard walks you through each feature:

| Feature | Default | What it does |
|---------|---------|-------------|
| Python package | Yes | Installs `langywrap` via `uv` in editable mode |
| RTK compression | Yes | Builds RTK from source (`cargo build --release`) for 60-90% token savings |
| Global config | Yes | Manages `~/.claude/` hooks, settings, skills via symlinks |
| ExecWrap | Yes | 5-layer execution wrapper for AI tools |
| Security hooks | Yes | Per-tool command blocking (Claude, OpenCode, Cursor, Cline) |
| Git hooks | Yes | Pre-commit Python scan + force-push protection |
| Skills | Yes | Claude Code slash commands (`/ralph-loop`, `/compound`, etc.) |
| HyperAgents | Yes | Agent evolution framework + experiment archive |
| Compound eng. | Yes | Cross-project lessons learned hub |

### Non-interactive

```bash
./install.sh --defaults    # Accept all defaults
./install.sh --dry-run     # Preview without changes
```

### Rerunning

Run `./install.sh` again anytime to change your setup. Previous choices are
remembered and shown as defaults.

### Prerequisites

| Tool | Required | Purpose |
|------|----------|---------|
| Python >= 3.10 | Yes | Library runtime |
| git | Yes | Version control |
| uv | Recommended | Package management (pip fallback) |
| cargo (Rust) | For RTK | Builds RTK output compressor |
| just | Recommended | Task runner |
| jq | For config merge | Merges settings.json |

## Running AI Tools

After installation, run Claude Code or OpenCode through the security wrapper:

```bash
# With ExecWrap (full 5-layer security)
/path/to/langywrap/execwrap/execwrap.bash claude
/path/to/langywrap/execwrap/execwrap.bash opencode

# Tip: add aliases to your shell rc
alias cw='/path/to/langywrap/execwrap/execwrap.bash claude'
alias ow='/path/to/langywrap/execwrap/execwrap.bash opencode'
```

In a coupled project with ExecWrap installed:
```bash
.exec/execwrap.bash claude
.exec/execwrap.bash opencode
```

Without ExecWrap, global hooks still provide security through `~/.claude/hooks/`.

## Coupling a Project

```bash
./just couple /path/to/project          # Interactive wizard
./just couple /path/to/project --full   # All features
./just couple /path/to/project --minimal # Security only
./just couple /path/to/project --dry-run # Preview
```

Coupling installs per-project:

| Feature | What gets installed |
|---------|-------------------|
| Security hooks | `.claude/hooks/`, `.opencode/plugins/`, `.cursor/hooks/` |
| ExecWrap | `.exec/execwrap.bash` + settings + preload |
| Git hooks | `.githooks/pre-commit` + `pre-push` |
| Ralph loop | `research/ralph/` state dir + prompt templates |
| HyperAgents | `.langywrap/router.yaml` (model routing config) |
| Compound eng. | `docs/solutions/` + `_template.md` |
| Quality gates | Compact output config check |
| Wrappers | `./just` + `./uv` (pager prevention) |
| Dev dependency | `langywrap` as editable uv dev dep |

### Coupling config

After coupling, the project has `.langywrap/` with:

```
.langywrap/
  config.yaml       # Project name, langywrap path, archive pointers
  router.yaml       # ExecutionRouter model routing (HyperAgent-evolvable)
  ralph.yaml         # Ralph loop settings (budget, gates, git paths)
```

## Components

### ExecutionRouter

Routes workflow steps to AI backends with retry, fallback, and evolution.

```
lib/langywrap/router/
  backends.py    — ClaudeBackend, OpenCodeBackend, OpenRouterBackend, DirectAPIBackend, MockBackend
  config.py      — RouteConfig, RouteRule, StepRole, ModelTier
  router.py      — ExecutionRouter (dispatch, retry, stats, dry-run)
  evolution.py   — RouteEvolver (HyperAgent-driven config mutation)
```

Per-project config in `.langywrap/router.yaml`. Default routing:

| Role | Model | Backend |
|------|-------|---------|
| orient | claude-haiku-4-5 | claude |
| plan | claude-sonnet-4-6 | claude |
| execute | kimi-k2.5 | opencode (free) |
| critic | claude-haiku-4-5 | claude |
| finalize | kimi-k2.5 | opencode (free) |
| review (every 10th) | claude-opus-4-6 | claude |

### Ralph Loop

Hybrid Python orchestrator for autonomous AI research/engineering cycles.
5-step pipeline: orient -> plan -> execute -> critic -> finalize.

```
lib/langywrap/ralph/
  config.py    — RalphConfig, StepConfig, QualityGateConfig
  state.py     — RalphState (tasks.md, progress.md, orient context compression)
  runner.py    — RalphLoop (the main loop with quality gates + git commit)
  context.py   — Template substitution, scope restriction injection
  prompts/     — Default step prompt templates
```

Key feature: **Orient context pre-digestion** — compresses large state files
(tasks.md, progress.md) by ~11x before feeding to the orient model.

### HyperAgents + Memento Skills

Agent evolution framework. Every coupled repo participates via ralph loops.

```
lib/langywrap/hyperagents/
  archive.py     — AgentVariant, Archive (growing population of configs)
  mutations.py   — Random + meta-mutations (LLM-guided optimization)
  engine.py      — HyperAgentEngine (evolve, record, exploit/explore)
  skills.py      — SkillLibrary (Memento pattern: utility-scored skills)
experiments/
  archive/       — Variant YAML files (git-versioned, nothing lost)
  meta/          — meta_agent.py (standalone evolution script)
```

### Security

Merged permissions from execsec. System denials NEVER overridable by project.

```
lib/langywrap/security/
  permissions.py   — Load + merge YAML configs (KEY FIX: deny-at-any-level wins)
  engine.py        — SecurityEngine (check, check_and_exec)
  audit.py         — JSON-lines audit logging
  defaults/        — Bundled permissions.yaml + resources.yaml
  interceptors/    — intercept-enhanced.py (57-rule YAML interceptor)
```

### MockBackend (Testing)

Bash-based mock LLM for integration testing. Verifies that commands routed
through ExecutionRouter are subject to SecurityEngine checks.

```python
from langywrap.router import Backend, BackendConfig, MockBackend

config = BackendConfig(type=Backend.MOCK, env_overrides={"MOCK_RESPONSE": "test"})
backend = MockBackend(config)
result = backend.run("prompt", "mock-v1", timeout=10)
# Also: run_with_security_check("rm -rf /", security_engine=engine)
```

## Development

```bash
./just sync       # Install dependencies
./just check      # Lint + typecheck + test
./just dev        # Fix + check (full cycle)
./just test       # pytest
./just lint       # ruff check -q
./just typecheck  # mypy
```

## Project Structure

```
langywrap/
  lib/langywrap/       Python library (pip-installable)
    security/           Execution security (permissions, audit, interceptors)
    router/             ExecutionRouter (model/backend routing, retry, evolution)
    ralph/              Ralph loop orchestration (hybrid Python/bash)
    hyperagents/        HyperAgent evolution + Memento Skills
    quality/            Quality gates (ruff, mypy, pytest, lean)
    compound/           Compound engineering (lessons learned flow)
    template/           Project scaffolding
    helpers/            Categorized helper scripts (python, bash, lean, data)
  hooks/                Per-tool security hooks
  execwrap/             Universal 5-layer execution wrapper
  harden/               Repo hardening installer
  rtk/                  Output compression (git submodule, build from source)
  experiments/          HyperAgent archive + evolution configs
  skills/               Claude Code slash commands
  agents/               Sub-agent definitions
  configs/              Global config templates, semgrep, docker
  docs/solutions/       Compound engineering hub
  scripts/              Install, coupling, utility scripts
  tests/                58 tests (security, ralph, router, scaffold, evolution)
  spec/                 Design specs from initial creation
```

## License

MIT
