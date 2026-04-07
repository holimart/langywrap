---
description: The compound engineering ritual — run BEFORE a task to proactively surface lessons learned and avoid repeating mistakes, or AFTER a task to capture new knowledge into docs/solutions/. Covers code changes, manual processes, deployments, and any workflow the team has been through. Use `/compound before` or `/compound after` (default: after). The ritual that makes compound engineering actually compound.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# The Compound Ritual

Two modes, one command:

- **`/compound before`** — proactive knowledge search before starting a task. Surfaces relevant past lessons, known gotchas, recurring patterns, and process notes so you don't repeat history.
- **`/compound after`** (default) — after-task capture. Routes new knowledge to the right storage layer, detects if a mistake was already known, identifies systemic patterns, and proposes process improvements.

> "Each unit of engineering work should make subsequent units easier, not harder."

The compound step is what transforms one-time discoveries into institutional memory that every future agent — and human — automatically benefits from.

---

## PREFLIGHT: Verify Scaffold Exists

Before running either mode, check:

```bash
ls docs/solutions/ docs/agent-guides/ docs/processes/ notes/ 2>/dev/null || echo "MISSING"
```

If `docs/solutions/` does not exist, stop and tell the user:

> "`docs/solutions/` doesn't exist yet. Run `/compound-engineering` first to scaffold the system, then re-run `/compound`."

---

---

# MODE 1: BEFORE TASK (Proactive Knowledge Search)

Invoke this **before starting any significant task** — a new feature, a bug fix, a migration, a deployment, a refactor, any process you've been through before.

The goal: make the unknown known before you start, not after you're stuck.

---

## B1: Understand the Incoming Task

From the conversation context or user's description, extract:
- What domain is this in? (database, auth, deployment, testing, a specific module, etc.)
- What tools, libraries, or commands will likely be involved?
- What type of work is this? (bug fix / new feature / migration / deployment / config change / process / review)
- What are the obvious risk areas?

Write these down as search terms for the next steps.

---

## B2: Search Existing Solutions (Episodic Memory)

Search `docs/solutions/` for anything relevant to this task:

```bash
# Full-text search on keywords from the task
grep -ril "KEYWORD1\|KEYWORD2" docs/solutions/ 2>/dev/null

# Search by tag
grep -rl "tags:.*DOMAIN" docs/solutions/ 2>/dev/null

# List all solutions with their problem/solution summary for skimming
grep -h "^problem:\|^solution:\|^tags:" docs/solutions/*.md 2>/dev/null | paste - - -
```

Run at least 2-3 searches with different keywords. If solutions are found, **read them fully** before proceeding.

**What to do with findings:**
- Surface each relevant solution to the user: "Before we start, I found these past lessons:"
- If a past solution directly applies, follow it — don't re-investigate what's already been investigated
- If a past solution is partially relevant, note the differences explicitly

---

## B3: Search Process Documentation (Manual Process Memory)

Search `docs/processes/` for documented manual processes related to this task:

```bash
ls docs/processes/ 2>/dev/null
grep -ril "KEYWORD" docs/processes/ 2>/dev/null
```

Process docs cover: deployment steps, database migration procedures, review workflows, approval chains, environment setup, rollback procedures, on-call runbooks, vendor interactions.

If a relevant process doc exists, read it and summarize the critical steps and gotchas for the user.

---

## B4: Search Agent Guides (Deep Convention Memory)

Check `docs/agent-guides/` for domain-specific conventions:

```bash
ls docs/agent-guides/ 2>/dev/null
grep -ril "KEYWORD" docs/agent-guides/ 2>/dev/null
```

If a relevant guide exists, read it and surface the most important constraints and patterns for this task.

---

## B5: Check Recurring Patterns (Systemic Issues)

Check `notes/recurring-patterns.md` if it exists:

```bash
cat notes/recurring-patterns.md 2>/dev/null
```

Recurring patterns are systemic issues — categories of mistakes that have happened multiple times. If any pattern is relevant to this task, call it out explicitly:

> "⚠️ Warning: We have a recurring pattern around [X]. Past occurrences: [N]. Known mitigation: [Y]."

---

## B6: Before-Task Report

Summarize findings before the task begins:

```
## Pre-Task Knowledge Brief

### Task: [task description]
### Domain: [database / auth / deployment / etc.]

### Relevant Past Solutions Found:
- docs/solutions/2025-11-15-name.md — [problem: ...] [solution: ...]
  → ACTION: [what this means for the current task]

### Relevant Process Docs:
- docs/processes/deploy-staging.md — [key steps / gotchas to watch for]

### Relevant Agent Guides:
- docs/agent-guides/database-guide.md — [key conventions to follow]

### Recurring Patterns to Watch For:
- ⚠️ [pattern name]: [description] — seen N times, mitigation: [...]

### Nothing Found (safe to proceed fresh):
- (list domains where no past lessons exist)

### Recommended Precautions:
1. [specific action based on lessons]
2. [specific action based on lessons]
```

