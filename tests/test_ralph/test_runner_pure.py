"""Tests for pure/static methods of langywrap.ralph.runner.RalphLoop.

Focuses on logic that doesn't require real AI backends or subprocess calls:
- Static helpers: _is_failed_cycle, _check_token, _check_depends_on
- Instance helpers: _find_step, detect_stagnation, _extract_plan_summary
- _plan_validation_enabled, _validate_plan, _detect_cycle_type
- _should_trigger_adversarial_milestone
- dry_run (stub mode — no router)
- run() guard: existing state + resume=False raises
- run_step() with router=None (stub mode)
- _print_review, _log_cycle_stats, _log_run_stats (smoke)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langywrap.ralph.config import RalphConfig, StepConfig
from langywrap.ralph.runner import RalphLoop
from langywrap.ralph.state import CycleResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, **kwargs) -> RalphConfig:
    """Minimal valid RalphConfig pointing at tmp_path."""
    state_dir = tmp_path / "ralph"
    state_dir.mkdir(parents=True, exist_ok=True)
    prompts = state_dir / "prompts"
    prompts.mkdir(exist_ok=True)

    template = prompts / "orient.md"
    template.write_text("# orient\nDo orient work.\n")

    step = StepConfig(
        name="orient",
        prompt_template=template,
        confirmation_token="ORIENT_CONFIRMED:",
        includes_orient_context=True,
    )
    return RalphConfig(
        project_dir=tmp_path,
        state_dir=state_dir,
        steps=[step],
        **kwargs,
    )


def _make_loop(tmp_path: Path, **kwargs) -> RalphLoop:
    cfg = _make_config(tmp_path, **kwargs)
    return RalphLoop(cfg, router=None)


def _make_result(**kwargs) -> CycleResult:
    defaults = {"cycle_number": 1}
    defaults.update(kwargs)
    return CycleResult(**defaults)


# ---------------------------------------------------------------------------
# _is_failed_cycle (static)
# ---------------------------------------------------------------------------


class TestIsFailedCycle:
    def test_qg_failed_is_failed(self):
        r = _make_result(quality_gate_passed=False)
        assert RalphLoop._is_failed_cycle(r) is True

    def test_qg_passed_fully_confirmed_is_not_failed(self):
        r = _make_result(quality_gate_passed=True, confirmed_tokens={"orient": True})
        assert RalphLoop._is_failed_cycle(r) is False

    def test_qg_none_fully_confirmed_is_not_failed(self):
        r = _make_result(quality_gate_passed=None, confirmed_tokens={"orient": True})
        assert RalphLoop._is_failed_cycle(r) is False

    def test_not_fully_confirmed_is_failed(self):
        r = _make_result(quality_gate_passed=None, confirmed_tokens={"orient": False})
        assert RalphLoop._is_failed_cycle(r) is True

    def test_empty_confirmed_tokens_is_failed(self):
        r = _make_result()
        # no confirmed_tokens → fully_confirmed is False
        assert RalphLoop._is_failed_cycle(r) is True


# ---------------------------------------------------------------------------
# _check_token (static)
# ---------------------------------------------------------------------------


class TestCheckToken:
    def test_empty_token_always_true(self):
        assert RalphLoop._check_token("anything", "") is True

    def test_token_present(self):
        assert RalphLoop._check_token("ORIENT_CONFIRMED: done", "ORIENT_CONFIRMED:") is True

    def test_token_absent(self):
        assert RalphLoop._check_token("nope", "ORIENT_CONFIRMED:") is False


# ---------------------------------------------------------------------------
# _check_depends_on
# ---------------------------------------------------------------------------


class TestCheckDependsOn:
    def setup_method(self, _):
        self._loop = None  # populated per test

    def _loop_for(self, tmp_path):
        return _make_loop(tmp_path)

    def test_no_depends_on_returns_empty(self, tmp_path):
        loop = self._loop_for(tmp_path)
        step = loop.config.steps[0]
        missing = loop._check_depends_on(step, {})
        assert missing == []

    def test_missing_dependency_returned(self, tmp_path):
        loop = self._loop_for(tmp_path)
        step = loop.config.steps[0]
        step = step.model_copy(update={"depends_on": ["PLAN_CONFIRMED:"]})
        missing = loop._check_depends_on(step, {"orient": "some output without token"})
        assert "PLAN_CONFIRMED:" in missing

    def test_present_dependency_not_missing(self, tmp_path):
        loop = self._loop_for(tmp_path)
        step = loop.config.steps[0]
        step = step.model_copy(update={"depends_on": ["PLAN_CONFIRMED:"]})
        missing = loop._check_depends_on(step, {"plan": "PLAN_CONFIRMED: yes"})
        assert missing == []


# ---------------------------------------------------------------------------
# _find_step
# ---------------------------------------------------------------------------


class TestFindStep:
    def test_found(self, tmp_path):
        loop = _make_loop(tmp_path)
        found = loop._find_step("orient")
        assert found is not None
        assert found.name == "orient"

    def test_not_found(self, tmp_path):
        loop = _make_loop(tmp_path)
        assert loop._find_step("nonexistent") is None


# ---------------------------------------------------------------------------
# detect_stagnation
# ---------------------------------------------------------------------------


class TestDetectStagnation:
    def test_no_progress_file_returns_false(self, tmp_path):
        loop = _make_loop(tmp_path)
        assert loop.detect_stagnation() is False

    def test_fewer_than_n_outcomes_returns_false(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.state.progress_file.parent.mkdir(parents=True, exist_ok=True)
        loop.state.progress_file.write_text("Outcome: success\nOutcome: success\n")
        assert loop.detect_stagnation(n_cycles=4) is False

    def test_all_same_outcome_returns_true(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.state.progress_file.parent.mkdir(parents=True, exist_ok=True)
        loop.state.progress_file.write_text(
            "Outcome: failed\nOutcome: failed\nOutcome: failed\nOutcome: failed\n"
        )
        assert loop.detect_stagnation(n_cycles=4) is True

    def test_mixed_outcomes_returns_false(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.state.progress_file.parent.mkdir(parents=True, exist_ok=True)
        loop.state.progress_file.write_text(
            "Outcome: success\nOutcome: failed\nOutcome: success\nOutcome: success\n"
        )
        assert loop.detect_stagnation(n_cycles=4) is False


# ---------------------------------------------------------------------------
# _extract_plan_summary
# ---------------------------------------------------------------------------


class TestExtractPlanSummary:
    def test_empty_plan_returns_empty(self, tmp_path):
        loop = _make_loop(tmp_path)
        # plan_file doesn't exist yet
        assert loop._extract_plan_summary() == ""

    def test_returns_first_non_header_line(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.state.plan_file.write_text("# Heading\n\nActual summary text here\n")
        result = loop._extract_plan_summary()
        assert result == "Actual summary text here"

    def test_truncates_at_72_chars(self, tmp_path):
        loop = _make_loop(tmp_path)
        long_line = "A" * 100
        loop.state.plan_file.write_text(long_line + "\n")
        result = loop._extract_plan_summary()
        assert len(result) == 72


# ---------------------------------------------------------------------------
# _plan_validation_enabled
# ---------------------------------------------------------------------------


class TestPlanValidationEnabled:
    def test_disabled_by_default(self, tmp_path):
        loop = _make_loop(tmp_path)
        assert loop._plan_validation_enabled() is False

    def test_enabled_by_must_contain(self, tmp_path):
        loop = _make_loop(tmp_path, plan_must_contain=["cycle"])
        assert loop._plan_validation_enabled() is True

    def test_enabled_by_must_match(self, tmp_path):
        loop = _make_loop(tmp_path, plan_must_match=["cycle \\d+"])
        assert loop._plan_validation_enabled() is True

    def test_enabled_by_require_current_cycle(self, tmp_path):
        loop = _make_loop(tmp_path, plan_require_current_cycle=True)
        assert loop._plan_validation_enabled() is True


# ---------------------------------------------------------------------------
# _validate_plan
# ---------------------------------------------------------------------------


class TestValidatePlan:
    def test_empty_plan_fails(self, tmp_path):
        loop = _make_loop(tmp_path)
        ok, msg = loop._validate_plan(1)
        assert ok is False
        assert "missing or empty" in msg

    def test_must_contain_passes(self, tmp_path):
        loop = _make_loop(tmp_path, plan_must_contain=["TASK-001"])
        loop.state.plan_file.write_text("# Plan\nTASK-001 implement feature\n")
        ok, msg = loop._validate_plan(1)
        assert ok is True
        assert msg == ""

    def test_must_contain_fails(self, tmp_path):
        loop = _make_loop(tmp_path, plan_must_contain=["MUST_HAVE"])
        loop.state.plan_file.write_text("# Plan\nno required token here\n")
        ok, msg = loop._validate_plan(1)
        assert ok is False
        assert "MUST_HAVE" in msg

    def test_must_match_regex_passes(self, tmp_path):
        loop = _make_loop(tmp_path, plan_must_match=["task-\\d+"])
        loop.state.plan_file.write_text("Focus: task-42\n")
        ok, msg = loop._validate_plan(1)
        assert ok is True

    def test_must_match_regex_fails(self, tmp_path):
        loop = _make_loop(tmp_path, plan_must_match=["task-\\d+"])
        loop.state.plan_file.write_text("No task references.\n")
        ok, msg = loop._validate_plan(1)
        assert ok is False

    def test_require_current_cycle_passes(self, tmp_path):
        loop = _make_loop(tmp_path, plan_require_current_cycle=True)
        loop.state.plan_file.write_text("This is plan for cycle 5.\n")
        ok, msg = loop._validate_plan(5)
        assert ok is True

    def test_require_current_cycle_fails(self, tmp_path):
        loop = _make_loop(tmp_path, plan_require_current_cycle=True)
        loop.state.plan_file.write_text("This is plan for cycle 3.\n")
        ok, msg = loop._validate_plan(5)
        assert ok is False
        assert "cycle 5" in msg


# ---------------------------------------------------------------------------
# _detect_cycle_type
# ---------------------------------------------------------------------------


class TestDetectCycleType:
    def test_no_rules_returns_empty(self, tmp_path):
        loop = _make_loop(tmp_path)
        assert loop._detect_cycle_type() == ""

    def test_no_plan_returns_empty(self, tmp_path):
        loop = _make_loop(
            tmp_path,
            cycle_type_rules=[{"name": "lean", "pattern": "sorry"}],
        )
        assert loop._detect_cycle_type() == ""

    def test_matching_rule(self, tmp_path):
        loop = _make_loop(
            tmp_path,
            cycle_type_rules=[{"name": "lean", "pattern": "sorry.*fill"}],
        )
        loop.state.plan_file.write_text("Goal: sorry fill all the gaps\n")
        assert loop._detect_cycle_type() == "lean"

    def test_last_match_wins(self, tmp_path):
        loop = _make_loop(
            tmp_path,
            cycle_type_rules=[
                {"name": "research", "pattern": "research"},
                {"name": "lean", "pattern": "sorry"},
            ],
        )
        loop.state.plan_file.write_text("Do research with sorry fill\n")
        assert loop._detect_cycle_type() == "lean"

    def test_no_match_returns_empty(self, tmp_path):
        loop = _make_loop(
            tmp_path,
            cycle_type_rules=[{"name": "lean", "pattern": "sorry"}],
        )
        loop.state.plan_file.write_text("Nothing matches here.\n")
        assert loop._detect_cycle_type() == ""


# ---------------------------------------------------------------------------
# _should_trigger_adversarial_milestone
# ---------------------------------------------------------------------------


class TestAdversarialMilestone:
    def test_no_patterns_returns_false(self, tmp_path):
        loop = _make_loop(tmp_path)
        assert loop._should_trigger_adversarial_milestone({"execute": "axiom added"}) is False

    def test_no_execute_output_returns_false(self, tmp_path):
        loop = _make_loop(tmp_path, adversarial_milestone_patterns=["axiom.*added"])
        assert loop._should_trigger_adversarial_milestone({}) is False

    def test_matching_pattern(self, tmp_path):
        loop = _make_loop(
            tmp_path,
            adversarial_milestone_patterns=["axiom.*added"],
        )
        assert loop._should_trigger_adversarial_milestone({"execute": "axiom was added!"}) is True

    def test_non_matching_pattern(self, tmp_path):
        loop = _make_loop(
            tmp_path,
            adversarial_milestone_patterns=["sorry.*filled"],
        )
        assert loop._should_trigger_adversarial_milestone({"execute": "no match here"}) is False


# ---------------------------------------------------------------------------
# run() guard: existing state raises without resume=True
# ---------------------------------------------------------------------------


class TestRunGuard:
    def test_existing_state_raises_without_resume(self, tmp_path):
        loop = _make_loop(tmp_path)
        # Simulate prior cycles
        loop.state.set_cycle_count(2)

        with pytest.raises(RuntimeError, match="resume=True"):
            loop.run(budget=1)

    def test_existing_state_continues_with_resume(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.state.set_cycle_count(1)
        # tasks.md has no pending tasks → loop exits immediately
        loop.state.tasks_file.write_text("")  # no pending tasks

        results = loop.run(budget=1, resume=True)
        # Should exit immediately (no pending tasks) without raising
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# run_step() in stub mode (router=None)
# ---------------------------------------------------------------------------


class TestRunStepStub:
    def test_stub_mode_returns_success(self, tmp_path):
        loop = _make_loop(tmp_path)
        step = loop.config.steps[0]
        ctx = {
            "cycle_num": 1,
            "orient_context": "",
            "confirmed_outputs": {},
            "cycle_type": "",
            "cycle_prompt_extra": "",
        }
        output, success, sr = loop.run_step(step, ctx)
        assert success is True
        assert sr is None
        assert "STUB" in output or step.name.upper() in output

    def test_stub_mode_no_template_raises(self, tmp_path):
        loop = _make_loop(tmp_path)
        step = loop.config.steps[0]
        step = step.model_copy(update={"prompt_template": tmp_path / "nonexistent.md"})
        ctx = {
            "cycle_num": 1,
            "orient_context": "",
            "confirmed_outputs": {},
            "cycle_type": "",
            "cycle_prompt_extra": "",
        }
        # In stub mode router is None so build_prompt is called
        with pytest.raises(FileNotFoundError):
            loop.run_step(step, ctx)


# ---------------------------------------------------------------------------
# dry_run() — stub mode
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_returns_dict_with_keys(self, tmp_path):
        loop = _make_loop(tmp_path)
        result = loop.dry_run()
        assert "project_dir" in result
        assert "state_dir" in result
        assert "steps" in result
        assert "router" in result
        assert result["router"] == "None (stub mode)"

    def test_includes_step_info(self, tmp_path):
        loop = _make_loop(tmp_path)
        result = loop.dry_run()
        assert len(result["steps"]) == 1
        assert result["steps"][0]["name"] == "orient"

    def test_quality_gate_none(self, tmp_path):
        loop = _make_loop(tmp_path)
        result = loop.dry_run()
        assert result["quality_gate"] is None


# ---------------------------------------------------------------------------
# _print_review, _log_cycle_stats, _log_run_stats — smoke tests
# ---------------------------------------------------------------------------


class TestLoggingMethods:
    def test_print_review_smoke(self, tmp_path):
        loop = _make_loop(tmp_path)
        r1 = _make_result(confirmed_tokens={"orient": True}, quality_gate_passed=True)
        r1.git_commit_hash = "abc1234"
        r2 = _make_result(cycle_number=2)
        loop._print_review([r1, r2])  # should not raise

    def test_log_cycle_stats_no_data(self, tmp_path):
        loop = _make_loop(tmp_path)
        r = _make_result()
        loop._log_cycle_stats(r)  # should not raise

    def test_log_cycle_stats_with_tokens(self, tmp_path):
        loop = _make_loop(tmp_path)
        r = _make_result(
            tokens_by_model={"claude-haiku": (1000, 500)},
            input_tokens=1000,
            output_tokens=500,
        )
        r.files_accessed = {"orient": ["/tmp/foo.py"]}
        loop._log_cycle_stats(r)  # should not raise

    def test_log_run_stats_empty(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._log_run_stats([])  # should not raise

    def test_log_run_stats_with_results(self, tmp_path):
        loop = _make_loop(tmp_path)
        r = _make_result(
            tokens_by_model={"kimi-k2": (2000, 300)},
            input_tokens=2000,
            output_tokens=300,
        )
        r.files_accessed = {"execute": ["/src/foo.lean"]}
        loop._log_run_stats([r])  # should not raise
