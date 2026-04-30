from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from langywrap.ralph.config import RalphConfig, StepConfig
from langywrap.ralph.runner import RalphLoop


def _loop(tmp_path: Path, **kwargs) -> RalphLoop:
    state = tmp_path / "ralph"
    prompts = state / "prompts"
    prompts.mkdir(parents=True)
    prompt = prompts / "step.md"
    prompt.write_text("# step\n", encoding="utf-8")
    cfg = RalphConfig(
        project_dir=tmp_path,
        state_dir=state,
        steps=[StepConfig(name="step", prompt_template=prompt)],
        **kwargs,
    )
    loop = RalphLoop(cfg, router=None)
    loop._messages = []
    loop._log = lambda msg: loop._messages.append(msg)  # type: ignore[method-assign]
    return loop


def test_run_step_with_retries_skips_when_step_failed(tmp_path: Path, monkeypatch) -> None:
    loop = _loop(tmp_path)
    step = loop.config.steps[0].model_copy(update={"retry_count": 2, "retry_gate_command": "false"})
    monkeypatch.setattr(loop, "run_step", lambda step, ctx: ("bad", False, None))

    output, success, _ = loop._run_step_with_retries(step, {})

    assert output == "bad"
    assert success is False
    assert any("preserving failure" in msg for msg in loop._messages)


def test_run_step_with_retries_honors_cycle_type_filter(tmp_path: Path, monkeypatch) -> None:
    loop = _loop(tmp_path)
    step = loop.config.steps[0].model_copy(
        update={
            "retry_count": 2,
            "retry_gate_command": "false",
            "retry_if_cycle_types": ["lean"],
        }
    )
    monkeypatch.setattr(loop, "run_step", lambda step, ctx: ("ok", True, None))

    output, success, _ = loop._run_step_with_retries(step, {}, cycle_type="research")

    assert output == "ok"
    assert success is True
    assert any("Retry skipped" in msg for msg in loop._messages)


def test_run_step_with_retries_injects_gate_error_and_retry_model(
    tmp_path: Path, monkeypatch
) -> None:
    loop = _loop(tmp_path)
    retry_prompt = loop.config.steps[0].prompt_template
    step = loop.config.steps[0].model_copy(
        update={
            "model": "first",
            "retry_count": 1,
            "retry_gate_command": "gate",
            "retry_model": "second",
            "retry_prompt_template": retry_prompt,
        }
    )
    calls = []
    gates = iter([(False, "compile error"), (True, "")])

    def fake_run_step(step_arg, ctx):
        calls.append((step_arg.model, dict(ctx)))
        return ("out", True, None)

    monkeypatch.setattr(loop, "run_step", fake_run_step)
    monkeypatch.setattr(loop, "_run_gate_command", lambda command: next(gates))

    output, success, _ = loop._run_step_with_retries(step, {"cycle": 1})

    assert output == "out"
    assert success is True
    assert calls[0][0] == "first"
    assert calls[1][0] == "second"
    assert calls[1][1]["retry_error"] == "compile error"
    assert calls[1][1]["retry_attempt"] == 1


def test_run_gate_command_timeout_and_oserror(tmp_path: Path, monkeypatch) -> None:
    loop = _loop(tmp_path)

    def timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired("cmd", 1)

    monkeypatch.setattr("langywrap.ralph.runner.subprocess.run", timeout_run)
    assert loop._run_gate_command("cmd") == (False, "Gate command timed out (10m)")

    def os_error_run(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr("langywrap.ralph.runner.subprocess.run", os_error_run)
    assert loop._run_gate_command("cmd") == (False, "boom")


def test_resolve_post_cycle_command_rewrites_missing_tool_path(tmp_path: Path, monkeypatch) -> None:
    loop = _loop(tmp_path)
    replacement = tmp_path / "bin" / "graphify"
    replacement.parent.mkdir()
    replacement.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(
        "langywrap.ralph.runner.find_tool", lambda name, project_dir: str(replacement)
    )

    resolved = loop._resolve_post_cycle_command("./missing/graphify update .")

    assert resolved.startswith(str(replacement))
    assert "update" in resolved


def test_run_post_cycle_commands_prefixes_discovered_tool_paths(
    tmp_path: Path, monkeypatch
) -> None:
    loop = _loop(tmp_path, post_cycle_commands=["graphify update ."], post_cycle_command_timeout=5)
    tool = tmp_path / "tools" / "graphify"
    tool.parent.mkdir()
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    captured = {}

    monkeypatch.setattr("langywrap.ralph.runner.find_tool", lambda name, project_dir: str(tool))

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("langywrap.ralph.runner.subprocess.run", fake_run)

    loop._run_post_cycle_commands(1)

    assert captured["cwd"] == tmp_path
    assert str(tool.parent) in captured["env"]["PATH"].split(":")[:1]
    assert any(msg == "    ok" for msg in loop._messages)


def test_verify_tool_discovery_logs_issues_and_openwolf_hints(tmp_path: Path, monkeypatch) -> None:
    loop = _loop(tmp_path)
    monkeypatch.setattr(
        "langywrap.ralph.runner.discovery_report",
        lambda project_dir: {
            "tools": {
                "execwrap": None,
                "rtk": "/rtk",
                "textify": None,
                "graphify": None,
                "openwolf": None,
            },
            "issues": ["missing execwrap"],
            "hints": {"execwrap": "install it"},
        },
    )
    monkeypatch.setattr(
        "langywrap.ralph.runner.openwolf_status",
        lambda project_dir: {
            "wolf_dir": None,
            "claude_hooks": False,
            "opencode_plugin": None,
            "issues": ["no wolf"],
            "hints": ["wire wolf"],
        },
    )

    report = loop._verify_tool_discovery()

    assert report["issues"] == ["missing execwrap"]
    assert any("install/fix helpers" in msg for msg in loop._messages)
    assert any("OpenWolf helpers" in msg for msg in loop._messages)
