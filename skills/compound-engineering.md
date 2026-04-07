---
description: Scaffold compound engineering capabilities into a repository — creates episodic memory library (docs/solutions/), working memory (notes/), sub-agent definitions (.claude/agents/), and minimally updates AGENTS.md/CLAUDE.md to wire everything together. Run once per repo.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, AskUserQuestion
---

# Compound Engineering Setup

Scaffold a complete compound engineering system into this repository. The goal is a **learning flywheel**: every task makes future tasks cheaper by capturing lessons into a searchable, structured knowledge base that agents (and humans) actively use.

## Philosophy (Read Before Acting)

Compound engineering is based on three insights from research into agentic coding:

1. **Context amnesia kills institutional knowledge.** Every agent session starts fresh. Without external memory structures, lessons vanish when the context window closes.

2. **AGENTS.md/CLAUDE.md must stay short** (< 300 lines). LLMs stop reliably following long instruction files. Use AGENTS.md as an *index* that points outward to richer knowledge — not as a dump of everything you know.

3. **The compound step must be a ritual enforced by tooling**, not discipline. The `/compound` skill (companion to this one) is that ritual — run it after every significant task.

### The Four Memory Layers

| Layer | What | Where |
|-------|------|-------|
| **Semantic** | Always-needed conventions, commands, gotchas | `AGENTS.md` (short) + `docs/agent-guides/` |
| **Episodic** | Past solved problems, searchable by tag | `docs/solutions/*.md` with YAML frontmatter |
| **Procedural** | How to do recurring workflows | `.claude/commands/*/` skills |
| **Working** | Active task state for long autonomous runs | `notes/agent-progress.md` |

---

## Phase 1: Survey the Repository

Before creating anything, understand what already exists.

```bash
# Check for existing instruction files
ls -la AGENTS.md CLAUDE.md 2>/dev/null || echo "No instruction files found"

# Check existing directory structure
ls -la docs/ notes/ .claude/ 2>/dev/null || true

# Check for existing solutions/guides
ls docs/solutions/ docs/agent-guides/ 2>/dev/null || echo "No knowledge dirs found"

# Check current AGENTS.md / CLAUDE.md size
wc -l AGENTS.md CLAUDE.md 2>/dev/null || true
```

Read any existing AGENTS.md or CLAUDE.md to understand current content before touching it.

Also check git log to understand the project's history and conventions:
```bash
git log --oneline -10 2>/dev/null || true
git branch --show-current 2>/dev/null || true
```

**Decision point**: If both AGENTS.md and CLAUDE.md exist, ask the user which is canonical. If neither exists, create AGENTS.md.

---

## Phase 2: Create the Knowledge Directory Structure

Create these directories and their README files. Check each one first — do not overwrite existing content.

### 2a. `docs/solutions/` — Episodic Memory Library

This is the most important directory. Every significant problem solved in this repo gets a file here.

**Check first:**
```bash
ls docs/solutions/ 2>/dev/null && echo "EXISTS" || echo "MISSING"
```

If missing, create:

**`docs/solutions/README.md`** — explain the pattern to agents and humans:

```markdown
# Solutions Library

This directory is the project's **episodic memory** — a searchable library of problems that have been solved in this codebase.

## Purpose

When an agent (or developer) encounters an error or unfamiliar situation, they should search here first:

```bash
grep -r "keyword" docs/solutions/
grep -r "tags:.*database" docs/solutions/
```

## When to Add a Solution

Add a file here whenever you:
- Solved a non-obvious bug (especially one that took > 30 min)
- Discovered a gotcha or footgun in a library/framework used here
- Found the "right way" to do something that had multiple options
- Hit an error that the next person will definitely hit again

## How to Add (run `/compound` after any significant task)

Copy `_template.md`, fill in the frontmatter and body, name the file:
`YYYY-MM-DD-short-description.md`

## Structure

YAML frontmatter makes files grep-searchable and RAG-retrievable:
- `tags`: domain keywords for discovery
- `problem`: one-line description of what went wrong / what was unclear
- `solution`: one-line description of the fix
- `applies-to`: libraries, frameworks, commands involved
- `agent-note`: short instruction for a future agent encountering this situation
```

