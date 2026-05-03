---
date: "2026-05-03"
tags: [ralph, dry-run, execwrap, openwolf, rtk]
problem: "Ralph dry-run reported stale project wiring and missing OpenWolf on a downstream project."
solution: "Refresh project execwrap from langywrap, install/wire OpenWolf, then treat remaining mock-probe timeout as an RTK probe interaction."
symptoms: "Dry-run showed openwolf not found, .wolf absent, rtk_wired=false, and EXECWRAP_PROJECT_DIR mismatch."
affected-files: ["scripts/couple.sh", "execwrap/execwrap.bash", "lib/langywrap/ralph"]
applies-to: "Downstream projects running `langywrap ralph run . --dry-run` through project-local execwrap."
time-to-discover: "~15 minutes"
agent-note: "If tool preflight is clean but mock backend probe still times out, check whether execwrap rewrote the probe command through RTK before treating it as broken project wiring."
project-origin: "compricing"
---

# Ralph Dry-Run Probe Wiring

## Context

While validating `compricing/.langywrap/ralph.py`, the Ralph dry-run initially found Kimi routing correctly but reported several environment issues.

## Problem

Initial `./ralph_loop.sh --dry-run` symptoms:

- `openwolf: not found`
- `.wolf directory is absent`
- `rtk_wired=false`
- `EXECWRAP_PROJECT_DIR is not the target project`

The project had a stale copied `.exec/execwrap.bash`. The current langywrap wrapper uses `PROJECT_DIR="${EXECWRAP_PROJECT_DIR:-...}"`, resolves RTK, and exports the project directory correctly. The stale downstream copy did not.

After refreshing wiring and installing OpenWolf, tool discovery became clean, but `mock_backend_probe` still timed out. The root cause was the nested `BASH_ENV` DEBUG trap: the env probe runs many tiny shell builtins (`printf`, `command -v`), and each one paid full execwrap security preflight cost. That exceeded the 10s dry-run timeout and left no output, causing false negatives for `EXECWRAP_PROJECT_DIR` and PATH checks.

The dry-run output also showed execwrap rewrote the RTK probe's harmless command:

```text
RTK rewrite: 'ls -l >/dev/null' -> 'rtk ls -l >/dev/null'
```

The env probe timed out after 10 seconds, leaving output empty. Because output was empty, langywrap inferred `EXECWRAP_PROJECT_DIR` and PATH checks as false even though tool discovery already showed the project-local wrapper and RTK were found.

## Solution

Run the downstream refresh first:

```bash
bash scripts/couple.sh /path/to/project --minimal
```

If OpenWolf is missing, build it and create the wrapper if needed:

```bash
cd /mnt/work4t/Projects/langywrap/openwolf
pnpm exec tsc && pnpm build:hooks && pnpm build:dashboard
```

Install wrapper:

```bash
#!/usr/bin/env bash
exec node "/mnt/work4t/Projects/langywrap/openwolf/dist/bin/openwolf.js" "$@"
```

Then wire project hooks:

```bash
langywrap integration openwolf wire . --init --langywrap-only
```

## Metrics

Before:

- OpenWolf absent.
- RTK not wired.
- Mock probe failed with multiple issues.

After:

- OpenWolf binary discovered.
- `.wolf` initialized.
- Claude and OpenCode OpenWolf hooks wired.
- RTK discovered as project-local `.exec/rtk` and `rtk_wired=true`.
- Remaining dry-run issue isolated to mock-probe timeout after RTK rewrite.

## Follow-Up

Ralph dry-run now sets `__EXECWRAP_ACTIVE=1` for the mock backend env probe. This keeps execwrap launcher-mode validation active while skipping the nested DEBUG trap for each builtin. The RTK probe remains separate and still validates internal RTK rewriting.

Potential fixes:

- Keep `__EXECWRAP_ACTIVE=1` on the env probe.
- Preserve partial output on timeout for future probe diagnostics.
- Keep RTK validation as a separate shell-mode probe.

## Code Reference

- `execwrap/execwrap.bash`: current project-dir and RTK wiring behavior.
- `scripts/couple.sh`: downstream project refresh path.
- `lib/langywrap/ralph/runner.py`: dry-run mock backend probe logic.
