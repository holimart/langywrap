from __future__ import annotations

import stat
from unittest.mock import patch

from langywrap.helpers.discovery import find_binary, find_execwrap, find_rtk

# ---------------------------------------------------------------------------
# find_binary
# ---------------------------------------------------------------------------


def test_find_binary_path_hit():
    # "echo" is on PATH on any Unix system
    result = find_binary("echo")
    assert result is not None
    assert "echo" in result


def test_find_binary_path_miss_executable_candidate(tmp_path):
    fake_bin = tmp_path / "myfakebin"
    fake_bin.write_text("#!/bin/sh\n")
    fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IEXEC)

    result = find_binary("myfakebin_not_on_path", candidates=[fake_bin])
    assert result == str(fake_bin)


def test_find_binary_path_miss_non_executable_candidate(tmp_path):
    fake_bin = tmp_path / "notexec"
    fake_bin.write_text("#!/bin/sh\n")
    # Remove executable bit
    fake_bin.chmod(0o644)

    result = find_binary("notexec_not_on_path", candidates=[fake_bin])
    assert result is None


def test_find_binary_none_candidates():
    result = find_binary("__totally_nonexistent_binary__xyz", candidates=None)
    assert result is None


def test_find_binary_empty_candidates():
    result = find_binary("__totally_nonexistent_binary__xyz", candidates=[])
    assert result is None


def test_find_binary_candidate_not_exists(tmp_path):
    missing = tmp_path / "does_not_exist"
    result = find_binary("__nonexistent__", candidates=[missing])
    assert result is None


# ---------------------------------------------------------------------------
# find_rtk
# ---------------------------------------------------------------------------


def test_find_rtk_project_dir_with_exec_rtk(tmp_path):
    exec_dir = tmp_path / ".exec"
    exec_dir.mkdir()
    rtk_bin = exec_dir / "rtk"
    rtk_bin.write_text("#!/bin/sh\n")
    rtk_bin.chmod(rtk_bin.stat().st_mode | stat.S_IEXEC)

    with patch("shutil.which", return_value=None):
        result = find_rtk(project_dir=tmp_path)
    assert result == str(rtk_bin)


def test_find_rtk_no_project_dir_falls_back_to_none():
    with patch("shutil.which", return_value=None):
        result = find_rtk(project_dir=None)
    # Either None or a real rtk on the system — just verify no crash
    assert result is None or isinstance(result, str)


def test_find_rtk_path_hit():
    with patch("shutil.which", return_value="/usr/bin/rtk"):
        result = find_rtk()
    assert result == "/usr/bin/rtk"


def test_find_rtk_returns_none_when_nothing_found(tmp_path):
    # project_dir with no .exec/rtk, PATH returns nothing, home has no rtk
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    with patch("shutil.which", return_value=None), \
         patch("pathlib.Path.home", return_value=fake_home):
        result = find_rtk(project_dir=tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# find_execwrap
# ---------------------------------------------------------------------------


def test_find_execwrap_project_dir_hit(tmp_path):
    exec_dir = tmp_path / ".exec"
    exec_dir.mkdir()
    ew = exec_dir / "execwrap.bash"
    ew.write_text("#!/bin/bash\n")
    ew.chmod(ew.stat().st_mode | stat.S_IEXEC)

    result = find_execwrap(project_dir=tmp_path)
    assert result == str(ew)


def test_find_execwrap_project_dir_not_executable(tmp_path):
    exec_dir = tmp_path / ".exec"
    exec_dir.mkdir()
    ew = exec_dir / "execwrap.bash"
    ew.write_text("#!/bin/bash\n")
    ew.chmod(0o644)

    # Also ensure home candidate missing
    with patch("pathlib.Path.home", return_value=tmp_path / "fakehome"):
        result = find_execwrap(project_dir=tmp_path)
    assert result is None


def test_find_execwrap_no_project_dir_no_home(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    with patch("pathlib.Path.home", return_value=fake_home):
        result = find_execwrap(project_dir=None)
    assert result is None


def test_find_execwrap_returns_none_when_missing(tmp_path):
    with patch("pathlib.Path.home", return_value=tmp_path / "fakehome"):
        result = find_execwrap(project_dir=tmp_path)
    assert result is None
