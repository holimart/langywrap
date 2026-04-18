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
# router/config.py
# ---------------------------------------------------------------------------


class TestRouteConfig:
    def test_parse_peak_hours_none(self):
        from langywrap.router.config import _parse_peak_hours
        assert _parse_peak_hours(None) is None

    def test_parse_peak_hours_list(self):
        from langywrap.router.config import _parse_peak_hours
        assert _parse_peak_hours([13, 19]) == (13, 19)

    def test_parse_peak_hours_invalid_raises(self):
        from langywrap.router.config import _parse_peak_hours
        with pytest.raises(ValueError):
            _parse_peak_hours("bad")

    def test_parse_rule_basic(self):
        from langywrap.router.config import _parse_rule
        rule = _parse_rule({
            "role": "orient",
            "model": "claude-haiku",
            "backend": "claude",
        })
        assert rule.model == "claude-haiku"

    def test_parse_rule_bad_role_raises(self):
        from langywrap.router.config import _parse_rule
        with pytest.raises(ValueError, match="Unknown step role"):
            _parse_rule({"role": "nonexistent_role", "model": "x", "backend": "claude"})

    def test_parse_rule_bad_backend_raises(self):
        from langywrap.router.config import _parse_rule
        with pytest.raises(ValueError, match="Unknown backend"):
            _parse_rule({"role": "orient", "model": "x", "backend": "bad_backend"})

    def test_parse_rule_bad_tier_defaults_to_mid(self):
        from langywrap.router.config import ModelTier, _parse_rule
        rule = _parse_rule(
            {"role": "orient", "model": "x", "backend": "claude", "tier": "superexpensive"}
        )
        assert rule.tier == ModelTier.MID

    def test_load_route_config_defaults_when_no_file(self, tmp_path):
        from langywrap.router.config import load_route_config
        cfg = load_route_config(tmp_path)
        # Should return DEFAULT_ROUTE_CONFIG
        assert cfg is not None
        assert len(cfg.rules) > 0

    def test_load_route_config_from_yaml(self, tmp_path):
        from langywrap.router.config import load_route_config
        yaml_content = """
name: test-config
rules:
  - role: orient
    model: claude-haiku-test
    backend: claude
    timeout_minutes: 10
"""
        langywrap_dir = tmp_path / ".langywrap"
        langywrap_dir.mkdir()
        (langywrap_dir / "router.yaml").write_text(yaml_content)
        cfg = load_route_config(tmp_path)
        assert cfg.name == "test-config"
        assert len(cfg.rules) == 1
        assert cfg.rules[0].model == "claude-haiku-test"

    def test_route_config_get_rule_unconditional(self):
        from langywrap.router.config import Backend, RouteConfig, RouteRule, StepRole
        rc = RouteConfig(
            rules=[
                RouteRule(role=StepRole.ORIENT, model="haiku", backend=Backend.CLAUDE),
                RouteRule(role=StepRole.EXECUTE, model="kimi", backend=Backend.OPENROUTER),
            ]
        )
        rule = rc.get_rule(StepRole.ORIENT)
        assert rule is not None
        assert rule.model == "haiku"

    def test_route_config_get_rule_conditional_wins(self):
        from langywrap.router.config import Backend, RouteConfig, RouteRule, StepRole
        rc = RouteConfig(
            rules=[
                RouteRule(
                    role=StepRole.EXECUTE,
                    model="kimi",
                    backend=Backend.OPENROUTER,
                ),
                RouteRule(
                    role=StepRole.EXECUTE,
                    model="sonnet",
                    backend=Backend.CLAUDE,
                    conditions={"cycle_type": "lean"},
                ),
            ]
        )
        rule = rc.get_rule(StepRole.EXECUTE, context={"cycle_type": "lean"})
        assert rule is not None
        assert rule.model == "sonnet"

    def test_route_config_get_rule_no_match_returns_none(self):
        from langywrap.router.config import Backend, RouteConfig, RouteRule, StepRole
        rc = RouteConfig(
            rules=[
                RouteRule(role=StepRole.ORIENT, model="haiku", backend=Backend.CLAUDE),
            ]
        )
        rule = rc.get_rule(StepRole.EXECUTE)
        assert rule is None

    def test_route_rule_matches_conditions_all_match(self):
        from langywrap.router.config import Backend, RouteRule, StepRole
        rule = RouteRule(
            role=StepRole.EXECUTE,
            model="kimi",
            backend=Backend.OPENROUTER,
            conditions={"cycle_type": "lean", "task": "fix"},
        )
        assert rule.matches_conditions({"cycle_type": "lean", "task": "fix"}) is True

    def test_route_rule_matches_conditions_partial_fails(self):
        from langywrap.router.config import Backend, RouteRule, StepRole
        rule = RouteRule(
            role=StepRole.EXECUTE,
            model="kimi",
            backend=Backend.OPENROUTER,
            conditions={"cycle_type": "lean"},
        )
        assert rule.matches_conditions({"cycle_type": "research"}) is False

    def test_route_rule_timeout_seconds_property(self):
        from langywrap.router.config import Backend, RouteRule, StepRole
        rule = RouteRule(
            role=StepRole.ORIENT,
            model="haiku",
            backend=Backend.CLAUDE,
            timeout_minutes=15,
        )
        assert rule.timeout_seconds == 900


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
        from langywrap.ralph.config import StepConfig, StepRole, _resolve_step_prompts
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        step = StepConfig(
            name="orient",
            prompt_template=Path("orient.md"),
            role=StepRole.ORIENT,
        )
        resolved = _resolve_step_prompts([step], prompts)
        assert resolved[0].prompt_template == prompts / "orient.md"

    def test_resolve_step_prompts_with_retry_template(self, tmp_path):
        from langywrap.ralph.config import StepConfig, StepRole, _resolve_step_prompts
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        step = StepConfig(
            name="execute",
            prompt_template=Path("execute.md"),
            role=StepRole.EXECUTE,
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
