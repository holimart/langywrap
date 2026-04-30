from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXECWRAP = ROOT / "execwrap" / "execwrap.bash"
RTK = ROOT / ".exec" / "rtk"


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
