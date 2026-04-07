"""
langywrap.ralph.config — Configuration models for the Ralph loop.

Declarative pipeline definition: steps, quality gates, git policy, and budget.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# StepRole — defined here; router will import from this module or redefine.
# Using a canonical definition here avoids circular import issues when the
# router module is not yet available.
# ---------------------------------------------------------------------------


class StepRole(str, Enum):
    """Logical role of a pipeline step, used by ExecutionRouter for model routing."""

    ORIENT = "orient"
    PLAN = "plan"
    EXECUTE = "execute"
    CRITIC = "critic"
    FINALIZE = "finalize"
    REVIEW = "review"
    GENERIC = "generic"


# ---------------------------------------------------------------------------
# StepConfig
# ---------------------------------------------------------------------------


class StepConfig(BaseModel):
    """Definition of a single pipeline step."""

    name: str
    """Short slug used for filenames and logging (e.g. 'orient', 'execute')."""

    prompt_template: Path
    """Path to the .md prompt template for this step."""

    role: StepRole = StepRole.GENERIC
    """Logical role — passed to ExecutionRouter for model selection."""

    timeout_minutes: int = 30
    """Hard wall-clock timeout for this step."""

    confirmation_token: str = ""
    """Token that MUST appear in step output to be considered successful.
    E.g. 'ORIENT_CONFIRMED:'.  Empty string skips the check."""

    depends_on: list[str] = Field(default_factory=list)
    """Confirmation tokens from prior steps that must be present before running.
    E.g. ['ORIENT_CONFIRMED:', 'PLAN_CONFIRMED:']."""

    model: str = ""
    """Model for this step (empty → router decides)."""

    tools: str = "Read,Write,Edit,Glob,Grep,Bash"
    """Comma-separated tool allow-list passed to the AI engine."""

    engine: str = "auto"
    """Force engine: 'claude', 'opencode', or 'auto' (router decides)."""

    # -- Conditional execution -----------------------------------------------

    run_if_step: str = ""
    """Name of a prior step whose output must match run_if_pattern.
    If empty, the step runs unconditionally."""

    run_if_pattern: str = ""
    """Regex pattern that must match the output of run_if_step for this step
    to execute. Case-insensitive. If run_if_step is empty, this is ignored."""

    run_if_cycle_types: list[str] = Field(default_factory=list)
    """If non-empty, this step only runs when the detected cycle type is in
    this list. E.g. ['lean', 'mixed']. Empty = run regardless of cycle type."""

    output_as: str = ""
    """If set, step output is written to steps/{output_as}.md instead of
    steps/{name}.md, and is stored under this key in confirmed_outputs.
    Use this to define multiple conditional variants of the same logical step
    (e.g. execute.lean and execute.research both output as 'execute')."""

    prompt_extra: str = ""
    """Extra text appended to the prompt template. Used for cycle-type-specific
    injections (e.g. research directives)."""

    # -- Retry loop ----------------------------------------------------------

    retry_count: int = 0
    """If > 0, retry this step up to N times after initial run.
    Useful for lean-fix retries where the step re-runs until compilation passes."""

    retry_gate_command: str = ""
    """Shell command to run after each attempt. If it exits 0, retries stop
    (success). If non-zero and retries remain, the step re-runs with error
    output injected into the prompt. Empty = retry on step failure only."""

    retry_model: str = ""
    """Override model for retry attempts (empty → same as step model)."""

    retry_prompt_template: Path | None = None
    """Alternative prompt template for retry attempts (None → reuse step template)."""

    retry_if_cycle_types: list[str] = Field(default_factory=list)
    """If non-empty, retry loop only runs when detected cycle type is in this list.
    E.g. ['lean', 'mixed']. Empty = retry always (if retry_count > 0)."""

    # -- Pipeline control ----------------------------------------------------

    pipeline: bool = True
    """If False, this step is excluded from the normal pipeline loop.
    Used for steps that only run on special triggers (e.g. adversarial)."""

    fail_fast: bool = False
    """If True and this step fails, skip remaining steps in the cycle."""

    every_n: int = 0
    """If > 0, this step only runs every Nth cycle. E.g. every_n=10 means
    run on cycles 10, 20, 30, etc. 0 = run every cycle."""


# ---------------------------------------------------------------------------
# QualityGateConfig
# ---------------------------------------------------------------------------


class QualityGateConfig(BaseModel):
    """Optional quality gate executed after EXECUTE and before FINALIZE."""

    command: str
    """Shell command to run (e.g. './just check' or 'pytest -q')."""

    timeout_minutes: int = 10
    """Hard timeout for the quality gate command."""

    required: bool = True
    """If True, a failing gate marks the cycle as failed; if False, it's a warning."""

    working_dir: str = ""
    """Working directory for the command; defaults to project_dir."""


# ---------------------------------------------------------------------------
# RalphConfig
# ---------------------------------------------------------------------------


