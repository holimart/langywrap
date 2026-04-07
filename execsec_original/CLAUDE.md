# execsec — Claude Code Interface Notes

## Check-only vs Execute mode

All interceptors default to **check-only** (validate, return 0/1, do not execute).
Add `--exec` as the FIRST argument to also execute the command on success.

This design makes all three tools composable validators: callers can use them as
pre-checks without causing double-execution.

| Call                                | Behavior                           |
|-------------------------------------|------------------------------------|
| `guard.sh -c "cmd"`                 | Check only — exit 0 or 1          |
| `guard.sh --exec -c "cmd"`          | Check + execute if allowed         |
| `intercept.py "cmd"`                | Check only — exit 0 or 1          |
| `intercept.py --exec "cmd"`         | Check + execute if allowed         |
| `intercept-enhanced.py "cmd"`       | Check only — exit 0 or 1          |
| `intercept-enhanced.py --exec "cmd"`| Check + execute if allowed         |
| `intercept-wrapper.sh -c "cmd"`     | Always check + execute (for $SHELL)|

### ASK rules in check-only mode

When `intercept.py` or `intercept-enhanced.py` is called in check-only mode and
a command matches an ASK rule, the prompt is **deferred** (logged as
`ALLOWED_ASK_DEFERRED`, exits 0). The `--exec` caller will prompt when it runs.

### Shell replacements vs validators

- `guard.sh` — check-only validator, used by execwrap as Layer 2 pre-check
- `guard-exec.sh` — shell replacement (`--exec` wrapper), installed by harden-wizard
  alongside `guard.sh`. Use as `SHELL=.llmsec/guard-exec.sh` for direct AI tool launch.
- `intercept-wrapper.sh` — always exec mode, fixes `secure-run.sh`'s `SHELL=` wiring.

## Key file locations

| File | Purpose |
|------|---------|
| `templates/shell-wrapper/guard.sh` | Uninstantiated template — has `__REAL_SHELL__` placeholder |
| `.llmsec/guard.sh` | Instantiated validator (created by harden-wizard) |
| `.llmsec/guard-exec.sh` | Shell replacement (created by harden-wizard) |
| `tools/interceptors/intercept.py` | Simple Python interceptor |
| `tools/interceptors/intercept-enhanced.py` | YAML-config interceptor (57+ rules) |
| `tools/interceptors/intercept-wrapper.sh` | $SHELL wrapper → intercept-enhanced.py --exec |
| `configs/defaults/permissions.yaml` | Default rule set for intercept-enhanced.py |

## Running tests

```bash
cd execsec && bash tests/test-orchestrator.sh
```

The test suite includes a "Check-Only Mode" section that verifies:
- Allowed commands exit 0 but produce no execution output in check-only mode
- Blocked commands exit 1 in all modes
- `--exec` flag enables execution and produces output
- `intercept-wrapper.sh` always executes (it is always in exec mode)

## Submodule usage (from parent repo)

```bash
# Initialize submodule
git submodule update --init execsec

# Run harden-wizard (installs .llmsec/guard.sh + guard-exec.sh)
/harden-wizard   # Claude Code skill

# Run execwrap-setup (Layer 1 rules + preload DEBUG trap)
/execwrap-setup  # Claude Code skill
```
