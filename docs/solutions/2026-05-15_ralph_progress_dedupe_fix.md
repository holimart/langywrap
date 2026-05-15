# Ralph `progress.md` dual-writer dedup (merge-in-place)

Date: 2026-05-15
Trigger: riemann2 audit found `## Cycle N` blocks duplicated across the
file (337 headers / 161 unique cycles); cross-repo check showed the bug
in every ralph-coupled repo, with `ktorobi` worst at 719/351.

## Symptom

`research/<state>/progress.md` accumulates two (or more) `## Cycle N`
blocks for the same cycle number. Per-repo damage at audit time:

| repo | headers / unique | TASK_TYPE conflicts |
|---|---|---|
| ktorobi | 719 / 351 | 206 |
| riemann2 | 337 / 161 | several |
| BSDconj | 237 / 116 | 0 (no TASK_TYPE) |
| whitehacky | 388 / 355 | 0 |
| sportsmarket | 10 / 5 | 5 |
| crunchdaoobesity | 7 / 4 | 0 |
| compricing | 2 / 1 | 1 |

## Root cause — two writers, no coordination

1. **LLM finalize prepends** a rich narrative block (`TASK_TYPE`, Task,
   Outcome, Rigor, Files, New tasks, Next) at the top of the file.
   Per-repo prompt: e.g. `riemann2/research/ralph/prompts/step4_finalize.md`.

2. **`RalphState.append_progress` appends** a skeletal block (`Outcome`,
   Confirmation Chain, Quality gate, Git commit, Duration) at the
   bottom. Called from `runner.py` after every cycle.

   The previous implementation always opened progress.md in append mode
   (`fh.open("a")`) with no awareness of the LLM-written narrative.

3. The audit gate `langywrap.ralph.validate_progress` deduped by
   `max(blocks, key=lambda b: b.n)` and kept the richest `TASK_TYPE`,
   which masked the duplication from coverage-budget rollups but left
   both raw entries in the file.

Some repos additionally have an execute-stage prompt that also writes
to progress.md, producing **three** blocks per cycle with
contradictory `TASK_TYPE` values.

## Fix — merge-in-place

`lib/langywrap/ralph/progress_dedupe.py` now provides:

* `merge_or_append(progress_text, cycle_num, lines)` — used at runtime
  by `RalphState.append_progress`. If a `## Cycle <cycle_num>` block
  already exists from the LLM finalize step, the skeletal metric lines
  are injected into that block (deduped by metric prefix). Lines are
  inserted just before any trailing `---` separator so block ordering
  stays clean. If no narrative exists, a fresh block is appended.

* `dedupe_progress(progress_text) -> (text, report)` — one-shot
  historical cleanup: for each cycle with multiple blocks, keep the
  first block that has a `TASK_TYPE` line (the freshest narrative,
  since legacy finalize prepends) and merge unique metric lines from
  its siblings.

Both entrypoints pick the **first** cycle block in file order as
canonical, on the rationale that the finalize step prepends — so the
freshest write ends up at the top, and that's what
`validate_progress` already reads.

## Cleanup tool

```bash
# Dry run (writes `<path>.deduped` for review):
uv run python scripts/dedupe-progress/dedupe_progress.py path/to/progress.md

# Apply in place (keeps `<path>.bak` next to the original):
uv run python scripts/dedupe-progress/dedupe_progress.py --apply \
    /mnt/work4t/Projects/{compricing/research,sportsmarket/research,BSDconj/research/ralph,whitehacky/ralph,ktorobi/ralph,riemann2/research/ralph}/progress.md \
    /mnt/work4t/Projects/crunchdaoobesity/competitions/obesity/research/progress.md
```

After fix, every audited repo went to `headers == unique_cycles`.

## Why merge instead of either-or

The runner's skeletal block carries data the LLM doesn't produce
(`Duration`, Confirmation Chain, Quality gate, Git commit). The LLM's
narrative carries data the runner doesn't have (Rigor, Files, New
tasks, Next steps). Both are useful. Merging into the LLM block
preserves narrative for humans + machine metrics for budgets and
post-mortem, without two writers stepping on each other.

## Crosswalk

- `lib/langywrap/ralph/state.py:append_progress` — runtime caller.
- `lib/langywrap/ralph/progress_dedupe.py` — merge + dedup library.
- `lib/langywrap/ralph/validate_progress.py` — postflight audit gate
  (unchanged; benefits automatically because there's now one block per
  cycle).
- `scripts/dedupe-progress/dedupe_progress.py` — historical cleanup
  CLI.
- `tests/test_ralph/test_progress_dedupe.py` — coverage for both the
  runtime merge and the one-shot dedup, including idempotency.
