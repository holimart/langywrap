---
description: Design and implement a tree-search ML experimentation loop (Ralph pattern) for autonomous model improvement
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Task, AskUserQuestion
---

# Ralph Loop: Autonomous ML/DS Experimentation

Design and implement an autonomous tree-search experimentation loop that iteratively improves ML/DS models. Combines the Ralph Wiggum pattern (persistent iteration with fresh context) with AIDE-style tree search (backtracking to avoid local optima).

## Quick Reference

**What this skill does:**
1. **If an existing bash ralph_loop.sh exists** → migrate it to langywrap library (YAML config + thin wrapper)
2. Otherwise, analyzes the target repository's ML/DS workflow
3. **Interactively designs the loop steps with the user** (customizable defaults)
4. Lets the user choose an **execution mode** per step (monolith / subagent / script)
5. Creates experiment infrastructure (state files, runner script, quality gates)
6. Runs autonomous experiment iterations with tree-search exploration

**Argument parsing:** `$ARGUMENTS`
- No args → full setup + first experiment run
- `migrate` → migrate existing bash ralph_loop.sh to langywrap library
- `setup` → only create infrastructure files
- `run` → run experiment loop (assumes setup done)
- `run --budget N` → run N iterations max
- `status` → show tree state and best results
- `resume` → continue from last checkpoint

---

## Background Knowledge

### The Ralph Pattern (Core Mechanics)

The Ralph technique (Geoffrey Huntley, ~Feb 2024) is a `while true` loop feeding an AI agent's output back into itself until external verification passes.

**Key principles:**
- The prompt never changes, but the world does (files on disk, git history, test results)
- Each iteration starts with **fresh context** (avoids context window degradation)
- Memory persists via: git commits, `progress.md`, and state JSON files
- **External verification** (metrics, tests) determines completion — not the LLM's self-assessment
- "Better to fail predictably than succeed unpredictably"

### Tree Search > Linear Iteration (AIDE Pattern)

AIDE (Weco AI) frames ML engineering as code optimization via **tree search in solution space**. On MLE-Bench (75 Kaggle competitions), tree search wins **4x more medals** than linear agents.

**How it works:**
- Each node is a distinct code version; each edge is an improvement step
- Nodes can **branch** (try different approach) or **deepen** (refine existing approach)
- **Backtracking** to earlier working solutions prevents getting stuck in local optima
- A base solution selector picks the most promising node for the next iteration

### Context Management (Fresh Context Per Iteration)

Standard agent loops suffer from **context accumulation** — every failed attempt stays in conversation history. The Ralph pattern solves this:

1. Start each iteration with fresh context (the core insight)
2. Persist state on disk, not in the conversation window
3. External files as memory:
   - `progress.md` — learnings log (what worked, what failed, patterns discovered)
   - `experiment_spec.json` — task definition with acceptance criteria
   - `tree_state.json` — full experiment tree with metrics per node
   - Git history — code changes audit trail

### Two-Loop Architecture (Alibaba Pattern)

Separate exploration from validation:
- **Inner loop** (cheap): Quick experiments on data subset, proxy metrics
- **Outer loop** (expensive): Full validation on complete dataset, only for promising candidates

### ML-Specific Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Overfitting to validation | Holdout test set never touched during loop |
| No statistical significance | Require >1 consecutive run above threshold |
| Computational cost | Set iteration budget, use subsets for exploration |
| Data leakage | Automated leakage checks in quality gates |
| Non-stationarity | Walk-forward validation, regime detection |
| Metric gaming | Immutable test sets, multiple metric requirements |

### Branch-Per-Experiment (Git Worktree Isolation)

Each experiment can run in its own git worktree:
- No interference between parallel experiments
- A coordinator compares metrics across branches
- Best experiment branch merges to main

Real-world: 10 tasks across 3 parallel worktrees, ~$15-25, under an hour.

---

## Architectural Variants: Step-Based vs Task Queue

The Ralph loop can be architected in two fundamentally different ways:

### **Variant A: Step-Based Loop (Default)**

Each iteration executes a **fixed sequence of steps**:
```
ORIENT → HYPOTHESIZE → DECIDE → IMPLEMENT → VALIDATE → EVALUATE → ANALYZE → UPDATE
```

**Characteristics:**
- Structured workflow with predictable stages
- Each step has specific inputs/outputs (JSON handoffs)
- Good for **ML modeling** (hypothesis-driven experimentation)
- Good for **complex tasks** requiring planning before execution

**Example use cases:**
- Feature engineering: form hypothesis about new feature, implement, test, evaluate
- Model architecture: decide on architecture change, implement, validate, measure performance
- Hyperparameter tuning: propose param change, run experiment, compare results

**Tree operations (DECIDE step):**
- DEEPEN: Refine current best approach
- BRANCH: Try alternative from best node
- BACKTRACK: Return to earlier node

---

### **Variant B: Task Queue Mode (Alternative)**

Instead of fixed steps, maintain a **priority queue of tasks** that iterations pick from:

```
tasks.json:
{
  "pending": [
    {"id": "gdelt_sentiment", "priority": "high", "estimated_effort": "2h"},
    {"id": "congressional_trading", "priority": "high", "estimated_effort": "3h"},
    {"id": "etf_flows", "priority": "medium", "estimated_effort": "4h"}
  ],
  "in_progress": [],
  "completed": [],
  "failed": []
}
```

**Each iteration:**
```
1. ORIENT: Read tasks.json, progress.md, git log
2. PICK: Select highest-priority pending task (adaptive selection)
3. EXECUTE: Run the task (may have substeps like design→implement→validate)
4. UPDATE: Move task to completed/failed, update priorities, git commit
```

**Characteristics:**
- Flexible, task-driven workflow
- Priorities can change based on learnings
- Good for **data engineering** (list of independent scrapers to implement)
- Good for **backlogs** where tasks are well-defined upfront
- Simpler than step-based (no hypothesis formation needed)

**Example use cases:**
- **Scraper implementation:** Backlog of 15 data sources, each needs scraper + tests + integration
- **Tech debt:** List of refactoring tasks, prioritized by impact
- **Feature backlog:** Product roadmap of features to implement

**Adaptive priority:**
- Completed tasks can unlock new tasks (dependencies)
- Failed tasks can be deprioritized or moved to "blocked"
- Learnings can reprioritize remaining tasks (e.g., "after GDELT success, prioritize other sentiment sources")

---

### **How to Choose**

| Factor | Step-Based | Task Queue |
|--------|------------|------------|
| **Task clarity** | Unclear (need hypothesis) | Clear (well-defined tasks) |
| **Dependencies** | Complex (hypothesis → implementation) | Simple (mostly independent) |
| **Task count** | 5-20 iterations | 10-100 tasks |
| **Exploration** | High (try different approaches) | Low (implement known tasks) |
| **Backtracking** | Needed (can hit dead ends) | Rarely (tasks are validated upfront) |
| **Best for** | Research, modeling, experimentation | Engineering, implementation, backlog |

**Example decision matrix:**

| Project | Mode | Rationale |
|---------|------|-----------|
| "Improve model ROI from 2% to 5%" | Step-Based | Need to explore different features, architectures, strategies |
| "Add 15 missing data sources" | Task Queue | Tasks are well-defined, mostly independent, clear success criteria |
| "Refactor codebase to improve test coverage" | Task Queue | List of modules to refactor, clear checklist |
| "Beat benchmark model on MLE-Bench" | Step-Based | Open-ended exploration, hypothesis-driven |

---

### **Task Queue Implementation**

**1. Task Manifest (`tasks.json`):**

```json
{
  "version": 1,
  "task_categories": {
    "quick_wins": ["gdelt_sentiment", "congressional_trading"],
    "high_value": ["etf_flows", "earnings_transcripts"],
    "research": ["satellite_data", "supply_chain"]
  },
  "tasks": {
    "gdelt_sentiment": {
      "id": "gdelt_sentiment",
      "name": "News Sentiment (GDELT)",
      "category": "quick_wins",
      "priority": 10,
      "estimated_effort_hours": 2,
      "status": "pending",
      "description": "Implement GDELT news sentiment scraper",
      "acceptance_criteria": [
        "Scraper passes all tests",
        "Bronze layer integration complete",
        "Lineage documented"
      ],
      "dependencies": [],
      "assigned_iteration": null
    }
  },
  "queue_state": {
    "pending": ["gdelt_sentiment", "congressional_trading", "..."],
    "in_progress": [],
    "completed": [],
    "failed": []
  }
}
```

**2. Iteration Steps (Simplified):**

```json
{
  "orchestration": {
    "mode": "task_queue",
    "steps": [
      {
        "name": "orient",
        "mode": "subagent",
        "prompt": "Read tasks.json and progress.md. Summarize: completed tasks, failed tasks, remaining tasks. Write to steps/orient.json."
      },
      {
        "name": "select",
        "mode": "subagent",
        "prompt": "Read tasks.json and steps/orient.json. Select the next task using adaptive priority strategy. Consider: quick wins first (iterations 1-4), high value after (5+), dependencies, failures. Write to steps/select.json: {selected_task_id, rationale}."
      },
      {
        "name": "execute",
        "mode": "subagent",
        "prompt": "Read steps/select.json and tasks.json. Execute the selected task. This may involve multiple substeps (design, implement, validate). When complete, write steps/execute.json: {success: bool, output_summary, issues_encountered}."
      },
      {
        "name": "update",
        "mode": "script",
        "command": "python update_tasks.py",
        "notes": "Moves task from pending to completed/failed. Updates priorities. Git commit."
      }
    ]
  }
}
```

**3. Adaptive Selection Logic (in SELECT step):**

```python
def select_next_task(tasks, orient_summary):
    """Adaptive task selection strategy."""
    iteration = orient_summary["iteration"]
    completed = orient_summary["completed"]
    failed = orient_summary["failed"]

    # Phase 1 (iterations 1-4): Quick wins
    if iteration <= 4:
        candidates = [t for t in tasks if t["category"] == "quick_wins" and t["status"] == "pending"]

    # Phase 2 (iterations 5+): High value
    else:
        candidates = [t for t in tasks if t["category"] in ["high_value", "quick_wins"] and t["status"] == "pending"]

    # Filter out tasks with unmet dependencies
    candidates = [t for t in candidates if all(dep in completed for dep in t["dependencies"])]

    # Skip recently failed tasks (give them cooldown)
    recent_failures = [f["task_id"] for f in failed[-3:]]
    candidates = [t for t in candidates if t["id"] not in recent_failures]

    # Sort by priority (descending)
    candidates.sort(key=lambda t: t["priority"], reverse=True)

    return candidates[0] if candidates else None
```

**4. Progress Tracking:**

```markdown
# Task Queue Progress

## Iteration 1 — gdelt_sentiment
**Status:** ✅ Completed
**Effort:** 2.5 hours (estimated: 2h)
**Output:** Scraper implemented, 17 tests passing, bronze integration complete
**Learnings:**
- GDELT API rate limit is 10 req/sec (update other news sources)
- Entity resolution via entity_mapping.csv works well
**Next:** Prioritize congressional_trading (also quick win)

---

## Iteration 2 — congressional_trading
**Status:** ❌ Failed
**Reason:** API requires paid subscription (not documented in manifest)
**Decision:** Move to "blocked" category, deprioritize similar premium APIs
**Next:** Move to etf_flows (high value, free API)

---
```

**5. Benefits vs Step-Based:**

| Aspect | Task Queue | Step-Based |
|--------|------------|------------|
| Setup complexity | Simpler (no hypothesis formation) | More complex (8 steps) |
| Execution simplicity | Simpler (pick and execute) | More structured (fixed workflow) |
| Resumption | Natural (just pick next task) | Requires special handling |
| Failure handling | Move to failed queue | May require backtracking |
| Parallelization | Easy (independent tasks) | Harder (tree dependencies) |
| Flexibility | Lower (tasks predefined) | Higher (can pivot strategy) |

**6. When to Use Task Queue:**

✅ **Use Task Queue if:**
- You have a clear backlog of independent tasks
- Tasks are well-defined with acceptance criteria
- Minimal exploration needed (you know what to build)
- Tasks are similar in nature (e.g., all scrapers, all refactorings)
- Prioritization is straightforward (quick wins → high value)

