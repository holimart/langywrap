---
name: inspect-projects
description: Quickly status or deeply diagnose Ralph-coupled projects from LANGYWRAP_PROJECTS
license: MIT
compatibility: claude-code, opencode
metadata:
  audience: agents
  purpose: project-inspection
---

# Inspect Ralph Projects

Use this skill to inspect projects registered in langywrap's repo-root `.env`.
It wraps `scripts/inspect-projects/inspect_projects.py` and returns either a fast
status table or a deeper debugging bundle for later analysis.

## Argument Parsing

Arguments support these forms:

- No args, `status`, or `quick` means quick status for every configured project.
- `status <project...>` or `quick <project...>` means quick status for selected projects.
- `progress <project...>` means compare current git HEADs with the previous inspection baseline.
- `deep <project...>` means full diagnosis for selected projects.
- `deep --commits N --artifacts N <project...>` passes through collector limits.
- A bare project name is treated as `deep <project>`.

## Quick Status Workflow

Run the collector in fast mode:

```bash
scripts/inspect-projects/inspect_projects.py --status-only <projects>
```

Report the printed table directly. Highlight any project where:

- `tasks.md` is missing.
- `progress.md` is missing in the bundle summary.
- tmux state is `not-running`, `shell-open`, or `awaiting-input-or-finished`.
- remote SSH access failed.

Do not run Ralph dry-runs in quick mode.

## Progress Workflow

Run the collector in progress mode when the user asks what changed or which
projects advanced since the last inspection:

```bash
scripts/inspect-projects/inspect_projects.py --progress-only <projects>
```

This compares each current git `HEAD` to `.log/inspect-projects/latest_state.json`
and updates that baseline after the run. Use `--no-update-latest` only when the
user wants a read-only comparison.

Report projects as `advanced`, `unchanged`, or `new-baseline`. If a project is
dirty, mention that the commit hash alone does not capture uncommitted work.

## Deep Diagnosis Workflow

Run the collector in full mode:

```bash
scripts/inspect-projects/inspect_projects.py --commits 10 --artifacts 20 <projects>
```

Then inspect the generated bundle under:

```text
.log/inspect-projects/<timestamp>/<project>/
```

For each requested project, read and summarize:

- `summary.json` for paths, mode, and tmux classification.
- `git/state.json` for the inspected commit, branch, dirty count, and previous baseline comparison.
- `dry_run.raw.txt` and `dry_run.json` for Ralph config, router, prompt-contract, and state-file issues.
- `state/tasks.md` for blocked, stale, malformed, or suspicious task state.
- `state/progress.md` for the latest real progress and repeated failure patterns.
- `git/latest_commits.txt` for recent code or task/progress changes.
- `artifacts/manifest.txt` and the newest copied step/log files for the immediate failure context.
- `tmux/status.json` and `tmux/pane_capture.txt` for whether the live loop is running, idle, finished, or waiting for input.

Prioritize findings in this order:

- Active blockers that require user input or credentials.
- Ralph config or dry-run failures.
- Missing or stale state files.
- Repeated step failures or no recent artifact growth.
- Recent commits that likely introduced the regression.

## Remote Langywrap Sync Check

For every remote project entry like `user@host:/path/to/project`, also check the
sibling langywrap repository on that remote host because it may be out of sync
with this local langywrap checkout.

Infer the remote sibling path as:

```text
<remote-project-parent>/langywrap
```

Use non-destructive git checks only:

```bash
ssh user@host 'cd /path/to/langywrap && git status --short && git log -1 --oneline'
git -C /mnt/work4t/Projects/langywrap log -1 --oneline
```

Report if the remote sibling `langywrap` is missing, dirty, on a different HEAD,
or otherwise likely to be running older Ralph/helper code. Do not pull, push,
reset, or edit the remote sibling unless explicitly asked.

## Langywrap Fix → Push → Remote Pull → Restart Workflow

