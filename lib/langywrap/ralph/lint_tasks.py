"""Deterministic linter for ``tasks.md`` in the unified format.

Acts as a safety net around the LLM-driven finalize step. Two operating
modes:

- ``preflight`` — runs at cycle start. Read-only check + safe autofix.
  If anything hard-fails, the cycle halts (caller's choice).
- ``postflight`` — runs after finalize. Same checks; on hard-fail, the
  expected response is to revert ``tasks.md`` and retry finalize.

Auto-fixable issues (never invent data):

- Strip legacy ``(auto-pin cycle N, policy: P<n>)`` suffix on tasks.
- Trim trailing whitespace.
- Collapse runs of more than 2 consecutive blank lines.

Hard-fail issues (require finalize/operator intervention):

- Checkbox line doesn't match the unified format.
- Priority tag missing or not in the allowed set.
- ``task:slug`` missing or duplicate.
- ``[task_type]`` missing or not in the allowed set.
- More than one task under ``## Active``.

CLI::

    python -m langywrap.ralph.lint_tasks autofix research/tasks.md \\
        --task-types research,fix,diagnose --priorities P0,P1,P2,P3

Exit code 0 on clean-or-autofixed, 1 on any hard-fail.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from langywrap.ralph.markdown_todo import (
    AUTO_PIN_RE,
    CHECKBOX_PREFIX_RE,
    UNIFIED_TASK_LINE_RE,
)

# Severity vocabulary
SEV_AUTOFIXED = "autofixed"
SEV_HARD_FAIL = "hard_fail"
SEV_WARNING = "warning"

_DEFAULT_PRIORITIES = ("P0", "P1", "P2", "P3")
_LEGACY_PIN_SUFFIX_RE = re.compile(r"\s*\(auto-pin cycle \d+, policy: P\d+\)\s*$")
_SECTION_HEADER_RE = re.compile(r"^##\s+(Active|Pending|Completed)\b", re.IGNORECASE)


class LintConfig(BaseModel):
    """Linter configuration. Typically declared per-repo in ``.langywrap/ralph.py``."""

    allowed_task_types: tuple[str, ...] = ()
    """Permitted ``[task_type]`` values. Empty = accept any."""

    allowed_priorities: tuple[str, ...] = _DEFAULT_PRIORITIES
    """Permitted ``[P<digit>]`` values."""

    require_unique_slug: bool = True
    """Slugs must be unique across the file."""

    max_active: int = 1
    """Max tasks under ``## Active``."""

    allow_legacy_format: bool = False
    """If True, lines matching the legacy ``- [ ] **<type>**: <label>`` shape are accepted
    (no priority/slug enforcement). Useful during per-repo migration."""

    strip_legacy_auto_pin_tag: bool = True
    """Auto-fix: strip the ``(auto-pin cycle N, policy: P<n>)`` suffix."""

    model_config = {"frozen": True}


@dataclass
class LintFinding:
    """One linter observation about ``tasks.md``."""

    rule: str
    severity: str
    message: str
    line_no: int | None = None
    line_excerpt: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "line_no": self.line_no,
            "line_excerpt": self.line_excerpt,
        }


@dataclass
class LintReport:
    """Result of a lint run."""

    findings: list[LintFinding] = field(default_factory=list)
    fixed_text: str | None = None
    """Modified text when autofix was applied. ``None`` for pure-check mode."""

    @property
    def hard_fails(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity == SEV_HARD_FAIL]

    @property
    def autofixed(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity == SEV_AUTOFIXED]

    @property
    def warnings(self) -> list[LintFinding]:
        return [f for f in self.findings if f.severity == SEV_WARNING]

    @property
    def is_clean(self) -> bool:
        return not self.hard_fails

    @property
    def applied_autofix(self) -> bool:
        return bool(self.autofixed)

    def render(self) -> str:
        """Human-readable summary."""
        if not self.findings:
            return "tasks.md lint: clean."
        lines = [
            f"tasks.md lint: {len(self.hard_fails)} hard-fail, "
            f"{len(self.autofixed)} autofixed, {len(self.warnings)} warning."
        ]
        for f in self.findings:
            loc = f"L{f.line_no}: " if f.line_no is not None else ""
            lines.append(f"  [{f.severity}] {f.rule}: {loc}{f.message}")
            if f.line_excerpt:
                lines.append(f"      | {f.line_excerpt.rstrip()}")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(
            {
                "is_clean": self.is_clean,
                "applied_autofix": self.applied_autofix,
                "counts": {
                    "hard_fail": len(self.hard_fails),
                    "autofixed": len(self.autofixed),
                    "warning": len(self.warnings),
                },
                "findings": [f.to_dict() for f in self.findings],
            },
            indent=2,
        )


