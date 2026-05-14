---
date: "2026-05-12"
tags: [inspect-projects, tmux, ralph, process-detection]
problem: "Ralph loops launched through helper scripts were misclassified as shell-open, and finished failures were buried in raw pane captures"
solution: "Classify tmux status using pane output markers plus the pane process tree, and extract traceback/error excerpts into tmux/error.txt"
symptoms: "tmux captures showed [ralph] heartbeats and active subprocesses, while the status table reported shell-open; riemann2 had a traceback only visible inside pane_capture.txt"
affected-files: ["scripts/inspect-projects/inspect_projects.py"]
applies-to: "Any tmux-based monitor where a long-running loop is launched through just, bash, uv, or another wrapper"
time-to-discover: "One status inspection"
agent-note: "Do not infer idle shell from pane_current_command=bash if pane text has active Ralph markers or descendants include opencode/claude/langywrap. Check process tree and finished/input markers first."
project-origin: "langywrap"
---

# Tmux Helper Process Classification

## Context

`inspect_projects.py --status-only` reported several Ralph sessions as `shell-open`. The tmux pane captures showed they were actually active Ralph loops launched through helper commands, so tmux only reported the foreground pane command as `bash`.

## Problem

The old classifier treated any shell pane without literal `langywrap ralph` text as `shell-open`. That failed for helper-launched loops where the visible process is a shell but the pane output contains `[ralph]` heartbeats and descendant processes include `opencode`, `claude`, or other loop subprocesses.

It also allowed idle-shell detection to mask explicit finished/input markers such as `Ralph finished ... Press Ctrl-D`.

## Solution

Collect `#{pane_pid}` from tmux, inspect descendant processes with `ps`, and classify in this order:

1. No session: `not-running`.
2. Active Ralph-related descendant process: `running`.
3. Finished/input markers: `awaiting-input-or-finished`.
4. Ralph output without active descendants: `running-or-idle`.
5. Plain shell with no Ralph evidence: `shell-open`.

## Metrics

Before: helper-launched active loops were reported as `shell-open`.

After: `ktorobi`, `whitehacky`, `compricing`, and `bsdconj` classify as `running`; `riemann2` correctly classifies as `awaiting-input-or-finished+error` after a Ralph hard failure. The failure excerpt is written to `tmux/error.txt` and surfaced in `tmux/status.json`.

## Code Reference

`scripts/inspect-projects/inspect_projects.py`: `collect_tmux`, `collect_tmux_process_tree`, `classify_tmux`.
