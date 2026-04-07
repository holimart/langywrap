"""Memento Skills — skills as the memory unit for agent learning.

Skills are structured files (markdown commands, Python helpers, bash scripts,
prompt templates) that carry utility scores. The library tracks usage success/failure
and the reflect_and_write loop creates new skills from task results.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langywrap.router.router import ExecutionRouter


class Skill(BaseModel):
    """A single skill in the library."""

    name: str
    description: str
    type: str = "command"  # command, agent, helper, prompt_template
    file_path: Path = Path(".")
    utility_score: float = 0.5
    success_count: int = 0
    failure_count: int = 0
    tags: list[str] = Field(default_factory=list)
    language: str = "markdown"  # python, bash, lean, markdown, yaml
    category: str = "general"  # quality, security, data, lean, meta, compound
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_used: datetime | None = None
    version: int = 1


class SkillLibrary:
    """Manages the skill catalog with utility-based selection and evolution."""

    def __init__(self, library_dir: Path) -> None:
        self.library_dir = Path(library_dir)
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_path = self.library_dir / "catalog.json"
        self._skills: dict[str, Skill] = {}
        self._load_catalog()

    def _load_catalog(self) -> None:
        if self.catalog_path.exists():
            try:
                data = json.loads(self.catalog_path.read_text())
                for name, entry in data.items():
                    if isinstance(entry.get("created_at"), str):
                        entry["created_at"] = datetime.fromisoformat(entry["created_at"])
                    if isinstance(entry.get("last_used"), str):
                        entry["last_used"] = datetime.fromisoformat(entry["last_used"])
                    if "file_path" in entry:
                        entry["file_path"] = Path(entry["file_path"])
                    self._skills[name] = Skill(**entry)
            except Exception:
                pass

    def _save_catalog(self) -> None:
        data = {}
        for name, skill in self._skills.items():
            entry = skill.model_dump()
            entry["created_at"] = entry["created_at"].isoformat()
            if entry["last_used"]:
                entry["last_used"] = entry["last_used"].isoformat()
            entry["file_path"] = str(entry["file_path"])
            data[name] = entry
        self.catalog_path.write_text(json.dumps(data, indent=2))

    def register(self, skill: Skill) -> None:
        """Add or update a skill in the catalog."""
        self._skills[skill.name] = skill
        self._save_catalog()

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def all_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def search(
        self,
        query: str = "",
        tags: list[str] | None = None,
        category: str | None = None,
        language: str | None = None,
    ) -> list[Skill]:
        """Search skills by keyword, tags, category, language."""
        results = self.all_skills()
        if query:
            q = query.lower()
            results = [
                s
                for s in results
                if q in s.name.lower() or q in s.description.lower() or q in " ".join(s.tags)
            ]
        if tags:
            tag_set = set(tags)
            results = [s for s in results if tag_set.intersection(s.tags)]
        if category:
            results = [s for s in results if s.category == category]
        if language:
            results = [s for s in results if s.language == language]
        return sorted(results, key=lambda s: s.utility_score, reverse=True)

    def get_by_utility(self, min_score: float = 0.5, n: int = 10) -> list[Skill]:
        """Top N skills by utility score."""
        above = [s for s in self.all_skills() if s.utility_score >= min_score]
        return sorted(above, key=lambda s: s.utility_score, reverse=True)[:n]

    def record_usage(self, skill_name: str, success: bool) -> None:
        """Update utility score after a skill is used."""
        skill = self._skills.get(skill_name)
        if not skill:
            return

        if success:
            skill.success_count += 1
        else:
            skill.failure_count += 1

        total = skill.success_count + skill.failure_count
        skill.utility_score = skill.success_count / total if total > 0 else 0.5
        skill.last_used = datetime.now(timezone.utc)
        self._save_catalog()

    def reflect_and_write(
        self,
        task_result: dict[str, Any],
        router: ExecutionRouter,
    ) -> list[Skill]:
        """The Memento reflect-write loop.

        After a task completes, analyze the result and either:
        (a) update an existing skill's code/prompt
        (b) create a new skill for a gap discovered
        (c) do nothing if no learning

        Uses a cheap model via the router to analyze.
        """
        from langywrap.router.config import StepRole

        existing_skills = [
            {"name": s.name, "description": s.description, "utility": s.utility_score}
            for s in self.get_by_utility(min_score=0.0, n=20)
        ]

        prompt = f"""Analyze this task result and determine if any new skills should be created
or existing skills updated. A skill is a reusable piece of knowledge (a script,
a prompt template, a helper function, or a convention) that helps future tasks.

Task result:
{json.dumps(task_result, indent=2, default=str)[:3000]}

Existing skills (top 20):
{json.dumps(existing_skills, indent=2)[:1000]}

For each new skill or update, output a block:
SKILL_ACTION: create|update
SKILL_NAME: <name>
SKILL_TYPE: command|agent|helper|prompt_template
SKILL_LANGUAGE: python|bash|lean|markdown|yaml
SKILL_CATEGORY: quality|security|data|lean|meta|compound|general
SKILL_DESCRIPTION: <one line>
SKILL_TAGS: tag1,tag2,tag3
SKILL_CONTENT:
<the actual skill content — code, markdown, or prompt>
END_SKILL

