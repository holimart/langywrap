"""Tests for project scaffolding."""

from __future__ import annotations

from pathlib import Path

from langywrap.template.scaffold import scaffold_project


class TestScaffold:
    def test_creates_project_dir(self, tmp_path: Path) -> None:
        result = scaffold_project(
            tmp_path,
            name="my-test-project",
            init_git=False,
            init_uv=False,
            couple_langywrap=False,
        )
        assert result.exists()
        assert result.is_dir()

    def test_creates_src_package(self, tmp_path: Path) -> None:
        result = scaffold_project(
            tmp_path,
            name="my-test-project",
            init_git=False,
            init_uv=False,
            couple_langywrap=False,
        )
        pkg = result / "src" / "my_test_project" / "__init__.py"
        assert pkg.exists()

    def test_creates_standard_dirs(self, tmp_path: Path) -> None:
        result = scaffold_project(
            tmp_path,
            name="test-proj",
            init_git=False,
            init_uv=False,
            couple_langywrap=False,
        )
        assert (result / "tests").exists()
        assert (result / "scripts").exists()
        assert (result / "docs").exists()
        assert (result / "notes").exists()
        assert (result / ".gitignore").exists()
        assert (result / ".env").exists()

    def test_creates_gitignore(self, tmp_path: Path) -> None:
        result = scaffold_project(
            tmp_path,
            name="test-proj",
            init_git=False,
            init_uv=False,
            couple_langywrap=False,
        )
        gi = (result / ".gitignore").read_text()
        assert "__pycache__" in gi