If nothing relevant was found in any location, say so clearly — this is not a failure, it means this is genuinely new territory and the upcoming `/compound after` will be especially important.

---

---

# MODE 2: AFTER TASK (Capture + Analyze + Improve)

Run this **after completing any significant task** — code change, bug fix, deployment, manual process, investigation (even one that found nothing), or any session where something was learned.

---

## A1: Understand What Just Happened

Gather context on the completed work:

```bash
# What code changed in this session
git diff HEAD~1 --stat 2>/dev/null || git diff --stat 2>/dev/null

# Recent commits
git log --oneline -5 2>/dev/null

# Current branch
git branch --show-current 2>/dev/null
```

Also read `notes/agent-progress.md` if it exists.

Beyond the code, **explicitly ask / review from context** — these capture knowledge that git diffs miss:

**Code & Technical:**
- Was there a non-obvious bug or error message that was misleading?
- Did something take longer than expected because of missing knowledge?
- Was there a "I wish I had known this earlier" moment?
- Did you try something that didn't work before finding what did?

**Manual Process:**
- Were there manual steps that had to be done in a specific order?
- Was there a step that required waiting (for a service, for a person, for a timer)?
- Was there anything that required human approval or external communication?
- Were there environment-specific steps (only on staging, only in prod, only on certain machines)?
- Was there a rollback or undo procedure that was non-obvious?
- Did any step fail silently (appeared to work but didn't)?

**Team & Coordination:**
- Was there tribal knowledge that only certain people knew?
- Was there an assumption that turned out to be wrong?
- Was there a gap between documentation and reality?

---

## A2: Check — Have We Seen This Before?

**Before writing any new solution file**, check if this mistake or situation is already documented:

```bash
# Search by error keywords
grep -ril "ERROR_KEYWORD\|SYMPTOM_KEYWORD" docs/solutions/ 2>/dev/null

# Search by domain/library
grep -rl "tags:.*RELEVANT_TAG" docs/solutions/ 2>/dev/null

# Search by affected component
grep -ril "FILENAME_OR_MODULE" docs/solutions/ 2>/dev/null
```

**If a match is found:**
- Read the existing solution file
- Determine: is this the *same* problem (update the existing file with new observations) or a *related but different* problem (create a new file with a link to the related one)?
- If it's the same problem recurring: **this is a pattern** — flag it for pattern analysis in step A5

**If no match is found:**
- Proceed to triage (A3) — this is genuinely new knowledge

This step prevents `docs/solutions/` from filling with near-duplicate files and ensures patterns get recognized rather than re-documented.

---

## A3: Triage — Which Bucket(s)?

A single session can produce knowledge for multiple buckets. Classify everything:

### Bucket A: Solved Problem / Gotcha / Process Lesson → `docs/solutions/`

Use this when:
- Fixed a non-obvious bug
- Discovered a footgun or surprising library behavior
- Found that a manual process has a non-obvious step or ordering constraint
- An error message was misleading and the actual cause was elsewhere
- A deployment/migration/configuration step failed in a non-obvious way
- You tried something that didn't work before finding what did (document the dead ends too)
- Future agents or developers will definitely hit this situation again

**High-value signal**: "This took more than 30 minutes" OR "I would not have known to do this without being told."

### Bucket B: Deep Conventions / Long Guide → `docs/agent-guides/`

Use this when:
- A domain now has enough conventions to fill a guide (> 15-20 lines)
- There is reference material (tables, steps, examples) that belongs near code
- The knowledge is how-to, not problem-solution

### Bucket C: Documented Manual Process → `docs/processes/`

Use this when:
- A manual process was followed that is likely to recur (deployment, migration, review, onboarding, incident response, vendor interaction)
- The process has a specific order, preconditions, or gotchas
- It involves coordination with external systems or people
- It is not a code change but a workflow

### Bucket D: Critical Short Convention → `AGENTS.md`

Use **sparingly** — only when:
- Every agent on any part of the project needs this
- It is one sentence / 2-3 bullets max
- Not adding it will cause repeated mistakes at the top level

**High bar**: If it fits in `docs/solutions/` instead, put it there.

### Bucket E: New Reusable Workflow → `.claude/commands/` (new skill)

Use this when:
- You performed a sequence of steps that will recur and is complex enough to need guidance each time
- Examples: "how to run migrations here", "how to deploy to staging", "how to profile this service"

### Bucket F: Update Working Memory → `notes/agent-progress.md`

Always — update this file to reflect current state.

---

## A4: Write to the Right Location

### For Bucket A — Write a Solution File

Get today's date:
```bash
date +%Y-%m-%d
```

Create `docs/solutions/YYYY-MM-DD-short-description.md` using the template from `docs/solutions/_template.md`.

**Naming**: Be specific. Prefer `2025-11-15-alembic-misses-partial-indexes.md` over `2025-11-15-database-bug.md`.

**Check existing tags for consistency:**
```bash
grep "^tags:" docs/solutions/*.md 2>/dev/null | grep -o '\[.*\]' | tr -d '[]' | tr ',' '\n' | tr -d ' ' | sort | uniq -c | sort -rn | head -20
```

Use existing tags where they apply — consistent tags make grep searches reliable.

**For problems where you tried things that didn't work**: include a `## Dead Ends` section in the body documenting what you tried and why it failed. This is some of the most valuable knowledge to capture — it prevents future agents from re-investigating the same dead ends.

**For manual process problems**: fill in the `process-type` frontmatter field if the template includes it, and add a `## Steps / Order` section showing the correct sequence.

**If updating an existing solution** (same problem, new observation): read the file, add a `## Update YYYY-MM-DD` section at the bottom rather than modifying the original. This preserves history.

### For Bucket B — Write or Update an Agent Guide

```bash
ls docs/agent-guides/
```

Read existing guide if one exists, then append. For new guides, use this structure:
```markdown
# [Domain] Guide

Brief intro: when to consult this guide.

## Core Patterns
...

## Gotchas
- ...

## Step-by-Step: [Common Task]
...
```

Add a reference to this guide in AGENTS.md if not already there.

### For Bucket C — Write or Update a Process Doc

```bash
ls docs/processes/ 2>/dev/null || echo "No processes dir yet"
```

If `docs/processes/` doesn't exist, create it with a `README.md`:

```markdown
# Process Documentation

Manual processes that recur in this project — documented so they can be followed
correctly and improved over time.

## Files
`<process-name>.md` — e.g., `deploy-staging.md`, `db-migration.md`, `incident-response.md`

## Format
Each file should include: purpose, preconditions, steps (numbered, in order),
known failure modes, rollback procedure, and who to contact.
```

Then create or update the process file. Use this structure:

```markdown
# Process: [Name]

**When to use**: [trigger / situation]
**Estimated time**: [X minutes]
**Who can run this**: [anyone / specific roles]
**Last verified**: [date]

## Preconditions

- [ ] [thing that must be true before starting]
- [ ] [access / permission required]

## Steps

1. [Step one — be specific about commands, URLs, UI paths]
2. [Step two]
   - ⚠️ Gotcha: [non-obvious thing about this step]
3. [Step three]

## Verification

How to confirm the process succeeded:
- [check 1]
- [check 2]

## Rollback

If something goes wrong:
1. [rollback step]

## Known Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| [symptom] | [cause] | [fix] |

## History

| Date | Who | Notes |
|------|-----|-------|
| [date] | [agent/person] | [what happened, what changed] |
```

### For Bucket D — Update AGENTS.md

Read AGENTS.md first. Add the minimum necessary — one bullet, one rule.

Check size after:
```bash
wc -l AGENTS.md CLAUDE.md 2>/dev/null
```

If > 300 lines: flag to user — "AGENTS.md is getting long. Consider moving content to `docs/agent-guides/`."

### For Bucket E — Propose a New Skill

Write a note in `notes/agent-progress.md` under `## Proposed Skills`:

```markdown
## Proposed Skills

- `<skill-name>`: [what it would do, why it came up, what the steps are]
```

Report to the user — they can create the skill in a follow-up.

### For Bucket F — Always: Update Working Memory

Update `notes/agent-progress.md`:
- Mark completed task as done
- Clear In Progress / Blockers
- Add decisions to Decisions Made
- Add session learnings to Learnings So Far

---

## A5: Pattern Analysis (Systemic Thinking)

After writing, run a pattern analysis over all solutions and processes. This is what prevents individual lessons from staying isolated and reveals systemic issues.

**Count solutions by tag:**
```bash
grep "^tags:" docs/solutions/*.md 2>/dev/null | grep -o '\[.*\]' | tr -d '[]' | tr ',' '\n' | sed 's/^ *//' | sed 's/ *$//' | sort | uniq -c | sort -rn | head -15
```

**Count solutions by month (are lessons accelerating or decelerating?):**
```bash
grep "^date:" docs/solutions/*.md 2>/dev/null | grep -o '[0-9]\{4\}-[0-9]\{2\}' | sort | uniq -c
```

**Find the most repeated problem domains** (any tag with 3+ occurrences is a candidate for systemic action):

If a tag has 3+ solutions:
- The domain has a systemic issue, not just isolated incidents
- Document it in `notes/recurring-patterns.md`
- Propose a concrete systemic fix (see A6)

**Update `notes/recurring-patterns.md`:**

```bash
cat notes/recurring-patterns.md 2>/dev/null || echo "(not yet created)"
```

Create or update:

```markdown
# Recurring Patterns

Systemic issues identified by pattern analysis of docs/solutions/.
Updated by `/compound after` runs. These are candidates for process improvements.

| Tag / Domain | Occurrences | First Seen | Status | Proposed Fix |
|--------------|-------------|------------|--------|--------------|
| [tag] | [N] | [date] | open / mitigated | [fix or "proposed: ..."] |
```

---

## A6: Process Improvement Proposals

Based on pattern analysis, propose concrete improvements that would prevent this category of mistake from recurring. Prioritize by impact:

**Tier 1 — Automate it away** (highest value):
- Can a pre-commit hook catch this?
- Can a CI check prevent this from reaching main?
- Can a linter rule flag this?
- Can the tool configuration be changed to make the wrong thing harder?

**Tier 2 — Make it a skill/checklist**:
- Can a `/skill` encode the correct procedure so agents always follow it?
- Can a checklist in a process doc prevent the wrong order of steps?

**Tier 3 — Document it more visibly**:
- Should it be promoted from `docs/solutions/` to `AGENTS.md` (if it's short and universal)?
- Should it be added to a pre-task checklist?

**Tier 4 — Accept and track**:
- If none of the above is practical, add it to `notes/recurring-patterns.md` with status `accepted` and a note on why it can't be automated.

For each proposed improvement, write it as an action item:

```
## Process Improvement Proposals

### High Priority (3+ recurrences):
- [ ] [Tag: database/migrations] — 4 occurrences. Propose: add a pre-commit hook that
      runs `alembic check` before any commit touching `models/`. See: docs/solutions/2025-11-*

### Medium Priority (2 recurrences):
- [ ] [Tag: auth] — 2 occurrences. Propose: add auth-specific section to AGENTS.md gotchas.

### Newly Documented (1 occurrence — watch for recurrence):
- [ ] [Tag: redis] — 1 occurrence. No action yet; flag if it appears again.
```

---

## A7: Final Report

```
## Compound Step Complete ✓

### Mode: After Task
### Date: [date]
### Branch: [branch]

---

### Knowledge Captured:

**New Solution Files:**
- docs/solutions/YYYY-MM-DD-name.md
  Problem: [one-line]
  Solution: [one-line]
  Tags: [tags]
  Dead ends documented: [yes/no]

**Process Docs:**
- docs/processes/deploy-staging.md [created/updated]
  Added: [what section / what changed]

**Agent Guides:**
- (none / docs/agent-guides/X-guide.md updated)

**AGENTS.md:**
- (unchanged / +N lines, now M lines total)

**Working Memory:**
- notes/agent-progress.md updated

---

### Repeat Mistake Detection:
- [NEW — not seen before] or
- [REPEAT — matches docs/solutions/YYYY-MM-DD-name.md, file updated]

---

### Pattern Analysis:

Top tags in docs/solutions/:
  [N]x database  [N]x auth  [N]x deployment  ...

Recurring patterns (3+ occurrences):
  ⚠️ [tag]: [N] occurrences — added to notes/recurring-patterns.md

---

### Process Improvement Proposals:
- [ ] [High] [proposal]
- [ ] [Medium] [proposal]
- (none if no patterns detected)

---

### AGENTS.md Health:
Current size: [N] lines ([healthy / ⚠️ getting long — consider offloading to agent-guides])

### Proposed Skills (for future /compound-engineering run):
- (none / list)
```

---

## Compound Accounting (for Ralph Loop)

If running inside a Ralph Loop iteration, append to `notes/agent-progress.md`:

```markdown
### Iteration Log — YYYY-MM-DD HH:MM

**Task completed**: [name]
**Commit**: [hash]
**Duration**: ~X minutes
**Solutions captured**: [N new files]
**Processes documented**: [N new/updated]
**Patterns flagged**: [N recurring]
**AGENTS.md delta**: +N lines
**Next task**: [from PRD/todo]
```

---

## Quick Reference

| Situation | Command |
|-----------|---------|
| Starting a task — what do we know? | `/compound before` |
| Finished a task — capture lessons | `/compound` or `/compound after` |
| System is set up? | Check: `ls docs/solutions/ docs/processes/ notes/` |
| System not set up | Run `/compound-engineering` first |
| Find past lessons manually | `grep -ril "keyword" docs/solutions/ docs/processes/` |
| See recurring patterns | `cat notes/recurring-patterns.md` |
