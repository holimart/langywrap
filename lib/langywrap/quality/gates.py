"""Pluggable quality gate runner.

Downstream repos declare gates in .langywrap/ralph.yaml or justfile.
This module runs them uniformly and reports pass/fail with structured output.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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

    def __init__(self, project_dir: Path, gates: list[str | list[str]] | None = None) -> None:
        self.project_dir = Path(project_dir)
        self.gates = gates or ["lint", "typecheck", "pytest"]

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
    def from_justfile(cls, project_dir: Path) -> QualityRunner:
        """Auto-detect gates from justfile 'check' recipe."""
        justfile = Path(project_dir) / "justfile"
        if not justfile.exists():
            return cls(project_dir)

        # Default to ./just check which runs lint + typecheck + test
        return cls(project_dir, gates=["just-check"])