❌ **Use Step-Based if:**
- Open-ended problem (don't know what will work)
- Need hypothesis formation and testing
- Tasks are interdependent (each build on previous learnings)
- Require backtracking when hitting dead ends
- Research/modeling focus (not engineering)

**7. Hybrid Approach:**

You can combine both:
- **Task Queue for backlog management** (what to work on)
- **Step-based for execution** (how to implement each task)

Example:
```
ORIENT → SELECT_TASK (from queue) → [DESIGN → IMPLEMENT → VALIDATE → INTEGRATE] → UPDATE_QUEUE
```

This gives you:
- Clear task prioritization (queue)
- Structured execution workflow (steps)
- Easy resumption (task-level checkpointing)

---

## Phase 0: Migrate Existing Bash Loop to langywrap Library

**When to use this phase:** The target repo already has a bash `ralph_loop.sh` (typically 500-1000 lines). Instead of maintaining complex bash, migrate to the langywrap Python library which handles all plumbing (model routing, retries, heartbeats, rate limits, hang detection, security, git commits, state compression).

**Skip to Phase 1 if:** No existing ralph_loop.sh exists.

### Step 0.1: Read the Existing Bash Script

Read the existing `ralph_loop.sh` and extract these key parameters:

| Parameter | Bash variable(s) | YAML destination |
|-----------|------------------|------------------|
| Models per step | `MODEL_ORIENT`, `MODEL_EXECUTE`, `MODEL_LIGHT`, `MODEL_REVIEW`, `MODEL_FALLBACK` | `router.yaml` rules |
| Engine detection | `_engine()` function (nvidia/* → opencode, else → claude) | `router.yaml` backend field |
| Timeouts | `TIMEOUT_ORIENT`, `TIMEOUT_EXECUTE`, etc. | `router.yaml` + `ralph.yaml` steps |
| Tool restrictions | `ALLOWED_TOOLS_ORIENT`, `ALLOWED_TOOLS_EXECUTE`, etc. | `ralph.yaml` steps.tools |
| Quality gate | `quality_gate()` function, `MAX_QUALITY_RETRIES` | `ralph.yaml` quality_gate |
| Git add paths | `safe_git_commit()` explicit file list | `ralph.yaml` git_add_paths |
| Scope restrictions | `build_scope_header()` | `ralph.yaml` scope_restriction |
| Secret patterns | grep patterns in `safe_git_commit()` | `ralph.yaml` secret_patterns |
| Prompt templates | `PROMPTS_DIR`, `build_prompt()` | `ralph.yaml` prompts_dir + steps.prompt_template |
| State files | `TASKS`, `PROGRESS`, `PLAN`, `CYCLE_FILE` | `ralph.yaml` state_dir |
| Budget | `BUDGET` default | `ralph.yaml` budget |
| Review cadence | e.g. `i % 10 == 0` | `ralph.yaml` + `router.yaml` review_every_n |
| Hygiene/lookback injections | `i % 5`, `i % 9` blocks | These stay in bash or move to hooks (not yet in library) |

### Step 0.2: Create `.langywrap/` Config Directory

Create three YAML files:

**`.langywrap/config.yaml`** — project identity:
```yaml
project_name: "<project-name>"
langywrap_dir: "/mnt/work4t/Projects/langywrap"  # or wherever langywrap is
archive_dir: "/mnt/work4t/Projects/langywrap/experiments/archive"
hub_solutions_dir: "/mnt/work4t/Projects/langywrap/docs/solutions"
```

**`.langywrap/router.yaml`** — model routing (one rule per step role):
```yaml
# Model routing — <Project Name>
# Migrated from ralph_loop.sh MODEL_* variables
name: <project>-v1
description: "<brief routing strategy>"
review_every_n: 10
default_backend: claude
rules:
  - role: orient
    model: sonnet               # was MODEL_ORIENT
    backend: claude              # from _engine() detection
    tier: mid
    timeout_minutes: 30          # was TIMEOUT_ORIENT
    retry_models: [claude-haiku-4-5-20251001]
    retry_max: 2
  - role: execute
    model: nvidia/moonshotai/kimi-k2.5   # was MODEL_EXECUTE
    backend: opencode            # nvidia/* prefix → opencode
    tier: cheap
    timeout_minutes: 120         # was TIMEOUT_EXECUTE
    retry_models: [sonnet]       # was MODEL_FALLBACK
    retry_max: 2
  - role: finalize
    model: nvidia/moonshotai/kimi-k2.5   # was MODEL_LIGHT
    backend: opencode
    tier: cheap
    timeout_minutes: 20          # was TIMEOUT_FINALIZE
    retry_models: [claude-haiku-4-5-20251001]
    retry_max: 2
  - role: review
    model: sonnet                # was MODEL_REVIEW
    backend: claude
    tier: mid
    timeout_minutes: 30          # was TIMEOUT_REVIEW
    retry_models: [claude-haiku-4-5-20251001]
    retry_max: 1
```

**`.langywrap/ralph.yaml`** — loop config:
```yaml
# Ralph loop config — <Project Name>
# Migrated from ralph_loop.sh (N lines → this YAML + langywrap library)

project_dir: "."
state_dir: "research"                    # was RESEARCH_DIR relative
prompts_dir: "research/prompts"          # was PROMPTS_DIR
budget: 10                               # was BUDGET default
review_every_n: 10                       # was i % 10 == 0
git_commit_after_cycle: true
git_add_paths:                           # from safe_git_commit() explicit list
  - "src/"
  - "tests/"
  - "research/tasks.md"
  - "research/progress.md"
  - "research/plan.md"
  - "research/cycle_count.txt"
  - "research/prompts/"
  - "docs/"
  - "pyproject.toml"
  - "justfile"
  - "CLAUDE.md"
verbose: true

quality_gate:
  command: "./just check"                # from quality_gate() function
  timeout_minutes: 10
  required: false                        # false = continue on failure
  max_retries: 2                         # was MAX_QUALITY_RETRIES

scope_restriction: |                     # from build_scope_header()
  <Copy the CRITICAL SCOPE RESTRICTIONS from the bash script>

secret_patterns:                         # from safe_git_commit() grep patterns
  - '\.env$'
  - 'credentials'
  - 'secret'
  - 'token'
  - '_key\.pem'
  - 'id_rsa'

steps:
  - name: orient
    prompt_template: "step1_orient_plan.md"
    role: orient
    timeout_minutes: 30
    confirmation_token: ""
    tools: "Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch"  # was ALLOWED_TOOLS_ORIENT
  - name: execute
    prompt_template: "step2_execute.md"
    role: execute
    timeout_minutes: 120
    confirmation_token: ""
    depends_on: []
    tools: "Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch"  # was ALLOWED_TOOLS_EXECUTE
  - name: finalize
    prompt_template: "step3_finalize.md"
    role: finalize
    timeout_minutes: 20
    confirmation_token: ""
    depends_on: []
    tools: "Read,Write,Edit,Glob,Grep"                          # was ALLOWED_TOOLS_LIGHT
  - name: review
    prompt_template: "step4_review.md"
    role: review
    timeout_minutes: 30
    confirmation_token: ""
    depends_on: []
    tools: "Read,Write,Edit,Glob,Grep"                          # was ALLOWED_TOOLS_REVIEW
```

### Step 0.3: Add langywrap as Dev Dependency

In `pyproject.toml`:
```toml
[dependency-groups]
dev = [
    "langywrap",
    # ... existing dev deps ...
]

[tool.uv.sources]
langywrap = { path = "/mnt/work4t/Projects/langywrap", editable = true }
```

Then sync: `./uv sync` (or `uv sync`).

### Step 0.4: Replace ralph_loop.sh with Thin Wrapper

Back up the old script, then replace with ~55-line wrapper:

```bash
cp ralph_loop.sh ralph_loop.sh.old
```

New `ralph_loop.sh`:
```bash
#!/usr/bin/env bash
# =============================================================================
# ralph_loop.sh — Thin wrapper over langywrap Python orchestrator
# =============================================================================
# <Project Name>
#
# All plumbing (model routing, retries, state compression, security, git)
# is handled by langywrap library. This script just parses args and delegates.
#
# Config lives in:
#   .langywrap/ralph.yaml   — steps, timeouts, quality gate, scope
#   .langywrap/router.yaml  — model routing (which model for which role)
#
# Domain logic lives in:
#   research/prompts/       — step templates (orient, execute, finalize, review)
#   research/tasks.md       — task queue
#   research/progress.md    — append-only learnings log
#   research/plan.md        — current cycle plan
#
# Old N-line bash loop preserved as ralph_loop.sh.old
# =============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate venv
if [[ -f "$SCRIPT_DIR/.venv/bin/activate" ]]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
fi

# Parse args into langywrap CLI format
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

### Step 0.5: Verify with Dry Run

```bash
./ralph_loop.sh --dry-run
```

This should output JSON showing:
- All steps with their prompt templates (and whether files exist)
- Router routing table (which model/backend per step)
- Quality gate config
- Current cycle count and pending task count

### Step 0.6: What Gets Migrated vs What Doesn't

**Handled by langywrap library** (remove from bash):
- Model routing + fallback (`_engine()`, model variables)
- Subagent execution (`run_subagent()` — ~120 lines)
- Heartbeat watcher (background thread, not bash process)
- API hang detection (exit 124 + output size < 2KB)
- Rate limit detection + backoff
- Quality gate execution + retry loop
- Safe git commit (explicit file list, secret scanning)
- Peak-hour throttling
- Resume/fresh detection
- Scope header injection
- Orient context pre-digestion
- Prompt building (scope + template)
- Cost tracking per model
- Dry-run validation
- CLAUDECODE unset + __EXECWRAP_ACTIVE

**NOT yet handled by library** (keep as custom hooks or accept the loss):
- Hygiene task injection (every N cycles) — custom per project
- Process improvement lookback (every M cycles) — custom per project
- Plan freshness validation (`grep -q "## Execution Checklist"`)
- IN_PROGRESS task check before execute

These project-specific injections can be added as pre-cycle hooks in the future, or kept in a small companion script that runs before `langywrap ralph run`.

### Step 0.7: Common Migration Pitfalls

1. **StepRole enum mismatch**: The ralph StepRole (`lib/langywrap/ralph/config.py`) must include all roles you use. If you get `Input should be 'orient', 'plan', 'execute'...` errors, check that `REVIEW` (or whatever role) exists in the enum.

2. **Router StepRole vs Ralph StepRole**: Two separate enums exist (`langywrap.router.config.StepRole` and `langywrap.ralph.config.StepRole`). Both are `str` enums with the same values, so string comparison works. The runner maps between them via `RouterStepRole(step.role.value)`.

3. **`tools` field format**: In `ralph.yaml`, `tools` is a comma-separated string (e.g. `"Read,Write,Edit,Glob,Grep,Bash"`). The router parses this into a list and passes to `ClaudeBackend` via `--allowedTools`.

4. **`engine` field**: Set to `"auto"` (default) to let the router decide based on `router.yaml`. Set to `"claude"`, `"opencode"`, `"openrouter"`, or `"direct_api"` to force a specific backend for a step.

5. **Prompt templates stay as-is**: The `research/prompts/*.md` files don't change. The library reads them and prepends the scope restriction header.

6. **`confirmation_token: ""`**: Set to empty string to skip token validation. If your bash loop checked for `ORIENT_CONFIRMED:` etc., you can add those tokens back.

---

## Phase 1: Repository Analysis & Loop Design

### Step 1.1: Discover Project Structure

Read these files (if they exist):
- `CLAUDE.md`, `.clinerules`, `README.md` — project conventions
- `pyproject.toml`, `package.json`, `Cargo.toml` — dependencies and tools
- `justfile`, `Makefile` — available commands
- Any existing experiment/backtest/training scripts

### Step 1.2: Identify ML/DS Workflow

Determine:
1. **What models exist?** (baseline models, production models, experimental)
2. **What metrics matter?** (ROI, Sharpe, accuracy, F1, RMSE, etc.)
3. **How are experiments run?** (scripts, notebooks, CLI commands)
4. **What data pipeline exists?** (raw → processed → features → training)
5. **What validation strategy is used?** (holdout, cross-val, walk-forward, temporal split)
6. **What quality gates exist?** (tests, linting, type checking, leakage detection)

### Step 1.3: Ask User for Experiment Goals

Use AskUserQuestion to clarify:
- **Target metric**: What are we optimizing? (e.g., "ROI > 3% on validation set")
- **Experiment scope**: What can we change? (features, model architecture, hyperparameters, data sources)
- **Budget**: Max iterations? Max compute time? Max API cost?
- **Autonomy level**: Full auto vs. human-approval checkpoints?

### Step 1.4: Design Loop Steps (Interactive)

Present the **default iteration steps** to the user for review and customization. Each step has a name, description, and suggested execution mode.

**Default steps:**

```
┌─────┬──────────────┬───────────────────────────────────────────────────┬────────────┐
│  #  │ Step         │ What it does                                      │ Default    │
├─────┼──────────────┼───────────────────────────────────────────────────┼────────────┤
│  1  │ ORIENT       │ Read state files, git log, understand context      │ subagent   │
│  2  │ HYPOTHESIZE  │ Form testable hypothesis based on learnings        │ subagent   │
│  3  │ DECIDE       │ Tree operation: deepen / branch / backtrack        │ subagent   │
│  4  │ IMPLEMENT    │ Make minimal code changes to test hypothesis       │ subagent   │
│  5  │ VALIDATE     │ Run quality gates (lint, typecheck, test)          │ script     │
│  6  │ EVALUATE     │ Run experiment, parse metrics                      │ script     │
│  7  │ ANALYZE      │ Compare results to best, decide next direction     │ subagent   │
│  8  │ UPDATE       │ Update tree_state.json, progress.md, git commit    │ script     │
└─────┴──────────────┴───────────────────────────────────────────────────┴────────────┘
```

Use AskUserQuestion with these questions:

**Question 1: "How should each iteration be orchestrated?"**

| Option | Description | Best for |
|--------|-------------|----------|
| **Monolith** (one big prompt) | All steps in a single `claude -p` invocation. Agent decides how to handle each step. Simplest, most flexible, but agent may skip steps or lose focus. | Quick experiments, exploration, when steps are tightly coupled |
| **Subagent per step** | Each step gets its own focused `claude -p` call with a narrow prompt. State passes between steps via JSON files. More controlled, each step gets full context budget. | Complex experiments, when individual steps need deep reasoning |
| **Script pipeline** | Each step is a bash/python script. AI only for creative steps (HYPOTHESIZE, IMPLEMENT, ANALYZE). Deterministic steps (VALIDATE, EVALUATE, UPDATE) run as plain scripts. Cheapest, most reproducible. | Production experiments, when quality gates and evaluation are well-defined |
| **Hybrid** (Recommended) | Mix modes per step. Creative steps use subagents, mechanical steps use scripts. Best balance of control and flexibility. | Most ML/DS workflows |

**Question 2: "Want to customize the steps?"**

| Option | Description |
|--------|-------------|
| **Use defaults** | Keep the 8 steps as shown above |
| **Customize** | Review and modify steps (add, remove, reorder, rename, change mode) |

If the user chooses "Customize", present each step and ask:
- Keep / Remove / Modify?
- Change execution mode?
- Add custom steps?

### Step 1.5: Confirm Loop Design

After customization, present the final step table for confirmation:

```
Final Loop Design:
┌─────┬──────────────┬──────────┬──────────────────────────────┐
│  #  │ Step         │ Mode     │ Command / Prompt             │
├─────┼──────────────┼──────────┼──────────────────────────────┤
│  1  │ ORIENT       │ subagent │ "Read state files and..."    │
│  2  │ HYPOTHESIZE  │ subagent │ "Based on progress.md..."    │
│  3  │ DECIDE       │ subagent │ "Given the tree state..."    │
│  4  │ IMPLEMENT    │ subagent │ "Implement this change..."   │
│  5  │ VALIDATE     │ script   │ ./just lint && ./just test   │
│  6  │ EVALUATE     │ script   │ ./just sports-baseline ...   │
│  7  │ ANALYZE      │ subagent │ "Compare results to best..." │
│  8  │ UPDATE       │ script   │ update_state.py              │
└─────┴──────────────┴──────────┴──────────────────────────────┘
```

Save this design into experiment_spec.json under `"orchestration"`.

---

## Phase 2: Create Infrastructure

### Step 2.1: Experiment Spec (`experiment_spec.json`)

Create in project root (or a configured experiments directory). Now includes orchestration config:

```json
{
  "project": "<project-name>",
  "created": "<ISO-8601 timestamp>",
  "objective": "<natural language description of what we're optimizing>",
  "metrics": {
    "primary": {
      "name": "<metric name, e.g. roi_validation>",
      "direction": "maximize|minimize",
      "threshold": "<number — minimum acceptable value>",
      "description": "<what this metric measures>"
    },
    "secondary": [
      {
        "name": "<e.g. sharpe_ratio>",
        "direction": "maximize",
        "threshold": "<number>",
        "description": "<description>"
      }
    ],
    "guardrails": [
      {
        "name": "<e.g. max_drawdown>",
        "operator": "<=",
        "threshold": "<number>",
        "description": "Hard constraint — experiment fails if violated"
      }
    ]
  },
  "validation": {
    "strategy": "temporal_split|walk_forward|cross_val|holdout",
    "train_period": "<e.g. 2022-01-01 to 2024-06-30>",
    "val_period": "<e.g. 2024-07-01 to 2025-06-30>",
    "test_period": "<e.g. 2025-07-01 to 2025-12-31 — NEVER TOUCH DURING LOOP>",
    "notes": "Test set is evaluated ONCE at the end, not during iteration"
  },
  "scope": {
    "changeable": ["<list of files/modules that can be modified>"],
    "frozen": ["<list of files/modules that must NOT be modified>"],
    "notes": "<any constraints on what the agent can change>"
  },
  "budget": {
    "max_iterations": 20,
    "max_cost_usd": 50,
    "max_time_minutes": 120
  },
  "quality_gates": {
    "pre_commit": ["<e.g. ./just lint>", "<e.g. ./just typecheck>"],
    "pre_evaluate": ["<e.g. ./just test>"],
    "leakage_check": "<command or null>",
    "statistical_significance": {
      "min_consecutive_improvements": 1,
      "min_sample_size": null
    }
  },
  "commands": {
    "run_experiment": "<command to train/run the model>",
    "evaluate": "<command to compute metrics on validation set>",
    "evaluate_test": "<command to compute metrics on test set — used ONCE at end>"
  },
  "orchestration": {
    "mode": "hybrid|monolith|subagent|script",
    "steps": [
      {
        "name": "orient",
        "description": "Read state files, git log, understand what has been tried",
        "mode": "subagent",
        "prompt": "Read experiments/experiment_spec.json, experiments/tree_state.json, experiments/progress.md, and git log --oneline -10. Summarize: (1) current best metric, (2) what has been tried, (3) what hasn't been tried yet. Write summary to experiments/step_orient.json.",
        "output": "experiments/step_orient.json"
      },
      {
        "name": "hypothesize",
        "description": "Form a testable hypothesis based on learnings",
        "mode": "subagent",
        "prompt": "Read experiments/step_orient.json. Based on what has and hasn't been tried, propose ONE testable hypothesis. Be specific: what change, what expected effect, why. Write to experiments/step_hypothesis.json with fields: hypothesis, expected_effect, rationale, files_to_change.",
        "input": "experiments/step_orient.json",
        "output": "experiments/step_hypothesis.json"
      },
      {
        "name": "decide",
        "description": "Choose tree operation: deepen, branch, or backtrack",
        "mode": "subagent",
        "prompt": "Read experiments/tree_state.json and experiments/step_hypothesis.json. Decide: DEEPEN (refine current best), BRANCH (try alternative from best), or BACKTRACK (return to earlier node). Write decision to experiments/step_decision.json with fields: operation, parent_node, rationale.",
        "input": "experiments/step_hypothesis.json",
        "output": "experiments/step_decision.json"
      },
      {
        "name": "implement",
        "description": "Make minimal code changes to test hypothesis",
        "mode": "subagent",
        "prompt": "Read experiments/step_hypothesis.json and experiments/step_decision.json. Implement the hypothesis with MINIMAL code changes. Only modify files listed in scope.changeable. Write a summary of changes to experiments/step_implement.json.",
        "input": "experiments/step_decision.json",
        "output": "experiments/step_implement.json"
      },
      {
        "name": "validate",
        "description": "Run quality gates (lint, typecheck, test)",
        "mode": "script",
        "command": "./just lint && ./just typecheck && ./just test",
        "on_failure": "The subagent for 'implement' is re-invoked with the error output to fix the issue (max 3 retries)."
      },
      {
        "name": "evaluate",
        "description": "Run experiment and capture metrics",
        "mode": "script",
        "command": "<from commands.evaluate in spec>",
        "output": "experiments/step_evaluate.json",
        "notes": "Script should parse metrics from command output into JSON."
      },
      {
        "name": "analyze",
        "description": "Compare results to best node, decide next direction",
        "mode": "subagent",
        "prompt": "Read experiments/step_evaluate.json and experiments/tree_state.json. Compare new metrics to best_node. Did we improve? Why or why not? What should the next iteration try? Write analysis to experiments/step_analyze.json with fields: improved (bool), delta, explanation, next_suggestion.",
        "input": "experiments/step_evaluate.json",
        "output": "experiments/step_analyze.json"
      },
      {
        "name": "update",
        "description": "Update tree state, progress log, git commit",
        "mode": "script",
        "command": "python experiments/update_state.py",
        "notes": "Script reads step_*.json files, updates tree_state.json and progress.md, runs git commit."
      }
    ]
  }
}
```

### Step 2.2: Tree State (`tree_state.json`)

This is the core data structure enabling tree search with backtracking:

```json
{
  "version": 1,
  "current_node": "node_001",
  "best_node": null,
  "best_metric": null,
  "iteration_count": 0,
  "total_cost_usd": 0,
  "nodes": {
    "node_000": {
      "id": "node_000",
      "parent": null,
      "children": [],
      "git_ref": "<commit hash or branch name — baseline>",
      "description": "Baseline (starting point)",
      "hypothesis": null,
      "metrics": {},
      "status": "evaluated",
      "created_at": "<ISO timestamp>",
      "iteration": 0
    }
  },
  "history": []
}
```

**Node lifecycle:** `proposed` → `implementing` → `evaluating` → `evaluated` → (`accepted` | `rejected`)

**Tree operations:**
- **Deepen**: Create child of current best node (refine what works)
- **Branch**: Create sibling of current node (try alternative approach)
- **Backtrack**: Return to a previous node and branch from there (escape local optima)

### Step 2.3: Progress Log (`progress.md`)

```markdown
# Experiment Progress

## Experiment: <objective from spec>
Started: <timestamp>

---

### Iteration 1 — node_001 (child of node_000)
**Hypothesis:** <what we're trying and why>
**Changes:** <brief description of code changes>
**Results:**
- primary_metric: <value> (baseline: <value>, delta: <+/- value>)
- secondary_metrics: ...
**Analysis:** <why did this work/fail? what did we learn?>
**Decision:** deepen | branch | backtrack
**Next:** <what to try next based on learnings>

---
```

### Step 2.4: Run Script (Mode-Specific)

Create a runner script based on the chosen orchestration mode.

**IMPORTANT — Claude CLI invocation:**
- Use `claude -p "$PROMPT"` (not `claude --print "$PROMPT"`)
- `-p` is the flag for non-interactive/headless mode that accepts a prompt argument
- `--print` alone does NOT accept a positional prompt — it requires stdin
- The script CANNOT run inside a Claude Code session (nested sessions crash). It must be run from a regular terminal.
- Add a `--dry-run` mode so users can validate setup from within Claude Code

#### Mode A: Monolith (one big prompt)

All steps in a single `claude -p` call. Simplest. Agent handles everything.

```bash
#!/usr/bin/env bash
# ralph_experiment.sh — Monolith mode: one prompt per iteration
set -euo pipefail

BUDGET=20; DRY_RUN=false
for arg in "$@"; do
  case "$arg" in --dry-run) DRY_RUN=true ;; [0-9]*) BUDGET="$arg" ;; esac
done

EXPERIMENT_DIR="$(cd "$(dirname "$0")" && pwd)"
SPEC="$EXPERIMENT_DIR/experiment_spec.json"
TREE="$EXPERIMENT_DIR/tree_state.json"
PROGRESS="$EXPERIMENT_DIR/progress.md"

# Prereqs
[[ -f "$SPEC" ]] || { echo "ERROR: $SPEC not found."; exit 1; }
[[ -f "$TREE" ]] || { echo "ERROR: $TREE not found."; exit 1; }
command -v jq &>/dev/null || { echo "ERROR: jq not found."; exit 1; }

if ! $DRY_RUN; then
  [[ -z "${CLAUDECODE:-}" ]] || { echo "ERROR: Cannot run inside Claude Code. Use a regular terminal."; exit 1; }
  command -v claude &>/dev/null || { echo "ERROR: claude not found."; exit 1; }
fi

PROMPT='You are an autonomous ML experiment agent. Read experiment_spec.json, tree_state.json, and progress.md. Then:

1. ORIENT: Read state files + git log. Understand what has been tried.
2. HYPOTHESIZE: Form a testable hypothesis based on learnings.
3. DECIDE: Deepen (refine current best), branch (try alternative), or backtrack.
4. IMPLEMENT: Make minimal code changes to test the hypothesis.
5. VALIDATE: Run quality gates (lint, typecheck, test).
6. EVALUATE: Run the experiment and record metrics.
7. ANALYZE: Compare to best. Explain why it worked or failed.
8. UPDATE: Update tree_state.json + progress.md. Git commit.

CRITICAL RULES:
- NEVER touch the test set. Validation metrics only.
- NEVER skip quality gates.
- If stuck 3+ iterations, BACKTRACK.
- Output EXPERIMENT_COMPLETE if threshold met.'

echo "=== Ralph Loop (Monolith Mode) === Budget: $BUDGET"
if $DRY_RUN; then
  echo "[OK] All files present. Prompt: ${#PROMPT} chars."
  echo "Run from terminal: ./experiments/ralph_experiment.sh $BUDGET"
  exit 0
fi

for ((i=1; i<=BUDGET; i++)); do
  echo ""; echo "=== Iteration $i / $BUDGET ==="
  echo "  Best: $(jq -r '.best_metric // "none"' "$TREE")"
  claude -p "$PROMPT" --allowedTools "Read,Write,Edit,Glob,Grep,Bash"
  grep -q "EXPERIMENT_COMPLETE" "$PROGRESS" 2>/dev/null && { echo "=== COMPLETE ==="; break; }
done

echo "=== Results: best=$(jq -r '.best_metric // "none"' "$TREE") ==="
```

#### Mode B: Subagent per step

Each step gets its own focused `claude -p` with a narrow prompt. State flows via `step_*.json` files.

```bash
#!/usr/bin/env bash
# ralph_experiment.sh — Subagent mode: one claude call per step
set -euo pipefail

BUDGET=20; DRY_RUN=false
for arg in "$@"; do
  case "$arg" in --dry-run) DRY_RUN=true ;; [0-9]*) BUDGET="$arg" ;; esac
done

EXPERIMENT_DIR="$(cd "$(dirname "$0")" && pwd)"
SPEC="$EXPERIMENT_DIR/experiment_spec.json"
TREE="$EXPERIMENT_DIR/tree_state.json"
PROGRESS="$EXPERIMENT_DIR/progress.md"
STEPS_DIR="$EXPERIMENT_DIR/steps"
mkdir -p "$STEPS_DIR"

[[ -f "$SPEC" ]] || { echo "ERROR: $SPEC not found."; exit 1; }
[[ -f "$TREE" ]] || { echo "ERROR: $TREE not found."; exit 1; }
command -v jq &>/dev/null || { echo "ERROR: jq not found."; exit 1; }

if ! $DRY_RUN; then
  [[ -z "${CLAUDECODE:-}" ]] || { echo "ERROR: Cannot run inside Claude Code."; exit 1; }
  command -v claude &>/dev/null || { echo "ERROR: claude not found."; exit 1; }
fi

echo "=== Ralph Loop (Subagent Mode) === Budget: $BUDGET"
if $DRY_RUN; then
  echo "[OK] All files present."
  echo "Steps: $(jq -r '.orchestration.steps | length' "$SPEC") configured"
  jq -r '.orchestration.steps[] | "  \(.name) [\(.mode)]"' "$SPEC"
  echo "Run from terminal: ./experiments/ralph_experiment.sh $BUDGET"
  exit 0
fi

run_subagent() {
  local step_name="$1" prompt="$2"
  echo "  [$step_name] Running subagent..."
  claude -p "$prompt" --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    2>&1 | tee "$STEPS_DIR/${step_name}_output.log"
}

run_script() {
  local step_name="$1" command="$2"
  echo "  [$step_name] Running: $command"
  eval "$command" 2>&1 | tee "$STEPS_DIR/${step_name}_output.log"
}

for ((i=1; i<=BUDGET; i++)); do
  echo ""; echo "========================================="
  echo "=== Iteration $i / $BUDGET ==="
  echo "========================================="

  # Read steps from spec and execute each one
  num_steps=$(jq -r '.orchestration.steps | length' "$SPEC")
  for ((s=0; s<num_steps; s++)); do
    step_name=$(jq -r ".orchestration.steps[$s].name" "$SPEC")
    step_mode=$(jq -r ".orchestration.steps[$s].mode" "$SPEC")

    case "$step_mode" in
      subagent)
        step_prompt=$(jq -r ".orchestration.steps[$s].prompt" "$SPEC")
        run_subagent "$step_name" "$step_prompt"
        ;;
      script)
        step_cmd=$(jq -r ".orchestration.steps[$s].command" "$SPEC")
        if ! run_script "$step_name" "$step_cmd"; then
          echo "  [$step_name] FAILED — checking on_failure policy..."
          on_fail=$(jq -r ".orchestration.steps[$s].on_failure // \"abort\"" "$SPEC")
          if [[ "$on_fail" == "abort" ]]; then
            echo "  Aborting iteration $i due to $step_name failure."
            break
          fi
          # Retry: re-run implement subagent with error context
          error_log=$(cat "$STEPS_DIR/${step_name}_output.log")
          run_subagent "fix_${step_name}" \
            "The $step_name step failed with: $error_log. Fix the code and try again."
          # Re-run the failed script
          run_script "$step_name" "$step_cmd" || {
            echo "  [$step_name] Still failing after fix. Skipping iteration."; break;
          }
        fi
        ;;
    esac
  done

  grep -q "EXPERIMENT_COMPLETE" "$PROGRESS" 2>/dev/null && { echo "=== COMPLETE ==="; break; }
done

echo "=== Results: best=$(jq -r '.best_metric // "none"' "$TREE") ==="
```

#### Mode C: Script pipeline (hybrid)

AI only for creative steps. Deterministic steps are plain scripts. Cheapest and most reproducible.

```bash
#!/usr/bin/env bash
# ralph_experiment.sh — Hybrid mode: AI for creative steps, scripts for mechanical
set -euo pipefail

BUDGET=20; DRY_RUN=false
for arg in "$@"; do
  case "$arg" in --dry-run) DRY_RUN=true ;; [0-9]*) BUDGET="$arg" ;; esac
done

EXPERIMENT_DIR="$(cd "$(dirname "$0")" && pwd)"
SPEC="$EXPERIMENT_DIR/experiment_spec.json"
TREE="$EXPERIMENT_DIR/tree_state.json"
PROGRESS="$EXPERIMENT_DIR/progress.md"
STEPS_DIR="$EXPERIMENT_DIR/steps"
mkdir -p "$STEPS_DIR"

[[ -f "$SPEC" ]] || { echo "ERROR: $SPEC not found."; exit 1; }
[[ -f "$TREE" ]] || { echo "ERROR: $TREE not found."; exit 1; }
command -v jq &>/dev/null || { echo "ERROR: jq not found."; exit 1; }

if ! $DRY_RUN; then
  [[ -z "${CLAUDECODE:-}" ]] || { echo "ERROR: Cannot run inside Claude Code."; exit 1; }
  command -v claude &>/dev/null || { echo "ERROR: claude not found."; exit 1; }
fi

echo "=== Ralph Loop (Hybrid Mode) === Budget: $BUDGET"
if $DRY_RUN; then
  echo "[OK] All files present."
  jq -r '.orchestration.steps[] | "  \(.name) [\(.mode)]"' "$SPEC"
  exit 0
fi

for ((i=1; i<=BUDGET; i++)); do
  echo ""; echo "=== Iteration $i / $BUDGET ==="
  echo "  Best: $(jq -r '.best_metric // "none"' "$TREE")"
  echo ""

  # --- STEP 1: ORIENT (script — just read and summarize state) ---
  echo "  [orient] Reading state..."
  jq '{
    current_node: .current_node,
    best_node: .best_node,
    best_metric: .best_metric,
    iteration_count: .iteration_count,
    node_count: (.nodes | length)
  }' "$TREE" > "$STEPS_DIR/orient.json"

  # --- STEP 2+3: HYPOTHESIZE + DECIDE (subagent — creative) ---
  echo "  [hypothesize+decide] Running subagent..."
  claude -p "Read experiments/tree_state.json, experiments/progress.md, and experiments/experiment_spec.json.
Based on what has been tried, propose ONE hypothesis. Decide: DEEPEN, BRANCH, or BACKTRACK.
Write to experiments/steps/hypothesis.json: {hypothesis, expected_effect, rationale, operation, parent_node, files_to_change}." \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash"

  # --- STEP 4: IMPLEMENT (subagent — creative) ---
  echo "  [implement] Running subagent..."
  claude -p "Read experiments/steps/hypothesis.json and experiments/experiment_spec.json.
Implement the hypothesis with MINIMAL code changes. Only modify files in scope.changeable.
When done, write experiments/steps/implement.json: {files_changed, summary}." \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash"

  # --- STEP 5: VALIDATE (script — deterministic) ---
  echo "  [validate] Running quality gates..."
  validate_cmd=$(jq -r '.quality_gates.pre_commit | join(" && ")' "$SPEC")
  test_cmd=$(jq -r '.quality_gates.pre_evaluate | join(" && ")' "$SPEC")
  if ! eval "$validate_cmd && $test_cmd"; then
    echo "  [validate] FAILED — asking agent to fix..."
    claude -p "Quality gates failed. Read the errors above and fix the code. Then re-run: $validate_cmd && $test_cmd" \
      --allowedTools "Read,Write,Edit,Glob,Grep,Bash"
    eval "$validate_cmd && $test_cmd" || { echo "  Still failing. Skipping iteration."; continue; }
  fi

  # --- STEP 6: EVALUATE (script — deterministic) ---
  echo "  [evaluate] Running experiment..."
  eval_cmd=$(jq -r '.commands.evaluate' "$SPEC")
  eval "$eval_cmd" 2>&1 | tee "$STEPS_DIR/evaluate_output.log"

  # --- STEP 7: ANALYZE (subagent — creative) ---
  echo "  [analyze] Analyzing results..."
  claude -p "Read experiments/steps/evaluate_output.log and experiments/tree_state.json.
Compare new results to best_node. Did we improve? Why or why not?
Write experiments/steps/analyze.json: {improved, metric_value, delta, explanation, next_suggestion}." \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash"

  # --- STEP 8: UPDATE (script — deterministic) ---
  echo "  [update] Updating state..."
  # Read analysis and update tree
  if [[ -f "$STEPS_DIR/analyze.json" ]]; then
    metric=$(jq -r '.metric_value // null' "$STEPS_DIR/analyze.json")
    improved=$(jq -r '.improved // false' "$STEPS_DIR/analyze.json")
    hypothesis=$(jq -r '.hypothesis // "unknown"' "$STEPS_DIR/hypothesis.json" 2>/dev/null || echo "unknown")

    # Update tree_state.json
    new_node="node_$(printf '%03d' $i)"
    parent=$(jq -r '.current_node' "$TREE")
    jq --arg id "$new_node" --arg parent "$parent" --arg metric "$metric" \
       --arg hyp "$hypothesis" --arg improved "$improved" \
       --arg ts "$(date -Iseconds)" --argjson iter "$i" '
      .iteration_count = $iter |
      .current_node = $id |
      (if $improved == "true" and ($metric | tonumber? // 0) > (.best_metric // 0 | tonumber? // 0)
       then .best_node = $id | .best_metric = ($metric | tonumber? // null)
       else . end) |
      .nodes[$id] = {
        id: $id, parent: $parent, children: [], git_ref: "",
        description: $hyp, hypothesis: $hyp,
        metrics: {primary: ($metric | tonumber? // null)},
        status: "evaluated", created_at: $ts, iteration: $iter
      } |
      .nodes[$parent].children += [$id] |
      .history += [{iteration: $iter, action: (if $improved == "true" then "deepen" else "branch" end),
                     node_id: $id, metric: ($metric | tonumber? // null), timestamp: $ts}]
    ' "$TREE" > "$TREE.tmp" && mv "$TREE.tmp" "$TREE"

    # Append to progress.md
    cat >> "$PROGRESS" <<PROGRESS_EOF

### Iteration $i — $new_node (child of $parent)
**Hypothesis:** $hypothesis
**Result:** metric=$metric, improved=$improved
**Analysis:** $(jq -r '.explanation // "N/A"' "$STEPS_DIR/analyze.json")
**Next:** $(jq -r '.next_suggestion // "N/A"' "$STEPS_DIR/analyze.json")

---
PROGRESS_EOF

    # Git commit
    git add -A && git commit -m "experiment: $hypothesis" --no-verify 2>/dev/null || true
  fi

  grep -q "EXPERIMENT_COMPLETE" "$PROGRESS" 2>/dev/null && { echo "=== COMPLETE ==="; break; }
done

echo ""
echo "=== Final Results ==="
echo "  Best node: $(jq -r '.best_node' "$TREE")"
echo "  Best metric: $(jq -r '.best_metric // "none"' "$TREE")"
echo "  Iterations: $(jq -r '.iteration_count' "$TREE") / $BUDGET"
```

**Choose the right mode:**

| Mode | AI calls/iter | Cost/iter | Control | Best for |
|------|--------------|-----------|---------|----------|
| Monolith | 1 | $0.50-2 | Low | Quick exploration |
| Subagent | 1 per step | $2-5 | High | Complex experiments |
| Hybrid | 3-4 (creative only) | $1-3 | Medium | Most ML/DS workflows |
| Script | 0 (pre-defined) | $0 | Total | Hyperparameter sweeps |

---

## Phase 3: Run the Experiment Loop

### Iteration Workflow (What Each Iteration Does)

```
┌─────────────────────────────────────────────────┐
│ 1. ORIENT                                       │
│    Read: experiment_spec.json                    │
│    Read: tree_state.json (current node, best)    │
│    Read: progress.md (learnings from all iters)  │
│    Read: git log --oneline -20                   │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│ 2. HYPOTHESIZE                                  │
│    Based on learnings, form a testable bet:      │
│    "Adding feature X should improve metric by Y  │
│     because Z was observed in iteration N"       │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│ 3. DECIDE: Tree Operation                       │
│    ┌─────────┐ ┌─────────┐ ┌──────────────┐    │
│    │ DEEPEN  │ │ BRANCH  │ │  BACKTRACK   │    │
│    │(refine) │ │ (new    │ │ (go back to  │    │
│    │ current │ │  idea)  │ │  best node)  │    │
│    └─────────┘ └─────────┘ └──────────────┘    │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│ 4. IMPLEMENT                                    │
│    Make minimal code changes                     │
│    (only files in scope.changeable)              │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│ 5. VALIDATE                                     │
│    Run: lint, typecheck, tests                   │
│    Run: leakage check (if configured)            │
│    If FAIL → fix and retry (max 3 attempts)      │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│ 6. EVALUATE                                     │
│    Run experiment command                        │
│    Parse metrics from output                     │
│    Compare to best_node metrics                  │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│ 7. ANALYZE                                      │
│    Did we improve? Why or why not?               │
│    What should the next iteration try?           │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│ 8. UPDATE STATE                                 │
│    Add node to tree_state.json                   │
│    Update best_node if improved                  │
│    Append iteration summary to progress.md       │
│    Git commit: "experiment: <hypothesis>"        │
│    Check completion: metric >= threshold? → DONE │
└─────────────────────────────────────────────────┘
```

### Tree Decision Logic

```
IF first iteration:
  → DEEPEN from baseline (node_000)

ELIF last iteration improved:
  → DEEPEN from current (continue what's working)

ELIF last 2 iterations worsened:
  → BACKTRACK to best_node, then BRANCH (try something different)

ELIF current approach stalled (3+ iters, <1% improvement):
  → BRANCH from best_node (fundamentally different approach)

ELSE:
  → DEEPEN from current (keep exploring)
```

### Metrics Parsing

After running the evaluation command, parse metrics from the output. Common patterns:

```python
# Pattern 1: JSON output
# Command outputs: {"roi": 0.035, "sharpe": 1.2, "max_drawdown": -0.15}
import json
metrics = json.loads(output)

# Pattern 2: CSV/table output
# Parse from summary.csv or stdout table

# Pattern 3: Log file
# Grep for metric patterns in log output
```

The agent should be flexible about parsing — read the project's existing metric output format.

---

## Phase 4: Completion & Reporting

### When the Loop Ends

1. **Success** (threshold met):
   - Run test set evaluation ONCE
   - Record test metrics in tree_state.json
   - Generate final report
   - Commit: `experiment-complete: <summary>`

2. **Budget exhausted**:
   - Report best result found
   - Suggest next steps (more budget, different approach, human review)
   - Do NOT run test set (save it for when we have a better candidate)

3. **User interrupt**:
   - Save current state (tree + progress)
   - Can resume later with `/ralph-loop resume`

### Final Report Template

Append to `progress.md`:

```markdown
## Final Report

### Summary
- **Objective:** <from spec>
- **Result:** SUCCESS | BUDGET_EXHAUSTED | STOPPED
- **Iterations:** N / budget
- **Best node:** node_XXX
- **Best validation metric:** <value> (threshold: <value>)
- **Test metric:** <value> (only if threshold met)

### Tree Statistics
- Total nodes explored: N
- Deepening operations: N
- Branching operations: N
- Backtrack operations: N
- Nodes rejected: N

### Key Learnings
1. <Most impactful finding>
2. <Second most impactful>
3. <Pattern discovered>

### What Worked
- <Approach that improved metrics>

### What Didn't Work
- <Approach that hurt metrics and why>

### Recommended Next Steps
1. <If more budget available>
2. <Alternative approaches not yet tried>
3. <Data improvements that could help>
```

---

## Sports Betting Example (This Repository)

For this sportsmarket repository, the Ralph loop maps to:

### Experiment Types

| Type | Run Command | Metric | Threshold |
|------|-------------|--------|-----------|
| Feature engineering | `./just sports-baseline nba ...` | ROI | > 3% |
| Model architecture | `./just sports-baseline-models nba ...` | Sharpe | > 1.5 |
| Hyperparameter sweep | `./just baselines --regime bull --hyperopt` | Hit rate | > 56% |
| New data integration | `./just ingest-all && ./just sports-baseline nba ...` | Coverage | > 90% odds JOIN |

### Recommended Mode: Hybrid

For sportsmarket, the hybrid mode works best because:
- **VALIDATE** and **EVALUATE** are well-defined scripts (`./just lint`, `./just sports-baseline`)
- **HYPOTHESIZE** and **IMPLEMENT** need creative reasoning (which features to add, how to change models)
- **UPDATE** is mechanical (update JSON, git commit)

### Quality Gates

```json
{
  "pre_commit": ["./just lint", "./just typecheck"],
  "pre_evaluate": ["./just test"],
  "leakage_check": "./uv run pytest tests/test_backtesting/test_sports_leakage.py -v"
}
```

---

## Implementation Notes

### Adapting to Any Repository

This skill is designed to be portable. When invoked in a new repository:

1. **Phase 1** discovers the project's conventions, tools, and ML workflow
2. **Phase 1.4-1.5** interactively designs the loop steps with the user
3. **Phase 2** creates infrastructure files tailored to what was discovered + chosen mode
4. **Phase 3** uses the project's own commands and metrics

### Key Design Decisions

1. **JSON for machine state, Markdown for agent state**: `tree_state.json` is parsed programmatically by bash; `tasks.md`, `progress.md`, `plan.md` are read by the LLM. **Prefer Markdown over JSON for anything an agent reads** — it enables richer reasoning, qualitative priority judgments, and free-form context that JSON cannot express. See Lesson 31.
2. **Git commits as checkpoints**: Every evaluated node gets a commit, enabling `git checkout` to any previous state
3. **Fresh context per iteration**: The outer loop spawns a new Claude instance each iteration, passing only the state files
4. **Immutable test set**: The test set evaluation command exists in the spec but is ONLY run at the very end when the primary threshold is met on validation
5. **Quality gates before evaluation**: Never evaluate a broken experiment — fix it first or reject the node
6. **Step-level JSON handoffs**: In subagent/hybrid mode, each step writes a `step_*.json` file that the next step reads. This provides clean interfaces between steps and enables debugging (inspect any step's output).
7. **`claude -p` not `claude --print`**: The `-p` flag accepts a positional prompt; `--print` requires stdin. This is a critical gotcha.

### Critical Lessons from Production Use

**These are ESSENTIAL gotchas learned from real deployments. Include these in every Ralph loop implementation:**

**45 lessons total (+ 6 opencode sub-gotchas in Lesson 42)** covering:
- **Lessons 1-13**: Core infrastructure (CLI flags, environment, validation, rate limits, resumability)
- **Lessons 14-16**: Bash scripting gotchas (`set -e`, `local`, jq syntax)
- **Lesson 17**: Architecture decision (task queue vs fixed-step)
- **Lessons 18-19**: Task queue resilience (command substitution, peek-execute-remove)
- **Lesson 20**: Shell JSON escaping for `jq --argjson`
- **Lesson 21**: Monitoring subagent progress with debug logs
- **Lesson 22**: Task queue deduplication to prevent wasted work
- **Lesson 23**: Safe JSON building with `jq -n`
- **Lesson 24**: FIX tasks must have higher priority than VALIDATE
- **Lesson 25**: Generic task executor for unknown task types
- **Lesson 26**: Extract all variables before use with `set -u`
- **Lesson 27**: `setsid` for process group isolation (security hooks + watchdogs)
- **Lesson 28**: Security wrapper variable names must match exactly (false-positive kill gotcha)
- **Lesson 29**: Exit code 124 = timeout, not crash — calibrate step timeouts generously
- **Lesson 30**: Finalize step (Step 3) is the compound engineering heartbeat
- **Lesson 31**: Prefer Markdown state over JSON for agent-readable state
- **Lesson 32**: One reviewer pass, then move on
- **Lesson 33**: Inject a hygiene task every N cycles (errors + tech debt + ML rigour)
- **Lesson 34**: Heartbeat + auto-retry for silent API hangs (exit 124 + log < 2KB = safe retry)
- **Lesson 35**: Two-frequency meta-loop — frequent hygiene checks + infrequent self-improvement of the Ralph loop itself
- **Lesson 36**: Verbose ON by default + model tiering (Opus for planning, Sonnet for execution)
- **Lesson 37**: Force non-interactive/headless session for every tool call — Claude and others
- **Lesson 38**: `set -euo pipefail` + `grep` silent-kill gotcha — always add `|| fallback` to grep in state-reading code
- **Lesson 39**: Live API ping in the same test run, using the exact same `run_subagent` construction, with cheapest model — validates the full stack before the real loop starts
- **Lesson 40**: Mandatory dry-run + full roundtrip test immediately after scaffolding — never hand the loop to the operator untested
- **Lesson 41**: Haiku for mechanical steps (orient + finalize) — use `MODEL_LIGHT` variable
- **Lesson 42**: OpenCode as alternative execute engine — `opencode run` vs `claude -p` differences and gotchas; XDG_DATA_HOME isolation breaks auth (gotchas 8–13 added 2026-04-05)
- **Lesson 43**: Permanent Mathlib/library gap tasks — never just "retry in N cycles"
- **Lesson 44**: Pre-digest large state files before the orient step — 11x compression, bash not LLM
- **Lesson 45**: Rate-limit detection must be gated on step failure — exit code is authoritative, log text is diagnostic

**Most critical for task queue implementations:** Lessons 14-26 (all discovered during ralph_datasources_v2.sh development)
**Most critical for subagent orchestration with security wrappers:** Lessons 27-29
**Most critical for loop design philosophy:** Lessons 30-45

---

#### 1. **CLAUDECODE Environment Variable (Critical!)**

**Problem:** The `claude` CLI refuses to run if `CLAUDECODE` environment variable is set (prevents nested sessions).

**Impact:** If the user's terminal was spawned from Claude Code (integrated terminal), it inherits `CLAUDECODE` and all `claude -p` calls will fail silently.

**Solution:** Always use `env -u CLAUDECODE` before `claude` calls:

```bash
# WRONG - will fail if run from Claude Code terminal
claude -p "$prompt" --model sonnet

# CORRECT - unsets CLAUDECODE before calling claude
env -u CLAUDECODE claude -p "$prompt" --model sonnet
```

**Script check:**
```bash
# Add this to dry-run validation
if ! $DRY_RUN; then
  # Test that claude works with CLAUDECODE unset
  env -u CLAUDECODE claude --help >/dev/null 2>&1 || {
    echo "ERROR: claude CLI not working even with CLAUDECODE unset"
    exit 1
  }
fi
```

#### 2. **Output Validation: Check JSON Files, Not Stdout**

**Problem:** `claude -p` in non-interactive mode does NOT print full conversation to stdout. The terminal log may be empty even when working correctly.

**Impact:** You cannot validate success by checking if `output.log` has content. This leads to false "stuck" diagnoses.

**Solution:** Validate by checking if the **expected output file** was created:

```bash
# WRONG - validates stdout (unreliable)
if claude -p "$prompt" 2>&1 | tee log.txt; then
  echo "Success"
fi

# CORRECT - validates the file the prompt was instructed to write
claude -p "$prompt" 2>&1 | tee log.txt
if [[ -f "$expected_output_file" ]]; then
  echo "✅ Step completed (output: $expected_output_file)"
else
  echo "❌ Step failed (no output at: $expected_output_file)"
fi
```

**Prompt design:** Always have prompts explicitly state where to write output:
```
Read X, Y, Z. Analyze them. Write results to experiments/steps/orient.json with fields: {...}
```

#### 3. **Critical Flag Name: --dangerously-skip-permissions (NOT camelCase!)**

⚠️ **CRITICAL:** The correct flag name has **hyphens**, not camelCase!

**WRONG (will fail with "unknown option" error):**
```bash
claude --dangerouslySkipApproval  # ❌ This doesn't exist!
```

**CORRECT:**
```bash
claude --dangerously-skip-permissions  # ✅ Kebab-case with hyphens
```

**Problem:** Documentation and examples often show camelCase version, but the actual CLI uses kebab-case.

**Solution:** Always use `--dangerously-skip-permissions` with hyphens.

**Required flags for non-interactive mode:**

```bash
claude --model sonnet \                      # Specify model (cost control)
  --dangerously-skip-permissions \            # Skip permission prompts (HYPHENS!)
  --allowedTools "Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch,Skill"
```

**Why Sonnet:** For long-running autonomous loops (data engineering, scraper implementation), Sonnet is 2-3x cheaper than Opus with comparable quality. Reserve Opus for complex research/modeling.

**Verify the flag exists:**
```bash
env -u CLAUDECODE claude --help | grep "dangerously-skip-permissions"
# Should show: --dangerously-skip-permissions
```

#### 4. **Use Stdin, Not -p Flag (More Reliable for Multi-line Prompts)**

**Problem:** `claude -p "$prompt"` doesn't reliably handle multi-line prompts. Shell escaping breaks, special characters cause issues, and prompts may fail silently.

**Impact:** Prompts with newlines, quotes, or special characters will fail or behave unpredictably.

**Solution:** Write prompt to file and use stdin:

```bash
# PROBLEMATIC - breaks with multi-line prompts
claude -p "$prompt" --model sonnet

# BETTER - write to file first
echo "$prompt" > prompt.txt
claude --model sonnet < prompt.txt

# BEST - write, verify, then use
prompt_file="steps/orient_prompt.txt"
echo "$prompt" > "$prompt_file"
echo "Prompt saved: $prompt_file ($(wc -c < "$prompt_file") bytes)"
claude --model sonnet --dangerously-skip-permissions < "$prompt_file"
```

**Why this works:**
- No shell escaping issues
- Handles newlines, quotes, special characters
- Can inspect the prompt file for debugging
- More reliable across different shell environments

**Real-world example:**
```bash
run_subagent() {
  local step_name="$1"
  local prompt="$2"
  local output_file="$3"

  # Write prompt to file
  local prompt_file="steps/${step_name}_prompt.txt"
  echo "$prompt" > "$prompt_file"

  # Run via stdin
  timeout 30m env -u CLAUDECODE claude --model sonnet \
    --dangerously-skip-permissions \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    < "$prompt_file" \
    2>&1 | tee "steps/${step_name}_output.log"

  # Validate by checking output file
  if [[ -f "$output_file" ]]; then
    echo "✅ Success"
  else
    echo "❌ Failed"
  fi
}
```

#### 5. **Test Claude CLI Before Running Loop**

**Problem:** The loop may fail silently if `claude` CLI doesn't work on the user's system.

**Solution:** Create a comprehensive test script:

```bash
# Test 1: Check flag name exists
if ! env -u CLAUDECODE claude --help 2>&1 | grep -q "dangerously-skip-permissions"; then
  echo "❌ Your claude CLI version doesn't support --dangerously-skip-permissions"
  echo "   Try updating: claude-code update"
  exit 1
fi

# Test 2: Test simple prompt via stdin
if $DRY_RUN; then
  echo "Testing claude CLI..."
  TEST_FILE="/tmp/ralph_test_$$.json"

  # Test via stdin (recommended approach)
  echo 'Use the Write tool to create /tmp/ralph_test_'"$$"'.json with {"test":true}' | \
    timeout 30s env -u CLAUDECODE claude --model sonnet \
      --dangerously-skip-permissions \
      --allowedTools "Write" \
      2>&1 > /tmp/claude_test.log

  if [[ -f "$TEST_FILE" ]]; then
    echo "✅ claude CLI working"
    rm -f "$TEST_FILE"
  else
    echo "❌ claude CLI test failed"
    cat /tmp/claude_test.log
    exit 1
  fi
fi
```

#### 6. **Timeout Configuration**

**Problem:** Some steps (IMPLEMENT, DESIGN) can take much longer than others.

**Solution:** Use per-step timeouts, not global timeout:

```bash
run_subagent "orient" "$PROMPT" "orient.json" 5    # 5 minutes
run_subagent "design" "$PROMPT" "design.json" 20   # 20 minutes
run_subagent "implement" "$PROMPT" "implement.json" 60  # 60 minutes
```

**Default:** 30 minutes is reasonable for most steps.

#### 7. **Error Output on Failure**

**Problem:** When a step fails, you need to see WHY it failed.

**Solution:** Print last 20 lines of the log on failure:

```bash
if [[ ! -f "$expected_output" ]]; then
  echo "❌ Step failed. Last 20 lines of log:"
  tail -20 "$STEPS_DIR/${step_name}_output.log"
  return 1
fi
```

#### 8. **Resume Support**

**Problem:** Long-running loops get interrupted (Ctrl+C, network issues, system restarts).

**Solution:** Track iteration count in `tree_state.json` and support `--resume`:

```bash
if $RESUME; then
  LAST_ITER=$(jq -r '.iteration_count' "$TREE")
  START_ITERATION=$((LAST_ITER + 1))
  echo "Resuming from iteration $START_ITERATION"
fi
```

**Clean state between iterations:**
```bash
# At start of each iteration, remove previous step outputs
rm -f "$STEPS_DIR"/*.json "$STEPS_DIR"/*_output.log
```

#### 9. **Cost Tracking**

**Problem:** Long autonomous loops can rack up unexpected API costs.

**Solution:** Track estimated cost in `tree_state.json`:

```json
{
  "total_cost_usd": 0,
  "cost_per_iteration": []
}
```

**Update after each iteration:**
```python
# Rough estimate: Sonnet ~$3/million input tokens, ~$15/million output
# Typical subagent call: 10K input, 2K output = $0.03 + $0.03 = $0.06
# 8 subagent calls per iteration = ~$0.50 per iteration
```

**Budget check:**
```bash
TOTAL_COST=$(jq -r '.total_cost_usd' "$TREE")
if (( $(echo "$TOTAL_COST > $MAX_COST" | bc -l) )); then
  echo "Budget exceeded ($TOTAL_COST > $MAX_COST)"
  exit 1
fi
```

#### 10. **Debugging Support**

**Problem:** When a step fails mysteriously, you need visibility.

**Solution:** Add verbose mode — **ON by default** (see Lesson 36 for the full rationale). Quiet is the opt-in:

```bash
# Verbose ON by default — operator sees everything unattended
VERBOSE=true
for arg in "$@"; do
  case "$arg" in --quiet|-q) VERBOSE=false ;; esac
done

if $VERBOSE; then
  set -x  # Print each command before executing
fi
```

**Log all subagent calls:**
```bash
echo "[$(date -Iseconds)] Running: $step_name" >> "$EXPERIMENT_DIR/audit.log"
```

#### 11. **Graceful Shutdown**

**Problem:** Ctrl+C leaves the tree state inconsistent.

**Solution:** Trap signals and save state:

```bash
trap 'echo "Interrupted - state saved in tree_state.json"; exit 130' INT TERM

# Or: auto-save state after each step completes
```

#### 12. **Rate Limit Handling (Critical for Long Runs!)**

**Problem:** Long-running loops hit API rate limits and fail. For Claude API, limits reset at specific times (e.g., "1pm Europe/Prague").

**Impact:** Loop fails in the middle of the night when you're not monitoring, wasting the iteration.

**Solution:** Detect rate limit messages, parse reset time, wait automatically:

```bash
# Run claude and check for rate limits
while [[ $retry_count -lt $max_retries ]]; do
  claude --model sonnet < prompt.txt 2>&1 | tee output.log

  # Check for rate limit
  if grep -q "You've hit your limit" output.log; then
    # Extract reset time (e.g., "resets 1pm (Europe/Prague)")
    reset_info=$(grep "resets" output.log | head -1)
    reset_time=$(echo "$reset_info" | sed -n 's/.*resets \([0-9]\+[ap]m\).*/\1/p')

    # Calculate wait time
    current_hour=$(date +%H)
    reset_hour=$(echo "$reset_time" | sed 's/[ap]m//')
    [[ "$reset_time" =~ "pm" && "$reset_hour" != "12" ]] && reset_hour=$((reset_hour + 12))

    wait_minutes=$(( (reset_hour - current_hour) * 60 + 5 ))  # +5 min buffer
    [[ $wait_minutes -lt 0 ]] && wait_minutes=$((wait_minutes + 1440))  # Next day

    echo "⏱️  Rate limit hit! Waiting $wait_minutes minutes until ${reset_time}..."

    # Wait with progress
    for ((i=0; i<wait_minutes; i++)); do
      remaining=$((wait_minutes - i))
      printf "\r⏳ %d minutes until reset..." $remaining
      sleep 60
    done

    echo "✅ Retrying after rate limit reset..."
    ((retry_count++))
    continue  # Retry
  fi

  break  # No rate limit, continue normally
done
```

**User experience:**
```
⏱️  Rate limit hit! Parsing reset time...
   You've hit your limit · resets 1pm (Europe/Prague)
   Current time: 09:45
   Reset time: 1pm (hour: 13)
   Waiting 198 minutes until reset...

   You can:
   - Let it wait automatically (recommended)
   - Press Ctrl+C to stop and resume later with --resume

   ⏳ Waiting... 197 minutes remaining (reset at 1pm)
   [progress updates every minute]
   ✅ Rate limit should be reset now, retrying...
```

**Benefits:**
- Overnight runs don't fail
- No manual intervention needed
- Loop continues automatically after reset
- User can still Ctrl+C if desired

**Max retries:** Set to 5 to handle multiple rate limit periods in very long runs.

#### 13. **Auto-Resume Detection for Incomplete Runs (Critical for Reliability!)**

**Problem:** Users forget to use `--resume` flag after interruptions (Ctrl+C, rate limits, crashes). Restarting from iteration 1 wastes previous work.

**Impact:** If iteration 3 of 15 is interrupted, user may accidentally restart from scratch, losing hours of work.

**Solution:** Detect incomplete runs at script startup and prompt user for action:

```bash
# At script start, before main loop
if [[ -f "$TREE" ]] && ! $RESUME && [[ "$1" != "--fresh" ]]; then
  LAST_ITER=$(jq -r '.iteration_count' "$TREE")
  TOTAL_NODES=$(jq -r '.nodes | length' "$TREE")

  if [[ $LAST_ITER -gt 0 ]]; then
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  Incomplete Run Detected!                                    ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Found previous run:"
    echo "  - Last iteration: $LAST_ITER"
    echo "  - Nodes explored: $TOTAL_NODES"
    echo "  - Best metric: $(jq -r '.best_metric // "none"' "$TREE")"
    echo ""

    # Show recent history
    echo "Last 3 iterations:"
    jq -r '.history[-3:] | .[] | "  \(.iteration): \(.node_id) - \(.action)"' "$TREE"
    echo ""

    # Prompt user
    read -p "Do you want to RESUME from iteration $((LAST_ITER + 1))? [Y/n] " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
      echo "✅ Resuming from iteration $((LAST_ITER + 1))"
      START_ITER=$((LAST_ITER + 1))
    else
      read -p "Start FRESH (will overwrite current state)? [y/N] " -n 1 -r
      echo ""

      if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Backup old state
        BACKUP_DIR="experiments/backups/$(date +%Y%m%d_%H%M%S)"
        mkdir -p "$BACKUP_DIR"
        cp "$TREE" "$BACKUP_DIR/tree_state.json"
        cp "$PROGRESS" "$BACKUP_DIR/progress.md" 2>/dev/null || true
        echo "📦 Backed up old state to: $BACKUP_DIR"
        echo "✅ Starting fresh from iteration 1"
        # Reset tree state
        jq '.iteration_count = 0 | .current_node = "node_000" | .history = []' "$TREE" > "$TREE.tmp"
        mv "$TREE.tmp" "$TREE"
        START_ITER=1
      else
        echo "❌ Cancelled - exiting"
        exit 0
      fi
    fi
  fi
fi
```

**Update ORIENT Step to Understand Resumption:**

The ORIENT step prompt should detect resumption context:

```json
{
  "prompt": "Read experiments/experiment_spec.json, experiments/tree_state.json, experiments/progress.md.

IMPORTANT: If resuming (iteration_count > 0), understand:
- What was attempted in the last iteration and whether it completed
- Whether to retry the same task or move to the next one
- What failures occurred and their root causes

Write summary to experiments/steps/orient.json with fields:
- sources_completed: list of successfully completed items
- sources_failed: list of failed attempts with reasons
- sources_remaining: list of not-yet-attempted items
- current_iteration: int
- is_resuming: bool (true if iteration_count > 0)
- last_attempt: {item_id: string, status: string, reason: string} (if resuming)
- next_action: string (should we retry the failed item or move on?)"
}
```

**SELECT Step Can Make Smart Decisions:**

With resumption context, SELECT can:
- **Retry transient failures** (rate limits, network errors)
- **Skip fundamental failures** (API doesn't exist, wrong schema)
- **Continue to new items** if previous succeeded

**User Experience:**

```
$ ./experiments/ralph_loop.sh 15

╔══════════════════════════════════════════════════════════════╗
║  Incomplete Run Detected!                                    ║
╚══════════════════════════════════════════════════════════════╝

Found previous run:
  - Last iteration: 3
  - Nodes explored: 4
  - Best metric: 0.85

Last 3 iterations:
  1: node_001 - deepen
  2: node_002 - deepen
  3: node_003 - branch

Do you want to RESUME from iteration 4? [Y/n] y

✅ Resuming from iteration 4

════════════════════════════════════════════════════════════════
  ITERATION 4 / 15
════════════════════════════════════════════════════════════════
```

**Benefits:**
- **User-friendly:** No need to remember `--resume` flag
- **Safe:** Offers to backup state before overwriting
- **Transparent:** Shows current state before prompting
- **Flexible:** User can resume, start fresh, or cancel

**Implementation:**
```bash
# Support explicit flags too
RESUME=false; FRESH=false
for arg in "$@"; do
  case "$arg" in
    --resume) RESUME=true ;;
    --fresh) FRESH=true ;;
  esac
