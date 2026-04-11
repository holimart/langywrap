"""Pluggable quality gate runner.

Downstream repos declare gates in .langywrap/ralph.yaml or justfile.
This module runs them uniformly and reports pass/fail with structured output.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class GateResult:
    name: str
    passed: bool
    output: str = ""
    duration_seconds: float = 0.0
    returncode: int = 0


@dataclass
class QualityReport:
    gates: list[GateResult] = field(default_factory=list)
    all_passed: bool = True
    total_duration: float = 0.0


# Tools that RTK has Python-ecosystem filters for.
# When RTK is available, `./uv run TOOL ...` is rewritten to `rtk TOOL ...`
# for real output compression (vs. passthrough-only for unknown commands).
_RTK_PYTHON_TOOLS = frozenset({"ruff", "pytest", "mypy", "black", "isort"})


def _rtk_wrap_cmd(cmd: list[str], rtk_path: Optional[str]) -> list[str]:
    """Rewrite a gate command to use RTK when beneficial.

    ``./uv run TOOL ...`` → ``rtk TOOL ...`` for RTK-filterable tools.
    Other commands are returned unchanged.
    """
    if not rtk_path:
        return cmd

    # Detect ./uv run TOOL ... pattern
    if len(cmd) >= 3 and cmd[0] in ("./uv", "uv") and cmd[1] == "run":
        tool = cmd[2]
        if tool in _RTK_PYTHON_TOOLS:
            return [rtk_path, tool, *cmd[3:]]

    return cmd


def _execwrap_cmd(cmd: list[str], execwrap_path: Optional[str]) -> list[str]:
    """Prepend execwrap security wrapper when available."""
    if execwrap_path and Path(execwrap_path).exists():
        return [execwrap_path] + cmd
    return cmd


class QualityRunner:
    """Runs quality gates in sequence, collecting results."""

    # Built-in gates that can be referenced by name
    BUILTIN_GATES: dict[str, list[str]] = {
        "ruff": ["./uv", "run", "ruff", "check", "-q"],
        "ruff-fix": ["./uv", "run", "ruff", "check", "--fix", "-q"],
        "mypy": ["./uv", "run", "mypy", "--config-file=pyproject.toml"],
        "pytest": ["./uv", "run", "pytest", "-q", "--tb=short"],
        "pytest-fast": ["./uv", "run", "pytest", "-q", "--tb=short", "-m", "not slow"],
        "fmt": ["./uv", "run", "ruff", "format", "-q", "--check"],
        "lint": ["./uv", "run", "ruff", "check", "-q"],
        "typecheck": ["./uv", "run", "mypy"],
        "just-check": ["./just", "check"],
        "just-validate": ["./just", "validate"],
        "lean-build": ["lake", "build"],
    }

    def __init__(
        self,
        project_dir: Path,
        gates: list[str | list[str]] | None = None,
        rtk_path: Optional[str] = None,
        execwrap_path: Optional[str] = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.gates = gates or ["lint", "typecheck", "pytest"]

        # Auto-detect RTK if not provided
        if rtk_path is None:
            rtk_path = shutil.which("rtk")
            if not rtk_path:
                for candidate in [
                    Path.home() / ".local" / "bin" / "rtk",
                    Path.home() / ".langywrap" / "rtk",
                ]:
                    if candidate.exists() and candidate.stat().st_mode & 0o111:
                        rtk_path = str(candidate)
                        break
        self.rtk_path = rtk_path

        # Auto-detect execwrap if not provided
        if execwrap_path is None:
            for candidate in [
                self.project_dir / ".exec" / "execwrap.bash",
                Path.home() / ".langywrap" / "execwrap.bash",
            ]:
                if candidate.exists() and candidate.stat().st_mode & 0o111:
                    execwrap_path = str(candidate)
                    break
        self.execwrap_path = execwrap_path

    def run_all(self, timeout_minutes: int = 10) -> QualityReport:
        """Run all configured gates. Returns report."""
        report = QualityReport()
        start = time.monotonic()

        for gate in self.gates:
            result = self.run_gate(gate, timeout_minutes)
            report.gates.append(result)
            if not result.passed:
                report.all_passed = False

        report.total_duration = time.monotonic() - start
        return report

    def run_gate(self, gate: str | list[str], timeout_minutes: int = 10) -> GateResult:
        """Run a single gate by name or command list."""
        if isinstance(gate, str):
            name = gate
            cmd = self.BUILTIN_GATES.get(gate, [gate])
        else:
            name = " ".join(gate[:2])
            cmd = gate

        cmd = _rtk_wrap_cmd(cmd, self.rtk_path)
        cmd = _execwrap_cmd(cmd, self.execwrap_path)

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=timeout_minutes * 60,
            )
            duration = time.monotonic() - start
            return GateResult(
                name=name,
                passed=proc.returncode == 0,
                output=(proc.stdout + proc.stderr)[-2000:],  # Truncate for token savings
                duration_seconds=duration,
                returncode=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return GateResult(
                name=name,
                passed=False,
                output=f"TIMEOUT after {timeout_minutes}min",
                duration_seconds=timeout_minutes * 60,
                returncode=-1,
            )
        except FileNotFoundError as e:
            return GateResult(
                name=name,
                passed=False,
                output=f"Command not found: {e}",
                returncode=-2,
            )

    def add_gate(self, name: str, command: list[str]) -> None:
        """Register a custom gate."""
        self.BUILTIN_GATES[name] = command
        self.gates.append(name)

    @classmethod
    def from_justfile(
        cls,
        project_dir: Path,
        rtk_path: Optional[str] = None,
        execwrap_path: Optional[str] = None,
    ) -> "QualityRunner":
        """Auto-detect gates from justfile 'check' recipe."""
        justfile = Path(project_dir) / "justfile"
        if not justfile.exists():
            return cls(project_dir, rtk_path=rtk_path, execwrap_path=execwrap_path)

        # Default to ./just check which runs lint + typecheck + test
        return cls(project_dir, gates=["just-check"], rtk_path=rtk_path, execwrap_path=execwrap_path)
