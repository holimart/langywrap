"""Subprocess helpers with uniform error handling.

All callers that run external commands through quality gates, lean checks, etc.
should use run_subprocess instead of calling subprocess.run directly with
duplicated try/except blocks.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_subprocess(
    cmd: list[str],
    cwd: Path | None = None,
    timeout: int = 300,
) -> tuple[bool, str, int]:
    """Run a command and return (success, combined_output, returncode).

    Handles the three common failure modes uniformly:
    - Normal failure:  (False, stdout+stderr, returncode)
    - Timeout:         (False, "TIMEOUT after Ns", -1)
    - Missing binary:  (False, "Command not found: ...", -2)

    Output is *not* truncated here — callers truncate to their own limits.
    """
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode == 0, proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT after {timeout}s", -1
    except FileNotFoundError as e:
        return False, f"Command not found: {e}", -2
