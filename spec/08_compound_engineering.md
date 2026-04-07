# Compound Engineering: Research Report

**Date:** 2026-04-06  
**Status:** Reference Specification

---

## 1. Definition and Core Concept

Compound engineering is an AI-native software development methodology where **each unit of engineering work makes subsequent units easier — not harder**. Coined and systematized by Every, Inc., the principle inverts the traditional trajectory of software development: instead of codebases accumulating technical debt that slows future work, each feature, bug fix, and pattern capture accelerates the next one.

The productivity formula underpinning the approach:

```
Productivity = (Code Velocity) × (Feedback Quality) × (Iteration Frequency)
```

When AI generates code in seconds, the bottleneck shifts from writing to feedback quality and iteration speed. Compound engineering is the systematic answer to that bottleneck.

### What It Is Not

- Not "vibe coding" (unstructured AI code generation)
- Not traditional agentic autocomplete
- Not one-time documentation practices

### The Inversion Principle

Traditional development: complexity compounds against the team  
Compound engineering: knowledge compounds *for* the team

Each bug fix eliminates a category of future bugs. Each solved problem becomes a searchable, reusable asset. Each PR review produces lessons that prevent the same mistake across all future agents and engineers.

### Quantified Impact

- Every, Inc.: one developer matches output of five (pre-AI era)
- Reported productivity gains: 300-700% over traditional methods
- Six-month horizon: teams running the compound loop have agents that "one-shot everything"; teams using autocomplete remain at day-one accuracy — the gap widens weekly

---

## 2. How Lessons Learned Are Captured and Propagated

### The Four-Phase Loop

```
Plan → Work → Review → Compound → (repeat)
```

| Phase | Time Allocation | Activity |
|-------|----------------|----------|
| Plan | 40% | Codebase research, implementation blueprinting |
| Work | 10% | Agentic code execution |
| Review | 40% | Multi-agent parallel code assessment |
| Compound | 10% | Knowledge extraction and persistence |

The **Compound phase** is the differentiating mechanism. It is not documentation for humans — it is documentation that agents automatically read and act on in the next cycle.

### Capture Mechanisms

**`/ce:compound` command** — triggers a structured knowledge extraction after each work cycle:
- Bugs encountered (symptom, cause, fix)
- Performance patterns discovered
- Architectural decisions made and alternatives rejected
- Reusable solution patterns
- Anti-patterns to avoid

**Post-review agent summarization** — code review findings are summarized by agents and archived automatically with "very little extra instruction" from the developer.

**Plan artifacts** — implementation plans stored as `docs/plans/[date]-[feature-name]-plan.md` become reference implementations for future similar work.

### Propagation Mechanism

```
Lesson captured → Written to docs/solutions/ or CLAUDE.md
  → Committed to repository
  → Auto-read by agent at next session start
  → Injected into agent context before task execution
```

Every developer on the team receives accumulated knowledge automatically. New hires inherit all institutional knowledge without manual onboarding. Knowledge that was tribal becomes structural.

### Event-Driven Reinforcement

To counter **instruction fade-out** (degradation of agent behavior in long sessions), compound systems use event-driven system reminders: contextual guidance injected at decision points rather than relying solely on initial instructions.

---

## 3. How It Relates to Claude Code Memory and CLAUDE.md Files

### CLAUDE.md as Compound Engineering's Primary Nerve

`CLAUDE.md` is the central intelligence file read by Claude Code at every session start. In the compound engineering paradigm, it is not a static config — it is a **living institutional memory**.

Contents evolve to include:
- Project conventions and preferences
- Documented anti-patterns (what to never do, why)
- Architectural decisions and rationales
- Error patterns and their fixes
- Code location conventions (where things live, to prevent duplication)
- Integration gotchas
- Team coding standards

**The compound ritual**: after each PR or task completion, learnings are extracted and appended to `CLAUDE.md` or `docs/solutions/`. The next agent session starts with that knowledge already loaded.

### Multi-Layer Memory Architecture

The compound engineering plugin formalizes a three-tier memory system:

| Layer | File/Directory | Scope |
|-------|---------------|-------|
| Working memory | Active conversation context | Current session |
| Episodic memory | `docs/solutions/`, `docs/plans/` | Persistent, searchable across sessions |
| Institutional memory | `CLAUDE.md` | Every session, every agent |

### AGENTS.md / CLAUDE.md Relationship

