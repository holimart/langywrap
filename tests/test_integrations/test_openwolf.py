from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from langywrap.integrations.openwolf import (
    claude_hook_settings,
    openwolf_status,
    wire_claude,
    wire_opencode,
    wire_openwolf,
)


def _create_wolf_hooks(project: Path) -> None:
    hooks = project / ".wolf" / "hooks"
    hooks.mkdir(parents=True)
    for name in (
        "session-start.js",
        "pre-read.js",
        "pre-write.js",
        "post-read.js",
        "post-write.js",
        "stop.js",
    ):
        (hooks / name).write_text("// hook\n", encoding="utf-8")


def test_claude_hook_settings_can_be_langywrap_only() -> None:
    settings = claude_hook_settings(langywrap_only=True)
    blob = json.dumps(settings)

    assert "LANGYWRAP_OPENWOLF" in blob
    assert ".wolf/hooks/session-start.js" in blob


def test_wire_claude_replaces_existing_openwolf_hooks(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    existing = {"hooks": {"SessionStart": [{"hooks": [{"command": "node .wolf/hooks/old.js"}]}]}}
    settings_path.write_text(
        json.dumps(existing),
        encoding="utf-8",
    )

    written = wire_claude(tmp_path, langywrap_only=True)
    data = json.loads(written.read_text(encoding="utf-8"))
    blob = json.dumps(data)

    assert written == settings_path
    assert "old.js" not in blob
    assert "session-start.js" in blob
    assert "LANGYWRAP_OPENWOLF" in blob


def test_wire_opencode_langywrap_only_plugin(tmp_path: Path) -> None:
    plugin = wire_opencode(tmp_path, langywrap_only=True)
    content = plugin.read_text(encoding="utf-8")

    assert plugin == tmp_path / ".opencode" / "plugins" / "openwolf.js"
    assert "LANGYWRAP_OPENWOLF_ONLY" in content
    assert "session.created" in content


def test_openwolf_status_reports_wired_project(tmp_path: Path) -> None:
    _create_wolf_hooks(tmp_path)
    wire_claude(tmp_path, langywrap_only=True)
    wire_opencode(tmp_path, langywrap_only=True)

    with patch("langywrap.integrations.openwolf.find_tool", return_value="/bin/openwolf"):
        status = openwolf_status(tmp_path)

    assert status["binary"] == "/bin/openwolf"
    assert status["claude_hooks"] is True
    assert status["claude_langywrap_only"] is True
    assert status["opencode_plugin"] == str(tmp_path / ".opencode" / "plugins" / "openwolf.js")
    assert status["opencode_langywrap_only"] is True
    assert status["issues"] == []


def test_wire_openwolf_can_skip_init_and_wire_both_runtimes(tmp_path: Path) -> None:
    _create_wolf_hooks(tmp_path)
    with patch("langywrap.integrations.openwolf.find_tool", return_value="/bin/openwolf"):
        result = wire_openwolf(tmp_path, init=False, langywrap_only=True)

    assert result["initialized"] is False
    assert "claude_settings" in result["written"]
    assert "opencode_plugin" in result["written"]
    assert result["status"]["issues"] == []
