from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from langywrap.ralph.config import StepRole
from langywrap.ralph.config_v2 import (
    _infer_backend,
    _infer_role,
    _parse_adversarial,
    _parse_flow_entry,
    _parse_gates,
    _parse_retry,
    _parse_when,
    _resolve_model,
    build_route_config_from_v2,
    is_v2_config,
    load_v2,
)

# ---------------------------------------------------------------------------
# _resolve_model
# ---------------------------------------------------------------------------


def test_resolve_model_alias():
    # "haiku" should expand to the full model ID
    result = _resolve_model("haiku")
    assert "haiku" in result.lower()


def test_resolve_model_unknown_passthrough():
    result = _resolve_model("my-custom-model")
    assert result == "my-custom-model"


def test_resolve_model_extra_alias_takes_precedence():
    result = _resolve_model("haiku", extra={"haiku": "custom-haiku-override"})
    assert result == "custom-haiku-override"


# ---------------------------------------------------------------------------
# _infer_backend
# ---------------------------------------------------------------------------


def test_infer_backend_nvidia():
    assert _infer_backend("nvidia/something") == "opencode"


def test_infer_backend_openai():
    assert _infer_backend("openai/gpt-4o") == "opencode"


def test_infer_backend_mistral():
    assert _infer_backend("mistral/large") == "opencode"


def test_infer_backend_claude():
    assert _infer_backend("claude-sonnet-4-6") == "claude"


def test_infer_backend_moonshotai():
    assert _infer_backend("moonshotai/kimi") == "opencode"


# ---------------------------------------------------------------------------
# _infer_role
# ---------------------------------------------------------------------------


def test_infer_role_orient():
    role = _infer_role("orient")
    assert role == StepRole.ORIENT


def test_infer_role_execute():
    role = _infer_role("execute")
    assert role == StepRole.EXECUTE


def test_infer_role_critic():
    role = _infer_role("critic")
    assert role == StepRole.CRITIC


def test_infer_role_validate_alias():
    role = _infer_role("validate")
    assert role == StepRole.CRITIC


def test_infer_role_adversarial_alias():
    role = _infer_role("adversarial")
    assert role == StepRole.CRITIC


def test_infer_role_review_alias():
    role = _infer_role("review")
    assert role == StepRole.REVIEW


def test_infer_role_unknown_is_generic():
    role = _infer_role("custom_step")
    assert role == StepRole.GENERIC


# ---------------------------------------------------------------------------
# _parse_when
# ---------------------------------------------------------------------------


def test_parse_when_valid():
    step, pattern = _parse_when("execute =~ /error/")
    assert step == "execute"
    assert pattern == "error"


def test_parse_when_invalid_raises():
    with pytest.raises(ValueError, match="Invalid when expression"):
        _parse_when("not valid")


# ---------------------------------------------------------------------------
# _parse_flow_entry
# ---------------------------------------------------------------------------


