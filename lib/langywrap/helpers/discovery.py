"""Binary discovery helpers.

Single source of truth for locating rtk, execwrap, and other optional tools.
All callers (cli.py, backends.py, gates.py) should use these instead of
duplicating candidate-list logic.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import yaml


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


def _package_root() -> Path:
    """Return the langywrap checkout/package root for editable installs."""
    return Path(__file__).resolve().parents[3]


def _configured_langywrap_dir(project_dir: Path | None = None) -> Path | None:
    """Read a downstream repo's .langywrap/config.yaml hub pointer if present."""
    if project_dir is None:
        return None
    cfg = Path(project_dir) / ".langywrap" / "config.yaml"
    if not cfg.is_file():
        return None
    try:
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    path = data.get("langywrap_dir")
    if not path:
        return None
    p = Path(str(path)).expanduser()
    return p if p.exists() else None


def _candidate_roots(project_dir: Path | None = None) -> list[Path]:
    """Roots searched after project-local installs and PATH."""
    roots: list[Path] = []
    configured = _configured_langywrap_dir(project_dir)
    if configured is not None:
        roots.append(configured)
    if project_dir is not None:
        sibling = Path(project_dir).resolve().parent / "langywrap"
        if sibling.exists():
            roots.append(sibling)
    roots.append(_package_root())

    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def _tool_candidates(name: str, project_dir: Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get(f"LANGYWRAP_{name.upper()}_PATH")
    if env_path:
        candidates.append(Path(env_path).expanduser())
    if project_dir is not None:
        project = Path(project_dir)
        candidates += [
            project / ".exec" / name,
            project / ".venv" / "bin" / name,
            project / "scripts" / ".venv" / "bin" / name,
        ]
    for root in _candidate_roots(project_dir):
        candidates += [
            root / ".exec" / name,
            root / "execwrap" / name,
            root / ".venv" / "bin" / name,
        ]
    candidates += [
        Path.home() / ".local" / "bin" / name,
        Path.home() / ".langywrap" / name,
    ]
    return candidates


def find_tool(name: str, project_dir: Path | None = None) -> str | None:
    """Locate a tool with project-local first, then PATH, then langywrap fallbacks."""
    env_path = os.environ.get(f"LANGYWRAP_{name.upper()}_PATH")
    if env_path:
        p = Path(env_path).expanduser()
        if p.exists() and p.stat().st_mode & 0o111:
            return str(p)
    project_candidates: list[Path] = []
    if project_dir is not None:
        project = Path(project_dir)
        project_candidates = [
            project / ".exec" / name,
            project / ".venv" / "bin" / name,
            project / "scripts" / ".venv" / "bin" / name,
        ]
    for c in project_candidates:
        if c.exists() and c.stat().st_mode & 0o111:
            return str(c)

    found = shutil.which(name)
    if found:
        return found

    fallback_candidates = [
        c for c in _tool_candidates(name, project_dir) if c not in project_candidates
    ]
    return find_binary(name, fallback_candidates)


def find_execwrap(project_dir: Path | None = None) -> str | None:
    """Locate execwrap.bash, preferring project-local over langywrap fallbacks."""
    env_path = os.environ.get("LANGYWRAP_EXECWRAP_PATH")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path).expanduser())
    if project_dir is not None:
        candidates.append(Path(project_dir) / ".exec" / "execwrap.bash")
    for root in _candidate_roots(project_dir):
        candidates.append(root / "execwrap" / "execwrap.bash")
    candidates.append(Path.home() / ".langywrap" / "execwrap.bash")
    for c in candidates:
        if c.exists() and c.stat().st_mode & 0o111:
            return str(c)
    return None


def _tool_hint(name: str) -> str:
    hints = {
        "execwrap": (
            "Run: ../langywrap/scripts/couple.sh . --defaults, or chmod +x "
            ".exec/execwrap.bash if it already exists."
        ),
        "rtk": (
            "Run from langywrap: ./just install-rtk, or rerun coupling to copy "
            ".exec/rtk into this project."
        ),
        "textify": (
            "Run from langywrap: ./just install-textify, or uv sync --extra knowledge-graph."
        ),
        "graphify": (
            "Run from langywrap: ./just install-graphify, or uv sync --extra knowledge-graph."
        ),
        "openwolf": (
            "Run from langywrap: ./just install-openwolf, then `langywrap "
            "integration openwolf wire . --init --langywrap-only`."
        ),
    }
    return hints.get(name, f"Install {name} or set LANGYWRAP_{name.upper()}_PATH.")


def discovery_report(project_dir: Path | None = None) -> dict[str, Any]:
    """Return tool discovery details for Ralph preflight diagnostics."""
    tools = {
        "execwrap": find_execwrap(project_dir),
        "rtk": find_rtk(project_dir),
        "textify": find_tool("textify", project_dir),
        "graphify": find_tool("graphify", project_dir),
        "openwolf": find_tool("openwolf", project_dir),
    }
    issues: list[str] = []
    hints: dict[str, str] = {}
    for name, path in tools.items():
        if path is None:
            issues.append(
                f"{name} not discovered in project, PATH, or langywrap fallback locations"
            )
            hints[name] = _tool_hint(name)

    return {
        "tools": tools,
        "langywrap_roots": [str(p) for p in _candidate_roots(project_dir)],
        "issues": issues,
        "hints": hints,
    }


def find_rtk(project_dir: Path | None = None) -> str | None:
    """Locate the rtk binary (Rust Token Killer).

    Search order: PATH → project .exec/ → ~/.local/bin/ → ~/.langywrap/
    """
    return find_tool("rtk", project_dir)