# ---------------------------------------------------------------------------
# Core lint passes
# ---------------------------------------------------------------------------


def lint(text: str, config: LintConfig | None = None) -> LintReport:
    """Read-only check. Returns findings without modifying the input."""
    return _run(text, config or LintConfig(), autofix=False)


def autofix(text: str, config: LintConfig | None = None) -> LintReport:
    """Apply safe fixes; return a report whose ``fixed_text`` carries the result.

    Always returns ``fixed_text`` (equal to ``text`` if no fix applied).
    """
    return _run(text, config or LintConfig(), autofix=True)


def _run(text: str, config: LintConfig, *, autofix: bool) -> LintReport:
    report = LintReport()
    lines = text.splitlines()
    # Track newline preservation for write-back.
    trailing_newline = text.endswith("\n")

    # --- Pass 1: per-line autofix (legacy auto-pin tag, trailing whitespace) ---
    if autofix:
        lines = _autofix_pass(lines, config, report)

    # --- Pass 2: blank-line collapsing ---
    if autofix:
        lines = _collapse_blank_runs(lines, report)

    # --- Pass 3: structural & per-task hard-fail checks ---
    _check_tasks(lines, config, report)
    _check_sections(lines, config, report)

    if autofix:
        report.fixed_text = "\n".join(lines) + ("\n" if trailing_newline else "")
    return report


def _autofix_pass(
    lines: list[str], config: LintConfig, report: LintReport
) -> list[str]:
    out: list[str] = []
    for i, line in enumerate(lines):
        new_line = line

        if config.strip_legacy_auto_pin_tag and AUTO_PIN_RE.search(new_line):
            stripped = _LEGACY_PIN_SUFFIX_RE.sub("", new_line)
            # Fallback: if the suffix wasn't at end-of-line, drop the tag anywhere.
            if stripped == new_line:
                stripped = AUTO_PIN_RE.sub("", new_line).rstrip()
            if stripped != new_line:
                report.findings.append(
                    LintFinding(
                        rule="strip_legacy_auto_pin_tag",
                        severity=SEV_AUTOFIXED,
                        line_no=i,
                        message="Removed legacy `(auto-pin cycle N, policy: P<n>)` suffix.",
                        line_excerpt=line,
                    )
                )
                new_line = stripped

        trimmed = new_line.rstrip()
        if trimmed != new_line:
            report.findings.append(
                LintFinding(
                    rule="trim_trailing_whitespace",
                    severity=SEV_AUTOFIXED,
                    line_no=i,
                    message="Trimmed trailing whitespace.",
                )
            )
            new_line = trimmed

        out.append(new_line)
    return out


def _collapse_blank_runs(
    lines: list[str], report: LintReport
) -> list[str]:
    out: list[str] = []
    blank_run = 0
    collapsed_at: list[int] = []
    for i, line in enumerate(lines):
        if line.strip() == "":
            blank_run += 1
            if blank_run > 2:
                collapsed_at.append(i)
                continue
        else:
            blank_run = 0
        out.append(line)
    if collapsed_at:
        report.findings.append(
            LintFinding(
                rule="collapse_blank_runs",
                severity=SEV_AUTOFIXED,
                message=f"Collapsed {len(collapsed_at)} excess blank line(s).",
            )
        )
    return out


