"""Lean 4 theorem prover helpers.

Wraps lean-check.sh functionality as Python functions for ralph loops
targeting Lean/Mathlib projects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from langywrap.helpers.process import run_subprocess


@dataclass
class LeanCheckResult:
    passed: bool
    sorry_count: int = 0
    errors: list[str] | None = None
    stale_oleans: list[str] | None = None
    output: str = ""


@dataclass
class SorryInfo:
    file: str
    line: int
    context: str


def lean_build(
    project_dir: Path, targets: list[str] | None = None, timeout: int = 300
) -> LeanCheckResult:
    """Run lake build, optionally on specific targets."""
    cmd = ["lake", "build"]
    if targets:
        cmd.extend(targets)

    passed, output, _ = run_subprocess(cmd, cwd=project_dir, timeout=timeout)
    return LeanCheckResult(
        passed=passed,
        errors=_parse_lean_errors(output),
        output=output[-3000:],
    )


def count_sorries(project_dir: Path, src_dir: str = ".") -> list[SorryInfo]:
    """Count sorry occurrences in Lean files (comment-aware).

    Uses the awk-based comment-stripping pattern from riemann2's lean-check.sh.
    Skips sorries that appear only in comments or docstrings.
    """
    sorries: list[SorryInfo] = []
    src_path = Path(project_dir) / src_dir

    for lean_file in src_path.rglob("*.lean"):
        content = lean_file.read_text()
        # Strip block comments /- ... -/
        stripped = re.sub(r"/\-.*?\-/", "", content, flags=re.DOTALL)
        # Strip line comments -- ...
        stripped = re.sub(r"--.*$", "", stripped, flags=re.MULTILINE)

        for i, line in enumerate(stripped.splitlines(), 1):
            if re.search(r"\bsorry\b", line):
                sorries.append(
                    SorryInfo(
                        file=str(lean_file.relative_to(project_dir)),
                        line=i,
                        context=line.strip()[:100],
                    )
                )

    return sorries


def check_stale_oleans(project_dir: Path) -> list[str]:
    """Detect .olean files newer than their .lean source (stale cache)."""
    stale: list[str] = []
    for lean_file in Path(project_dir).rglob("*.lean"):
        olean = lean_file.with_suffix(".olean")
        if olean.exists() and olean.stat().st_mtime < lean_file.stat().st_mtime:
            stale.append(str(lean_file.relative_to(project_dir)))
    return stale


def check_axioms(project_dir: Path, src_dir: str = ".") -> list[str]:
    """Find custom axiom declarations (non-standard axioms that need elimination)."""
    standard_axioms = {"propext", "Quot.sound", "Classical.choice"}
    custom: list[str] = []

    for lean_file in (Path(project_dir) / src_dir).rglob("*.lean"):
        for i, line in enumerate(lean_file.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("axiom "):
                name = stripped.split()[1].rstrip(":")
                if name not in standard_axioms:
                    custom.append(f"{lean_file.name}:{i}: {stripped[:80]}")

    return custom


def lean_retry_loop(
    project_dir: Path,
    lean_file: Path,
    fix_prompt_template: str,
    max_retries: int = 5,
) -> tuple[bool, str]:
    """Run lean build, on failure extract errors and return fix prompt.

    Returns (success, prompt_or_output). If success, prompt_or_output is empty.
    If failure, prompt_or_output contains the error-injection prompt for the executor.
    """
    for attempt in range(max_retries):
        result = lean_build(project_dir, targets=[lean_file.stem])
        if result.passed:
            return True, ""

        error_context = result.output[-2000:]
        prompt = fix_prompt_template.replace("$ERRORS", error_context)
        prompt = prompt.replace("$FILE", str(lean_file))
        prompt = prompt.replace("$ATTEMPT", str(attempt + 1))
        prompt = prompt.replace("$MAX_RETRIES", str(max_retries))

        if attempt < max_retries - 1:
            # Return prompt for next attempt (caller feeds to executor)
            return False, prompt

    return False, f"Failed after {max_retries} retries:\n{result.output[-1000:]}"


def _parse_lean_errors(output: str) -> list[str]:
    """Extract error lines from lean/lake output."""
    errors = []
    for line in output.splitlines():
        if ": error:" in line.lower() or "error:" in line.lower():
            errors.append(line.strip()[:200])
    return errors