done

# If explicit flag, skip prompt
if $RESUME; then
  START_ITER=$(($(jq -r '.iteration_count' "$TREE") + 1))
elif $FRESH; then
  # Backup and reset
fi
```

#### 14. **Bash Arithmetic with `set -e` (Critical Gotcha!)**

**Problem:** Using `((var++))` when var=0 causes script to exit with `set -e`.

**Root cause:** In bash, arithmetic expansion `((expr))` returns the **result value** as exit code:
- `((0))` returns exit code 1 (FALSE)
- `((1))` returns exit code 0 (SUCCESS)

When `task_count=0`, `((task_count++))` evaluates to 0 **before** incrementing, which is FALSE, triggering `set -e` to exit!

**Impact:** Loop starts with `task_count=0`, first `((task_count++))` causes immediate exit. Script appears to hang/exit mysteriously.

**Solution:** Use explicit arithmetic assignment instead:

```bash
# WRONG - exits when var is 0
while [[ $count -lt $budget ]]; do
  ((count++))  # ❌ Exits on first iteration when count=0
  ...
done

# CORRECT - safe with set -e
while [[ $count -lt $budget ]]; do
  count=$((count + 1))  # ✅ Always succeeds
  ...
done

# ALSO CORRECT - disable set -e for this line
while [[ $count -lt $budget ]]; do
  ((count++)) || true  # ✅ Prevents exit on failure
  ...
