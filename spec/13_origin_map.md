# Origin Map — Where Everything Came From

Maps every langywrap component to its source repo and any transformations applied.

## From llmtemplate

| langywrap path | llmtemplate source | Notes |
|---|---|---|
| `hooks/claude/security_hook.sh` | `.claude/hooks/security_hook.sh` | Direct copy |
| `hooks/claude/agent_research_opencode.sh` | `.claude/hooks/agent_research_opencode.sh` | Direct copy |
| `hooks/claude/websearch_kimi.sh` | `.claude/hooks/websearch_kimi.sh` | Direct copy |
| `hooks/opencode/security-guard.ts` | `.opencode/plugins/security-guard.ts` | Direct copy |
| `hooks/cursor/*` | `.cursor/hooks/*` | Direct copy |
| `hooks/cline/PreToolUse` | `.clinerules/hooks/PreToolUse` | Direct copy |
| `hooks/githooks/*` | `.githooks/*` | Direct copy |
| `hooks/shell-wrapper/*` | `.llmsec/*` | Direct copy |
| `execwrap/*` | `.exec/*` | Direct copy |
| `scripts/ralph_loop.sh` | `scripts/ralph_loop.sh` | Direct copy (reference, superseded by Python module) |
| `skills/*.md` | `.claude/commands/*.md` | Direct copy |
| `configs/claude-settings*.json` | `.claude/settings*.json` | Direct copy |
| `configs/code-quality.md` | `.claude/code-quality.md` | Direct copy |
| `configs/.pre-commit-config.yaml` | `.pre-commit-config.yaml` | Direct copy |
| `lib/langywrap/template/templates/*` | Root template files | Renamed with .template suffix |
| `lib/langywrap/helpers/bash/just-wrapper` | `./just` | Renamed |
| `lib/langywrap/helpers/bash/uv-wrapper` | `./uv` | Renamed |
| `lib/langywrap/ralph/prompts/*` | `ralph/prompts/*` | Direct copy |
| `notes/todos.txt` | `notes/todos.txt` | Direct copy |

## From execsec (full copy)

| langywrap path | execsec source | Notes |
|---|---|---|
| `execsec_original/` | Entire submodule | Full copy for reference |
| `lib/langywrap/security/interceptors/*` | `tools/interceptors/*` | Direct copy |
| `lib/langywrap/security/defaults/*` | `configs/defaults/*` | Direct copy |
| `lib/langywrap/security/monitors/*` | `tools/monitors/*` | Direct copy |
| `harden/harden.sh` | `tools/harden/harden.sh` | Direct copy |
| `harden/secure-run.sh` | `secure-run.sh` | Direct copy |
| `configs/semgrep/*` | `configs/semgrep/*` | Direct copy |
| `configs/docker/*` | `configs/docker/*` | Direct copy |
| `tests/test_security/*` | `tests/*` | Direct copy |
| `docs/ARCHITECTURE.md` etc. | `docs/*` | Direct copy |

## New in langywrap (not from any source)

| Path | Description |
|---|---|
| `lib/langywrap/security/{__init__,permissions,engine,audit}.py` | Refactored Python security library (fixes merge bug) |
| `lib/langywrap/router/` | ExecutionRouter (new, patterns extracted from 3 ralph loops) |
| `lib/langywrap/ralph/{config,state,runner,context}.py` | Python ralph orchestrator (new, patterns from bash versions) |
| `lib/langywrap/hyperagents/` | HyperAgents + Memento framework (new, from papers) |
| `lib/langywrap/quality/gates.py` | Pluggable quality gate runner (new) |
| `lib/langywrap/quality/lean.py` | Lean helpers (new, patterns from riemann2) |
| `lib/langywrap/compound/` | Compound engineering module (new) |
| `lib/langywrap/template/scaffold.py` | Project scaffolding (new) |
| `lib/langywrap/helpers/python/*.py` | Helper utilities (new) |
| `experiments/meta/meta_agent.py` | Standalone evolution script (new) |
| `install.sh` | Interactive install wizard (new, replaces old basic version) |
| `scripts/couple.sh` | Interactive coupling wizard (new, replaces old basic version) |
| All `tests/test_*/*.py` | Python test suite (new, 58 tests) |

## From riemann2 (patterns, not code)

Not directly copied, but these patterns informed the design:
- 5-step cycle (orient/plan/execute/critic/finalize)
- Multi-model routing (haiku orient, opus plan, kimi execute, gpt-5.2 critic)
- Lean retry loop pattern → `lib/langywrap/quality/lean.py`
- Adversarial cycle every N → `adversarial_every_n` in RalphConfig
- Stagnation detection (4-cycle same-type trigger)
- Peak-hour throttling
- `__EXECWRAP_ACTIVE=1` convention

## From crunchdaoobesity (patterns, not code)

- Orient context pre-digestion (~11x compression) → `state.py:build_orient_context()`
- 4-step multi-model architecture (Claude plans, Kimi executes)
- Safe git commit with secret scanning → `runner.py:safe_git_commit()`
- Scope restriction headers → `context.py:inject_scope_restriction()`
- 70+ docs/solutions/ entries demonstrated compound engineering at scale
- Quality gate as `./just check` pattern
- `MOCK_COMMAND` / `MOCK_RESPONSE` env var pattern for testing

## Papers that informed design

| Paper | What it informed |
|---|---|
| HyperAgents (arxiv 2603.19461) | `hyperagents/archive.py`, `mutations.py`, `engine.py` — archive, fitness+novelty selection, meta-mutations |
| Memento Skills (arxiv 2603.18743) | `hyperagents/skills.py` — SkillLibrary, utility scores, reflect_and_write loop |
| Compound Engineering (Every Inc) | `compound/` module, `docs/solutions/` pattern, hub-and-spoke knowledge flow |
