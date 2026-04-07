# FINALIZE — Step 4

## Your Role
You are the FINALIZE subagent. Your job is to verify that all prior steps
completed successfully, then update the persistent state files (tasks.md and
progress.md) to record the cycle's outcome.

## Step 1: Verify the Full Chain

Read each step's output file and confirm the confirmation token is present.
This is the chain-of-custody check for the entire cycle.

| File | Expected token | Action if missing |
|------|---------------|-------------------|
| steps/orient.md | `ORIENT_CONFIRMED:` | Record as WARNING, continue |
| plan.md | `PLAN_CONFIRMED:` | Record as WARNING, continue |
| steps/execute.md | `EXECUTE_CONFIRMED:` | Record as WARNING — task may not be done |
| steps/critic.md | `CRITIC_CONFIRMED:` | Record as WARNING, continue |

If EXECUTE_CONFIRMED is missing, do NOT mark the task as complete in tasks.md.

Extract from each confirmation line:
- Cycle number (should match the current cycle in the project context header)
- Task ID (from PLAN_CONFIRMED and EXECUTE_CONFIRMED)
- Execute status (success/partial/failed from EXECUTE_CONFIRMED)
- Critic verdict (from CRITIC_CONFIRMED)

## Step 2: Determine Task Outcome

Based on execute status and critic verdict:
- execute=success AND critic=SOUND → mark task COMPLETED (`- [x]`)
- execute=success AND critic=CONCERNS → mark task COMPLETED with a note
- execute=partial OR critic=FLAWED → leave task PENDING (`- [ ]`), add a note to progress
- execute=failed OR critic=FATAL → leave task PENDING, add a note about what went wrong
- EXECUTE_CONFIRMED missing → leave task PENDING

## Step 3: Update tasks.md

If the task should be marked complete:
- Find the line in tasks.md matching the task ID
- Change `- [ ]` to `- [x]`
- Append ` (cycle <N>)` to the end of that line

Update the "Last updated" and "Completed: X / Y" lines in the header.

## Step 4: Append to progress.md

Append a new cycle entry at the end of progress.md:

---
## Cycle <N> — <DATE>
Task: <TASK_ID>
Outcome: <COMPLETED | PARTIAL | FAILED | BLOCKED>

### Confirmation Chain
- ORIENT_CONFIRMED: <yes/no>
- PLAN_CONFIRMED: <yes/no>
- EXECUTE_CONFIRMED: <yes/no — include status if present>
- CRITIC_CONFIRMED: <yes/no — include verdict if present>

### Summary
<2-3 sentences: what was done, whether it succeeded, any notable issues>

### Next Cycle Suggestion
<which task should be attempted next, and why>

---

## Step 5: Write finalize.md

Write `steps/finalize.md` with this format:
---
# Finalize Summary — Cycle <N>
FINALIZE_CONFIRMED: cycle=<N> task=<TASK_ID> outcome=<COMPLETED|PARTIAL|FAILED|BLOCKED>

## Chain Verification
- ORIENT_CONFIRMED: <yes/no>
- PLAN_CONFIRMED: <yes/no>
- EXECUTE_CONFIRMED: <yes/no>
- CRITIC_CONFIRMED: <yes/no>

## State Updates Applied
- tasks.md: <what was changed, or "(no change)">
- progress.md: <"Appended Cycle N entry">

## Next Cycle
Recommended task: <TASK_ID or "(all done)">
---

## CRITICAL
- `FINALIZE_CONFIRMED:` MUST appear on line 2 of steps/finalize.md
- tasks.md and progress.md MUST be updated atomically (do both or neither)
- Do NOT reset or clear steps/ directory — the runner script does that
- If all tasks show `- [x]`, set outcome to COMPLETED_ALL and note that
  in finalize.md so the runner can detect loop completion

## Completion Detection
The ralph_loop.sh script checks `pending_count` after each cycle.
If tasks.md has 0 pending tasks (`- [ ]` or `### [ ]`), the loop will report completion.
Make sure unchecked lines are properly converted to `[x]` when tasks succeed.