done
```

**Testing:**
```bash
# Test arithmetic behavior
set -e
count=0
((count++))  # Script exits here!
echo "This never prints"

# Versus
set -e
count=0
count=$((count + 1))  # Script continues
echo "This prints: $count"  # Output: This prints: 1
```

**Why this matters:** Very common pattern in loops, fails silently with `set -e`, hard to debug.

#### 15. **`local` Variable Scope (Syntax Error)**

**Problem:** Using `local` keyword outside of functions causes syntax error.

**Impact:** Script fails with: `bash: local: can only be used in a function`

**Solution:** Use `local` only inside functions, regular assignment in main script:

```bash
# WRONG - in main script body
task=$(pop_task)
local exit_code=$?  # ❌ Syntax error

# CORRECT - in main script body
task=$(pop_task)
exit_code=$?  # ✅ Regular variable

# CORRECT - inside function
execute_task() {
  local task="$1"  # ✅ local works here
  local exit_code=$?  # ✅ local works here
  ...
}
```

**Why this is confusing:** Many scripting guides use `local` everywhere, but it only works in functions.

#### 16. **jq `del()` Syntax for Queue Operations**

**Problem:** Can't use `del()` with filter expressions in jq.

**Wrong approach:**
```bash
# ❌ INVALID - del() doesn't work with filter expressions
jq 'del(.queue[0] | sort_by(-.priority) | .[0])' tasks.json

# This tries to delete a path, but the expression is a value, not a path
```

**Correct approach:** Filter the array to exclude the item:

```bash
# ✅ CORRECT - filter out item by ID
pop_task() {
  # Get highest priority task
  local task_json=$(jq -c '.queue | sort_by(-.priority) | .[0]' "$TASKS")

  if [[ "$task_json" == "null" || "$task_json" == "" ]]; then
    return 1
  fi

  # Get task ID and remove from queue by filtering
  local task_id=$(echo "$task_json" | jq -r '.id')
  jq --arg id "$task_id" '.queue = [.queue[] | select(.id != $id)]' "$TASKS" > "$TASKS.tmp"
  mv "$TASKS.tmp" "$TASKS"

  echo "$task_json"
  return 0
}
```

**Alternative approaches:**

```bash
# Using del() with index (requires knowing exact index)
jq '.queue |= del(.[0])' tasks.json  # Deletes first item

# Using array slicing
jq '.queue |= .[1:]' tasks.json  # Removes first item

# For priority queue: sort, take first, filter out by ID (most robust)
jq --arg id "$task_id" '.queue = [.queue[] | select(.id != $id)]' tasks.json
```

**Why the filter approach is best for queues:**
- Works even if queue is modified concurrently
- Doesn't depend on index position
- Handles the case where item might not exist
- More explicit about what's being removed

#### 17. **Task Queue vs Fixed-Step Architecture**

**Problem:** Fixed iteration steps continue even when validation fails.

**Real example from production:**
```bash
# Fixed-step loop (OLD):
VALIDATE ❌ (tests fail)
  → "⚠️ marking as failed and continuing"
  → SCRAPE ✅ (runs anyway with broken scraper!)
  → INTEGRATE ✅ (deploys broken code to production!)
  → Next iteration starts (broken scraper never gets fixed)
```

**Solution:** Task queue with dynamic priority:

```bash
# Task queue (NEW):
VALIDATE ❌ (tests fail)
  → Insert FIX task at priority 98 (higher than SCRAPE at 70)
  → FIX executes next (due to priority)
  → FIX completes → adds VALIDATE at priority 95
  → VALIDATE again
  → Still fails? → another FIX at priority 98
  → Loop continues until tests pass or max retries hit
  → Only then adds SCRAPE (priority 70)
```

**Key architectural insight:**

Don't use fixed iteration sequences when some steps can fail and need retries. Use a priority queue instead:

```json
{
  "queue": [
    {"type": "fix", "priority": 98},
    {"type": "validate", "priority": 95},
    {"type": "scrape", "priority": 70},
    {"type": "integrate", "priority": 60}
  ]
}
```

**Benefits:**
- Failed validation **blocks** forward progress
- Fix tasks **jump to front** of queue
- **FIX → VALIDATE loop** continues until pass
- Side tasks can be **inserted dynamically**
- Critical issues get **priority 99** (absolute front)

**When to use each:**

| Architecture | Use When |
|--------------|----------|
| **Fixed-step** | Steps always succeed, simple linear workflow, exploration/research |
| **Task queue** | Steps can fail, need validation gates, engineering/implementation |

**Implementation pattern:**

```bash
# Instead of:
for iteration in 1..N:
  step1 || warn
  step2 || warn  # runs even if step1 failed!
  step3 || warn

# Use:
while queue not empty:
  task = pop_highest_priority()
  case task.type:
    validate:
      if failed: add_task("fix", priority=98)
      if passed: add_task("integrate", priority=60)
```

See `experiments/TASK_QUEUE_ARCHITECTURE.md` for complete implementation guide.

#### 18. **`set -e` with Command Substitution (Critical Gotcha!)**

**Problem:** When capturing command output with `var=$(command)`, if the command returns non-zero, `set -e` exits the script **before** you can check `$?`.

**Root cause:** Command substitution inherits `set -e`, and a non-zero exit code triggers immediate script termination.

**Impact:** Cannot check if a function succeeded or failed when using command substitution. Script exits mysteriously when trying to handle failure gracefully.

**Real example from production:**

```bash
set -e

# Pop task from queue (returns 1 if queue empty)
pop_task() {
  local task=$(jq '.queue[0]' tasks.json)
  if [[ "$task" == "null" ]]; then
    return 1  # Queue empty
  fi
  echo "$task"
  return 0
}

# Main loop
task=$(pop_task)  # ❌ Script exits here if queue empty!
exit_code=$?      # ❌ Never reached
if [[ $exit_code -ne 0 ]]; then
  echo "Queue empty"  # ❌ Never prints
fi
```

**Why this is confusing:**

Without `set -e`, this pattern works perfectly:
```bash
# Works fine WITHOUT set -e
task=$(pop_task)
if [[ $? -ne 0 ]]; then
  echo "Queue empty"  # ✅ Prints correctly
fi
```

But with `set -e`, the script exits before the `if` statement.

**Solution 1: Temporarily disable `set -e`**

```bash
# ✅ CORRECT - disable set -e around the command
set +e
task=$(pop_task)
exit_code=$?
set -e

if [[ $exit_code -ne 0 ]]; then
  echo "Queue empty"  # ✅ Now works
fi
```

**Solution 2: Use `|| true` to prevent exit**

```bash
# ✅ CORRECT - prevent exit with || true
task=$(pop_task) || true

# Check if task is empty/null instead of exit code
if [[ -z "$task" || "$task" == "null" ]]; then
  echo "Queue empty"
fi
```

**Solution 3: Don't use command substitution for control flow**

```bash
# ✅ CORRECT - call directly and check exit code
if pop_task > /tmp/task.txt; then
  task=$(cat /tmp/task.txt)
  echo "Got task: $task"
else
  echo "Queue empty"
fi
```

**Best practice for Ralph loops:**

When you need to check if a function succeeded:

```bash
# Pattern: Function that returns data + exit code
pop_task() {
  local task=$(jq '.queue[0]' "$TASKS")
  if [[ "$task" == "null" ]]; then
    echo ""  # Return empty string
    return 1
  fi
  echo "$task"
  return 0
}

# Safe usage with set -e
set +e  # Disable
task=$(pop_task)
exit_code=$?
set -e  # Re-enable

if [[ $exit_code -ne 0 ]]; then
  # Handle empty queue
  add_task "orient" 100 "Repopulate queue"
  continue
fi

# Process task
execute_task "$task"
```

**Testing:**

```bash
# Demonstrate the issue
cat > test_set_e.sh <<'EOF'
#!/bin/bash
set -e

may_fail() {
  return 1
}

echo "Test 1: Without protection"
result=$(may_fail)  # Script exits here!
echo "This never prints"
EOF

chmod +x test_set_e.sh
./test_set_e.sh
# Output: Script exits after "Test 1", no further output

# Fixed version
cat > test_set_e_fixed.sh <<'EOF'
#!/bin/bash
set -e

may_fail() {
  return 1
}

echo "Test 1: With set +e protection"
set +e
result=$(may_fail)
exit_code=$?
set -e

echo "Exit code: $exit_code"
echo "This prints!"
EOF

chmod +x test_set_e_fixed.sh
./test_set_e_fixed.sh
# Output:
#   Test 1: With set +e protection
#   Exit code: 1
#   This prints!
```

**Why this matters:**

Very common pattern in scripts:
- Popping from queues (may be empty)
- Reading files (may not exist)
- Parsing JSON (may be invalid)
- API calls (may fail)

All need graceful error handling, which `set -e` + command substitution breaks.

**Related gotcha:** `set -e` is inherited by subshells and command substitutions, so this affects:
- `var=$(command)`
- `result=$({ complex; pipeline; })`
- Process substitution in some cases

**Quick reference:**

| Pattern | With `set -e` | Behavior |
|---------|---------------|----------|
| `var=$(cmd)` where cmd fails | ❌ Exits | Script terminates |
| `var=$(cmd) \|\| true` | ✅ Works | Continues, var empty |
| `set +e; var=$(cmd); set -e` | ✅ Works | Continues, can check $? |
| `if cmd > file; then ...` | ✅ Works | if handles the failure |

#### 19. **Resilient Task Queue: Peek-Execute-Remove Pattern** (Critical for Resumability!)

**Problem:** Removing tasks from the queue **before** execution means failures or interruptions lose that work forever.

**Anti-pattern:**
```bash
# ❌ BAD: Pop (remove) task before executing
task=$(pop_task)  # Task removed from queue immediately
execute_task()    # If this fails or Ctrl+C happens, task is LOST!
```

**Impact:**
- Interrupted runs lose progress
- Failed tasks disappear instead of being retried
- Can't resume from where you left off

**Solution: Peek → Execute → Remove on Success**

```bash
# Peek at task WITHOUT removing it
peek_task() {
  jq -c '.queue | sort_by(-.priority) | .[0]' tasks.json
}

# Remove task by ID (only after success)
remove_task() {
  local task_id="$1"
  jq --arg id "$task_id" '.queue = [.queue[] | select(.id != $id)]' tasks.json > tmp
  mv tmp tasks.json
}

# Main loop
task=$(peek_task)
task_id=$(echo "$task" | jq -r '.id')

# Execute
if execute_task "$task"; then
  remove_task "$task_id"  # ✅ Only remove on success
  echo "Task completed and removed"
else
  echo "Task failed - left in queue for retry"  # ⚠️ Still in queue
fi
```

**Comparison:**

| Scenario | Pop-Before | Peek-Remove-After |
|----------|------------|-------------------|
| Task succeeds | ✅ OK | ✅ OK |
| Task fails | ❌ Lost forever | ✅ Stays in queue for retry |
| Ctrl+C during execution | ❌ Lost | ✅ Stays in queue |
| Script crashes | ❌ Lost | ✅ Stays in queue |
| Resume after interrupt | ❌ Skips to next | ✅ Retries same task |

**Real example:**

```
With pop-before (BAD):
  Task 1: implement - gdelt (30 min task)
    → Removed from queue immediately
    → 15 minutes in... Ctrl+C
    → On resume: Queue starts at Task 2
    → Lost 15 minutes of work!

With peek-remove-after (GOOD):
  Task 1: implement - gdelt (30 min task)
    → Still in queue
    → 15 minutes in... Ctrl+C
    → On resume: Retries Task 1
    → Can continue or manually complete
```

**Implementation:**

```bash
# Track success
task_succeeded=false

case "$task_type" in
  validate)
    if execute_validate "$task"; then
      task_succeeded=true
    fi
    ;;
  implement)
    if execute_implement "$task"; then
      task_succeeded=true
    fi
    ;;
esac

# Only remove on success
if $task_succeeded; then
  remove_task "$task_id"
else
  echo "⚠️  Task failed - kept in queue for retry"
fi
```

**Bonus: Make tasks idempotent**

This pattern encourages idempotent task design:

```bash
execute_implement() {
  # Check if already done
  if [[ -f "output/${source_id}.py" ]]; then
    echo "Already implemented - skipping"
    return 0  # Success (idempotent)
  fi

  # Do the work...
}
```

**When to use:**
- ✅ Long-running tasks (>5 minutes)
- ✅ Autonomous overnight runs
- ✅ Tasks that call external APIs
- ✅ Any interruptible workflow

---

#### 20. **Shell JSON Strings for jq --argjson** (Escaping Gotcha!)

**Problem:** Passing JSON strings to `jq --argjson` from shell scripts requires careful quoting. Double-quoted strings with backslashes fail.

**Anti-pattern:**
```bash
# ❌ BAD: Backslashes consumed by shell, jq receives invalid JSON
add_task "validate" "$source_id" 95 "Validate" "{\"attempt\": 1}"
# Shell interprets \", passes: {attempt: 1} or "attempt": 1 → NOT valid JSON!

jq --argjson ctx "{\"attempt\": 1}" '...'  # FAILS: invalid JSON text
```

**Why it fails:**
1. Shell processes double-quoted strings and interprets `\"`
2. What jq receives is NOT the string `{"attempt": 1}`
3. It might receive `{attempt: 1}` (missing quotes) → syntax error

**Solutions:**

**Option 1: Use single quotes (simplest)**
```bash
# ✅ GOOD: Single quotes preserve the string exactly
add_task "validate" "$source_id" 95 "Validate" '{"attempt": 1}'

# For variables, close and reopen quotes:
add_task "validate" "$source_id" 95 "Validate" '{"attempt": '$attempt'}'
# Note: $attempt is OUTSIDE single quotes
```

**Option 2: Validate JSON before using --argjson**
```bash
add_task() {
  local context="${5:-{}}"

  # Validate context is valid JSON
  if ! echo "$context" | jq -e . >/dev/null 2>&1; then
    echo "⚠️  Warning: Invalid JSON context, using {}" >&2
    context="{}"
  fi

  jq --argjson ctx "$context" '...'
}
```

**Option 3: Build JSON programmatically**
```bash
# For complex JSON with variables, use printf or jq itself:
local fix_context
fix_context=$(printf '{"errors": %s, "attempt": %d, "severity": "%s"}' \
  "$errors" "$attempt" "$severity")

# Or use jq to build the JSON:
fix_context=$(jq -n --arg sev "$severity" --argjson attempt "$attempt" \
  '{errors: [], attempt: $attempt, severity: $sev}')

add_task "fix" "$source_id" 98 "Fix errors" "$fix_context"
```

**Comparison:**

| Approach | Pros | Cons |
|----------|------|------|
| Single quotes | Simple, no escaping | Can't embed variables directly |
| Validate before use | Robust, catches all errors | Extra code, warning messages |
| Build programmatically | Safest for complex JSON | More verbose |

**Real example from ralph_datasources_v2.sh:**

```bash
# BEFORE (broken):
add_task "validate" "$source_id" 95 "Validate" "{\"validation_attempt\": 1}"
# jq error: invalid JSON text passed to --argjson

# AFTER (fixed):
add_task "validate" "$source_id" 95 "Validate" '{"validation_attempt": 1}'
# ✅ Works!

# With variable:
add_task "validate" "$source_id" 95 "Re-validate" '{"validation_attempt": '$next_attempt'}'
#                                                 ^                        ^
#                                                 Close single quote, embed variable, reopen
```

**When to use:**
- ✅ Always when passing JSON to `jq --argjson`
- ✅ Task queue systems with JSON context
- ✅ Any shell script building JSON data structures

**Key takeaway:** When in doubt, use **single quotes for JSON literals** and close/reopen quotes for variables.

---

#### 21. **Monitoring Subagent Progress** (Critical for Long-Running Tasks!)

**Problem:** `claude -p` in non-interactive mode doesn't print output to stdout, making it impossible to see what the subagent is doing. Long tasks (validation, scraping) appear "stuck" even when working correctly.

**Impact:**
- No visibility into subagent progress
- Can't tell if task is working or hanging
- Users interrupt working tasks thinking they're stuck
- Debugging failures is difficult without logs

**Solution: Use Debug Logs**

```bash
# Add --debug-file and --verbose flags to claude calls
run_subagent() {
  local step_name="$1"
  local prompt="$2"
  local output_file="${3:-}"
  local timeout="${4:-30}"
  local debug_log="$STEPS_DIR/${step_name}_debug.log"

  echo "💡 MONITOR PROGRESS:"
  echo "   tail -f $debug_log"
  echo ""

  timeout "${timeout}m" env -u CLAUDECODE claude --model sonnet \
    --dangerously-skip-permissions \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch,Skill" \
    --debug-file "$debug_log" \    # ← Writes detailed debug logs
    --verbose \                      # ← More output
    < "$prompt_file" \
    2>&1 | tee "$STEPS_DIR/${step_name}_output.log"
}
```

**What debug logs contain:**
- ✅ Tool calls (Read, Write, Edit, Bash, etc.)
- ✅ Tool call arguments and results
- ✅ API requests and responses
- ✅ Thinking/reasoning steps (when shown)
- ✅ Error messages and stack traces
- ✅ Timing information

**Monitoring techniques:**

**Option 1: Watch debug log (best for real-time monitoring)**
```bash
# In a separate terminal
tail -f experiments/steps/validate_debug.log
```

**Option 2: Watch file creation (see which step is running)**
```bash
watch -n 2 'ls -lht experiments/steps/*.json | head -5'
```

**Option 3: Monitor processes (see what tools are being called)**
```bash
# See what the subagent is executing
watch -n 5 'pstree -p $(pgrep -f ralph_datasources) | head -30'

# See active Bash tool calls
watch -n 5 'ps aux | grep -E "just|pytest|uv|ruff" | grep -v grep'
```

**Option 4: File modification watcher**
```bash
# Get notified immediately when files change
inotifywait -m experiments/steps/ -e create,modify
```

**Example debug log output:**
```
[2026-02-15 15:06:23] Tool call: Bash
[2026-02-15 15:06:23]   command: ./just test
[2026-02-15 15:06:23]   description: Run test suite
[2026-02-15 15:06:45]   exit_code: 0
[2026-02-15 15:06:45]   output: 24 tests passed
[2026-02-15 15:06:46] Tool call: Write
[2026-02-15 15:06:46]   file_path: experiments/steps/validate.json
[2026-02-15 15:06:46]   content: {"all_tests_passed": true, ...}
```

**When to use:**
- ✅ Any task taking >2 minutes
- ✅ Tasks that run external commands (validation, scraping, tests)
- ✅ Debugging subagent failures
- ✅ Understanding what went wrong in a failed step

**Integration with existing logging:**

```bash
# Script already logs to:
experiments/steps/${step_name}_output.log   # stdout/stderr (often empty)
experiments/steps/${step_name}_prompt.txt   # Input prompt
experiments/steps/${step_name}.json         # Final output

# Now also logs to:
experiments/steps/${step_name}_debug.log    # NEW: Detailed debug info
```

**Pro tip:** Add a progress indicator to the script:

```bash
echo "┌─────────────────────────────────────────┐"
echo "│ EXECUTING: $step_name                  │"
echo "└─────────────────────────────────────────┘"
echo "Timeout: ${timeout}m"
echo "Output:  $output_file"
echo "Debug:   tail -f $debug_log"
echo ""
```

---

#### 22. **Task Queue Deduplication** (Prevent Wasted Work!)

**Problem:** Dynamic task insertion (FIX loops, side tasks, reprioritization) can create duplicate tasks in the queue. Multiple tasks for the same source/type waste resources and create confusion.

