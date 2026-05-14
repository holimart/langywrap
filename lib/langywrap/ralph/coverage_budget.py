"""Coverage-budget engine for anti-mode-collapse.

A *coverage budget* asserts a minimum fraction of recent realised cycles
that should be of a given ``task_type``. The inline orient step consults
the engine; when one or more budgets are violated, the picker filters
pending tasks to the union of violated types — ordering inside the
filtered set is left to ordinary priority rules.

Design rules (locked):

- ``window`` = last N **realised** cycles (cycles with an explicit
  ``TASK_TYPE:`` label in their ``progress.md`` block).
- Cycles without a ``TASK_TYPE`` label are **invisible** — neither
  numerator nor denominator.
- Multiple violations → **set-union** filter; orient still picks by
  ordinary priority inside that filter.
- **No backfill.** If fewer labelled cycles exist than a budget's
  ``window``, the budget is not yet evaluated (no violation can fire).

Usage::

    from langywrap.ralph.coverage_budget import (
        CoverageBudget,
        evaluate_coverage,
        filter_eligible_tasks,
    )

    budgets = [
        CoverageBudget(task_type="research", min_fraction=0.20, window=10),
        CoverageBudget(task_type="diagnose", min_fraction=0.15, window=10),
    ]
    report = evaluate_coverage(progress_md_text, budgets)
    if report.has_violations:
        eligible = filter_eligible_tasks(parsed_tasks, report)
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel, Field, field_validator

from langywrap.ralph.markdown_todo import dedupe_cycles, parse_cycle_blocks


class CoverageBudget(BaseModel):
    """Minimum-fraction constraint on a ``task_type`` over recent labelled cycles."""

    task_type: str
    """The ``TASK_TYPE:`` value the budget watches."""

    min_fraction: float = Field(gt=0.0, le=1.0)
    """Minimum acceptable ``count(task_type) / window``."""

    window: int = Field(gt=0, default=10)
    """Number of most-recent labelled cycles to inspect."""

    model_config = {"frozen": True}

    @field_validator("task_type")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip().lower()


class CoverageReport(BaseModel):
    """Result of evaluating budgets against progress history."""

    violations: tuple[CoverageBudget, ...] = ()
    """Budgets whose observed fraction was below ``min_fraction``."""

    counts_by_type: dict[str, int] = Field(default_factory=dict)
    """Observed count of each ``task_type`` in the maximum window. Only labelled cycles count."""

    labelled_in_window: int = 0
    """Number of labelled cycles considered (denominator for the report's fractions)."""

    window_cycles: tuple[int, ...] = ()
    """Cycle numbers considered, oldest → newest."""

    skipped_unlabelled: int = 0
    """Cycles within the maximum window that lacked a ``TASK_TYPE:`` label and were skipped."""

    model_config = {"frozen": True}

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    def violated_types(self) -> set[str]:
        """Union of ``task_type`` values from violating budgets."""
        return {b.task_type for b in self.violations}

    def render_summary(self) -> str:
        """Human-readable one-block summary suitable for orient.md."""
        lines = ["## Coverage Report"]
        if not self.labelled_in_window:
            lines.append("No labelled cycles in window yet — engine inactive.")
            return "\n".join(lines)
        lines.append(
            f"Labelled cycles in window: {self.labelled_in_window} "
            f"(cycles {self.window_cycles[0]}–{self.window_cycles[-1]})"
        )
        if self.skipped_unlabelled:
            lines.append(f"Unlabelled cycles skipped: {self.skipped_unlabelled}")
        if self.counts_by_type:
            counts = ", ".join(
                f"{t}={n}" for t, n in sorted(self.counts_by_type.items(), key=lambda kv: -kv[1])
            )
            lines.append(f"Counts: {counts}")
        if self.violations:
            viol = ", ".join(
                f"{b.task_type} (need ≥{b.min_fraction:.0%} over last {b.window})"
                for b in self.violations
            )
            lines.append(f"**Violations:** {viol}")
            lines.append(f"**Eligible types this cycle:** {sorted(self.violated_types())}")
        else:
            lines.append("**No violations.** All budgets within bounds.")
        return "\n".join(lines)


def evaluate_coverage(
    progress_md: str,
    budgets: Sequence[CoverageBudget],
) -> CoverageReport:
    """Compute the coverage report from ``progress.md`` text + budget set.

    Skips cycles without a ``TASK_TYPE:`` label entirely. If labelled-cycle
    count is less than a budget's ``window``, that budget is not evaluated
    (no violation can fire). Returns a fully-populated report.
    """
    if not budgets:
        return CoverageReport()

    cycles = dedupe_cycles(parse_cycle_blocks(progress_md))
    cycles_sorted = sorted(cycles, key=lambda c: c.n)
    labelled = [c for c in cycles_sorted if c.task_type]

    max_window = max(b.window for b in budgets)
    # For the report summary: use the largest window across all budgets.
    repr_window = labelled[-max_window:] if labelled else []
    # Count unlabelled cycles that fall *within* the cycle-number range we considered.
    skipped_unlabelled = 0
    if repr_window:
        lo, hi = repr_window[0].n, repr_window[-1].n
        skipped_unlabelled = sum(
            1 for c in cycles_sorted if c.task_type is None and lo <= c.n <= hi
        )

    violations: list[CoverageBudget] = []
    for budget in budgets:
        if len(labelled) < budget.window:
            continue
        window = labelled[-budget.window :]
        observed = sum(1 for c in window if c.task_type == budget.task_type)
        if observed / budget.window < budget.min_fraction:
            violations.append(budget)

    return CoverageReport(
        violations=tuple(violations),
        counts_by_type=dict(Counter(c.task_type for c in repr_window if c.task_type)),
        labelled_in_window=len(repr_window),
        window_cycles=tuple(c.n for c in repr_window),
        skipped_unlabelled=skipped_unlabelled,
    )


def filter_eligible_tasks(tasks: Iterable[Any], report: CoverageReport) -> list[Any]:
    """Filter parsed tasks to the union of violated types.

    Each task is expected to expose ``.task_type`` (any ``CheckboxTask``-like).
    If ``report.has_violations`` is False, returns the input as a list unchanged.
    """
    if not report.has_violations:
        return list(tasks)
    allowed = report.violated_types()
    return [t for t in tasks if getattr(t, "task_type", None) in allowed]


__all__ = [
    "CoverageBudget",
    "CoverageReport",
    "evaluate_coverage",
    "filter_eligible_tasks",
]
