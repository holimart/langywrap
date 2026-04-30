from __future__ import annotations

from pathlib import Path

from langywrap.ralph.config import RalphConfig, StepConfig
from langywrap.ralph.runner import RalphLoop


def _make_loop(tmp_path: Path) -> RalphLoop:
    state_dir = tmp_path / "ralph"
    prompts = state_dir / "prompts"
    prompts.mkdir(parents=True)
    template = prompts / "orient.md"
    template.write_text("# orient\n", encoding="utf-8")
    cfg = RalphConfig(
        project_dir=tmp_path,
        state_dir=state_dir,
        steps=[StepConfig(name="orient", prompt_template=template)],
    )
    return RalphLoop(cfg, router=None)


def _write_executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_mock_backend_probe_reports_execwrap_internal_rtk_wiring(
    tmp_path: Path, monkeypatch
) -> None:
    execwrap = _write_executable(
        tmp_path / "bin" / "execwrap.bash",
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"-c\" ]]; then\n"
        "  echo \"[execwrap:debug] RTK rewrite: '$2' -> 'rtk $2'\" >&2\n"
        "  exit 0\n"
        "fi\n"
        "exec \"$@\"\n",
    )
    rtk = _write_executable(tmp_path / "bin" / "rtk", "#!/usr/bin/env bash\nexec \"$@\"\n")
    for name in ("textify", "graphify", "openwolf"):
        _write_executable(tmp_path / "bin" / name, "#!/usr/bin/env bash\nexit 0\n")

    def fake_find_tool(name: str, project_dir: Path | None = None) -> str | None:
        return str(tmp_path / "bin" / name)

    monkeypatch.setattr(
        "langywrap.helpers.discovery.find_execwrap", lambda project_dir=None: str(execwrap)
    )
    monkeypatch.setattr("langywrap.helpers.discovery.find_rtk", lambda project_dir=None: str(rtk))
    monkeypatch.setattr("langywrap.helpers.discovery.find_tool", fake_find_tool)

    probe = _make_loop(tmp_path)._run_mock_backend_probe()

    assert probe["ok"] is True
    assert probe["execwrap_applied"] is True
    assert probe["rtk_outer_applied"] is False
    assert probe["rtk_internal_applied"] is True
    assert probe["rtk_wired"] is True
    assert probe["execwrap_project_dir_is_project"] is True
    assert probe["issues"] == []


def test_mock_backend_probe_warns_when_rtk_discovered_but_not_wired(
    tmp_path: Path, monkeypatch
) -> None:
    execwrap = _write_executable(
        tmp_path / "bin" / "execwrap.bash",
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"-c\" ]]; then exit 0; fi\n"
        "exec \"$@\"\n",
    )
    rtk = _write_executable(tmp_path / "bin" / "rtk", "#!/usr/bin/env bash\nexec \"$@\"\n")
    for name in ("textify", "graphify", "openwolf"):
        _write_executable(tmp_path / "bin" / name, "#!/usr/bin/env bash\nexit 0\n")

    def fake_find_tool(name: str, project_dir: Path | None = None) -> str | None:
        return str(tmp_path / "bin" / name)

    monkeypatch.setattr(
        "langywrap.helpers.discovery.find_execwrap", lambda project_dir=None: str(execwrap)
    )
    monkeypatch.setattr("langywrap.helpers.discovery.find_rtk", lambda project_dir=None: str(rtk))
    monkeypatch.setattr("langywrap.helpers.discovery.find_tool", fake_find_tool)

    probe = _make_loop(tmp_path)._run_mock_backend_probe()

    assert probe["ok"] is True
    assert probe["rtk_wired"] is False
    assert "RTK is discovered" in probe["issues"][0]