class RalphConfig(BaseModel):
    """Complete configuration for a RalphLoop instance."""

    project_dir: Path
    """Root of the target project."""

    state_dir: Path = Path("ralph")
    """Directory (relative to project_dir) for plan.md, steps/, cycle_count.txt."""

    tasks_file: Path | None = None
    """Override path (relative to project_dir) for tasks.md. Default: state_dir/tasks.md."""

    progress_file: Path | None = None
    """Override path (relative to project_dir) for progress.md. Default: state_dir/progress.md."""

    prompts_dir: Path = Path("")
    """Directory for prompt templates; empty → state_dir/prompts (resolved at runtime)."""

    steps: list[StepConfig]
    """Ordered pipeline steps."""

    quality_gate: QualityGateConfig | None = None
    """Optional quality gate run after all steps."""

    quality_gates: list[QualityGateConfig] = Field(default_factory=list)
    """Additional quality gates (run in order after quality_gate).
    Use for domain-specific gates like `lake build` that are separate from lint/test."""

    budget: int = 10
    """Maximum number of cycles to run."""

    review_every_n: int = 10
    """Print a summary review every N cycles."""

    adversarial_every_n: int | None = 12
    """If set, run an adversarial / stress-test cycle every N cycles."""

    hygiene_every_n: int | None = 5
    """If set, inject a hygiene task into tasks.md every N cycles.
    Hygiene tasks cover: lint/type/test fixes, debt review, format checks.
    Set to None to disable."""

    hygiene_template: str = ""
    """Custom hygiene task markdown. If empty, a sensible default is used.
    Placeholders: {cycle}, {date}, {quality_gate_cmd}."""

    periodic_tasks: list[dict[str, Any]] = Field(default_factory=list)
    """Additional periodic task injections (beyond hygiene).
    Each dict: {"every": 9, "marker": "lookback", "template": "...markdown..."}
    Marker is used to prevent duplicate injection. Template supports {cycle}, {date}."""

    git_commit_after_cycle: bool = True
    """Commit staged changes at the end of each cycle."""

    git_add_paths: list[str] = Field(default_factory=list)
    """Explicit paths to stage before committing (empty → no git add, only already-staged)."""

    scope_restriction: str = ""
    """Text injected into every prompt header as a CRITICAL SCOPE RESTRICTION."""

    secret_patterns: list[str] = Field(
        default_factory=lambda: [
            r"\.env$",
            r"credentials",
            r"secret",
            r"\.pem$",
            r"\.key$",
            r"password",
            r"api_key",
            r"AUTH_TOKEN",
        ]
    )
    """Regex patterns for filenames that must never be committed."""

    verbose: bool = True
    """Emit step banners and progress logs to stdout."""

    max_hang_retries: int = 2
    """Retry count when a step exits 124 (timeout) with tiny output (API hang)."""

    # -- Peak-hour throttle --------------------------------------------------

    throttle_utc_start: int | None = None
    """UTC hour (0–23) when peak-hour throttle begins. None = disabled.
    E.g. 13 for 13:00 UTC (= 14:00 CET Prague)."""

    throttle_utc_end: int | None = None
    """UTC hour (0–23) when peak-hour throttle ends. E.g. 19 for 19:00 UTC."""

    throttle_weekdays_only: bool = True
    """If True, throttle only applies Monday–Friday."""

    # -- Adversarial milestone triggers --------------------------------------

    adversarial_step: str = ""
    """Name of the step config to use for adversarial cycles (from steps list).
    If empty, adversarial cycles use a step named 'adversarial' or are skipped."""

    adversarial_milestone_patterns: list[str] = Field(default_factory=list)
    """Regex patterns matched against execute step output. If ANY match,
    an adversarial cycle is triggered regardless of adversarial_every_n.
    E.g. ['axiom.*elim', 'sorry.*chain.*0', 'all.*sorries.*filled']."""

    # -- Cycle type detection ------------------------------------------------

    cycle_type_rules: list[dict[str, str]] = Field(default_factory=list)
    """Rules for classifying cycles based on plan.md content.
    Each dict: {"name": "lean", "pattern": "sorry.*fill|lean formali"}
    Last matching rule wins. Used to set cycle_type which gates conditional
    steps via step.run_if_cycle_types. Pattern is case-insensitive regex
    matched against plan.md content."""

    # ------------------------------------------------------------------ helpers

    @property
    def resolved_state_dir(self) -> Path:
        sd = self.state_dir
        if not sd.is_absolute():
            sd = self.project_dir / sd
        return sd

    @property
    def resolved_tasks_file(self) -> Path:
        if self.tasks_file:
            p = self.tasks_file
            if not p.is_absolute():
                p = self.project_dir / p
            return p
        return self.resolved_state_dir / "tasks.md"

    @property
    def resolved_progress_file(self) -> Path:
        if self.progress_file:
            p = self.progress_file
            if not p.is_absolute():
                p = self.project_dir / p
            return p
        return self.resolved_state_dir / "progress.md"

    @property
    def resolved_prompts_dir(self) -> Path:
        if self.prompts_dir and str(self.prompts_dir) != "":
            pd = self.prompts_dir
            if not pd.is_absolute():
                pd = self.project_dir / pd
            return pd
        return self.resolved_state_dir / "prompts"

    def model_post_init(self, __context: Any) -> None:  # pydantic v2 hook
        # Resolve project_dir to absolute
        self.project_dir = self.project_dir.resolve()


