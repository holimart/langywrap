---
description: Migrate a downstream repo from standalone bash ralph loops + execsec to langywrap library
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, AskUserQuestion
---

# Migrate Downstream Repo to langywrap

Transforms a downstream project's standalone bash ralph loops and execsec setup
to use langywrap as a live editable library. Tested pattern from crunchdaoobesity
(861-line bash → 54-line wrapper + YAML config).

**Goal**: downstream repos own the **domain** (prompts, tasks, competition/research knowledge).
langywrap owns the **plumbing** (routing, retries, state compression, security, git commits).

**Argument parsing:** `$ARGUMENTS`
- No args → full migration of current directory
- `<path>` → migrate the repo at that path
- `--dry-run` → analyze only, don't write files
- `--discover` → only run feature discovery (phase 2)

---

## Phase 0: Prerequisites Check

Run these checks. Stop and report if any fail.

```bash
# 1. langywrap importable?
python -c "import langywrap; print('langywrap:', langywrap.__file__)"

# 2. Is it editable (live-linked)?
python -c "
from pathlib import Path; import langywrap
di = list(Path(langywrap.__file__).parent.parent.glob('langywrap-*.dist-info'))
if di:
    du = di[0] / 'direct_url.json'
    if du.exists():
        import json; d = json.loads(du.read_text())
        print('editable:', d.get('dir_info', {}).get('editable', False))
        print('url:', d.get('url', '?'))
"

# 3. Does it have a ralph loop script?
ls -la ralph_loop.sh ralph_research.sh ralph_expansion.sh 2>/dev/null

# 4. Does it have execsec?
ls -la .exec/ .llmsec/ .claude/hooks/security_hook.sh 2>/dev/null
```

If langywrap is not editable, fix pyproject.toml:
```toml
[tool.uv.sources]
langywrap = { path = "/mnt/work4t/Projects/langywrap", editable = true }
```
Then `uv sync`.

If no .langywrap/ dir exists, run coupling first:
```bash
/mnt/work4t/Projects/langywrap/scripts/couple.sh <project-path> --defaults
```

---

## Phase 1: Analyze Old Bash Ralph Loop

Read the entire bash ralph loop script. Extract these values into a structured summary:

| Config Key | Where to Find | Example |
|---|---|---|
| `MODEL_ORIENT` | Variable near top | `sonnet` |
| `MODEL_EXECUTE` | Variable near top | `nvidia/moonshotai/kimi-k2.5` |
| `MODEL_LIGHT` / `MODEL_FINALIZE` | Variable near top | `nvidia/moonshotai/kimi-k2.5` |
| `MODEL_REVIEW` | Variable near top | `sonnet` |
| `MODEL_FALLBACK` | Variable near top | `sonnet` |
| `TIMEOUT_ORIENT` | Variable near top | `30` |
| `TIMEOUT_EXECUTE` | Variable near top | `120` |
| `TIMEOUT_FINALIZE` | Variable near top | `20` |
| `TIMEOUT_REVIEW` | Variable near top | `30` |
| `BUDGET` | Default variable | `10` |
| `ALLOWED_TOOLS_*` | Per-step tool lists | `Read,Write,Edit,Glob,Grep,Bash` |
| Prompt templates | `PROMPTS_DIR` + filenames in build_prompt/check_prereqs | `step1_orient_plan.md` etc |
| Quality gate | `quality_gate()` function body | `./just check` |
| Git add paths | `safe_git_commit()` function body | `src/ tests/ scripts/ research/` |
| Scope restriction | `build_scope_header()` function body | Domain-specific text |
| State dir | `RESEARCH_DIR` variable | `research` or `research/ralph` |
| Review cadence | Main loop `% 10` or similar | `10` |
| Hygiene cadence | Look for `% 5` hygiene injection | `5` or absent |
| Secret patterns | `safe_git_commit()` grep patterns | `.env, credentials, token` |
| Engine routing | `_engine()` function logic | `nvidia/* → opencode, else → claude` |

Present this summary to the user before proceeding.

---

## Phase 2: Feature Discovery — CRITICAL

This is the most important phase. Compare what the old bash loop does vs what langywrap provides.

### Features langywrap HAS (the plumbing it replaces)

Check each. Mark with the langywrap module that handles it:

