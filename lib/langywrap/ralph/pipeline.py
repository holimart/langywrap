"""
langywrap.ralph.pipeline — DSPy-style Python pipeline definitions.

Define ralph loops as Python classes with typed Pydantic models instead of YAML.
Each pipeline is a Module subclass with step definitions as class attributes
and a ``forward()`` method defining the execution flow.

The pipeline objects bridge to the RalphConfig/StepConfig used by the
runner; model+engine+timeout live on each Step directly and are handed to
``ExecutionRouter.execute()`` at run time. There is no separate RouteConfig.

Example::

    from langywrap.ralph.pipeline import Pipeline, Step, Gate

    config = Pipeline(
        prompts="research/prompts",
        steps=[
            Step("orient", model="haiku", prompt="orient.md", fail_fast=True),
            Step("execute", model="kimi", prompt="execute.md", timeout=120,
                 fallback="sonnet"),
            Step("finalize", model="kimi", prompt="finalize.md"),
        ],
        gates=[Gate("./just check")],
    )

HyperAgent compatibility:
    - Step attributes are the "genome" — random mutations patch these
    - Pipeline structure is the "program" — meta-mutations rewrite forward()
    - ``export_genome()`` / ``apply_overrides()`` for variant integration
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Model alias resolution (shared with config_v2)
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
    """Infer backend from model prefix.

    This is used when a Step doesn't explicitly set ``engine``.

    Supported prefixes:
    - ``openrouter/`` → openrouter
    - ``claude-`` / ``gpt-`` / ``o1-`` / ``o3-`` → direct_api
    - otherwise → opencode
    """
    m = model.strip()
    if m.startswith("openrouter/"):
        return "openrouter"
    if (
        m.startswith("claude-")
        or m.startswith("gpt-")
        or m.startswith("o1-")
        or m.startswith("o3-")
    ):
        return "direct_api"
    return "opencode"


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


class Gate(BaseModel):
    """Quality gate — a shell command that must pass."""

    command: str
    timeout: int = 10
    """Timeout in minutes."""

    required: bool = True
    """If False, failure is a warning, not an error."""

    def __init__(self, command: str, **kwargs: Any) -> None:
        super().__init__(command=command, **kwargs)


# ---------------------------------------------------------------------------
# Match — cycle type detection
# ---------------------------------------------------------------------------


class Match(BaseModel):
    """Cycle type classifier — matches plan output against regex patterns.

    Usage::

        Match(
            lean=r"sorry.*fill|\\.lean|lake build",
            research=r"web.?research|literature|arXiv",
        )
    """

    source: str = "plan"
    """Step whose output to match against (default: plan)."""

    rules: dict[str, str] = Field(default_factory=dict)
    """Mapping of cycle_type_name → regex pattern."""

    def __init__(self, source: str = "plan", **kwargs: Any) -> None:
        # Separate known fields from pattern kwargs
        rules = {}
        known_fields = {"source", "rules"}
        extra = {}
        for k, v in kwargs.items():
            if k in known_fields:
                extra[k] = v
            elif isinstance(v, str):
                rules[k] = v
        if "rules" in extra:
            rules.update(extra.pop("rules"))
        super().__init__(source=source, rules=rules, **extra)


class PlanDecision(BaseModel):
    """Cycle type classifier — read an explicit planner decision field.

    The planner writes a small structured block, for example::

        orchestrator:
          execute_type: lean

    The runner reads ``execute_type`` directly instead of inferring from plan
    prose. Missing, invalid, mixed, or undecided values fall back to
    ``default``.
    """

    source: str = "plan"
    """Step whose output contains the decision block."""

    field: str = "execute_type"
    """Planner field to read."""

    allowed: list[str] = Field(default_factory=lambda: ["execute", "lean", "research"])
    """Accepted route names."""

    default: str = "execute"
    """Route used when the field is missing, invalid, mixed, or undecided."""


# ---------------------------------------------------------------------------
# CycleOverride — per-cycle-type modifications
# ---------------------------------------------------------------------------


class CycleOverride(BaseModel):
    """Override step parameters when a specific cycle type is detected."""

    model: str = ""
    """Override model for this cycle type."""

    inject: str = ""
    """Prompt file or inline text to inject for this cycle type.
    If it ends with .md, treated as a file relative to prompts dir."""


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


class Retry(BaseModel):
    """Retry policy for a step — gate check + retry loop + fallback.

    Usage::

        Retry(
            gate=Gate("./lean-check.sh"),
            attempts=5,
            model="kimi",
            prompt="retry.md",
            fallback="sonnet",
            cycles=["lean", "mixed"],
        )
    """

    gate: Gate | None = None
    """Gate command run around each LLM attempt.

    ``gate_mode`` controls when the first gate check happens:
    - ``"after"``  (default) — run gate *after* the LLM; standard retry loop.
    - ``"before"`` — run gate *before* the first LLM call; if it already
      passes, skip the LLM entirely (useful for fix/lint steps that may be
      no-ops)."""

    gate_mode: str = "after"
    """When to run the first gate check: ``"before"`` or ``"after"`` (default)."""

    attempts: int = 3
    """Maximum retry attempts."""

    model: str = ""
    """Model to use for retry attempts (empty = same as step)."""

    prompt: str = ""
    """Prompt template for retries (empty = same as step). Relative to prompts dir."""

    fallback: str = ""
    """Fallback model after all retry attempts exhausted. Runs once."""

    cycles: list[str] = Field(default_factory=list)
    """Only retry for these cycle types. Empty = always retry."""


# ---------------------------------------------------------------------------
# Step
# ---------------------------------------------------------------------------


class Step(BaseModel):
    """Definition of a single pipeline step.

    Usage::

        Step("orient", model="haiku", prompt="orient.md", fail_fast=True)
        Step("execute", model="kimi", prompt="execute.md", timeout=120,
             fallback="sonnet",
             retry=Retry(gate=Gate("./check.sh"), attempts=5))
    """

    name: str
    """Short slug (e.g. 'orient', 'execute')."""

    model: str = "sonnet"
    """Model alias or full ID."""

    prompt: str = ""
    """Prompt template filename, relative to prompts dir."""

    timeout: int = 30
    """Timeout in minutes."""

    tools: list[str] = Field(
        default_factory=lambda: ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]
    )
    """Tool allow-list."""

    fail_fast: bool = False
    """If True and step fails, skip remaining steps in cycle."""

    confirmation_token: str = ""
    """Token that must appear in the step output to mark it confirmed."""

    engine: str = "auto"
    """Force engine: 'claude', 'opencode', or 'auto' (router decides)."""

    builtin: str = ""
    """Optional native non-LLM implementation name (e.g. 'orient')."""

    # -- Conditional execution -----------------------------------------------

    when: str = ""
    """Guard condition: ``'execute =~ /pattern/'``. Step only runs if matched."""

    when_cycle: list[str] = Field(default_factory=list)
    """Cycle-type gate: step only runs when detected cycle type is in this list.
    E.g. ``["lean", "mixed"]``. Empty = run regardless of cycle type."""

    output_as: str = ""
    """If set, step output is written to steps/{output_as}.md instead of
    steps/{name}.md. Use for conditional variants of the same logical step
    (e.g. execute.lean and execute.research both output as 'execute')."""

    inject: str = ""
    """Extra text appended to the prompt template (e.g. research directive)."""

    every: int = 0
    """Run every Nth cycle only (0 = every cycle)."""

    # -- Fallback (simple) ---------------------------------------------------

    fallback: str = ""
    """Simple fallback model. If step fails, retry once with this model."""

    # -- Retry (complex) -----------------------------------------------------

    retry: Retry | None = None
    """Full retry policy with gate, attempts, fallback chain."""

    # -- Cycle type detection ------------------------------------------------

    detects_cycle: Match | PlanDecision | None = None
    """If set, this step's output is used to classify the cycle type."""

    per_cycle: dict[str, dict[str, str]] = Field(default_factory=dict)
    """DEPRECATED. Use conditional steps with when_cycle instead."""

    # -- Pipeline control ----------------------------------------------------

    pipeline: bool = True
    """If False, excluded from normal pipeline (e.g. adversarial)."""

    gate: Gate | None = None
    """Step-level quality gate (run after this step)."""

    enabled: bool = True
    """HyperAgent-togglable. If False, step is skipped."""

    enrich: list[str] = Field(default_factory=list)
    """External context enrichers to inject before the prompt body.

    Resolved by name against ``ralph.context.ENRICHERS``. Built-in:
        'graphify' — reads graphify-out/GRAPH_REPORT.md (capped 20KB).

    Prefer for ``orient``/``critic`` steps; skip ``execute`` (grep beats
    graphs there per SWE-bench evidence). Missing source files silently
    no-op, so pipelines are safe on repos without graphify installed.
    HyperAgent genome includes this list — evolution can toggle per role."""

    # -- Explicit role flags (replace former step.name magic) ----------------
    #
    # The runner historically inferred behavior from `step.name` — e.g. a step
    # named "orient" got orient-context injection, "execute" was picked for
    # peak-hour backend inference, and "orient"/"plan" triggered plan.md
    # validation. Name-based magic is gone: projects opt in via these flags.

    validates_plan: bool = False
    """After this step runs, validate ``plan.md`` against
    ``Pipeline.plan_must_contain`` / ``plan_must_match`` / ``plan_require_current_cycle``.
    Set on the step that writes plan.md (typically the plan step)."""

    primary: bool = False
    """This step is the primary execute step. Used for peak-hour throttle
    backend inference (``throttle_skip_backends``). Exactly one step per
    pipeline should set this; if none do, throttling treats every backend
    as non-primary (no skip)."""

    includes_orient_context: bool = False
    """If True, the step's prompt is prefixed with the compact orient_context
    block (recent cycles summary + tasks.md head). Set this on the step
    whose prompt expects the context (typically the orient step)."""

    def __init__(self, name: str = "", **kwargs: Any) -> None:
        if "token" in kwargs and "confirmation_token" not in kwargs:
            kwargs["confirmation_token"] = kwargs.pop("token")
        super().__init__(name=name, **kwargs)


