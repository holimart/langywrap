from __future__ import annotations

import os
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXECWRAP = ROOT / "execwrap" / "execwrap.bash"
RTK = ROOT / ".exec" / "rtk"


def _minimal_settings(interceptor_path: str) -> dict:
    return {
        "features": {
            "env_loading": {"enabled": False, "env_file": ".env"},
            "adhoc_saving": {"enabled": False, "dir": "scripts/adhoc"},
            "logging": {"enabled": False, "dir": ".log"},
            "tmux": {"enabled": False, "default_mode": "none", "session_prefix": "execwrap"},
            "hooks": {"enabled": False},
            "hardening": {
                "enabled": True,
                "guard": {"enabled": False, "path": ".llmsec/guard.sh"},
                "interceptor": {"enabled": True, "path": interceptor_path},
            },
            "rtk": {"enabled": False, "path": ".exec/rtk"},
            "local_priority": {"enabled": False, "binaries": []},
            "debug_info": {"enabled": True},
        },
        "rules": [],
    }


@pytest.mark.skipif(shutil.which("jq") is None, reason="execwrap settings require jq")
@pytest.mark.skipif(not EXECWRAP.exists(), reason="execwrap script is absent")
@pytest.mark.skipif(not RTK.exists(), reason="RTK binary is absent")
def test_execwrap_project_override_finds_sibling_rtk(tmp_path: Path) -> None:
    proc = subprocess.run(
        [str(EXECWRAP), "-c", "ls -l >/dev/null"],
        cwd=tmp_path,
        env={
            **os.environ,
            "EXECWRAP_PROJECT_DIR": str(tmp_path),
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    output = proc.stdout + proc.stderr

    assert proc.returncode == 0, output
    assert "RTK rewrite:" in output
    assert "rtk ls -l >/dev/null" in output
    assert "rtk: command not found" not in output


@pytest.mark.skipif(shutil.which("jq") is None, reason="execwrap settings require jq")
@pytest.mark.skipif(not EXECWRAP.exists(), reason="execwrap script is absent")
def test_symlinked_execwrap_prefers_project_local_settings(tmp_path: Path) -> None:
    exec_dir = tmp_path / ".exec"
    exec_dir.mkdir()
    (exec_dir / "execwrap.bash").symlink_to(EXECWRAP)
    (exec_dir / "settings.json").write_text(
        json.dumps(_minimal_settings(".exec/local-interceptor.py"))
    )

    proc = subprocess.run(
        [str(exec_dir / "execwrap.bash"), "-c", "true"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    output = proc.stdout + proc.stderr

    assert proc.returncode == 0, output
    assert f"{tmp_path}/.exec/local-interceptor.py" in output
    assert "execsec/tools/interceptors/intercept-enhanced.py" not in output


@pytest.mark.skipif(shutil.which("jq") is None, reason="execwrap settings require jq")
@pytest.mark.skipif(not EXECWRAP.exists(), reason="execwrap script is absent")
def test_symlinked_execwrap_falls_back_to_langywrap_settings_when_local_missing(
    tmp_path: Path,
) -> None:
    exec_dir = tmp_path / ".exec"
    exec_dir.mkdir()
    (exec_dir / "execwrap.bash").symlink_to(EXECWRAP)

    proc = subprocess.run(
        [str(exec_dir / "execwrap.bash"), "-c", "true"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    output = proc.stdout + proc.stderr

    assert proc.returncode == 0, output
    assert f"{tmp_path}/execsec/tools/interceptors/intercept-enhanced.py" in output