**`docs/solutions/_template.md`** — template for new solutions:

```markdown
---
date: YYYY-MM-DD
tags: [tag1, tag2, tag3]
problem: "One-line description of the problem"
solution: "One-line description of the fix"
symptoms:
  - "Observable symptom 1"
  - "Observable symptom 2"
affected-files: []
applies-to: [library, framework, command]
time-to-discover: "X hours"
agent-note: "Short instruction for a future agent hitting this situation"
---

# Problem: [Title]

## Symptom

What you observed. Error messages, unexpected behavior, test failures.

## Root Cause

Why it happened. Be specific — link to library internals, version changes, or implicit assumptions.

## Solution

Step-by-step fix. Include the exact code or command that resolved it.

```bash
# Example command or code
```

## Prevention / Future Agent Guidance

What to check proactively to avoid this. What to do differently next time.
Should this be added to AGENTS.md gotchas? (If yes, add it there too.)

## Related

- Link to relevant docs, issues, PRs
- Related solutions in this directory
```

### 2b. `docs/agent-guides/` — Deep Context (Semantic Memory Overflow)

Content that is too long for AGENTS.md but too important to omit. AGENTS.md links here.

**Check first:**
```bash
ls docs/agent-guides/ 2>/dev/null && echo "EXISTS" || echo "MISSING"
```

If missing, create:

**`docs/agent-guides/README.md`**:

```markdown
# Agent Guides

Detailed context for AI agents working in this codebase — too long for AGENTS.md but
referenced from it. Agents are directed here from AGENTS.md for specific domains.

## Files

Add a guide here when:
- A domain area has complex enough conventions that AGENTS.md would exceed 300 lines if included
- A workflow requires more than 10 steps to explain
- There is reference material (tables, examples, gotcha lists) that belongs near code but not in AGENTS.md

## Naming Convention

`<domain>-guide.md` — e.g., `testing-guide.md`, `deployment-guide.md`, `database-guide.md`
```

### 2c. `docs/processes/` — Manual Process Documentation

Human and agent processes that recur in this project. Deployments, migrations, review workflows, incident response, onboarding steps, vendor interactions — anything that has been done manually and will be done again.

**Check first:**
```bash
ls docs/processes/ 2>/dev/null && echo "EXISTS" || echo "MISSING"
```

If missing, create:

**`docs/processes/README.md`**:

```markdown
# Process Documentation

Manual processes that recur in this project — documented so they can be followed
correctly and improved over time. Maintained by `/compound after` runs.

## Files

`<process-name>.md` — e.g., `deploy-staging.md`, `db-migration.md`, `incident-response.md`

## Format

Each file includes: purpose, preconditions (checklist), numbered steps with gotchas,
verification checks, rollback procedure, known failure modes, and a history log.

## Search

```bash
grep -ril "keyword" docs/processes/
```

## When to Add

Add a process doc whenever:
- A manual sequence was followed that will recur
- The process has a specific order, preconditions, or non-obvious steps
- It involves coordination with external systems or people
- It failed or had a near-miss that revealed a gap in existing docs
```

### 2d. `notes/` — Working Memory

For active task state, Ralph Loop progress, and session scratchpad.

**Check first:**
```bash
ls notes/ 2>/dev/null && echo "EXISTS" || echo "MISSING"
```

If missing, create:

**`notes/agent-progress.md`** — Ralph Loop / long-run working memory:

```markdown
# Agent Progress

Working memory for long-running autonomous tasks and Ralph Loop iterations.
This file is read at the start of each agent iteration and updated throughout.
Commit it as part of each task commit so state survives context resets.

## Active Task

**Task**: (none)
**Status**: idle
**Branch**: -
**Started**: -

## Completed Steps

(none yet)

## In Progress

(none)

## Blockers

(none)

## Decisions Made

(none)

## Learnings So Far

(none)

---
*Update this file at the start and end of each agent work session.*
*Run `/compound` when a task completes to capture lessons in `docs/solutions/`.*
```

**`notes/recurring-patterns.md`** — systemic pattern tracker, populated by `/compound after`:

