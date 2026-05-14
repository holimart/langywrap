"""Extended tests for ralph state — covering save_tasks, mark_task,
inject_hygiene_task, inject_periodic_task, append_progress branches,
and _derive_outcome."""

from __future__ import annotations

from pathlib import Path

import pytest
from langywrap.ralph.lint_tasks import LintConfig, lint
from langywrap.ralph.state import CycleResult, RalphState, TaskStatus


@pytest.fixture
def state(tmp_path: Path) -> RalphState:
    d = tmp_path / "ralph"
    d.mkdir()
    return RalphState(d)


def _write_tasks(state: RalphState, content: str) -> None:
    state.tasks_file.parent.mkdir(parents=True, exist_ok=True)
    state.tasks_file.write_text(content)


def _assert_tasks_lint_clean(text: str, *task_types: str) -> None:
    report = lint(text, LintConfig(allowed_task_types=task_types))
    assert report.is_clean, report.render()


# ---------------------------------------------------------------------------
# save_tasks
# ---------------------------------------------------------------------------


class TestSaveTasks:
    def test_no_tasks_file_is_noop(self, state: RalphState):
        # tasks_file doesn't exist yet → no error
        state.save_tasks([])

    def test_updates_checkbox(self, state: RalphState):
        _write_tasks(state, "- [ ] task-1 Do something\n")
        tasks = state.load_tasks()
        assert len(tasks) == 1
        tasks[0].status = TaskStatus.COMPLETED
        state.save_tasks(tasks)
        text = state.tasks_file.read_text()
        assert "[x]" in text

    def test_preserves_non_task_lines(self, state: RalphState):
        _write_tasks(state, "# Header\n- [ ] task-1 Do something\n## Footer\n")
        tasks = state.load_tasks()
        state.save_tasks(tasks)
        text = state.tasks_file.read_text()
        assert "# Header" in text
        assert "## Footer" in text


# ---------------------------------------------------------------------------
# mark_task_completed
# ---------------------------------------------------------------------------


class TestMarkTaskCompleted:
    def test_no_tasks_file_returns_false(self, state: RalphState):
        assert state.mark_task_completed("task-1", 1) is False

    def test_marks_existing_task(self, state: RalphState):
        _write_tasks(state, "- [ ] task-1 Do something\n")
        result = state.mark_task_completed("task-1", 3)
        assert result is True
        text = state.tasks_file.read_text()
        assert "[x]" in text
        assert "(cycle 3)" in text

    def test_task_not_found_returns_false(self, state: RalphState):
        _write_tasks(state, "- [ ] task-1 Do something\n")
        assert state.mark_task_completed("task-999", 1) is False

    def test_no_duplicate_cycle_annotation(self, state: RalphState):
        _write_tasks(state, "- [ ] task-1 Do something (cycle 3)\n")
        state.mark_task_completed("task-1", 3)
        text = state.tasks_file.read_text()
        # Should not double-annotate
        assert text.count("(cycle 3)") == 1


# ---------------------------------------------------------------------------
# inject_hygiene_task
# ---------------------------------------------------------------------------


