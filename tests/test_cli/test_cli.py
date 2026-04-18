"""Tests for langywrap CLI commands."""

from __future__ import annotations

from click.testing import CliRunner
from langywrap.cli import main


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