def test_parse_flow_entry_string(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    steps = _parse_flow_entry("orient", models={}, prompts_dir=prompts_dir, default_tools="Bash")
    assert len(steps) == 1
    assert steps[0].name == "orient"


def test_parse_flow_entry_dict_with_opts(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    steps = _parse_flow_entry(
        {"execute": {"timeout": "60m", "fail_fast": True}},
        models={},
        prompts_dir=prompts_dir,
        default_tools="Bash",
    )
    assert len(steps) == 1
    assert steps[0].name == "execute"
    assert steps[0].timeout_minutes == 60
    assert steps[0].fail_fast is True


def test_parse_flow_entry_retry_returns_empty(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    steps = _parse_flow_entry(
        {"execute.retry": {"max": 3}},
        models={},
        prompts_dir=prompts_dir,
        default_tools="Bash",
    )
    assert steps == []


def test_parse_flow_entry_tools_list(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    steps = _parse_flow_entry(
        {"execute": {"tools": ["Bash", "Read"]}},
        models={},
        prompts_dir=prompts_dir,
        default_tools="Bash",
    )
    assert "Bash" in steps[0].tools
    assert "Read" in steps[0].tools


def test_parse_flow_entry_when_str(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    steps = _parse_flow_entry(
        {"critic": {"when": "execute =~ /error/"}},
        models={},
        prompts_dir=prompts_dir,
        default_tools="",
    )
    assert steps[0].run_if_step == "execute"
    assert steps[0].run_if_pattern == "error"


def test_parse_flow_entry_when_list(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    steps = _parse_flow_entry(
        {"execute": {"when": ["lean", "mixed"]}},
        models={},
        prompts_dir=prompts_dir,
        default_tools="",
    )
    assert "lean" in steps[0].run_if_cycle_types


def test_parse_flow_entry_invalid_type():
    with pytest.raises(TypeError):
        _parse_flow_entry(42, models={}, prompts_dir=Path("."), default_tools="")


def test_parse_flow_entry_invalid_dict_multi_key():
    with pytest.raises(ValueError):
        _parse_flow_entry(
            {"a": {}, "b": {}}, models={}, prompts_dir=Path("."), default_tools=""
        )


# ---------------------------------------------------------------------------
# _parse_retry
# ---------------------------------------------------------------------------


def test_parse_retry_basic(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    updates = _parse_retry(
        {"max": 3, "gate": "./just check"},
        "execute",
        models={},
        prompts_dir=prompts_dir,
    )
    assert updates["retry_count"] == 3
    assert updates["retry_gate_command"] == "./just check"


def test_parse_retry_with_model(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    updates = _parse_retry(
        {"max": 2, "model": "haiku"},
        "execute",
        models={},
        prompts_dir=prompts_dir,
    )
    assert "retry_model" in updates
    assert "haiku" in updates["retry_model"].lower()


# ---------------------------------------------------------------------------
# _parse_gates
# ---------------------------------------------------------------------------


def test_parse_gates_none():
    primary, extra = _parse_gates(None)
    assert primary is None
    assert extra == []


def test_parse_gates_string():
    primary, extra = _parse_gates("./just check")
    assert primary is not None
    assert primary.command == "./just check"
    assert extra == []


def test_parse_gates_list_of_strings():
    primary, extra = _parse_gates(["./just check", "./just validate"])
    assert primary is not None
    assert len(extra) == 1


def test_parse_gates_list_with_command_dict():
    primary, extra = _parse_gates([{"command": "lake build", "timeout": "15m"}])
    assert primary is not None
    assert primary.command == "lake build"
    assert primary.timeout_minutes == 15


def test_parse_gates_single_key_dict():
    primary, extra = _parse_gates([{"lake build": {"timeout": "10m"}}])
    assert primary is not None
    assert primary.command == "lake build"


# ---------------------------------------------------------------------------
# _parse_adversarial
# ---------------------------------------------------------------------------


def test_parse_adversarial_none():
    every, step, patterns, finalize = _parse_adversarial(None)
    assert every is None
    assert step == ""
    assert patterns == []


def test_parse_adversarial_basic():
    every, step, patterns, finalize = _parse_adversarial({"every": 5, "step": "adv"})
    assert every == 5
    assert step == "adv"


def test_parse_adversarial_milestone():
    _, _, patterns, _ = _parse_adversarial(
        {"milestone": "execute =~ /theorem/"}
    )
    assert "theorem" in patterns[0]


def test_parse_adversarial_milestone_list():
    _, _, patterns, _ = _parse_adversarial({"milestone": ["pat1", "pat2"]})
    assert len(patterns) == 2


# ---------------------------------------------------------------------------
# is_v2_config
# ---------------------------------------------------------------------------


def test_is_v2_with_flow_key():
    assert is_v2_config({"flow": ["orient"]}) is True


def test_is_v2_without_flow_key():
    assert is_v2_config({"steps": []}) is False


# ---------------------------------------------------------------------------
# load_v2
# ---------------------------------------------------------------------------


def test_load_v2_minimal(tmp_path):
    raw = {
        "flow": ["orient", "execute", "critic"],
    }
    config = load_v2(raw, tmp_path)
    assert len(config.steps) == 3
    step_names = [s.name for s in config.steps]
    assert "orient" in step_names


def test_load_v2_with_models(tmp_path):
    raw = {
        "models": {"execute": "haiku"},
        "flow": ["orient", "execute"],
    }
    config = load_v2(raw, tmp_path)
    execute_step = next(s for s in config.steps if s.name == "execute")
    assert "haiku" in execute_step.model.lower()


def test_load_v2_with_gates(tmp_path):
    raw = {
        "flow": ["orient"],
        "gates": "./just check",
    }
    config = load_v2(raw, tmp_path)
    assert config.quality_gate is not None
    assert "just check" in config.quality_gate.command


def test_load_v2_with_throttle(tmp_path):
    raw = {
        "flow": ["orient"],
        "throttle": {"utc": "2-6"},
    }
    config = load_v2(raw, tmp_path)
    assert config.throttle_utc_start == 2
    assert config.throttle_utc_end == 6


def test_load_v2_with_retry(tmp_path):
    raw = {
        "flow": [
            "execute",
            {"execute.retry": {"max": 3, "gate": "./just check"}},
        ],
    }
    config = load_v2(raw, tmp_path)
    execute_step = next(s for s in config.steps if s.name == "execute")
    assert execute_step.retry_count == 3


def test_load_v2_with_cycle_types_deprecated_warns(tmp_path):
    raw = {
        "flow": ["execute"],
        "cycle_types": {
            "lean": {"match": "*.lean", "execute_model": "haiku"},
        },
    }
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        load_v2(raw, tmp_path)
    assert any("deprecated" in str(warning.message).lower() for warning in w)


def test_load_v2_git_config(tmp_path):
    raw = {
        "flow": ["execute"],
        "git": {"commit": False, "paths": ["src/"]},
    }
    config = load_v2(raw, tmp_path)
    assert config.git_commit_after_cycle is False
    assert "src/" in config.git_add_paths


# ---------------------------------------------------------------------------
# build_route_config_from_v2
# ---------------------------------------------------------------------------


def test_build_route_config_from_v2_minimal(tmp_path):
    raw = {
        "name": "test",
        "models": {"execute": "haiku"},
    }
    rc = build_route_config_from_v2(raw, tmp_path)
    assert rc is not None
    assert len(rc.rules) >= 1


def test_build_route_config_no_models(tmp_path):
    raw = {"name": "test"}
    rc = build_route_config_from_v2(raw, tmp_path)
    assert rc is None


def test_build_route_config_dict_model_spec(tmp_path):
    raw = {
        "models": {
            "execute": {
                "model": "haiku",
                "retry": ["sonnet"],
                "backend": "claude",
            }
        }
    }
    rc = build_route_config_from_v2(raw, tmp_path)
    assert rc is not None
    rules_by_role = {r.role.value: r for r in rc.rules}
    assert "execute" in rules_by_role
    assert len(rules_by_role["execute"].retry_models) >= 1


def test_build_route_config_unknown_role_skipped(tmp_path):
    raw = {
        "models": {
            "unknown_role_xyz": "haiku",
            "execute": "haiku",
        }
    }
    rc = build_route_config_from_v2(raw, tmp_path)
    assert rc is not None
    # Only execute should be included (unknown_role_xyz raises ValueError in RouterStepRole)
    role_names = [r.role.value for r in rc.rules]
    assert "execute" in role_names
    assert "unknown_role_xyz" not in role_names
