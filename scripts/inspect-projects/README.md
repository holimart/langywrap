# Project Inspection Helpers

Collect Ralph debugging context from projects listed in the repo-root `.env`.

## Usage

```bash
scripts/inspect-projects/inspect_projects.py
scripts/inspect-projects/inspect_projects.py --status-only
scripts/inspect-projects/inspect_projects.py --status-only --model-details
scripts/inspect-projects/inspect_projects.py --progress-only
scripts/inspect-projects/inspect_projects.py ktorobi sportsmarket
scripts/inspect-projects/inspect_projects.py --commits 20 --artifacts 40 riemann2
scripts/inspect-projects/inspect_projects.py --skip-dry-run whitehacky
```

## Inputs

The script reads:

```env
LANGYWRAP_PROJECTS=ktorobi,whitehacky
LANGYWRAP_PROJECT_KTOROBI=/path/to/ktorobi
LANGYWRAP_PROJECT_RIEMANN2=user@host:/path/to/riemann2
```

Local paths and `user@host:/path` SSH locations are supported.

## Output

Inspection bundles are written under:

```text
.log/inspect-projects/<timestamp>/<project>/
```

Each project bundle includes:

- `dry_run.raw.txt` and, when parseable, `dry_run.json`
- `state/tasks.md` and `state/progress.md`
- `git/state.json`
- `git/latest_commits.txt`
- `artifacts/` with latest Ralph `steps/` and `logs/` text files
- `tmux/status.json` and `tmux/pane_capture.txt`
- `model_mix.json` with effective step model/provider percentages
- `summary.json`

The script also writes these top-level files:

- `.log/inspect-projects/<timestamp>/git_state.json` for the current run.
- `.log/inspect-projects/latest_state.json` as the persistent comparison baseline.

Tmux sessions are checked as `ralph-<project-directory-name>`, matching the
`langywrap ralph run` launcher convention.

Use `--status-only` for a fast scan that skips dry-run, git history, and
artifact copying while still resolving state paths and checking tmux sessions.
It also reports compact provider percentages. Add `--model-details` to print the
full per-step effective model list, including live `--replace-model` substitutions
parsed from the running Ralph tmux process.

Use `--progress-only` to compare current project HEADs with the previous
`latest_state.json` baseline. It records a new baseline unless
`--no-update-latest` is passed.