class TestInjectHygieneTask:
    def test_no_tasks_file_returns_false(self, state: RalphState):
        assert state.inject_hygiene_task(5) is False

    def test_injects_task(self, state: RalphState):
        _write_tasks(state, "# Tasks\n- [ ] task-1 Existing task\n")
        injected = state.inject_hygiene_task(5)
        assert injected is True
        text = state.tasks_file.read_text()
        assert "- [ ] **[P2] task:hygiene-cycle-5** [hygiene] Technical hygiene" in text

    def test_injected_task_lints_in_unified_format(self, state: RalphState):
        _write_tasks(state, "## Pending\n")
        assert state.inject_hygiene_task(5, quality_gate_cmd="lake build") is True
        _assert_tasks_lint_clean(state.tasks_file.read_text(), "hygiene")

    def test_no_duplicate_injection(self, state: RalphState):
        _write_tasks(state, "# Tasks\n- [ ] task-1 Existing\n")
        state.inject_hygiene_task(5)
        injected_again = state.inject_hygiene_task(5)
        assert injected_again is False

    def test_custom_template_lints_when_unified(self, state: RalphState):
        _write_tasks(state, "- [ ] **[P2] task:task-1** [hygiene] base\n")
        template = (
            "- [ ] **[P2] task:hygiene-cycle-{cycle}** [hygiene] "
            "Custom hygiene for cycle {cycle}"
        )
        state.inject_hygiene_task(2, template=template)
        text = state.tasks_file.read_text()
        assert "Custom hygiene for cycle 2" in text
        _assert_tasks_lint_clean(text, "hygiene")

    def test_rejects_non_unified_hygiene_template(self, state: RalphState):
        _write_tasks(state, "## Pending\n")
        with pytest.raises(ValueError, match="unified format"):
            state.inject_hygiene_task(
                2, template="- [ ] **[P2] Technical hygiene — cycle {cycle}**"
            )
        assert state.tasks_file.read_text() == "## Pending\n"

    def test_inserts_before_completed_section(self, state: RalphState):
        _write_tasks(state, "- [ ] task-1 Active\n\n## Completed\n- [x] old-task\n")
        state.inject_hygiene_task(3)
        text = state.tasks_file.read_text()
        # hygiene block should appear before ## Completed
        hygiene_pos = text.find("hygiene-cycle-3")
        completed_pos = text.find("## Completed")
        assert hygiene_pos < completed_pos

    def test_periodic_injected_task_lints_in_unified_format(self, state: RalphState):
        _write_tasks(state, "## Pending\n")
        content = "- [ ] **[P2] task:lookback-cycle-10** [lookback] Process lookback"
        assert state.inject_periodic_task(10, marker="lookback", content=content) is True
        _assert_tasks_lint_clean(state.tasks_file.read_text(), "lookback")


# ---------------------------------------------------------------------------
# inject_periodic_task
# ---------------------------------------------------------------------------


class TestInjectPeriodicTask:
    def test_no_tasks_file_returns_false(self, state: RalphState):
        assert state.inject_periodic_task(1) is False

    def test_no_content_returns_false(self, state: RalphState):
        _write_tasks(state, "- [ ] t1 Task\n")
        assert state.inject_periodic_task(1, content="") is False

    def test_injects_content(self, state: RalphState):
        _write_tasks(state, "- [ ] **[P2] task:t1** [lookback] Task\n")
        result = state.inject_periodic_task(
            1,
            marker="lookback",
            content="- [ ] **[P2] task:lookback-cycle-1** [lookback] lookback content",
        )
        assert result is True
        text = state.tasks_file.read_text()
        assert "lookback content" in text

    def test_dedup_by_marker(self, state: RalphState):
        _write_tasks(state, "- [ ] **[P2] task:t1** [lookback] Task\n")
        content = "- [ ] **[P2] task:review-cycle-1** [lookback] Review content"
        state.inject_periodic_task(1, marker="review", content=content)
        result2 = state.inject_periodic_task(1, marker="review", content=content)
        assert result2 is False

    def test_adds_marker_comment_when_missing(self, state: RalphState):
        _write_tasks(state, "- [ ] **[P2] task:t1** [lookback] Task\n")
        state.inject_periodic_task(
            1,
            marker="custom",
            content="- [ ] **[P2] task:custom-cycle-1** [lookback] Content without marker",
        )
        text = state.tasks_file.read_text()
        assert "custom-cycle-1" in text

    def test_inserts_before_completed_section(self, state: RalphState):
        _write_tasks(state, "Pending stuff\n\n## Completed\n- [x] done\n")
        state.inject_periodic_task(
            1,
            marker="lb",
            content="- [ ] **[P2] task:lb-cycle-1** [lookback] lookback task",
        )
        text = state.tasks_file.read_text()
        lb_pos = text.find("lookback task")
        completed_pos = text.find("## Completed")
        assert lb_pos < completed_pos

    def test_rejects_non_unified_checkbox_content(self, state: RalphState):
        _write_tasks(state, "## Pending\n")
        with pytest.raises(ValueError, match="unified format"):
            state.inject_periodic_task(
                1,
                marker="lookback",
                content="- [ ] **[P2] Technical hygiene — cycle 1**",
            )
        assert state.tasks_file.read_text() == "## Pending\n"

    def test_rejects_content_without_checkbox_task(self, state: RalphState):
        _write_tasks(state, "## Pending\n")
        with pytest.raises(ValueError, match="must include a unified checkbox"):
            state.inject_periodic_task(1, marker="lookback", content="lookback content")
        assert state.tasks_file.read_text() == "## Pending\n"


