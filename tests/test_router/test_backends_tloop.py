"""Tests for ThinkingLoopBackend and related pure helpers in backends.py."""

from __future__ import annotations

import pytest
from langywrap.router.backends import (
    Backend,
    BackendConfig,
    ThinkingLoopBackend,
    ThinkingLoopBackendConfig,
    _tloop_execute_code,
    _tloop_parse_tool_calls,
    _tloop_search_web,
    _tloop_write_code,
)

# ---------------------------------------------------------------------------
# _tloop_parse_tool_calls — pure regex, fully testable
# ---------------------------------------------------------------------------


class TestParseToolCalls:
    def test_empty_string(self):
        assert _tloop_parse_tool_calls("") == []

    def test_search_web(self):
        text = "[SEARCH_WEB: python asyncio tutorial]"
        calls = _tloop_parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["type"] == "SEARCH_WEB"
        assert calls[0]["args"] == "python asyncio tutorial"

    def test_run_code(self):
        text = "[RUN_CODE: analysis.py]"
        calls = _tloop_parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["type"] == "RUN_CODE"
        assert calls[0]["args"] == "analysis.py"

    def test_load_data(self):
        text = "[LOAD_DATA: /data/dataset.csv]"
        calls = _tloop_parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["type"] == "LOAD_DATA"
        assert calls[0]["args"] == "/data/dataset.csv"

    def test_search_complete(self):
        text = "[SEARCH_COMPLETE: done]"
        calls = _tloop_parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["type"] == "SEARCH_COMPLETE"

    def test_write_code(self):
        text = "[WRITE_CODE: analysis.py]\nprint('hello')\n[/WRITE_CODE]"
        calls = _tloop_parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["type"] == "WRITE_CODE"
        assert calls[0]["name"] == "analysis.py"
        assert "print('hello')" in calls[0]["body"]

    def test_write_test(self):
        text = "[WRITE_TEST: test_foo.py]\ndef test_bar(): pass\n[/WRITE_TEST]"
        calls = _tloop_parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["type"] == "WRITE_TEST"
        assert calls[0]["name"] == "test_foo.py"

    def test_multiple_calls(self):
        text = (
            "[SEARCH_WEB: pandas groupby]\n"
            "[LOAD_DATA: /data/sales.csv]\n"
        )
        calls = _tloop_parse_tool_calls(text)
        types = [c["type"] for c in calls]
        assert "SEARCH_WEB" in types
        assert "LOAD_DATA" in types

    def test_write_code_multiline_body(self):
        text = "[WRITE_CODE: script.py]\nimport numpy\nresult = 42\n[/WRITE_CODE]"
        calls = _tloop_parse_tool_calls(text)
        assert len(calls) == 1
        body = calls[0]["body"]
        assert "import numpy" in body
        assert "result = 42" in body

    def test_args_stripped(self):
        text = "[SEARCH_WEB:   trailing spaces   ]"
        calls = _tloop_parse_tool_calls(text)
        assert calls[0]["args"] == "trailing spaces"

    def test_no_matching_tags(self):
        text = "Normal text without any tool calls here."
        assert _tloop_parse_tool_calls(text) == []


# ---------------------------------------------------------------------------
# _tloop_search_web — test the httpx-missing branch
# ---------------------------------------------------------------------------


class TestTloopSearchWeb:
    def test_httpx_missing_returns_unavailable(self, monkeypatch):
        """When httpx is not installed, return graceful string."""
        import sys
        # Temporarily remove httpx from sys.modules if present and block import
        original = sys.modules.get("httpx")
        sys.modules["httpx"] = None  # type: ignore[assignment]
        try:
            result = _tloop_search_web("test query")
        finally:
            if original is None:
                del sys.modules["httpx"]
            else:
                sys.modules["httpx"] = original

        assert "unavailable" in result.lower() or "test query" in result


# ---------------------------------------------------------------------------
# _tloop_write_code — pure I/O, fully testable
# ---------------------------------------------------------------------------


