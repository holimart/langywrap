from __future__ import annotations

from unittest.mock import patch

from langywrap.quality.gates import GateResult, QualityReport, QualityRunner

# ---------------------------------------------------------------------------
# GateResult
# ---------------------------------------------------------------------------


def test_gate_result_defaults():
    r = GateResult(name="lint", passed=True)
    assert r.name == "lint"
    assert r.passed is True
    assert r.output == ""
    assert r.duration_seconds == 0.0
    assert r.returncode == 0


def test_gate_result_failed():
    r = GateResult(name="mypy", passed=False, output="error", returncode=1)
    assert r.passed is False
    assert r.returncode == 1


# ---------------------------------------------------------------------------
# QualityReport
# ---------------------------------------------------------------------------


def test_quality_report_defaults():
    rep = QualityReport()
    assert rep.all_passed is True
    assert rep.gates == []
    assert rep.total_duration == 0.0


# ---------------------------------------------------------------------------
# QualityRunner init
# ---------------------------------------------------------------------------


def test_init_with_explicit_paths(tmp_path):
    runner = QualityRunner(
        project_dir=tmp_path,
        rtk_path="/fake/rtk",
        execwrap_path="/fake/execwrap.bash",
    )
    assert runner.rtk_path == "/fake/rtk"
    assert runner.execwrap_path == "/fake/execwrap.bash"


def test_init_default_gates(tmp_path):
    runner = QualityRunner(project_dir=tmp_path, rtk_path=None, execwrap_path=None)
    assert "lint" in runner.gates or "typecheck" in runner.gates or "pytest" in runner.gates


# ---------------------------------------------------------------------------
# run_gate — builtin name resolves to cmd list
# ---------------------------------------------------------------------------


def test_run_gate_builtin_name_resolves(tmp_path):
    runner = QualityRunner(project_dir=tmp_path, rtk_path=None, execwrap_path=None)

    def fake_run(cmd, cwd=None, timeout=300):
        # Capture what cmd was built and return success
        assert isinstance(cmd, list)
        return True, "ok", 0

    with patch("langywrap.quality.gates.run_subprocess", side_effect=fake_run):
        result = runner.run_gate("ruff")
    assert result.name == "ruff"
    assert result.passed is True


def test_run_gate_custom_list(tmp_path):
    runner = QualityRunner(project_dir=tmp_path, rtk_path=None, execwrap_path=None)

    with patch("langywrap.quality.gates.run_subprocess", return_value=(True, "ok", 0)):
        result = runner.run_gate(["echo", "ok"])
    assert result.passed is True


def test_run_gate_echo_actually_works(tmp_path):
    """Real subprocess: echo is always available."""
    runner = QualityRunner(project_dir=tmp_path, rtk_path=None, execwrap_path=None)
    result = runner.run_gate(["echo", "hello"])
    assert result.passed is True
    assert "hello" in result.output


# ---------------------------------------------------------------------------
# run_all
# ---------------------------------------------------------------------------


def test_run_all_all_passed(tmp_path):
    runner = QualityRunner(
        project_dir=tmp_path,
        gates=[["echo", "a"], ["echo", "b"]],
        rtk_path=None,
        execwrap_path=None,
    )
    report = runner.run_all()
    assert report.all_passed is True
    assert len(report.gates) == 2


def test_run_all_one_fails(tmp_path):
    runner = QualityRunner(
        project_dir=tmp_path,
        gates=[["echo", "ok"], ["false"]],
        rtk_path=None,
        execwrap_path=None,
    )
    report = runner.run_all()
    assert report.all_passed is False
    assert any(not g.passed for g in report.gates)


def test_run_all_duration_set(tmp_path):
    runner = QualityRunner(
        project_dir=tmp_path,
        gates=[["echo", "x"]],
        rtk_path=None,
        execwrap_path=None,
    )
    report = runner.run_all()
    assert report.total_duration >= 0.0


# ---------------------------------------------------------------------------
# add_gate
# ---------------------------------------------------------------------------


def test_add_gate_registers_and_runs(tmp_path):
    runner = QualityRunner(
        project_dir=tmp_path,
        gates=[],
        rtk_path=None,
        execwrap_path=None,
    )
    runner.add_gate("myecho", ["echo", "from-myecho"])
    assert "myecho" in runner.gates
    result = runner.run_gate("myecho")
    assert result.passed is True
    assert "from-myecho" in result.output


# ---------------------------------------------------------------------------
# from_justfile
# ---------------------------------------------------------------------------


def test_from_justfile_with_justfile(tmp_path):
    jf = tmp_path / "justfile"
    jf.write_text("check:\n  echo ok\n")
    runner = QualityRunner.from_justfile(tmp_path, rtk_path=None, execwrap_path=None)
    assert runner.gates == ["just-check"]


def test_from_justfile_without_justfile(tmp_path):
    runner = QualityRunner.from_justfile(tmp_path, rtk_path=None, execwrap_path=None)
    # Falls back to default gates
    assert runner.gates == ["lint", "typecheck", "pytest"]
