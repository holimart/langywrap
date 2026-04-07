# Known Issues and TODOs — langywrap

## Resolved (2026-04-06)

- ~~Security patterns incomplete~~ — data_theft_prevention loaded and converted to deny rules in permissions.py. mkfs prefix matching works (mkfs.ext4 matches mkfs). Curl-to-pastebin patterns fire via data_theft_prevention→deny conversion.
- ~~Pydantic deprecation warnings~~ — All models already use model_config = ConfigDict(...). No class Config: found.
- ~~CLI stubs~~ — All CLI commands wired to library functions (install, couple, scaffold, compound, ralph, harden, router).
- ~~RTK not integrated~~ — RTK wired into execwrap (auto-rewrite via `rtk rewrite`) and Claude Code (PreToolUse hook). Pipes, compounds, heredocs handled correctly.
- ~~ExecWrap copies are static snapshots~~ — couple.sh now symlinks execwrap.bash and preload.sh; copies settings.json only if absent.
- ~~Couple script re-couple detection~~ — Detects existing .langywrap/ and prompts update vs cancel.
- ~~HyperAgent meta_mutate swallows errors~~ — Now logs warning before fallback.
- ~~DirectAPIBackend missing ImportError~~ — anthropic/openai imports now raise helpful ImportError messages.
- ~~Ralph stub mode silent~~ — Logs warning when router is None.
- ~~safe_git_commit assumes git~~ — Checks for .git directory before proceeding.
- ~~No tests for compound, helpers, CLI~~ — Added test_compound, test_helpers, test_cli suites.
- ~~Skills reference old execsec/ paths~~ — Updated harden-wizard.md and execwrap-setup.md to use lib/langywrap/security/ paths.
- ~~Layer 3 comment paths stale~~ — Updated execwrap.bash comments to reference lib/langywrap/security/.
- ~~Rewrite chains should stack~~ — Fixed via RTK integration in execwrap (python → uv run python → rtk-wrapped).

## Priority 2 — Before first coupling

### Install script not yet tested end-to-end
- RTK build works (verified 2026-04-06)
- Still needs: dry-run test for full install script, handle missing jq gracefully

### Couple script
- `couple_dev_dep` uses `uv add --dev "langywrap @ file://..."` — may not work with all uv versions

## Priority 3 — Nice to have

### Router
- `OpenRouterBackend` needs httpx dependency (optional, not in default deps) — handled at runtime with ImportError
- Cost estimation in `_COST_PER_1K_TOKENS` is rough — should be configurable

### Ralph loop
- No integration test for full ralph cycle with MockBackend

### HyperAgents
- `compute_novelty()` uses a simple key-diff distance — could use embedding-based distance
- Archive pruning doesn't preserve lineage (might delete ancestors of good variants)

### Tests
- Lean helpers are untested (need a Lean project fixture)
- No integration test for full ralph cycle with MockBackend

## Inherited from llmtemplate (notes/todos.txt)

1. `interceptor.config_dirs` field in settings.json is decorative — execwrap never passes it
2. Cline (`.clinerules/`) missing from execwrap-setup skill's Phase 0 checks

## Architecture debt

- `execsec_original/` is a 100% copy kept for reference — remove once all useful code is confirmed extracted
