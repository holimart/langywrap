"""
langywrap.ralph.config_v2 — Clean, grouped YAML config format for ralph loops.

V2 format groups related concerns into readable sections:
    models, flow, gates, adversarial, throttle, git, secrets, scope, cycle_types

The parser reads v2 YAML and produces the same RalphConfig + RouteConfig
objects used by the runner and ExecutionRouter — zero runtime changes needed.

Detection: a YAML file with a ``flow:`` key is treated as v2.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from langywrap.ralph.config import (
    QualityGateConfig,
    RalphConfig,
    StepConfig,
    StepRole,
)

# Router types — optional import (ralph is usable without router)
try:
    from langywrap.router.config import (
        Backend,
        RouteConfig,
        RouteRule,
    )
    from langywrap.router.config import (
        StepRole as RouterStepRole,
    )
except ImportError:
    RouteConfig = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Model alias resolution
# ---------------------------------------------------------------------------

from langywrap.ralph.aliases import BUILTIN_ALIASES as _MODEL_ALIASES


def _resolve_model(name: str, extra: dict[str, str] | None = None) -> str:
    """Expand short aliases to full model IDs.

    ``extra`` is merged on top of builtins, so project aliases take precedence.
    """
    if extra:
        return {**_MODEL_ALIASES, **extra}.get(name, name)
    return _MODEL_ALIASES.get(name, name)


def _infer_backend(model: str) -> str:
    """Infer backend from model prefix: nvidia/* | openai/* | mistral/* → opencode."""
    for prefix in ("nvidia/", "moonshotai/", "openai/", "mistral/", "google/"):
        if model.startswith(prefix):
            return "opencode"
    return "claude"


_ROLE_ALIASES: dict[str, StepRole] = {
    "validate": StepRole.CRITIC,
    "adversarial": StepRole.CRITIC,
    "review": StepRole.REVIEW,
}


def _infer_role(name: str) -> StepRole:
    """Infer StepRole from step name."""
    name_lower = name.lower()
    # Check aliases first
    if name_lower in _ROLE_ALIASES:
        return _ROLE_ALIASES[name_lower]
    for role in StepRole:
        if role.value in name_lower:
            return role
    return StepRole.GENERIC


# ---------------------------------------------------------------------------
# Flow entry parsing
# ---------------------------------------------------------------------------

_WHEN_RE = re.compile(r"^(\w+)\s*=~\s*/(.+)/$")


def _parse_when(when_str: str) -> tuple[str, str]:
    """Parse 'step =~ /pattern/' into (step_name, regex_pattern)."""
    m = _WHEN_RE.match(when_str.strip())
    if m:
        return m.group(1), m.group(2)
    raise ValueError(f"Invalid when expression: {when_str!r}. Expected: 'step =~ /pattern/'")


def _parse_flow_entry(
    entry: str | dict,
    models: dict[str, str],
    prompts_dir: Path,
    default_tools: str,
) -> list[StepConfig]:
    """Parse a single flow entry into one or more StepConfig objects.

    Flow entries can be:
      - "orient"                        → simple step, infer everything
      - "orient": {fail_fast: true}     → step with options
      - "execute.retry": {...}          → retry config (attached to execute step — returned empty,
                                          retry info stored separately)
    """
    if isinstance(entry, str):
        # Simple: just a step name
        name = entry
        opts: dict[str, Any] = {}
    elif isinstance(entry, dict):
        if len(entry) != 1:
            raise ValueError(
                f"Flow entry dict must have exactly one key, got: {list(entry.keys())}"
            )
        name = next(iter(entry))
        opts = entry[name] or {}
    else:
        raise TypeError(f"Flow entry must be str or dict, got {type(entry)}")

    # Skip retry entries — handled by caller
    if ".retry" in name:
        return []

    # Resolve model
    model_id = _resolve_model(opts.get("model", models.get(name, "")))
    role = _infer_role(name)

    # Parse timeout: accept "120m" or int
    timeout_raw = opts.get("timeout", 30)
    if isinstance(timeout_raw, str) and timeout_raw.endswith("m"):
        timeout = int(timeout_raw[:-1])
    else:
        timeout = int(timeout_raw)

    # Parse tools
    tools = opts.get("tools", default_tools)
    if isinstance(tools, list):
        tools = ",".join(tools)

    # Parse when condition (string → run_if_step/pattern, list → run_if_cycle_types)
    run_if_step = ""
    run_if_pattern = ""
    run_if_cycle_types: list[str] = []
    when = opts.get("when", opts.get("when_cycle", ""))
    if when:
        if isinstance(when, list):
            # when: [lean, mixed] → cycle type gate
            run_if_cycle_types = [str(w) for w in when]
        elif isinstance(when, str):
            # when: 'execute =~ /pattern/' → output pattern gate
            run_if_step, run_if_pattern = _parse_when(when)

    # Parse output_as (allows step variants to share an output slot)
    output_as = opts.get("output_as", "")

    # Parse prompt_extra (cycle-type-specific injection)
    prompt_extra = opts.get("inject", opts.get("prompt_extra", ""))

    # Parse engine
    engine = opts.get("engine", "auto")

    # Template: name-based convention
    template_name = opts.get("template", "")
    if not template_name:
        # Convention: look for step_name.md or stepN_name.md
        template_name = f"{name}.md"

    template_path = prompts_dir / template_name
    # If convention doesn't exist, try with step prefix
    if not template_path.exists():
        # Try numbered patterns
        for candidate in prompts_dir.glob(f"*_{name}*.md"):
            template_path = candidate
            break

    return [StepConfig(
        name=name,
        prompt_template=template_path,
        role=role,
        timeout_minutes=timeout,
        confirmation_token=opts.get("token", ""),
        depends_on=opts.get("depends_on", []),
        model=model_id,
        tools=tools,
        engine=engine,
        run_if_step=run_if_step,
        run_if_pattern=run_if_pattern,
        run_if_cycle_types=run_if_cycle_types,
        output_as=output_as,
        prompt_extra=prompt_extra,
        fail_fast=opts.get("fail_fast", False),
        pipeline=opts.get("pipeline", True),
        every_n=opts.get("every", 0),
    )]