# ---------------------------------------------------------------------------
# Loop — compound step with inner cycle
# ---------------------------------------------------------------------------


class Loop(BaseModel):
    """Compound step with an inner retry loop.

    Usage::

        Loop("develop", max=5, until="review =~ /LGTM/", steps=[
            Step("engineer", model="kimi", prompt="engineer.md", timeout=60),
            Gate("./just check"),
            Step("review", model="sonnet", prompt="review.md", timeout=20),
        ], escalate={4: {"engineer.model": "sonnet"}})
    """

    name: str
    """Name of the compound step."""

    max: int = 5
    """Maximum iterations."""

    until: str = ""
    """Exit condition: ``'review =~ /LGTM/'``. Loop exits when matched."""

    steps: list[Step | Gate] = Field(default_factory=list)
    """Inner steps executed each iteration."""

    escalate: dict[int, dict[str, str]] = Field(default_factory=dict)
    """Per-iteration overrides: ``{4: {"engineer.model": "sonnet"}}``."""

    def __init__(self, name: str = "", **kwargs: Any) -> None:
        super().__init__(name=name, **kwargs)


# ---------------------------------------------------------------------------
# Periodic
# ---------------------------------------------------------------------------


class Periodic(BaseModel):
    """Periodic task injection (hygiene, lookback, adversarial, etc.).

    Usage::

        Periodic(every=12, step=Step("adversarial", model="sonnet", prompt="adversarial.md"),
                 or_when="execute =~ /axiom.*elim/")
        Periodic(every=5, builtin="hygiene")
        Periodic(every=9, builtin="lookback", template="...")
    """

    every: int
    """Run every N cycles."""

    step: Step | None = None
    """Step to run (for non-builtin periodic tasks like adversarial)."""

    builtin: str = ""
    """Built-in periodic task name: 'hygiene' or 'lookback'."""

    template: str = ""
    """Markdown template for task injection. Supports {cycle}, {date}."""

    or_when: str = ""
    """Additional trigger condition: ``'execute =~ /pattern/'``."""

    marker: str = ""
    """Dedup marker for periodic task injection. Defaults to builtin or step name."""


