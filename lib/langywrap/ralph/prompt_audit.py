"""Static audit of step prompts against their pipeline contract.

Catches ``ralph.py`` ↔ prompt mismatches at preflight time so a misconfigured
loop does not silently pass validation by accident (as happened with ktorobi
plan validation: prompts emitted ``PLAN_CONFIRMED`` as text but never wrote
``ralph/plan.md``, so the validator kept reading a stale plan).

Each rule below is *static* — it inspects only the loaded RalphConfig and the
prompt-template files on disk. No LLM, no router, no sandbox runs.

Findings are returned, not raised; callers (e.g. ``dry_run``) decide how to
surface them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from langywrap.ralph.config import RalphConfig, StepConfig


Severity = Literal["error", "warn"]


@dataclass(frozen=True)
class Finding:
    """One contract violation between a step's config and its prompt."""

    step: str
    severity: Severity
    rule: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "step": self.step,
            "severity": self.severity,
            "rule": self.rule,
            "detail": self.detail,
        }


# Static set of paths the runner writes itself.  Any prompt that tells the
# agent to Write/Overwrite one of these collides with the runner's response-
# write to ``steps/<step.name>.md`` and is the wart that motivated this rule.
_RUNNER_OWNED_STEPS_PATH_RE = re.compile(
    r"""(?ix)
    (?: write | overwrite | update | save | emit | tee )
    [^\n]{0,40}? `? ralph/ steps/ [a-z_]+ \. md `?
    """,
    re.VERBOSE,
)


# Regex helpers --------------------------------------------------------------

# Matches a write/overwrite verb adjacent to a `plan.md` reference.  Accepts:
#   "Write `ralph/plan.md`", "Overwrite ralph/plan.md", "save plan.md",
#   "Update `ralph/plan.md`", "tee > ralph/plan.md".
_PLAN_WRITE_RE = re.compile(
    r"""(?ix)
    (?: write | overwrite | update | save | emit | output | tee )
    [^\n]{0,40}? `? (?: ralph/ )? plan \. md `?
    """,
    re.VERBOSE,
)

# Matches a cycle-number requirement in plan prompts.  Accepts a placeholder
# (``cycle <N>``, ``cycle {N}``, ``cycle {CYCLE_NUM}``, ``cycle=<N>``) or a
# literal directive that names the requirement.
_CYCLE_NUM_RE = re.compile(
    r"""(?ix)
    cycle [\s_=]* [<{(] [^>}\n)]{1,16} [>})]
    | cycle\s+number
    | current\s+cycle
    | \{cycle_?num\}
    """,
    re.VERBOSE,
)


def _read_prompt(step: "StepConfig") -> str:
    if step.builtin:
        return ""
    p = step.prompt_template
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


# Rules ----------------------------------------------------------------------


def _rule_write_plan_target(
    step: "StepConfig", prompt: str, _cfg: "RalphConfig"
) -> list[Finding]:
    """`output_as="plan"` + `validates_plan` ⇒ prompt must instruct an explicit
    Write of ``ralph/plan.md``.

    The runner intentionally does not mirror the response into ``plan.md``;
    the validator reads ``state_dir/plan.md`` which only changes when the
    agent writes the file itself.  Without that instruction the validator
    sees a stale plan from a prior cycle and either fails (correctly) or
    passes (by coincidence) on substring matches in legacy state.
    """
    if step.builtin or step.output_as != "plan" or not step.validates_plan:
        return []
    if _PLAN_WRITE_RE.search(prompt):
        return []
    return [
        Finding(
            step=step.name,
            severity="error",
            rule="WRITE_PLAN_TARGET",
            detail=(
                "Step has output_as='plan' + validates_plan=True, but its prompt "
                "does not instruct the agent to Write `ralph/plan.md`. The runner "
                "does NOT mirror the response into plan.md, so validates_plan will "
                "read a stale plan from a prior cycle. Add a 'Write `ralph/plan.md` "
                "AND `ralph/steps/plan.md`' section to the prompt."
            ),
        )
    ]