def _parse_retry(
    retry_dict: dict[str, Any],
    step_name: str,
    models: dict[str, str],
    prompts_dir: Path,
) -> dict[str, Any]:
    """Parse a retry block into StepConfig update fields."""
    updates: dict[str, Any] = {}
    updates["retry_count"] = retry_dict.get("max", 0)
    updates["retry_gate_command"] = retry_dict.get("gate", "")

    retry_model = retry_dict.get("model", "")
    if retry_model:
        updates["retry_model"] = _resolve_model(retry_model)

    template = retry_dict.get("template", "")
    if template:
        updates["retry_prompt_template"] = prompts_dir / template

    when_types = retry_dict.get("when", [])
    if isinstance(when_types, list):
        updates["retry_if_cycle_types"] = when_types

    return updates


# ---------------------------------------------------------------------------
# Gate parsing
# ---------------------------------------------------------------------------

def _parse_gates(raw: Any) -> tuple[QualityGateConfig | None, list[QualityGateConfig]]:
    """Parse gates section into primary + additional quality gates.

    Accepts:
      - string: "./just check"
      - list of strings/dicts
    """
    if raw is None:
        return None, []

    if isinstance(raw, str):
        return QualityGateConfig(command=raw), []

    if isinstance(raw, list):
        gates: list[QualityGateConfig] = []
        for item in raw:
            if isinstance(item, str):
                gates.append(QualityGateConfig(command=item))
            elif isinstance(item, dict):
                # Handle "lake build: {timeout: 15m}" or {"command": "...", ...}
                if "command" in item:
                    timeout = item.get("timeout", item.get("timeout_minutes", 10))
                    if isinstance(timeout, str) and timeout.endswith("m"):
                        timeout = int(timeout[:-1])
                    gates.append(QualityGateConfig(
                        command=item["command"],
                        timeout_minutes=int(timeout),
                        required=item.get("required", True),
                    ))
                else:
                    # Single-key dict: "lake build": {timeout: 15m}
                    cmd = next(iter(item))
                    opts = item[cmd] or {}
                    timeout = opts.get("timeout", opts.get("timeout_minutes", 10))
                    if isinstance(timeout, str) and timeout.endswith("m"):
                        timeout = int(timeout[:-1])
                    gates.append(QualityGateConfig(
                        command=cmd,
                        timeout_minutes=int(timeout),
                        required=opts.get("required", True),
                    ))

        primary = gates[0] if gates else None
        additional = gates[1:] if len(gates) > 1 else []
        return primary, additional

    return None, []


# ---------------------------------------------------------------------------
# Adversarial parsing
# ---------------------------------------------------------------------------