# ---------------------------------------------------------------------------
# Throttle
# ---------------------------------------------------------------------------


class Throttle(BaseModel):
    """Peak-hour throttle configuration."""

    utc: str = ""
    """UTC hour range: ``'13-19'``."""

    weekdays_only: bool = True
    """Only throttle on weekdays (Mon–Fri)."""


# ---------------------------------------------------------------------------
# Pipeline — top-level config
# ---------------------------------------------------------------------------


class Pipeline(BaseModel):
    """Complete pipeline definition. Converts to RalphConfig for the runner.

    Usage::

        config = Pipeline(
            prompts="research/prompts",
            state="research",
            steps=[
                Step("orient", model="haiku", prompt="orient.md", fail_fast=True),
                Step("execute", model="kimi", prompt="execute.md", timeout=120),
                Step("finalize", model="kimi", prompt="finalize.md"),
            ],
            gates=[Gate("./just check")],
            throttle=Throttle(utc="13-19"),
        )
    """

    prompts: str = ""
    """Prompts directory, relative to project root."""

    state: str = "ralph"
    """State directory, relative to project root."""

    tasks_file: str = ""
    """Override path for tasks.md (relative to project root). Default: state/tasks.md."""

    progress_file: str = ""
    """Override path for progress.md (relative to project root). Default: state/progress.md."""

    steps: list[Step | Loop] = Field(default_factory=list)
    """Ordered pipeline steps and loops."""

    gates: list[Gate] = Field(default_factory=list)
    """Global quality gates (run after all steps each cycle)."""

    periodic: list[Periodic] = Field(default_factory=list)
    """Periodic tasks (hygiene, lookback, adversarial, etc.)."""

    throttle: Throttle | None = None
    """Peak-hour throttle."""

    throttle_skip_backends: list[str] = Field(default_factory=list)
    """Backend names that bypass peak-hour throttling."""

    git: list[str] = Field(default_factory=list)
    """Git paths to stage after each cycle."""

    post_cycle_commands: list[str] = Field(default_factory=list)
    """Shell commands run at the end of every cycle, before git commit.

    Fires regardless of commit outcome. Non-zero exits are warnings, not
    failures. Intended for refreshing external indices so updates land in
    the same commit as the code that triggered them::

        Pipeline(
            post_cycle_commands=[
                "./textify/src/textify/cli.py docs graphify-in/docs || true",
                "graphify --update",
            ],
            ...
        )"""

    post_cycle_command_timeout: int = 120
    """Per-command timeout (seconds) for ``post_cycle_commands``."""

    secrets: list[str] = Field(
        default_factory=lambda: [r"\.env$", "credentials", "secret", "api_key"]
    )
    """Regex patterns for files that must never be committed."""

    aliases: dict[str, str] = Field(default_factory=dict)
    """Project-specific model aliases (merged on top of builtins).

    Example::

        Pipeline(
            aliases={
                "codex":      "openai/gpt-5.1-codex",
                "codex-mini": "openai/codex-mini-latest",
                "codex-max":  "openai/gpt-5.1-codex-max",
            },
            ...
        )
    """

    scope: str = ""
    """Scope restriction injected into every prompt."""

    plan_must_contain: list[str] = Field(default_factory=list)
    """Literal substrings that must appear in plan.md after orient."""

    plan_must_match: list[str] = Field(default_factory=list)
    """Regex patterns that must match plan.md after orient."""

    plan_require_current_cycle: bool = False
    """Require plan.md to mention the current cycle number."""

    budget: int = 10
    """Default max cycles."""

    verbose: bool = True
    """Emit progress logs."""

    max_consecutive_failed_cycles: int = 3
    """Stop after N consecutive failed cycles."""

    # -----------------------------------------------------------------------
    # Conversion to RalphConfig (bridge to runner)
    # -----------------------------------------------------------------------

    def to_ralph_config(self, project_dir: Path) -> RalphConfig:  # noqa: F821
        """Convert this Pipeline to a RalphConfig for the runner.

        This is the bridge: Python pipeline → internal config objects.
        Zero runner changes needed.
        """
        from langywrap.ralph.config import (
            QualityGateConfig,
            RalphConfig,
            StepConfig,
        )

        project_dir = project_dir.resolve()
        prompts_dir = (
            project_dir / self.prompts if self.prompts else project_dir / self.state / "prompts"
        )
        resolve = lambda name: _resolve_model(name, self.aliases)  # noqa: E731

        step_configs: list[StepConfig] = []
        cycle_type_rules: list[dict[str, str]] = []
        cycle_type_source: str = "plan"
        adversarial_step_name = ""
        adversarial_every_n: int | None = None
        adversarial_milestone_patterns: list[str] = []
        hygiene_every_n: int | None = None
        periodic_tasks: list[dict[str, Any]] = []

        # --- Steps ---
        for item in self.steps:
            if isinstance(item, Loop):
                # Loop → expand to steps with retry logic
                # For now, loops are converted to their inner steps
                # with the loop's retry semantics encoded
                step_configs.extend(self._loop_to_step_configs(item, prompts_dir))
                continue

            step = item
            if not step.enabled:
                continue

            sc = self._step_to_step_config(step, prompts_dir)
            step_configs.append(sc)

            # Cycle type detection
            if step.detects_cycle:
                # Match.source / PlanDecision.source names the step whose
                # output drives cycle type detection.
                if step.detects_cycle.source:
                    cycle_type_source = step.detects_cycle.source
                if isinstance(step.detects_cycle, PlanDecision):
                    cycle_type_rules.append(
                        {
                            "name": "__plan_decision__",
                            "field": step.detects_cycle.field,
                            "allowed": "|".join(step.detects_cycle.allowed),
                            "default": step.detects_cycle.default,
                        }
                    )
                else:
                    for name, pattern in step.detects_cycle.rules.items():
                        rule: dict[str, str] = {"name": name, "pattern": pattern}
                        cycle_type_rules.append(rule)

            # Collect per_cycle overrides into cycle_type_rules
            if step.per_cycle:
                for ct_name, overrides in step.per_cycle.items():
                    # Find or create the rule
                    existing = next((r for r in cycle_type_rules if r["name"] == ct_name), None)
                    if existing is None:
                        existing = {"name": ct_name, "pattern": ""}
                        cycle_type_rules.append(existing)
                    if "model" in overrides:
                        existing["model"] = resolve(overrides["model"])
                    if "inject" in overrides:
                        inject_val = overrides["inject"]
                        # If ends with .md, read the file
                        if inject_val.endswith(".md"):
                            inject_path = prompts_dir / inject_val
                            if inject_path.exists():
                                inject_val = inject_path.read_text(encoding="utf-8")
                        existing["prompt_extra"] = inject_val

        # --- Periodic tasks ---
        for p in self.periodic:
            if p.builtin == "hygiene":
                hygiene_every_n = p.every
            elif p.builtin == "lookback":
                marker = p.marker or "lookback"
                periodic_tasks.append(
                    {
                        "every": p.every,
                        "marker": marker,
                        "template": p.template,
                    }
                )
            elif p.step:
                # Adversarial or custom periodic step
                if p.step.name == "adversarial":
                    adversarial_every_n = p.every
                    adversarial_step_name = p.step.name
                    # Parse or_when for milestone patterns
                    if p.or_when:
                        _, pattern = _parse_when(p.or_when)
                        adversarial_milestone_patterns.append(pattern)
                    # Add adversarial step config (non-pipeline)
                    adv_sc = self._step_to_step_config(p.step, prompts_dir)
                    adv_sc = adv_sc.model_copy(update={"pipeline": False})
                    step_configs.append(adv_sc)
                else:
                    # Generic periodic step
                    periodic_tasks.append(
                        {
                            "every": p.every,
                            "marker": p.marker or p.step.name,
                            "template": p.template,
                        }
                    )
            elif p.template:
                # Template-only periodic (like lookback without builtin flag)
                periodic_tasks.append(
                    {
                        "every": p.every,
                        "marker": p.marker or "periodic",
                        "template": p.template,
                    }
                )

        # --- Gates ---
        primary_gate = None
        extra_gates: list[QualityGateConfig] = []
        for i, g in enumerate(self.gates):
            qg = QualityGateConfig(
                command=g.command,
                timeout_minutes=g.timeout,
                required=g.required,
            )
            if i == 0:
                primary_gate = qg
            else:
                extra_gates.append(qg)

        # Also collect step-level gates as additional gates
        for item in self.steps:
            if isinstance(item, Step) and item.gate:
                extra_gates.append(
                    QualityGateConfig(
                        command=item.gate.command,
                        timeout_minutes=item.gate.timeout,
                        required=item.gate.required,
                    )
                )

        # --- Throttle ---
        throttle_start = None
        throttle_end = None
        throttle_weekdays = True
        if self.throttle and self.throttle.utc:
            parts = self.throttle.utc.split("-")
            if len(parts) == 2:
                throttle_start = int(parts[0])
                throttle_end = int(parts[1])
                throttle_weekdays = self.throttle.weekdays_only

        return RalphConfig(
            project_dir=project_dir,
            state_dir=Path(self.state),
            prompts_dir=Path(self.prompts) if self.prompts else Path(""),
            steps=step_configs,
            quality_gate=primary_gate,
            quality_gates=extra_gates,
            budget=self.budget,
            adversarial_every_n=adversarial_every_n,
            adversarial_step=adversarial_step_name,
            adversarial_milestone_patterns=adversarial_milestone_patterns,
            hygiene_every_n=hygiene_every_n,
            periodic_tasks=periodic_tasks,
            git_commit_after_cycle=True,
            git_push_after_commit=True,
            git_add_paths=self.git,
            post_cycle_commands=list(self.post_cycle_commands),
            post_cycle_command_timeout=self.post_cycle_command_timeout,
            scope_restriction=self.scope,
            secret_patterns=self.secrets,
            verbose=self.verbose,
            max_consecutive_failed_cycles=self.max_consecutive_failed_cycles,
            throttle_utc_start=throttle_start,
            throttle_utc_end=throttle_end,
            throttle_weekdays_only=throttle_weekdays,
            throttle_skip_backends=self.throttle_skip_backends,
            cycle_type_rules=cycle_type_rules,
            cycle_type_source=cycle_type_source,
            plan_must_contain=self.plan_must_contain,
            plan_must_match=self.plan_must_match,
            plan_require_current_cycle=self.plan_require_current_cycle,
            tasks_file=Path(self.tasks_file) if self.tasks_file else None,
            progress_file=Path(self.progress_file) if self.progress_file else None,
        )

    # -----------------------------------------------------------------------
    # HyperAgent genome interface
    # -----------------------------------------------------------------------

    def export_genome(self) -> dict[str, Any]:
        """Export mutable parameters as a flat dict for HyperAgent variants.

        Random mutations operate on this dict. Structure matches what
        ``apply_overrides()`` accepts.
        """
        genome: dict[str, Any] = {}
        for item in self.steps:
            if isinstance(item, Step):
                genome[item.name] = {
                    "model": item.model,
                    "timeout": item.timeout,
                    "enabled": item.enabled,
                    "fail_fast": item.fail_fast,
                    "tools": item.tools,
                    "enrich": list(item.enrich),
                }
                if item.fallback:
                    genome[item.name]["fallback"] = item.fallback
                if item.retry:
                    genome[item.name]["retry"] = {
                        "attempts": item.retry.attempts,
                        "model": item.retry.model,
                        "fallback": item.retry.fallback,
                    }
                if item.per_cycle:
                    genome[item.name]["per_cycle"] = item.per_cycle
            elif isinstance(item, Loop):
                genome[item.name] = {
                    "max": item.max,
                    "steps": {},
                }
                for inner in item.steps:
                    if isinstance(inner, Step):
                        genome[item.name]["steps"][inner.name] = {
                            "model": inner.model,
                            "timeout": inner.timeout,
                        }

        # Periodic steps
        for p in self.periodic:
            if p.step:
                genome[f"periodic.{p.step.name}"] = {
                    "every": p.every,
                    "model": p.step.model,
                }

        return genome

    def apply_overrides(self, overrides: dict[str, Any]) -> Pipeline:
        """Apply HyperAgent variant overrides (genome patches) to this pipeline.

        Returns a new Pipeline with the overrides applied.

        Example overrides::

            {
                "orient.model": "sonnet",
                "execute.timeout": 180,
                "execute.enabled": False,
                "lean_retry.attempts": 3,
            }
        """
        import copy

        new = copy.deepcopy(self)

        for key, value in overrides.items():
            parts = key.split(".", 1)
            if len(parts) != 2:
                continue
            step_name, field = parts

            # Find step in pipeline
            for i, item in enumerate(new.steps):
                if isinstance(item, Step) and item.name == step_name:
                    if field == "model":
                        new.steps[i] = item.model_copy(update={"model": value})
                    elif field == "timeout":
                        new.steps[i] = item.model_copy(update={"timeout": value})
                    elif field == "enabled":
                        new.steps[i] = item.model_copy(update={"enabled": value})
                    elif field == "fail_fast":
                        new.steps[i] = item.model_copy(update={"fail_fast": value})
                    elif field == "fallback":
                        new.steps[i] = item.model_copy(update={"fallback": value})
                    elif field == "enrich":
                        new.steps[i] = item.model_copy(update={"enrich": list(value)})
                    break
                elif isinstance(item, Loop) and item.name == step_name:
                    if field == "max":
                        new.steps[i] = item.model_copy(update={"max": value})
                    break

            # Check periodic steps
            for i, p in enumerate(new.periodic):
                key_prefix = key.split(".")[0] + "." + key.split(".")[1]
                if p.step and f"periodic.{p.step.name}" == key_prefix:
                    if len(parts) > 1 and parts[1] == "every":
                        new.periodic[i] = p.model_copy(update={"every": value})
                    elif len(parts) > 1 and parts[1] == "model" and p.step:
                        new_step = p.step.model_copy(update={"model": value})
                        new.periodic[i] = p.model_copy(update={"step": new_step})

        return new

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _step_to_step_config(self, step: Step, prompts_dir: Path) -> StepConfig:  # noqa: F821
        """Convert a Step to a StepConfig."""
        from langywrap.ralph.config import StepConfig

        resolve = lambda name: _resolve_model(name, self.aliases)  # noqa: E731
        model_id = resolve(step.model)

        # Resolve prompt template path
        prompt_path = prompts_dir / step.prompt if step.prompt else prompts_dir / f"{step.name}.md"
        if not prompt_path.exists():
            for candidate in prompts_dir.glob(f"*_{step.name}*.md"):
                prompt_path = candidate
                break

        # Parse when condition
        run_if_step = ""
        run_if_pattern = ""
        if step.when:
            run_if_step, run_if_pattern = _parse_when(step.when)

        # Retry config
        retry_count = 0
        retry_gate = ""
        retry_gate_mode = "after"
        retry_model = ""
        retry_prompt: Path | None = None
        retry_cycles: list[str] = []

        if step.retry:
            retry_count = step.retry.attempts
            retry_gate = step.retry.gate.command if step.retry.gate else ""
            retry_gate_mode = step.retry.gate_mode
            retry_model = resolve(step.retry.model) if step.retry.model else ""
            if step.retry.prompt:
                retry_prompt = prompts_dir / step.retry.prompt
            retry_cycles = step.retry.cycles

        # Simple fallback → convert to retry with 1 attempt
        if step.fallback and not step.retry:
            retry_count = 1
            retry_model = resolve(step.fallback)

        # Build the dispatcher fallback chain (Step.fallback + Retry.fallback).
        retry_chain: list[str] = []
        if step.fallback:
            retry_chain.append(resolve(step.fallback))
        if step.retry and step.retry.fallback:
            fb = resolve(step.retry.fallback)
            if fb not in retry_chain:
                retry_chain.append(fb)

        tools = ",".join(step.tools) if step.tools else "Read,Write,Edit,Glob,Grep,Bash"

        return StepConfig(
            name=step.name,
            prompt_template=prompt_path,
            timeout_minutes=step.timeout,
            confirmation_token=step.confirmation_token,
            model=model_id,
            tools=tools,
            engine=step.engine,
            builtin=step.builtin,
            retry_models=retry_chain,
            run_if_step=run_if_step,
            run_if_pattern=run_if_pattern,
            run_if_cycle_types=step.when_cycle,
            output_as=step.output_as,
            prompt_extra=step.inject,
            retry_count=retry_count,
            retry_gate_command=retry_gate,
            retry_gate_mode=retry_gate_mode,
            retry_model=retry_model,
            retry_prompt_template=retry_prompt,
            retry_if_cycle_types=retry_cycles,
            fail_fast=step.fail_fast,
            pipeline=step.pipeline,
            every_n=step.every,
            enrich=list(step.enrich),
            validates_plan=step.validates_plan,
            primary=step.primary,
            includes_orient_context=step.includes_orient_context,
        )

    def _loop_to_step_configs(self, loop: Loop, prompts_dir: Path) -> list[StepConfig]:  # noqa: F821
        """Convert a Loop to StepConfig list.

        The loop's inner steps become regular pipeline steps. The loop's
        max/until semantics are encoded as retry config on the last inner step.
        """
        configs = []
        for inner in loop.steps:
            if isinstance(inner, Gate):
                # Gates inside loops are handled by the retry gate mechanism
                continue
            if isinstance(inner, Step):
                sc = self._step_to_step_config(inner, prompts_dir)
                configs.append(sc)
        return configs


# ---------------------------------------------------------------------------
# When expression parser
# ---------------------------------------------------------------------------

_WHEN_RE = re.compile(r"^(\w+)\s*=~\s*/(.+)/$")


def _parse_when(when_str: str) -> tuple[str, str]:
    """Parse ``'step =~ /pattern/'`` into (step_name, regex_pattern)."""
    m = _WHEN_RE.match(when_str.strip())
    if m:
        return m.group(1), m.group(2)
    raise ValueError(f"Invalid when expression: {when_str!r}. Expected: 'step =~ /pattern/'")


# ---------------------------------------------------------------------------
# Config loader — load Pipeline from .langywrap/ralph.py
# ---------------------------------------------------------------------------


def load_pipeline_config(project_dir: Path) -> Pipeline | None:
    """Load a Pipeline from .langywrap/ralph.py if it exists.

    Imports the module and looks for a ``config`` attribute of type Pipeline.
    Returns None if no ralph.py exists.
    """
    ralph_py = project_dir / ".langywrap" / "ralph.py"
    if not ralph_py.exists():
        return None

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f"_ralph_config_{project_dir.name}",
        ralph_py,
    )
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    config = getattr(module, "config", None)
    if isinstance(config, Pipeline):
        return config

    return None