```markdown
# Recurring Patterns

Systemic issues identified by pattern analysis across `docs/solutions/` and `docs/processes/`.
Updated automatically by `/compound after` runs when a tag reaches 3+ occurrences.

These are candidates for process improvements: automation, checklists, hooks, or skills.

| Tag / Domain | Occurrences | First Seen | Status | Proposed Fix |
|--------------|-------------|------------|--------|--------------|
| (none yet — populated by /compound after runs) | | | | |

## Status Values
- `open` — identified, no fix yet
- `proposed` — improvement proposed, not implemented
- `mitigated` — fix in place, monitoring
- `accepted` — known, cannot automate, documented for awareness
```

**`notes/README.md`**:

```markdown
# Notes

Working memory for active agent sessions and long-running autonomous tasks.

| File | Purpose |
|------|---------|
| `agent-progress.md` | State file for Ralph Loop iterations and multi-session work |
| `recurring-patterns.md` | Systemic issues detected by pattern analysis (updated by /compound) |
| `todo.md` | Active task list (create as needed) |
| `session-*.md` | Per-session scratchpad (create as needed, optionally gitignore) |

These files are **meant to be committed** (except session scratchpads) so that
state survives across context resets. They are the agent's external working memory.
```

### 2e. `.claude/agents/` — Specialized Sub-Agent Definitions

Reviewer sub-agents for the parallel review phase of compound engineering.

**Check first:**
```bash
ls .claude/agents/ 2>/dev/null && echo "EXISTS" || echo "MISSING"
```

If missing, create the directory and add two starter reviewers:

**`.claude/agents/README.md`**:

```markdown
# Sub-Agent Definitions

Specialized reviewer agents for the compound engineering review phase.
The orchestrator spawns these in parallel after implementation.

## Usage

In a compound engineering review phase, spawn these in parallel:
- Security reviewer: check for OWASP top 10, secrets, injection
- Architecture reviewer: check for coupling, naming, patterns

## Adding Reviewers

Create a `.md` file here. The file is the system prompt / instructions for the sub-agent.
Name files `<role>-reviewer.md` for reviewer agents, `<role>-agent.md` for workers.
```

**`.claude/agents/security-reviewer.md`**:

```markdown
# Security Reviewer Agent

You are a security-focused code reviewer. You have been given a diff or set of files to review.

## Your Job

Review the code for security vulnerabilities. Focus on:

1. **Injection**: SQL injection, command injection, XSS, template injection
2. **Authentication/Authorization**: Missing auth checks, privilege escalation, insecure defaults
3. **Secrets**: Hardcoded credentials, API keys, tokens in code or logs
4. **Input Validation**: Missing validation at system boundaries (user input, external APIs)
5. **Dependency Risk**: Known-vulnerable packages, supply chain concerns
6. **Cryptography**: Weak algorithms, improper key management, broken TLS
7. **Logging**: Sensitive data in logs, missing audit trails

## Output Format

Rate each finding P1/P2/P3:
- **P1**: Must fix before merge (exploitable vulnerability)
- **P2**: Should fix soon (defense-in-depth, hardening)
- **P3**: Consider fixing (best practice, low risk)

For each finding:
```
[P1] SQL Injection in user search
File: src/api/users.py:42
Issue: Raw string interpolation into SQL query
Fix: Use parameterized queries: cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
```

If no issues found, say: "No security issues found in this diff."
```

**`.claude/agents/architecture-reviewer.md`**:

```markdown
# Architecture Reviewer Agent

You are an architecture-focused code reviewer. You review for structural quality and long-term maintainability.

## Your Job

Review for architectural concerns:

1. **Coupling**: Are modules too tightly coupled? Is the dependency direction correct?
2. **Naming**: Do names accurately describe what things do? Are they consistent with existing conventions?
3. **Abstraction level**: Is this the right level of abstraction, or is it over/under-engineered?
4. **Single Responsibility**: Does each function/class do one thing?
5. **Error handling**: Are errors handled at the right level and propagated correctly?
6. **Patterns**: Does this follow the patterns already established in this codebase?
7. **Testability**: Is this code testable as written?

## Output Format

Rate findings P1/P2/P3:
- **P1**: Must fix — breaks existing patterns or creates technical debt that blocks future work
- **P2**: Should fix — inconsistent or will cause confusion
- **P3**: Consider — minor improvement opportunity

For each finding, cite the file and line, explain the issue, and suggest the fix.

If no issues found, say: "Architecture looks solid — consistent with existing patterns."
```

