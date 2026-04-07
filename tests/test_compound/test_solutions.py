"""Tests for compound engineering solutions module."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from langywrap.compound.solutions import Solution, SolutionStore, _slugify


class TestSolution:
    def test_to_markdown_roundtrip(self) -> None:
        sol = Solution(
            title="Fix DB timeout",
            date=date(2026, 4, 6),
            tags=["db", "timeout"],
            problem="Connection pool exhaustion",
            solution="Increase pool size to 20",
        )
        md = sol.to_markdown()
        assert "# Fix DB timeout" in md
        assert "2026-04-06" in md
        assert "Connection pool exhaustion" in md

    def test_from_file(self, tmp_path: Path) -> None:
        content = """---
date: "2026-04-06"
tags: [security, fix]
problem: XSS in form
solution: Escape output
---

# XSS Fix

Escape output
"""
        f = tmp_path / "xss_fix.md"
        f.write_text(content)
        sol = Solution.from_file(f)
        assert sol.title == "xss_fix"
        assert sol.tags == ["security", "fix"]
        assert sol.problem == "XSS in form"

    def test_from_file_no_frontmatter(self, tmp_path: Path) -> None:
        f = tmp_path / "bare.md"
        f.write_text("# Just a title\n\nSome content")
        sol = Solution.from_file(f)
        assert sol.title == "bare"
        assert sol.date == date.today()


class TestSolutionStore:
    def test_create_and_search(self, tmp_path: Path) -> None:
        store = SolutionStore(tmp_path / "solutions")
        store.add(Solution(
            title="Pool fix",
            date=date(2026, 4, 1),
            tags=["db"],
            problem="Pool exhaustion",
            solution="Increase pool",
        ))
        store.add(Solution(
            title="Auth bug",
            date=date(2026, 4, 2),
            tags=["auth"],
            problem="Token expired",
            solution="Refresh token",
        ))
        assert store.count() == 2

        results = store.search(query="pool")
        assert len(results) == 1
        assert results[0].title == "2026-04-01_pool_fix"

    def test_search_by_tags(self, tmp_path: Path) -> None:
        store = SolutionStore(tmp_path / "solutions")
        store.add(Solution(title="A", date=date.today(), tags=["x"]))
        store.add(Solution(title="B", date=date.today(), tags=["y"]))
        assert len(store.search(tags=["x"])) == 1

    def test_template_created(self, tmp_path: Path) -> None:
        store = SolutionStore(tmp_path / "solutions")
        assert (tmp_path / "solutions" / "_template.md").exists()

    def test_empty_store(self, tmp_path: Path) -> None:
        store = SolutionStore(tmp_path / "solutions")
        assert store.count() == 0
        assert store.all_solutions() == []


class TestSlugify:
    def test_basic(self) -> None:
        assert _slugify("Fix DB Timeout") == "fix_db_timeout"

    def test_special_chars(self) -> None:
        assert _slugify("hello-world! @#$") == "hello_world"

    def test_truncation(self) -> None:
        long = "a" * 100
        assert len(_slugify(long)) <= 60
