"""Tests for helpers.python.output_filter module."""

from __future__ import annotations

from pathlib import Path

from langywrap.helpers.python.output_filter import audit_output_config


class TestAuditOutputConfig:
    def test_no_pyproject(self, tmp_path: Path) -> None:
        result = audit_output_config(tmp_path)
        assert result == {"error": "no pyproject.toml found"}

    def test_fully_configured(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\naddopts = "-q --tb=short"\n'
            "[tool.mypy]\npretty = false\n"
        )
        (tmp_path / "justfile").write_text("lint:\n    ruff check -q lib/\n")
        result = audit_output_config(tmp_path)
        assert result["pytest"] == "ok"
        assert result["mypy"] == "ok"
        assert result["ruff"] == "ok"

    def test_missing_flags(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\naddopts = \"-v\"\n"
            "[tool.mypy]\nstrict = true\n"
        )
        result = audit_output_config(tmp_path)
        assert "missing" in result["pytest"]
        assert "missing" in result["mypy"]

    def test_no_justfile(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]\nname = \"test\"\n")
        result = audit_output_config(tmp_path)
        assert result["ruff"] == "no justfile"