def _rule_confirmation_token_in_prompt(
    step: "StepConfig", prompt: str, _cfg: "RalphConfig"
) -> list[Finding]:
    """If a step expects a confirmation token, the prompt must mention it
    verbatim so the agent emits it."""
    token = step.confirmation_token
    if not token or step.builtin:
        return []
    if token in prompt:
        return []
    return [
        Finding(
            step=step.name,
            severity="error",
            rule="CONFIRMATION_TOKEN_NOT_IN_PROMPT",
            detail=(
                f"Step expects confirmation_token={token!r} but the prompt does not "
                f"contain that literal string. The agent has no signal to emit it, "
                f"so the cycle will be classified as 'token NOT FOUND'."
            ),
        )
    ]


def _rule_cycle_num_requirement(
    step: "StepConfig", prompt: str, cfg: "RalphConfig"
) -> list[Finding]:
    """If RalphConfig.plan_require_current_cycle, the validating prompt must
    tell the agent to mention the current cycle number."""
    if not cfg.plan_require_current_cycle or not step.validates_plan or step.builtin:
        return []
    if _CYCLE_NUM_RE.search(prompt):
        return []
    return [
        Finding(
            step=step.name,
            severity="warn",
            rule="CYCLE_NUM_REQUIREMENT_MISSING",
            detail=(
                "RalphConfig.plan_require_current_cycle=True but the prompt has no "
                "directive about including the current cycle number (looked for "
                "'cycle <N>', 'cycle {N}', 'current cycle', etc.). Validation will "
                "fail every cycle on first attempt unless the agent guesses to "
                "include it."
            ),
        )
    ]


def _rule_plan_must_contain_in_prompt(
    step: "StepConfig", prompt: str, cfg: "RalphConfig"
) -> list[Finding]:
    """Every literal in plan_must_contain should appear in the validating
    prompt — otherwise the agent has no idea those strings are required."""
    if not step.validates_plan or step.builtin:
        return []
    findings: list[Finding] = []
    for needle in cfg.plan_must_contain:
        if needle and needle not in prompt:
            findings.append(
                Finding(
                    step=step.name,
                    severity="warn",
                    rule="PLAN_MUST_CONTAIN_NOT_IN_PROMPT",
                    detail=(
                        f"plan_must_contain literal {needle!r} is required by the "
                        f"validator but is not mentioned in this prompt."
                    ),
                )
            )
    return findings


def _rule_cycle_type_labels_in_source_prompt(
    step: "StepConfig", prompt: str, cfg: "RalphConfig"
) -> list[Finding]:
    """The step that drives cycle-type detection (cycle_type_source) must
    have a prompt that mentions the labels it is expected to emit.

    Two rule shapes are supported (see ``RalphConfig.cycle_type_rules``):
    ``{"name", "pattern"}`` for regex match, or
    ``{"field", "allowed", "default"}`` for explicit field decision. For the
    second shape, the user-facing labels are the ``|``-separated alternatives
    in ``allowed`` rather than the synthetic ``name``.
    """
    if step.builtin or step.name != cfg.cycle_type_source:
        return []
    findings: list[Finding] = []
    for rule in cfg.cycle_type_rules:
        labels: list[str] = []
        if rule.get("field"):
            labels = [a for a in rule.get("allowed", "").split("|") if a]
        else:
            name = rule.get("name") or ""
            # Skip synthetic markers like __plan_decision__.
            if name and not (name.startswith("__") and name.endswith("__")):
                labels = [name]
        for label in labels:
            if label not in prompt:
                findings.append(
                    Finding(
                        step=step.name,
                        severity="warn",
                        rule="CYCLE_TYPE_LABEL_NOT_IN_SOURCE_PROMPT",
                        detail=(
                            f"cycle_type_source={step.name!r} drives detection "
                            f"but the label {label!r} (from cycle_type_rules) is "
                            f"never mentioned in its prompt — the model has "
                            f"nothing to anchor on."
                        ),
                    )
                )
    return findings


def _rule_prompt_writes_runner_file(
    step: "StepConfig", prompt: str, _cfg: "RalphConfig"
) -> list[Finding]:
    """Prompt tells the agent to Write a ``ralph/steps/<X>.md`` path that the
    runner already writes from the model's text response. Two writers, one
    file → last write wins → silent divergence from intent."""
    if step.builtin:
        return []
    findings: list[Finding] = []
    for m in _RUNNER_OWNED_STEPS_PATH_RE.finditer(prompt):
        snippet = m.group(0).strip()
        findings.append(
            Finding(
                step=step.name,
                severity="error",
                rule="PROMPT_WRITES_RUNNER_FILE",
                detail=(
                    f"Prompt instruction {snippet!r} targets a file under "
                    f"ralph/steps/, but the runner already writes "
                    f"ralph/steps/{step.name}.md from this step's text "
                    f"response. The agent's Write will be clobbered (or "
                    f"itself clobber the runner-written debug log, depending "
                    f"on order). Drop the Write directive and let the "
                    f"response itself be the per-step debug log; for "
                    f"canonical state files, target ralph/<file>.md instead."
                ),
            )
        )
    return findings