---

## Phase 3: Update AGENTS.md / CLAUDE.md (Minimal, Surgical)

This is the most delicate step. **Do not rewrite or restructure the existing file.** Add only what is necessary to wire the new system in.

Read the existing instruction file first. Then add a `## Compound Engineering` section (or `## Institutional Memory` if that fits better) with exactly these elements — no more:

```markdown
## Compound Engineering

This project uses compound engineering to accumulate institutional knowledge across sessions.
Every agent should proactively search existing lessons before starting significant work.

### Before Starting Any Significant Task

Search for past lessons relevant to the task domain:

```bash
grep -ril "KEYWORD" docs/solutions/ docs/processes/ docs/agent-guides/
```

Run `/compound before` for a guided pre-task knowledge brief.
Check `notes/recurring-patterns.md` for known systemic issues in this area.

### Memory System

| Layer | Location | What Goes There |
|-------|----------|-----------------|
| Deep context | `docs/agent-guides/` | Domain guides linked from here |
| Solved problems | `docs/solutions/` | Past bugs, gotchas, solutions (searchable by grep/tag) |
| Manual processes | `docs/processes/` | Deployment, migration, review, runbook procedures |
| Systemic patterns | `notes/recurring-patterns.md` | Repeated issues flagged for systemic fixes |
| Active task state | `notes/agent-progress.md` | Ralph Loop state, multi-session working memory |
| Procedural skills | `.claude/commands/` | Slash command workflows |

### After Every Significant Task

Run `/compound` (or `/compound after`) to capture lessons learned. Covers code changes,
manual processes, dead ends, and anything that was non-obvious. **The compound step is
not optional — it is what makes the system compound.**

### Searching Past Lessons

```bash
grep -ril "error or keyword" docs/solutions/ docs/processes/
grep -rl "tags:.*database" docs/solutions/    # filter by tag
cat notes/recurring-patterns.md               # systemic issues
```
```

**Where to insert**: At the end of the file, before any final footer section. Do not insert in the middle of existing content.

**If the file doesn't exist**: Create a minimal AGENTS.md with:
- Project name and 1-sentence description (ask user if not inferrable)
- Build/test commands (check justfile or package.json)
- The compound engineering section above

---

## Phase 4: Report What Was Created

After all operations complete, print a clear summary:

```
## Compound Engineering Setup Complete

### Created / Updated:
- [ ] docs/solutions/README.md            — episodic memory library
- [ ] docs/solutions/_template.md         — solution template
- [ ] docs/agent-guides/README.md         — deep context overflow
- [ ] docs/processes/README.md            — manual process documentation
- [ ] notes/agent-progress.md             — working memory / Ralph Loop state
- [ ] notes/recurring-patterns.md         — systemic pattern tracker
- [ ] notes/README.md                     — notes directory guide
- [ ] .claude/agents/README.md            — sub-agent directory
- [ ] .claude/agents/security-reviewer.md
- [ ] .claude/agents/architecture-reviewer.md
- [ ] AGENTS.md (or CLAUDE.md)            — added Compound Engineering section

### Already Existed (skipped):
(list any that were skipped)

### Next Steps:
1. Run `/compound before` before your next task — surface any existing lessons
2. Run `/compound` after your next significant task to capture the first lesson
3. Customize .claude/agents/ reviewers to match your project's security/arch concerns
4. Add domain-specific guides to docs/agent-guides/ as conventions emerge
5. When a manual process is followed, document it in docs/processes/
6. Consider running `/ralph-loop` for autonomous multi-task execution with built-in compounding
```

---

## Idempotency Rules

This skill is safe to re-run. Always:
- Check before creating: if a file exists, read it first and only append/update if needed
- Never overwrite existing content without reading it
- If a directory already has the expected content, report it as "Already existed (skipped)"
- AGENTS.md/CLAUDE.md: only add the compound engineering section if it is not already present
