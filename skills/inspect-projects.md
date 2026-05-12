---
description: Quickly status or deeply diagnose Ralph-coupled projects from LANGYWRAP_PROJECTS
allowed-tools: Read, Glob, Grep, Bash
---

# Inspect Ralph Projects

Use this command to inspect projects registered in langywrap's repo-root `.env`.
It wraps `scripts/inspect-projects/inspect_projects.py` and returns either a fast
status table or a deeper debugging bundle for later analysis.

## Argument Parsing

`$ARGUMENTS` supports these forms:

- No args, `status`, or `quick` means quick status for every configured project.
- `status <project...>` or `quick <project...>` means quick status for selected projects.
- `status --model-details <project...>` or `quick --model-details <project...>` means quick status plus full per-step model/provider details.
- `progress <project...>` means compare current git HEADs with the previous inspection baseline.
- `deep <project...>` means full diagnosis for selected projects.
- `deep --commits N --artifacts N <project...>` passes through collector limits.
- A bare project name is treated as `deep <project>`.

## Quick Status Workflow

Run the collector in fast mode:

```bash
scripts/inspect-projects/inspect_projects.py --status-only $PROJECTS
```

When the user asks to discuss model usage, configured providers, or per-step
models, include the details flag:

```bash
scripts/inspect-projects/inspect_projects.py --status-only --model-details $PROJECTS
```

Quick status includes a compact model-provider mix column. `--model-details`
prints each step's effective model after live `--replace-model` arguments are
extracted from the Ralph tmux process. The collector writes `model_mix.json` in
each project bundle. Remote projects can report `models: error` when their
environment cannot import the langywrap helper used to load configs directly;
in that case, check the sibling remote langywrap checkout and Python path.
If the missing helper is a new local langywrap change, commit and push the local
langywrap update, then pull it in the sibling remote langywrap checkout before
re-running status. Do not do this automatically unless the user explicitly asks.

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
scripts/inspect-projects/inspect_projects.py --progress-only $PROJECTS
```

This compares each current git `HEAD` to `.log/inspect-projects/latest_state.json`
and updates that baseline after the run. Use `--no-update-latest` only when the
user wants a read-only comparison.

Report projects as `advanced`, `unchanged`, or `new-baseline`. If a project is
dirty, mention that the commit hash alone does not capture uncommitted work.

## Deep Diagnosis Workflow

Run the collector in full mode:

```bash
scripts/inspect-projects/inspect_projects.py --commits 10 --artifacts 20 $PROJECTS
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

For example:

```text
workyone@192.168.0.101:/home/workyone/hddProjects/riemann2
```

should also check:

```text
workyone@192.168.0.101:/home/workyone/hddProjects/langywrap
```

Use non-destructive git checks only:

```bash
ssh user@host 'cd /path/to/langywrap && git status --short && git log -1 --oneline'
git -C /mnt/work4t/Projects/langywrap log -1 --oneline
```

Report if the remote sibling `langywrap` is missing, dirty, on a different HEAD,
or otherwise likely to be running older Ralph/helper code. Do not pull, push,
reset, or edit the remote sibling unless explicitly asked.

When the user explicitly asks to sync helper code for remote inspection, use
normal non-force git flow only: commit the local langywrap changes, push them,
then run `git pull --ff-only` in the sibling remote langywrap checkout. Never
force-push or reset the remote checkout as part of inspection.

## Debug, Repair, Restart Workflow

When status or deep diagnosis shows a failed Ralph loop, use this loop before
answering if the user asked for repair or restart:

- Read `tmux/status.json` first. If it contains `error`, read `tmux/error.txt`.
- If `tmux` is `awaiting-input-or-finished+error`, treat the pane as stopped and
  diagnose the newest error excerpt, not older scrollback.
- If `tmux` is `running`, do not restart. Report the current step and any fresh
  heartbeats from `tmux/pane_capture.txt`.
- If the failure came from a generated task line or helper output, inspect the
  langywrap source that generated it before blaming the downstream repo.
- If the project is remote, check whether the remote sibling `langywrap` has the
  same source fix as the local checkout. Remote Ralph may import from the sibling
  source tree even when invoked through the project venv.
- Make only targeted remote edits needed to unblock the loop when explicitly
  asked to repair or restart. Never pull, push, reset, or broadly sync remotes
  without explicit permission.
- Before restart, run the same narrow validation that failed, for example
  `langywrap.ralph.lint_tasks` with the downstream repo's configured task types.
- Restart inside the existing tmux pane when possible, using `--no-tmux` so the
  command runs in that pane instead of nesting tmux sessions.
- After restart, re-run `inspect_projects.py --status-only <project>` and verify
  the status is `running` or that it has progressed past the previous failure.

Useful restart pattern for a remote pane:

```bash
ssh user@host 'tmux send-keys -t ralph-project "cd /path/to/project && path/to/langywrap ralph run -n 50 --resume --no-tmux ." C-m'
```

If an old traceback remains in tmux scrollback after a successful restart, rely on
the inspector's scoped `tmux.error` for the latest Ralph run. Do not report stale
errors from before the newest `RalphLoop starting:` marker as active failures.

### Common Failure Signatures

- `git-error: fatal: not a git repository` on a remote project can be an SSH
  quoting bug, not a missing `.git`. Verify the remote directory exists and has
  `.git`; remote `bash -lc` commands must be sent as one quoted command string.
- `shell-open` with `[ralph]` heartbeats in the pane means the classifier missed a
  helper-launched process. Inspect the pane process tree and update the collector
  if needed.
- `awaiting-input-or-finished+error` with `Ralph finished (exit "1")` means the
  loop is stopped. Extract and fix the nearest traceback or hard-fail report.
- `inline_orient: preflight lint hard-failed` on an injected line usually means a
  task injector drifted from `lint_tasks`' unified format. Add linter-backed tests
  for the injector, fix the downstream bad line, patch the source used by the
  running loop, then restart.

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

- Add or update a `docs/solutions/YYYY-MM-DD-*.md` entry when the finding is a
  reusable lesson, non-obvious root cause, or bug future agents are likely to hit.
- Update `scripts/inspect-projects/inspect_projects.py` when the collector failed
  to capture evidence that would have made the diagnosis easier.
- Update this skill when the diagnostic procedure itself changes, such as a new
  tmux state, remote sync check, Ralph artifact location, or triage heuristic.
- Update `.opencode/command/inspect-projects.md` if the OpenCode workflow should
  mirror the same procedural change.

Treat those updates as part of the repair when they are small and directly caused
by the diagnosis. If the improvement is larger or product-defining, report it as
a recommended follow-up instead of making broad changes silently.

End the response with a short "Learning captured" note stating which lesson,
skill, or helper script was updated. If nothing was worth capturing, say why.
