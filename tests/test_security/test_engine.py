"""Tests for SecurityEngine."""

from __future__ import annotations

from pathlib import Path

import pytest

from langywrap.security.engine import PermissionDecision, SecurityEngine, SecurityResult
from langywrap.security.permissions import PermissionRule, PermissionsConfig


class TestSecurityEngine:
    def test_deny_rm_rf(self, tmp_path: Path) -> None:
        engine = SecurityEngine(project_dir=tmp_path, system_dir=tmp_path / "system")
        result = engine.check("rm -rf /")
        assert result.decision == PermissionDecision.DENY

    def test_allow_safe_commands(self, tmp_path: Path) -> None:
        engine = SecurityEngine(project_dir=tmp_path, system_dir=tmp_path / "system")
        result = engine.check("ls -la")
        assert result.decision == PermissionDecision.ALLOW

    def test_deny_sudo(self, tmp_path: Path) -> None:
        engine = SecurityEngine(project_dir=tmp_path, system_dir=tmp_path / "system")
        result = engine.check("sudo apt install foo")
        assert result.decision == PermissionDecision.DENY

    def test_force_push_not_allowed(self, tmp_path: Path) -> None:
        engine = SecurityEngine(project_dir=tmp_path, system_dir=tmp_path / "system")
        result = engine.check("git push --force origin main")
        # Force push should be at least ASK (not freely allowed)
        assert result.decision in (PermissionDecision.DENY, PermissionDecision.ASK)
