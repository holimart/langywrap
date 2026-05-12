"""Tests for ``langywrap.ralph.prompt_audit``.

Covers each rule and confirms the auditor catches the historical ktorobi
failure mode (output_as='plan' + validates_plan, prompt missing the Write
instruction so plan.md stayed stale across cycles).
"""

from __future__ import annotations

from pathlib import Path

from langywrap.ralph.config import (
    QualityGateConfig,
    RalphConfig,
    StepConfig,
)
from langywrap.ralph.prompt_audit import (
    Finding,
    audit_prompt_contracts,
    format_findings,
)

# Fixtures -------------------------------------------------------------------


def _make_step(
    tmp_path: Path,
    name: str,
    prompt_body: str,
    *,
    output_as: str = "",
    validates_plan: bool = False,
    confirmation_token: str = "",
    builtin: str = "",
) -> StepConfig:
    prompt = tmp_path / f"{name}.md"
    prompt.write_text(prompt_body, encoding="utf-8")
    return StepConfig(
        name=name,
        prompt_template=prompt,
        output_as=output_as,
        validates_plan=validates_plan,
        confirmation_token=confirmation_token,
        builtin=builtin,
    )


def _make_cfg(tmp_path: Path, steps: list[StepConfig], **kw: object) -> RalphConfig:
    return RalphConfig(
        project_dir=tmp_path,
        steps=steps,
        quality_gate=QualityGateConfig(command="true"),
        **kw,
    )


# Rule WRITE_PLAN_TARGET -----------------------------------------------------


