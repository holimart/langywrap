"""Tests for the coverage-budget engine."""

from __future__ import annotations

import pytest
from langywrap.ralph.coverage_budget import (
    CoverageBudget,
    CoverageReport,
    evaluate_coverage,
    filter_eligible_tasks,
)
from langywrap.ralph.markdown_todo import CheckboxTask
from pydantic import ValidationError


def _progress(*cycles: tuple[int, str | None]) -> str:
    """Build a progress.md text from (cycle_n, task_type|None) pairs."""
    parts: list[str] = []
    for n, ttype in cycles:
        parts.append(f"## Cycle {n}")
        if ttype is not None:
            parts.append(f"TASK_TYPE: {ttype}")
        parts.append("notes: ...\n")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CoverageBudget validation
# ---------------------------------------------------------------------------


def test_budget_rejects_zero_min_fraction() -> None:
    with pytest.raises(ValidationError):
        CoverageBudget(task_type="x", min_fraction=0.0)


def test_budget_rejects_min_fraction_above_one() -> None:
    with pytest.raises(ValidationError):
        CoverageBudget(task_type="x", min_fraction=1.5)


def test_budget_rejects_zero_window() -> None:
    with pytest.raises(ValidationError):
        CoverageBudget(task_type="x", min_fraction=0.5, window=0)


def test_budget_normalises_task_type_case_and_whitespace() -> None:
    b = CoverageBudget(task_type="  Research  ", min_fraction=0.1)
    assert b.task_type == "research"


# ---------------------------------------------------------------------------
# evaluate_coverage
# ---------------------------------------------------------------------------


def test_no_budgets_yields_empty_report() -> None:
    report = evaluate_coverage(_progress((1, "research"), (2, "diagnose")), [])
    assert report.violations == ()
    assert report.counts_by_type == {}
    assert report.labelled_in_window == 0


def test_empty_progress_no_violations() -> None:
    budgets = [CoverageBudget(task_type="research", min_fraction=0.2, window=5)]
    report = evaluate_coverage("", budgets)
    assert not report.has_violations
    assert report.labelled_in_window == 0


def test_fewer_labelled_than_window_no_violation() -> None:
    # Only 3 labelled cycles; window=5 → not yet evaluated.
    progress = _progress((1, "research"), (2, "fix"), (3, "fix"))
    budgets = [CoverageBudget(task_type="research", min_fraction=0.4, window=5)]
    report = evaluate_coverage(progress, budgets)
    assert not report.has_violations


def test_single_budget_violation_fires() -> None:
    # 10 labelled cycles, only 1 research → 0.10 < 0.20 → violate.
    cycles = [(i, "research" if i == 1 else "fix") for i in range(1, 11)]
    budgets = [CoverageBudget(task_type="research", min_fraction=0.20, window=10)]
    report = evaluate_coverage(_progress(*cycles), budgets)
    assert report.has_violations
    assert report.violated_types() == {"research"}
    assert report.counts_by_type == {"research": 1, "fix": 9}
    assert report.labelled_in_window == 10


def test_single_budget_satisfied_no_violation() -> None:
    # 10 labelled cycles, 3 research → 0.30 ≥ 0.20 → ok.
    cycles = [
        (1, "research"),
        (2, "research"),
        (3, "research"),
        (4, "fix"),
        (5, "fix"),
        (6, "fix"),
        (7, "fix"),
        (8, "fix"),
        (9, "fix"),
        (10, "fix"),
    ]
    budgets = [CoverageBudget(task_type="research", min_fraction=0.20, window=10)]
    report = evaluate_coverage(_progress(*cycles), budgets)
    assert not report.has_violations


def test_multiple_violations_union_of_types() -> None:
    cycles = [(i, "fix") for i in range(1, 11)]
    budgets = [
        CoverageBudget(task_type="research", min_fraction=0.2, window=10),
        CoverageBudget(task_type="diagnose", min_fraction=0.1, window=10),
    ]
    report = evaluate_coverage(_progress(*cycles), budgets)
    assert report.violated_types() == {"research", "diagnose"}


