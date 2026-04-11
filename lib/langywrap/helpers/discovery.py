"""Binary discovery helpers.

Single source of truth for locating rtk, execwrap, and other optional tools.
All callers (cli.py, backends.py, gates.py) should use these instead of
duplicating candidate-list logic.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def find_binary(name: str, candidates: list[Path] | None = None) -> str | None:
    """Find a binary via PATH, then by candidate paths.

    Returns the first match as an absolute string path, or None if not found.
    Candidates are checked for existence and executable bit.
    """
    found = shutil.which(name)
    if found:
        return found
    for c in candidates or []:
        if c.exists() and c.stat().st_mode & 0o111:
            return str(c)
    return None


def find_rtk(project_dir: Path | None = None) -> str | None:
    """Locate the rtk binary (Rust Token Killer).

    Search order: PATH → project .exec/ → ~/.local/bin/ → ~/.langywrap/
    """
    candidates: list[Path] = []
    if project_dir is not None:
        candidates.append(Path(project_dir) / ".exec" / "rtk")
    candidates += [
        Path.home() / ".local" / "bin" / "rtk",
        Path.home() / ".langywrap" / "rtk",
    ]
    return find_binary("rtk", candidates)


def find_execwrap(project_dir: Path | None = None) -> str | None:
    """Locate execwrap.bash (universal execution wrapper).

    Search order: project .exec/ → ~/.langywrap/
    execwrap is never on PATH (it's a .bash file), so no PATH search.
    """
    candidates: list[Path] = []
    if project_dir is not None:
        candidates.append(Path(project_dir) / ".exec" / "execwrap.bash")
    candidates.append(Path.home() / ".langywrap" / "execwrap.bash")
    for c in candidates:
        if c.exists() and c.stat().st_mode & 0o111:
            return str(c)
    return None
