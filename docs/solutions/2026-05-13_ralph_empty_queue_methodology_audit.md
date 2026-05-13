---
date: "2026-05-13"
tags: [ralph, methodology, empty-queue, scan-feedback, tooling]
problem: "A Ralph loop can stop at `Pending: (none)` even though recent scans, refutations, skipped tiers, and backlog entries still imply useful work."
solution: "Before accepting an empty queue, audit recent scan/deepllm/repro cycles for missed detector, suppression, tier-support, coverage-audit, findings-ledger, and backlog-refill tasks."
symptoms: "`langywrap ralph run --resume` exits with `no pending tasks`, while progress shows skipped tiers, no-signal scans, refutations, or viable backlog entries."
affected-files: ["ralph/tasks.md", "ralph/progress.md", "ralph/findings.md", "ralph/prompts/step4_finalize.md", "ralph/prompts/step3_execute_scan.md", "ralph/prompts/step3_execute_deepllm.md"]
applies-to: "Downstream Ralph loops that combine cheap scans, deep LLM audit, repro, and detector/tooling feedback."
time-to-discover: "~45 minutes"
agent-note: "Do not equate task exhaustion with methodology exhaustion. Empty queue is a trigger for a feedback-loop audit, not automatically success."
project-origin: "whitehacky"
---

# Ralph Empty Queue Methodology Audit

## Context

`whitehacky` resumed cleanly but immediately exited because `ralph/tasks.md` had
`Pending: (none)`. A closer review showed the queue was empty only because the
latest case tasks had been completed. The loop still had viable backlog entries
and several methodology gaps from recent cycles.

## Problem

The loop had correctly completed recent case work, but the final state hid useful
next work:

- Some cheap scans produced no signal or narrow zero-hit results.
- Some tier-3 scanners were skipped because of missing Hardhat/Foundry/Slither,
  unsupported languages, missing parser dependencies, or no source materialization.
- Refuted deepllm hypotheses had not always been converted into suppressions or
  downrank rules.
- `needs-poc` and informational repro outcomes did not always trigger a separate
  detector/scorer decision.
- `ralph/findings.md` had too little structured scan history to support future
  automatic queue decisions.
- The prompts were ambiguous: execute prompts told agents to append tasks, while
  finalize said it was the sole task writer.

## Principle

An empty queue is only valid after three audits pass:

- **Backlog audit:** no viable program remains to promote into `caseinit`, or
  discovery is queued because backlog is stale.
- **Coverage audit:** recent scans have no skipped tier, unsupported language,
  missing source, narrow-detector zero-hit, or weak-signal gap without a queued
  deepllm/tooling task.
- **Learning audit:** every recent scan/deepllm/repro cycle has a documented
  learning decision: new detector, new suppression, new language/tier support,
  new repro, deeper audit queued, or explicit `no reusable lesson because ...`.

## Policy Rules

- No-signal cheap scan is not success by itself. It means either the target is
  clean or the scanner is blind; queue deeper review or a coverage audit when the
  evidence is insufficient.
- Every scan/deepllm/repro should produce a learning decision, even when the case
  task is complete.
- Refutations are valuable. If a cheap-tool hit led to a refuted hypothesis,
  queue a suppression/downrank task unless the false positive is demonstrably too
  case-specific to generalize.
- Confirmed bugs should queue both a repro and a non-LLM detector/scorer task for
  the bug class.
- `needs-poc` should queue repro and separately decide whether the cheap-scan
  signal needs sharpening.
- Skipped tiers are actionable. Missing Hardhat, Foundry, Slither, Nano,
  tree-sitter, source files, or unsupported language support should usually queue
  tooling.
- A large-corpus zero-hit result from one narrow detector should queue a negative
  coverage audit unless broader tiers already reviewed the corpus.
- `ralph/findings.md` should be a structured scan ledger, not only a few latest
  notes.
- Finalize should be the sole writer to `ralph/tasks.md`; execute stages should
  report follow-up candidates with evidence.
- If `## Pending` would become `(none)`, finalize should refill from recent
  methodology gaps, then viable backlog `caseinit`, then discovery.

## Example Recovered Tasks

From the `whitehacky` audit, the strict policy recovered tasks such as:

- Empty-queue refill policy hardening.
- Findings-ledger enrichment.
- Python symlink cleanup/delete detector from SecureDrop `rm.secure_delete()`.
- Python archive/temp/GPG vector expansion from Freedom of Press scan hotspots.
- Solidity Foundry/no-Hardhat Slither or fallback support after skipped tier-3.
- Rust negative coverage audit after a single narrow detector returned zero hits
  over a large Tor corpus.
- A concrete next `caseinit` from backlog so audit work continues.

## Prompt Fix Pattern

Update downstream prompts so:

- `step4_finalize.md` owns task creation and contains the policy above.
- `step3_execute_scan.md` reports deepllm/tooling candidates but does not edit
  `tasks.md` directly.
- `step3_execute_deepllm.md` reports repro/tooling candidates but does not edit
  `tasks.md` directly.

Then validate with:

```bash
uv run python -m langywrap.ralph.lint_tasks check ralph/tasks.md --task-types caseinit,scan,deepllm,repro,tooling,discovery --max-active 2
langywrap ralph run --dry-run --no-tmux .
```

## Reusable Checklist

When a Ralph loop reports no pending tasks:

- Inspect `ralph/progress.md` for the last 20 cycles.
- Inspect `ralph/tasks.md` staged/uncommitted changes before assuming HEAD is
  current.
- Search for `skipped`, `blocked`, `weak`, `ambiguous`, `refuted`, `needs-poc`,
  `no deepllm follow-up`, and `no new follow-ups`.
- Compare scan outcomes to `docs/registry/attack_vectors.yaml` and
  `docs/registry/languages.yaml`.
- Check `ralph/findings.md` for missing rows or missing skipped-tier reasons.
- Refill tasks before resuming if backlog or methodology gaps remain.
