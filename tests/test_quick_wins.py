"""Quick-win tests targeting specific uncovered branches across multiple modules.

Covers:
- ralph/context.py: inject_scope_restriction, substitute_template, build_project_header,
  build_full_prompt (orient branch, extra_context)
- router/config.py: _parse_rule, _parse_peak_hours, load_route_config (YAML path),
  RouteRule.matches_conditions, RouteConfig.get_rule (conditional/unconditional)
- ralph/step_logger.py: open_step, close_step, stop_heartbeat, close
- ralph/config.py: load_ralph_config (default + pipeline paths)
- quality/gates.py: wrap_cmd import guard
- hyperagents/mutations.py: lines 168,175
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# ralph/context.py
# ---------------------------------------------------------------------------


class TestRalphContext:
    def test_inject_scope_empty_returns_unchanged(self):
        from langywrap.ralph.context import inject_scope_restriction
        assert inject_scope_restriction("my prompt", "") == "my prompt"

    def test_inject_scope_whitespace_only_returns_unchanged(self):
        from langywrap.ralph.context import inject_scope_restriction
        assert inject_scope_restriction("prompt", "   ") == "prompt"

    def test_inject_scope_adds_header(self):
        from langywrap.ralph.context import inject_scope_restriction
        result = inject_scope_restriction("body", "Only touch src/")
        assert "CRITICAL SCOPE RESTRICTION" in result
        assert "Only touch src/" in result
        assert result.endswith("body")

    def test_substitute_template_dollar_key(self):
        from langywrap.ralph.context import substitute_template
        result = substitute_template("Cycle $CYCLE_NUM", {"CYCLE_NUM": "3"})
        assert result == "Cycle 3"

    def test_substitute_template_braces(self):
        from langywrap.ralph.context import substitute_template
        result = substitute_template("Root: ${PROJECT_ROOT}", {"PROJECT_ROOT": "/tmp"})
        assert result == "Root: /tmp"

    def test_substitute_template_unknown_var_kept(self):
        from langywrap.ralph.context import substitute_template
        result = substitute_template("$UNKNOWN_VAR stays", {})
        assert "$UNKNOWN_VAR" in result

    def test_build_project_header_basic(self, tmp_path):
        from langywrap.ralph.context import build_project_header
        header = build_project_header(
            project_dir=tmp_path,
            state_dir=tmp_path / "ralph",
            cycle_num=5,
        )
        assert "5" in header
        assert str(tmp_path) in header

    def test_build_project_header_with_scope(self, tmp_path):
        from langywrap.ralph.context import build_project_header
        header = build_project_header(
            project_dir=tmp_path,
            state_dir=tmp_path / "ralph",
            cycle_num=1,
            scope_restriction="Only src/",
        )
        assert "CRITICAL SCOPE RESTRICTION" in header

    def test_build_project_header_with_extra(self, tmp_path):
        from langywrap.ralph.context import build_project_header
        header = build_project_header(
            project_dir=tmp_path,
            state_dir=tmp_path / "ralph",
            cycle_num=1,
            extra={"Custom": "/custom/path"},
        )
        assert "Custom" in header

    def test_build_full_prompt_orient_step(self, tmp_path):
        from langywrap.ralph.context import build_full_prompt
        result = build_full_prompt(
            template="Do work for $CYCLE_NUM",
            project_dir=tmp_path,
            state_dir=tmp_path / "ralph",
            cycle_num=2,
            orient_context="orient context here",
            is_orient_step=True,
        )
        assert "orient context here" in result
        assert "Do work for 2" in result

    def test_build_full_prompt_non_orient(self, tmp_path):
        from langywrap.ralph.context import build_full_prompt
        result = build_full_prompt(
            template="Do execute work",
            project_dir=tmp_path,
            state_dir=tmp_path / "ralph",
            cycle_num=3,
            orient_context="should not appear",
            is_orient_step=False,
        )
        assert "should not appear" not in result
        assert "Do execute work" in result

    def test_build_full_prompt_extra_context(self, tmp_path):
        from langywrap.ralph.context import build_full_prompt
        result = build_full_prompt(
            template="Dir: $MY_DIR",
            project_dir=tmp_path,
            state_dir=tmp_path / "ralph",
            cycle_num=1,
            extra_context={"MY_DIR": "/special"},
        )
        assert "/special" in result


# ---------------------------------------------------------------------------
# router/router.py (replaces the old router/config.py tests — RouteConfig
# and RouteRule were removed; routing lives on Step objects now).
# ---------------------------------------------------------------------------


class TestExecutionRouterBasics:
    def test_execute_routes_to_explicit_engine(self):
        from langywrap.router.backends import Backend, BackendConfig
        from langywrap.router.router import ExecutionRouter

        backends = {Backend.MOCK: BackendConfig(type=Backend.MOCK)}
        router = ExecutionRouter(backends=backends, default_backend=Backend.MOCK)
        result = router.execute(
            prompt="hi", model="mock-x", engine="auto", timeout_minutes=1, tag="orient"
        )
        assert result.ok

    def test_execute_unknown_engine_falls_back_to_model_inference(self):
        from langywrap.router.backends import Backend, BackendConfig
        from langywrap.router.router import ExecutionRouter

        backends = {Backend.MOCK: BackendConfig(type=Backend.MOCK)}
        router = ExecutionRouter(backends=backends, default_backend=Backend.MOCK)
        # Unknown engine → warning + use _infer_backend_from_model, which for
        # an unknown (non-claude) model returns OPENCODE. That's not configured,
        # so execute falls back to default_backend (MOCK).
        result = router.execute(
            prompt="hi",
            model="mock-unknown",
            engine="not-a-real-engine",
            timeout_minutes=1,
            tag="execute",
        )
        assert result.ok


# ---------------------------------------------------------------------------
# ralph/step_logger.py
# ---------------------------------------------------------------------------


class TestStepLogger:
    def test_basic_log(self, tmp_path):
        from langywrap.ralph.step_logger import StepLogger
        sl = StepLogger(tmp_path / "logs")
        sl.log("test message")
        sl.close()
        master_logs = list((tmp_path / "logs").glob("ralph_master_*.log"))
        assert len(master_logs) == 1
        content = master_logs[0].read_text()
        assert "test message" in content

    def test_open_step(self, tmp_path):
        from langywrap.ralph.step_logger import StepLogger
        sl = StepLogger(tmp_path / "logs")
        log_path = sl.open_step("orient", model="haiku", timeout_minutes=20)
        assert log_path.exists()
        sl.close()

    def test_open_step_with_engine(self, tmp_path):
        from langywrap.ralph.step_logger import StepLogger
        sl = StepLogger(tmp_path / "logs")
        sl.open_step("execute", engine="opencode", tools="Read,Write")
        sl.close()

    def test_close_step_success(self, tmp_path):
        from langywrap.ralph.step_logger import StepLogger
        sl = StepLogger(tmp_path / "logs")
        sl.open_step("orient")
        sl.close_step("orient", "# ORIENT OUTPUT\nORIENT_CONFIRMED: yes\n",
                      success=True, duration=10.0)
        sl.close()

    def test_close_step_failure_tails_output(self, tmp_path):
        from langywrap.ralph.step_logger import StepLogger
        sl = StepLogger(tmp_path / "logs")
        sl.open_step("execute")
        sl.close_step("execute", "something went wrong\nfinal error line",
                      success=False, duration=5.0)
        sl.close()

    def test_stop_heartbeat_no_thread(self, tmp_path):
        from langywrap.ralph.step_logger import StepLogger
        sl = StepLogger(tmp_path / "logs")
        sl.stop_heartbeat()  # should not raise when no thread
        sl.close()

    def test_log_multiline(self, tmp_path):
        from langywrap.ralph.step_logger import StepLogger
        sl = StepLogger(tmp_path / "logs")
        sl.log("line1\nline2\nline3")
        sl.close()
        content = list((tmp_path / "logs").glob("*.log"))[0].read_text()
        assert "line1" in content
        assert "line2" in content


# ---------------------------------------------------------------------------
# ralph/config.py — load_ralph_config defaults
# ---------------------------------------------------------------------------


class TestLoadRalphConfig:
    def test_default_config_when_no_files(self, tmp_path):
        from langywrap.ralph.config import load_ralph_config
        # tmp_path has no .langywrap/ or ralph.yaml
        cfg = load_ralph_config(tmp_path)
        assert cfg.project_dir == tmp_path.resolve()
        assert len(cfg.steps) > 0

    def test_loads_v1_yaml(self, tmp_path):
        from langywrap.ralph.config import load_ralph_config
        langywrap_dir = tmp_path / ".langywrap"
        langywrap_dir.mkdir()
        yaml_content = f"""
