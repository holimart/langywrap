"""Solution store — manages docs/solutions/ in projects and the hub.

Each solution is a markdown file with YAML frontmatter capturing a
reusable lesson, pattern, or fix discovered during work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml


@dataclass
class Solution:
    """A single compound engineering solution entry."""

    title: str
    date: date
    tags: list[str] = field(default_factory=list)
    problem: str = ""
    solution: str = ""
    symptoms: str = ""
    affected_files: list[str] = field(default_factory=list)
    applies_to: str = ""
    time_to_discover: str = ""
    agent_note: str = ""
    file_path: Path | None = None
    project_origin: str = ""

    def to_markdown(self) -> str:
        frontmatter = {
            "date": self.date.isoformat(),
            "tags": self.tags,
            "problem": self.problem,
            "solution": self.solution,
            "symptoms": self.symptoms,
            "affected-files": self.affected_files,
            "applies-to": self.applies_to,
            "time-to-discover": self.time_to_discover,
            "agent-note": self.agent_note,
            "project-origin": self.project_origin,
        }
        fm = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
        return f"---\n{fm}---\n\n# {self.title}\n\n{self.solution}\n"

    @classmethod
    def from_file(cls, path: Path) -> Solution:
        text = path.read_text()
        # Parse YAML frontmatter
        match = re.match(r"^---\n(.+?)\n---\n", text, re.DOTALL)
        if not match:
            return cls(title=path.stem, date=date.today(), file_path=path)

        fm = yaml.safe_load(match.group(1)) or {}
        d = fm.get("date", date.today())
        if isinstance(d, str):
            d = date.fromisoformat(d)

        return cls(
            title=path.stem,
            date=d,
            tags=fm.get("tags", []),
            problem=fm.get("problem", ""),
            solution=fm.get("solution", ""),
            symptoms=fm.get("symptoms", ""),
            affected_files=fm.get("affected-files", []),
            applies_to=fm.get("applies-to", ""),
            time_to_discover=fm.get("time-to-discover", ""),
            agent_note=fm.get("agent-note", ""),
            project_origin=fm.get("project-origin", ""),
            file_path=path,
        )


class SolutionStore:
    """Manages a docs/solutions/ directory."""

    def __init__(self, solutions_dir: Path) -> None:
        self.solutions_dir = Path(solutions_dir)
        self.solutions_dir.mkdir(parents=True, exist_ok=True)
        self.template_path = self.solutions_dir / "_template.md"
        self._ensure_template()

    def _ensure_template(self) -> None:
        if not self.template_path.exists():
            self.template_path.write_text(
                Solution(
                    title="Template",
                    date=date.today(),
                    tags=["template"],
                    problem="Describe the problem",
                    solution="Describe the solution",
                ).to_markdown()
            )

    def all_solutions(self) -> list[Solution]:
        solutions = []
        for f in sorted(self.solutions_dir.glob("*.md")):
            if f.name.startswith("_"):
                continue
            try:
                solutions.append(Solution.from_file(f))
            except Exception:
                continue
        return solutions

    def search(self, query: str = "", tags: list[str] | None = None) -> list[Solution]:
        results = self.all_solutions()
        if query:
            q = query.lower()
            results = [
                s for s in results
                if q in s.title.lower()
                or q in s.problem.lower()
                or q in s.solution.lower()
                or q in " ".join(s.tags).lower()
            ]
        if tags:
            tag_set = set(tags)
            results = [s for s in results if tag_set.intersection(s.tags)]
        return results

    def add(self, solution: Solution) -> Path:
        """Add a solution. Returns the file path."""
        filename = f"{solution.date.isoformat()}_{_slugify(solution.title)}.md"
        path = self.solutions_dir / filename
        path.write_text(solution.to_markdown())
        solution.file_path = path
        return path

    def count(self) -> int:
        return len([f for f in self.solutions_dir.glob("*.md") if not f.name.startswith("_")])


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]
