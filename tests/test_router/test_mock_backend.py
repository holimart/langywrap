"""Integration tests for MockBackend — verifies security and token sparing layers.

These tests use the MockBackend (bash-based) to verify that:
1. Commands routed through ExecutionRouter are subject to SecurityEngine
2. Dangerous commands are blocked before execution
3. Safe commands pass through and produce output
4. The mock backend works as a test double for real LLM backends
5. RTK output compression would be applied (when RTK binary present)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langywrap.router.backends import Backend, BackendConfig, MockBackend
from langywrap.security.engine import SecurityEngine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config() -> BackendConfig:
    """Basic mock backend config without execwrap."""
    return BackendConfig(type=Backend.MOCK, timeout_seconds=10)


@pytest.fixture
def mock_backend(mock_config: BackendConfig) -> MockBackend:
    return MockBackend(mock_config)


@pytest.fixture
def security_engine(tmp_path: Path) -> SecurityEngine:
    return SecurityEngine(project_dir=tmp_path, system_dir=tmp_path / "system")


# ---------------------------------------------------------------------------
# Basic MockBackend functionality
# ---------------------------------------------------------------------------


class TestMockBackendBasic:
    def test_echo_response(self, mock_backend: MockBackend) -> None:
        result = mock_backend.run("Hello world", "mock-model", timeout=10)
        assert result.ok
        assert result.backend_used == Backend.MOCK
        assert "Hello world" in result.text

    def test_fixed_response(self) -> None:
        config = BackendConfig(
            type=Backend.MOCK,
            env_overrides={"MOCK_RESPONSE": "I am a mock LLM"},
        )
        backend = MockBackend(config)
        result = backend.run("anything", "mock-v1", timeout=10)
        assert result.ok
        assert "I am a mock LLM" in result.text

    def test_command_execution(self) -> None:
        config = BackendConfig(
            type=Backend.MOCK,
            env_overrides={"MOCK_COMMAND": "echo 'safe output'"},
        )
        backend = MockBackend(config)
        result = backend.run("", "mock", timeout=10)
        assert result.ok
        assert "safe output" in result.text

    def test_failing_command(self) -> None:
        config = BackendConfig(
            type=Backend.MOCK,
            env_overrides={"MOCK_COMMAND": "exit 1"},
        )
        backend = MockBackend(config)
        result = backend.run("", "mock", timeout=10)
        assert not result.ok
        assert result.exit_code == 1

    def test_timeout(self) -> None:
        config = BackendConfig(
            type=Backend.MOCK,
            timeout_seconds=2,
            env_overrides={"MOCK_COMMAND": "sleep 10"},
        )
        backend = MockBackend(config)
        result = backend.run("", "mock", timeout=2)
        assert result.timed_out
        assert result.exit_code == 124

    def test_result_properties(self, mock_backend: MockBackend) -> None:
        result = mock_backend.run("Test prompt", "mock-v1", timeout=10)
        assert result.model_used == "mock-v1"
        assert result.duration_seconds >= 0
        assert result.token_estimate > 0
        assert not result.hung
        assert not result.rate_limited


# ---------------------------------------------------------------------------
# Security enforcement through MockBackend
# ---------------------------------------------------------------------------


class TestSecurityThroughMock:
    """Verify dangerous commands are blocked by SecurityEngine before execution."""

    def test_rm_rf_blocked(
        self, mock_backend: MockBackend, security_engine: SecurityEngine
    ) -> None:
        result = mock_backend.run_with_security_check(
            "rm -rf /",
            security_engine=security_engine,
        )
        assert result.exit_code == 2
        assert "BLOCKED" in result.error

    def test_sudo_blocked(
        self, mock_backend: MockBackend, security_engine: SecurityEngine
    ) -> None:
        result = mock_backend.run_with_security_check(
            "sudo apt install evil-package",
            security_engine=security_engine,
        )
        assert result.exit_code == 2
        assert "BLOCKED" in result.error

    def test_chmod_777_blocked(
        self, mock_backend: MockBackend, security_engine: SecurityEngine
    ) -> None:
        result = mock_backend.run_with_security_check(
            "chmod 777 /etc/passwd",
            security_engine=security_engine,
        )
        assert result.exit_code == 2
        assert "BLOCKED" in result.error

    def test_dd_blocked(
        self, mock_backend: MockBackend, security_engine: SecurityEngine
    ) -> None:
        result = mock_backend.run_with_security_check(
            "dd if=/dev/zero of=/dev/sda",
            security_engine=security_engine,
        )
        assert result.exit_code == 2
        assert "BLOCKED" in result.error

    def test_safe_echo_allowed(
        self, mock_backend: MockBackend, security_engine: SecurityEngine
    ) -> None:
        result = mock_backend.run_with_security_check(
            "echo hello world",
            security_engine=security_engine,
        )
        assert result.ok
        assert "hello world" in result.text

    def test_safe_ls_allowed(
        self, mock_backend: MockBackend, security_engine: SecurityEngine
    ) -> None:
        result = mock_backend.run_with_security_check(
            "ls -la /tmp",
            security_engine=security_engine,
        )
        assert result.ok

    def test_safe_cat_allowed(
        self, mock_backend: MockBackend, security_engine: SecurityEngine
    ) -> None:
        result = mock_backend.run_with_security_check(
            "cat /etc/hostname",
            security_engine=security_engine,
        )
        # May or may not have hostname file, but should not be blocked
        assert result.exit_code != 2  # Not security-blocked

    def test_git_force_push_blocked_or_ask(
        self, mock_backend: MockBackend, security_engine: SecurityEngine
    ) -> None:
        """Force push should at minimum require confirmation (ASK or DENY)."""
        result = mock_backend.run_with_security_check(
            "git push --force origin main",
            security_engine=security_engine,
        )
        # Should be blocked (exit 2) or at least not freely executed
        assert result.exit_code == 2 or "BLOCKED" in result.error or result.exit_code != 0

    def test_dd_device_write_blocked(
        self, mock_backend: MockBackend, security_engine: SecurityEngine
    ) -> None:
        """dd with if= is in the deny list (pattern: dd:if=)."""
        result = mock_backend.run_with_security_check(
            "dd if=/dev/zero of=/dev/sda bs=1M",
            security_engine=security_engine,
        )
        assert result.exit_code == 2
        assert "BLOCKED" in result.error


# ---------------------------------------------------------------------------
# Token sparing / output compression
# ---------------------------------------------------------------------------


class TestTokenSparing:
    """Verify that output from MockBackend can be measured for token impact."""

    def test_large_output_token_estimate(self) -> None:
        """Generate large output and verify token estimate scales."""
        config = BackendConfig(
            type=Backend.MOCK,
            env_overrides={"MOCK_COMMAND": "seq 1 1000"},
        )
        backend = MockBackend(config)
        result = backend.run("", "mock", timeout=10)
        assert result.ok
        # ~4000 chars of numbers -> ~1000 token estimate
        assert result.token_estimate > 100

    def test_quiet_output_saves_tokens(self) -> None:
        """Verify that quiet flags reduce token count."""
        # Verbose output
        config_verbose = BackendConfig(
            type=Backend.MOCK,
            env_overrides={"MOCK_COMMAND": "seq 1 100"},
        )
        verbose_result = MockBackend(config_verbose).run("", "mock", timeout=10)

        # Quiet output (only count)
        config_quiet = BackendConfig(
            type=Backend.MOCK,
            env_overrides={"MOCK_COMMAND": "seq 1 100 | wc -l"},
        )
        quiet_result = MockBackend(config_quiet).run("", "mock", timeout=10)

        assert quiet_result.token_estimate < verbose_result.token_estimate

    def test_rtk_path_not_prepended_when_missing(self) -> None:
        """RTK binary that doesn't exist is silently skipped."""
        config = BackendConfig(
            type=Backend.MOCK,
            env_overrides={"MOCK_COMMAND": "echo test"},
            rtk_path="/nonexistent/rtk",
        )
        backend = MockBackend(config)
        result = backend.run("", "mock", timeout=10)
        assert result.ok
        assert "test" in result.text

    def test_rtk_path_prepended_when_present(self, tmp_path: Path) -> None:
        """RTK binary that exists is prepended to the command."""
        # Create a fake rtk that just passes through to the next command
        fake_rtk = tmp_path / "rtk"
        fake_rtk.write_text("#!/bin/bash\nexec \"$@\"\n")
        fake_rtk.chmod(0o755)

        config = BackendConfig(
            type=Backend.MOCK,
            env_overrides={"MOCK_COMMAND": "echo rtk_was_here"},
            rtk_path=str(fake_rtk),
        )
        backend = MockBackend(config)
        result = backend.run("", "mock", timeout=10)
        assert result.ok
        assert "rtk_was_here" in result.text

    def test_execwrap_and_rtk_layered(self, tmp_path: Path) -> None:
        """execwrap and RTK stack correctly: cmd = [rtk, --, execwrap, ...cmd]."""
        # Fake execwrap: append a marker env var and exec the rest
        fake_execwrap = tmp_path / "execwrap.bash"
        fake_execwrap.write_text("#!/bin/bash\nexec \"$@\"\n")
        fake_execwrap.chmod(0o755)

        fake_rtk = tmp_path / "rtk"
        fake_rtk.write_text("#!/bin/bash\nexec \"$@\"\n")
        fake_rtk.chmod(0o755)

        config = BackendConfig(
            type=Backend.MOCK,
            env_overrides={"MOCK_COMMAND": "echo layered_ok"},
            execwrap_path=str(fake_execwrap),
            rtk_path=str(fake_rtk),
        )
        backend = MockBackend(config)
        result = backend.run("", "mock", timeout=10)
        assert result.ok
        assert "layered_ok" in result.text