In the compound-engineering-plugin repository, `CLAUDE.md` contains only `@AGENTS.md` — a pointer to the canonical instruction file. This pattern supports multi-tool compatibility: `AGENTS.md` is the source of truth consumed by Claude, OpenCode, Codex, Gemini, and others. `CLAUDE.md` is a compatibility shim.

For the llmtemplate pattern, this maps directly: a root `AGENTS.md` is the authoritative knowledge file; `CLAUDE.md` includes it.

### Claude Code Memory Hierarchy

Claude Code reads instruction files in a hierarchy:
1. Global `~/.claude/CLAUDE.md` — user-level patterns across all projects
2. Project root `CLAUDE.md` — project-specific knowledge
3. Subdirectory `CLAUDE.md` files — directory-scoped rules

Compound engineering treats all three levels as writable memory surfaces that accumulate knowledge over time.

---

## 4. Best Practices for Implementing Compound Engineering

### Workflow Practices

1. **80/20 time allocation**: 80% planning and review; 20% execution and compounding. Planning is not delegation — it requires developer creative thinking.

2. **Plans as primary artifacts**: Detailed implementation plans become the source of truth before any code is written. Store all plans in `docs/plans/`.

3. **Parallel review agents**: Use multiple specialized agents (security, performance, architecture, data integrity, deployment safety) rather than one general reviewer.

4. **Reuse-first mentality**: Before building anything new, agents ask "Should this be added to something that already exists?"

5. **Agent-native environments**: Agents need the same access as humans — logs, test runners, linters, git operations, error tracking, debuggers. Restricting this is the primary source of agent failure.

6. **Skip permissions carefully**: `--dangerously-skip-permissions` removes approval prompts. Use only in sandboxed environments with good test coverage.

7. **Three review questions** (when multi-agent review is unavailable):
   - "What was the hardest decision?"
   - "What alternatives did you reject?"
   - "What are you least confident about?"

### Knowledge Capture Practices

8. **Document bugs in triplicate**: Symptom, cause, fix. Future agents pattern-match on all three.

9. **Record architectural trade-offs**: Prevents re-evaluating the same decisions. Include what was rejected and why.

10. **Formalize code location conventions**: Prevents duplication. Where does X live? Put it in CLAUDE.md.

11. **Treat solved problems as assets**: Not sunk costs, but reusable capital.

12. **Embrace the 95% garbage rate**: First attempts are expected to be poor. Iteration speed matters more than initial quality. Run the loop more times, not slower.

### Team Practices

13. **Extract taste into systems**: Document preferences in configuration rather than enforcing through review gatekeeping.

14. **Plans require explicit approval** before implementation begins.

15. **PR owner is responsible** regardless of whether an agent or human wrote the code.

16. **Human reviewers focus on intent**, not syntax or security (agents handle those).

17. **Compound documentation replaces tribal knowledge** — no knowledge lives only in one person's head.

---

## 5. How Knowledge Flows Between Projects

### Current State: Per-Project Silos

As of early 2026, compound engineering knowledge is primarily scoped to individual repositories. Each project's `CLAUDE.md` and `docs/solutions/` accumulate project-specific knowledge. Cross-project propagation requires explicit manual action.

### The Skills Hierarchy Pattern (OpenDev/OpenCode model)

The terminal agent architecture (arXiv 2603.05344) implements a three-tier skills resolution:

```
Built-in skills (framework defaults)
  ← User-global skills (~/.opendev/skills/ or ~/.claude/commands/)
    ← Project-local skills (.opendev/skills/ or .claude/commands/)
```

Settings resolve through the same hierarchy: project-local overrides user-global overrides built-in. This enables:
- **Inheritance**: project starts with all user-learned patterns
- **Override**: project-specific rules take precedence
- **Isolation**: project changes don't pollute user-global

Applied to Claude Code: skills in `~/.claude/commands/` are available to all projects. Skills in `.claude/commands/` are project-local. This is the primary existing cross-project knowledge channel.

### Proposed Hub-and-Spoke Architecture (Not Yet Native)

