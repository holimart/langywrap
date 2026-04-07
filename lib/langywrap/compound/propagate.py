"""Propagate lessons between projects and the langywrap hub.

push_to_hub: copies a solution from a downstream project to langywrap/docs/solutions/
pull_from_hub: copies relevant solutions from the hub to a project
"""

from __future__ import annotations

import shutil
from pathlib import Path

from langywrap.compound.solutions import Solution, SolutionStore


def find_hub_dir() -> Path | None:
    """Find langywrap hub directory. Checks common locations."""
    candidates = [
        Path.home() / ".langywrap" / "hub_path",  # Stored during install
        Path("/mnt/work4t/Projects/langywrap"),
        Path.home() / "Projects" / "langywrap",
    ]

    for c in candidates:
        if c.suffix == "":
            solutions = c / "docs" / "solutions"
            if solutions.exists():
                return c
        elif c.exists():
            # File containing path
            hub = Path(c.read_text().strip())
            if (hub / "docs" / "solutions").exists():
                return hub
    return None


def push_to_hub(
    solution_path: Path,
    hub_dir: Path | None = None,
    project_name: str = "",
) -> Path | None:
    """Push a solution from a downstream project to the langywrap hub.

    Returns the destination path, or None if hub not found.
    """
    hub = hub_dir or find_hub_dir()
    if not hub:
        return None

    hub_solutions = hub / "docs" / "solutions"
    hub_solutions.mkdir(parents=True, exist_ok=True)

    solution = Solution.from_file(Path(solution_path))
    if project_name:
        solution.project_origin = project_name

    store = SolutionStore(hub_solutions)
    return store.add(solution)


def pull_from_hub(
    project_dir: Path,
    tags: list[str] | None = None,
    query: str = "",
    hub_dir: Path | None = None,
) -> int:
    """Pull relevant solutions from the hub to a project's docs/solutions/.

    Returns count of solutions copied.
    """
    hub = hub_dir or find_hub_dir()
    if not hub:
        return 0

    hub_store = SolutionStore(hub / "docs" / "solutions")
    project_store = SolutionStore(Path(project_dir) / "docs" / "solutions")

    existing_titles = {s.title for s in project_store.all_solutions()}
    matches = hub_store.search(query=query, tags=tags)

    copied = 0
    for solution in matches:
        if solution.title not in existing_titles and solution.file_path:
            dest = project_store.solutions_dir / solution.file_path.name
            shutil.copy2(solution.file_path, dest)
            copied += 1

    return copied
