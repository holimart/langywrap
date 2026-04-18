from __future__ import annotations

from pathlib import Path

from langywrap.ralph.step_logger import StepLogger

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_logger(tmp_path: Path) -> StepLogger:
    return StepLogger(logs_dir=tmp_path / "logs")


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


def test_init_creates_logs_dir(tmp_path):
    logs_dir = tmp_path / "logs" / "sub"
    logger = StepLogger(logs_dir=logs_dir)
    assert logs_dir.exists()
    logger.close()


def test_init_creates_master_log_file(tmp_path):
    logger = make_logger(tmp_path)
    assert logger.master_log.exists()
    logger.close()


# ---------------------------------------------------------------------------
# log()
# ---------------------------------------------------------------------------


def test_log_writes_to_master_log(tmp_path, capsys):
    logger = make_logger(tmp_path)
    logger.log("hello world")
    logger.close()
    content = logger.master_log.read_text()
    assert "hello world" in content


def test_log_has_timestamp_prefix(tmp_path):
    logger = make_logger(tmp_path)
    logger.log("test line")
    logger.close()
    content = logger.master_log.read_text()
    # Format: [YYYY-MM-DD HH:MM:SS] [ralph] test line
    assert "[ralph]" in content
    assert "test line" in content


def test_log_empty_string(tmp_path):
    logger = make_logger(tmp_path)
    logger.log("")
    logger.close()
    content = logger.master_log.read_text()
    assert "[ralph]" in content


def test_log_multiline_splits(tmp_path):
    logger = make_logger(tmp_path)
    logger.log("line1\nline2\nline3")
    logger.close()
    content = logger.master_log.read_text()
    assert "line1" in content
    assert "line2" in content
    assert "line3" in content
    # Each line should have its own timestamp tag
    assert content.count("[ralph]") >= 3


# ---------------------------------------------------------------------------
# open_step()
# ---------------------------------------------------------------------------


def test_open_step_creates_file(tmp_path):
    logger = make_logger(tmp_path)
    path = logger.open_step("orient", model="test-model", timeout_minutes=10)
    logger.close()
    assert path.exists()


def test_open_step_returns_path(tmp_path):
    logger = make_logger(tmp_path)
    path = logger.open_step("plan")
    logger.close()
    assert isinstance(path, Path)
    assert "plan" in path.name


def test_open_step_sets_current_step_log(tmp_path):
    logger = make_logger(tmp_path)
    path = logger.open_step("execute")
    logger.close()
    assert logger._current_step_log == path


def test_open_step_engine_not_auto_emits(tmp_path):
    logger = make_logger(tmp_path)
    logger.open_step("orient", engine="opencode")
    logger.close()
    content = logger.master_log.read_text()
    assert "opencode" in content


def test_open_step_engine_auto_not_emitted(tmp_path):
    logger = make_logger(tmp_path)
    logger.open_step("orient", engine="auto")
    logger.close()
    content = logger.master_log.read_text()
    assert "Engine:" not in content


def test_open_step_tools_emitted(tmp_path):
    logger = make_logger(tmp_path)
    logger.open_step("execute", tools="bash,python")
    logger.close()
    content = logger.master_log.read_text()
    assert "bash,python" in content


# ---------------------------------------------------------------------------
# close_step()
# ---------------------------------------------------------------------------


def test_close_step_success_writes_output(tmp_path):
    logger = make_logger(tmp_path)
    path = logger.open_step("execute")
    logger.close_step("execute", output="some output", success=True)
    logger.close()
    assert "some output" in path.read_text()


def test_close_step_success_emits_completed(tmp_path):
    logger = make_logger(tmp_path)
    logger.open_step("execute")
    logger.close_step("execute", output="out", success=True)
    logger.close()
    content = logger.master_log.read_text()
    assert "COMPLETED" in content


def test_close_step_failure_emits_failed(tmp_path):
    logger = make_logger(tmp_path)
    logger.open_step("execute")
    logger.close_step("execute", output="error text", success=False)
    logger.close()
    content = logger.master_log.read_text()
    assert "FAILED" in content


def test_close_step_failure_tails_output(tmp_path):
    logger = make_logger(tmp_path)
    logger.open_step("execute")
    many_lines = "\n".join(f"line{i}" for i in range(20))
    logger.close_step("execute", output=many_lines, success=False)
    logger.close()
    content = logger.master_log.read_text()
    # Should tail last 10 lines
    assert "line19" in content


def test_close_step_with_duration(tmp_path):
    logger = make_logger(tmp_path)
    logger.open_step("execute")
    logger.close_step("execute", output="x", success=True, duration=42.3)
    logger.close()
    content = logger.master_log.read_text()
    assert "42.3s" in content


def test_close_step_no_duration_omits_in_str(tmp_path):
    logger = make_logger(tmp_path)
    logger.open_step("execute")
    logger.close_step("execute", output="x", success=True, duration=0.0)
    logger.close()
    content = logger.master_log.read_text()
    assert "in 0.0s" not in content


# ---------------------------------------------------------------------------
# stop_heartbeat() noop
# ---------------------------------------------------------------------------


def test_stop_heartbeat_noop_when_no_thread(tmp_path):
    logger = make_logger(tmp_path)
    # Should not raise
    logger.stop_heartbeat()
    logger.close()


# ---------------------------------------------------------------------------
# close() idempotent
# ---------------------------------------------------------------------------


def test_close_idempotent(tmp_path):
    logger = make_logger(tmp_path)
    logger.close()
    # Second close should not raise
    logger.close()
