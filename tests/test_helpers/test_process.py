from __future__ import annotations

import sys

from langywrap.helpers.process import run_subprocess


def test_successful_echo():
    ok, output, rc = run_subprocess(["echo", "hello"])
    assert ok is True
    assert "hello" in output
    assert rc == 0


def test_failing_command():
    ok, output, rc = run_subprocess([sys.executable, "-c", "import sys; sys.exit(1)"])
    assert ok is False
    assert rc == 1


def test_timeout_expired():
    ok, output, rc = run_subprocess(["sleep", "10"], timeout=1)
    assert ok is False
    assert "TIMEOUT" in output
    assert rc == -1


def test_missing_binary():
    ok, output, rc = run_subprocess(["__nonexistent_binary_xyz__"])
    assert ok is False
    assert "Command not found" in output
    assert rc == -2


def test_cwd_parameter(tmp_path):
    # Write a marker file and list it from cwd
    marker = tmp_path / "marker.txt"
    marker.write_text("x")
    ok, output, rc = run_subprocess(["ls", "marker.txt"], cwd=tmp_path)
    assert ok is True
    assert "marker.txt" in output


def test_combined_stdout_stderr():
    script = "import sys; print('OUT'); print('ERR', file=sys.stderr)"
    ok, output, rc = run_subprocess([sys.executable, "-c", script])
    assert ok is True
    assert "OUT" in output
    assert "ERR" in output


def test_nonzero_rc_captured():
    ok, output, rc = run_subprocess([sys.executable, "-c", "import sys; sys.exit(42)"])
    assert ok is False
    assert rc == 42
