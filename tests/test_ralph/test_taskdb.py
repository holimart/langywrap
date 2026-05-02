from __future__ import annotations

from pathlib import Path

from langywrap.ralph.taskdb import TaskDB, render_orient_snapshot


def _write_state(tmp_path: Path) -> Path:
    state = tmp_path / "research" / "ralph"
    (state / "steps").mkdir(parents=True)
    (tmp_path / "research" / "ralph" / "lean").mkdir(parents=True)
    (tmp_path / "research" / "ralph" / "lean" / "Foo.lean").write_text(
        "axiom h : True\ntheorem t : True := by\n  sorry\n",
        encoding="utf-8",
    )
    (state / "tasks.md").write_text(
        "# Tasks\n\n"
        "### [P2] Later task <!-- task:later -->\n"
        "**Status:** PENDING\n"
        "Body\n\n"
        "### [P1-R] Research task <!-- task:research -->\n"
        "**Status:** PARTIAL\n"
        "Research body\n"
        "Depends on `task:later` before endpoint retry.\n\n"
        "### [P0] Closed task <!-- task:closed -->\n"
        "**Status:** COMPLETED\n",
        encoding="utf-8",
    )
    (state / "progress.md").write_text(
        "## Cycle 7 — finalize\n"
        "**Outcome:** PARTIAL\n"
        "**Rigor achieved:** L3\n"
        "**Lean status:** N/A\n"
        "**Key insight:** Useful insight.\n"
        "**Next:** RESEARCH CYCLE RECOMMENDED -- do research.\n"
        "---\n",
        encoding="utf-8",
    )
    (state / "plan.md").write_text("# Plan\n\nDo the thing.\n", encoding="utf-8")
    (state / "steps" / "critic.md").write_text("Verdict: CONCERNS\n", encoding="utf-8")
    return state


def test_taskdb_snapshot_orders_open_tasks_and_reads_progress(tmp_path: Path) -> None:
    state = _write_state(tmp_path)
    snap = TaskDB(tmp_path, state).snapshot()

    assert snap.cycle == 8
    assert [task.task_id for task in snap.tasks] == ["task:later"]
    assert [task.task_id for task in snap.blocked_tasks] == ["task:research"]
    assert snap.blocked_tasks[0].depends_on == ("task:later",)
    assert snap.blocked_tasks[0].task_refs == ("task:later",)
    assert "Depends on" in snap.blocked_tasks[0].dependency_hints[0]
    assert snap.recent_progress[0].key_insight == "Useful insight."
    assert snap.lean.total_sorries == 1
    assert "critic: CONCERNS" in snap.verdict_flags


def test_render_orient_snapshot_includes_confirmation_token(tmp_path: Path) -> None:
    state = _write_state(tmp_path)
    snap = TaskDB(tmp_path, state).snapshot()
    out = render_orient_snapshot(snap, confirmation_token="ORIENT_CONFIRMED:")

    assert "# Cycle 8 Orient Summary" in out
    assert "## Planning Brief" in out
    assert "Highest actionable task" in out
    assert "## Deferred Blocked/Dependent Tasks" in out
    assert "task:research" in out
    assert "ORIENT_CONFIRMED: native_orient=true" in out