# ---------------------------------------------------------------------------
# append_progress — branch coverage for optional fields
# ---------------------------------------------------------------------------


class TestAppendProgress:
    def test_basic_cycle_result(self, state: RalphState):
        r = CycleResult(cycle_number=1)
        state.append_progress(r)
        text = state.progress_file.read_text()
        assert "Cycle 1" in text

    def test_with_task_id_and_summary(self, state: RalphState):
        r = CycleResult(cycle_number=2, duration_seconds=60.0)
        state.append_progress(r, task_id="TASK-42", summary="Did something")
        text = state.progress_file.read_text()
        assert "TASK-42" in text
        assert "Did something" in text

    def test_with_confirmed_tokens(self, state: RalphState):
        r = CycleResult(
            cycle_number=3,
            confirmed_tokens={"orient": True, "execute": False},
        )
        state.append_progress(r)
        text = state.progress_file.read_text()
        assert "ORIENT_CONFIRMED" in text
        assert "EXECUTE_CONFIRMED" in text

    def test_with_quality_gate(self, state: RalphState):
        r = CycleResult(cycle_number=4, quality_gate_passed=True)
        state.append_progress(r)
        text = state.progress_file.read_text()
        assert "PASS" in text

    def test_with_git_commit(self, state: RalphState):
        r = CycleResult(cycle_number=5, git_commit_hash="abc1234")
        state.append_progress(r)
        text = state.progress_file.read_text()
        assert "abc1234" in text


# ---------------------------------------------------------------------------
# _derive_outcome — static method
# ---------------------------------------------------------------------------


class TestDeriveOutcome:
    def test_no_tokens_unknown(self):
        r = CycleResult(cycle_number=1)
        assert RalphState._derive_outcome(r) == "UNKNOWN"

    def test_finalize_and_execute_completed(self):
        r = CycleResult(
            cycle_number=1,
            confirmed_tokens={"finalize": True, "execute": True},
        )
        assert RalphState._derive_outcome(r) == "COMPLETED"

    def test_execute_only_partial(self):
        r = CycleResult(
            cycle_number=1,
            confirmed_tokens={"execute": True, "finalize": False},
        )
        assert RalphState._derive_outcome(r) == "PARTIAL"

    def test_some_confirmed_partial(self):
        r = CycleResult(
            cycle_number=1,
            confirmed_tokens={"orient": True, "execute": False},
        )
        assert RalphState._derive_outcome(r) == "PARTIAL"

    def test_all_false_failed(self):
        r = CycleResult(
            cycle_number=1,
            confirmed_tokens={"orient": False, "execute": False},
        )
        assert RalphState._derive_outcome(r) == "FAILED"


# ---------------------------------------------------------------------------
# build_orient_context — additional branches
# ---------------------------------------------------------------------------


class TestBuildOrientContext:
    def test_no_files_returns_string(self, state: RalphState):
        ctx = state.build_orient_context()
        assert isinstance(ctx, str)
        assert "not found" in ctx.lower() or "progress" in ctx.lower()

    def test_with_tasks_file(self, state: RalphState):
        _write_tasks(state, "# Tasks\n- [ ] task-1 Do work\n- [x] task-2 Done\n")
        ctx = state.build_orient_context()
        assert "task-1" in ctx

    def test_with_progress_file(self, state: RalphState):
        state.progress_file.write_text("## Cycle 1\nOutcome: success\n")
        ctx = state.build_orient_context()
        assert "Cycle 1" in ctx

    def test_with_plan_file(self, state: RalphState):
        state.plan_file.write_text("# Plan\nDo something important\n")
        ctx = state.build_orient_context()
        assert "Do something important" in ctx

    def test_plan_truncated_at_40_lines(self, state: RalphState):
        lines = [f"line {i}" for i in range(50)]
        state.plan_file.write_text("\n".join(lines))
        ctx = state.build_orient_context()
        assert "truncated" in ctx

    def test_extract_pending_blocks(self, state: RalphState):
        _write_tasks(
            state,
            "header line\n"
            "- [ ] task-1 First pending task\n"
            "  detail line\n"
            "- [x] task-2 Completed task\n",
        )
        ctx = state.build_orient_context()
        assert "task-1" in ctx