- [ ] Orient context pre-digestion (~8-11x compression) → `RalphState.build_orient_context()`
- [ ] Model routing per step role → `ExecutionRouter` + `.langywrap/router.yaml`
- [ ] Retry with fallback models on failure → `ExecutionRouter.execute()` retry_models
- [ ] API hang detection (exit 124, small output) → `ExecutionRouter` hung detection
- [ ] Rate limit detection + backoff → `ExecutionRouter` rate_limited handling
- [ ] Heartbeat watcher (progress logging) → `_HeartbeatWatcher`
- [ ] Quality gate subprocess runner → `RalphLoop.quality_gate()`
- [ ] Safe git commit with secret scanning → `RalphLoop.safe_git_commit()`
- [ ] Cycle counter persistence → `RalphState.get/set_cycle_count()`
- [ ] State file management (tasks/progress/plan) → `RalphState`
- [ ] Prompt template loading + scope injection → `build_full_prompt()`
- [ ] Stagnation detection → `RalphLoop.detect_stagnation()`
- [ ] Hygiene task injection every N cycles → `RalphState.inject_hygiene_task()`
- [ ] Dry-run validation → `RalphLoop.dry_run()`
- [ ] Resume from last cycle → `RalphLoop.run(resume=True)`
- [ ] Security engine (deny/ask/allow rules) → `SecurityEngine`
- [ ] Execution wrapper (5-layer) → `.exec/execwrap.bash`

### Features the old bash loop has that langywrap MIGHT NOT

Scan the bash script for patterns NOT in the list above. Common discoveries:

```
LOOK FOR:
  - Custom pre/post cycle hooks (e.g., data refresh, submission upload)
  - Domain-specific validation beyond quality gate (e.g., Lean build, submission format check)
  - Backup/fresh-start logic (state backup before reset)
  - Graceful shutdown / signal trapping (SIGINT/SIGTERM)
  - Interactive resume prompts
  - Custom logging format or log rotation
  - Environment variable loading (.env sourcing)
  - OpenCode-specific setup (XDG_DATA_HOME isolation, auth.json seeding)
  - Tool restriction injection per step (TOOL RESTRICTION block in prompts)
  - Plan freshness validation (check plan mentions current cycle)
  - Pending task count check mid-loop (break if no IN_PROGRESS tasks)
  - Custom metric tracking beyond quality gate
  - Tmux integration
  - Parallel step execution
  - Competition/domain-specific post-processing
```

### Report format

Present discoveries as:

```
FEATURE DISCOVERY REPORT
========================

Already in langywrap:
  ✓ Orient compression (RalphState.build_orient_context)
  ✓ Model routing (ExecutionRouter)
  ...

In old bash, NOT in langywrap — candidates for upstream:
  ✗ Plan freshness validation (check plan.md mentions current cycle)
    → Would benefit: any project using orient+execute pattern
    → Complexity: low (regex check in runner.py)
  ✗ Graceful shutdown with state save (trap SIGINT)
    → Would benefit: all ralph users
    → Complexity: low (signal handler in runner.py)
  ✗ OpenCode auth seeding (XDG_DATA_HOME + auth.json copy)
    → Would benefit: any project using opencode backend
    → Complexity: medium (in backends.py)

In old bash, project-specific — keep in downstream:
  ~ Competition submission format check
  ~ CrunchDAO-specific data validation
```

**Ask the user**: "Want me to add any of these to langywrap before proceeding with migration?"

If yes, implement the requested features in langywrap FIRST, then continue.

---

## Phase 3: Write Config Files

### `.langywrap/ralph.yaml`

Write using values extracted in Phase 1:

```yaml
project_dir: "."
state_dir: "<extracted>"
prompts_dir: "<extracted>"
budget: <extracted>
review_every_n: <extracted>
hygiene_every_n: <extracted or 5>
git_commit_after_cycle: true
git_add_paths: <extracted list>
verbose: true

quality_gate:
  command: "<extracted>"
  timeout_minutes: 10
  required: false  # false = warning only, matches old bash behavior

scope_restriction: |
  <extracted from build_scope_header()>

secret_patterns: <extracted from safe_git_commit()>

steps:
  # Map old step functions to StepConfig entries
  # Use the EXACT prompt template filenames from the old script
```

### `.langywrap/router.yaml`

```yaml
name: <project>-v1
description: "<human description of routing pattern>"
review_every_n: <extracted>
default_backend: claude
rules:
  # Map MODEL_* variables to role/model/backend/tier rules
  # Map TIMEOUT_* to timeout_minutes
  # Map MODEL_FALLBACK to retry_models on execute rule
  # Map _engine() logic to backend field
```

### `.langywrap/permissions.yaml` (if custom rules exist)

