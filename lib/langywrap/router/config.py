"""
langywrap.router.config — Routing configuration models and loader.

RouteConfig describes how each workflow step (orient, plan, execute, …)
maps to a model and backend.  Configs are stored in ``.langywrap/router.yaml``
inside the coupled repo and can be evolved by HyperAgents.

Default routing (crunchdaoobesity pattern):
  orient   → claude-haiku  (cheap, fast context digest)
  plan     → claude-sonnet (mid-tier, structured output)
  execute  → kimi-k2.5     (free via OpenRouter, long context)
  critic   → claude-haiku  (cheap soundness check)
  finalize → claude-haiku  (cheap summary)
  review   → claude-opus   (expensive, every N cycles)
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .backends import Backend

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ModelTier(str, Enum):
    """Cost/capability tier of a model."""

    CHEAP = "cheap"
    MID = "mid"
    EXPENSIVE = "expensive"


class StepRole(str, Enum):
    """
    Named role of a workflow step in a Ralph-pattern loop.

    orient      — digest current state, cheap context summary
    plan        — structured plan / task decomposition
    execute     — main implementation step (may use expensive models or free tier)
    critic      — soundness / quality review of execute output
    finalize    — write progress, update state files
    review      — deep review every N cycles (expensive)
    adversarial — red-team / challenge the plan
    lean_retry  — cheap retry for a Lean sorry-elimination loop
    validate    — run tests / type-check and report
    """

    ORIENT = "orient"
    PLAN = "plan"
    EXECUTE = "execute"
    CRITIC = "critic"
    FINALIZE = "finalize"
    REVIEW = "review"
    ADVERSARIAL = "adversarial"
    LEAN_RETRY = "lean_retry"
    VALIDATE = "validate"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RouteRule(BaseModel):
    """
    A single routing rule: maps a step role to a model/backend/timeout.

    Fields
    ------
    role:
        Which workflow step this rule applies to.
    model:
        Model identifier as expected by the backend (e.g. ``claude-haiku-4-5-20251001``).
    backend:
        Which backend to use for this rule.
    tier:
        Cost/capability tier (informational; used by evolver mutations).
    timeout_minutes:
        Per-step wall-clock timeout in minutes.
    retry_models:
        Fallback chain: if this model hangs or fails, try these in order.
        Example: ``["claude-haiku-4-5-20251001", "claude-opus-4-5"]``
    retry_max:
        Maximum number of retry attempts across the fallback chain.
    conditions:
        Optional dict of context conditions that must match for this rule
        to apply.  Example: ``{"cycle_type": "lean"}``.
        Keys/values are compared against the ``context`` dict passed to
        ``ExecutionRouter.route()``.
    """

    role: StepRole
    model: str
    backend: Backend
    tier: ModelTier = ModelTier.MID
    timeout_minutes: int = 30
    retry_models: list[str] = Field(default_factory=list)
    retry_max: int = 2
    conditions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timeout_minutes")
    @classmethod
    def timeout_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("timeout_minutes must be > 0")
        return v

    @property
    def timeout_seconds(self) -> int:
        return self.timeout_minutes * 60

    def matches_conditions(self, context: dict[str, Any]) -> bool:
        """Return True if all rule conditions match the provided context."""
        return all(context.get(key) == expected for key, expected in self.conditions.items())

    model_config = ConfigDict(extra="allow")


class RouteConfig(BaseModel):
    """
    Complete routing configuration for a coupled repo.

    Fields
    ------
    name:
        Human-readable name for this configuration (e.g. ``"crunchdaoobesity-v1"``).
    description:
        Free-text description.
    rules:
        List of RouteRule, evaluated in order.  First matching rule wins.
    review_every_n:
        How many cycles between deep-review steps.  Default 10.
    peak_hours:
        Optional UTC (start_hour, end_hour) during which calls are throttled.
        Example: ``(9, 17)`` = throttle 09:00–17:00 UTC.
    default_backend:
        Fallback backend when no rule matches.
    """

    name: str = "default"
    description: str = ""
    rules: list[RouteRule] = Field(default_factory=list)
    review_every_n: int = 10
    peak_hours: tuple[int, int] | None = None
    default_backend: Backend = Backend.CLAUDE

    @field_validator("review_every_n")
    @classmethod
    def review_n_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("review_every_n must be > 0")
        return v

    def get_rule(self, role: StepRole, context: dict[str, Any] | None = None) -> RouteRule | None:
        """
        Return the first rule matching ``role`` (and conditions if any).

        Rules with conditions are checked first; then unconditional rules.
        This ensures specialised rules (e.g. lean_retry for lean cycle type)
        take precedence over generic catch-alls.
        """
        ctx = context or {}
        # Pass 1: conditional rules
        for rule in self.rules:
            if rule.role == role and rule.conditions and rule.matches_conditions(ctx):
                return rule
        # Pass 2: unconditional rules
        for rule in self.rules:
            if rule.role == role and not rule.conditions:
                return rule
        return None

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Default routing config (crunchdaoobesity pattern)
# ---------------------------------------------------------------------------


DEFAULT_ROUTE_CONFIG = RouteConfig(
    name="langywrap-default",
    description=(
        "Default routing based on the crunchdaoobesity pattern. "
        "Cheap models for orientation and finalisation; free tier (kimi-k2.5) "
        "for heavy execute steps; expensive models for periodic deep review."
    ),
    review_every_n=10,
    default_backend=Backend.CLAUDE,
    rules=[
        RouteRule(
            role=StepRole.ORIENT,
            model="claude-haiku-4-5-20251001",
            backend=Backend.CLAUDE,
            tier=ModelTier.CHEAP,
            timeout_minutes=20,
            retry_models=["claude-haiku-4-5-20251001"],
            retry_max=2,
        ),
        RouteRule(
            role=StepRole.PLAN,
            model="claude-sonnet-4-5-20251001",
            backend=Backend.CLAUDE,
            tier=ModelTier.MID,
            timeout_minutes=20,
            retry_models=["claude-haiku-4-5-20251001"],
            retry_max=2,
        ),
        RouteRule(
            role=StepRole.EXECUTE,
            model="openrouter/moonshotai/kimi-k2.5",
            backend=Backend.OPENROUTER,
            tier=ModelTier.CHEAP,
            timeout_minutes=120,
            retry_models=[
                "openrouter/moonshotai/kimi-k2.5",
                "openrouter/mistralai/mistral-nemo",
            ],
            retry_max=3,
        ),
        RouteRule(
            role=StepRole.CRITIC,
            model="claude-haiku-4-5-20251001",
            backend=Backend.CLAUDE,
            tier=ModelTier.CHEAP,
            timeout_minutes=45,
            retry_models=["claude-haiku-4-5-20251001"],
            retry_max=2,
        ),
        RouteRule(
            role=StepRole.FINALIZE,
            model="claude-haiku-4-5-20251001",
            backend=Backend.CLAUDE,
            tier=ModelTier.CHEAP,
            timeout_minutes=30,
            retry_models=["claude-haiku-4-5-20251001"],
            retry_max=2,
        ),
        RouteRule(
            role=StepRole.REVIEW,
            model="claude-opus-4-5-20251001",
            backend=Backend.CLAUDE,
            tier=ModelTier.EXPENSIVE,
            timeout_minutes=60,
            retry_models=["claude-sonnet-4-5-20251001"],
            retry_max=1,
        ),
        RouteRule(
            role=StepRole.ADVERSARIAL,
            model="claude-sonnet-4-5-20251001",
            backend=Backend.CLAUDE,
            tier=ModelTier.MID,
            timeout_minutes=45,
            retry_models=["claude-haiku-4-5-20251001"],
            retry_max=2,
        ),
        RouteRule(
            role=StepRole.LEAN_RETRY,
            model="claude-haiku-4-5-20251001",
            backend=Backend.CLAUDE,
            tier=ModelTier.CHEAP,
            timeout_minutes=30,
            retry_models=["claude-haiku-4-5-20251001"],
            retry_max=3,
        ),
        RouteRule(
            role=StepRole.VALIDATE,
            model="claude-haiku-4-5-20251001",
            backend=Backend.CLAUDE,
            tier=ModelTier.CHEAP,
            timeout_minutes=20,
            retry_models=[],
            retry_max=1,
        ),
    ],
)


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------


def _parse_peak_hours(raw: Any) -> tuple[int, int] | None:
    """Parse peak_hours from YAML: list [start, end] or null."""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return (int(raw[0]), int(raw[1]))
    raise ValueError(f"peak_hours must be [start_hour, end_hour] or null, got: {raw!r}")


def _parse_rule(raw: dict[str, Any]) -> RouteRule:
    """Parse a single rule dict from YAML."""
    role_str = raw.get("role", "")
    try:
        role = StepRole(role_str)
    except ValueError as err:
        raise ValueError(
            f"Unknown step role: {role_str!r}. "
            f"Valid roles: {[r.value for r in StepRole]}"
        ) from err

    backend_str = raw.get("backend", "claude")
    try:
        backend = Backend(backend_str)
    except ValueError as err:
        raise ValueError(
            f"Unknown backend: {backend_str!r}. "
            f"Valid backends: {[b.value for b in Backend]}"
        ) from err

    tier_str = raw.get("tier", "mid")
    try:
        tier = ModelTier(tier_str)
    except ValueError:
        tier = ModelTier.MID

    return RouteRule(
        role=role,
        model=raw.get("model", ""),
        backend=backend,
        tier=tier,
        timeout_minutes=int(raw.get("timeout_minutes", 30)),
        retry_models=list(raw.get("retry_models") or []),
        retry_max=int(raw.get("retry_max", 2)),
        conditions=dict(raw.get("conditions") or {}),
    )


def load_route_config(project_dir: Path) -> RouteConfig:
    """
    Load routing config from ``<project_dir>/.langywrap/router.yaml``.

    Falls back to ``DEFAULT_ROUTE_CONFIG`` if the file does not exist.

    YAML schema example::

        name: myproject-v1
        description: Custom routing for myproject
        review_every_n: 5
        peak_hours: [9, 17]
        default_backend: claude
        rules:
          - role: orient
            model: claude-haiku-4-5-20251001
            backend: claude
            tier: cheap
            timeout_minutes: 15
            retry_models:
              - claude-haiku-4-5-20251001
            retry_max: 2
          - role: execute
            model: openrouter/moonshotai/kimi-k2.5
            backend: openrouter
            tier: cheap
            timeout_minutes: 90
    """
    # Try Python pipeline first (.langywrap/ralph.py).
    # This is the preferred source — model assignments live in the Pipeline,
    # not in a separate router.yaml.
    try:
        from langywrap.ralph.pipeline import load_pipeline_config

        pipeline = load_pipeline_config(project_dir)
        if pipeline is not None:
            route_cfg = pipeline.to_route_config(project_dir)
            if route_cfg is not None:
                return route_cfg
    except Exception:
        pass  # pipeline unavailable or broken — fall through to YAML

    config_path = project_dir / ".langywrap" / "router.yaml"
    if not config_path.exists():
        return DEFAULT_ROUTE_CONFIG

    with config_path.open("r") as fh:
        raw = yaml.safe_load(fh) or {}

    rules = [_parse_rule(r) for r in (raw.get("rules") or [])]

    backend_str = raw.get("default_backend", "claude")
    try:
        default_backend = Backend(backend_str)
    except ValueError:
        default_backend = Backend.CLAUDE

    return RouteConfig(
        name=str(raw.get("name", "unnamed")),
        description=str(raw.get("description", "")),
        rules=rules,
        review_every_n=int(raw.get("review_every_n", 10)),
        peak_hours=_parse_peak_hours(raw.get("peak_hours")),
        default_backend=default_backend,
    )


def save_route_config(config: RouteConfig, project_dir: Path) -> Path:
    """
    Serialize a RouteConfig to ``<project_dir>/.langywrap/router.yaml``.

    Returns the path written.
    """
    config_dir = project_dir / ".langywrap"
    config_dir.mkdir(parents=True, exist_ok=True)
    out_path = config_dir / "router.yaml"

    data: dict[str, Any] = {
        "name": config.name,
        "description": config.description,
        "review_every_n": config.review_every_n,
        "default_backend": config.default_backend.value,
        "peak_hours": list(config.peak_hours) if config.peak_hours else None,
        "rules": [
            {
                "role": rule.role.value,
                "model": rule.model,
                "backend": rule.backend.value,
                "tier": rule.tier.value,
                "timeout_minutes": rule.timeout_minutes,
                "retry_models": rule.retry_models,
                "retry_max": rule.retry_max,
                "conditions": rule.conditions,
            }
            for rule in config.rules
        ],
    }

    with out_path.open("w") as fh:
        yaml.dump(data, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return out_path
