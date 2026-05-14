"""
langywrap.ralph.state — Persistent state management for the Ralph loop.

Handles tasks.md, progress.md, plan.md, and cycle_count.txt.
The key pattern: build_orient_context() pre-digests state files for ~11x
token compression (pending tasks only + last 3 cycle summaries).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from langywrap.ralph.markdown_todo import CHECKBOX_PREFIX_RE, UNIFIED_TASK_LINE_RE

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EXHAUSTED = "EXHAUSTED"


class TaskPriority(StrEnum):
    P0 = "P0"  # critical / blocker
    P1 = "P1"  # high
    P2 = "P2"  # normal
    P3 = "P3"  # low / nice-to-have


# ---------------------------------------------------------------------------
# TaskEntry
# ---------------------------------------------------------------------------


@dataclass
class TaskEntry:
    id: str
    title: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.P2
    metadata: dict = field(default_factory=dict)
    raw_line: str = ""

    @property
    def is_pending(self) -> bool:
        return self.status == TaskStatus.PENDING

    @property
    def checkbox(self) -> str:
        return "x" if self.status == TaskStatus.COMPLETED else " "


# ---------------------------------------------------------------------------
# CycleResult
# ---------------------------------------------------------------------------


@dataclass
class CycleResult:
    cycle_number: int
    steps_completed: dict[str, Path] = field(default_factory=dict)
    """Map of step_name → output file path for each successfully completed step."""

    quality_gate_passed: bool | None = None
    """None if no quality gate configured."""

    git_commit_hash: str | None = None
    """Short commit hash, or None if no commit was made."""

    duration_seconds: float = 0.0
    models_used: dict[str, str] = field(default_factory=dict)
    """Map of step_name → model string used."""

    confirmed_tokens: dict[str, bool] = field(default_factory=dict)
    """Map of step_name → whether confirmation token was found."""

    rate_limited: bool = False
    """True if any step returned a rate-limit response this cycle."""

    auth_failed: bool = False
    """True if any step returned a provider-auth failure (e.g. opencode OAuth
    refresh 401). Terminal — the loop should stop immediately without retries."""

    auth_failed_snippet: str = ""
    """Literal snippet captured from the failing step's output. Empty unless
    ``auth_failed`` is True."""

    input_tokens: int = 0
    """Total input tokens across all steps this cycle."""
    output_tokens: int = 0
    """Total output tokens across all steps this cycle."""
    tokens_by_model: dict[str, tuple[int, int]] = field(default_factory=dict)
    """Map of model_name → (input_tokens, output_tokens) accumulated this cycle."""
    files_accessed: dict[str, list[str]] = field(default_factory=dict)
    """Map of step_name → list of file paths accessed."""

    @property
    def fully_confirmed(self) -> bool:
        """True if every step produced its confirmation token."""
        return all(self.confirmed_tokens.values()) if self.confirmed_tokens else False

    @property
    def step_names_completed(self) -> list[str]:
        return list(self.steps_completed.keys())


def validate_injected_task_content(content: str, *, source: str) -> None:
    """Reject injected task templates that would create non-unified checkboxes."""
    checkbox_lines = [line for line in content.splitlines() if CHECKBOX_PREFIX_RE.match(line)]
    if not checkbox_lines:
        raise ValueError(f"{source} must include a unified checkbox task line")
    for line in checkbox_lines:
        if not UNIFIED_TASK_LINE_RE.match(line):
            raise ValueError(
                f"{source} checkbox line must match unified format: "
                "`- [ ] **[Pn] task:slug** [task_type] label`; "
                f"got {line!r}"
            )


def render_hygiene_task_content(
    cycle_num: int,
    *,
    template: str = "",
    quality_gate_cmd: str = "",
    today: str | None = None,
) -> str:
    """Render a hygiene task block without mutating tasks.md."""
    marker = f"hygiene-cycle-{cycle_num}"
    rendered_date = today or datetime.now().strftime("%Y-%m-%d")
    qg = quality_gate_cmd or "run quality checks"

    if template:
        return template.format(
            cycle=cycle_num,
            date=rendered_date,
            quality_gate_cmd=qg,
        )
    return (
        f"\n- [ ] **[P2] task:{marker}** [hygiene] "
        f"Technical hygiene — cycle {cycle_num} "
        f"<!-- {marker} -->\n"
        f"  - Status: PENDING\n"
        f"  - Added: {rendered_date} | Source: langywrap (scheduled hygiene)\n"
        f"  - Why: Scheduled maintenance every N cycles\n"
        f"  - Definition of done:\n"
        f"    1. Run `{qg}` — fix ALL lint, type, and test failures\n"
        f"    2. Review progress.md for TODO/debt callouts\n"
        f"    3. Clean up any temporary files or dead code\n"
        f"    4. Verify project still builds and tests pass\n\n"
    )


# ---------------------------------------------------------------------------
# RalphState
# ---------------------------------------------------------------------------


class RalphState:
    """Manages all file I/O for the ralph loop state directory."""

    def __init__(
        self,
        state_dir: Path,
        *,
        tasks_file: Path | None = None,
        progress_file: Path | None = None,
    ) -> None:
        self.state_dir = state_dir.resolve()
        self.tasks_file = (tasks_file or self.state_dir / "tasks.md").resolve()
        self.progress_file = (progress_file or self.state_dir / "progress.md").resolve()
        self.plan_file = self.state_dir / "plan.md"
        self.cycle_file = self.state_dir / "cycle_count.txt"
        self.steps_dir = self.state_dir / "steps"
        self.logs_dir = self.state_dir / "logs"

        # Ensure directories exist
        self.steps_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------

    def load_tasks(self) -> list[TaskEntry]:
        """Parse tasks.md and return all TaskEntry objects."""
        if not self.tasks_file.exists():
            return []
        text = self.tasks_file.read_text(encoding="utf-8")
        tasks: list[TaskEntry] = []
        lines = text.splitlines()
        for line in lines:
            entry = self._parse_task_line(line)
            if entry is not None:
                tasks.append(entry)
        tasks.extend(entry for _, _, entry in self._parse_heading_task_blocks(lines))
        return tasks

    def save_tasks(self, tasks: list[TaskEntry]) -> None:
        """Rewrite tasks.md updating checkbox lines in-place."""
        if not self.tasks_file.exists():
            return
        text = self.tasks_file.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)

        # Build a lookup of id → task
        by_id = {t.id: t for t in tasks}

        new_lines: list[str] = []
        for line in lines:
            entry = self._parse_task_line(line.rstrip("\n"))
            if entry is not None and entry.id in by_id:
                updated = by_id[entry.id]
                # Replace the checkbox
                new_line = re.sub(
                    r"^(\s*-\s*\[)[ x](\])",
                    rf"\g<1>{updated.checkbox}\2",
                    line.rstrip("\n"),
                )
                new_lines.append(new_line + "\n")
            else:
                new_lines.append(line if line.endswith("\n") else line + "\n")

        self.tasks_file.write_text("".join(new_lines), encoding="utf-8")

    def mark_task_completed(self, task_id: str, cycle_num: int) -> bool:
        """Mark a specific task as COMPLETED in tasks.md. Returns True if found."""
        if not self.tasks_file.exists():
            return False
        text = self.tasks_file.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)

        for idx, line in enumerate(lines):
            entry = self._parse_task_line(line.rstrip("\n"))
            if entry is not None and entry.id == task_id:
                new_line = re.sub(
                    r"^(\s*-\s*\[)[ x](\])",
                    r"\g<1>x\2",
                    line.rstrip("\n"),
                )
                if f"(cycle {cycle_num})" not in new_line:
                    new_line = new_line.rstrip() + f" (cycle {cycle_num})"
                lines[idx] = new_line + "\n"
                self.tasks_file.write_text("".join(lines), encoding="utf-8")
                return True

        plain_lines = [line.rstrip("\n") for line in lines]
        for start, end, entry in self._parse_heading_task_blocks(plain_lines):
            if entry.id != task_id:
                continue

            for idx in range(start + 1, end):
                if "**Status:**" in plain_lines[idx]:
                    status_line = re.sub(
                        r"(\*\*Status:\*\*\s*).*$",
                        rf"\1✅ **COMPLETED** (cycle {cycle_num})",
                        plain_lines[idx],
                    )
                    lines[idx] = status_line + "\n"
                    self.tasks_file.write_text("".join(lines), encoding="utf-8")
                    return True

        return False

    _UNCHECKED_RE = re.compile(r"^\s*(?:-|#{1,6})\s*\[ \]", re.MULTILINE)

    def pending_count(self) -> int:
        """Count unchecked `- [ ]` or `### [ ]` lines in tasks.md."""
        if not self.tasks_file.exists():
            return 0
        text = self.tasks_file.read_text(encoding="utf-8")
        lines = text.splitlines()
        checkbox_pending = len(self._UNCHECKED_RE.findall(text))
        heading_pending = sum(
            1 for _, _, entry in self._parse_heading_task_blocks(lines) if entry.is_pending
        )
        return checkbox_pending + heading_pending

    # ------------------------------------------------------------------
    # Cycle counter
    # ------------------------------------------------------------------

    def get_cycle_count(self) -> int:
        """Return the current cycle count (0 if file absent)."""
        if not self.cycle_file.exists():
            return 0
        try:
            return int(self.cycle_file.read_text(encoding="utf-8").strip())
        except ValueError:
            return 0

    def increment_cycle(self) -> int:
        """Atomically increment and return the new cycle count."""
        n = self.get_cycle_count() + 1
        self.cycle_file.write_text(str(n) + "\n", encoding="utf-8")
        return n

    def set_cycle_count(self, n: int) -> None:
        self.cycle_file.write_text(str(n) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Progress log
    # ------------------------------------------------------------------

    def append_progress(
        self, cycle_result: CycleResult, task_id: str = "", summary: str = ""
    ) -> None:
        """Append a cycle entry to progress.md."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        entry_lines: list[str] = [
            f"\n## Cycle {cycle_result.cycle_number} — {date_str}",
        ]
        if task_id:
            entry_lines.append(f"Task: {task_id}")

        outcome = self._derive_outcome(cycle_result)
        entry_lines.append(f"Outcome: {outcome}")

        if cycle_result.confirmed_tokens:
            entry_lines.append("\n### Confirmation Chain")
            for step, confirmed in cycle_result.confirmed_tokens.items():
                entry_lines.append(f"- {step.upper()}_CONFIRMED: {'yes' if confirmed else 'NO'}")

        if cycle_result.quality_gate_passed is not None:
            qg = "PASS" if cycle_result.quality_gate_passed else "FAIL"
            entry_lines.append(f"\nQuality gate: {qg}")

        if cycle_result.git_commit_hash:
            entry_lines.append(f"Git commit: {cycle_result.git_commit_hash}")

        entry_lines.append(f"Duration: {cycle_result.duration_seconds:.1f}s")

        if summary:
            entry_lines.append(f"\n### Summary\n{summary}")

        entry_lines.append("")

        text = "\n".join(entry_lines) + "\n"
        with self.progress_file.open("a", encoding="utf-8") as fh:
            fh.write(text)

    # ------------------------------------------------------------------
    # Hygiene task injection
    # ------------------------------------------------------------------

    def inject_hygiene_task(
        self,
        cycle_num: int,
        template: str = "",
        quality_gate_cmd: str = "",
    ) -> bool:
        """Inject a hygiene task into tasks.md if not already present for this cycle.

        Returns True if a task was injected, False if already present or no tasks file.
        """
        if not self.tasks_file.exists():
            return False

        marker = f"hygiene-cycle-{cycle_num}"
        text = self.tasks_file.read_text(encoding="utf-8")
        if marker in text:
            return False

        task_block = render_hygiene_task_content(
            cycle_num,
            template=template,
            quality_gate_cmd=quality_gate_cmd,
        )

        validate_injected_task_content(task_block, source="hygiene task")

        # Insert before "## Completed" section if it exists, else append
        completed_match = re.search(r"^## Completed", text, re.MULTILINE)
        if completed_match:
            insert_pos = completed_match.start()
            text = text[:insert_pos] + task_block + text[insert_pos:]
        else:
            text += task_block

        self.tasks_file.write_text(text, encoding="utf-8")
        return True

    def inject_periodic_task(
        self,
        cycle_num: int,
        marker: str = "periodic",
        content: str = "",
    ) -> bool:
        """Inject a periodic task into tasks.md with dedup by marker.

        Returns True if injected, False if marker already present.
        """
        if not self.tasks_file.exists() or not content:
            return False

        full_marker = f"{marker}-cycle-{cycle_num}"
        text = self.tasks_file.read_text(encoding="utf-8")
        if full_marker in text:
            return False

        # Ensure marker comment is in the content
        if full_marker not in content:
            content = content.rstrip() + f" <!-- {full_marker} -->\n"

        validate_injected_task_content(content, source=f"periodic task `{marker}`")

        # Insert before "## Completed" section if it exists, else append
        completed_match = re.search(r"^## Completed", text, re.MULTILINE)
        if completed_match:
            insert_pos = completed_match.start()
            text = text[:insert_pos] + content + "\n" + text[insert_pos:]
        else:
            text += "\n" + content

        self.tasks_file.write_text(text, encoding="utf-8")
        return True

    # ------------------------------------------------------------------
    # Plan file
    # ------------------------------------------------------------------

    def read_plan(self) -> str:
        """Return current plan.md contents (empty string if absent)."""
        if not self.plan_file.exists():
            return ""
        return self.plan_file.read_text(encoding="utf-8")

    def write_plan(self, content: str) -> None:
        self.plan_file.write_text(content, encoding="utf-8")

    # ------------------------------------------------------------------
    # Step output helpers
    # ------------------------------------------------------------------

    def step_output_path(self, step_name: str) -> Path:
        return self.steps_dir / f"{step_name}.md"

    def read_step_output(self, step_name: str) -> str:
        p = self.step_output_path(step_name)
        if not p.exists():
            return ""
        return p.read_text(encoding="utf-8")

    def clear_steps(self) -> None:
        """Remove all files from steps/ dir (called at start of each cycle)."""
        for f in self.steps_dir.iterdir():
            if f.is_file():
                f.unlink()

    # ------------------------------------------------------------------
    # THE KEY PATTERN: orient context pre-digestion (~11x compression)
    # ------------------------------------------------------------------

    def build_orient_context(self, max_recent_cycles: int = 3) -> str:
        """Pre-digest state files for the ORIENT step.

        Only extracts:
        - tasks.md header (first 80 lines)
        - All pending task blocks (compact, ~12 lines each)
        - Last `max_recent_cycles` cycle entries from progress.md
        - Current plan.md if it exists

        This is pure Python — no LLM involved.  Achieves ~11x token compression
        over feeding the raw files directly (Lesson 44 from riemann2).
        """
        parts: list[str] = [
            "# Pre-Digested State Context (auto-generated by langywrap.ralph)",
            "",
        ]

        # ── tasks.md ───────────────────────────────────────────────────────────
        if self.tasks_file.exists():
            tasks_text = self.tasks_file.read_text(encoding="utf-8")
            tasks_lines = tasks_text.splitlines()
            total_tasks = len(tasks_lines)

            parts += [
                f"> tasks.md: {total_tasks} lines total. Only pending tasks and header shown.",
                "> Do NOT re-read the full file — everything you need is below.",
                "",
                "## Tasks — Header (tasks.md lines 1–80)",
                "",
            ]
            parts.extend(tasks_lines[:80])
            parts += ["", "---", ""]

            # Pending task blocks
            pending_blocks = self._extract_pending_blocks(tasks_lines, context_lines=12)
            parts += [
                "## Pending Tasks (all `- [ ]` items, compact view)",
                "",
            ]
            if pending_blocks:
                parts.extend(pending_blocks)
            else:
                parts.append("(no pending tasks)")
            parts.append("")
        else:
            parts += ["> tasks.md not found.", ""]

        # ── progress.md — last N cycles ────────────────────────────────────────
        if self.progress_file.exists():
            progress_text = self.progress_file.read_text(encoding="utf-8")
            progress_lines = progress_text.splitlines()
            total_progress = len(progress_lines)

            cycle_starts = [
                i for i, line in enumerate(progress_lines) if line.startswith("## Cycle")
            ]

            if cycle_starts:
                start_idx = (
                    cycle_starts[-max_recent_cycles]
                    if len(cycle_starts) >= max_recent_cycles
                    else cycle_starts[0]
                )
            else:
                start_idx = 0

            parts += [
                f"## Recent Progress — Last {max_recent_cycles} Cycles (from progress.md)",
                f"(progress.md: {total_progress} lines total; "
                f"only last {max_recent_cycles} cycles shown)",
                "",
            ]
            parts.extend(progress_lines[start_idx:])
            parts.append("")
        else:
            parts += ["## Recent Progress", "(progress.md not found — first run)", ""]

        # ── plan.md (if it exists and is not empty) ────────────────────────────
        plan = self.read_plan()
        if plan.strip():
            plan_lines = plan.splitlines()
            # Only first 40 lines of plan to keep context tight
            parts += [
                "## Current Plan (plan.md — first 40 lines)",
                "",
            ]
            parts.extend(plan_lines[:40])
            if len(plan_lines) > 40:
                parts.append(f"... ({len(plan_lines) - 40} more lines truncated)")
            parts.append("")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_task_line(line: str) -> TaskEntry | None:
        """Parse a markdown task line like `- [ ] TASK_001` or `### [ ] TASK_001`."""
        m = re.match(r"^\s*(?:-|#{1,6})\s*\[([ x])\]\s+(\S+)\s*(.*)", line)
        if not m:
            return None
        checked, task_id, rest = m.group(1), m.group(2), m.group(3).strip()
        status = TaskStatus.COMPLETED if checked == "x" else TaskStatus.PENDING
        return TaskEntry(
            id=task_id,
            title=rest or task_id,
            status=status,
            raw_line=line,
        )

    @staticmethod
    def _parse_heading_task_blocks(lines: list[str]) -> list[tuple[int, int, TaskEntry]]:
        """Parse heading-style task blocks used by research queues.

        Supported format:
        `### **[P1-R] task:foo**`
        followed by a `**Status:** OPEN|PENDING|...` line.
        """
        result: list[tuple[int, int, TaskEntry]] = []
        total = len(lines)
        i = 0

        while i < total:
            line = lines[i]
            if not re.match(r"^\s*#{1,6}\s+", line):
                i += 1
                continue

            task_match = re.search(r"(task:[A-Za-z0-9._-]+)", line)
            if not task_match:
                i += 1
                continue

            end = i + 1
            while end < total:
                if re.match(r"^\s*---\s*$", lines[end]):
                    break
                if end > i and re.match(r"^\s*#{1,6}\s+", lines[end]):
                    break
                end += 1

            status = TaskStatus.PENDING
            status_line = ""
            for j in range(i + 1, min(end, i + 8)):
                if "**Status:**" in lines[j]:
                    status_line = lines[j]
                    break

            normalized_status = status_line.upper()
            if (
                "COMPLETED" in normalized_status
                or "RESOLVED" in normalized_status
                or "CLOSED" in normalized_status
                or "INVALIDATED" in normalized_status
                or "~~" in line
            ):
                status = TaskStatus.COMPLETED
            elif "IN PROGRESS" in normalized_status or "IN_PROGRESS" in normalized_status:
                status = TaskStatus.IN_PROGRESS
            elif (
                "OPEN" in normalized_status
                or "PENDING" in normalized_status
                or "ACTIVE" in normalized_status
                or "PARTIAL" in normalized_status
                or status_line == ""
            ):
                status = TaskStatus.PENDING

            result.append(
                (
                    i,
                    end,
                    TaskEntry(
                        id=task_match.group(1),
                        title=line.strip(),
                        status=status,
                        raw_line=line,
                    ),
                )
            )
            i = end + 1 if end < total and re.match(r"^\s*---\s*$", lines[end]) else end

        return result

    @staticmethod
    def _extract_pending_blocks(lines: list[str], context_lines: int = 12) -> list[str]:
        """For each unchecked checkbox line, extract a block of context around it."""
        total = len(lines)
        result: list[str] = []
        for i, line in enumerate(lines):
            if re.match(r"^\s*(?:-|#{1,6})\s*\[ \]", line):
                start = max(0, i - 2)
                end = min(total, i + context_lines)
                result.extend(lines[start:end])
                result.append("")
        for start, end, entry in RalphState._parse_heading_task_blocks(lines):
            if entry.is_pending:
                result.extend(lines[start:end])
                result.append("")
        return result

    @staticmethod
    def _derive_outcome(result: CycleResult) -> str:
        if not result.confirmed_tokens:
            return "UNKNOWN"
        finalize_ok = result.confirmed_tokens.get("finalize", False)
        execute_ok = result.confirmed_tokens.get("execute", False)
        if finalize_ok and execute_ok:
            return "COMPLETED"
        if execute_ok:
            return "PARTIAL"
        if any(result.confirmed_tokens.values()):
            return "PARTIAL"
        return "FAILED"
