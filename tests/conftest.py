"""Shared test fixtures for langywrap."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory with minimal structure."""
    project = tmp_path / "test_project"
    project.mkdir()
    (project / "src").mkdir()
    (project / "tests").mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "test_project"\n')
    (project / "justfile").write_text("check:\n\techo ok\n")
    return project


@pytest.fixture
def tmp_langywrap_dir(tmp_path: Path) -> Path:
    """Create a temporary langywrap-like directory."""
    lw = tmp_path / "langywrap"
    lw.mkdir()
    (lw / "docs" / "solutions").mkdir(parents=True)
    (lw / "experiments" / "archive").mkdir(parents=True)
    (lw / "lib" / "langywrap" / "security" / "defaults").mkdir(parents=True)
    return lw