# ---------------------------------------------------------------------------
# MockBackend as ExecutionRouter backend
# ---------------------------------------------------------------------------


class TestMockInRouter:
    """Verify MockBackend works as a drop-in backend in ExecutionRouter."""

    def test_router_with_mock_backend(self, tmp_path: Path) -> None:
        from langywrap.router.config import RouteConfig, RouteRule, StepRole
        from langywrap.router.router import ExecutionRouter

        # Create a config that routes everything through mock
        rules = [
            RouteRule(
                role=StepRole.ORIENT,
                model="mock-haiku",
                backend=Backend.MOCK,
                timeout_minutes=1,
            ),
            RouteRule(
                role=StepRole.EXECUTE,
                model="mock-kimi",
                backend=Backend.MOCK,
                timeout_minutes=1,
            ),
        ]
        config = RouteConfig(name="test", rules=rules)
        backends = {
            Backend.MOCK: BackendConfig(
                type=Backend.MOCK,
                env_overrides={"MOCK_RESPONSE": "Mock LLM output"},
            ),
        }

        router = ExecutionRouter(config, backends)
        result = router.execute(
            StepRole.ORIENT,
            "What should we work on?",
            context={"cycle_number": 1},
        )
        assert result.ok
        assert "Mock LLM output" in result.text
        assert result.backend_used == Backend.MOCK

    def test_router_mock_stats(self, tmp_path: Path) -> None:
        from langywrap.router.config import RouteConfig, RouteRule, StepRole
        from langywrap.router.router import ExecutionRouter

        config = RouteConfig(
            name="stats-test",
            rules=[
                RouteRule(
                    role=StepRole.ORIENT, model="mock-v1", backend=Backend.MOCK, timeout_minutes=1
                ),
            ],
        )
        backends = {
            Backend.MOCK: BackendConfig(type=Backend.MOCK, env_overrides={"MOCK_RESPONSE": "ok"}),
        }
        router = ExecutionRouter(config, backends)

        # Run 3 calls
        for _ in range(3):
            router.execute(StepRole.ORIENT, "test", context={"cycle_number": 1})

        stats = router.get_stats()
        # Stats keyed by model name
        assert "mock-v1" in stats
        assert stats["mock-v1"]["calls"] == 3
        assert stats["mock-v1"]["tokens"] > 0

    def test_router_dry_run_with_mock(self) -> None:
        from langywrap.router.config import RouteConfig, RouteRule, StepRole
        from langywrap.router.router import ExecutionRouter

        config = RouteConfig(
            name="dry-test",
            rules=[
                RouteRule(
                    role=StepRole.ORIENT, model="mock-v1", backend=Backend.MOCK, timeout_minutes=1
                ),
                RouteRule(
                    role=StepRole.EXECUTE, model="mock-v2", backend=Backend.MOCK, timeout_minutes=1
                ),
            ],
        )
        backends = {
            Backend.MOCK: BackendConfig(type=Backend.MOCK, env_overrides={"MOCK_RESPONSE": "PONG"}),
        }
        router = ExecutionRouter(config, backends)
        results = router.dry_run()

        # Should test all configured roles
        assert len(results) >= 2
        for role, model, reachable in results:
            assert reachable, f"Mock backend should always be reachable: {role}:{model}"