def _parse_adversarial(raw: dict[str, Any] | None) -> tuple[int | None, str, list[str], bool]:
    """Parse adversarial section.

    Returns (every_n, step_name, milestone_patterns, finalize_after).
    """
    if not raw:
        return None, "", [], False

    every = raw.get("every")

    milestone = raw.get("milestone", "")
    patterns: list[str] = []
    if milestone:
        if isinstance(milestone, str):
            # Parse "execute =~ /pattern/"
            _, pattern = _parse_when(milestone)
            patterns.append(pattern)
        elif isinstance(milestone, list):
            patterns = milestone

    return (
        every,
        raw.get("step", "adversarial"),
        patterns,
        raw.get("finalize_after", True),
    )


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

def is_v2_config(raw: dict) -> bool:
    """Return True if this YAML dict uses v2 format (has 'flow' key)."""
    return "flow" in raw


def load_v2(raw: dict, project_dir: Path) -> RalphConfig:
    """Parse v2 YAML dict into a RalphConfig (with all v1 fields populated).

    This is the bridge: v2 YAML → v1 internal objects.
    """
    # -- Paths ---------------------------------------------------------------
    state_dir_str = raw.get("state", raw.get("state_dir", "ralph"))
    state_dir = Path(state_dir_str)

    prompts_dir_str = raw.get("prompts", raw.get("prompts_dir", ""))
    if prompts_dir_str:
        prompts_dir = project_dir / prompts_dir_str
    else:
        prompts_dir = project_dir / state_dir_str / "prompts"

    # -- Models --------------------------------------------------------------
    models: dict[str, str] = {}
    for name, model_ref in (raw.get("models") or {}).items():
        models[name] = _resolve_model(str(model_ref))

    # -- Default tools -------------------------------------------------------
    default_tools = raw.get("tools", "Read,Write,Edit,Glob,Grep,Bash")
    if isinstance(default_tools, list):
        default_tools = ",".join(default_tools)

    # -- Flow → StepConfig list ----------------------------------------------
    flow_entries = raw.get("flow", [])
    steps: list[StepConfig] = []
    retry_configs: dict[str, dict] = {}  # step_name → retry updates

    for entry in flow_entries:
        # Check for retry entries (e.g. "execute.retry" or "execute.lean.retry")
        if isinstance(entry, dict):
            key = next(iter(entry))
            if key.endswith(".retry"):
                step_name = key[: -len(".retry")]  # "execute.lean.retry" → "execute.lean"
                retry_configs[step_name] = _parse_retry(
                    entry[key], step_name, models, prompts_dir,
                )
                continue

        parsed = _parse_flow_entry(entry, models, prompts_dir, default_tools)
        steps.extend(parsed)

    # Apply retry configs to their parent steps
    for i, step in enumerate(steps):
        if step.name in retry_configs:
            steps[i] = step.model_copy(update=retry_configs[step.name])

    # -- Non-pipeline steps (adversarial) that have models but no flow entry
    # Only add if referenced as adversarial_step or has a known special role
    adv_raw = raw.get("adversarial", {})
    adv_step_name = adv_raw.get("step", "adversarial") if adv_raw else "adversarial"

    for name, model_id in models.items():
        if any(s.name == name for s in steps):
            continue
        # Only auto-add if it's the adversarial step (not arbitrary model entries like lean_retry)
        if name != adv_step_name:
            continue
        template = prompts_dir / f"{name}.md"
        if not template.exists():
            for candidate in prompts_dir.glob(f"*_{name}*.md"):
                template = candidate
                break
        if template.exists():
            steps.append(StepConfig(
                name=name,
                prompt_template=template,
                role=_infer_role(name),
                timeout_minutes=45,
                model=model_id,
                pipeline=False,
            ))

    # -- Gates ---------------------------------------------------------------
    primary_gate, extra_gates = _parse_gates(raw.get("gates", raw.get("gate")))

    # -- Adversarial ---------------------------------------------------------
    adv_every, adv_step, adv_patterns, _ = _parse_adversarial(raw.get("adversarial"))

    # -- Throttle ------------------------------------------------------------
    throttle = raw.get("throttle", {})
    throttle_start = None
    throttle_end = None
    if throttle:
        utc_range = throttle.get("utc", "")
        if isinstance(utc_range, str) and "-" in utc_range:
            parts = utc_range.split("-")
            throttle_start = int(parts[0])
            throttle_end = int(parts[1])

    # -- Git -----------------------------------------------------------------
    git_cfg = raw.get("git", {})
    if isinstance(git_cfg, dict):
        git_commit = git_cfg.get("commit", True)
        git_paths = git_cfg.get("paths", [])
    else:
        git_commit = True
        git_paths = []

    # -- Secrets -------------------------------------------------------------
    secrets_raw = raw.get("secrets", [])
    secret_patterns = secrets_raw if isinstance(secrets_raw, list) else [str(secrets_raw)]

    # -- Cycle types (detection only — model selection is on the step) ------
    cycle_type_rules: list[dict[str, str]] = []
    for name, ct_cfg in (raw.get("cycle_types") or {}).items():
        if isinstance(ct_cfg, dict):
            rule: dict[str, str] = {"name": name}
            if "match" in ct_cfg:
                rule["pattern"] = ct_cfg["match"]
            # execute_model is deprecated — use conditional steps instead
            if "execute_model" in ct_cfg:
                import warnings
                warnings.warn(
                    f"cycle_types.{name}.execute_model is deprecated. "
                    f"Define a conditional step with when: [{name}] instead.",
                    DeprecationWarning,
                    stacklevel=2,
                )
            cycle_type_rules.append(rule)

    # -- Periodic tasks (lookback, etc.) -------------------------------------
    periodic_tasks: list[dict[str, Any]] = []
    for pt in (raw.get("periodic") or []):
        if isinstance(pt, dict):
            periodic_tasks.append(pt)

    # -- Build RalphConfig ---------------------------------------------------
    return RalphConfig(
        project_dir=project_dir,
        state_dir=state_dir,
        prompts_dir=Path(prompts_dir_str) if prompts_dir_str else Path(""),
        steps=steps,
        quality_gate=primary_gate,
        quality_gates=extra_gates,
        budget=raw.get("budget", 10),
        review_every_n=raw.get(
            "review_every_n",
            raw.get("review", {}).get("every", 10) if isinstance(raw.get("review"), dict) else 10,
        ),
        adversarial_every_n=adv_every,
        adversarial_step=adv_step,
        adversarial_milestone_patterns=adv_patterns,
        hygiene_every_n=raw.get(
            "hygiene_every_n",
            raw.get("hygiene", {}).get("every", 5) if isinstance(raw.get("hygiene"), dict) else 5,
        ),
        git_commit_after_cycle=git_commit,
        git_add_paths=git_paths,
        scope_restriction=raw.get("scope", ""),
        secret_patterns=(
            secret_patterns
            if secret_patterns
            else RalphConfig.model_fields["secret_patterns"].default_factory()  # type: ignore[union-attr]
        ),
        verbose=raw.get("verbose", True),
        max_hang_retries=raw.get("max_hang_retries", 2),
        throttle_utc_start=throttle_start,
        throttle_utc_end=throttle_end,
        throttle_weekdays_only=throttle.get("weekdays_only", True) if throttle else True,
        cycle_type_rules=cycle_type_rules,
        periodic_tasks=periodic_tasks,
        tasks_file=Path(raw["tasks_file"]) if raw.get("tasks_file") else None,
        progress_file=Path(raw["progress_file"]) if raw.get("progress_file") else None,
    )