When a bug in langywrap itself causes loops to fail fleet-wide (e.g. an engine
mismatch, a config parsing error, a runner regression), the repair cycle is:

1. **Stop affected loops** — send `C-c` to each tmux pane before editing code.
   For remote loops: `ssh user@host 'tmux send-keys -t ralph-project C-c'`.
   Stop all affected projects before patching so none restarts mid-fix.

2. **Fix and verify locally** — edit the langywrap library, run `./just check`
   (lint + typecheck + 874 tests). Do not skip this step even for small patches.

3. **Commit and push**:

   ```bash
   git add <changed files>
   git commit -m "fix(ralph): ..."
   git push
   ```

4. **Pull on every remote host** that runs affected projects:

   ```bash
   ssh user@host 'cd /path/to/langywrap && git pull'
   ```

   Confirm the pull output shows the fix commit. A fast-forward with no output
   means the remote was already up to date — double-check the remote HEAD.

5. **Restart all affected loops** with the same `--replace-model` flags as
   before (substitutions are not persisted; they must be re-supplied on each
   `langywrap ralph run` invocation).

6. **Verify** with `--status-only --model-details` for each project. Look for
   `running` tmux state and the expected `anth X%/oa Y%/oth Z%` distribution.

### Engine auto-flip: opencode → claude on Anthropic substitution

As of 2026-05-16, `apply_model_substitutions` in `langywrap.ralph.config`
automatically switches the engine from `opencode` to `claude` when a model
substitution replaces a model with an Anthropic/Claude model (`claude-*` or
`anthropic/*`). OpenCode does not accept bare `claude-*` model IDs and returns
`Model not found: claude-sonnet-4-6/.` immediately, causing 3 consecutive failed
cycles and a loop stop.

**Symptoms of the pre-fix bug:**
- Loop stops after exactly 3 cycles with all token counts at 0.
- Pane log shows `Model not found: claude-sonnet-4-6/.` from opencode.
- `--status-only` reports `done 3; confirmed 0/3` and model mix reverts to
  original percentages (replacements not shown because loop exited).

**If you hit this on an older langywrap:** pull the fix commit (`c19cacd`) on
every host, then restart with `--replace-model` flags.

## Ralph Session Control And Resume

Use this workflow when the user asks to resume paused loops across projects:

- First run `scripts/inspect-projects/inspect_projects.py --status-only --model-details`.
- Treat `running` as already active; do not restart it unless explicitly asked.
- Treat `awaiting-input-or-finished` with `active_process: false` as resumable.
- Treat `not-running` as startable if `tasks.md` has pending tasks.
- For unified task-format lint failures, compare HEAD, staged, and unstaged
  `tasks.md` before blaming the generator. Dirty task-ledger rewrites can
  reintroduce old headers; normalize only malformed headers and preserve local
  edits. See `docs/solutions/2026-05-13_ralph_tasks_unified_format_regression.md`.
- Do not resume a project whose task queue is complete, even if its tmux pane is idle.
- Read the relevant `summary.json` or `tasks.md` before deciding whether an idle pane is paused, finished, or blocked.
- If a project stopped because `tasks.md` has `Pending: (none)`, run an
  empty-queue methodology audit before accepting completion. Inspect recent
  `progress.md` for skipped tiers, weak/no-signal scans, refuted cheap-tool hits,
  `needs-poc`, informational repros, and missing learning decisions. Check
  `findings.md` and backlog, then queue detector/suppression/tier-support,
  findings-ledger, caseinit, or discovery work when warranted. See
  `docs/solutions/2026-05-13_ralph_empty_queue_methodology_audit.md`.

Default Ralph cycle behavior can be surprising. If the user wants a specific run
length, always pass it explicitly:

```bash
langywrap ralph run --resume --budget 50 .
```

Local existing-pane resume pattern:

```bash
tmux send-keys -t ralph-project "cd /path/to/project && langywrap ralph run --resume --budget 50 ." C-m
```

