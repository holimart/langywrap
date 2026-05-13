---
date: "2026-05-13"
tags: [ralph, tasks-md, lint, unified-format, working-tree]
problem: "Ralph inline_orient can hard-fail on old task checkbox headers that were reintroduced by local task-ledger rewrites after the unified-format migration."
solution: "When lint reports malformed task headers, compare HEAD, staged, and unstaged `tasks.md` before blaming the generator; preserve local ledger changes and normalize only the malformed headers."
symptoms: "`inline_orient: preflight lint hard-failed` with `Checkbox line does not match the unified format`, while recent commits already contain unified task headers."
affected-files: ["research/tasks.md", "ralph/tasks.md", "lib/langywrap/ralph/lint_tasks.py", "lib/langywrap/ralph/runner.py"]
applies-to: "Downstream Ralph projects that migrated to `- [ ] **[Pn] task:slug** [task_type] label` task headers."
time-to-discover: "~15 minutes"
agent-note: "A dirty working tree can be the source of malformed tasks even when commit history and generated templates are already fixed."
project-origin: "compricing"
---

# Ralph Tasks Unified Format Regression

## Context

`compricing` was restarted with `langywrap ralph run --resume --budget 50 .`.
The loop created its tmux session but failed immediately in `inline_orient` before
any model call.

## Failure

The linter reported three malformed checkbox headers:

- Completed external LLM-logprob overlay task from cycle 660.
- Completed hygiene task from cycle 660.
- Pending daily Numerai timeout verification task from cycle 651.

Each line used an old style such as:

```text
- [x] **[P1] External LLM-logprob feature overlay sprint0 ...**
```

instead of:

```text
- [x] **[P1] task:external-llm-logprob-overlay-sprint0-c660** [modeling] External LLM-logprob feature overlay sprint0 ...
```

## Root Cause

The committed task history was already mostly unified. The bad headers were in
the dirty working-tree copy of `research/tasks.md`. The local diff showed a large
task-ledger compaction/rewrite that removed many recently closed unified entries
and reintroduced a few old-style headers.

This means the source was not the current scheduled-task template and not the
current inline-orient injector. It was an existing local ledger edit that drifted
from the post-migration format.

## Repair Pattern

1. Read the exact linter lines from the newest tmux error artifact.
2. Validate the configured allowed task types from `.langywrap/ralph.py`.
3. Normalize only the malformed checkbox headers.
4. Preserve task body text and surrounding local ledger edits.
5. Run the linter with the downstream project's configured task types.
6. Restart in the existing pane with `--no-tmux`.
7. Re-run inspect status and confirm the loop is `running`.

Example validation:

```bash
uv run python -m langywrap.ralph.lint_tasks check /path/to/project/research/tasks.md --task-types research,modeling,backtest,numerai,data,tooling,documentation,hygiene,lookback,fix --max-active 2
```

## Prevention

When a unified-format lint error appears after migration:

- Check `git diff -- tasks.md` and `git diff --cached -- tasks.md`.
- Check whether `HEAD:tasks.md` already has unified headers.
- If HEAD is clean but the working tree is malformed, repair the local ledger
  minimally instead of changing langywrap templates.
- If a generated periodic task is malformed, fix the project `.langywrap/ralph.py`
  template and add/adjust langywrap injector-linter tests.
