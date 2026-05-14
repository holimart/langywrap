---
date: "2026-05-14"
tags: [ralph, finalize, coverage-budget, mode-collapse, prompt-engineering, validator]
problem: "Finalize LLM stamps every cycle as TASK_TYPE: documentation, blinding the coverage-budget engine and locking the loop onto one task"
solution: "Prompt fix forcing TASK_TYPE inheritance from orient.md + new postflight validator (langywrap.ralph.validate_progress) chained into the finalize Gate + upgrade finalize to gpt-5.4"
symptoms: "progress.md last N entries all show `TASK_TYPE: documentation` despite orient.md picking `lean`/`research`; coverage-budget violations fire every cycle but picker rotation never happens; same `task:*` slug wins ~30% of all cycles"
affected-files:
  - lib/langywrap/ralph/validate_progress.py
  - tests/test_ralph/test_validate_progress.py
  - <repo>/.langywrap/ralph.py
  - <repo>/research/ralph/prompts/step4_finalize.md
  - <repo>/research/ralph/prompts/step2_plan.md
applies-to: "Any langywrap-coupled repo running the 5-step ralph pipeline whose finalize prompt uses the YOU ARE A STATE-UPDATE-ONLY AGENT framing"
time-to-discover: "~1 hour: spotted 36% B11 task domination in riemann2 cycle history, traced to coverage_budget reading TASK_TYPE=documentation on 14/15 last cycles, traced to finalize prompt's `<...documentation...>` placeholder + self-role-labeling priming"
agent-note: "When auditing any ralph loop: grep `TASK_TYPE:` in progress.md. If it is `documentation` on >50% of recent cycles for cycles whose orient.md said something else, this bug is live. Fix-in-one-shot: copy this lesson's prompt rule, prompt-section additions, validate_progress.py invocation, and gpt-5.4 model swap into the affected repo. Check both step4_finalize.md and step2_plan.md."
project-origin: "riemann2"
---

# Finalize task-type misstamp → coverage budget blinded → mode collapse

## Context

Auditing riemann2 the morning of 2026-05-14 to validate yesterday's
progress. The loop had completed 55 cycles between 2026-05-13 00:00 and
2026-05-14 ~11:00.

## Problem

**Symptom 1 — task domination.** 16 of 55 cycles (29%) worked on a single
task: `task:lean-b11-monotonicity-single-fold`. Adding `task:sorry-b11-monotonicity`
brings the figure to 36% of all cycles on B11 monotonicity in some form.
Net mathematical progress on that file over 13 cycles was **negative**
(1 sorry → 3 sorries; the bridge decomposition kept re-splitting without
closing the parent).

**Symptom 2 — engine fires but cannot rotate.** Every orient.md in the
window reported `**Violations:** research (need ≥20% over last 12),
lean (need ≥40% over last 12)`. The coverage-budget engine `evaluate_coverage`
in `lib/langywrap/ralph/coverage_budget.py` correctly detected starvation
of both research and lean, then `filter_eligible_tasks` correctly
restricted the pending pool to those two types. But the highest-priority
eligible task in that union was always the same P1 lean B11 task, so
the picker handed the loop back to B11 *every cycle*.

**Symptom 3 — the smoking gun.** `progress.md` cycle 1577–1589:

```
## Cycle 1589 — FINALIZE: B11 FTC/API repair state consolidation (2026-05-13)
TASK_TYPE: documentation
## Cycle 1588 — FINALIZE: B11 lean-cycle blocked-state consolidation (2026-05-13)
TASK_TYPE: documentation
## Cycle 1587 — FINALIZE: B11 bridge decomposition state consolidation (2026-05-13)
TASK_TYPE: documentation
... (13 of last 15 cycles labelled `documentation`)
```

…even though the corresponding `orient.md` for every one of those cycles
emitted `TASK_TYPE: lean`. The coverage engine reads progress.md, not
orient.md, so its view of the last 12 cycles was
`Counts: documentation=12`. **Both budgets violate every cycle by
construction**, and "research ∪ lean" eligibility includes every P1 lean
task in the queue. Selection pressure → zero.

## Root cause

Two interacting prompt-engineering bugs:

1. **TASK_TYPE placeholder lets the LLM choose.** `step4_finalize.md`
   Section B's template literally read:
   ```
   TASK_TYPE: <research|lean|governance|hygiene|adversarial|documentation|fix|lookback|fallback>
   ```
   No instruction to *copy* from orient.md. The `runner.py:757` source
   comment claims "FINALIZE copies the orient label across" — that was
   never enforced by the prompt and never validated by code.

