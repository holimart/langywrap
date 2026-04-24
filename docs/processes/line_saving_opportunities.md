---
date: "2026-04-18"
tags: [cleanup, refactor, dead-code]
status: "proposed"
context: "Follow-up to the StepRole/RouteConfig/RouteRule removal refactor (7-stage, -1250 LOC)"
---

# Line-saving opportunities — post-StepRole refactor

After the 7-stage refactor that deleted `StepRole` enum, `RouteConfig`,
`RouteRule`, and `router/config.py`, the following opportunities remain.
Ranked by confidence × size.

## High-confidence wins

### 1. Delete `ralph/module.py` — ~1400 lines

DSPy-style `Module` / `ModuleRunner` / `StepDef` DSL.

**Users:**
- `cli.py:450-482` — first-try fallback before Pipeline DSL
- `tests/test_ralph/test_module.py`
- Zero downstream `.langywrap/ralph.py` files use it. The only match in
  `compricing/.langywrap/ralph.py` is a commented-out import line.

**Actions:**
- Delete `lib/langywrap/ralph/module.py` (~992 lines)
- Delete `tests/test_ralph/test_module.py` (~400 lines)
- Remove `Module`, `ModuleRunner`, `StepDef`, `module_step`, `module_match`,
  `module_gate` exports from `lib/langywrap/ralph/__init__.py`
- Delete Module-first branch in `lib/langywrap/cli.py:450-482` (~33 lines)

**Total: ~1400+ lines**

### 2. Fix or delete `hyperagents/mutations.py` `_apply_mutation` — ~90-120 lines

`_apply_mutation` (lines 94-182) operates on `config.get("routes", {})` —
that shape ceased to exist when `RouteConfig` was deleted. The mutations
target `routes[role]["model"]`, `routes[role]["retry_models"]`,
`routes[role]["backend"]`, etc. These branches are all no-ops against
current configs.

`StepEvolver` in `router/evolution.py` now handles the same responsibility
against real `Step` objects.

**Options:**
- (a) Delete `_apply_mutation` + `mutate()` + `meta_mutate()` +
  `MutationType` enum; retarget `hyperagents/engine.py` to use
  `StepEvolver.mutate()` directly. ~90-120 lines removed.
- (b) Rewrite `_apply_mutation` to operate on `config["steps"]: list[dict]`
  (the YAML-serialized Step shape) — same line count, but keeps
  hyperagents semantically distinct.

**Recommended:** (a). One evolution mechanism is enough.

## Medium-confidence wins

### 3. Consolidate duplicated helpers — ~30 lines

`_resolve_model()` and `_infer_backend()` are duplicated across:
- `lib/langywrap/ralph/pipeline.py:31-76`
- `lib/langywrap/ralph/module.py:60-72` (goes away with #1)
- `lib/langywrap/ralph/config_v2.py:31-46`

Good home already exists: `lib/langywrap/ralph/aliases.py` (26 lines).
Extract the shared logic there, import in both places.

### 4. `config.py` vs `config_v2.py` — investigate only

Both parse `.langywrap/ralph.py` / YAML. Currently `load_ralph_config` in
`config.py` delegates to pipeline. Merge risk is high; do not touch
unless committing to re-running all ralph tests end-to-end.

Potential ~100-line win, deferred.

## Low-value cleanup

### 5. Stale docstrings — ~15 lines

Still reference deleted `RouteConfig` / `StepRole`:
- `lib/langywrap/router/router.py:7` — module docstring
- `lib/langywrap/router/__init__.py:7` — module docstring
- `lib/langywrap/hyperagents/mutations.py:52,220` — inline comments
- `tests/test_quick_wins.py:1-15` — header docstring

### 6. Dedupe CLI lazy imports — ~4 lines

`load_ralph_config` imported 6× from inside `cli.py` command bodies
(lines 334, 485, 519, 542, 610, 637). Hoist to module top — the import
has no side effects worth deferring now.

## Summary

| Priority | Win | Risk | Lines |
|---|---|---|---|
| High | Delete `ralph/module.py` | Low — no downstream users | ~1400 |
| High | Delete/fix `_apply_mutation` | Medium — touches hyperagents engine | ~100 |
| Medium | Consolidate `_resolve_model` / `_infer_backend` | Low | ~30 |
| Low | Stale docstrings | None | ~15 |
| Low | CLI lazy import dedupe | None | ~4 |
| Deferred | Merge config.py + config_v2.py | High | ~100 |

**Realistic total: ~1550 lines saved**, on top of the -1250 already banked
from the StepRole/RouteConfig removal.