**When duplicates occur:**
- Multiple VALIDATE tasks added during FIX loops
- Same side task added by different steps
- Manual task insertion + dynamic task generation
- Reprioritization creates new tasks instead of updating existing ones

**Impact:**
- ❌ Wasted compute (running same validation 3 times)
- ❌ Wasted API costs (3x Claude calls for identical work)
- ❌ Queue bloat (harder to see what needs to be done)
- ❌ Confusion about progress (which VALIDATE is the "real" one?)

**Example of duplication:**

```json
{
  "queue": [
    {"id": "validate_gdelt_1708012345", "type": "validate", "source_id": "gdelt", "priority": 95},
    {"id": "validate_gdelt_1708012398", "type": "validate", "source_id": "gdelt", "priority": 95},
    {"id": "validate_gdelt_1708012456", "type": "validate", "source_id": "gdelt", "priority": 95}
  ]
}
```

All three tasks do the same work!

**Solution 1: Check for duplicates before adding**

```bash
add_task() {
  local task_type="$1"
  local source_id="${2:-}"
  local priority="$3"
  local description="${4:-}"
  local context="${5:-{}}"

  # Check for existing task with same type + source_id
  local existing_count=$(jq --arg type "$task_type" --arg src "$source_id" \
    '[.queue[] | select(.type == $type and .source_id == $src)] | length' "$TASKS")

  if [[ $existing_count -gt 0 ]]; then
    echo "  ⚠️  Task already exists: $task_type for $source_id"
    echo "     Updating priority instead of creating duplicate"

    # Update priority of existing task if new priority is higher
    jq --arg type "$task_type" --arg src "$source_id" --argjson prio "$priority" \
      '(.queue[] | select(.type == $type and .source_id == $src) | .priority) |=
       if . < $prio then $prio else . end' "$TASKS" > "$TASKS.tmp"
    mv "$TASKS.tmp" "$TASKS"

    return 0
  fi

  # No duplicate - add normally
  local task_id="${task_type}_${source_id}_$(date +%s)"
  jq --arg id "$task_id" \
     --arg type "$task_type" \
     --arg source "$source_id" \
     --argjson prio "$priority" \
     --arg desc "$description" \
     --argjson ctx "$context" \
     --arg ts "$(date -Iseconds)" \
     '.queue += [{
       "id": $id,
       "type": $type,
       "source_id": $source,
       "priority": $prio,
       "description": $desc,
       "context": $ctx,
       "created_at": $ts
     }]' "$TASKS" > "$TASKS.tmp"
  mv "$TASKS.tmp" "$TASKS"

  echo "  ➕ Added task: [$priority] $task_type - $description"
}
```

**Solution 2: Periodic deduplication**

```bash
# Run after every N tasks or at end of iteration
deduplicate_queue() {
  echo "🔍 Checking for duplicate tasks..."

  # Group by type + source_id, keep only highest priority
  jq '.queue |= (
    group_by(.type + "_" + .source_id) |
    map(
      # For each group, keep only the task with highest priority
      max_by(.priority)
    )
  )' "$TASKS" > "$TASKS.tmp"

  local before=$(jq '.queue | length' "$TASKS")
  local after=$(jq '.queue | length' "$TASKS.tmp")
  local removed=$((before - after))

  if [[ $removed -gt 0 ]]; then
    mv "$TASKS.tmp" "$TASKS"
    echo "  ✂️  Removed $removed duplicate tasks"
  else
    rm "$TASKS.tmp"
    echo "  ✅ No duplicates found"
  fi
}
```

**Solution 3: Fuzzy matching for similar tasks**

```bash
# For side tasks like "update_docs", check if description is similar
check_similar_tasks() {
  local task_type="$1"
  local description="$2"

  # Extract key words from description (normalize)
  local key_words=$(echo "$description" | tr '[:upper:]' '[:lower:]' | grep -oE '[a-z_]+' | sort -u)

  # Check existing tasks of same type for similar descriptions
  local similar=$(jq --arg type "$task_type" \
    '.queue[] | select(.type == $type) | .description' "$TASKS" | \
    grep -i "$key_words" | wc -l)

  if [[ $similar -gt 0 ]]; then
    echo "  ⚠️  Similar task already exists: $task_type"
    return 1
  fi

  return 0
}
```

**Solution 4: Merge contexts when deduplicating**

```bash
# When keeping highest priority, preserve context from both tasks
deduplicate_with_context_merge() {
  jq '.queue |= (
    group_by(.type + "_" + .source_id) |
    map(
      # Sort by priority descending
      sort_by(-.priority) |
      # Take highest priority task
      .[0] |
      # Merge contexts from all tasks in group
      .context += (.[1:] | map(.context) | add // {})
    )
  )' "$TASKS" > "$TASKS.tmp"
  mv "$TASKS.tmp" "$TASKS"
}
```

**Integration into add_task workflow:**

```bash
add_task() {
  local task_type="$1"
  local source_id="${2:-}"
  local priority="$3"
  local description="${4:-}"
  local context="${5:-{}}"

  # 1. Deduplicate before adding
  local existing=$(jq --arg type "$task_type" --arg src "$source_id" \
    '[.queue[] | select(.type == $type and .source_id == $src)] | length' "$TASKS")

  if [[ $existing -gt 0 ]]; then
    echo "  🔄 Updating existing task instead of adding duplicate"

    # Update priority if higher, merge contexts
    jq --arg type "$task_type" --arg src "$source_id" \
       --argjson prio "$priority" --argjson new_ctx "$context" \
      '(.queue[] | select(.type == $type and .source_id == $src)) |= (
        .priority = (if .priority < $prio then $prio else .priority end) |
        .context += $new_ctx
      )' "$TASKS" > "$TASKS.tmp"
    mv "$TASKS.tmp" "$TASKS"
    return 0
  fi

  # 2. Add normally if no duplicate
  # ... (existing add logic)
}

# Call periodically to catch any duplicates that slipped through
deduplicate_queue() {
  # ... (implementation from Solution 2)
}
```

**When to deduplicate:**

| Timing | Method | Use Case |
|--------|--------|----------|
| **Before adding** | Check in add_task() | Prevent duplicates from being created |
| **After every 5 tasks** | Call deduplicate_queue() | Catch duplicates from parallel operations |
| **After reprioritization** | Merge similar tasks | When boosting/lowering priorities creates duplicates |
| **At iteration end** | Full dedup + report | Clean up before next iteration |

**Example: Deduplication report**

```bash
# Add to main loop after every 5 tasks
if [[ $((task_count % 5)) -eq 0 ]]; then
  echo ""
  echo "────────────────────────────────────────"
  echo "  Queue Maintenance (every 5 tasks)"
  echo "────────────────────────────────────────"
  deduplicate_queue

  echo ""
  echo "Current queue status:"
  jq -r '.queue | group_by(.type) |
    map("\(.0.type): \(length) tasks") | .[]' "$TASKS"
  echo ""
fi
```

**Output example:**
```
🔍 Checking for duplicate tasks...
  ✂️  Removed 3 duplicate tasks

Current queue status:
validate: 2 tasks
fix: 1 tasks
integrate: 4 tasks
update_docs: 1 tasks
```

**Benefits:**
- ✅ Saves compute resources (no redundant work)
- ✅ Saves API costs (fewer Claude calls)
- ✅ Cleaner queue (easier to see progress)
- ✅ Preserves highest priority (most urgent tasks kept)
- ✅ Merges context (no information loss)

**When to use:**
- ✅ Any task queue with dynamic task insertion
- ✅ FIX → VALIDATE loops
- ✅ Side task systems
- ✅ Reprioritization features
- ✅ Long-running queues (>10 tasks)

---

#### 23. **Safe JSON Building with jq** (Prevent Invalid JSON Errors!)

**Problem:** Using `printf` or string concatenation to build JSON breaks with special characters (quotes, backslashes, dollar signs, etc.), causing "Invalid JSON context" errors.

**Anti-pattern:**
```bash
# ❌ BAD: printf breaks with special characters
errors='[{"message": "Path: $HOME with \"quotes\""}]'
context=$(printf '{"errors": %s, "severity": "%s"}' "$errors" "$severity")
# Result: Malformed JSON!

# ❌ BAD: String concatenation with quotes
context='{"status": "failed", "message": "'"$message"'"}'
# Result: Breaks if $message contains quotes
```

**Why it fails:**
- `printf` doesn't escape JSON special characters
- Shell variable expansion in double quotes doesn't escape
- Single-quote close/reopen technique breaks with embedded quotes
- Dollar signs, backslashes, newlines all break the JSON

**Solution: Use `jq -n` to build JSON**

```bash
# ✅ GOOD: jq handles all escaping automatically
errors='[{"message": "Path: $HOME with \"quotes\" and backslash: \\"}]'
severity="CRITICAL"
attempt=2

context=$(jq -n \
  --argjson errors "$errors" \
  --arg severity "$severity" \
  --argjson attempt "$attempt" \
  '{errors: $errors, severity: $severity, attempt: $attempt}')

# Result: Valid JSON every time!
```

**How it works:**
- `jq -n` creates new JSON from scratch (no input file)
- `--arg name value` passes string arguments (auto-escaped)
- `--argjson name json` passes JSON arguments (parsed, then embedded)
- Result is always valid, properly escaped JSON

**Common patterns:**

**Pattern 1: Task context with error array**
```bash
# Build context for add_task()
errors=$(jq -c '.errors_found' validate.json)  # Get errors as JSON array
severity="HIGH"
attempt=1

fix_context=$(jq -n \
  --argjson errors "$errors" \
  --arg severity "$severity" \
  --argjson attempt "$attempt" \
  '{errors: $errors, severity: $severity, attempt: $attempt}')

add_task "fix" "$source_id" 98 "Fix errors" "$fix_context"
```

**Pattern 2: Completion metadata**
```bash
# Build context for complete_task()
status="failed"
attempt=3
severity="MEDIUM"

complete_ctx=$(jq -n \
  --arg status "$status" \
  --argjson attempt "$attempt" \
  --arg severity "$severity" \
  '{status: $status, attempt: $attempt, severity: $severity}')

complete_task "$task_id" "$complete_ctx"
```

**Pattern 3: Simple error list**
```bash
# Fixed error list (no variables)
fail_context=$(jq -n \
  --argjson attempt "$attempt" \
  '{errors: ["validation subagent failed", "timeout"], attempt: $attempt}')

add_task "fix" "$source_id" 98 "Fix timeout" "$fail_context"
```

**Comparison:**

| Method | Pros | Cons | Safe? |
|--------|------|------|-------|
| `printf` | Fast, simple | Breaks with special chars | ❌ NO |
| String concat | Simple | Breaks with quotes/escapes | ❌ NO |
| Single-quote technique | Works for simple cases | Complex, error-prone | ⚠️ FRAGILE |
| **`jq -n`** | **Always valid** | Slightly slower | ✅ **YES** |

**Real-world example from ralph_datasources_v2.sh:**

**Before (broken):**
```bash
# This breaks if error messages contain quotes or special chars
fix_context=$(printf '{"errors": %s, "attempt": %d, "severity": "%s"}' \
  "$errors" "$attempt" "$severity")
# Error: ⚠️ Warning: Invalid JSON context, using {}
```

**After (fixed):**
```bash
# This always works, regardless of content
fix_context=$(jq -n \
  --argjson errors "$errors" \
  --argjson attempt "$attempt" \
  --arg severity "$severity" \
  '{errors: $errors, attempt: $attempt, severity: $severity}')
# Success: ✅ Valid JSON
```

**When to use:**
- ✅ Any time you build JSON for `add_task()` context parameter
- ✅ Any time you build JSON for `complete_task()` output parameter
- ✅ Any JSON construction with user input or error messages
- ✅ Any JSON that might contain quotes, backslashes, or special characters

**Testing your JSON:**

```bash
# Always validate JSON after building
context=$(jq -n ...)

if echo "$context" | jq -e . >/dev/null 2>&1; then
  echo "✅ Valid JSON"
else
  echo "❌ Invalid JSON"
fi
```

**Benefits:**
- ✅ No more "Invalid JSON context" errors
- ✅ Handles error messages with quotes, paths with backslashes
- ✅ Works with nested JSON structures
- ✅ Auto-escapes all special characters
- ✅ Type-safe (distinguishes strings from numbers/booleans)

---

#### 24. **FIX Tasks Must Have Higher Priority Than VALIDATE** (Critical for Task Ordering!)

**Problem:** When a VALIDATE task fails and creates a FIX task, the FIX task might have lower priority than VALIDATE, causing VALIDATE to run again before the fix is applied.

**Scenario:**
```
VALIDATE task (priority 95) finds LOW severity errors
→ Creates FIX task with priority 75 (based on severity)
→ Queue: [95] VALIDATE, [75] FIX
→ VALIDATE runs again before FIX! ❌
→ Infinite loop of validation failures
```

**Why this happens:**
- VALIDATE tasks typically have priority 95
- FIX priority is based on error severity:
  - CRITICAL → 99
  - HIGH → 98
  - MEDIUM → 85 ❌ (lower than VALIDATE!)
  - LOW → 75 ❌ (lower than VALIDATE!)
- MEDIUM and LOW severity FIX tasks have lower priority than the VALIDATE that created them
- This causes VALIDATE to execute before FIX, creating a loop

**Impact:**
- ❌ Validation failures repeat without fixes being applied
- ❌ Wasted compute (running validation on unfixed code)
- ❌ Progress blocked (FIX never gets a chance to run)
- ❌ Confusing behavior (why is validation failing repeatedly?)

**Solution: Dynamic Priority Adjustment**

```bash
execute_validate() {
  # ... validation logic ...

  if [[ "$all_passed" != "true" ]]; then
    # Get current VALIDATE task priority
    local validate_priority=$(echo "$task" | jq -r '.priority // 95')

    # Base FIX priority on severity
    local fix_priority=98
    case "$severity" in
      CRITICAL) fix_priority=99 ;;
      HIGH) fix_priority=98 ;;
      MEDIUM) fix_priority=85 ;;
      LOW) fix_priority=75 ;;
    esac

    # CRITICAL: Ensure FIX always runs BEFORE re-validation
    # FIX must have higher priority than the VALIDATE that created it
    local min_fix_priority=$((validate_priority + 3))
    if [[ $fix_priority -lt $min_fix_priority ]]; then
      echo "⬆️  Boosting FIX priority from $fix_priority to $min_fix_priority"
      fix_priority=$min_fix_priority
    fi

    add_task "fix" "$source_id" "$fix_priority" "Fix errors"
  fi
}
```

**Priority Calculation Examples:**

| VALIDATE Priority | Severity | Base FIX | Minimum FIX | Final FIX | Action |
|-------------------|----------|----------|-------------|-----------|--------|
| 95 | CRITICAL | 99 | 98 | **99** | No boost (already high) |
| 95 | HIGH | 98 | 98 | **98** | No boost (already high) |
| 95 | MEDIUM | 85 | 98 | **98** | ⬆️ Boosted (+13) |
| 95 | LOW | 75 | 98 | **98** | ⬆️ Boosted (+23) |
| 99 | LOW | 75 | 102 | **102** | ⬆️ Boosted (+27) |
| 50 | MEDIUM | 85 | 53 | **85** | No boost (already high) |
| 50 | LOW | 75 | 53 | **75** | No boost (already high) |

**Why +3 instead of +1?**
- Provides buffer for concurrent task additions
- Ensures FIX clearly runs first (not just barely first)
- Accounts for other tasks that might be added at same priority level
- Prevents edge cases where tasks alternate

**Visual Example:**

**Before (broken):**
```
Queue at iteration 5:
  [95] VALIDATE - gdelt
  [75] FIX - gdelt (LOW severity)
  [70] SCRAPE - other_source

Execution order:
1. VALIDATE runs → fails again (not fixed yet!)
2. Creates another FIX task
3. Now have 2 FIX tasks, still no progress
```

**After (fixed):**
```
Queue at iteration 5:
  [98] FIX - gdelt (boosted from 75)
  [95] VALIDATE - gdelt
  [70] SCRAPE - other_source

Execution order:
1. FIX runs → fixes the issues
2. FIX adds VALIDATE task (priority 95)
3. VALIDATE runs → passes! ✅
4. Proceeds to SCRAPE
```

**Edge case handling:**

**Case 1: Already-boosted VALIDATE**
```bash
# VALIDATE was boosted to 99 due to critical issues elsewhere
# FIX with LOW severity should be even higher
VALIDATE=99, severity=LOW → FIX=102 (99+3)
```

**Case 2: Lowered VALIDATE**
```bash
# VALIDATE was lowered to 50 to let other work proceed
# FIX with MEDIUM severity already > 50, no boost needed
VALIDATE=50, severity=MEDIUM → FIX=85 (no change)
```

**Testing:**
```bash
# Test all scenarios
VALIDATE=95, CRITICAL → FIX=99  ✅
VALIDATE=95, HIGH → FIX=98      ✅
VALIDATE=95, MEDIUM → FIX=98    ✅ (boosted from 85)
VALIDATE=95, LOW → FIX=98       ✅ (boosted from 75)
VALIDATE=99, LOW → FIX=102      ✅ (boosted from 75)
```

**Implementation pattern:**

```bash
# 1. Get source task priority
source_priority=$(echo "$task" | jq -r '.priority // 95')

# 2. Calculate base priority (severity, type, etc.)
base_priority=75

# 3. Ensure created task priority > source task priority
min_priority=$((source_priority + 3))
final_priority=$(( base_priority > min_priority ? base_priority : min_priority ))

# Or more concisely:
final_priority=$(( base_priority < source_priority + 3 ? source_priority + 3 : base_priority ))
```

**When to use:**
- ✅ Any task that creates a dependent task (VALIDATE → FIX, DESIGN → IMPLEMENT, etc.)
- ✅ Any task that creates a retry task
- ✅ Any workflow where task A must complete before task B can be validated

**Related lessons:**
- Lesson 18: Peek-execute-remove pattern (ensures failed tasks stay in queue)
- Lesson 22: Task queue deduplication (prevents multiple FIX tasks)

---

#### 25. **Generic Task Executor for Unknown Task Types** (Graceful Degradation!)

**Problem:** When the task queue contains a custom task type that's not in the case statement, the script fails immediately without attempting to execute it.

**Scenario:**
```bash
Task added: {"type": "create_bronze_loader", "description": "Create bronze layer loader..."}
  ↓
case statement doesn't have "create_bronze_loader"
  ↓
Falls through to default case: *)
  ↓
echo "❌ Unknown task type"
  ↓
Task fails without being attempted ❌
```

**Why this is a problem:**
- Dynamic task systems add new task types at runtime
- Side tasks use descriptive type names (update_docs, fix_bug, create_loader)
- Every new task type requires code changes to the case statement
- Unknown tasks block progress even though they might be simple
- Wastes opportunity to leverage Claude's general capabilities

