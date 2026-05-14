---
date: "2026-05-12"
tags: [inspect-projects, ssh, remote, diagnostics]
problem: "Remote inspect-projects git commands failed from the remote home directory despite valid project Git repos"
solution: "Send a single shell-quoted remote command to ssh so bash -lc receives the intended command payload intact"
symptoms: "Remote projects reported git-error: fatal: not a git repository, while ssh ls showed .git in the configured project root"
affected-files: ["scripts/inspect-projects/inspect_projects.py"]
applies-to: "Any collector command using ssh host bash -lc with compound commands such as cd ... && git ..."
time-to-discover: "One inspection cycle"
agent-note: "If remote commands ignore cd or run from $HOME, check whether ssh argv is being re-parsed by the remote login shell. Pass one quoted remote command string."
project-origin: "langywrap"
---

# Remote SSH bash -lc Quoting

## Context

`inspect_projects.py` was diagnosing remote Ralph projects over SSH. Both `riemann2` and `bsdconj` reported `git-error` even though the configured directories existed and contained `.git`.

## Problem

The collector invoked SSH as separate argv elements: `ssh host bash -lc <command>`. OpenSSH sends the remote command through the remote login shell, which re-parses those arguments. For compound commands like `cd /path && git ...`, `bash -lc` received only `cd`, and `git` ran afterward from the remote home directory.

The misleading symptom was `fatal: not a git repository`, even though the project path was correct.

## Solution

Build one quoted remote command string with `shlex.join(["bash", "-lc", command])` and pass that as the remote command argument to SSH. This preserves the full `bash -lc` payload across the remote shell boundary.

## Metrics

Before: `riemann2` and `bsdconj` showed `git-error`.

After: both projects resolve commit IDs, dirty state, tmux state, and state file paths.

## Code Reference

`scripts/inspect-projects/inspect_projects.py`: `run_remote`.