A formal proposal (Claude Code issue #25252, closed as NOT_PLANNED March 2026) articulated the ideal architecture:

**Hub project** — canonical knowledge files, base system prompt  
**Spoke projects** — inherit hub, add domain-specific overlays

Key properties of the proposed model:
- **Symlink model, not copy-paste**: one source of truth, multiple consumers
- **Propagation on edit**: update hub once, all spokes see it automatically
- **Loose coupling**: spokes function independently if hub is deleted
- **Recursive composition**: spokes can become hubs for sub-projects

This is not natively implemented in Claude Code but can be approximated manually (see Section 7).

### Compound Engineering Plugin: Cross-Tool Distribution

The compound-engineering-plugin converts a single plugin definition to 10+ agent platform formats:

| Platform | Output |
|---------|--------|
| Claude Code | Native `.claude/` structure |
| OpenCode | `opencode.json`, `.opencode/{agents,skills,plugins}` |
| Codex CLI | YAML configs |
| Gemini CLI | Tool-specific format |
| Windsurf | `.agent.md` format |
| Factory Droid | TOML configs |

**`sync` command**: mirrors `~/.claude/` configuration across tools, with skills symlinked (not copied) for live editing. This is cross-tool knowledge propagation — one skill definition, available everywhere.

---

## 6. Tooling and Infrastructure Needed

### Core Tools

| Tool | Role |
|------|------|
| Claude Code | Primary AI coding agent (most adopted as of 2025-2026) |
| Compound Engineering Plugin | Workflow commands, 29 agents, 22 commands, 20 skills |
| OpenCode / Codex CLI | Alternative/complementary agents |
| Linters | Automated code quality validation |
| Unit tests | Agent self-verification during work phase |
| Git | Session-to-session knowledge persistence via commits |

### Plugin Components (compound-engineering-plugin)

- **29 agents**: 15 review agents (security, performance, architecture, language-specific), 5 research agents, 3 design agents, 5 workflow agents, 1 documentation agent
- **22 workflow commands**: `/ce:ideate`, `/ce:brainstorm`, `/ce:plan`, `/ce:work`, `/ce:review`, `/ce:compound`, `/lfg` (end-to-end pipeline)
- **20 skills**: Expert guidance modules encoding domain patterns
- **1 MCP server**: Framework documentation lookup

### Directory Structure

```
project/
├── CLAUDE.md                    # Institutional memory (or @AGENTS.md pointer)
├── AGENTS.md                    # Canonical multi-tool instruction file
├── .claude/
│   ├── commands/                # Project-local skills and commands
│   └── settings.json            # Hooks and configuration
├── docs/
│   ├── plans/                   # Implementation blueprints (date-feature-plan.md)
│   ├── solutions/               # Solved problems, categorized
│   │   ├── developer-experience/
│   │   ├── integrations/
│   │   ├── workflow/
│   │   └── skill-design/
│   ├── brainstorms/             # Requirements exploration
│   └── specs/                   # Formal specifications
└── notes/                       # Working memory / scratchpad
```

### Agent-Native Checklist

For compound engineering to work, agents must have access to:
- Application runtime
- Test execution
- Linting
- Git operations
- Local and production logs
- Debugging tools
- Error tracking systems
- Deployment commands

### ReAct Execution Loop (per arXiv 2603.05344)

Each agent iteration runs 6 phases:
1. Pre-check
2. Thinking
3. Self-critique
4. Action selection
5. Tool execution
6. Post-processing

This loop runs within a harness that manages context compaction, session persistence, and message injection.

---

## 7. How a Master Repo Could Serve as the Compound Engineering Hub

### The llmtemplate Pattern

The `llmtemplate` repository is architecturally positioned to be the master compound engineering hub. It already contains:
- `AGENTS.md` — canonical instruction file
- `.claude/commands/` — cross-project skills (compound, ralph-loop, execwrap-setup, etc.)
- `.claude/settings.json` — hooks and tool configuration
- `scripts/` — reusable automation
- `spec/` — specifications (this file)

### Hub Architecture for llmtemplate

```
llmtemplate/ (THE HUB)
├── AGENTS.md                    # Master agent instructions
├── CLAUDE.md                    # @AGENTS.md pointer
├── .claude/
│   ├── commands/                # Skills available globally when symlinked
│   ├── hooks/                   # Event-driven knowledge injection
│   └── settings.json            # Global configuration template
├── docs/solutions/              # Cross-project solved problems
├── spec/                        # Architecture specifications (this file)
└── scripts/                     # Reusable automation

project-foo/ (A SPOKE)
├── CLAUDE.md                    # @../llmtemplate/AGENTS.md (or symlinked)
├── .claude/
│   ├── commands/ -> ../llmtemplate/.claude/commands/  # Symlinked
│   └── settings.json            # Inherits from hub template
└── docs/solutions/              # Project-specific solutions
```

### Implementation Strategy

**Approach 1: Symlinks (current best option)**
```bash
# In each project:
ln -s /path/to/llmtemplate/.claude/commands .claude/commands
# CLAUDE.md references llmtemplate AGENTS.md:
echo "@/path/to/llmtemplate/AGENTS.md" > CLAUDE.md
```

**Approach 2: Git submodule**
```bash
git submodule add <llmtemplate-url> .llmtemplate
# CLAUDE.md: @.llmtemplate/AGENTS.md
```

**Approach 3: Global installation**
```bash
# Skills installed to ~/.claude/commands/ propagate to all projects
cp -r llmtemplate/.claude/commands/* ~/.claude/commands/
# Or symlink the whole directory
ln -s /path/to/llmtemplate/.claude/commands ~/.claude/commands
```

### Knowledge Flow in the Hub Model

```
Project encounter bug
  → /compound captures solution to project docs/solutions/
  → Developer promotes cross-project lesson to llmtemplate docs/solutions/
  → llmtemplate AGENTS.md updated with new pattern
  → All projects inheriting llmtemplate see update immediately (symlink)
  → Or: developer pulls llmtemplate changes into project (submodule)
```

### Hub Responsibilities

The master repo should own:

1. **Universal agent instructions** — coding standards, patterns, anti-patterns applicable across all projects
2. **Cross-project solutions library** — bugs and fixes that appear in multiple codebases
3. **Skill definitions** — compound, ralph-loop, execwrap, security-audit, etc.
4. **Hook templates** — pre-tool-call hooks, post-session compounding triggers
5. **Configuration templates** — base `settings.json`, base `.env.example`
6. **Specification library** — architectural decisions, system designs (this spec directory)

### Spoke Responsibilities

Each project repo owns:

1. **Project-specific CLAUDE.md additions** — domain rules, local conventions
2. **Project docs/solutions/** — issues specific to this codebase
3. **Project docs/plans/** — feature blueprints for this project
4. **Local overrides** — any hub pattern that needs adjustment for this context

### Automation: Promoting Lessons to Hub

A promotion workflow keeps the hub current:

```bash
# After compounding in a project:
# 1. Review docs/solutions/ for cross-project candidates
# 2. Copy applicable solutions to llmtemplate/docs/solutions/
# 3. Update llmtemplate/AGENTS.md if pattern is universal
# 4. Commit to llmtemplate
# 5. All projects inherit via symlink or next pull
```

This can be partially automated with a hook or skill that flags solutions as "hub-worthy" during the compound phase.

---

## 8. Summary: The Compound Engineering Flywheel

```
Task completed
  ↓
Lessons extracted (bugs, patterns, decisions)
  ↓
Written to docs/solutions/ + CLAUDE.md
  ↓
Committed to repo (project or hub)
  ↓
Next agent session reads accumulated knowledge
  ↓
Agent one-shots similar problems
  ↓
More tasks completed, faster
  ↓
(repeat — velocity compounds)
```

The core insight: **knowledge captured is capital invested**. Teams not running this loop are spending principal every sprint. Teams running it are earning compound interest on every lesson learned.

The llmtemplate repository is the natural hub for this flywheel across all projects in an individual developer's or team's portfolio.

---

## Sources

- [Compound Engineering: How Every Codes With Agents](https://every.to/chain-of-thought/compound-engineering-how-every-codes-with-agents) — Every, Inc.
- [Compound Engineering Guide](https://every.to/guides/compound-engineering) — Every, Inc.
- [Compound Engineering: AI-Assisted Software Development Methodology](https://reading.torqsoftware.com/notes/software/ai-ml/agentic-coding/2026-01-19-compound-engineering-claude-code/) — Torq Software Reading List
- [Compound Engineering: The Next Paradigm Shift](https://www.vincirufus.com/en/posts/compound-engineering/) — Vinci Rufus
- [Learning from Every's Compound Engineering](https://lethain.com/everyinc-compound-engineering/) — Will Larson / Irrational Exuberance
- [Building Effective AI Coding Agents for the Terminal](https://arxiv.org/html/2603.05344v1) — arXiv 2603.05344
- [Compound Engineering Plugin](https://github.com/EveryInc/compound-engineering-plugin) — EveryInc GitHub
- [Compound Engineering Plugin Docs](https://www.mintlify.com/EveryInc/compound-engineering-plugin/plugin/overview) — Mintlify
- [Hub-and-Spoke Knowledge Propagation Proposal](https://github.com/anthropics/claude-code/issues/25252) — Claude Code Issue #25252
