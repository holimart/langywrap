"""Output filtering for token savings.

Configures dev tools for compact output: pytest -q --tb=short,
ruff -q, mypy pretty=false, etc. Reduces AI token consumption
by 60-80% on typical quality gate output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


# Recommended settings for compact output
COMPACT_SETTINGS: dict[str, dict[str, Any]] = {
    "pytest": {
        "file": "pyproject.toml",
        "section": "tool.pytest.ini_options",
        "key": "addopts",
        "value": "-q --tb=short",
    },
    "mypy": {
        "file": "pyproject.toml",
        "section": "tool.mypy",
        "key": "pretty",
        "value": False,
    },
    "ruff": {
        "note": "Use `ruff check -q` and `ruff format -q` in justfile recipes",
    },
}


def audit_output_config(project_dir: Path) -> dict[str, str]:
    """Check which tools have compact output configured.

    Returns dict of tool -> status (ok/missing/wrong).
    """
    results: dict[str, str] = {}
    pyproject = project_dir / "pyproject.toml"

    if not pyproject.exists():
        return {"error": "no pyproject.toml found"}

    content = pyproject.read_text()

    # pytest
    if "-q" in content and "--tb=short" in content:
        results["pytest"] = "ok"
    elif "pytest" in content:
        results["pytest"] = "missing: add -q --tb=short to addopts"
    else:
        results["pytest"] = "not configured"

    # mypy
    if "pretty = false" in content or 'pretty = "false"' in content:
        results["mypy"] = "ok"
    elif "mypy" in content:
        results["mypy"] = "missing: add pretty = false"
    else:
        results["mypy"] = "not configured"

    # ruff in justfile
    justfile = project_dir / "justfile"
    if justfile.exists():
        jcontent = justfile.read_text()
        if "ruff check -q" in jcontent:
            results["ruff"] = "ok"
        elif "ruff" in jcontent:
            results["ruff"] = "missing: add -q flag"
        else:
            results["ruff"] = "not in justfile"
    else:
        results["ruff"] = "no justfile"

    return results
