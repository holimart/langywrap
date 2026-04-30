from __future__ import annotations

import json
from pathlib import Path

from langywrap.router.backends import (
    Backend,
    BackendConfig,
    SubagentResult,
    _build_env,
    _detect_auth_failure,
    _extract_stream_stats,
    _is_fresher_auth,
    _seed_opencode_auth,
    _sync_project_mcp_config,
)


def test_auth_failed_property_overrides_ok() -> None:
    result = SubagentResult(
        text="fine",
        exit_code=0,
        duration_seconds=0,
        model_used="m",
        backend_used=Backend.OPENCODE,
        auth_failed_snippet='{"statusCode":401}',
    )

    assert result.auth_failed is True
    assert result.ok is False


def test_detect_auth_failure_from_raw_line_and_truncates() -> None:
    long_line = '{"statusCode":401,"message":"' + ("x" * 500) + '"}'
    snippet = _detect_auth_failure("", (long_line + "\n").encode())

    assert '"statusCode":401' in snippet
    assert len(snippet) <= 401


def test_extract_stream_stats_reads_claude_and_opencode_shapes() -> None:
    raw = b"\n".join(
        [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "usage": {"input_tokens": 3, "output_tokens": 4},
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Read",
                                "input": {"file_path": "a.py"},
                            },
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": "ls"},
                            },
                        ],
                    },
                }
            ).encode(),
            json.dumps(
                {
                    "type": "tool_use",
                    "part": {
                        "tool": "edit",
                        "state": {"input": {"filePath": "b.py"}},
                    },
                }
            ).encode(),
            json.dumps(
                {
                    "type": "step_finish",
                    "part": {"tokens": {"input": 10, "output": 20}},
                }
            ).encode(),
            json.dumps(
                {"type": "result", "usage": {"input_tokens": 30, "output_tokens": 40}}
            ).encode(),
            b"not json",
        ]
    )

    input_tokens, output_tokens, files = _extract_stream_stats(raw)

    assert input_tokens == 30
    assert output_tokens == 40
    assert files == ["a.py", "b.py"]


def test_is_fresher_auth_prefers_later_oauth_expiry() -> None:
    assert _is_fresher_auth({"expires": 10}, {"expires": 20}) is True
    assert _is_fresher_auth({"expires": 20}, {"expires": 10}) is False
    assert _is_fresher_auth({"api": "old"}, {"api": "new"}) is True


def test_seed_opencode_auth_merges_freshest_entries(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    local = home / ".local" / "share" / "opencode"
    local.mkdir(parents=True)
    (local / "auth.json").write_text(
        json.dumps({"openai": {"type": "oauth", "expires": 10, "token": "old"}}),
        encoding="utf-8",
    )
    xdg = tmp_path / "xdg" / "opencode"
    xdg.mkdir(parents=True)
    (xdg / "auth.json").write_text(
        json.dumps({"openai": {"type": "oauth", "expires": 30, "token": "new"}}),
        encoding="utf-8",
    )
    target = tmp_path / "target"

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("pathlib.Path.home", lambda: home)

    _seed_opencode_auth(str(target))

    merged = json.loads((target / "opencode" / "auth.json").read_text(encoding="utf-8"))
    assert merged["openai"]["token"] == "new"


def test_build_env_applies_extra_after_config(monkeypatch) -> None:
    monkeypatch.setenv("BASE", "1")
    cfg = BackendConfig(type=Backend.MOCK, env_overrides={"BASE": "config", "A": "B"})

    env = _build_env(cfg, {"A": "extra"})

    assert env["BASE"] == "config"
    assert env["A"] == "extra"


def test_sync_project_mcp_config_handles_missing_and_errors(tmp_path: Path, monkeypatch) -> None:
    assert _sync_project_mcp_config(None) is None
    assert _sync_project_mcp_config(str(tmp_path)) is None

    (tmp_path / ".langywrap").mkdir()
    (tmp_path / ".langywrap" / "mcp.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "langywrap.mcp_config.sync_langywrap_mcp_manifest",
        lambda repo: repo / ".mcp.json",
    )

    assert _sync_project_mcp_config(str(tmp_path)) == tmp_path / ".mcp.json"
