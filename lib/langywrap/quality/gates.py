"""Pluggable quality gate runner.

Downstream repos declare gates in .langywrap/ralph.yaml or justfile.
This module runs them uniformly and reports pass/fail with structured output.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from langywrap.helpers.discovery import find_execwrap, find_rtk
from langywrap.helpers.process import run_subprocess

try:
    from langywrap.router.backends import wrap_cmd
except ImportError:  # defensive — backends may not always be available
    def wrap_cmd(cmd, execwrap_path=None, rtk_path=None, *, shell_mode=False):  # type: ignore[misc]
        return cmd


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
        rtk_path: str | None = None,
        execwrap_path: str | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.gates = gates or ["lint", "typecheck", "pytest"]

        self.rtk_path = rtk_path if rtk_path is not None else find_rtk(self.project_dir)
        self.execwrap_path = (
            execwrap_path if execwrap_path is not None else find_execwrap(self.project_dir)
        )

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

        # Quality gates must preserve the command's exit status exactly. Execwrap
        # may apply RTK internally while still running the shell command, but a
        # direct RTK prefix can treat unsupported gate commands as successful.
        rtk_path = self.rtk_path if self.execwrap_path else None
        cmd = wrap_cmd(cmd, self.execwrap_path, rtk_path, shell_mode=True)

        start = time.monotonic()
        passed, output, returncode = run_subprocess(
            cmd, cwd=self.project_dir, timeout=timeout_minutes * 60
        )
        duration = time.monotonic() - start
        return GateResult(
            name=name,
            passed=passed,
            output=output[-2000:],  # Truncate for token savings
            duration_seconds=duration,
            returncode=returncode,
        )

    def add_gate(self, name: str, command: list[str]) -> None:
        """Register a custom gate."""
        self.BUILTIN_GATES[name] = command
        self.gates.append(name)

    @classmethod
    def from_justfile(
        cls,
        project_dir: Path,
        rtk_path: str | None = None,
        execwrap_path: str | None = None,
    ) -> QualityRunner:
        """Auto-detect gates from justfile 'check' recipe."""
        justfile = Path(project_dir) / "justfile"
        if not justfile.exists():
            return cls(project_dir, rtk_path=rtk_path, execwrap_path=execwrap_path)

        # Default to ./just check which runs lint + typecheck + test
        return cls(
            project_dir, gates=["just-check"], rtk_path=rtk_path, execwrap_path=execwrap_path
        )
