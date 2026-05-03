"""Tests for pure-Python parts of backends.py (no subprocess calls to real AI CLIs)."""

from __future__ import annotations

import json
import os
import stat
import subprocess

import pytest
from langywrap.router.backends import (
    Backend,
    BackendConfig,
    ClaudeBackend,
    DirectAPIBackend,
    MockBackend,
    OpenCodeBackend,
    OpenRouterBackend,
    SubagentResult,
    ThinkingLoopBackend,
    _build_env,
    _resolve_api_key,
    _resolve_binary,
    _sample_process_activity,
    create_backend,
    wrap_cmd,
)

# ---------------------------------------------------------------------------
# SubagentResult — properties
# ---------------------------------------------------------------------------


def make_result(**kwargs) -> SubagentResult:
    defaults = {
        "text": "",
        "exit_code": 0,
        "duration_seconds": 1.0,
        "model_used": "test-model",
        "backend_used": Backend.MOCK,
    }
    defaults.update(kwargs)
    return SubagentResult(**defaults)


def test_subagent_result_ok_true():
    r = make_result(exit_code=0)
    assert r.ok is True


def test_subagent_result_ok_false():
    r = make_result(exit_code=1)
    assert r.ok is False


def test_subagent_result_timed_out():
    r = make_result(exit_code=124)
    assert r.timed_out is True


def test_subagent_result_not_timed_out():
    r = make_result(exit_code=0)
    assert r.timed_out is False


def test_subagent_result_token_estimate():
    r = make_result(text="a" * 100)
    assert r.token_estimate == 25


def test_subagent_result_token_estimate_min_one():
    r = make_result(text="")
    assert r.token_estimate >= 1


def test_subagent_result_hung_via_idle_timeout():
    r = make_result(exit_code=0, idle_timeout=True)
    assert r.hung is True


def test_sample_process_activity_includes_root_process():
    proc = subprocess.Popen(["/bin/sh", "-c", "sleep 2"])
    try:
        snapshot, active, count, summary = _sample_process_activity(proc.pid, {})
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    assert proc.pid in snapshot
    assert active is True
    assert count >= 1
    assert "sh" in summary or "sleep" in summary


def test_sample_process_activity_reports_live_sleeping_root_on_repeat():
    proc = subprocess.Popen(["/bin/sh", "-c", "sleep 2"])
    try:
        snapshot, _, _, _ = _sample_process_activity(proc.pid, {})
        _, active, count, summary = _sample_process_activity(proc.pid, snapshot)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    assert active is False
    assert count >= 1
    assert "sh" in summary or "sleep" in summary


def test_subagent_result_hung_via_size_heuristic():
    r = make_result(exit_code=124, raw_output=b"x" * 100)
    assert r.hung is True


def test_subagent_result_not_hung_large_output():
    r = make_result(exit_code=124, raw_output=b"x" * 10000)
    assert r.hung is False


def test_subagent_result_not_rate_limited():
    r = make_result(text="Everything is fine")
    assert r.rate_limited is False
    assert r.rate_limit_snippet == ""


def test_subagent_result_rate_limited_in_text():
    r = make_result(text="You've hit your limit on this plan.")
    assert r.rate_limited is True
    assert r.rate_limit_snippet != ""


def test_subagent_result_rate_limited_in_error():
    r = make_result(text="", error="Too Many Requests")
    assert r.rate_limited is True


def test_subagent_result_rate_limit_short_literal_not_in_text():
    # "Rate Limited" should NOT trigger from model text (only from error field)
    r = make_result(
        text="The system was Rate Limited last week but now it works.",
        error="",
    )
    assert r.rate_limited is False


def test_subagent_result_rate_limit_snippet_multiline():
    r = make_result(
        text="normal output\nYou've hit your limit on this plan.\nmore output"
    )
    snippet = r.rate_limit_snippet
    assert "hit your limit" in snippet.lower()


# ---------------------------------------------------------------------------
# wrap_cmd
# ---------------------------------------------------------------------------


def test_wrap_cmd_no_wrappers():
    cmd = ["./uv", "run", "ruff", "check"]
    result = wrap_cmd(cmd)
    assert result == cmd


def test_wrap_cmd_with_execwrap(tmp_path):
    ew = tmp_path / "execwrap.bash"
    ew.write_text("#!/bin/bash\n")
    ew.chmod(ew.stat().st_mode | stat.S_IEXEC)

    result = wrap_cmd(["ruff", "check"], execwrap_path=str(ew))
    assert result[0] == str(ew)
    assert "ruff" in result


def test_wrap_cmd_execwrap_shell_mode(tmp_path):
    ew = tmp_path / "execwrap.bash"
    ew.write_text("#!/bin/bash\n")
    ew.chmod(ew.stat().st_mode | stat.S_IEXEC)

    result = wrap_cmd(["ruff", "check", "-q"], execwrap_path=str(ew), shell_mode=True)
    assert result[0] == str(ew)
    assert result[1] == "-c"
    assert "ruff" in result[2]


def test_wrap_cmd_with_rtk(tmp_path):
    rtk = tmp_path / "rtk"
    rtk.write_text("#!/bin/bash\n")
    rtk.chmod(rtk.stat().st_mode | stat.S_IEXEC)

    result = wrap_cmd(["./uv", "run", "pytest"], rtk_path=str(rtk))
    assert result[0] == str(rtk)
    # ./uv should have ./ stripped
    assert result[1] == "uv"


