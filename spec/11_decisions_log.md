# Decision Log — langywrap

Decisions made during initial design session (2026-04-06).

## D01: RTK — Git submodule, build from source
- **Why**: User wants to build from source to reduce supply-chain attack surface
- **How**: `git submodule add rtk-ai/rtk`, cargo build during `./install.sh`
- **Binary goes to**: `~/.local/bin/rtk` + `execwrap/rtk`

## D02: execsec — Full copy, not submodule
- **Why**: User said "forget execsec exists." We want full ownership.
- **What changed**: Refactored into `lib/langywrap/security/` (Python) + `hooks/` (shell)
- **Key fix**: `merge_permissions()` now merges ALL config levels. Deny at any level wins. System denials are NEVER overridable by project config. Original execsec had first-found-wins bug.
- **Original preserved**: `execsec_original/` directory for reference

## D03: Ralph loop — Hybrid Python/bash
- **Why**: 675+ cycles proven in bash (riemann2), but Python is testable and pip-installable
- **How**: Python orchestrator (`lib/langywrap/ralph/`) for state/retry/routing. Shell wrapping stays bash (`execwrap/`).
- **Source repos**: riemann2 (most mature, 5-step, lean retry), crunchdaoobesity (212 cycles, 4-step, orient compression), llmtemplate (generic)

## D04: Downstream coupling via install scripts
- **How**: `./scripts/couple.sh /path/to/project` — interactive wizard
- **Modes**: `--full` (default), `--minimal` (security only), `--security-only`, `--dry-run`
- **Creates**: `.langywrap/{config,router,ralph}.yaml` in the target project
- **Left for later**: Actual coupling of riemann2/compricing/crunchdaoobesity (do separately)

## D05: HyperAgents — Fully working, not scaffold
- **Why**: User wants every coupled repo to participate by simply running ralph loops
- **How**: `experiments/archive/` stores variants, `HyperAgentEngine` alternates exploit/explore, ralph loop feeds metrics back via `record_evaluation()`
- **Paper**: arxiv.org/abs/2603.19461 (DGM-H: meta-agent rewrites itself)

## D06: Compound engineering — CLI push + auto via ralph finalize
- **How**: `langywrap compound push "lesson.md"` + automatic in ralph finalize step
- **Hub**: `langywrap/docs/solutions/` is the cross-project hub
- **Paper source**: Every Inc compound engineering methodology

## D07: Global config — Symlinks by default, user chooses during install
- **How**: `./install.sh` asks "symlinks or copy?" Default: symlinks
- **What gets linked**: `~/.claude/hooks/ -> langywrap/hooks/claude/`, `~/.claude/commands/ -> langywrap/skills/`
- **settings.json**: Additive merge via jq (never removes user entries)
- **Rerunnable**: Previous choices saved in `~/.langywrap/install_state.env`

## D08: Skill evolution — Full autonomy design, git versioning
- **Why**: User said "design for full autonomy now, humans intervene anytime, all versions in git"
- **How**: SkillLibrary with utility scores, reflect_and_write loop after each task. All skill files are git-tracked.
- **Paper**: Memento-Skills (arxiv.org/abs/2603.18743)

## D09: Permissions merge — System deny always wins (C)
- **Fix**: `merge_permissions()` collects deny/ask/allow from ALL levels. A pattern in `deny` at ANY level blocks it from appearing in `allow` at any level.
- **Config hierarchy**: bundled defaults -> project `.langywrap/` -> system `~/.langywrap/`

## D10: Lean + all helpers — Include everything, categorize
- **Why**: User wants "tons of helpers that coupled repos would be happy to use"
- **Organization**: `lib/langywrap/helpers/{python,bash,lean,data}/`
- **Quality module**: `lib/langywrap/quality/{gates.py, lean.py}`
- **Extensible**: HyperAgents and Memento skills generate new helpers over time

## D11: ExecutionRouter (not ModelRouter)
- **Name**: ExecutionRouter — routes models, backends, retries, branching
- **Why not ModelRouter**: Routes more than models — decides opencode vs claude, handles retry chains, peak-hour throttle, budget tracking
- **Evolvable**: HyperAgents mutate the routing table (`RouteEvolver` + `RouteConfigVariant`)
- **Per-repo configs**: `.langywrap/router.yaml` in each coupled repo
- **Best + explorative**: Archive keeps best config AND mutated variants for exploration

## D12: MockBackend for testing
- **Why**: User wanted to verify that security and token-sparing layers fire through the router
- **How**: Bash-based mock that runs through same subprocess pipeline. `run_with_security_check()` explicitly checks SecurityEngine.
- **58 tests passing** including security enforcement + token estimation
