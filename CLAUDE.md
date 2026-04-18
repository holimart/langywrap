# langywrap — Universal AI Agent Orchestration Toolkit

## What This Repo Is

langywrap is the master repository for all AI agent tooling, security wrappers,
ralph loop orchestration, hyperagent evolution, compound engineering, and project
scaffolding. Downstream repos (riemann2, compricing, crunchdaoobesity, etc.) are
coupled to this repo and consume its libraries, hooks, and skills.

## Key Directories

- `lib/langywrap/` — Python library (pip-installable)
- `hooks/` — Shell hooks for claude/opencode/cursor/cline/git
- `execwrap/` — Universal execution wrapper (5-layer security)
- `harden/` — Repo hardening installer
- `rtk/` — RTK output compression (git submodule, build from source)
- `openwolf/` — OpenWolf token-conscious AI brain (git submodule, build from source)
- `textify/` — LLM-free doc extraction (git submodule, opt-in via `knowledge-graph` extra)
- `graphify/` — Code-graph skill via tree-sitter + Leiden (git submodule, opt-in via `knowledge-graph` extra)
- `skills/` — Claude Code slash commands (symlinked globally)
- `agents/` — Sub-agent definitions (Memento pattern)
- `experiments/` — HyperAgent evolution archive and configs
- `docs/solutions/` — Compound engineering hub (cross-project lessons)
- `configs/` — Global config templates, semgrep rules, docker configs
- `scripts/` — Install, coupling, and utility scripts
- `spec/` — Design specs and analysis from initial creation

## Development Commands

```
./just sync          # uv sync dependencies
./just check         # lint + typecheck + test
./just dev           # fix + check (full local cycle)
./just install            # System-wide install (builds RTK, OpenWolf, textify, graphify, installs package)
./just install-rtk        # Build RTK from source only
./just install-openwolf   # Build OpenWolf from source only
./just install-textify    # Install textify submodule (editable) via knowledge-graph extra
./just install-graphify   # Install graphify submodule (editable) via knowledge-graph extra
./just couple PATH   # Couple a downstream repo
```

## Architecture

### ExecutionRouter
Routes workflow steps to backends (claude CLI, opencode, openrouter, direct API).
Per-role model selection. Retry with fallback. HyperAgent-evolvable routing tables.
Config: `.langywrap/router.yaml` per coupled repo.

### Ralph Loop (Hybrid)
Python orchestrator (`lib/langywrap/ralph/`) calling subagents via ExecutionRouter.
5-step pipeline: orient -> plan -> execute -> critic -> finalize.
Declarative config: `.langywrap/ralph.py` (pydantic Pipeline) per coupled repo.
Optional per-step enrichment: `Step(..., enrich=["graphify"])` injects a fresh
code-graph summary into the prompt. Cycle-end rebuild: `post_cycle_commands`
runs after gates, before commit. Runner warns about stale graphs and
missing textify preprocessing (see `ralph/context.py:check_graphify_health`).

### HyperAgents
Evolution archive in `experiments/archive/`. Mutations + meta-mutations.
Every coupled repo participates by running ralph loops that feed metrics back.
Parent selection by fitness + novelty. Cheap eval, expensive modification.

### Memento Skills
Skills in `agents/meta/` + SkillLibrary catalog. Utility-scored. Reflect-write
loop after each task creates/updates skills automatically. All versions in git.

### Security (from execsec)
Merged permissions: system denials NEVER overridable by project config.
5-layer defense: JSON rules -> guard.sh -> intercept-enhanced.py -> tool hooks -> git hooks.

## Important Conventions

- Use `./just` and `./uv` wrappers (pipe through cat, prevent pager issues)
- All quality tools configured for compact output: pytest -q --tb=short, ruff -q, mypy pretty=false
- No hardcoded absolute paths: use `Path(__file__).parent`, `${BASH_SOURCE[0]}`
- `__EXECWRAP_ACTIVE=1` env var prevents recursive guard invocation