def test_unlabelled_cycles_are_invisible() -> None:
    # Labelled at odd cycles, unlabelled at even cycles (cycle 2..8) — the
    # 4 unlabelled cycles fall inside the labelled-window's [1..9] span.
    cycles = [
        (1, "fix"),
        (2, None),
        (3, "fix"),
        (4, None),
        (5, "fix"),
        (6, None),
        (7, "fix"),
        (8, None),
        (9, "fix"),
    ]
    budgets = [CoverageBudget(task_type="research", min_fraction=0.2, window=5)]
    report = evaluate_coverage(_progress(*cycles), budgets)
    assert report.has_violations
    assert report.labelled_in_window == 5
    assert report.skipped_unlabelled == 4


def test_window_uses_most_recent_labelled() -> None:
    # 12 labelled cycles; window=5. Only last 5 count.
    cycles = (
        [(i, "research") for i in range(1, 8)]  # 7 research (old)
        + [(i, "fix") for i in range(8, 13)]  # 5 fix (recent)
    )
    budgets = [CoverageBudget(task_type="research", min_fraction=0.4, window=5)]
    report = evaluate_coverage(_progress(*cycles), budgets)
    # last 5 = all fix → violation on research
    assert report.has_violations
    assert report.counts_by_type == {"fix": 5}


def test_per_budget_independent_windows() -> None:
    # Different windows per budget should evaluate independently.
    cycles = [(i, "research") for i in range(1, 11)]
    budgets = [
        # 10 of 10 research → satisfied
        CoverageBudget(task_type="research", min_fraction=0.5, window=10),
        # 0 of 10 diagnose → violated
        CoverageBudget(task_type="diagnose", min_fraction=0.1, window=10),
    ]
    report = evaluate_coverage(_progress(*cycles), budgets)
    assert report.violated_types() == {"diagnose"}


# ---------------------------------------------------------------------------
# filter_eligible_tasks
# ---------------------------------------------------------------------------


def _task(task_type: str, label: str = "x") -> CheckboxTask:
    return CheckboxTask(line_no=0, raw="", status=" ", task_type=task_type, label=label)


def test_filter_passthrough_when_no_violations() -> None:
    report = CoverageReport()
    tasks = [_task("a"), _task("b")]
    assert filter_eligible_tasks(tasks, report) == tasks


def test_filter_keeps_only_violated_types() -> None:
    budget = CoverageBudget(task_type="research", min_fraction=0.2, window=10)
    report = CoverageReport(violations=(budget,))
    tasks = [_task("fix"), _task("research"), _task("diagnose")]
    eligible = filter_eligible_tasks(tasks, report)
    assert [t.task_type for t in eligible] == ["research"]


def test_filter_union_across_multiple_violations() -> None:
    b1 = CoverageBudget(task_type="research", min_fraction=0.2, window=10)
    b2 = CoverageBudget(task_type="diagnose", min_fraction=0.1, window=10)
    report = CoverageReport(violations=(b1, b2))
    tasks = [_task("fix"), _task("research"), _task("diagnose"), _task("profile")]
    eligible = filter_eligible_tasks(tasks, report)
    assert sorted(t.task_type for t in eligible) == ["diagnose", "research"]


# ---------------------------------------------------------------------------
# render_summary
# ---------------------------------------------------------------------------


def test_render_summary_inactive_when_no_data() -> None:
    out = CoverageReport().render_summary()
    assert "engine inactive" in out.lower()


def test_render_summary_includes_violation_block() -> None:
    cycles = [(i, "fix") for i in range(1, 11)]
    budgets = [CoverageBudget(task_type="research", min_fraction=0.20, window=10)]
    report = evaluate_coverage(_progress(*cycles), budgets)
    out = report.render_summary()
    assert "Violations:" in out
    assert "research" in out
    assert "Eligible types this cycle:" in out


def test_render_summary_clean_when_satisfied() -> None:
    cycles = [(i, "research") for i in range(1, 11)]
    budgets = [CoverageBudget(task_type="research", min_fraction=0.20, window=10)]
    report = evaluate_coverage(_progress(*cycles), budgets)
    out = report.render_summary()
    assert "No violations" in out