_RULES = [
    _rule_write_plan_target,
    _rule_confirmation_token_in_prompt,
    _rule_cycle_num_requirement,
    _rule_plan_must_contain_in_prompt,
    _rule_cycle_type_labels_in_source_prompt,
    _rule_prompt_writes_runner_file,
]


# Cross-step (whole-config) rules --------------------------------------------


def _rule_orphan_plan_validator_config(cfg: "RalphConfig") -> list[Finding]:
    """``plan_must_contain`` / ``plan_must_match`` / ``plan_require_current_cycle``
    only fire when at least one step has ``validates_plan=True``. If any of those
    fields are set but no step opts in, the validator never runs — silent
    misconfiguration (sportsmarket-style)."""
    has_validator_step = any(
        step.validates_plan and not step.builtin for step in cfg.steps
    )
    if has_validator_step:
        return []
    configured: list[str] = []
    if cfg.plan_must_contain:
        configured.append(f"plan_must_contain={cfg.plan_must_contain!r}")
    if cfg.plan_must_match:
        configured.append(f"plan_must_match={cfg.plan_must_match!r}")
    if cfg.plan_require_current_cycle:
        configured.append("plan_require_current_cycle=True")
    if not configured:
        return []
    return [
        Finding(
            step="<config>",
            severity="error",
            rule="ORPHAN_PLAN_VALIDATOR_CONFIG",
            detail=(
                "RalphConfig has plan-validator settings ("
                + ", ".join(configured)
                + ") but no step has validates_plan=True. The validator never "
                "runs, so these settings are dead — either mark the plan step "
                "with validates_plan=True or remove the plan_* config."
            ),
        )
    ]


def _rule_orphan_plan_output(cfg: "RalphConfig") -> list[Finding]:
    """A step writing ``output_as='plan'`` without ``validates_plan=True`` is
    suspicious: it produces the canonical plan but no validation gates the
    next step. Warn so the operator confirms it's intentional."""
    findings: list[Finding] = []
    for step in cfg.steps:
        if step.builtin or step.output_as != "plan":
            continue
        if step.validates_plan:
            continue
        findings.append(
            Finding(
                step=step.name,
                severity="warn",
                rule="OUTPUT_PLAN_WITHOUT_VALIDATES_PLAN",
                detail=(
                    "Step has output_as='plan' but validates_plan=False, so "
                    "no plan_must_contain / plan_must_match / "
                    "plan_require_current_cycle check runs after it. "
                    "Set validates_plan=True if you want the plan-content "
                    "validator to gate the next step."
                ),
            )
        )
    return findings


_CONFIG_RULES = [
    _rule_orphan_plan_validator_config,
    _rule_orphan_plan_output,
]


# Public entry point ---------------------------------------------------------


def audit_prompt_contracts(cfg: "RalphConfig") -> list[Finding]:
    """Run every static prompt-vs-config rule across all steps in ``cfg``."""
    findings: list[Finding] = []
    for step in cfg.steps:
        prompt = _read_prompt(step)
        for rule in _RULES:
            findings.extend(rule(step, prompt, cfg))
    for cfg_rule in _CONFIG_RULES:
        findings.extend(cfg_rule(cfg))
    return findings


def format_findings(findings: list[Finding]) -> str:
    """Render findings for human-readable preflight output."""
    if not findings:
        return "  [prompt audit] OK — all prompts match their step contracts.\n"
    errors = [f for f in findings if f.severity == "error"]
    warns = [f for f in findings if f.severity == "warn"]
    lines = [f"  [prompt audit] {len(errors)} error(s), {len(warns)} warning(s):"]
    for f in errors + warns:
        lines.append(
            f"    [{f.severity.upper()}] {f.step} — {f.rule}\n      {f.detail}"
        )
    lines.append("")
    return "\n".join(lines)