def _check_tasks(
    lines: list[str], config: LintConfig, report: LintReport
) -> None:
    """Per-task hard-fail rules."""
    allowed_types = set(config.allowed_task_types)
    allowed_priorities = set(config.allowed_priorities)
    slugs: Counter[str] = Counter()
    slug_first_line: dict[str, int] = {}

    for i, line in enumerate(lines):
        # Only inspect checkbox lines.
        if not CHECKBOX_PREFIX_RE.match(line):
            continue

        unified = UNIFIED_TASK_LINE_RE.match(line)
        if unified:
            _, prio, slug, ttype, _label = unified.groups()
            if prio not in allowed_priorities:
                report.findings.append(
                    LintFinding(
                        rule="valid_priority",
                        severity=SEV_HARD_FAIL,
                        line_no=i,
                        message=f"Priority `[{prio}]` not in allowed {sorted(allowed_priorities)}.",
                        line_excerpt=line,
                    )
                )
            if allowed_types and ttype not in allowed_types:
                report.findings.append(
                    LintFinding(
                        rule="valid_task_type",
                        severity=SEV_HARD_FAIL,
                        line_no=i,
                        message=f"Task type `[{ttype}]` not in allowed {sorted(allowed_types)}.",
                        line_excerpt=line,
                    )
                )
            slugs[slug] += 1
            if slug not in slug_first_line:
                slug_first_line[slug] = i
            continue

        # Line didn't match unified format. If legacy mode is on, accept silently.
        if config.allow_legacy_format:
            continue

        report.findings.append(
            LintFinding(
                rule="unified_format",
                severity=SEV_HARD_FAIL,
                line_no=i,
                message=(
                    "Checkbox line does not match the unified format "
                    "`- [ ] **[Pn] task:slug** [task_type] label`."
                ),
                line_excerpt=line,
            )
        )

    if config.require_unique_slug:
        for slug, count in slugs.items():
            if count > 1:
                report.findings.append(
                    LintFinding(
                        rule="unique_slug",
                        severity=SEV_HARD_FAIL,
                        line_no=slug_first_line[slug],
                        message=f"Slug `task:{slug}` appears {count} times; must be unique.",
                    )
                )


def _check_sections(
    lines: list[str], config: LintConfig, report: LintReport
) -> None:
    """Section structure: ``## Active`` cap."""
    active_idx = None
    for i, line in enumerate(lines):
        m = _SECTION_HEADER_RE.match(line)
        if not m:
            continue
        section = m.group(1).lower()
        if section == "active":
            active_idx = i
            break
    if active_idx is None:
        return

    # Count tasks under Active until the next ## header.
    count = 0
    for j in range(active_idx + 1, len(lines)):
        if lines[j].startswith("## "):
            break
        if CHECKBOX_PREFIX_RE.match(lines[j]):
            count += 1
    if count > config.max_active:
        report.findings.append(
            LintFinding(
                rule="active_count",
                severity=SEV_HARD_FAIL,
                line_no=active_idx,
                message=(
                    f"`## Active` has {count} tasks; max {config.max_active}. "
                    "Move extras to `## Pending`."
                ),
            )
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_csv_list(s: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in s.split(",") if x.strip())


def _build_config(args: argparse.Namespace) -> LintConfig:
    kwargs: dict[str, object] = {}
    if args.task_types:
        kwargs["allowed_task_types"] = _parse_csv_list(args.task_types)
    if args.priorities:
        kwargs["allowed_priorities"] = _parse_csv_list(args.priorities)
    if args.max_active is not None:
        kwargs["max_active"] = args.max_active
    if args.allow_legacy:
        kwargs["allow_legacy_format"] = True
    return LintConfig(**kwargs)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="langywrap.ralph.lint_tasks",
        description="Lint and (optionally) autofix tasks.md.",
    )
    parser.add_argument(
        "mode",
        choices=("check", "autofix", "report"),
        help=(
            "check: read-only check, exit 1 on any finding; "
            "autofix: apply safe fixes in place, exit 1 on hard-fail; "
            "report: print JSON report to stdout, always exit 0."
        ),
    )
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--task-types",
        default="",
        help="Comma-separated allowed task types (empty = accept any).",
    )
    parser.add_argument(
        "--priorities",
        default="",
        help="Comma-separated allowed priorities (default P0,P1,P2,P3).",
    )
    parser.add_argument("--max-active", type=int, default=None)
    parser.add_argument(
        "--allow-legacy",
        action="store_true",
        help="Accept legacy `**<type>**: <label>` lines without enforcing unified format.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.path.exists():
        print(f"lint_tasks: path not found: {args.path}", file=sys.stderr)
        return 2

    text = args.path.read_text(encoding="utf-8")
    config = _build_config(args)

    if args.mode == "check":
        report = lint(text, config)
        print(report.render())
        return 0 if not report.findings else 1

    if args.mode == "report":
        report = lint(text, config)
        print(report.to_json())
        return 0

    # autofix
    report = autofix(text, config)
    if report.fixed_text is not None and report.fixed_text != text:
        args.path.write_text(report.fixed_text, encoding="utf-8")
    print(report.render())
    return 0 if report.is_clean else 1


__all__ = [
    "LintConfig",
    "LintFinding",
    "LintReport",
    "SEV_AUTOFIXED",
    "SEV_HARD_FAIL",
    "SEV_WARNING",
    "autofix",
    "lint",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