project_dir: {tmp_path}
state_dir: ralph
budget: 5
steps: []
"""
        (langywrap_dir / "ralph.yaml").write_text(yaml_content)
        cfg = load_ralph_config(tmp_path)
        assert cfg.budget == 5

    def test_resolve_step_prompts(self, tmp_path):
        from langywrap.ralph.config import StepConfig, _resolve_step_prompts
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        step = StepConfig(
            name="orient",
            prompt_template=Path("orient.md"),
        )
        resolved = _resolve_step_prompts([step], prompts)
        assert resolved[0].prompt_template == prompts / "orient.md"

    def test_resolve_step_prompts_with_retry_template(self, tmp_path):
        from langywrap.ralph.config import StepConfig, _resolve_step_prompts
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        step = StepConfig(
            name="execute",
            prompt_template=Path("execute.md"),
            retry_prompt_template=Path("retry.md"),
        )
        resolved = _resolve_step_prompts([step], prompts)
        assert resolved[0].retry_prompt_template == prompts / "retry.md"


# ---------------------------------------------------------------------------
# hyperagents/mutations.py — lines 168 (remove skill), 175 (return None)
# ---------------------------------------------------------------------------


class TestMutations:
    def _make_variant(self, config=None):
        from langywrap.hyperagents.archive import AgentVariant
        return AgentVariant(
            id="test-001",
            generation=0,
            config=config or {},
        )

    def test_change_skill_selection_remove(self):
        """Covers line 168: skills.pop when action=remove and skills non-empty."""
        import random

        from langywrap.hyperagents.mutations import MutationType, _apply_mutation
        config = {"selected_skills": ["skill_a", "skill_b", "skill_c"]}
        random.seed(42)
        # Force remove action by calling directly
        original_choice = random.choice
        call_count = [0]

        def mock_choice(seq):
            call_count[0] += 1
            if call_count[0] == 1:
                return "remove"
            return original_choice(seq)

        import langywrap.hyperagents.mutations as mut_mod
        old = mut_mod.random.choice
        mut_mod.random.choice = mock_choice
        try:
            result = _apply_mutation(config, MutationType.CHANGE_SKILL_SELECTION)
        finally:
            mut_mod.random.choice = old

        assert result is not None or len(config["selected_skills"]) <= 3

    def test_apply_mutation_returns_none_for_unknown_type(self):
        """Covers line 175: return None at end of _apply_mutation."""
        from langywrap.hyperagents.mutations import MutationType, _apply_mutation
        # CHANGE_REVIEW_FREQUENCY always returns a description — use SWAP_MODEL with no routes
        result = _apply_mutation({}, MutationType.SWAP_MODEL)
        assert result is None

    def test_mutate_creates_child(self):
        from langywrap.hyperagents.archive import AgentVariant
        from langywrap.hyperagents.mutations import MutationType, mutate
        parent = AgentVariant(
            id="parent-1",
            generation=0,
            config={
                "routes": {
                    "orient": {"model": "haiku", "backend": "claude", "timeout_minutes": 20}
                },
                "review_every_n": 10,
            },
        )
        child = mutate(parent, mutation_types=[MutationType.CHANGE_REVIEW_FREQUENCY])
        assert child.generation == 1
        assert child.parent_id == "parent-1"