class TestTloopWriteCode:
    def test_creates_file(self, tmp_path):
        _tloop_write_code("script.py", "print('hello')", tmp_path)
        assert (tmp_path / "script.py").exists()
        assert (tmp_path / "script.py").read_text() == "print('hello')"

    def test_returns_written_message(self, tmp_path):
        result = _tloop_write_code("script.py", "x = 1", tmp_path)
        assert "Written" in result
        assert "script.py" in result

    def test_creates_nested_dir(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        _tloop_write_code("foo.py", "pass", nested)
        assert (nested / "foo.py").exists()

    def test_returns_byte_count(self, tmp_path):
        content = "hello world"
        result = _tloop_write_code("f.py", content, tmp_path)
        assert str(len(content)) in result


# ---------------------------------------------------------------------------
# _tloop_execute_code — test the "file not found" branch
# ---------------------------------------------------------------------------


class TestTloopExecuteCode:
    def test_file_not_found(self, tmp_path):
        result = _tloop_execute_code("nonexistent.py", tmp_path)
        assert "ERROR" in result
        assert "not found" in result.lower() or "nonexistent" in result

    def test_creates_pyproject_when_missing(self, tmp_path):
        # Create the file but uv might not be available; we only test pyproject creation
        (tmp_path / "script.py").write_text("x = 1\n")
        # pyproject doesn't exist yet
        assert not (tmp_path / "pyproject.toml").exists()
        # Call the function; it will try to run uv which may fail, but pyproject gets created
        _tloop_execute_code("script.py", tmp_path, timeout=1)
        # pyproject.toml should have been created before the subprocess call
        assert (tmp_path / "pyproject.toml").exists()

    def test_does_not_create_pyproject_when_exists(self, tmp_path):
        (tmp_path / "script.py").write_text("x = 1\n")
        existing_content = "[project]\nname = 'custom'\n"
        (tmp_path / "pyproject.toml").write_text(existing_content)
        _tloop_execute_code("script.py", tmp_path, timeout=1)
        # Should not overwrite existing pyproject
        assert (tmp_path / "pyproject.toml").read_text() == existing_content


# ---------------------------------------------------------------------------
# ThinkingLoopBackendConfig — Pydantic model defaults / validation
# ---------------------------------------------------------------------------


class TestThinkingLoopBackendConfig:
    def test_default_type(self):
        cfg = ThinkingLoopBackendConfig()
        assert cfg.type == Backend.THINKING_LOOP

    def test_default_max_rounds(self):
        cfg = ThinkingLoopBackendConfig()
        assert cfg.max_rounds == 12

    def test_default_use_docker(self):
        cfg = ThinkingLoopBackendConfig()
        assert cfg.use_docker is False

    def test_default_working_dir_none(self):
        cfg = ThinkingLoopBackendConfig()
        assert cfg.working_dir is None

    def test_custom_system_prompt(self):
        cfg = ThinkingLoopBackendConfig(system_prompt="You are a helpful assistant.")
        assert cfg.system_prompt == "You are a helpful assistant."

    def test_custom_max_rounds(self):
        cfg = ThinkingLoopBackendConfig(max_rounds=5)
        assert cfg.max_rounds == 5

    def test_working_dir_as_string(self, tmp_path):
        cfg = ThinkingLoopBackendConfig(working_dir=str(tmp_path))
        assert cfg.working_dir == tmp_path

    def test_working_dir_as_path(self, tmp_path):
        cfg = ThinkingLoopBackendConfig(working_dir=tmp_path)
        assert cfg.working_dir == tmp_path

    def test_docker_fields(self):
        cfg = ThinkingLoopBackendConfig(
            use_docker=True,
            docker_image="my-image:v1",
            docker_network="bridge",
        )
        assert cfg.use_docker is True
        assert cfg.docker_image == "my-image:v1"
        assert cfg.docker_network == "bridge"

    def test_on_progress_callback(self):
        events = []
        def cb(name, data):
            events.append((name, data))
        cfg = ThinkingLoopBackendConfig(on_progress=cb)
        assert cfg.on_progress is cb


# ---------------------------------------------------------------------------
# ThinkingLoopBackend.__init__ — wrong config type raises TypeError
# ---------------------------------------------------------------------------


class TestThinkingLoopBackendInit:
    def test_wrong_config_type_raises(self):
        bad_cfg = BackendConfig(type=Backend.MOCK)
        with pytest.raises(TypeError, match="ThinkingLoopBackendConfig"):
            ThinkingLoopBackend(bad_cfg)

    def test_correct_config_type_accepted(self):
        cfg = ThinkingLoopBackendConfig()
        backend = ThinkingLoopBackend(cfg)
        assert backend.config is cfg

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        cfg = ThinkingLoopBackendConfig(api_key_source="ANTHROPIC_API_KEY")
        backend = ThinkingLoopBackend(cfg)
        assert backend._api_key == "sk-test-key"

    def test_api_key_from_env_overrides(self, monkeypatch):
        cfg = ThinkingLoopBackendConfig()
        cfg.env_overrides["ANTHROPIC_API_KEY"] = "sk-override"
        backend = ThinkingLoopBackend(cfg)
        assert backend._api_key == "sk-override"

    def test_no_api_key_empty_string(self):
        cfg = ThinkingLoopBackendConfig()
        backend = ThinkingLoopBackend(cfg)
        assert backend._api_key == ""
