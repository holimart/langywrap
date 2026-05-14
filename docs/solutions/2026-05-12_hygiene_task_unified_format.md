---
date: "2026-05-12"
tags: [ralph, tasks-md, lint, hygiene]
problem: "Task injectors emitted legacy checkbox lines that could fail unified tasks.md preflight lint"
solution: "Emit injected tasks in unified format and test injector output with the same linter used by Ralph preflight"
symptoms: "Ralph stopped during inline_orient with `unified_format` hard-fail on `Technical hygiene — cycle N`"
affected-files: ["lib/langywrap/ralph/state.py", "lib/langywrap/ralph/markdown_todo.py", "tests/test_ralph/test_state_extended.py", "tests/test_ralph/test_markdown_todo.py"]
applies-to: "Any Ralph project with preflight_lint=True and scheduled hygiene task injection"
time-to-discover: "One traceback inspection"
agent-note: "When Ralph fails on an auto-injected hygiene task, inspect the injector template before blaming the downstream tasks.md author."
project-origin: "riemann2"
---

# Hygiene Task Unified Format

## Context

`riemann2` stopped at cycle 1530 during `inline_orient` preflight lint. The failing line was auto-injected by langywrap's scheduled hygiene hook, not manually authored in the downstream project.

## Problem

The default hygiene injector produced:

```text
- [ ] **[P2] Technical hygiene — cycle 1530** <!-- hygiene-cycle-1530 -->
```

Projects using unified `tasks.md` lint require:

```text
- [ ] **[Pn] task:slug** [task_type] label
```

Older hygiene tasks in `riemann2` already used the valid form, so cycle 1530 exposed that the fallback injector template had not been migrated.

## Solution

Change injected task renderers to produce unified task lines. The default hygiene task now renders as:

```text
- [ ] **[P2] task:hygiene-cycle-1530** [hygiene] Technical hygiene — cycle 1530 <!-- hygiene-cycle-1530 -->
```

This preserves the duplicate-injection marker and satisfies unified lint.

Auto-pins now render as unified task lines too:

```text
- [ ] **[P2] task:auto-pin-p1-cycle-42** [py_plugin] do thing (auto-pin cycle 42, policy: P1)
```

Tests should validate every built-in task injector by running the generated `tasks.md` text through `langywrap.ralph.lint_tasks.lint`, not only by checking for marker substrings.

## Metrics

Before: `inline_orient` hard-failed before the cycle could run.

After: injected hygiene, periodic, and auto-pin task lines pass `lint_tasks` in focused tests.

## Code Reference

`lib/langywrap/ralph/state.py`: `RalphState.inject_hygiene_task`, `RalphState.inject_periodic_task`.

`lib/langywrap/ralph/markdown_todo.py`: `AutoPin.render`.