# ---------------------------------------------------------------------------
# Default 5-step pipeline — matches riemann2 proven pattern
# ---------------------------------------------------------------------------

_PROMPTS_PLACEHOLDER = Path("__prompts__")  # resolved at load time


DEFAULT_STEPS: list[StepConfig] = [
    StepConfig(
        name="orient",
        prompt_template=_PROMPTS_PLACEHOLDER / "step1_orient.md",
        role=StepRole.ORIENT,
        timeout_minutes=20,
        confirmation_token="ORIENT_CONFIRMED:",
        depends_on=[],
    ),
    StepConfig(
        name="plan",
        prompt_template=_PROMPTS_PLACEHOLDER / "step2_plan.md",
        role=StepRole.PLAN,
        timeout_minutes=20,
        confirmation_token="PLAN_CONFIRMED:",
        depends_on=["ORIENT_CONFIRMED:"],
    ),
    StepConfig(
        name="execute",
        prompt_template=_PROMPTS_PLACEHOLDER / "step3_execute.md",
        role=StepRole.EXECUTE,
        timeout_minutes=120,
        confirmation_token="EXECUTE_CONFIRMED:",
        depends_on=["PLAN_CONFIRMED:"],
    ),
    StepConfig(
        name="critic",
        prompt_template=_PROMPTS_PLACEHOLDER / "step3c_critic.md",
        role=StepRole.CRITIC,
        timeout_minutes=45,
        confirmation_token="CRITIC_CONFIRMED:",
        depends_on=["EXECUTE_CONFIRMED:"],
    ),
    StepConfig(
        name="finalize",
        prompt_template=_PROMPTS_PLACEHOLDER / "step4_finalize.md",
        role=StepRole.FINALIZE,
        timeout_minutes=30,
        confirmation_token="FINALIZE_CONFIRMED:",
        depends_on=["CRITIC_CONFIRMED:"],
    ),
]


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

_CONFIG_PATHS = [
    ".langywrap/ralph.yaml",
    ".langywrap/ralph.yml",
    "ralph.yaml",
]


def _resolve_step_prompts(steps: list[StepConfig], prompts_dir: Path) -> list[StepConfig]:
    """Replace _PROMPTS_PLACEHOLDER in template paths with the real prompts dir."""
    resolved = []
    for step in steps:
        updates: dict[str, Any] = {}

        pt = step.prompt_template
        parts = pt.parts
        if parts and parts[0] == "__prompts__":
            pt = prompts_dir / Path(*parts[1:])
        elif not pt.is_absolute():
            pt = prompts_dir / pt
        updates["prompt_template"] = pt

        # Also resolve retry_prompt_template if set
        if step.retry_prompt_template is not None:
            rpt = step.retry_prompt_template
            if not rpt.is_absolute():
                rpt = prompts_dir / rpt
            updates["retry_prompt_template"] = rpt

        resolved.append(step.model_copy(update=updates))
    return resolved


def load_ralph_config(project_dir: Path) -> "RalphConfig":
    """Load RalphConfig from .langywrap/ralph.yaml (or fallback paths).

    Supports two formats:
      - **v2** (preferred): detected by presence of ``flow:`` key. Clean grouped sections.
      - **v1** (legacy): flat field soup with ``steps:`` list.

    Falls back to a DEFAULT_STEPS config if no file is found.
    """
    project_dir = project_dir.resolve()

    # Try Python pipeline first (.langywrap/ralph.py)
    from langywrap.ralph.pipeline import load_pipeline_config

    pipeline = load_pipeline_config(project_dir)
    if pipeline is not None:
        return pipeline.to_ralph_config(project_dir)

    cfg_path: Path | None = None
    for candidate in _CONFIG_PATHS:
        p = project_dir / candidate
        if p.exists():
            cfg_path = p
            break

    if cfg_path is None:
        # Build a sensible default config for the project
        prompts_dir = project_dir / "ralph" / "prompts"
        steps = _resolve_step_prompts(DEFAULT_STEPS, prompts_dir)
        return RalphConfig(
            project_dir=project_dir,
            state_dir=Path("ralph"),
            steps=steps,
        )

    with cfg_path.open() as fh:
        raw: dict = yaml.safe_load(fh) or {}

    # V2 format detection: presence of 'flow' key
    from langywrap.ralph.config_v2 import is_v2_config, load_v2

    if is_v2_config(raw):
        return load_v2(raw, project_dir)

    # V1 legacy format
    raw["project_dir"] = str(project_dir)

    if "steps" not in raw or not raw["steps"]:
        raw_steps = []
        prompts_dir = project_dir / raw.get("state_dir", "ralph") / "prompts"
        raw["steps"] = []
        cfg = RalphConfig(**raw)
        cfg_steps = _resolve_step_prompts(DEFAULT_STEPS, cfg.resolved_prompts_dir)
        return cfg.model_copy(update={"steps": cfg_steps})

    cfg = RalphConfig(**raw)
    resolved_steps = _resolve_step_prompts(cfg.steps, cfg.resolved_prompts_dir)
    return cfg.model_copy(update={"steps": resolved_steps})