**Impact:**
- ❌ Progress blocked on unknown task types
- ❌ Manual intervention required to add case handlers
- ❌ Inflexible system (can't handle new task types dynamically)
- ❌ Wasted context (task description contains all needed info)

**Solution: Generic Task Executor**

Instead of failing on unknown task types, execute them generically based on the description:

```bash
case "$task_type" in
  orient|select|design|implement|validate|fix|scrape|integrate|quality)
    # Known task types with specific handlers
    ;;

  update_docs|fix_bug|refactor|optimize)
    # Generic side task handler
    ;;

  *)
    # Unknown task type - try generic execution
    echo "⚠️  Unknown task type: $task_type"
    echo "   Attempting to execute as generic task..."

    # Build prompt from task metadata
    local generic_prompt="Execute the following task:

Task Type: $task_type
Description: $task_desc
Source: $source_id

Based on the task type and description, determine what needs to be done.

Common patterns:
- create_* → Create the specified component
- update_* → Update existing component
- fix_* → Fix issues
- analyze_* → Analyze and report

Write results to experiments/steps/generic_${task_type}.json:
{
  \"task_type\": \"$task_type\",
  \"completed\": bool,
  \"files_created\": [...],
  \"files_modified\": [...],
  \"summary\": \"what was done\",
  \"recommend_adding_to_case_statement\": bool
}"

    if run_subagent "generic_${task_type}" "$generic_prompt" "$STEPS_DIR/generic_${task_type}.json" 30; then
      # Check if should add to case statement
      local recommend=$(jq -r '.recommend_adding_to_case_statement // false' \
        "$STEPS_DIR/generic_${task_type}.json")

      if [[ "$recommend" == "true" ]]; then
        echo "📝 Task recommends adding '$task_type' to case statement"
      fi

      task_succeeded=true
    fi
    ;;
esac
```

**How it works:**

1. **Detect unknown task type** - Falls through to default case `*)`
2. **Build generic prompt** - Uses task type, description, and source_id
3. **Execute with Claude** - Let Claude figure out what to do based on context
4. **Capture results** - Same output format as other tasks
5. **Track recommendations** - Claude can suggest if task type should be formalized

**Example execution:**

**Task:** `create_bronze_loader`
```json
{
  "type": "create_bronze_loader",
  "description": "Create bronze layer loader for yahoo_intraday_ohlc data",
  "source_id": "yahoo_intraday_ohlc"
}
```

**Generic execution:**
```
⚠️  Unknown task type: create_bronze_loader
   Attempting to execute as generic task...
   💡 If this task type is common, consider adding to case statement

┌─────────────────────────────────────────┐
│ EXECUTING: generic_create_bronze_loader │
└─────────────────────────────────────────┘

Claude analyzes:
- Task type pattern: create_*
- Description mentions: "bronze layer loader"
- Source: yahoo_intraday_ohlc

Claude creates:
- compricing/datalayers/bronze/loaders/yahoo_intraday_ohlc.py
- tests/test_datalayers/test_yahoo_intraday_ohlc_loader.py
- Updates orchestrator.py

✅ Generic task completed: create_bronze_loader
📝 Task recommends adding 'create_bronze_loader' to case statement
```

**Output JSON:**
```json
{
  "task_type": "create_bronze_loader",
  "completed": true,
  "files_created": [
    "compricing/datalayers/bronze/loaders/yahoo_intraday_ohlc.py",
    "tests/test_datalayers/test_yahoo_intraday_ohlc_loader.py"
  ],
  "files_modified": [
    "compricing/datalayers/orchestrator.py"
  ],
  "summary": "Created bronze layer loader for yahoo_intraday_ohlc data with deduplication, tests, and orchestrator registration",
  "recommend_adding_to_case_statement": true
}
```

**Benefits:**

| Aspect | Without Generic Executor | With Generic Executor |
|--------|-------------------------|----------------------|
| **Unknown tasks** | ❌ Immediate failure | ✅ Attempted execution |
| **New task types** | ❌ Requires code changes | ✅ Works dynamically |
| **Side tasks** | ❌ Must be pre-defined | ✅ Self-describing |
| **Flexibility** | ❌ Rigid case statement | ✅ Adaptive to new needs |
| **Development speed** | ❌ Stop to add handlers | ✅ Keep iterating |

**When to add to case statement:**

Generic execution works well, but add explicit handlers when:
- ✅ Task type used frequently (>3 times)
- ✅ Task needs specific validation or setup
- ✅ Task has complex multi-step workflow
- ✅ Output format needs to be standardized
- ✅ Task requires specific tools or permissions

**Gradual formalization pattern:**

```
Iteration 1: create_bronze_loader added dynamically
  → Generic executor handles it ✅

Iteration 2-3: create_bronze_loader used 2 more times
  → Still works via generic executor ✅

Iteration 4: Add to case statement for better handling
  → Now has dedicated handler with bronze-specific logic ✅
```

**Real-world example:**

**Before (rigid):**
```
❌ Unknown task type: create_bronze_loader
   If this is a custom side task, add it to the case statement
⚠️  Task failed - left in queue
Queue blocked until manual code change!
```

**After (flexible):**
```
⚠️  Unknown task type: create_bronze_loader
   Attempting to execute as generic task...
✅ Generic task completed: create_bronze_loader
📝 Task recommends adding to case statement (used 3+ times)
Queue continues, task executed successfully!
```

**Error handling:**

```bash
# If generic execution also fails, provide helpful context
if ! run_subagent "generic_${task_type}" "$generic_prompt" ...; then
  echo "⚠️  Generic task failed: $task_type"
  echo "   Task description: $task_desc"
  echo "   Consider:"
  echo "   1. Verify task description is clear"
  echo "   2. Check if task requires specific setup"
  echo "   3. Add explicit handler to case statement"
  echo "   4. Remove task from queue if not needed"
fi
```

**Monitoring recommendations:**

After several iterations, check which task types are being handled generically:

```bash
# Count generic task executions
ls experiments/steps/generic_*.json | wc -l

# See most common generic task types
ls experiments/steps/generic_*.json | \
  sed 's/.*generic_//' | sed 's/\.json//' | \
  sort | uniq -c | sort -rn

# Example output:
#  5 create_bronze_loader
#  3 analyze_data_quality
#  2 update_lineage
#  1 fix_imports
```

**Decision guide:**

| Count | Action |
|-------|--------|
| 1-2 uses | ✅ Keep as generic (works fine) |
| 3-4 uses | ⚠️ Consider adding to case statement |
| 5+ uses | 📝 Add to case statement (common pattern) |

**Template for adding to case statement:**

```bash
# After seeing create_bronze_loader used 5 times, formalize it:
case "$task_type" in
  # ... existing cases ...

  create_bronze_loader)
    echo "🏗️  CREATE BRONZE LOADER: $task_desc"

    local prompt="Create a bronze layer loader for $source_id:

1. Create compricing/datalayers/bronze/loaders/${source_id}.py
2. Implement loader following bronze layer patterns
3. Add deduplication keys
4. Create tests
5. Register in orchestrator

Write to experiments/steps/create_bronze_loader.json"

    if run_subagent "create_bronze_loader" "$prompt" "$STEPS_DIR/create_bronze_loader.json" 30; then
      task_succeeded=true
    fi
    ;;
esac
```

**When to use:**
- ✅ Any task queue system with dynamic task creation
- ✅ Side task systems where task types aren't known upfront
- ✅ Rapid prototyping (don't want to stop to add handlers)
- ✅ Long-running autonomous loops
- ✅ Systems where tasks are described in natural language

**Related lessons:**
- Lesson 17: Task queue vs fixed-step (task queues need flexibility)
- Lesson 22: Task deduplication (prevents duplicate generic executions)

---

#### 26. **Extract All Variables Before Use with `set -u`** (Bash Strict Mode Gotcha!)

**Problem:** When using `set -u` (treat unset variables as errors), trying to use a variable that wasn't extracted from JSON causes the script to exit immediately.

**Scenario:**
```bash
#!/usr/bin/env bash
set -euo pipefail  # Strict mode: -u = unset variables are errors

task='{"type":"create_loader","source_id":"yahoo","description":"Create loader"}'

# Extract some variables
task_type=$(echo "$task" | jq -r '.type')
task_desc=$(echo "$task" | jq -r '.description')
# ❌ Forgot to extract source_id!

# Later in generic executor:
echo "Source: $source_id"  # 💥 ERROR: source_id: unbound variable
```

**Why this happens:**
- `set -u` is a best practice (catches typos, missing variables)
- JSON task objects may have many fields
- Easy to forget to extract a field before using it
- Bash exits immediately on unset variable access
- Error message is cryptic (just line number + variable name)

**Impact:**
- ❌ Script crashes with "unbound variable" error
- ❌ Task marked as failed even though logic is correct
- ❌ Hard to debug (error doesn't point to where extraction was missing)
- ❌ Wastes iteration if task was otherwise valid

**Solution: Extract ALL task fields at the top**

```bash
# Extract task details AT THE TOP of the execution block
task_type=$(echo "$task" | jq -r '.type')
task_id=$(echo "$task" | jq -r '.id')
task_desc=$(echo "$task" | jq -r '.description // .source_id')
task_prio=$(echo "$task" | jq -r '.priority')

# ✅ CRITICAL: Extract source_id even if not all cases use it
task_source=$(echo "$task" | jq -r '.source_id // "unknown"')
task_context=$(echo "$task" | jq -r '.context // {}')

# Now safe to use in ANY case statement branch
case "$task_type" in
  *)
    # Generic executor can safely use $task_source
    echo "Source: $task_source"
    ;;
esac
```

**Alternative: Extract locally in each case**

If different cases need different fields, extract locally:

```bash
case "$task_type" in
  create_bronze_loader)
    # Extract fields needed for this specific case
    local source_id=$(echo "$task" | jq -r '.source_id')
    local loader_type=$(echo "$task" | jq -r '.context.loader_type // "standard"')

    echo "Creating loader for $source_id (type: $loader_type)"
    ;;

  *)
    # Generic case extracts its own fields
    local source_id=$(echo "$task" | jq -r '.source_id // "unknown"')
    echo "Generic execution for source: $source_id"
    ;;
esac
```

**⚠️ CRITICAL: `local` is function-only!**

If the case statement is NOT inside a function (i.e., in main script body), you CANNOT use `local`:

```bash
# Main script body (NOT in a function)
case "$task_type" in
  *)
    # ❌ ERROR: local can only be used in a function
    local source_id=$(echo "$task" | jq -r '.source_id // "unknown"')

    # ✅ CORRECT: No 'local' keyword
    source_id=$(echo "$task" | jq -r '.source_id // "unknown"')
    ;;
esac

# Inside a function
execute_generic() {
  local task="$1"

  # ✅ CORRECT: local is OK inside functions
  local source_id=$(echo "$task" | jq -r '.source_id')
  local generic_prompt="..."
}
```

**Error message if you use `local` outside a function:**
```
./script.sh: line 1072: local: can only be used in a function
```

**Use jq defaults to handle missing fields:**

```bash
# If field might not exist, provide default
source_id=$(echo "$task" | jq -r '.source_id // "unknown"')
priority=$(echo "$task" | jq -r '.priority // 50')
context=$(echo "$task" | jq -r '.context // {}')

# For booleans
completed=$(echo "$task" | jq -r '.completed // false')

# For arrays
depends_on=$(echo "$task" | jq -r '.depends_on // []')
```

**Real-world debugging example:**

**Error message:**
```
./experiments/ralph_datasources_v2.sh: line 1094: source_id: unbound variable
```

**Debugging steps:**
1. Check line 1094 - sees `echo "Source: $source_id"`
2. Search backwards for `source_id=$(...)` - NOT FOUND!
3. Task JSON shows `"source_id": "side_task"` - field exists
4. **Root cause:** Variable extraction was missing
5. **Fix:** Add `local source_id=$(echo "$task" | jq -r '.source_id // "unknown"')`

**Prevention checklist:**

Before using a variable from task JSON:
- ✅ Is it extracted at the top of the execution block?
- ✅ Does the extraction use `// "default"` for optional fields?
- ✅ Is the variable declared `local` if inside a function/case?
- ✅ Does the extraction handle the case where field doesn't exist?

**Good pattern:**

```bash
# GOOD: Extract once at top, use everywhere
task_source=$(echo "$task" | jq -r '.source_id // "unknown"')
task_attempt=$(echo "$task" | jq -r '.context.attempt // 1')

case "$task_type" in
  validate)
    echo "Validating $task_source (attempt $task_attempt)"
    ;;
  fix)
    echo "Fixing $task_source (attempt $task_attempt)"
    ;;
  *)
    echo "Generic: $task_source (attempt $task_attempt)"
    ;;
esac
```

**Bad pattern:**

```bash
# BAD: Extract only in some cases
case "$task_type" in
  validate)
    local source_id=$(echo "$task" | jq -r '.source_id')
    echo "Validating $source_id"
    ;;
  fix)
    # ❌ Forgot to extract source_id here!
    echo "Fixing $source_id"  # 💥 ERROR
    ;;
esac
```

**Template for case statement variable handling:**

```bash
# Option 1: Global extraction (use if most cases need the same fields)
task_id=$(echo "$task" | jq -r '.id')
task_type=$(echo "$task" | jq -r '.type')
task_source=$(echo "$task" | jq -r '.source_id // "unknown"')
task_desc=$(echo "$task" | jq -r '.description // ""')

case "$task_type" in
  # All cases can use task_id, task_type, task_source, task_desc
  validate) ... ;;
  fix) ... ;;
  *) ... ;;
esac

# Option 2: Local extraction (use if cases need different fields)
case "$task_type" in
  validate)
    local source_id=$(echo "$task" | jq -r '.source_id')
    local threshold=$(echo "$task" | jq -r '.context.threshold // 0.95')
    ;;

  fix)
    local source_id=$(echo "$task" | jq -r '.source_id')
    local attempt=$(echo "$task" | jq -r '.context.attempt // 1')
    local errors=$(echo "$task" | jq -r '.context.errors // []')
    ;;
esac
```

**When to use:**
- ✅ Any bash script with `set -u` (strict mode)
- ✅ Any code that builds strings/prompts from JSON data
- ✅ Generic executors that work with dynamic task types
- ✅ Case statements where different branches need same variables

**Related lessons:**
- Lesson 23: Safe JSON building with jq (input side)
- Lesson 25: Generic task executor (where this error was discovered)

**Key insight:** `set -u` is your friend (catches bugs), but requires discipline to extract all needed variables before use. Always use `jq ... // "default"` for optional fields.

---

#### 27. **`setsid` for Process Group Isolation** (Security Hooks + Watchdogs)

**Problem:** If a security hook or watchdog inside the subagent calls `kill -TERM 0`, it kills every process in the same process group — including the parent orchestrator loop.

**Scenario:**
```bash
# WRONG: subagent runs in same process group as ralph_research.sh
timeout 120m env -u CLAUDECODE claude ... < prompt.md

# If guard.sh inside the subagent fires kill -TERM 0:
# → kills the subagent ✅ (intended)
# → kills ralph_research.sh ❌ (loop dies)
```

**Solution:** Use `setsid` to start the subagent in a fresh process group:

```bash
# CORRECT: setsid creates a new process group
setsid timeout 120m env -u CLAUDECODE claude ... < prompt.md
# If guard fires kill -TERM 0: only kills the subagent's group, loop survives
```

**Also:** Use `set +e` / `PIPESTATUS` / `set -e` so a failed subagent is logged and skipped, not fatal:

```bash
set +e
setsid timeout "${timeout_min}m" env -u CLAUDECODE .exec/execwrap.bash claude \
  --model sonnet --dangerously-skip-permissions \
  < "$prompt_file" 2>&1 | tee "$output_log"
local exit_code="${PIPESTATUS[0]}"
set -e

if [[ "$exit_code" -ne 0 ]]; then
  echo "  ⚠️  [$step_name] exited with code $exit_code (check $output_log)"
  return "$exit_code"
fi
```

**Key insight:** A failed step should be logged and reported — not crash the whole loop. Use `setsid` + `PIPESTATUS` together.

---

#### 28. **Security Wrapper Variable Names Must Match Exactly**

**Problem:** If your loop uses layered security (guard scripts, preload DEBUG traps), a single name mismatch in a guard variable causes the guard to self-trigger on its own grep patterns, producing a false-positive kill.

**Real example:**
- `preload.sh` checks `__EXECWRAP_ACTIVE` (double underscore prefix)
- `execwrap.bash` was exporting `EXECWRAP_ACTIVE` (single underscore prefix)
- Anti-recursion guard never fired → DEBUG trap installed inside `guard.sh`'s subprocess
- `guard.sh`'s own exfiltration grep (`'(curl|wget|http).*(file\.io|...)'`) contains `http` and `file.io` in the pattern string → matches itself → `kill -TERM 0` → false-positive kill of entire loop

**Diagnosis:** Check the security audit log (e.g. `~/.llmsec/logs/`). Look for lines like:
```
[BLOCK] Matched exfiltration pattern: http
```
If the blocked command IS the guard script's grep itself, you have a self-triggering guard.

**Fix:**
```bash
# In ralph_research.sh, before subagent calls:
# set the variable that preload.sh ACTUALLY checks
# (audit preload.sh to find the right name):
export __EXECWRAP_ACTIVE=1
```

**Key insight:** Always audit what variable name the preload/guard checks, and what the launcher exports. A one-character mismatch silently disables the anti-recursion protection.

---

#### 29. **Exit Code 124 = Timeout, Not Crash — Calibrate Generously**

**Problem:** `timeout` exits with code 124 when it sends SIGTERM. This looks like a failure but the step may have been making progress. Under-estimated timeouts waste entire cycles.

**Common trap:** Estimating step2 (execute) timeout based on average runtime, not worst-case. A cycle that includes both a long data build AND a full experiment run can easily 2x the average.

**Example worst case budget:**
```
Data build (e.g. ARIMA cache):  ~30 min
Full-universe experiment run:   ~30 min
Second experiment (bear regime):~30 min
Reviewer subagent:              ~10 min
Overhead + retries:             ~20 min
────────────────────────────────────────
Total:                         ~120 min → set timeout to 300 min (5 hours)
```

**Rule of thumb:** Set the execute step timeout to the **sum of all possible sub-tasks**, not just the expected path. CPU-bound ML training steps should get 5+ hours. Orient and finalize steps are cheap — 20-30 min is fine.

**Key insight:** Exit code 124 is silent data loss. Always log it explicitly and set the budget to the worst conceivable case.

---

#### 30. **Finalize Step (Step 3) is the Compound Engineering Heartbeat**

**Problem:** Research cycles produce ephemeral results. If Step 3 is skipped, rushed, or times out, knowledge evaporates and the loop doesn't actually compound.

**What Step 3 must do to create durable value:**
1. Write at least one lesson to `docs/solutions/` or `notes/research_lessons.md`
2. Move completed tasks to Done in `tasks.md`
3. Add follow-up tasks with priorities
4. Update `progress.md` with the cycle summary

**Key insight:** The loop's long-term value is proportional to the quality of Step 3, not Step 2. Experiment results are useless if they're not captured in a form future cycles can build on. Step 3 should never be the step that gets its timeout cut.

---

#### 31. **Prefer Markdown State Over JSON for Agent-Readable State**

**Problem:** JSON task queues require agents to parse structured data, adding prompt complexity and making the task queue harder to reason about qualitatively (priorities, relationships, context).

**Tradeoff:**

| Approach | Pros | Cons |
|----------|------|------|
| JSON task queue | Machine-parseable, structured | Agents treat it mechanically; hard to express nuance; jq bugs in bash |
| Markdown task queue | Agent reads naturally; supports rich context, rationale, priority notes | Requires agent to interpret, not parse |

**Recommendation:** Use **Markdown for agent-readable state** (`tasks.md`, `progress.md`, `plan.md`). Use JSON only for data that a bash script needs to parse programmatically (e.g. `tree_state.json` for backtracking).

**The freedom dividend:** When the task list is Markdown, the orient agent can reason holistically — weighing task rationale, dependencies, expected value, and compound effects — rather than mechanically popping a queue item. This produces better task selection and better plans.

**Minimal bash integration pattern (no JSON needed):**
```
research/tasks.md        → Markdown priority queue (agent reads + writes)
research/plan.md         → Markdown plan for current cycle (agent writes, agent reads)
research/progress.md     → Append-only Markdown log (agent appends)
research/cycle_count.txt → Single integer (bash reads for resume)
```

The bash script only needs:
```bash
grep -q "IN_PROGRESS" "$TASKS"   # check if any task is active
grep "## Execution Checklist" "$PLAN"  # validate plan was written
echo "$i" > "$CYCLE_FILE"        # persist cycle counter
```

**Key insight:** Less JSON = more agent thinking. Reserve JSON for data that a program (not an agent) must parse.

---

#### 32. **One Reviewer Pass, Then Move On**

**Problem:** Unlimited SE ↔ Reviewer loops don't converge — they cycle. Each reviewer pass finds new edge cases; the SE fixes them and introduces others. This wastes compute and delays experiments.

**Solution:** Hard-cap the reviewer at **one pass**. If the reviewer finds issues, the SE addresses them once. Remaining issues become tasks in the next cycle.

**Why this works:**
- "Good enough to ship" is almost always better than perfect-but-delayed in research loops
- The next cycle's orient step will reprioritize unresolved issues if they matter
- Reviewer cycles consume budget that could go toward experiments

**Key insight:** The loop itself is the quality gate — bad code that causes experiment failures gets caught and fixed next cycle. One reviewer pass is sufficient for research-grade code.

---

#### 33. **Inject a Hygiene Task Every N Cycles**

**Problem:** Research loops accumulate silent debt — lint errors, unused config flags, and ML methodology violations (e.g., not recording ablations, forgetting to check look-ahead bias in new features). No individual cycle feels like the right moment to stop and clean up, so it never gets scheduled.

**Solution:** Have the orchestrator script automatically inject a `[P2] Technical hygiene` task into the task queue every N cycles (5 is a good default). The task covers three dimensions:
1. **Errors** — run the full check suite (`./just check`), fix every lint/type/test failure
2. **Tech debt** — review the progress log for unresolved TODO callouts; scan the model/feature code for dead flags, duplicate configs, and unused code paths
3. **ML/DS rigour** — verify recent experiments respected temporal train/val/test split, used no look-ahead bias, recorded feature importances, and documented ablations before accepting a result as valid; if any principle is violated, add a P1 fix task immediately

**Implementation pattern (bash):**
```bash
# Before step1 runs, every 5th cycle:
if (( i % 5 == 0 )); then
  HYGIENE_MARKER="hygiene-cycle-$i"
  if ! grep -q "$HYGIENE_MARKER" "$TASKS" 2>/dev/null; then
    python3 - "$TASKS" "$i" "$(date +%Y-%m-%d)" <<'PYEOF'
import sys, re
tasks_file, cycle, today = sys.argv[1], sys.argv[2], sys.argv[3]
with open(tasks_file) as f:
    content = f.read()
task = f"""
- [ ] **[P2] Technical hygiene — cycle {cycle}** <!-- hygiene-cycle-{cycle} -->
  - Status: PENDING
  - Added: {today} | Source: orchestrator (every-5-cycles hygiene injection)
  - Definition of done:
    1. Run full check suite — fix ALL new errors
    2. Review progress log for TODO/debt callouts not yet tasked
    3. Verify recent experiments: temporal split? no look-ahead? importances noted? ablations recorded?
    4. If any principle is violated → add a P1 fix task immediately
"""
content = re.sub(r'(^## Completed)', task + r'\1', content, count=1, flags=re.MULTILINE)
with open(tasks_file, 'w') as f:
    f.write(content)
PYEOF
  fi
fi
```

The marker comment prevents double-injection on loop restarts. The task is injected before step1 reads the queue, so the orient agent picks it up naturally and includes it in the cycle plan.

**Also update step1_orient.md** to explain how to handle hygiene tasks when found — treat each dimension as a sub-item in the SE Steps section, and escalate any principle violation to P1 immediately.

**Why this works:**
- Debt cleanup gets scheduled predictably instead of "when we feel like it"
- Three-dimension checklist makes the scope concrete and completable in one cycle
- The marker prevents double-scheduling; injected-but-skipped tasks remain visible for the next hygiene cycle
- N=5 is empirically good: frequent enough to stay clean, infrequent enough not to dominate research throughput

---

#### 34. **Heartbeat + Auto-Retry for Silent API Hangs**

**Problem:** Long-running subagents (5-hour timeout) can silently hang — the API connection drops, claude produces zero output, and the terminal shows nothing for 5 hours before exit code 124. The operator has no idea whether the agent is working or stuck.

**Two-part solution:**

**Part 1 — Heartbeat watcher** (background subshell, no extra dependencies):
```bash
local cur_log="$output_log"   # capture path for subshell
(
  hb_prev=0; hb_mins=0
  while true; do
    sleep 600   # every 10 minutes
    hb_mins=$((hb_mins + 10))
    hb_cur=$(wc -c < "$cur_log" 2>/dev/null || echo 0)
    if [[ "$hb_cur" -le "$hb_prev" ]]; then
      printf "  [heartbeat %dm] ⚠️  no new output — log: %dB (API may be hung)\n" \
        "$hb_mins" "$hb_cur"
    else
      printf "  [heartbeat %dm] still running — log: %dB (+%dB)\n" \
        "$hb_mins" "$hb_cur" "$((hb_cur - hb_prev))"
    fi
    hb_prev=$hb_cur
  done
) &
heartbeat_pid=$!
# ... run the subagent ...
kill "$heartbeat_pid" 2>/dev/null || true
wait "$heartbeat_pid" 2>/dev/null || true
```

**Part 2 — Auto-retry on silent hang** (exit 124 + tiny log):
```bash
if [[ "$exit_code" -eq 124 ]]; then
  log_size=$(wc -c < "$output_log" 2>/dev/null || echo 0)
  if [[ "$log_size" -lt 2000 ]]; then
    # Only execwrap headers in log = API hung before claude produced anything
    attempt=$((attempt + 1))
    if [[ "$attempt" -le "$max_hang_retries" ]]; then
      sleep 15
      output_log="$LOGS_DIR/$(date +%Y%m%d_%H%M%S)_${step_name}_retry${attempt}.log"
      continue   # restart the while true loop
    fi
  else
    # Log has real content = genuine timeout, not a hang — don't retry
    echo "  [timeout] Genuine timeout (${log_size}B) — not retrying"
  fi
fi
```

**Key distinction:** 2000 bytes is the right threshold because execwrap startup headers are ~700 bytes. Any real claude output pushes the log above 2 KB. So `< 2000` reliably identifies "claude never connected" vs "claude ran but task took too long".

**Why this works:**
- Silent API hangs are transient (network hiccup, server-side timeout) — retrying seconds later almost always succeeds
- Genuine long runs (log has content) are not retried — the 5-hour budget was legitimately consumed
- Fresh log file per retry keeps each attempt independently inspectable (`_retry1.log`, `_retry2.log`)
- Heartbeat is zero-cost (pure bash `sleep` + `wc`) and zero-risk (killed before the next step)
- `wait "$heartbeat_pid"` avoids zombie processes

---

#### 35. **Two-Frequency Meta-Loop: Hygiene Every N Cycles, Self-Improvement Every M Cycles**

**Problem:** Lesson 33 injects a hygiene task every N cycles to keep code clean. But the Ralph loop *itself* also drifts — prompts get stale, timeouts are wrong for the actual workload, step ordering causes redundant work, or a recurring failure pattern points to a structural flaw. Without a scheduled moment to reflect, the loop runs faster but in the wrong direction.

**Solution:** Run two nested periodic tasks on different cadences:

| Cadence | Task | Scope |
|---------|------|-------|
| Every **N cycles** (default: 5) | **Hygiene check** — existing Lesson 33 | Code quality, tech debt, outstanding TODOs, ML rigour |
| Every **M cycles** (default: 20) | **Loop self-improvement** — new | Prompt quality, timeout calibration, step ordering, lessons captured, structural flaws |

**Self-improvement task definition (inject every M cycles):**
```
- [ ] **[P2] Loop self-improvement — cycle {cycle}** <!-- loop-improve-cycle-{cycle} -->
  - Status: PENDING
  - Added: {today} | Source: orchestrator (every-20-cycles loop-improvement injection)
  - Definition of done:
    1. Review the last M cycles of progress.md — identify recurring failures, slow steps, and skipped tasks
    2. Review all docs/solutions/ lesson entries added since the last loop-improvement task
    3. Propose concrete changes to at least one of: step prompts, timeouts, task-injection rules, or loop structure
    4. Apply approved changes directly (edit the runner script / prompt files)
    5. Add a "Loop improvement log" entry to docs/solutions/ documenting what changed and why
```

**Implementation pattern (extends Lesson 33's bash pattern):**
```bash
# Every M-th cycle: inject a loop self-improvement task
M_IMPROVE=20
if (( i % M_IMPROVE == 0 )); then
  IMPROVE_MARKER="loop-improve-cycle-$i"
  if ! grep -q "$IMPROVE_MARKER" "$TASKS" 2>/dev/null; then
    python3 - "$TASKS" "$i" "$(date +%Y-%m-%d)" <<'PYEOF'
import sys, re
tasks_file, cycle, today = sys.argv[1], sys.argv[2], sys.argv[3]
with open(tasks_file) as f:
    content = f.read()
task = f"""
- [ ] **[P2] Loop self-improvement — cycle {cycle}** <!-- loop-improve-cycle-{cycle} -->
  - Status: PENDING
  - Added: {today} | Source: orchestrator (every-20-cycles loop-improvement injection)
  - Definition of done:
    1. Review last 20 cycles of progress.md for recurring failures, slow steps, skipped tasks
    2. Review docs/solutions/ entries added since last loop-improvement
    3. Propose and apply changes to: step prompts, timeouts, task-injection rules, or loop structure
    4. Add a loop improvement log entry to docs/solutions/loop_improvements.md
"""
content = re.sub(r'(^## Completed)', task + r'\1', content, count=1, flags=re.MULTILINE)
with open(tasks_file, 'w') as f:
    f.write(content)
PYEOF
  fi
fi
```

**Choosing N and M:**
- N=5 (hygiene): frequent enough to prevent debt accumulation, infrequent enough not to dominate throughput
- M=20 (self-improvement): infrequent enough that there's meaningful history to review; adjust downward for fast-moving loops or early phases where the process is still stabilising
- Rule of thumb: M should cover roughly one "chapter" of work — enough cycles to reveal a pattern but not so many that the loop has been running wrong for too long

**What the self-improvement agent should look for:**
1. **Recurring failures** — same step failing repeatedly → prompt is ambiguous or task is too large
2. **Slow steps** — consistently consuming >80% of their timeout → increase timeout or split the step
3. **Skipped/deferred tasks** — tasks that keep getting pushed back → either too vague, wrong priority, or blocked by a structural dependency never resolved
4. **Lessons not yet applied** — docs/solutions/ entries that describe a recurring problem but the loop code hasn't been updated to prevent it
5. **Prompt drift** — step prompts that no longer match the actual state schema or output format

**Why this works:**
- The loop compounds on two axes simultaneously: domain knowledge (Lesson 30/33) and process quality (Lesson 35)
- Self-improvement tasks are injected automatically, so they happen predictably rather than only when the operator notices something is wrong
- Documenting each loop-improvement cycle in `docs/solutions/` creates a second-order knowledge base: lessons about the lessons themselves
- The two frequencies are independent — a hygiene cycle and an improvement cycle can coincide at cycle LCM(N,M) without conflict (both tasks are in the queue simultaneously, handled sequentially)

---

#### 37. **Force Non-Interactive/Headless Session for Every Tool Call**

**Problem:** When the ralph loop script runs from a terminal, tool invocations (claude, opencode, etc.) inherit the parent TTY. This causes two classes of failure:

1. **TUI hijack** — tools detect a TTY and launch an interactive UI, blocking the loop indefinitely waiting for user input that never comes.
2. **ANSI pollution** — color escape codes and cursor-movement sequences written to stdout/stderr corrupt log files, making them unreadable by grep, jq, or the next prompt that reads them.

Both failures are silent from the loop's perspective: the tool appears to hang or produces garbage output.

**Root cause:** Tools test `isatty(stdin)` or `isatty(stdout)` to decide between interactive and headless mode. A loop running in a terminal passes that test even though no human is reading the output.

---

**Complete non-interactive invocation template (Claude):**

```bash
# The canonical headless claude call — ALL of these env vars + flags are required
_invoke_claude() {
  local model="$1" prompt_file="$2" output_log="$3" timeout_min="${4:-30}"

  NO_COLOR=1 \
  TERM=dumb \
  env -u CLAUDECODE \
  timeout "${timeout_min}m" \
    claude \
      --model "$model" \
      --dangerously-skip-permissions \
      --allowedTools "Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch,Skill" \
      --output-format stream-json \
      --verbose \
      --debug-file "${output_log%.log}_debug.log" \
      < "$prompt_file" \
    2>&1 | tee "$output_log"
}
```

**What each piece does and why it's required:**

| Piece | Why required |
|-------|-------------|
| `NO_COLOR=1` | Suppresses ANSI color codes — respected by claude, git, pytest, and most CLI tools. Without it, log files contain raw escape sequences that break grep/jq. |
| `TERM=dumb` | Second line of defense: tools that ignore `NO_COLOR` but check `$TERM` disable TUI features for `dumb` terminals. |
| `env -u CLAUDECODE` | Removes the nested-session guard (Lesson 1). Always required. |
| `timeout ${n}m` | Hard kill — prevents silent hangs from blocking the loop forever (Lessons 12, 34). |
| `--dangerously-skip-permissions` | Suppresses all interactive "allow this?" prompts. Without it, the loop hangs at the first tool confirmation. |
| `--output-format stream-json` | Emits structured JSON events instead of human-formatted text. Allows the loop to parse progress, tool calls, and final output programmatically. Test for support first (see below). |
| `< "$prompt_file"` | stdin redirect signals non-interactive mode at the OS level. Tools that check `isatty(0)` see a file, not a terminal, and stay headless. |

---

**Checking `--output-format` support (add to dry-run validation):**

```bash
if env -u CLAUDECODE claude --help 2>&1 | grep -q "output-format"; then
  OUTPUT_FORMAT_FLAG="--output-format stream-json"
else
  OUTPUT_FORMAT_FLAG=""  # older version — omit flag, parse plain text
  echo "⚠️  --output-format not supported — upgrade claude for structured output"
fi
```

---

**For OpenCode and other tools — check headless flags, apply universal env vars:**

Each tool has its own headless flag (`--no-interactive`, `--headless`, `--json`, `--quiet` — check `tool --help`). The `NO_COLOR=1 TERM=dumb` prefix applies universally.

```bash
# OpenCode headless (flags vary by version — verify with --help)
NO_COLOR=1 TERM=dumb \
  opencode run \
    --no-input \
    --model "$model" \
    < "$prompt_file" \
  2>&1 | tee "$output_log"

# Nuclear option: setsid creates a new session with NO controlling terminal at all.
# Use when the tool tries to open /dev/tty directly (bypasses stdin check).
# Trade-off: tools that legitimately need /dev/tty for auth prompts will fail.
_headless_setsid() {
  NO_COLOR=1 TERM=dumb setsid "$@" < /dev/null
}
```

---

**Verifying your invocation is truly headless (add to test suite):**

```bash
# Uses cheapest model — just verifies headless connectivity and flag combination
echo 'Use the Write tool to create /tmp/headless_test_'"$$"'.txt with content "ok"' \
  | NO_COLOR=1 TERM=dumb env -u CLAUDECODE \
    timeout 60s claude \
      --model claude-haiku-4-5-20251001 \
      --dangerously-skip-permissions \
      --allowedTools "Write" \
      2>/dev/null

if [[ -f "/tmp/headless_test_$$.txt" ]]; then
  echo "✅ Headless invocation working"
  rm "/tmp/headless_test_$$.txt"
else
  echo "❌ Headless invocation failed — check flags and env vars"
  exit 1
fi
```

**Context-specific behaviour to know:**

| Runtime context | Risk | Mitigation |
|-----------------|------|------------|
| Terminal (interactive) | Tool detects TTY and launches TUI | `NO_COLOR=1 TERM=dumb` + stdin redirect |
| tmux pane | Has PTY — same risk as terminal | Same as above |
| SSH without `-t` | No PTY — tools requiring terminal crash | `--dangerously-skip-permissions` prevents most prompts |
| cron / systemd | No terminal; stdin is `/dev/null` | Safest context; tools opening `/dev/tty` directly still crash → use `setsid` |
| Inside Claude Code terminal | Inherits `CLAUDECODE` env var | `env -u CLAUDECODE` (Lesson 1) |

---

#### 38. **`set -euo pipefail` + `grep` Silent-Kill Gotcha**

**Problem:** `grep` exits with code 1 when it finds no matches — which is not an error, just an empty result. But with `set -euo pipefail` active, exit code 1 from any command in a pipeline or subshell kills the entire script silently, with no error message and no indication of where it died.

**Real scenario that triggered this:** Reading cycle count from `progress.md`:

```bash
# Script has set -euo pipefail at the top.
# progress.md exists but has NO "## Cycle" lines —
# cycles 1-4 were failed API hangs that timed out before writing anything.

LAST_CYCLE=$(grep -c "^## Cycle" progress.md)
#                 ↑ grep returns exit code 1 (no matches)
#                   pipefail propagates it
#                   set -e silently kills the script here
#                   LAST_CYCLE is never set
#                   loop never starts, no error printed
```

The operator sees the script start, print the banner, then stop — with exit code 1 and zero explanation.

**Why it's insidious:** The file exists (no `set -u` violation), the command is syntactically valid, and the "no matches" result is the correct answer in early cycles. It looks like the script is working until you notice it never reaches the first iteration.

**Solution: always add a `|| fallback` for any `grep` used to read state:**

```bash
# WRONG — kills script when progress.md has no cycle headers yet
LAST_CYCLE=$(grep -c "^## Cycle" progress.md)

# CORRECT — returns 0 when no matches, continues normally
LAST_CYCLE=$(grep -c "^## Cycle" progress.md || echo "0")

# Also correct — explicit exit code suppression
LAST_CYCLE=$(grep -c "^## Cycle" progress.md || true; echo "${PIPESTATUS[0]:-0}")

# For grep used as a condition (not capturing output) — || true is enough
if grep -q "^## Cycle" progress.md || true; then ...
# But better: let the if-statement handle the exit code naturally
if grep -q "^## Cycle" progress.md; then
  ...  # grep exit code is consumed by if — set -e does NOT fire here
fi
```

**Key rule:** `grep` inside an `if` condition or after `||` is safe — `set -e` only fires on unchecked non-zero exits. `grep` in a bare assignment or pipeline is dangerous.

**Full pattern for safe state reading:**

```bash
# All state-reading grep calls in a ralph loop — use this template
CYCLE_COUNT=$(grep -c "^## Cycle"    progress.md 2>/dev/null || echo "0")
LAST_SCORE=$(grep -oP "score: \K[\d.]+" progress.md 2>/dev/null | tail -1 || echo "0")
HAS_ERROR=$(grep -c "^ERROR:"        progress.md 2>/dev/null || echo "0")

# For multi-line extraction into a variable:
FAILED_STEPS=$(grep "^- \[FAILED\]" tasks.md 2>/dev/null || true)
# $FAILED_STEPS is empty string when no failures — that's the correct answer
```

**Also applies to:** `wc -l` on empty files (exits 0, safe), `awk` (exits 0 on no match, safe), `sed` (exits 0, safe) — `grep` is uniquely dangerous because it's the only common text-processing tool that returns exit code 1 on "no match found".

**Add to dry-run validation:**
```bash
# Verify grep fallback pattern works in this shell environment
test_result=$(grep -c "NONEXISTENT_PATTERN" /dev/null 2>/dev/null || echo "0")
[[ "$test_result" == "0" ]] || { echo "ERROR: grep fallback pattern broken"; exit 1; }
echo "✅ grep || fallback pattern verified"
```

---

#### 39. **Live API Ping Inside Dry-Run: Use the Exact Same `run_subagent` Construction**

**Problem:** The dry-run phase (Lesson 5) validates flags with `--help` and checks that binaries exist — but it tests a *different code path* than the actual loop. The real `run_subagent` function may have a subtly broken flag combination, a bad env var order, a misquoted argument, or an output-format mismatch that `--help` parsing can't catch. The operator only discovers this at cycle 1, after the loop has already started.

**Root cause:** Lesson 5's test call is written inline, simplified, and often diverges from the actual `run_subagent` wrapper as the script evolves. They drift apart.

**Solution:** At the end of dry-run, call the real `run_subagent` function (not a simplified copy) with the cheapest available model and a trivial "connection ping" prompt. This exercises the entire stack — env vars, flags, stdin redirect, output parsing, file I/O — in one shot.

```bash
# At the END of the dry-run block, after all static checks pass:
if $DRY_RUN; then
  echo ""
  echo "=== Live API ping (cheapest model, real run_subagent construction) ==="

  PING_PROMPT_FILE="$STEPS_DIR/ping_prompt.txt"
  PING_OUTPUT_FILE="$STEPS_DIR/ping_output.json"

  # Write the simplest possible prompt that requires a tool call + file write
  cat > "$PING_PROMPT_FILE" <<'EOF'
You are a connection ping test. Your only task:
Use the Write tool to create the file at the path given to you with exactly this JSON content:
{"status": "pong", "ok": true}

The file path is: PING_OUTPUT_FILE_PLACEHOLDER
Do not read any other files. Do not think. Just write the file and stop.
EOF
  # Substitute the actual path (heredoc can't expand variables directly inside single-quote EOF)
  sed -i "s|PING_OUTPUT_FILE_PLACEHOLDER|$PING_OUTPUT_FILE|g" "$PING_PROMPT_FILE"

  # ⚠️ CRITICAL: call run_subagent — NOT a hand-rolled claude call.
  # This is the whole point: we test the real wrapper, not a simplified copy.
  # Use MODEL_PING (Haiku) — cheapest model, connection test only, no reasoning needed.
  MODEL_PING="${RALPH_MODEL_PING:-claude-haiku-4-5-20251001}"

  if run_subagent "ping" "$PING_PROMPT_FILE" "$PING_OUTPUT_FILE" 2 "$MODEL_PING"; then
    if [[ -f "$PING_OUTPUT_FILE" ]] && grep -q '"ok": true' "$PING_OUTPUT_FILE" 2>/dev/null; then
      echo "✅ Live API ping succeeded — full run_subagent stack verified"
      rm -f "$PING_PROMPT_FILE" "$PING_OUTPUT_FILE"
    else
      echo "❌ Ping prompt ran but output file missing or malformed"
      echo "   Expected: $PING_OUTPUT_FILE"
      [[ -f "$PING_OUTPUT_FILE" ]] && echo "   Got: $(cat "$PING_OUTPUT_FILE")"
      exit 1
    fi
  else
    echo "❌ Live API ping failed — run_subagent returned non-zero"
    echo "   Check: $STEPS_DIR/ping_output.log and ping_debug.log"
    exit 1
  fi

  echo ""
  echo "✅ All dry-run checks passed. Ready to start the loop."
  echo "   Remove --dry-run to begin."
  exit 0
fi
```

**Why cheapest model (Haiku), not Sonnet or Opus:**
- The ping test proves connectivity and flag correctness — not reasoning quality
- Haiku responds in seconds; Sonnet takes longer and costs 5× more per test
- A failed ping on Haiku means the whole stack is broken — model choice is irrelevant
- A passing ping on Haiku does NOT mean Opus will work for planning (auth/model name could differ) — but those failures are caught immediately at cycle 1, not silently

**What this catches that `--help` checks miss:**

| Issue | `--help` check | Live ping |
|-------|---------------|-----------|
| Invalid API key / expired token | ✗ | ✅ |
| Wrong model name (typo in MODEL_PLAN) | ✗ | ✅ (catches MODEL_PING at minimum) |
| `--output-format` flag broken in this version | ✗ | ✅ |
| `run_subagent` file-path bug (wrong STEPS_DIR) | ✗ | ✅ |
| stdin redirect failing due to shell quoting | ✗ | ✅ |
| `env -u CLAUDECODE` stripping needed var | ✗ | ✅ |
| Rate limit already hit before loop starts | ✗ | ✅ |
| `NO_COLOR`/`TERM=dumb` breaking output parsing | ✗ | ✅ |

**Also update Lesson 5** when implementing this: replace its hand-rolled test call with a pointer to this pattern — "use `run_subagent` directly, not an inline copy."

---

#### 36. **Verbose ON by Default + Model Tiering (Opus for Planning, Sonnet for Execution)**

**Two separate problems, always discovered together:**

---

**Problem A — Verbose off by default:**
Lesson 10 added `VERBOSE=false` as the default, requiring `--verbose` to get any diagnostic output. In practice, long autonomous loops run unattended overnight and the operator has zero visibility when something goes wrong. Reconstructing failures from silent logs is painful.

**Solution:** Flip the default — verbose is ON, quietness requires opt-in:

```bash
# WRONG (Lesson 10 default — blind by default)
VERBOSE=false
for arg in "$@"; do
  case "$arg" in --verbose|-v) VERBOSE=true ;; esac
done

# CORRECT — verbose on, opt out with --quiet
VERBOSE=true
for arg in "$@"; do
  case "$arg" in --quiet|-q) VERBOSE=false ;; esac
done
```

With verbose ON by default, the `run_subagent` function should always pass `--verbose` and `--debug-file` to `claude`:

```bash
run_subagent() {
  local step_name="$1" prompt_file="$2" output_file="$3" timeout="${4:-30}" model="${5:-$MODEL_EXEC}"
  local debug_log="$LOGS_DIR/${step_name}_debug.log"

  if $VERBOSE; then
    echo "💡 Monitor: tail -f $debug_log"
  fi

  timeout "${timeout}m" env -u CLAUDECODE claude \
    --model "$model" \
    --dangerously-skip-permissions \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch,Skill" \
    --verbose \
    --debug-file "$debug_log" \
    < "$prompt_file" \
    2>&1 | tee "$LOGS_DIR/${step_name}_output.log"
}
```

**Why verbose is always worth the cost:** debug logs are written to file, not stdout — they don't clutter the terminal. `--verbose` adds negligible latency. The only reason to suppress it is disk space on very long runs (hundreds of cycles), which is the `--quiet` use case.

---

**Problem B — Flat model assignment (Sonnet everywhere):**
Every `claude` call uses `--model sonnet` regardless of what the step does. Planning and orientation steps (orient, hypothesize, review) require deep reasoning across large contexts. Execution steps (fix, validate, integrate) run narrowly scoped tasks that Sonnet handles well. Using Sonnet for planning underperforms; using Opus for execution wastes money.

**Solution:** Define two model constants and assign per step type:

```bash
# Model tier constants — set at top of runner script
MODEL_PLAN="${RALPH_MODEL_PLAN:-claude-opus-4-6}"    # Deep reasoning: orient, hypothesize, review, loop-improve
MODEL_EXEC="${RALPH_MODEL_EXEC:-claude-sonnet-4-6}"  # Narrow execution: fix, validate, integrate, hygiene

# Allow override via env vars for cost experiments:
#   RALPH_MODEL_PLAN=claude-sonnet-4-6 ./ralph_loop.sh  # budget run
#   RALPH_MODEL_PLAN=claude-opus-4-6 ./ralph_loop.sh    # full quality
```

**Step → model mapping:**

| Step / Task type | Model | Reason |
|------------------|-------|--------|
| `orient` / `hypothesize` | `MODEL_PLAN` (Opus) | Reads all context, reasons across many experiments, sets direction |
| `review` / `loop-improve` | `MODEL_PLAN` (Opus) | Evaluating quality, identifying subtle flaws, meta-reasoning |
| `execute` / `implement` | `MODEL_EXEC` (Sonnet) | Follows a concrete plan, bounded scope |
| `validate` / `fix` | `MODEL_EXEC` (Sonnet) | Deterministic checks, targeted edits |
| `integrate` / `hygiene` | `MODEL_EXEC` (Sonnet) | Mechanical: run checks, apply patches |

**Implementation in `run_subagent` (model as 5th arg with per-call default):**

```bash
# Planning steps — pass MODEL_PLAN
run_subagent "orient"      "$PROMPT_DIR/orient.md"      "$STATE/orient.json"      60 "$MODEL_PLAN"
run_subagent "hypothesize" "$PROMPT_DIR/hypothesize.md" "$STATE/hypothesis.json"  45 "$MODEL_PLAN"

# Execution steps — default MODEL_EXEC (arg can be omitted)
run_subagent "execute"     "$PROMPT_DIR/execute.md"     "$STATE/result.json"      90
run_subagent "validate"    "$PROMPT_DIR/validate.md"    "$STATE/validation.json"  30
run_subagent "fix"         "$PROMPT_DIR/fix.md"         "$STATE/fix.json"         45
```

**Cost vs quality trade-off:**
- A typical Ralph loop iteration: 1 Opus call (orient) + 3–4 Sonnet calls (execute/validate/fix)
- Opus is ~5× the cost of Sonnet per token but is only used for the high-leverage decision
- Net effect: ~30–40% higher cost per iteration vs all-Sonnet, but meaningfully better experiment direction and fewer wasted iterations (which saves more than the premium)
- For budget runs, set `RALPH_MODEL_PLAN=claude-sonnet-4-6` — the env var override makes this a one-liner

**Also update Lesson 10 when implementing this:** replace `VERBOSE=false` with `VERBOSE=true` and `--verbose|-v` with `--quiet|-q` in all existing runner scripts.

---

#### 40. **Mandatory Dry-Run + Full Roundtrip Test Immediately After Scaffolding**

**Problem:** The `/ralph-loop` skill generates a complete runner script, prompt files, and state directory structure. The operator then tries to run it for real — and discovers on cycle 1 that a prompt path is wrong, an output file is expected in the wrong directory, or the state machine never transitions because the orient step writes `orient.json` but the loop reads `step_orient.json`.

These are structural bugs introduced during scaffolding, not API issues. They are invisible to the live API ping (Lesson 39), which only tests the wrapper function itself.

**Solution:** The skill itself must run `./ralph_loop.sh --dry-run` immediately after generating all files, then run a single real cycle (`--budget 1`) with the cheapest model before handing off to the operator. This is the acceptance test for the scaffolded loop.

**Sequence the skill must follow after generating files:**

```
Step 1: Static dry-run (flag checks, jq, python3, permissions)
         → ./ralph_loop.sh --dry-run
         → Must exit 0 before proceeding

Step 2: Live API ping (Lesson 39 — real run_subagent, Haiku model)
         → Embedded in --dry-run block
         → Must produce ping_output.json with {"ok": true}

Step 3: Single real cycle roundtrip (--budget 1, cheapest models)
         → RALPH_MODEL_PLAN=claude-haiku-4-5-20251001 \
           RALPH_MODEL_EXEC=claude-haiku-4-5-20251001 \
           ./ralph_loop.sh 1
         → Must complete cycle 1 without error
         → Must produce the expected state files for cycle 1
         → Must write at least one entry to progress.md

Step 4: Report to operator
         → Print what was created, what was verified, what the operator should do next
         → Only reach this step if Steps 1-3 all passed
```

**Implementation in the skill (what the `/ralph-loop` skill agent must do):**

```bash
# After generating all files, run this sequence:
echo "=== Step 1: Static dry-run ==="
./ralph_loop.sh --dry-run || {
  echo "❌ Dry-run failed — fix issues above before proceeding"
  exit 1
}

echo ""
echo "=== Step 3: Single real cycle (cheapest models, budget=1) ==="
echo "This verifies the full state machine: orient → execute → evaluate → progress.md"
RALPH_MODEL_PLAN=claude-haiku-4-5-20251001 \
RALPH_MODEL_EXEC=claude-haiku-4-5-20251001 \
  ./ralph_loop.sh 1 || {
  echo "❌ Cycle 1 failed — check logs in $LOGS_DIR/"
  exit 1
}

# Verify state files were actually written
expected_files=(
  "experiments/steps/orient.json"
  "experiments/progress.md"
)
for f in "${expected_files[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "❌ Expected state file missing after cycle 1: $f"
    exit 1
  fi
done

echo ""
echo "✅ Full roundtrip verified. Loop is ready."
echo ""
echo "To run for real:"
echo "  ./ralph_loop.sh 20          # 20 cycles, default models"
echo "  ./ralph_loop.sh 20 --quiet  # suppress verbose output"
```

**Why Haiku for the roundtrip test, not Sonnet or Opus:**
- The roundtrip test validates *structure*, not reasoning quality — did the prompt produce the expected output file with the expected schema?
- Haiku is fast (~30s per step vs 2–5 min for Opus) — the operator gets confirmation within 2–3 minutes
- If Haiku produces a correctly-structured output file, the state machine works; Opus will produce a better-quality file through the same working machinery
- Cost: ~$0.01–0.05 for a Haiku roundtrip vs $1–5 for an Opus one

**What a passing roundtrip proves vs what it doesn't:**

| Verified by roundtrip ✅ | NOT verified ❌ |
|--------------------------|----------------|
| Prompt file paths correct | Reasoning quality of orient step |
| Output file naming matches loop expectations | Hypothesis quality |
| State transitions (orient → execute → evaluate) work | Whether the ML task is solvable |
| progress.md gets written | Rate limit behaviour over 20+ cycles |
| Logging/debug-file paths work | Long-run resilience |
| Flag combination works with real API call | Cost at full Opus scale |

**The contract:** The `/ralph-loop` skill must not exit with "done" until the roundtrip passes. Handing an untested loop to the operator is not done.

---

#### 41. **Haiku for Mechanical Steps (Orient + Finalize) — Use `MODEL_LIGHT` Variable**

**Problem:** Orient and finalize are the most mechanical steps in any fixed-step Ralph loop: orient reads state files and writes a templated summary; finalize marks tasks done and appends a structured progress entry. Running these on Sonnet or Opus wastes budget — they require no creative reasoning.

**Impact:** Significant per-cycle cost reduction (80–90% cheaper per step) with zero quality loss. If orient writes something wrong, plan/execute will catch it. If finalize writes something wrong, the next cycle's orient will flag it.

**Solution:** Introduce a `MODEL_LIGHT` variable (default: `haiku`) used only for orient and finalize:

```bash
MODEL="sonnet"        # execute/critic — code writing and reasoning
MODEL_LIGHT="haiku"   # orient/finalize — mechanical read-summarize-write

# CLI override: --model-light=sonnet to promote if needed
for arg in "$@"; do
  case "$arg" in
    --model=*)        MODEL="${arg#--model=}" ;;
    --model-light=*)  MODEL_LIGHT="${arg#--model-light=}" ;;
  esac
done

# In run_subagent calls:
run_subagent "orient"   "$prompt" "$TIMEOUT_ORIENT"   "$MODEL_LIGHT"
run_subagent "plan"     "$prompt" "$TIMEOUT_PLAN"     "opus"         # explicit
run_subagent "execute"  "$prompt" "$TIMEOUT_EXECUTE"               # uses $MODEL
run_subagent "critic"   "$prompt" "$TIMEOUT_CRITIC"                # uses $MODEL
run_subagent "finalize" "$prompt" "$TIMEOUT_FINALIZE"  "$MODEL_LIGHT"
```

**Startup log:** Print both models so the operator sees at a glance:
```bash
_log "Model: $MODEL (execute/critic) | $MODEL_LIGHT (orient/finalize)"
```

**Rule of thumb for step classification:**
- **Haiku-eligible:** reads files → runs grep/shell commands → writes templated markdown. Zero novel reasoning.
- **Sonnet:** writes code, interprets error messages, iterates on failures.
- **Opus:** selects task strategy, designs proof/experiment approach, makes architectural decisions.

**Related lessons:** Lesson 36 (model tiering philosophy), Lesson 29 (step timeout calibration)

---

#### 42. **OpenCode as Alternative Execute Engine — `opencode run` vs `claude -p` Differences**

**Context:** OpenCode (`~/.opencode/bin/opencode`, installed via `curl -fsSL https://opencode.ai/install | bash`) is a provider-agnostic coding agent that can run models from OpenRouter, Anthropic, Google, and others. It is an alternative to `claude -p` for the execute step, useful for cost arbitrage (e.g. MiniMax M2.5 via OpenRouter).

**Verified working (tested 2026-03-07, opencode v1.2.20):**
- Model flag: `--model openrouter/minimax/minimax-m2.5`
- Non-interactive: `opencode run "prompt text"` (positional arg, NOT `-p`)
- File tools (read/write/edit): work correctly
- Bash tool: works correctly
- Auth: stored in `~/.local/share/opencode/auth.json` via `opencode auth login` — NOT env vars by default
- List available models: `opencode models openrouter`
- Check auth: `opencode auth list`

**Critical gotchas:**

1. **`--format json` is required for clean exit.** `--format default` (the default) hangs after bash tool use and never exits (exit 124). Always use `--format json` in non-interactive pipelines:
   ```bash
   timeout "${timeout_min}m" /home/martin/.opencode/bin/opencode run \
     --model openrouter/minimax/minimax-m2.5 \
     --format json \
     --dir "$PROJECT_DIR" \
     "$prompt_text" \
     </dev/null > "$output_log" 2>&1
   ```

2. **No `env -u CLAUDECODE` needed.** OpenCode is a different process — Lesson 1's CLAUDECODE gotcha does not apply.

3. **No `--dangerously-skip-permissions` or `--allowedTools`.** Tools are allowed by default. Permission control is config-based only (`~/.config/opencode/opencode.json`). No CLI flag equivalent.

4. **No `-p` flag.** The prompt is a positional argument to `opencode run`, not a flag. For long prompts (step prompt files can be 3–5 KB), this is fine — Linux arg limit is ~128 KB. Quote the variable: `"$prompt_text"`.

5. **`--format json` output in log files.** The monitor's `tail -20 "$output_log"` will show raw JSON events instead of human-readable text. This is acceptable for automation; add a jq post-processor if readability matters.

6. **Bash tool timeout for long-running commands is unverified.** `lake build` takes 15–30 minutes. OpenCode's internal bash tool timeout may be shorter than the step's outer `timeout` wrapper. Test explicitly before deploying to heavy execute tasks.

7. **Bash execution overhead.** A single bash tool call (tool invocation + model response) takes ~25 seconds with MiniMax M2.5 via OpenRouter, vs ~3.7 seconds for text-only. Budget accordingly.

**Dry-run ping test for OpenCode (add to the loop's `--dry-run` section):**
```bash
if command -v opencode &>/dev/null || [[ -x "$HOME/.opencode/bin/opencode" ]]; then
  OPENCODE_BIN="${HOME}/.opencode/bin/opencode"
  PING_LOG="$LOGS_DIR/ping_opencode_$$.log"
  timeout 30s "$OPENCODE_BIN" run \
    --model openrouter/minimax/minimax-m2.5 \
    --format json \
    "Reply with exactly: PONG" \
    </dev/null > "$PING_LOG" 2>&1
  if grep -q '"text":"PONG"' "$PING_LOG" 2>/dev/null; then
    echo "  OpenCode ping: OK"
  else
    echo "  OpenCode ping: FAILED — check $PING_LOG"
  fi
fi
```

**Implementation pattern — `--engine` flag for swappable backends:**
```bash
ENGINE="claude"   # or "opencode"
for arg in "$@"; do
  case "$arg" in --engine=*) ENGINE="${arg#--engine=}" ;; esac
done

run_execute_step() {
  local prompt_file="$1" timeout_min="$2" output_log="$3"
  case "$ENGINE" in
    opencode)
      timeout "${timeout_min}m" "$HOME/.opencode/bin/opencode" run \
        --model openrouter/minimax/minimax-m2.5 --format json \
        --dir "$PROJECT_DIR" "$(cat "$prompt_file")" \
        </dev/null > "$output_log" 2>&1 ;;
    *)
      timeout "${timeout_min}m" env -u CLAUDECODE claude \
        --model "$MODEL" --dangerously-skip-permissions \
        --allowedTools "Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch,Task" \
        -p "$(cat "$prompt_file")" \
        </dev/null > "$output_log" 2>&1 ;;
  esac
}
```

**Related lessons:** Lesson 1 (CLAUDECODE env var), Lesson 37 (force headless), Lesson 39 (live ping test)

**Additional gotchas discovered 2026-04-05 (multi-provider routing in production):**

8. **`XDG_DATA_HOME` temp-dir isolation breaks auth.** The common pattern of using `XDG_DATA_HOME="$(mktemp -d /tmp/opencode_XXXXXX)"` to isolate concurrent opencode sessions means the new dir has no `auth.json` — so all providers fail with "API key is missing" even though `opencode auth login` was run successfully. Fix: create the temp dir first, copy `~/.local/share/opencode/auth.json` into it, then set `XDG_DATA_HOME`:
   ```bash
   _oc_data="$(mktemp -d /tmp/opencode_XXXXXX)"
   mkdir -p "$_oc_data/opencode"
   local _auth_src="$HOME/.local/share/opencode/auth.json"
   if [[ -f "$_auth_src" ]]; then
     cp "$_auth_src" "$_oc_data/opencode/auth.json"
   fi
   timeout "${timeout_min}m" setsid env __EXECWRAP_ACTIVE=1 XDG_DATA_HOME="$_oc_data" \
     "$OPENCODE_BIN" run --model "$step_model" --format json \
     </dev/null "$prompt_text" > "$output_log" 2>&1
   ```

9. **Auth location is `~/.local/share/opencode/auth.json`, NOT env vars.** After `opencode auth login` for any provider, the key is stored there — NOT in `~/.bashrc` or the shell environment. The file is keyed by provider ID (e.g. `"nvidia"`, `"openai"`, `"mistral"`). Check it with `cat ~/.local/share/opencode/auth.json | python3 -c "import json,sys; [print(k) for k in json.load(sys.stdin)]"`. If a provider is missing, the login wasn't completed for it.

10. **execwrap loads `.env` but does NOT export vars to child processes.** If your loop sources `.env` inside an `if ! $DRY_RUN` block, opencode (spawned during the live run) will not inherit those env vars. Source `.env` unconditionally at script startup with `set -a`:
    ```bash
    if [[ -f "$PROJECT_DIR/.env" ]]; then
      set -a; source "$PROJECT_DIR/.env" 2>/dev/null || true; set +a
    fi
    ```
    This applies to both dry-run pings and live execution. Without it, providers that fall back to env-var auth (e.g. OpenAI's `OPENAI_API_KEY`) will fail even when the key is in `.env`.

11. **Model string prefix must match provider key in `opencode.json`.** The model string `nvidia/moonshotai/kimi-k2.5` means: provider key = `nvidia`, model ID = `moonshotai/kimi-k2.5`. If you write `moonshotai/kimi-k2.5` (no `nvidia/` prefix), opencode looks for a provider keyed `moonshotai` which doesn't exist → timeout/404. Always use `providerKey/modelId` format.

12. **`tool_call: true` required in `opencode.json` for tool-using models.** Models that need function-calling (all non-trivial steps) must have `"tool_call": true` in their model entry in `~/.config/opencode/opencode.json`. Without it the model receives no tools and cannot read/write files. This is NOT the default.

14. **Some models ignore "PONG" and start working — relax the ping success check.** Leanstral (and similar instruction-following specialist models) respond to "Reply with exactly: PONG" by starting actual research work instead. This is still a valid connectivity proof. The ping check should accept: PONG found in output OR (exit=0 AND output >500B AND no auth/provider error string). Never fail a ping solely because the model didn't echo "PONG".

13. **`_engine()` must cover all non-claude prefixes.** The routing function `_engine() { [[ "$1" == nvidia/* ]] || ... && echo "opencode" || echo "claude"; }` must include every provider prefix you add. Adding a new provider (e.g. `openai/`) without updating `_engine()` silently routes it via the claude CLI, which fails with an unknown model error. Keep the function in sync with `MODEL_*` variables.

---

#### 43. **Permanent Library/Mathlib Gap Tasks — Never Just "Retry in N Cycles"**

**Problem:** When a task is blocked because a theorem or library function is missing from the underlying formal library (e.g. Mathlib for Lean 4), the common pattern is to write "BLOCKED — retry in N cycles" and move on. After 20 cycles, the search runs again, finds nothing, and schedules another retry. This is a spinning wheel that produces no lasting value.

**Impact:** Confirmed library gaps get rediscovered repeatedly (often 5–10 times across 100+ cycles) with no accumulated documentation. Upstream contribution opportunities are missed. The gap is never communicated to the library maintainers.

**Solution:** When a search confirms a library gap, immediately create a permanent `task:library-gap-[name]` (or `task:mathlib-gap-[name]`) task with five required fields:

```
task:mathlib-gap-[theorem-name] [P3]
What is missing: <exact Lean 4 / library stub that would be needed>
Why absent: <unformalized deep result | API design gap | open math problem>
Proof sketch: <how it would be proved; textbook reference>
Upstream PR path: <which file, what dependencies, realistic estimate of effort>
Workaround: <weaker version or specialization sufficient for our use>
Status: DOCUMENTED — not yet attempted as PR
```

This gap task lives **alongside** the blocked task, not as a replacement. The blocked task still gets retried (e.g., when a major library version drops); the gap task ensures every retry has prior context and can be escalated to an upstream PR.

**Implementation — orient audit:** At the start of every cycle, orient should scan the task queue for BLOCKED/PENDING-RETRY tasks and flag any that lack a corresponding gap task:

> ⚠️ MATHLIB GAP NOT DOCUMENTED: `task:[name]` is BLOCKED by missing library infrastructure but no `task:mathlib-gap-[name]` exists. Create it this cycle.

**Implementation — finalize gate:** In finalize, after updating tasks.md, check: did this cycle confirm a library gap? If yes and no gap task exists → create it before exiting.

**Example gap tasks from the Schanuel→RH Lean loop:**
- `task:mathlib-gap-weyl-equidistribution` — `MeasureTheory.Weyl` for T^k not in Mathlib 4.28; needed for Baker compact nonzero step 2
- `task:mathlib-gap-zfr-critical-strip` — classical zero-free region for ζ in Re(s) ∈ (0,1); only Re(s) ≥ 1 available
- `task:mathlib-gap-eta-deriv-sign` — `HasDerivAt riemannZeta` for Re(s) < 1; no signed derivative results in Mathlib 4.28

**Key insight:** Discovered gaps are research outputs. They belong in version control alongside the proofs. They can seed upstream Mathlib PRs, motivate new formalization projects, or serve as the exact spec when someone else wants to contribute.

**Related lessons:** Lesson 32 (one reviewer pass then move on), Lesson 33 (hygiene task injection), Lesson 35 (meta-loop self-improvement)

---

#### 44. **Pre-Digest Large State Files Before the Orient Step**

**Problem:** As the loop runs, state files grow large. `tasks.md` accumulates hundreds of completed tasks; `progress.md` accumulates hundreds of cycle entries. The orient step is instructed to read both files to understand current state. A model that reads them in full wastes most of its context window on irrelevant history, producing slow, costly, and bloated orient outputs.

**Real example:** After 150+ cycles, `tasks.md` grew to 1483 lines (143 completed tasks + 4 pending), and `progress.md` to 2148 lines. The orient model read both in full — producing 163KB of output — when it only needed the 4 pending task blocks (~120 lines) and the last 5 cycle entries (~70 lines).

**Solution:** Add a `build_orient_context()` function in the orchestrator script that pre-digests the state files in bash before the orient step runs, and injects the condensed result directly into the prompt header:

```bash
build_orient_context() {
  local output="$STEPS_DIR/orient_context.md"
  {
    echo "# Pre-Digested State Context (auto-generated)"
    echo ""
    # tasks.md: header/current-state section (first ~80 lines)
    echo "## Tasks — Header and Current State"
    head -80 "$TASKS"
    echo ""
    # tasks.md: each pending task block (a few lines of context around each [ ])
    echo "## Pending Tasks (all \`- [ ]\` items)"
    grep -n '^\- \[ \]' "$TASKS" | while IFS=: read -r lineno _; do
      local start=$(( lineno > 3 ? lineno - 3 : 1 ))
      local end=$(( lineno + 35 ))
      sed -n "${start},${end}p" "$TASKS"
      echo "---"
    done
    # progress.md: last 5 cycles only
    echo "## Recent Progress — Last 5 Cycles"
    local cycle_start
    cycle_start=$(grep -n '^## Cycle' "$PROGRESS" | tail -5 | head -1 | cut -d: -f1)
    sed -n "${cycle_start},\$p" "$PROGRESS"
  } > "$output"
  echo "$output"
}
```

Then in `build_prompt()`, detect the orient step and inject this context before the prompt template:

```bash
if [[ "$step_name" == "step1_orient" ]]; then
  local ctx_file
  ctx_file=$(build_orient_context)
  cat "$ctx_file" >> "$output"
fi
```

Update the orient prompt template to say: **use the pre-injected context above**; if you need to look up a specific older task or cycle, you may read the files directly, but do so in small targeted chunks using `offset` and `limit` — not the full file.

**Results:** 3631 lines → 321 lines; ~180KB → 32KB — an 11x compression. Orient becomes faster, cheaper, and more focused.

**Key insight:** Orient is a summarisation step, not an archaeology step. Pre-digest in bash (cheap, deterministic) what the model would otherwise summarise at LLM cost. The model should spend its context budget on the lean-check output and previous step results, not scrolling through completed history.

---

#### 45. **Rate-Limit Detection Must Be Gated on Step Failure**

**Problem:** The classic rate-limit check pattern — `grep -qi "rate.limit\|429" "$output_log"` — fires on any text match in the output log, regardless of whether the step actually succeeded. This causes false-positive 10-minute waits when a step completes successfully but the provider retried a transient 429 internally and logged it.

**Real example:** MiniMax M2.5 via NVIDIA NIM retried a transient 429 mid-stream, producing a successful response (exit 0, output file written). But the 429 text leaked into the captured log. The orchestrator saw the pattern, waited 10 minutes, and re-ran the orient step — wasting a full cycle.

**Anti-pattern:**
```bash
# ❌ BAD: fires even when exit_code=0
if grep -qi "rate.limit\|hit your limit\|too many requests\|429" "$output_log"; then
  sleep 600
  continue
fi

if [[ "$exit_code" -ne 0 ]]; then
  return "$exit_code"
fi
return 0
```

**Solution:** Gate the rate-limit check inside the non-zero exit branch:

```bash
# ✅ CORRECT: only check for rate limit when the step actually failed
if [[ "$exit_code" -ne 0 ]]; then
  if grep -qi "rate.limit\|hit your limit\|too many requests\|429" "$output_log"; then
    _log "[$step_name] Rate limit detected (exit $exit_code). Waiting 10 minutes..."
    sleep 600
    attempt=$((attempt + 1))
    [[ $attempt -le $max_hang_retries ]] && continue
  fi
  _log "[$step_name] FAILED (exit $exit_code)"
  return "$exit_code"
fi
_log "[$step_name] COMPLETED"
return 0
```

**Why providers emit 429 in successful responses:** Many provider SDKs (including opencode) handle rate limits transparently via exponential backoff. The retry happens inside the SDK, the final response is successful, but the 429 text may appear in stderr or the JSON streaming output — which gets captured in the log.

**Key insight:** The exit code is the authoritative signal. Log text is diagnostic, not control flow. Only use log text to *characterise* a failure (e.g. distinguish rate limit from timeout), never to *detect* one on its own.

**Related lessons:** Lesson 12 (rate limit handling), Lesson 34 (heartbeat + auto-retry for API hangs)

---

### Quick Reference Template for Runner Scripts

#### **Template 1: Fixed-Step Loop (Simple)**

```bash
#!/usr/bin/env bash
set -euo pipefail

# ... argument parsing ...

# Helper: run subagent with proper validation
run_subagent() {
  local step_name="$1"
  local prompt="$2"
  local output_file="$3"
  local timeout="${4:-30}"

  echo "[$step_name] Starting (timeout: ${timeout}m, output: $output_file)"

  # Write prompt to file (handles multi-line prompts reliably)
  local prompt_file="$STEPS_DIR/${step_name}_prompt.txt"
  echo "$prompt" > "$prompt_file"
  echo "Prompt saved: $prompt_file ($(wc -c < "$prompt_file") bytes)"

  # Run claude via stdin with all critical flags
  timeout "${timeout}m" env -u CLAUDECODE claude --model sonnet \
    --dangerously-skip-permissions \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch,Skill" \
    < "$prompt_file" \
    2>&1 | tee "$STEPS_DIR/${step_name}_output.log"

  # Validate by checking output file, NOT exit code or stdout
  if [[ -f "$output_file" && -s "$output_file" ]]; then
    echo "✅ [$step_name] Completed"
    return 0
  else
    echo "❌ [$step_name] Failed - no output file"
    tail -20 "$STEPS_DIR/${step_name}_output.log"
    return 1
  fi
}

# Dry run: test claude CLI
if $DRY_RUN; then
  echo "Testing claude CLI..."
  TEST_FILE="/tmp/ralph_test_$$.json"

  # Test via stdin (recommended)
  echo 'Use Write tool to create /tmp/ralph_test_'"$$"'.json with {"test":true}' | \
    env -u CLAUDECODE claude --model sonnet \
      --dangerously-skip-permissions --allowedTools "Write" >/dev/null 2>&1

  [[ -f "$TEST_FILE" ]] && rm "$TEST_FILE" || { echo "❌ claude test failed"; exit 1; }
  echo "✅ All checks passed"
  exit 0
fi

# Main loop with resume support
START_ITER=1
[[ "$RESUME" == "true" ]] && START_ITER=$(($(jq -r '.iteration_count' "$TREE") + 1))

# ⚠️ CRITICAL: Use count=$((count+1)) NOT ((count++)) with set -e
for ((i=START_ITER; i<=BUDGET; i++)); do
  echo "=== Iteration $i / $BUDGET ==="
  rm -f "$STEPS_DIR"/*.json  # Clean state

  # Run steps
  run_subagent "step1" "$PROMPT1" "$STEPS_DIR/step1.json" 10 || continue
  run_subagent "step2" "$PROMPT2" "$STEPS_DIR/step2.json" 20 || continue
  # ... more steps ...

  # Update state
  python update_state.py
  git add -A && git commit -m "iteration $i" --no-verify
done
```

#### **Template 2: Task Queue Loop (Advanced)**

```bash
#!/usr/bin/env bash
set -euo pipefail

# ... argument parsing ...

# Helper: Pop highest priority task from queue
pop_task() {
  local task_json=$(jq -c '.queue | sort_by(-.priority) | .[0]' "$TASKS")

  if [[ "$task_json" == "null" || "$task_json" == "" ]]; then
    return 1
  fi

  # ✅ CORRECT: Filter out by ID, not del()
  local task_id=$(echo "$task_json" | jq -r '.id')
  jq --arg id "$task_id" '.queue = [.queue[] | select(.id != $id)]' "$TASKS" > "$TASKS.tmp"
  mv "$TASKS.tmp" "$TASKS"

  echo "$task_json"
  return 0
}

# Helper: Add task to queue
add_task() {
  local task_type="$1"
  local priority="$2"
  local description="$3"

  local task_id="${task_type}_$(date +%s)"

  jq --arg id "$task_id" \
     --arg type "$task_type" \
     --argjson prio "$priority" \
     --arg desc "$description" \
     '.queue += [{
       "id": $id,
       "type": $type,
       "priority": $prio,
       "description": $desc,
       "created_at": "'$(date -Iseconds)'"
     }]' "$TASKS" > "$TASKS.tmp"
  mv "$TASKS.tmp" "$TASKS"

  echo "➕ Added: [$priority] $task_type - $description"
}

# Main task queue loop
task_count=0

# ⚠️ CRITICAL: Use count=$((count+1)) NOT ((count++)) with set -e
while [[ $task_count -lt $BUDGET ]]; do
  task_count=$((task_count + 1))  # ✅ Safe with set -e

  echo "=== Task $task_count / $BUDGET ==="

  # Peek at next task (don't remove yet - Lesson 19)
  # ⚠️ CRITICAL: Disable set -e for command substitution that may fail (Lesson 18)
  set +e
  task=$(peek_task)
  exit_code=$?
  set -e

  if [[ $exit_code -ne 0 ]]; then
    echo "Queue empty"
    break
  fi

  # ⚠️ CRITICAL: Use regular variables, NOT local (only in functions)
  task_type=$(echo "$task" | jq -r '.type')  # ✅ No 'local' here
  task_id=$(echo "$task" | jq -r '.id')

  # Track if task succeeds
  task_succeeded=false

  # Execute based on type
  case "$task_type" in
    validate)
      if run_subagent "validate" "$PROMPT" "$OUTPUT" 30; then
        # Validation passed
        add_task "integrate" 60 "Integrate to pipeline"
        task_succeeded=true
      else
        # Validation failed - insert FIX task
        add_task "fix" 98 "Fix validation errors"
        # Don't mark as succeeded - keep in queue
      fi
      ;;

    fix)
      if run_subagent "fix" "$PROMPT" "$OUTPUT" 45; then
        # After fix, always re-validate
        add_task "validate" 95 "Re-validate after fixes"
        task_succeeded=true
      fi
      ;;

    *)
      echo "Unknown task type: $task_type"
      ;;
  esac

  # ⚠️ CRITICAL: Only remove task if successful (Lesson 19)
  if $task_succeeded; then
    remove_task "$task_id"
    echo "✅ Task completed and removed"
  else
    echo "⚠️  Task failed - kept in queue for retry"
  fi
done
```

**Key differences between templates:**

| Aspect | Fixed-Step | Task Queue |
|--------|------------|------------|
| Loop variable | `for ((i=1; i<=N; i++))` | `while [[ count -lt N ]]` |
| Counter increment | Built into for loop | `count=$((count+1))` ⚠️ |
| State tracking | iteration number | task queue (JSON) |
| Failure handling | `|| continue` (skip iteration) | Insert FIX task (retry) |
| Use case | Simple, linear workflow | Complex, needs validation gates |

---

### Sources & References

- [Geoffrey Huntley — Ralph Wiggum technique](https://ghuntley.com/ralph/)
- [AIDE — Tree search for ML (Weco AI)](https://github.com/WecoAI/aideml)
- [pentoai/ml-ralph — Autonomous ML agent](https://github.com/pentoai/ml-ralph)
- [AI Scientist v2 — Progressive agentic tree search](https://github.com/SakanaAI/AI-Scientist-v2)
- [Alibaba — Two-loop self-evolving systems](https://arxiv.org/html/2602.10226)
- [Ralph Orchestrator — Git worktree isolation](https://github.com/mikeyobrien/ralph-orchestrator)
- [ClaytonFarr/ralph-playbook](https://github.com/ClaytonFarr/ralph-playbook)
- [AI Hero — 11 Tips for Ralph Loops](https://www.aihero.dev/tips-for-ai-coding-with-ralph-wiggum)