def build_route_config_from_v2(raw: dict, project_dir: Path) -> RouteConfig | None:
    """Build a RouteConfig from v2 YAML models section.

    Models can be specified as:
      - string: ``execute: kimi`` (short alias, auto-infer backend + fallback)
      - dict: ``execute: {model: kimi, retry: [sonnet, haiku], backend: opencode}``

    Returns None if router module is not available.
    """
    if RouteConfig is None:
        return None

    models = raw.get("models", {})
    if not models:
        return None

    rules: list[RouteRule] = []
    for name, model_spec in models.items():
        # Parse model spec: string or dict
        if isinstance(model_spec, str):
            model_id = _resolve_model(model_spec)
            retry_models_raw: list[str] = []
            backend_override = ""
        elif isinstance(model_spec, dict):
            model_id = _resolve_model(str(model_spec.get("model", "")))
            retry_models_raw = model_spec.get("retry", [])
            backend_override = model_spec.get("backend", "")
        else:
            continue

        backend_str = backend_override or _infer_backend(model_id)

        try:
            role = RouterStepRole(name)
        except ValueError:
            # Not a standard role — skip (e.g. "lean_retry")
            continue

        backend = Backend(backend_str)

        # Resolve retry models
        retry_models = [_resolve_model(m) for m in retry_models_raw]
        # Default fallback to sonnet if none specified and not already sonnet
        if not retry_models and model_id != _resolve_model("sonnet"):
            retry_models = [_resolve_model("sonnet")]

        rules.append(RouteRule(
            role=role,
            model=model_id,
            backend=backend,
            retry_models=retry_models,
            retry_max=2,
        ))

    return RouteConfig(
        name=raw.get("name", project_dir.name),
        description=f"Auto-generated from v2 config for {project_dir.name}",
        rules=rules,
        default_backend=Backend.CLAUDE,
    )