If no learning, output: NO_NEW_SKILLS

Be selective — only create skills for genuinely reusable patterns, not one-off fixes.
"""

        try:
            result = router.execute(
                role=StepRole.FINALIZE,  # Use cheap model
                prompt=prompt,
                context={"cycle_type": "reflect"},
            )
            return self._parse_skill_output(result.text)
        except Exception:
            return []

    def _parse_skill_output(self, text: str) -> list[Skill]:
        """Parse LLM output into Skill objects."""
        if "NO_NEW_SKILLS" in text:
            return []

        new_skills: list[Skill] = []
        blocks = text.split("SKILL_ACTION:")

        for block in blocks[1:]:  # skip first empty
            lines = block.strip().splitlines()
            if not lines:
                continue

            fields: dict[str, str] = {}
            content_lines: list[str] = []
            in_content = False

            for line in lines:
                if line.strip() == "END_SKILL":
                    in_content = False
                    continue
                if in_content:
                    content_lines.append(line)
                    continue
                if line.startswith("SKILL_CONTENT:"):
                    in_content = True
                    continue
                if ":" in line:
                    key, _, val = line.partition(":")
                    fields[key.strip()] = val.strip()

            action = lines[0].strip() if lines else "create"
            name = fields.get("SKILL_NAME", "unnamed_skill")
            content = "\n".join(content_lines)

            if action == "update" and name in self._skills:
                # Update existing
                skill = self._skills[name]
                skill.version += 1
                if content:
                    skill.file_path.write_text(content)
                new_skills.append(skill)
            elif action == "create":
                # Write content to file
                ext = {"python": ".py", "bash": ".sh", "lean": ".lean"}.get(
                    fields.get("SKILL_LANGUAGE", "markdown"), ".md"
                )
                file_path = self.library_dir / f"{name}{ext}"
                if content:
                    file_path.write_text(content)

                skill = Skill(
                    name=name,
                    description=fields.get("SKILL_DESCRIPTION", "Auto-generated skill"),
                    type=fields.get("SKILL_TYPE", "helper"),
                    file_path=file_path,
                    language=fields.get("SKILL_LANGUAGE", "markdown"),
                    category=fields.get("SKILL_CATEGORY", "general"),
                    tags=fields.get("SKILL_TAGS", "").split(","),
                )
                self.register(skill)
                new_skills.append(skill)

        return new_skills

    def compose(self, skill_names: list[str]) -> str:
        """Combine multiple skills into a composite prompt/script."""
        parts: list[str] = []
        for name in skill_names:
            skill = self.get(name)
            if not skill:
                continue
            if skill.file_path.exists():
                parts.append(f"# === Skill: {skill.name} ===\n{skill.file_path.read_text()}\n")
            else:
                parts.append(f"# === Skill: {skill.name} ===\n{skill.description}\n")
        return "\n".join(parts)

    def export_for_project(self, project_dir: Path, skill_names: list[str]) -> int:
        """Copy skills to a project's .langywrap/skills/ directory. Returns count exported."""
        target = Path(project_dir) / ".langywrap" / "skills"
        target.mkdir(parents=True, exist_ok=True)
        exported = 0
        for name in skill_names:
            skill = self.get(name)
            if not skill or not skill.file_path.exists():
                continue
            dest = target / skill.file_path.name
            dest.write_text(skill.file_path.read_text())
            exported += 1
        return exported

    def scan_and_register_existing(self, dirs: list[Path]) -> int:
        """Scan directories for existing skill-like files and register them.

        Looks for .claude/commands/*.md, scripts/*.sh, scripts/*.py,
        docs/solutions/*.md, etc.
        """
        registered = 0
        patterns = {
            "*.md": ("command", "markdown"),
            "*.sh": ("helper", "bash"),
            "*.py": ("helper", "python"),
            "*.lean": ("helper", "lean"),
        }

        for d in dirs:
            d = Path(d)
            if not d.exists():
                continue
            for pattern, (skill_type, language) in patterns.items():
                for f in d.glob(pattern):
                    if f.name.startswith("_") or f.name.startswith("."):
                        continue
                    name = f.stem
                    if name not in self._skills:
                        category = self._infer_category(f)
                        skill = Skill(
                            name=name,
                            description=f"Auto-discovered from {f.relative_to(f.parent.parent)}",
                            type=skill_type,
                            file_path=f,
                            language=language,
                            category=category,
                            tags=["auto-discovered"],
                        )
                        self.register(skill)
                        registered += 1
        return registered

    @staticmethod
    def _infer_category(path: Path) -> str:
        """Infer skill category from file path."""
        parts = str(path).lower()
        if "security" in parts or "guard" in parts or "harden" in parts:
            return "security"
        if "lean" in parts:
            return "lean"
        if "quality" in parts or "lint" in parts or "test" in parts:
            return "quality"
        if "data" in parts or "duckdb" in parts:
            return "data"
        if "compound" in parts or "solution" in parts:
            return "compound"
        if "meta" in parts or "agent" in parts:
            return "meta"
        return "general"
