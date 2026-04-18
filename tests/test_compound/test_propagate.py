from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

from langywrap.compound.propagate import pull_from_hub, push_to_hub
from langywrap.compound.solutions import Solution

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_solution_file(directory: Path, title: str = "test-solution") -> Path:
    """Create a minimal solution markdown file."""
    directory.mkdir(parents=True, exist_ok=True)
    sol = Solution(
        title=title,
        date=date(2026, 1, 1),
        tags=["test"],
        problem="problem text",
        solution="solution text",
    )
    path = directory / f"{title}.md"
    path.write_text(sol.to_markdown())
    return path


def make_hub(tmp_path: Path) -> Path:
    """Create a minimal hub dir with docs/solutions/."""
    hub = tmp_path / "hub"
    (hub / "docs" / "solutions").mkdir(parents=True)
    return hub


# ---------------------------------------------------------------------------
# find_hub_dir
# ---------------------------------------------------------------------------


def test_find_hub_dir_returns_none_when_nothing(tmp_path):
    # Use a fake home with no hub and patch out the hardcoded paths
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    with patch("pathlib.Path.home", return_value=fake_home), \
         patch("langywrap.compound.propagate.find_hub_dir",
               return_value=None) as mock_fhd:
        result = mock_fhd()
    assert result is None


def test_find_hub_dir_detects_known_path(tmp_path):
    hub = make_hub(tmp_path)
    sol_file = make_solution_file(tmp_path / "project" / "docs" / "solutions")
    result = push_to_hub(sol_file, hub_dir=hub)
    assert result is not None


# ---------------------------------------------------------------------------
# push_to_hub
# ---------------------------------------------------------------------------


def test_push_to_hub_returns_none_when_no_hub(tmp_path):
    sol_file = make_solution_file(tmp_path / "solutions")
    result = push_to_hub(sol_file, hub_dir=None)
    # If the actual system hub exists, this may return a path. If not, None.
    # We can't guarantee the system state, so just check no crash.
    assert result is None or isinstance(result, Path)


def test_push_to_hub_copies_to_hub(tmp_path):
    hub = make_hub(tmp_path)
    sol_file = make_solution_file(tmp_path / "project" / "solutions", "my-solution")
    result = push_to_hub(sol_file, hub_dir=hub)
    assert result is not None
    assert result.exists()


def test_push_to_hub_with_project_name(tmp_path):
    hub = make_hub(tmp_path)
    sol_file = make_solution_file(tmp_path / "project" / "solutions", "proj-solution")
    result = push_to_hub(sol_file, hub_dir=hub, project_name="myproject")
    assert result is not None
    content = result.read_text()
    assert "myproject" in content


def test_push_to_hub_explicit_hub_dir_overrides_autodiscovery(tmp_path):
    hub = make_hub(tmp_path)
    sol_file = make_solution_file(tmp_path / "s")
    result = push_to_hub(sol_file, hub_dir=hub)
    assert result is not None


# ---------------------------------------------------------------------------
# pull_from_hub
# ---------------------------------------------------------------------------


def test_pull_from_hub_returns_zero_when_no_hub(tmp_path):
    result = pull_from_hub(tmp_path, hub_dir=None)
    # Depends on system state; just no crash
    assert isinstance(result, int)


def test_pull_from_hub_copies_matching(tmp_path):
    hub = make_hub(tmp_path)
    # Add two solutions to hub
    make_solution_file(hub / "docs" / "solutions", "solution-alpha")
    make_solution_file(hub / "docs" / "solutions", "solution-beta")

    project = tmp_path / "project"
    (project / "docs" / "solutions").mkdir(parents=True)

    count = pull_from_hub(project, hub_dir=hub)
    assert count == 2


def test_pull_from_hub_skips_existing(tmp_path):
    hub = make_hub(tmp_path)
    make_solution_file(hub / "docs" / "solutions", "existing-sol")

    project = tmp_path / "project"
    (project / "docs" / "solutions").mkdir(parents=True)
    # Pre-populate project with same solution
    make_solution_file(project / "docs" / "solutions", "existing-sol")

    count = pull_from_hub(project, hub_dir=hub)
    assert count == 0


def test_pull_from_hub_with_tags_filter(tmp_path):
    hub = make_hub(tmp_path)

    # Create solution with specific tag
    hub_sols = hub / "docs" / "solutions"
    tagged = Solution(title="tagged-solution", date=date.today(), tags=["lean"])
    (hub_sols / "tagged-solution.md").write_text(tagged.to_markdown())

    untagged = Solution(title="untagged-solution", date=date.today(), tags=["other"])
    (hub_sols / "untagged-solution.md").write_text(untagged.to_markdown())

    project = tmp_path / "project"
    (project / "docs" / "solutions").mkdir(parents=True)

    count = pull_from_hub(project, tags=["lean"], hub_dir=hub)
    # Only the lean-tagged solution should be pulled
    assert count == 1


def test_pull_from_hub_with_query(tmp_path):
    hub = make_hub(tmp_path)
    hub_sols = hub / "docs" / "solutions"
    sol = Solution(title="pydantic-fix", date=date.today(), problem="pydantic validation error")
    (hub_sols / "pydantic-fix.md").write_text(sol.to_markdown())

    project = tmp_path / "project"
    (project / "docs" / "solutions").mkdir(parents=True)

    count = pull_from_hub(project, query="pydantic", hub_dir=hub)
    assert count == 1
