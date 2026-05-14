"""Read-only Ralph task database helpers.

This module intentionally starts as a Markdown-backed snapshot layer.  It does
not mutate tasks, reorder priorities, claim work, or replace finalize.  Its
first job is to make deterministic state summaries available without spending
an LLM call on ORIENT.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TaskRecord:
    """A task parsed from a Ralph-style Markdown queue."""

    task_id: str
    title: str
    priority: str = "P2"
    status: str = "PENDING"
    line: int = 0
    body: str = ""
    raw_heading: str = ""
    task_refs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    dependency_hints: tuple[str, ...] = ()

    @property
    def is_open(self) -> bool:
        status = self.status.upper()
        return not any(
            word in status
            for word in ("COMPLETED", "CLOSED", "RESOLVED", "ABANDONED", "INVALIDATED")
        )

    @property
    def is_blocked(self) -> bool:
        text = f"{self.status}\n{self.body}".lower()
        return any(word in text for word in ("blocked", "externally blocked", "pending external"))

    def is_actionable(self, tasks_by_id: dict[str, TaskRecord]) -> bool:
        """Return true when this task has no open in-queue prerequisites."""
        if self.is_blocked:
            return False
        for dep_id in self.depends_on:
            dep = tasks_by_id.get(dep_id)
            if dep and dep.is_open:
                return False
        return True


@dataclass(frozen=True)
class ProgressEntry:
    """A parsed cycle entry from progress.md."""

    cycle: int
    title: str = ""
    outcome: str = ""
    rigor: str = ""
    lean_status: str = ""
    key_insight: str = ""
    next_step: str = ""
    body: str = ""


@dataclass(frozen=True)
class LeanSnapshot:
    """Cheap source-level Lean dashboard."""

    total_sorries: int = 0
    files_with_sorries: int = 0
    top_files: tuple[tuple[str, int], ...] = ()
    axiom_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class RalphSnapshot:
    """Read-only state snapshot used to render native orient output."""

    cycle: int
    tasks: tuple[TaskRecord, ...]
    recent_progress: tuple[ProgressEntry, ...]
    blocked_tasks: tuple[TaskRecord, ...] = ()
    plan_preview: str = ""
    verdict_flags: tuple[str, ...] = ()
    lean: LeanSnapshot = field(default_factory=LeanSnapshot)
    stagnation_warning: str = ""


class TaskDB:
    """Markdown-backed read-only task/progress snapshotter."""

    _PRIORITY_ORDER = {"P0": 0, "P1-R": 1, "P1": 2, "P2": 3, "P3": 4}

    def __init__(self, project_dir: Path, state_dir: Path) -> None:
        self.project_dir = project_dir.resolve()
        self.state_dir = state_dir.resolve()
        self.tasks_path = self.state_dir / "tasks.md"
        self.progress_path = self.state_dir / "progress.md"
        self.plan_path = self.state_dir / "plan.md"
        self.steps_dir = self.state_dir / "steps"

    def snapshot(self, max_recent_cycles: int = 5, max_tasks: int = 12) -> RalphSnapshot:
        """Build a deterministic, read-only Ralph state snapshot."""
        parsed_tasks = self.parse_tasks()
        selected_tasks = self._select_top_tasks(parsed_tasks, max_tasks=max_tasks)
        tasks_by_id = {task.task_id: task for task in parsed_tasks}
        actionable = tuple(task for task in selected_tasks if task.is_actionable(tasks_by_id))
        blocked = tuple(task for task in selected_tasks if not task.is_actionable(tasks_by_id))
        recent = tuple(self.parse_progress()[:max_recent_cycles])
        cycle = recent[0].cycle + 1 if recent else 1
        return RalphSnapshot(
            cycle=cycle,
            tasks=actionable,
            blocked_tasks=blocked,
            recent_progress=recent,
            plan_preview=self._plan_preview(),
            verdict_flags=tuple(self._verdict_flags()),
            lean=self._lean_snapshot(),
            stagnation_warning=self._stagnation_warning(recent),
        )

    def parse_tasks(self) -> list[TaskRecord]:
        """Parse checkbox and heading-style tasks from tasks.md."""
        if not self.tasks_path.exists():
            return []
        lines = self.tasks_path.read_text(encoding="utf-8").splitlines()
        records: list[TaskRecord] = []

        i = 0
        while i < len(lines):
            line = lines[i]
            heading = re.match(r"^\s*#{1,6}\s+(.*task:[A-Za-z0-9._-]+.*)$", line)
            checkbox = re.match(r"^\s*-\s*\[([ xX])\]\s+(.*task:[A-Za-z0-9._-]+.*)$", line)
            if not heading and not checkbox:
                i += 1
                continue

            end = i + 1
            while end < len(lines):
                if end > i and re.match(r"^\s*#{1,6}\s+", lines[end]):
                    break
                if re.match(r"^\s*---\s*$", lines[end]):
                    break
                end += 1

            block = lines[i:end]
            record = self._task_from_block(
                block, line_no=i + 1, checked=checkbox.group(1) if checkbox else ""
            )
            if record:
                records.append(record)
            i = end + 1 if end < len(lines) and re.match(r"^\s*---\s*$", lines[end]) else end

        return records

    def parse_progress(self) -> list[ProgressEntry]:
        """Parse progress.md entries newest-first."""
        if not self.progress_path.exists():
            return []
        text = self.progress_path.read_text(encoding="utf-8")
        matches = list(re.finditer(r"^## Cycle\s+(\d+)\b([^\n]*)", text, re.MULTILINE))
        entries: list[ProgressEntry] = []
        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            entries.append(
                ProgressEntry(
                    cycle=int(match.group(1)),
                    title=match.group(2).strip(" -"),
                    outcome=self._field(body, "Outcome"),
                    rigor=self._field(body, "Rigor achieved"),
                    lean_status=self._field(body, "Lean status"),
                    key_insight=self._field(body, "Key insight"),
                    next_step=self._field(body, "Next"),
                    body=body,
                )
            )
        by_cycle: dict[int, ProgressEntry] = {}
        for entry in entries:
            current = by_cycle.get(entry.cycle)
            if current is None or self._progress_score(entry) > self._progress_score(current):
                by_cycle[entry.cycle] = entry
        return sorted(by_cycle.values(), key=lambda e: e.cycle, reverse=True)

    @staticmethod
    def _progress_score(entry: ProgressEntry) -> int:
        return sum(
            bool(value)
            for value in (
                entry.outcome,
                entry.rigor,
                entry.lean_status,
                entry.key_insight,
                entry.next_step,
            )
        )

    def render_orient(self, *, confirmation_token: str = "") -> str:
        """Render native ORIENT output as Markdown."""
        return render_orient_snapshot(self.snapshot(), confirmation_token=confirmation_token)

    def _task_from_block(
        self, block: list[str], *, line_no: int, checked: str = ""
    ) -> TaskRecord | None:
        raw = block[0]
        task_match = re.search(r"(task:[A-Za-z0-9._-]+)", raw)
        if not task_match:
            return None
        priority_match = re.search(r"\[(P\d(?:-R)?)\]", raw)
        title = re.sub(r"<[^>]+>", "", raw)
        title = re.sub(r"^\s*(?:#{1,6}|-\s*\[[ xX]\])\s*", "", title).strip()
        status = "COMPLETED" if checked.lower() == "x" else "PENDING"
        for line in block[1:10]:
            if "**Status:**" in line:
                status = re.sub(r".*\*\*Status:\*\*\s*", "", line).strip()
                break
            status_line = re.match(r"^\s*-\s*Status:\s*(.*)$", line)
            if status_line:
                status = status_line.group(1).strip()
                break
        body = "\n".join(block[1:])
        return TaskRecord(
            task_id=task_match.group(1),
            title=title,
            priority=priority_match.group(1) if priority_match else "P2",
            status=status,
            line=line_no,
            body="\n".join(block[1:12]),
            raw_heading=raw,
            task_refs=self._task_refs(body),
            depends_on=self._depends_on(body),
            dependency_hints=self._dependency_hints(body),
        )

    def _select_top_tasks(self, tasks: list[TaskRecord], *, max_tasks: int) -> list[TaskRecord]:
        open_tasks = [task for task in tasks if task.is_open]
        tasks_by_id = {task.task_id: task for task in tasks}
        return sorted(
            open_tasks,
            key=lambda task: (
                not task.is_actionable(tasks_by_id),
                self._PRIORITY_ORDER.get(task.priority, 99),
                task.line,
            ),
        )[:max_tasks]

    @staticmethod
    def _task_refs(text: str) -> tuple[str, ...]:
        refs = sorted(set(re.findall(r"task:[A-Za-z0-9._-]+", text)))
        return tuple(refs[:8])

    @staticmethod
    def _depends_on(text: str) -> tuple[str, ...]:
        deps: list[str] = []
        patterns = (
            r"(?im)^\s*(?:[-*]\s*)?(?:depends on|requires|prerequisite(?:s)?|blocked by)\s*:?\s*(.*)$",
            r"(?im)^\s*(?:[-*]\s*)?.*\bbefore\b\s+(?:retry|revisiting|re-attempting|downstream|endpoint|map|tail).*$",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                deps.extend(re.findall(r"task:[A-Za-z0-9._-]+", match.group(0)))
        return tuple(sorted(set(deps))[:8])

    @staticmethod
    def _dependency_hints(text: str) -> tuple[str, ...]:
        hints: list[str] = []
        for line in text.splitlines():
            clean = line.strip(" -*")
            lowered = clean.lower()
            if not clean:
                continue
            if (
                any(
                    word in lowered
                    for word in (
                        "depends on",
                        "requires",
                        "blocked",
                        "prerequisite",
                        "before",
                        "after",
                    )
                )
                or "->" in clean
                and re.search(r"\bH_[A-Za-z0-9_-]+", clean)
            ):
                hints.append(clean[:220])
            if len(hints) >= 4:
                break
        return tuple(hints)

    @staticmethod
    def _field(body: str, name: str) -> str:
        match = re.search(
            rf"^(?:\*\*)?{re.escape(name)}:(?:\*\*)?\s*(.*)$",
            body,
            re.MULTILINE,
        )
        return match.group(1).strip() if match else ""

    def _plan_preview(self) -> str:
        if not self.plan_path.exists():
            return ""
        lines = [line.strip() for line in self.plan_path.read_text(encoding="utf-8").splitlines()]
        skip_prefixes = ("#", "```", "orchestrator:", "execute_type:", "decision_reason:")
        meaningful = [
            line
            for line in lines
            if line and not any(line.startswith(prefix) for prefix in skip_prefixes)
        ]
        return meaningful[0][:240] if meaningful else ""

    def _verdict_flags(self) -> list[str]:
        flags: list[str] = []
        for name in ("validate", "critic", "adversarial"):
            path = self.steps_dir / f"{name}.md"
            if not path.exists():
                flags.append(f"{name}: absent")
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            matches = sorted(
                set(
                    re.findall(
                        r"\b(VALIDATED|CONCERNS|LIKELY INVALID|ALREADY KNOWN|SOUND|FLAWED|FATAL|BROKEN)\b",
                        text,
                        re.IGNORECASE,
                    )
                )
            )
            flags.append(f"{name}: {', '.join(matches) if matches else 'present/no verdict found'}")
        return flags

    def _lean_snapshot(self) -> LeanSnapshot:
        roots = [self.project_dir / "research", self.project_dir / "math-for-transcendentals"]
        counts: list[tuple[str, int]] = []
        axiom_files: set[str] = set()
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*.lean"):
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                count = text.count("sorry")
                if count:
                    counts.append((str(path.relative_to(self.project_dir)), count))
                if re.search(r"(?m)^\s*(?:noncomputable\s+)?axiom\b", text):
                    axiom_files.add(str(path.relative_to(self.project_dir)))
        counts.sort(key=lambda item: item[1], reverse=True)
        return LeanSnapshot(
            total_sorries=sum(count for _, count in counts),
            files_with_sorries=len(counts),
            top_files=tuple(counts[:5]),
            axiom_files=tuple(sorted(axiom_files)[:10]),
        )

    @staticmethod
    def _stagnation_warning(recent: tuple[ProgressEntry, ...]) -> str:
        if len(recent) < 4:
            return ""
        last4 = recent[:4]
        lean_words = re.compile(r"sorry|skeleton|critic review|axiom|port|formaliz", re.IGNORECASE)
        if all(
            lean_words.search(entry.lean_status + " " + entry.title + " " + entry.next_step)
            for entry in last4
        ):
            return "STAGNATION DETECTED: Last 4+ cycles look Lean-heavy. MANDATORY RESEARCH CYCLE."
        return ""


def render_orient_snapshot(snapshot: RalphSnapshot, *, confirmation_token: str = "") -> str:
    """Render a deterministic orient summary from a RalphSnapshot."""
    last = snapshot.recent_progress[0] if snapshot.recent_progress else None
    lines: list[str] = [
        f"# Cycle {snapshot.cycle} Orient Summary",
        "",
        "## Snapshot",
        f"- Cycle: {snapshot.cycle}",
        f"- Last completed cycle: {last.cycle if last else 'unknown'}",
        f"- Last cycle outcome: {last.outcome if last and last.outcome else 'unknown'}",
    ]
    if snapshot.stagnation_warning:
        lines += ["", f"WARNING: {snapshot.stagnation_warning}"]

    lines += _planning_brief(snapshot)

    lines += ["", "## Recent Progress"]
    if snapshot.recent_progress:
        for entry in snapshot.recent_progress[:5]:
            insight = entry.key_insight or entry.next_step or entry.title or "no summary"
            lines.append(f"- Cycle {entry.cycle}: {entry.outcome or 'UNKNOWN'}; {insight}")
    else:
        lines.append("- No progress entries found.")

    lines += ["", "## Lean Status"]
    lean = snapshot.lean
    lines += [
        f"- Source-level sorry count: {lean.total_sorries}",
        f"- Files with sorries: {lean.files_with_sorries}",
    ]
    if lean.top_files:
        lines.append("- Largest sorry files:")
        for path, count in lean.top_files:
            lines.append(f"  - `{path}`: {count}")
    else:
        lines.append("- Largest sorry files: none found")
    if lean.axiom_files:
        lines.append(
            "- Axiom-bearing files detected: " + ", ".join(f"`{p}`" for p in lean.axiom_files[:5])
        )
    else:
        lines.append("- Axiom-bearing files detected: none found")
    lines.append(
        "- Build status: not run by native orient; use configured gates/checks for compilation evidence."
    )

    lines += ["", "## Most Promising Actionable Tasks"]
    if snapshot.tasks:
        for task in snapshot.tasks[:5]:
            lines.append(f"- `{task.task_id}` ({task.priority}, {task.status}) - {task.title}")
            if task.depends_on:
                lines.append(
                    "  Depends on: " + ", ".join(f"`{dep}`" for dep in task.depends_on[:4])
                )
            if task.dependency_hints:
                lines.append(f"  Dependency hint: {task.dependency_hints[0]}")
            elif task.task_refs:
                lines.append(
                    "  Related tasks: " + ", ".join(f"`{ref}`" for ref in task.task_refs[:4])
                )
    else:
        lines.append("- No actionable open tasks parsed from tasks.md.")

    if snapshot.blocked_tasks:
        lines += ["", "## Deferred Blocked/Dependent Tasks"]
        for task in snapshot.blocked_tasks[:5]:
            reason = "explicit blocked status"
            if task.depends_on:
                reason = "open prerequisite(s): " + ", ".join(
                    f"`{dep}`" for dep in task.depends_on[:4]
                )
            lines.append(f"- `{task.task_id}` ({task.priority}) - {reason}")

    lines += ["", "## Verdict Flags"]
    lines.extend(f"- {flag}" for flag in snapshot.verdict_flags)

    lines += ["", "## Recommended Focus"]
    if last and last.next_step:
        lines.append(last.next_step)
    elif snapshot.tasks:
        lines.append(
            f"Start from `{snapshot.tasks[0].task_id}` unless PLAN has a stronger reason to branch."
        )
    else:
        lines.append("No recommendation available from deterministic state.")

    if snapshot.plan_preview:
        lines += ["", "## Current Plan Preview", snapshot.plan_preview]

    if confirmation_token:
        lines += ["", f"{confirmation_token} native_orient=true"]
    return "\n".join(lines) + "\n"


def _planning_brief(snapshot: RalphSnapshot) -> list[str]:
    """Render deterministic high-level guidance for the PLAN step."""
    lines = ["", "## Planning Brief"]
    actionable = [task for task in snapshot.tasks if task.is_open]
    blocked = list(snapshot.blocked_tasks)
    last = snapshot.recent_progress[0] if snapshot.recent_progress else None

    if actionable:
        task = actionable[0]
        lines.append(
            f"- Highest actionable task: `{task.task_id}` ({task.priority}) - {task.title}"
        )
    elif blocked:
        task = blocked[0]
        lines.append(
            f"- Highest-priority open task appears blocked/dependent: `{task.task_id}` ({task.priority}) - {task.title}"
        )
    else:
        lines.append("- No open parsed tasks; inspect tasks.md manually.")

    if blocked:
        lines.append(
            "- Blocked high-priority tasks exist; PLAN should avoid repeating blocked routes unless new evidence is available."
        )
    if last and "RESEARCH CYCLE RECOMMENDED" in last.next_step:
        lines.append(
            "- Latest finalize guidance recommends a research cycle; weigh this against any P0 governance guards."
        )
    if last and last.next_step:
        lines.append(f"- Latest next-step instruction: {last.next_step[:260]}")
    return lines
