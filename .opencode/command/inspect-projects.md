---
description: Quickly status or deeply diagnose Ralph-coupled projects
---

# Inspect Ralph Projects

Use `scripts/inspect-projects/inspect_projects.py` from the langywrap repo root.

Interpret `$ARGUMENTS` as:

- No args, `status`, or `quick`: run quick status for all projects.
- `status <project...>` or `quick <project...>`: run quick status for selected projects.
- `status --model-details <project...>` or `quick --model-details <project...>`: run quick status and print full per-step model/provider details.
- `progress <project...>`: compare current git HEADs with the previous inspection baseline.
- `deep <project...>`: run deep diagnosis for selected projects.
- Bare project name: treat as `deep <project>`.

Quick status command:

```bash
scripts/inspect-projects/inspect_projects.py --status-only <projects>
```

Quick status prints compact provider percentages. When the user asks to discuss
step/model usage, add `--model-details`:

```bash
scripts/inspect-projects/inspect_projects.py --status-only --model-details <projects>
```

The collector writes `model_mix.json` in each project bundle and applies live
`--replace-model` arguments parsed from the running Ralph tmux process. Report
`models: error` entries, especially for remote projects whose environment cannot
import the matching langywrap helper.
If that helper is a new local langywrap change, the fix is to commit and push
local langywrap, then pull it in the sibling remote langywrap checkout. Only do
this when explicitly requested.

Deep diagnosis command:

```bash
scripts/inspect-projects/inspect_projects.py --commits 10 --artifacts 20 <projects>
```

Progress comparison command:

```bash
scripts/inspect-projects/inspect_projects.py --progress-only <projects>
```

Progress mode compares current git `HEAD` values with
`.log/inspect-projects/latest_state.json` and updates that baseline unless
`--no-update-latest` is passed.

Inspection bundles are written under:

```text
.log/inspect-projects/<timestamp>/<project>/
```

For deep diagnosis, inspect `summary.json`, `git/state.json`, `dry_run.raw.txt`,
`dry_run.json`, `state/tasks.md`, `state/progress.md`, `git/latest_commits.txt`,
`artifacts/`, and `tmux/` before answering.

For every remote project entry like `user@host:/path/to/project`, also check the
sibling remote langywrap repo because it may be out of sync with this local one:

```text
user@host:/path/to/langywrap
```

Use only non-destructive checks such as:

```bash
ssh user@host 'cd /path/to/langywrap && git status --short && git log -1 --oneline'
git -C /mnt/work4t/Projects/langywrap log -1 --oneline
```

Report missing, dirty, or different remote langywrap HEADs. Do not pull, push,
reset, or edit the remote sibling unless explicitly requested.

When explicitly requested to sync helper code for remote inspection, use normal
non-force git flow only: commit local langywrap changes, push, then run
`git pull --ff-only` in the sibling remote langywrap checkout. Do not force-push
or reset the remote checkout.

## Debug, Repair, Restart Workflow

When a loop is failed and the user asks for repair or restart:

- Read `tmux/status.json`; if it has `error`, read `tmux/error.txt`.
- Treat `awaiting-input-or-finished+error` as stopped. Diagnose the newest error
  excerpt, not stale pane scrollback.
- If status is `running`, do not restart; report current step/heartbeat evidence.
- For generated task/helper failures, inspect the langywrap generator before
  blaming the downstream repo.
- For remote projects, verify the sibling remote `langywrap` has any needed source
  fix because the project venv may import from that sibling checkout.
- Make only targeted remote edits when explicitly asked to repair or restart.
- Validate the exact failed condition before restart, e.g. run `lint_tasks` with
  the downstream repo's configured task types.
- Restart in the existing tmux pane with `--no-tmux` to avoid nested sessions.
- Re-run `scripts/inspect-projects/inspect_projects.py --status-only <project>`
  and confirm the loop is `running` or past the old failure.

Remote restart pattern:

```bash
ssh user@host 'tmux send-keys -t ralph-project "cd /path/to/project && path/to/langywrap ralph run -n 50 --resume --no-tmux ." C-m'
```

Common signatures:

- Remote `git-error: fatal: not a git repository` can be SSH quoting, not a bad path.
- `shell-open` with `[ralph]` heartbeats means helper-launched process detection is missing.
- `Ralph finished (exit "1")` means stopped; fix the nearest traceback/hard-fail.
- `inline_orient` lint failures on generated lines mean injector/linter drift; add linter-backed injector tests.

## Compound/Memento Follow-Up

After any deep diagnosis that finds a real bug, recurring Ralph failure, stale
remote setup, missing collector evidence, or confusing workflow gap:

- Add or update `docs/solutions/YYYY-MM-DD-*.md` for reusable lessons.
- Update `scripts/inspect-projects/inspect_projects.py` if the collector missed
  evidence needed for diagnosis.
- Update `skills/inspect-projects.md` and this OpenCode command if the workflow
  itself changed.

Make small, directly relevant learning updates as part of the repair. For larger
changes, report the recommended follow-up instead. End with a brief "Learning
captured" note naming what changed, or say why no capture was needed.
