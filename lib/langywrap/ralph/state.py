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
from enum import Enum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EXHAUSTED = "EXHAUSTED"


class TaskPriority(str, Enum):
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

    quality_gate_passed: Optional[bool] = None
    """None if no quality gate configured."""

    git_commit_hash: Optional[str] = None
    """Short commit hash, or None if no commit was made."""

    duration_seconds: float = 0.0
    models_used: dict[str, str] = field(default_factory=dict)
    """Map of step_name → model string used."""

    confirmed_tokens: dict[str, bool] = field(default_factory=dict)
    """Map of step_name → whether confirmation token was found."""

    rate_limited: bool = False
    """True if any step returned a rate-limit response this cycle."""

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
        for line in text.splitlines():
            entry = self._parse_task_line(line)
            if entry is not None:
                tasks.append(entry)
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
        found = False
        new_lines: list[str] = []
        for line in lines:
            entry = self._parse_task_line(line.rstrip("\n"))
            if entry is not None and entry.id == task_id and not found:
                new_line = re.sub(
                    r"^(\s*-\s*\[)[ x](\])",
                    r"\g<1>x\2",
                    line.rstrip("\n"),
                )
                # Append cycle annotation if not already present
                if f"(cycle {cycle_num})" not in new_line:
                    new_line = new_line.rstrip() + f" (cycle {cycle_num})"
                new_lines.append(new_line + "\n")
                found = True
            else:
                new_lines.append(line if line.endswith("\n") else line + "\n")
        if found:
            self.tasks_file.write_text("".join(new_lines), encoding="utf-8")
        return found

    _UNCHECKED_RE = re.compile(
        r"^\s*(?:-|#{1,6})\s*\[ \]", re.MULTILINE
    )

    def pending_count(self) -> int:
        """Count unchecked `- [ ]` or `### [ ]` lines in tasks.md."""
        if not self.tasks_file.exists():
            return 0
        text = self.tasks_file.read_text(encoding="utf-8")
        return len(self._UNCHECKED_RE.findall(text))

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

    def append_progress(self, cycle_result: CycleResult, task_id: str = "", summary: str = "") -> None:
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

        today = datetime.now().strftime("%Y-%m-%d")
        qg = quality_gate_cmd or "run quality checks"

        if template:
            task_block = template.format(
                cycle=cycle_num, date=today, quality_gate_cmd=qg,
            )
        else:
            task_block = (
                f"\n- [ ] **[P2] Technical hygiene — cycle {cycle_num}** "
                f"<!-- {marker} -->\n"
                f"  - Status: PENDING\n"
                f"  - Added: {today} | Source: langywrap (scheduled hygiene)\n"
                f"  - Why: Scheduled maintenance every N cycles\n"
                f"  - Definition of done:\n"
                f"    1. Run `{qg}` — fix ALL lint, type, and test failures\n"
                f"    2. Review progress.md for TODO/debt callouts\n"
                f"    3. Clean up any temporary files or dead code\n"
                f"    4. Verify project still builds and tests pass\n\n"
            )

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
                start_idx = cycle_starts[-max_recent_cycles] if len(cycle_starts) >= max_recent_cycles else cycle_starts[0]
            else:
                start_idx = 0

            parts += [
                f"## Recent Progress — Last {max_recent_cycles} Cycles (from progress.md)",
                f"(progress.md: {total_progress} lines total; only last {max_recent_cycles} cycles shown)",
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
    def _parse_task_line(line: str) -> Optional[TaskEntry]:
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