def test_wrap_cmd_execwrap_missing_falls_through(tmp_path):
    result = wrap_cmd(["ruff"], execwrap_path=str(tmp_path / "nonexistent.bash"))
    assert result == ["ruff"]


def test_wrap_cmd_rtk_missing_falls_through(tmp_path):
    result = wrap_cmd(["ruff"], rtk_path=str(tmp_path / "nonexistent_rtk"))
    assert result == ["ruff"]


def test_wrap_cmd_execwrap_supersedes_rtk(tmp_path):
    ew = tmp_path / "execwrap.bash"
    ew.write_text("#!/bin/bash\n")
    ew.chmod(ew.stat().st_mode | stat.S_IEXEC)
    rtk = tmp_path / "rtk"
    rtk.write_text("#!/bin/bash\n")
    rtk.chmod(rtk.stat().st_mode | stat.S_IEXEC)

    result = wrap_cmd(["pytest"], execwrap_path=str(ew), rtk_path=str(rtk))
    assert result[0] == str(ew)  # execwrap supersedes


# ---------------------------------------------------------------------------
# _resolve_binary
# ---------------------------------------------------------------------------


def test_resolve_binary_path_hit():
    result = _resolve_binary(None, "echo")
    assert "echo" in result


def test_resolve_binary_explicit_path(tmp_path):
    bin_file = tmp_path / "mybin"
    bin_file.write_text("#!/bin/sh")
    result = _resolve_binary(str(bin_file), "mybin")
    assert result == str(bin_file)


def test_resolve_binary_explicit_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        _resolve_binary(str(tmp_path / "nonexistent"), "mybin")


def test_resolve_binary_not_in_path_raises():
    with pytest.raises(FileNotFoundError):
        _resolve_binary(None, "__totally_nonexistent_binary_xyz__")


# ---------------------------------------------------------------------------
# _resolve_api_key
# ---------------------------------------------------------------------------


def test_resolve_api_key_none():
    assert _resolve_api_key(None) is None


def test_resolve_api_key_from_json_file(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"api_key": "sk-test-123"}))
    result = _resolve_api_key(str(auth))
    assert result == "sk-test-123"


def test_resolve_api_key_from_json_camel(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"apiKey": "sk-camel-456"}))
    result = _resolve_api_key(str(auth))
    assert result == "sk-camel-456"


def test_resolve_api_key_malformed_json_falls_to_env(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text("not json{{")
    os.environ["FAKE_KEY_TEST"] = "env-value"
    try:
        result = _resolve_api_key(str(auth))
        # Falls back to env var name lookup → None (no env var named the file path)
        assert result is None
    finally:
        del os.environ["FAKE_KEY_TEST"]


def test_resolve_api_key_from_env_var():
    os.environ["MY_TEST_API_KEY_XYZ"] = "env-key-value"
    try:
        result = _resolve_api_key("MY_TEST_API_KEY_XYZ")
        assert result == "env-key-value"
    finally:
        del os.environ["MY_TEST_API_KEY_XYZ"]


def test_resolve_api_key_env_var_missing():
    result = _resolve_api_key("__NONEXISTENT_ENV_VAR_XYZ__")
    assert result is None


# ---------------------------------------------------------------------------
# _build_env
# ---------------------------------------------------------------------------


def test_build_env_merges_overrides():
    cfg = BackendConfig(type=Backend.MOCK, env_overrides={"MY_VAR": "hello"})
    env = _build_env(cfg)
    assert env["MY_VAR"] == "hello"


def test_build_env_extra_overrides():
    cfg = BackendConfig(type=Backend.MOCK, env_overrides={"A": "1"})
    env = _build_env(cfg, extra={"B": "2"})
    assert env["A"] == "1"
    assert env["B"] == "2"


# ---------------------------------------------------------------------------
# create_backend
# ---------------------------------------------------------------------------


def test_create_backend_mock():
    cfg = BackendConfig(type=Backend.MOCK)
    b = create_backend(cfg)
    assert isinstance(b, MockBackend)


def test_create_backend_claude():
    cfg = BackendConfig(type=Backend.CLAUDE)
    b = create_backend(cfg)
    assert isinstance(b, ClaudeBackend)


def test_create_backend_opencode():
    cfg = BackendConfig(type=Backend.OPENCODE)
    b = create_backend(cfg)
    assert isinstance(b, OpenCodeBackend)


def test_create_backend_openrouter():
    cfg = BackendConfig(type=Backend.OPENROUTER)
    b = create_backend(cfg)
    assert isinstance(b, OpenRouterBackend)


def test_create_backend_direct_api():
    cfg = BackendConfig(type=Backend.DIRECT_API)
    b = create_backend(cfg)
    assert isinstance(b, DirectAPIBackend)


def test_create_backend_thinking_loop():
    from langywrap.router.backends import ThinkingLoopBackendConfig
    cfg = ThinkingLoopBackendConfig()  # sets type=THINKING_LOOP internally
    b = create_backend(cfg)
    assert isinstance(b, ThinkingLoopBackend)


# ---------------------------------------------------------------------------
# BackendConfig
# ---------------------------------------------------------------------------


def test_backend_config_defaults():
    cfg = BackendConfig(type=Backend.MOCK)
    assert cfg.timeout_seconds == 300
    assert cfg.extra_args == []
    assert cfg.env_overrides == {}
    assert cfg.binary_path is None
    assert cfg.stream_output is False
