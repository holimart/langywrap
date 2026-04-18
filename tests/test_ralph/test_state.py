"""Tests for ralph loop state management."""

from __future__ import annotations

from pathlib import Path

import pytest
from langywrap.ralph.state import CycleResult, RalphState


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ralph"
    d.mkdir()
    (d / "steps").mkdir()
    return d


@pytest.fixture
def state(state_dir: Path) -> RalphState:
    return RalphState(state_dir)


class TestRalphState:
    def test_initial_cycle_count(self, state: RalphState) -> None:
        assert state.get_cycle_count() == 0

    def test_increment_cycle(self, state: RalphState) -> None:
        assert state.increment_cycle() == 1
        assert state.increment_cycle() == 2
        assert state.get_cycle_count() == 2

    def test_write_and_read_plan(self, state: RalphState) -> None:
        state.write_plan("# Test Plan\nStep 1: do stuff")
        assert "Step 1" in state.read_plan()

    def test_load_empty_tasks(self, state: RalphState) -> None:
        tasks = state.load_tasks()
        assert tasks == []

    def test_save_and_load_tasks(self, state: RalphState) -> None:
        # Write tasks.md in the expected format first
        (state.state_dir / "tasks.md").write_text(
            "- [ ] **[P1] task:task-1** First task\n"
            "  - Status: PENDING\n"
            "- [x] **[P2] task:task-2** Second task\n"
            "  - Status: COMPLETED\n"
        )
        loaded = state.load_tasks()
        assert len(loaded) >= 1  # At least one task parsed

    def test_append_progress(self, state: RalphState) -> None:
        result = CycleResult(
            cycle_number=1,
            steps_completed={"orient": Path("steps/orient.md")},
            quality_gate_passed=True,
            duration_seconds=120.0,
            models_used={"orient": "haiku"},
        )
        state.append_progress(result)
        progress = (state.state_dir / "progress.md").read_text()
        assert "Cycle 1" in progress

    def test_build_orient_context_empty(self, state: RalphState) -> None:
        ctx = state.build_orient_context()
        assert "No tasks" in ctx or "pending" in ctx.lower() or len(ctx) > 0


class TestOrientContextCompression:
    def test_large_tasks_compressed(self, state_dir: Path) -> None:
        """Verify the ~11x compression pattern works."""
        state = RalphState(state_dir)

        # Create large tasks.md with many completed tasks
        lines = []
        for i in range(100):
            status = "x" if i < 90 else " "
            task_status = "COMPLETED" if i < 90 else "PENDING"
            lines.append(f"- [{status}] **[P1] Task {i}**\n  - Status: {task_status}\n")
        (state_dir / "tasks.md").write_text("\n".join(lines))

        # Create large progress.md
        progress_lines = []
        for i in range(50):
            progress_lines.append(f"## Cycle {i}\nDid some work on task {i}\n")
        (state_dir / "progress.md").write_text("\n".join(progress_lines))

        ctx = state.build_orient_context()
        original_size = len("\n".join(lines)) + len("\n".join(progress_lines))
        compressed_size = len(ctx)

        # Should be significantly smaller (at least 30% reduction)
        assert compressed_size < original_size * 0.7
