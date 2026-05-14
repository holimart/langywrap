"""Project scaffolding — creates new repos from langywrap templates.

Templates live in langywrap/lib/langywrap/template/templates/.
Placeholders like __PROJECT_NAME__, __DESCRIPTION__ are substituted.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

TEMPLATE_DIR = Path(__file__).parent / "templates"

PLACEHOLDER_MAP = {
    "__PROJECT_NAME__": "name",
    "__DESCRIPTION__": "description",
    "__PYTHON_VERSION__": "python_version",
    "[PROJECT_NAME]": "name",
    "[DESCRIPTION]": "description",
}


def scaffold_project(
    target_dir: Path,
    name: str,
    description: str = "",
    python_version: str = "3.10",
    init_git: bool = True,
    init_uv: bool = True,
    couple_langywrap: bool = True,
    langywrap_dir: Path | None = None,
) -> Path:
    """Create a new project from the langywrap template.

    Args:
        target_dir: Where to create the project
        name: Project name (used in pyproject.toml, CLAUDE.md, etc.)
        description: One-line project description
        python_version: Python version for pyproject.toml
        init_git: Initialize git repo
        init_uv: Run uv init / uv sync
        couple_langywrap: Run coupling script after scaffold
        langywrap_dir: Path to langywrap repo (for coupling)

    Returns:
        Path to the created project
    """
    target = Path(target_dir) / name
    target.mkdir(parents=True, exist_ok=True)

    context = {
        "name": name,
        "description": description or f"{name} project",
        "python_version": python_version,
    }

    # Copy and substitute template files
    _copy_templates(target, context)

    # Create standard directories
    _create_directories(target, name)

    # Initialize git
    if init_git:
        subprocess.run(["git", "init"], cwd=target, capture_output=True)
        # Set up .githooks path
        subprocess.run(
            ["git", "config", "core.hooksPath", ".githooks"],
            cwd=target,
            capture_output=True,
        )

    # Initialize uv
    if init_uv:
        subprocess.run(["uv", "sync"], cwd=target, capture_output=True)

    # Couple to langywrap
    if couple_langywrap and langywrap_dir:
        couple_script = Path(langywrap_dir) / "scripts" / "couple.sh"
        if couple_script.exists():
            subprocess.run(
                ["bash", str(couple_script), str(target), "--full"],
                capture_output=True,
            )

    return target


def _copy_templates(target: Path, context: dict[str, Any]) -> None:
    """Copy template files with placeholder substitution."""
    template_map = {
        "AGENTS.md.template": "CLAUDE.md",
        "DESIGN_PRINCIPLES.md": "DESIGN_PRINCIPLES.md",
        "justfile.template": "justfile",
        "pyproject.toml.template": "pyproject.toml",
        "TEMPLATE_GUIDE.md": "docs/TEMPLATE_GUIDE.md",
    }

    for src_name, dst_name in template_map.items():
        src = TEMPLATE_DIR / src_name
        if not src.exists():
            continue

        content = src.read_text()
        for placeholder, key in PLACEHOLDER_MAP.items():
            if key in context:
                content = content.replace(placeholder, context[key])

        dst = target / dst_name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content)


def _create_directories(target: Path, name: str) -> None:
    """Create standard project directories."""
    dirs = [
        f"src/{name.replace('-', '_')}",
        "tests",
        "scripts",
        "scripts/adhoc",
        "notes",
        "docs",
        "docs/solutions",
        "docs/agent-guides",
        ".githooks",
    ]
    for d in dirs:
        (target / d).mkdir(parents=True, exist_ok=True)

    # Create __init__.py
    pkg_dir = target / "src" / name.replace("-", "_")
    init_file = pkg_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text(f'"""{name} package."""\n')

    # Create .env placeholder
    env_file = target / ".env"
    if not env_file.exists():
        env_file.write_text("# Environment variables\n")

    # Create .python-version
    pv = target / ".python-version"
    if not pv.exists():
        pv.write_text("3.10\n")

    # Create .gitignore
    gi = target / ".gitignore"
    if not gi.exists():
        gi.write_text(
            "__pycache__/\n*.pyc\n.mypy_cache/\n.ruff_cache/\n"
            "*.egg-info/\ndist/\nbuild/\n.env\n.venv/\n"
            ".langywrap/active_variant.yaml\n"
        )