Only create if the old .exec/settings.json or .llmsec/guard.sh had project-specific
rules beyond the langywrap defaults.

---

## Phase 4: Create Thin Wrapper

Rename old script: `mv ralph_loop.sh ralph_loop.sh.old`

Write new `ralph_loop.sh` (~54 lines):

```bash
#!/usr/bin/env bash
# ralph_loop.sh — Thin wrapper over langywrap Python orchestrator
# <project description>
#
# Config:  .langywrap/ralph.yaml + .langywrap/router.yaml
# Domain:  research/prompts/ + research/tasks.md
# Old:     ralph_loop.sh.old (preserved for reference)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$SCRIPT_DIR/.venv/bin/activate" ]]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
fi

CMD="run"
ARGS=("$SCRIPT_DIR")

while [[ $# -gt 0 ]]; do
    case "$1" in
        --budget)    shift; ARGS+=(--budget "$1") ;;
        --dry-run)   ARGS+=(--dry-run) ;;
        --resume)    ARGS+=(--resume) ;;
        status)      CMD="status"; ARGS=() ;;
        [0-9]*)      ARGS+=(--budget "$1") ;;
        *)           ARGS+=("$1") ;;
    esac
    shift
done

exec langywrap ralph "$CMD" "${ARGS[@]}"
```

Make executable: `chmod +x ralph_loop.sh`

---

## Phase 5: Validate Migration

Run each check and report results:

```bash
# 1. Config loading
python -c "
from pathlib import Path
from langywrap.ralph.config import load_ralph_config
from langywrap.router.config import load_route_config

cfg = load_ralph_config(Path('.'))
print(f'Steps: {[s.name for s in cfg.steps]}')
print(f'Budget: {cfg.budget}')
for s in cfg.steps:
    print(f'  {s.name}: template={s.prompt_template.name} exists={s.prompt_template.exists()}')

rt = load_route_config(Path('.'))
print(f'Router: {rt.name} ({len(rt.rules)} rules)')
for r in rt.rules:
    print(f'  {r.role.value}: {r.model} via {r.backend.value}')
"

# 2. Security engine
python -c "
from langywrap.security.engine import SecurityEngine
e = SecurityEngine('.')
print(f'Security: {len(e.config.deny)} deny, {len(e.config.ask)} ask, {len(e.config.allow)} allow')
"

# 3. Orient context compression
python -c "
import os
from pathlib import Path
from langywrap.ralph.state import RalphState
from langywrap.ralph.config import load_ralph_config
cfg = load_ralph_config(Path('.'))
state = RalphState(cfg.resolved_state_dir)
ctx = state.build_orient_context()
raw = sum(os.path.getsize(f) for f in [state.tasks_file, state.progress_file, state.plan_file] if f.exists())
print(f'Orient compression: {raw:,}B → {len(ctx):,}B ({raw/max(len(ctx),1):.1f}x)')
print(f'Cycle count: {state.get_cycle_count()}, Pending: {state.pending_count()}')
"

# 4. Dry-run
./ralph_loop.sh --dry-run

# 5. Status
./ralph_loop.sh status

# 6. Quality gate (optional — may take time)
# ./just check
```

---

## Phase 6: Summary Report

Present final diff:

```
MIGRATION COMPLETE: <project>
================================

Before:
  ralph_loop.sh           <N> lines (standalone bash orchestrator)
  .exec/                  static copies
  .llmsec/                standalone guards

After:
  ralph_loop.sh           54 lines (thin wrapper → langywrap)
  .langywrap/ralph.yaml   ~70 lines (domain config)
  .langywrap/router.yaml  ~40 lines (model routing)
  ralph_loop.sh.old       preserved backup

Lines removed:  ~<N>
Lines added:    ~<M> (config YAML)
Net reduction:  ~<N-M> lines of implementation

What langywrap now handles:
  - Orient context compression (<X>x)
  - Model routing + retry + hang detection
  - Security (29 deny rules, prefix matching, data theft prevention)
  - State management (tasks/progress/plan/cycle counter)
  - Quality gate execution
  - Safe git commit with secret scanning
  - Hygiene task injection every <N> cycles
  - Stagnation detection

What stays in <project> (domain):
  - research/prompts/ (step templates)
  - research/tasks.md (task queue)
  - research/progress.md (learnings)
  - All source code, scripts, tests

Features discovered and added to langywrap:
  <list any features added during Phase 2>

Features kept project-specific:
  <list any features NOT upstreamed>

Live-linked: changes in langywrap are immediately visible (editable install).
```
