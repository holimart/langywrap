"""Integration tests for the ``inline_orient`` builtin step.

Uses the runner's internal ``_run_inline_orient`` method to exercise the
preflight-lint + coverage-budget + picker flow end-to-end on a tmpdir fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langywrap.ralph.config import RalphConfig, StepConfig
from langywrap.ralph.runner import RalphLoop


def _build_loop(
    tmp_path: Path,
    tasks_md: str,
    progress_md: str,
    *,
    coverage_budgets: list[dict] | None = None,
    allowed_task_types: tuple[str, ...] = (),
    allow_legacy_format: bool = False,
) -> tuple[RalphLoop, StepConfig]:
    state_dir = tmp_path / "research"
    state_dir.mkdir(parents=True, exist_ok=True)
    prompts = state_dir / "prompts"
    prompts.mkdir(exist_ok=True)
    (prompts / "orient.md").write_text("stub")
    (state_dir / "tasks.md").write_text(tasks_md)
    (state_dir / "progress.md").write_text(progress_md)

    step = StepConfig(
        name="orient",
        prompt_template=prompts / "orient.md",
        confirmation_token="ORIENT_CONFIRMED:",
        builtin="inline_orient",
        coverage_budgets=coverage_budgets or [],
        allowed_task_types=list(allowed_task_types),
        allow_legacy_format=allow_legacy_format,
        preflight_lint=True,
    )
    cfg = RalphConfig(project_dir=tmp_path, state_dir=state_dir, steps=[step])
    return RalphLoop(cfg, router=None), step


def test_picks_first_pending_when_no_violations(tmp_path: Path) -> None:
    tasks = (
        "## Active\n\n"
        "## Pending\n"
        "- [ ] **[P0] task:do-it** [research] First thing\n"
        "- [ ] **[P1] task:later** [fix] Second thing\n"
    )
    progress = (
        "## Cycle 1\nTASK_TYPE: research\n\n"
        "## Cycle 2\nTASK_TYPE: research\n\n"
    )
    loop, step = _build_loop(
        tmp_path,
        tasks,
        progress,
        coverage_budgets=[{"task_type": "research", "min_fraction": 0.2, "window": 2}],
        allowed_task_types=("research", "fix"),
    )
    out = loop._run_inline_orient(step, {"cycle_num": 3})
    assert "task:do-it" in out
    assert "[research]" in out
    assert "ORIENT_CONFIRMED:" in out
    assert "No violations" in out


def test_budget_filters_pending_when_violated(tmp_path: Path) -> None:
    # 10 cycles all 'fix' → research budget 0% < 20% → violation.
    progress = "".join(
        f"## Cycle {i}\nTASK_TYPE: fix\n\n" for i in range(1, 11)
    )
    tasks = (
        "## Active\n\n"
        "## Pending\n"
        "- [ ] **[P0] task:another-fix** [fix] Another quick fix\n"
        "- [ ] **[P1] task:explore** [research] Investigate area X\n"
    )
    loop, step = _build_loop(
        tmp_path,
        tasks,
        progress,
        coverage_budgets=[{"task_type": "research", "min_fraction": 0.2, "window": 10}],
        allowed_task_types=("research", "fix"),
    )
    out = loop._run_inline_orient(step, {"cycle_num": 11})
    # Budget violated → orient must pick the research task, not the higher-priority fix.
    assert "task:explore" in out
    assert "[research]" in out
    assert "Violations:" in out


def test_preflight_autofix_strips_legacy_pin_tag(tmp_path: Path) -> None:
    tasks = (
        "## Active\n\n"
        "## Pending\n"
        "- [ ] **[P0] task:pick-me** [research] do thing "
        "(auto-pin cycle 5, policy: P2)\n"
    )
    loop, step = _build_loop(
        tmp_path,
        tasks,
        "",
        allowed_task_types=("research",),
    )
    loop._run_inline_orient(step, {"cycle_num": 1})
    # The file on disk must have been mutated by the autofix pass.
    written = (tmp_path / "research" / "tasks.md").read_text()
    assert "auto-pin cycle" not in written
    assert "task:pick-me" in written


def test_preflight_hard_fail_raises(tmp_path: Path) -> None:
    tasks = (
        "## Pending\n"
        "- [ ] **[P9] task:bad** [research] invalid priority\n"
    )
    loop, step = _build_loop(
        tmp_path,
        tasks,
        "",
        allowed_task_types=("research",),
    )
    with pytest.raises(ValueError, match="preflight lint hard-failed"):
        loop._run_inline_orient(step, {"cycle_num": 1})


def test_missing_tasks_file_raises(tmp_path: Path) -> None:
    state_dir = tmp_path / "research"
    state_dir.mkdir(parents=True, exist_ok=True)
    prompts = state_dir / "prompts"
    prompts.mkdir(exist_ok=True)
    (prompts / "orient.md").write_text("stub")
    step = StepConfig(
        name="orient",
        prompt_template=prompts / "orient.md",
        builtin="inline_orient",
        allowed_task_types=["research"],
    )
    cfg = RalphConfig(project_dir=tmp_path, state_dir=state_dir, steps=[step])
    loop = RalphLoop(cfg, router=None)
    with pytest.raises(ValueError, match="tasks file not found"):
        loop._run_inline_orient(step, {"cycle_num": 1})


def test_no_pending_task_raises(tmp_path: Path) -> None:
    tasks = "## Active\n\n## Pending\n\n## Completed\n"
    loop, step = _build_loop(
        tmp_path,
        tasks,
        "",
        allowed_task_types=("research",),
    )
    with pytest.raises(ValueError, match="no pending task"):
        loop._run_inline_orient(step, {"cycle_num": 1})


def test_emits_task_type_token_for_downstream_detect(tmp_path: Path) -> None:
    """The orient output must carry a literal ``TASK_TYPE: <type>`` line.

    Two downstream consumers depend on this:

    1. Per-repo configs use ``detects_cycle=Match(scan=r"TASK_TYPE:\\s*scan")``
       to gate plan/execute steps. Without the token, every typed step
       SKIPS with ``cycle type '' not in [...]``.
    2. ``coverage_budget.evaluate_coverage`` reads ``TASK_TYPE:`` rows from
       progress.md to count which cycle types are under their floor.

    Regression: 2026-05-12 — initial inline_orient render emitted only
    the bracket form ``[type]`` in the bullet, no literal token. Every
    whitehacky cycle ran ORIENT → FINALIZE only.
    """
    tasks = (
        "## Active\n\n"
        "## Pending\n"
        "- [ ] **[P0] task:do-it** [research] First thing\n"
    )
    loop, step = _build_loop(
        tmp_path,
        tasks,
        "",
        allowed_task_types=("research", "fix"),
    )
    out = loop._run_inline_orient(step, {"cycle_num": 1})

    # 1. Literal token present on its own line.
    assert "TASK_TYPE: research" in out
    import re

    assert re.search(r"^TASK_TYPE:\s*research\s*$", out, re.MULTILINE)

    # 2. Round-trip: the output satisfies the per-repo detects_cycle pattern.
    loop.config.cycle_type_rules = [
        {"name": "research", "pattern": r"TASK_TYPE:\s*research"},
        {"name": "fix", "pattern": r"TASK_TYPE:\s*fix"},
    ]
    assert loop._detect_cycle_type(out) == "research"


def test_violation_with_no_eligible_task_raises(tmp_path: Path) -> None:
    # Coverage violated on `research`, but no research task exists.
    progress = "".join(
        f"## Cycle {i}\nTASK_TYPE: fix\n\n" for i in range(1, 11)
    )
    tasks = (
        "## Pending\n"
        "- [ ] **[P0] task:fix-x** [fix] something\n"
    )
    loop, step = _build_loop(
        tmp_path,
        tasks,
        progress,
        coverage_budgets=[{"task_type": "research", "min_fraction": 0.2, "window": 10}],
        allowed_task_types=("research", "fix"),
    )
    with pytest.raises(ValueError, match="no pending task of types"):
        loop._run_inline_orient(step, {"cycle_num": 11})


def test_picks_by_priority_within_eligible_set(tmp_path: Path) -> None:
    # Two pending of the same violated type — P0 wins over P1.
    progress = "".join(
        f"## Cycle {i}\nTASK_TYPE: fix\n\n" for i in range(1, 11)
    )
    tasks = (
        "## Pending\n"
        "- [ ] **[P2] task:later-research** [research] later thing\n"
        "- [ ] **[P0] task:urgent-research** [research] urgent thing\n"
    )
    loop, step = _build_loop(
        tmp_path,
        tasks,
        progress,
        coverage_budgets=[{"task_type": "research", "min_fraction": 0.2, "window": 10}],
        allowed_task_types=("research", "fix"),
    )
    out = loop._run_inline_orient(step, {"cycle_num": 11})
    assert "task:urgent-research" in out
    assert "task:later-research" not in out.split("## Selected Task")[1].split("## Coverage")[0]