Local start pattern when no tmux session exists:

```bash
cd /path/to/project && langywrap ralph run --resume --budget 50 .
```

Remote existing-pane resume pattern. Quote the whole remote command so `&&` runs
inside the tmux pane rather than in the SSH shell:

```bash
ssh user@host 'tmux send-keys -t ralph-project "cd /path/to/project && langywrap ralph run --resume --budget 50 ." C-m'
```

If a bad remote send leaves partial input at the prompt, clear it before resending:

```bash
ssh user@host 'tmux send-keys -t ralph-project C-c'
```

Model replacement syntax is `--replace-model FROM=TO`. Quote glob replacements so
the local shell, SSH shell, and remote shell do not expand `*`. Substitutions are
**not persisted** — they must be re-supplied on every `langywrap ralph run`
invocation. When a loop stops and you restart it, always include the same flags.

Typical fleet-wide replacement (replace all gpt and kimi slots with Sonnet):

```bash
# local
tmux send-keys -t ralph-project "cd /path/to/project && langywrap ralph run --resume --budget 50 --replace-model '*gpt*=claude-sonnet-4-6' --replace-model '*kimi*=claude-sonnet-4-6' ." C-m

# remote — use \* inside the double-quoted pane command
ssh user@host 'tmux send-keys -t ralph-project "cd /path/to/project && langywrap ralph run --resume --budget 50 --replace-model \*gpt\*=claude-sonnet-4-6 --replace-model \*kimi\*=claude-sonnet-4-6 ." C-m'
```

When substituting to a Claude model on a step that was `engine="opencode"`,
langywrap automatically switches the engine to `claude` (fix landed 2026-05-16,
commit `c19cacd`). If running an older langywrap, stop all loops, pull the fix on
every host, then restart — see the **Langywrap Fix → Push → Remote Pull →
Restart Workflow** section above.

Verify the resume after sending commands:

```bash
scripts/inspect-projects/inspect_projects.py --status-only --model-details
```

For model substitutions, confirmation is a `replacements:` line in model details
and provider percentages changing as expected. A fleet-wide Claude-only run shows
`anth 100%/oa 0%/oth 0%` for every project.

Common lesson: `bash: line 1: langywrap: command not found` immediately after an
SSH `tmux send-keys` command can mean the command was quoted incorrectly and the
remote SSH shell executed the second half of `cd ... && langywrap ...` outside
tmux. It does not necessarily mean the tmux pane lacks `langywrap`.

## Response Shape

For quick status, return a compact table plus only critical notes.

For deep diagnosis, return:

- Bundle path.
- Findings ordered by severity.
- Evidence paths, including file names inside the bundle.
- Suggested next command or next debugging step.

Do not claim a Ralph dry-run passed unless the bundle shows a successful dry-run
command and no relevant findings in its output.

## Compound/Memento Follow-Up

After any deep diagnosis that discovers a real bug, recurring Ralph failure,
missing collector evidence, stale remote setup, or confusing workflow gap, do the
compound step before finishing:

- Add or update a `docs/solutions/YYYY-MM-DD-*.md` entry when the finding is a reusable lesson, non-obvious root cause, or bug future agents are likely to hit.
- Update `scripts/inspect-projects/inspect_projects.py` when the collector failed to capture evidence that would have made the diagnosis easier.
- Update this skill when the diagnostic procedure itself changes, such as a new tmux state, remote sync check, Ralph artifact location, or triage heuristic.
- Update `.opencode/command/inspect-projects.md` if the OpenCode workflow should mirror the same procedural change.

Treat those updates as part of the repair when they are small and directly caused
by the diagnosis. If the improvement is larger or product-defining, report it as
a recommended follow-up instead of making broad changes silently.

End the response with a short "Learning captured" note stating which lesson,
skill, or helper script was updated. If nothing was worth capturing, say why.