class TestWritePlanTarget:
    def test_missing_write_instruction_raises_error(self, tmp_path: Path) -> None:
        # The historical ktorobi bug: output_as='plan' + validates_plan but
        # the prompt only asks the agent to emit ``PLAN_CONFIRMED:`` as text.
        step = _make_step(
            tmp_path,
            "plan_profile",
            "End with:\n\nPLAN_CONFIRMED: <one-sentence>",
            output_as="plan",
            validates_plan=True,
        )
        cfg = _make_cfg(tmp_path, [step])
        findings = audit_prompt_contracts(cfg)
        rules = {f.rule for f in findings}
        assert "WRITE_PLAN_TARGET" in rules
        assert any(f.severity == "error" for f in findings if f.rule == "WRITE_PLAN_TARGET")

    def test_explicit_write_passes(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "plan_profile",
            "Write `ralph/plan.md` AND `ralph/steps/plan.md`:\n\nPLAN_CONFIRMED: x",
            output_as="plan",
            validates_plan=True,
            confirmation_token="PLAN_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        findings = audit_prompt_contracts(cfg)
        assert "WRITE_PLAN_TARGET" not in {f.rule for f in findings}

    def test_overwrite_verb_also_passes(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "plan",
            "Overwrite ralph/plan.md with:\nPLAN_CONFIRMED:",
            output_as="plan",
            validates_plan=True,
            confirmation_token="PLAN_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        assert "WRITE_PLAN_TARGET" not in {f.rule for f in audit_prompt_contracts(cfg)}

    def test_read_only_mention_does_not_pass(self, tmp_path: Path) -> None:
        # Just naming the file in passing is not enough.
        step = _make_step(
            tmp_path,
            "plan",
            "ralph/plan.md is canonical. Read `ralph/plan.md` for context.\nPLAN_CONFIRMED:",
            output_as="plan",
            validates_plan=True,
            confirmation_token="PLAN_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "WRITE_PLAN_TARGET" in rules

    def test_non_plan_step_not_audited(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "execute",
            "Implement the plan.\nEXECUTE_CONFIRMED:",
            output_as="execute",
            validates_plan=False,
            confirmation_token="EXECUTE_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        assert "WRITE_PLAN_TARGET" not in {f.rule for f in audit_prompt_contracts(cfg)}


# Rule CONFIRMATION_TOKEN_NOT_IN_PROMPT --------------------------------------


class TestConfirmationToken:
    def test_token_missing_raises_error(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "orient",
            "Look at the repo. Decide cycle type.",
            confirmation_token="ORIENT_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        findings = audit_prompt_contracts(cfg)
        match = [f for f in findings if f.rule == "CONFIRMATION_TOKEN_NOT_IN_PROMPT"]
        assert match
        assert match[0].severity == "error"
        assert "ORIENT_CONFIRMED:" in match[0].detail

    def test_token_present_passes(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "orient",
            "End with: ORIENT_CONFIRMED: <reason>",
            confirmation_token="ORIENT_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "CONFIRMATION_TOKEN_NOT_IN_PROMPT" not in rules

    def test_empty_token_skipped(self, tmp_path: Path) -> None:
        step = _make_step(tmp_path, "fix", "do work", confirmation_token="")
        cfg = _make_cfg(tmp_path, [step])
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "CONFIRMATION_TOKEN_NOT_IN_PROMPT" not in rules


# Rule CYCLE_NUM_REQUIREMENT_MISSING -----------------------------------------


class TestCycleNumRequirement:
    def test_warn_when_directive_absent(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "plan",
            "Write ralph/plan.md.\nPLAN_CONFIRMED:",
            output_as="plan",
            validates_plan=True,
            confirmation_token="PLAN_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step], plan_require_current_cycle=True)
        findings = audit_prompt_contracts(cfg)
        rules = {f.rule for f in findings}
        assert "CYCLE_NUM_REQUIREMENT_MISSING" in rules
        assert all(
            f.severity == "warn"
            for f in findings
            if f.rule == "CYCLE_NUM_REQUIREMENT_MISSING"
        )

    def test_placeholder_passes(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "plan",
            "Write ralph/plan.md. Mention cycle <N>.\nPLAN_CONFIRMED:",
            output_as="plan",
            validates_plan=True,
            confirmation_token="PLAN_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step], plan_require_current_cycle=True)
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "CYCLE_NUM_REQUIREMENT_MISSING" not in rules

    def test_skipped_when_feature_off(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "plan",
            "Write ralph/plan.md.\nPLAN_CONFIRMED:",
            output_as="plan",
            validates_plan=True,
            confirmation_token="PLAN_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step], plan_require_current_cycle=False)
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "CYCLE_NUM_REQUIREMENT_MISSING" not in rules


# Rule PLAN_MUST_CONTAIN_NOT_IN_PROMPT ---------------------------------------


class TestPlanMustContain:
    def test_missing_literal_warns(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "plan",
            "Write ralph/plan.md.\nPLAN_CONFIRMED:",
            output_as="plan",
            validates_plan=True,
            confirmation_token="PLAN_CONFIRMED:",
        )
        cfg = _make_cfg(
            tmp_path,
            [step],
            plan_must_contain=["TASK_TYPE", "ESTIMATED_RUNTIME"],
        )
        findings = audit_prompt_contracts(cfg)
        missing = sorted(
            f.detail for f in findings if f.rule == "PLAN_MUST_CONTAIN_NOT_IN_PROMPT"
        )
        assert len(missing) == 2
        assert any("TASK_TYPE" in d for d in missing)
        assert any("ESTIMATED_RUNTIME" in d for d in missing)


# Rule PROMPT_WRITES_RUNNER_FILE ---------------------------------------------


class TestPromptWritesRunnerFile:
    def test_write_steps_plan_md_flagged(self, tmp_path: Path) -> None:
        # The current ktorobi/whitehacky pattern: prompt tells the agent to
        # Write a ralph/steps/<X>.md path that the runner already owns.
        # Now classified as a fragility warning (the gating "error" lives in
        # the sharper CONFIRMATION_TOKEN_IN_RUNNER_FILE_BLOCK rule).
        step = _make_step(
            tmp_path,
            "plan_profile",
            "Write `ralph/plan.md` AND `ralph/steps/plan.md` with the same content.\nPLAN_CONFIRMED:",
            output_as="plan",
            validates_plan=True,
            confirmation_token="PLAN_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        findings = audit_prompt_contracts(cfg)
        match = [f for f in findings if f.rule == "PROMPT_WRITES_RUNNER_FILE"]
        assert match
        assert match[0].severity == "warn"
        assert "ralph/steps" in match[0].detail or "steps/" in match[0].detail.lower()

    def test_only_state_dir_write_passes(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "plan_profile",
            "Write `ralph/plan.md` with the plan.\nPLAN_CONFIRMED:",
            output_as="plan",
            validates_plan=True,
            confirmation_token="PLAN_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "PROMPT_WRITES_RUNNER_FILE" not in rules

    def test_overwrite_steps_path_also_flagged(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "execute_repro",
            "Overwrite `ralph/steps/execute.md` with results.\nEXECUTE_CONFIRMED:",
            output_as="execute",
            confirmation_token="EXECUTE_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "PROMPT_WRITES_RUNNER_FILE" in rules

    def test_read_only_mention_not_flagged(self, tmp_path: Path) -> None:
        # Prompts often *reference* steps/ paths for reading; those are fine.
        step = _make_step(
            tmp_path,
            "execute_repro",
            "Read `ralph/steps/orient.md` for context. Then act.\nEXECUTE_CONFIRMED:",
            confirmation_token="EXECUTE_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "PROMPT_WRITES_RUNNER_FILE" not in rules


# Rule CONFIRMATION_TOKEN_IN_RUNNER_FILE_BLOCK -------------------------------


class TestConfirmationTokenInRunnerFileBlock:
    """Guards the 2026-05-12 finalize regression: prompt's only home for the
    confirmation token was inside a ``Write ralph/steps/finalize.md:`` block,
    which the runner overwrites with the model's stdout reply. The token
    never reached the runner's grep and three cycles failed in a row."""

    def test_token_only_inside_write_block_errors(self, tmp_path: Path) -> None:
        prompt = (
            "## Output\n"
            "1. Update ralph/tasks.md.\n"
            "2. Write `ralph/steps/finalize.md`:\n"
            "\n"
            "---\n"
            "# Finalize Summary\n"
            "FINALIZE_CONFIRMED: cycle=<N> outcome=<C>\n"
            "---\n"
        )
        step = _make_step(
            tmp_path,
            "finalize",
            prompt,
            confirmation_token="FINALIZE_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        findings = audit_prompt_contracts(cfg)
        match = [
            f for f in findings if f.rule == "CONFIRMATION_TOKEN_IN_RUNNER_FILE_BLOCK"
        ]
        assert match, f"expected gating finding, got {findings}"
        assert match[0].severity == "error"
        assert "FINALIZE_CONFIRMED:" in match[0].detail

    def test_explicit_reply_directive_silences_rule(self, tmp_path: Path) -> None:
        # The shape applied to the post-fix step4_finalize.md: keeps the
        # template block but the directive points at the model's stdout
        # reply rather than a Write of the runner-owned file.
        prompt = (
            "## Output\n"
            "End your reply with the block below (do NOT write it to a file):\n"
            "\n"
            "---\n"
            "FINALIZE_CONFIRMED: cycle=<N>\n"
            "---\n"
        )
        step = _make_step(
            tmp_path,
            "finalize",
            prompt,
            confirmation_token="FINALIZE_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "CONFIRMATION_TOKEN_IN_RUNNER_FILE_BLOCK" not in rules

    def test_reply_directive_via_in_your_response(self, tmp_path: Path) -> None:
        prompt = (
            "Write `ralph/steps/execute.md` with the same content as in your "
            "response, starting with EXECUTE_CONFIRMED:\n"
        )
        step = _make_step(
            tmp_path,
            "execute",
            prompt,
            confirmation_token="EXECUTE_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "CONFIRMATION_TOKEN_IN_RUNNER_FILE_BLOCK" not in rules

    def test_token_appearing_before_write_is_safe(self, tmp_path: Path) -> None:
        # If the prompt references the token in body text (e.g. "must contain
        # PLAN_CONFIRMED:") before any Write directive, the agent has at
        # least one prompt-level anchor outside the clobbered file path.
        prompt = (
            "## Inputs\n"
            "- `ralph/plan.md` (must contain `PLAN_CONFIRMED: ... task_type=...`)\n"
            "\n"
            "## Output\n"
            "Write `ralph/steps/plan.md`:\n"
            "\n"
            "PLAN_CONFIRMED: cycle=<N>\n"
        )
        step = _make_step(
            tmp_path,
            "plan",
            prompt,
            output_as="plan",
            confirmation_token="PLAN_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "CONFIRMATION_TOKEN_IN_RUNNER_FILE_BLOCK" not in rules

    def test_no_write_directive_does_not_fire(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "orient",
            "Decide cycle type. End with ORIENT_CONFIRMED: <reason>",
            confirmation_token="ORIENT_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "CONFIRMATION_TOKEN_IN_RUNNER_FILE_BLOCK" not in rules

    def test_empty_token_skipped(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "fix",
            "Write `ralph/steps/fix.md` with notes.",
            confirmation_token="",
        )
        cfg = _make_cfg(tmp_path, [step])
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "CONFIRMATION_TOKEN_IN_RUNNER_FILE_BLOCK" not in rules


# Cross-config rules ---------------------------------------------------------


class TestOrphanPlanValidatorConfig:
    def test_validator_set_but_no_validates_plan_step_errors(self, tmp_path: Path) -> None:
        # The sportsmarket pattern: plan_require_current_cycle=True at config
        # level, but no step has validates_plan=True. The validator never runs.
        step = _make_step(
            tmp_path,
            "plan",
            "Write `ralph/plan.md` with the plan.\nPLAN_CONFIRMED:",
            output_as="plan",
            validates_plan=False,  # ← the bug
            confirmation_token="PLAN_CONFIRMED:",
        )
        cfg = _make_cfg(
            tmp_path,
            [step],
            plan_require_current_cycle=True,
            plan_must_contain=["## Execution Checklist"],
        )
        findings = audit_prompt_contracts(cfg)
        match = [f for f in findings if f.rule == "ORPHAN_PLAN_VALIDATOR_CONFIG"]
        assert match, f"expected ORPHAN_PLAN_VALIDATOR_CONFIG, got {findings}"
        assert match[0].severity == "error"
        # Detail mentions every dead setting:
        assert "plan_require_current_cycle" in match[0].detail
        assert "Execution Checklist" in match[0].detail

    def test_at_least_one_validates_plan_step_silences_rule(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "plan",
            "Write `ralph/plan.md` with cycle <N>.\nPLAN_CONFIRMED:",
            output_as="plan",
            validates_plan=True,
            confirmation_token="PLAN_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step], plan_require_current_cycle=True)
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "ORPHAN_PLAN_VALIDATOR_CONFIG" not in rules

    def test_no_plan_config_silences_rule(self, tmp_path: Path) -> None:
        # No plan validators configured at all → rule does not fire even if
        # no step has validates_plan.
        step = _make_step(
            tmp_path,
            "execute",
            "Do work.\nEXECUTE_CONFIRMED:",
            confirmation_token="EXECUTE_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "ORPHAN_PLAN_VALIDATOR_CONFIG" not in rules


class TestOutputPlanWithoutValidatesPlan:
    def test_warns_when_plan_written_but_not_validated(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "plan",
            "Write `ralph/plan.md`.\nPLAN_CONFIRMED:",
            output_as="plan",
            validates_plan=False,
            confirmation_token="PLAN_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        findings = audit_prompt_contracts(cfg)
        match = [f for f in findings if f.rule == "OUTPUT_PLAN_WITHOUT_VALIDATES_PLAN"]
        assert match
        assert match[0].severity == "warn"

    def test_passes_when_validates_plan_true(self, tmp_path: Path) -> None:
        step = _make_step(
            tmp_path,
            "plan",
            "Write `ralph/plan.md` with cycle <N>.\nPLAN_CONFIRMED:",
            output_as="plan",
            validates_plan=True,
            confirmation_token="PLAN_CONFIRMED:",
        )
        cfg = _make_cfg(tmp_path, [step])
        rules = {f.rule for f in audit_prompt_contracts(cfg)}
        assert "OUTPUT_PLAN_WITHOUT_VALIDATES_PLAN" not in rules


# Format helper --------------------------------------------------------------


class TestFormatFindings:
    def test_empty_returns_ok(self) -> None:
        out = format_findings([])
        assert "OK" in out
        # The "deeper audit" pointer should NOT appear when everything is fine.
        assert "/ralph-prompt-audit" not in out

    def test_groups_errors_before_warnings(self) -> None:
        findings = [
            Finding(step="a", severity="warn", rule="W", detail="warn1"),
            Finding(step="b", severity="error", rule="E", detail="err1"),
        ]
        out = format_findings(findings)
        assert out.index("[ERROR]") < out.index("[WARN]")

    def test_points_at_skill_when_findings_exist(self) -> None:
        findings = [Finding(step="x", severity="warn", rule="R", detail="d")]
        out = format_findings(findings)
        # The skill pointer must be there so operators discover the LLM-level
        # audit even on warn-only output.
        assert "/ralph-prompt-audit" in out
        assert "claude" in out or "opencode" in out