2. **Self-labeling priming.** The same prompt opens with
   `## CRITICAL CONSTRAINTS — YOU ARE A STATE-UPDATE-ONLY AGENT`. The
   LLM (kimi-k2.6 in riemann2's default variant) reads this, looks at the
   placeholder, and reasonably concludes "I am doing documentation/
   consolidation work, so `TASK_TYPE: documentation` is the correct
   label." It is not — the label describes the *underlying* cycle.

A secondary, related defect: **plan.md proposals never reach finalize.**
The plan step's prompt has language like "If you discover a new direction
during planning, note it as a future task," but the plan template has no
structured `## Proposed New Tasks` section, and finalize's input list in
step4_finalize.md does *not* include plan.md. Plan's strategic foresight
was silently dropped every cycle.

## Solution

Four changes, applied to langywrap (library + tests + lesson) and to the
affected downstream repo (riemann2):

1. **`lib/langywrap/ralph/validate_progress.py`** (new, ~150 LOC + CLI).
   Diffs orient.md's structured `TASK_TYPE:` token against the latest
   cycle block in progress.md (using `parse_cycle_blocks` so it stays in
   lockstep with the coverage engine's view). Exits 1 with an actionable
   diagnostic on mismatch.

2. **Finalize prompt** (`step4_finalize.md`):
   - New `⚠️ TASK_TYPE INHERITANCE RULE` block right after the framing,
     explicitly forbidding self-labeling and telling the LLM the gate
     exists.
   - Section B template now says "copy verbatim from orient.md."
   - Section E split into E0 (plan-proposed) and E1 (Lean-pipeline) so
     plan's foresight is honored.
   - Step-1 input list adds plan.md; outputs checklist adds the new items.

3. **Plan prompt** (`step2_plan.md`): new structured
   `## Proposed New Tasks` section in the plan.md template with explicit
   per-task block schema (`task_type`/`priority`/`slug`/`label`/`why`)
   and "default P2, never auto-elevate to P0" rule.

4. **Per-repo config** (`<repo>/.langywrap/ralph.py`):
   - New `FINALIZE_MODEL = "openai/gpt-5.4"` constant used only by the
     finalize Step (kimi/codex stay on execute and fix). Finalize is
     structured-output + judgment work, not code writing.
   - Finalize's retry Gate command is extended with `&& uv run python -m
     langywrap.ralph.validate_progress --orient ... --progress ...`. On
     mismatch the retry fires and the diagnostic is injected into
     retry_error context, so the next finalize attempt sees the rule.

## Metrics

Before (riemann2, cycles 1575–1589 / 15 cycles):
- TASK_TYPE: documentation × 14, lean × 1
- coverage-budget violations: lean + research every cycle (cannot resolve)
- B11 monotonicity share of cycles: 36%
- B11 file sorry trend: 1 → 3 (regression)

After (verified by smoke-test against the broken live state):
- `validate_progress.py` correctly identifies the mismatch:
  `TASK_TYPE mismatch on cycle 1589. orient.md picked lean ... progress.md
   was stamped documentation. ... rewrite to read lean.`
- Postflight gate now fails finalize and forces a retry with this
  diagnostic inside `retry_error`. Real measurement of post-fix
  recovery will be reflected in cycles ≥ 1590.

## Code reference

- `lib/langywrap/ralph/validate_progress.py` — new CLI validator
- `tests/test_ralph/test_validate_progress.py` — 14 tests (all pass)
- `lib/langywrap/ralph/runner.py:752–761` — the source comment that
  asserted "FINALIZE copies the orient label across" without enforcement
- `lib/langywrap/ralph/coverage_budget.py:127–170` — the engine that was
  reading the polluted label
- `lib/langywrap/ralph/markdown_todo.py:203–265` — `parse_cycle_blocks` /
  `TASK_TYPE_BODY_RE` reused by the validator

## Related tasks

- Audit follow-up (TODO): apply the same prompt + config fix to other
  ralph-coupled repos. Check whether each repo's finalize prompt has
  identical placeholders / self-labeling framing, and whether its
  plan prompt has any structured channel for proposed new tasks.

## Agent note

When asked to audit a ralph loop:

1. Pull latest in the target repo.
2. `grep -E "^TASK_TYPE:" <state>/progress.md | head -20` — if
   `documentation` dominates and the corresponding orient.md said
   anything else, this bug is live.
3. `git log --since="<window>" --format="%s" | sed 's/.*Task: \?\(.\{1,80\}\).*/\1/' | sort | uniq -c | sort -rn` — if one task >25% of cycles, mode collapse is real.
4. Apply: copy validate_progress.py + the four prompt/config edits.
5. Smoke-test:
   `uv run python -m langywrap.ralph.validate_progress --orient ... --progress ...`
   should exit 1 once against the polluted state, then 0 after the next
   finalize-retry rewrites the entry.
