"""Tests for langywrap CLI commands."""

from __future__ import annotations

from click.testing import CliRunner
from langywrap.cli import _build_router, main
from langywrap.router.backends import Backend


class TestCLI:
    def test_version(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "langywrap" in result.output.lower() or "version" in result.output.lower()

    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "install" in result.output
        assert "couple" in result.output
        assert "ralph" in result.output
        assert "harden" in result.output
        assert "router" in result.output
        assert "compound" in result.output

    def test_install_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["install", "--help"])
        assert result.exit_code == 0
        assert "system" in result.output
        assert "rtk" in result.output

    def test_couple_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["couple", "--help"])
        assert result.exit_code == 0
        assert "add" in result.output
        assert "remove" in result.output
        assert "list" in result.output

    def test_ralph_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["ralph", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output
        assert "status" in result.output
        assert "resume" in result.output

    def test_ralph_run_dry_run_replaces_models(self, tmp_path) -> None:
        cfg_dir = tmp_path / ".langywrap"
        cfg_dir.mkdir()
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "execute.md").write_text("execute")
        (cfg_dir / "ralph.yaml").write_text(
            "models:\n"
            "  execute: kimi\n"
            "prompts: prompts\n"
            "flow:\n"
            "  - execute\n"
        )

        result = CliRunner().invoke(
            main,
            [
                "ralph",
                "run",
                str(tmp_path),
                "--dry-run",
                "--no-tmux",
                "--replace-model",
                "kimi=openai/gpt-5.3-codex",
            ],
        )

        assert result.exit_code == 0
        assert "openai/gpt-5.3-codex" in result.output
        assert "nvidia/moonshotai/kimi-k2.6" not in result.output

    def test_router_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["router", "--help"])
        assert result.exit_code == 0
        assert "show" in result.output
        assert "test" in result.output

    def test_compound_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["compound", "--help"])
        assert result.exit_code == 0
        assert "push" in result.output
        assert "search" in result.output

    def test_couple_list_no_coupled(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["couple", "list"])
        assert result.exit_code == 0

    def test_couple_remove_nonexistent(self, tmp_path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["couple", "remove", str(tmp_path)])
        assert result.exit_code == 0
        assert "No coupling" in result.output

    def test_build_router_records_claude_binary(self, tmp_path, monkeypatch) -> None:
        def fake_which(name: str) -> str | None:
            if name == "claude":
                return "/opt/bin/claude"
            if name == "opencode":
                return "/opt/bin/opencode"
            return None

        monkeypatch.setattr("langywrap.cli.shutil.which", fake_which)

        router = _build_router(tmp_path)

        assert router._backends[Backend.CLAUDE].binary_path == "/opt/bin/claude"

    def test_openwolf_status_command_outputs_json(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            "langywrap.integrations.openwolf.openwolf_status",
            lambda path: {"binary": "/bin/openwolf", "wolf_dir": str(path / ".wolf")},
        )

        result = CliRunner().invoke(main, ["integration", "openwolf", "status", str(tmp_path)])

        assert result.exit_code == 0
        assert '"binary": "/bin/openwolf"' in result.output

    def test_openwolf_wire_command_passes_flags(self, tmp_path, monkeypatch) -> None:
        captured = {}

        def fake_wire(path, **kwargs):
            captured["path"] = path
            captured.update(kwargs)
            return {"written": {"claude_settings": "x"}, "status": {}}

        monkeypatch.setattr("langywrap.integrations.openwolf.wire_openwolf", fake_wire)

        result = CliRunner().invoke(
            main,
            [
                "integration",
                "openwolf",
                "wire",
                str(tmp_path),
                "--init",
                "--no-opencode",
                "--langywrap-only",
            ],
        )

        assert result.exit_code == 0
        assert captured == {
            "path": tmp_path.resolve(),
            "init": True,
            "claude": True,
            "opencode": False,
            "langywrap_only": True,
        }

    def test_mcp_register_rejects_bad_env(self, tmp_path) -> None:
        result = CliRunner().invoke(
            main,
            [
                "mcp",
                "register",
                "--repo",
                str(tmp_path),
                "--name",
                "srv",
                "--command",
                "python",
                "--env",
                "NOT_KEY_VALUE",
            ],
        )

        assert result.exit_code != 0
        assert "Invalid --env value" in result.output

    def test_mcp_register_and_sync_commands(self, tmp_path, monkeypatch) -> None:
        calls = {}

        def fake_register(config_path, **kwargs):
            calls["register"] = (config_path, kwargs)

        def fake_sync(repo):
            calls["sync"] = repo
            return repo / ".mcp.json"

        monkeypatch.setattr("langywrap.mcp_config.register_mcp_server", fake_register)
        monkeypatch.setattr("langywrap.mcp_config.sync_langywrap_mcp_manifest", fake_sync)

        runner = CliRunner()
        reg = runner.invoke(
            main,
            [
                "mcp",
                "register",
                "--repo",
                str(tmp_path),
                "--name",
                "srv",
                "--command",
                "python",
                "--arg",
                "server.py",
                "--env",
                "A=B",
            ],
        )
        sync = runner.invoke(main, ["mcp", "sync", "--repo", str(tmp_path)])

        assert reg.exit_code == 0
        assert sync.exit_code == 0
        assert calls["register"][1]["env"] == {"A": "B"}
        assert calls["sync"] == tmp_path.resolve()

    def test_router_show_lists_steps(self, tmp_path, monkeypatch) -> None:
        class FakeStep:
            name = "orient"
            model = "openai/gpt-test"
            engine = "auto"
            timeout_minutes = 7
            retry_models = ["fallback"]

        fake_cfg = type(
            "Cfg",
            (),
            {"steps": [FakeStep()], "throttle_utc_start": None, "throttle_utc_end": None},
        )()
        monkeypatch.setattr("langywrap.ralph.config.load_ralph_config", lambda path: fake_cfg)

        result = CliRunner().invoke(main, ["router", "show", str(tmp_path)])

        assert result.exit_code == 0
        assert "orient" in result.output
        assert "fallback" in result.output

    def test_router_test_filters_model(self, tmp_path, monkeypatch) -> None:
        class FakeStep:
            model = "wanted-model"
            engine = "auto"
            timeout_minutes = 1

        fake_cfg = type("Cfg", (), {"steps": [FakeStep()]})()
        monkeypatch.setattr("langywrap.ralph.config.load_ralph_config", lambda path: fake_cfg)

        result_obj = type(
            "DryRun",
            (), {
                "model": "wanted-model",
                "backend": "mock",
                "reachable": True,
                "reason": "ok",
                "detail": "",
            },
        )()
        fake_router = type("Router", (), {"dry_run_detailed": lambda self, targets: [result_obj]})()
        monkeypatch.setattr("langywrap.cli._build_router", lambda path: fake_router)

        result = CliRunner().invoke(main, ["router", "test", "--model", "wanted", str(tmp_path)])

        assert result.exit_code == 0
        assert "wanted-model" in result.output
        assert "OK" in result.output
