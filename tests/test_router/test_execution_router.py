"""Tests for ExecutionRouter using MockBackend to avoid real AI calls."""

from __future__ import annotations

import pytest
from langywrap.router.backends import (
    Backend,
    BackendConfig,
    SubagentResult,
)
from langywrap.router.config import DEFAULT_ROUTE_CONFIG, StepRole
from langywrap.router.router import (
    ExecutionRouter,
    _estimate_cost,
    _HeartbeatWatcher,
    _infer_backend_from_model,
    _ModelStats,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_router(mock_text: str = "OK", exit_code: int = 0) -> ExecutionRouter:
    """Create an ExecutionRouter with a MockBackend that returns mock_text."""
    from langywrap.router.config import ModelTier, RouteConfig, RouteRule

    backends = {Backend.MOCK: BackendConfig(type=Backend.MOCK)}
    # Build a config that uses "mock-model" (non-claude) so backend stays MOCK
    rules = []
    for role in StepRole:
        rules.append(RouteRule(
            role=role,
            model="mock-model",
            backend=Backend.MOCK,
            retry_models=[],
            retry_max=0,
            tier=ModelTier.CHEAP,
        ))
    config = RouteConfig(rules=rules, name="test", default_backend=Backend.MOCK)
    router = ExecutionRouter(config=config, backends=backends)
    return router


# ---------------------------------------------------------------------------
# _infer_backend_from_model
# ---------------------------------------------------------------------------


def test_infer_backend_claude_model():
    assert _infer_backend_from_model("claude-sonnet-4-6") == Backend.CLAUDE


def test_infer_backend_other_model():
    assert _infer_backend_from_model("gpt-4o") == Backend.OPENCODE


def test_infer_backend_kimi():
    assert _infer_backend_from_model("kimi-k2") == Backend.OPENCODE


# ---------------------------------------------------------------------------
# _estimate_cost
# ---------------------------------------------------------------------------


def test_estimate_cost_haiku():
    cost = _estimate_cost("claude-haiku-4-5-20251001", 1000)
    assert cost == pytest.approx(0.00025)


def test_estimate_cost_unknown():
    cost = _estimate_cost("totally-unknown-model", 1000)
    assert cost == pytest.approx(0.001)


def test_estimate_cost_zero_tokens():
    cost = _estimate_cost("kimi-k2", 0)
    assert cost == 0.0


# ---------------------------------------------------------------------------
# _ModelStats
# ---------------------------------------------------------------------------


def test_model_stats_record_ok():
    stats = _ModelStats()
    result = SubagentResult(
        text="ok output",
        exit_code=0,
        duration_seconds=1.5,
        model_used="mock",
        backend_used=Backend.MOCK,
    )
    stats.record(result)
    assert stats.calls == 1
    assert stats.failures == 0
    assert stats.total_seconds == pytest.approx(1.5)


def test_model_stats_record_failure():
    stats = _ModelStats()
    result = SubagentResult(
        text="",
        exit_code=1,
        duration_seconds=0.5,
        model_used="mock",
        backend_used=Backend.MOCK,
    )
    stats.record(result)
    assert stats.failures == 1


def test_model_stats_record_timeout():
    stats = _ModelStats()
    result = SubagentResult(
        text="",
        exit_code=124,
        duration_seconds=300.0,
        model_used="mock",
        backend_used=Backend.MOCK,
    )
    stats.record(result)
    assert stats.timeouts == 1


# ---------------------------------------------------------------------------
# ExecutionRouter init
# ---------------------------------------------------------------------------


def test_router_init_default_config():
    router = ExecutionRouter()
    assert router._config is not None


def test_router_init_no_backends():
    router = ExecutionRouter()
    assert router._backends == {}


# ---------------------------------------------------------------------------
# route()
# ---------------------------------------------------------------------------


def test_route_returns_rule_for_orient():
    router = ExecutionRouter()
    rule = router.route(StepRole.ORIENT)
    assert rule.role == StepRole.ORIENT


def test_route_unknown_role_raises():
    # Use a config with no rules
    from langywrap.router.config import RouteConfig
    empty_config = RouteConfig(rules=[], name="empty")
    router = ExecutionRouter(config=empty_config)
    with pytest.raises(LookupError):
        router.route(StepRole.ORIENT)


def test_route_review_promotion():
    """cycle_number multiple of review_every_n promotes EXECUTE → REVIEW."""
    router = ExecutionRouter()
    review_every = router._config.review_every_n
    rule = router.route(StepRole.EXECUTE, context={"cycle_number": review_every})
    assert rule.role == StepRole.REVIEW


def test_route_no_promotion_wrong_cycle():
    router = ExecutionRouter()
    review_every = router._config.review_every_n
    rule = router.route(StepRole.EXECUTE, context={"cycle_number": review_every + 1})
    assert rule.role == StepRole.EXECUTE


# ---------------------------------------------------------------------------
# execute() with MockBackend
# ---------------------------------------------------------------------------


def test_execute_success():
    router = make_router()
    result = router.execute(StepRole.ORIENT, prompt="hello")
    assert result.ok
    assert "hello" in result.text


def test_execute_accumulates_stats():
    router = make_router()
    router.execute(StepRole.ORIENT, prompt="test prompt")
    stats = router.get_stats()
    # Mock backend uses "mock-model"
    assert stats["budget_usd"] >= 0.0
    # At least one model in stats
    assert len(stats) > 1  # budget_usd + at least one model


def test_execute_tools_string():
    router = make_router()
    result = router.execute(StepRole.EXECUTE, prompt="do it", tools="Bash,Read")
    assert result.ok


def test_execute_tools_list():
    router = make_router()
    result = router.execute(StepRole.EXECUTE, prompt="do it", tools=["Bash", "Read"])
    assert result.ok


def test_execute_timeout_override():
    router = make_router()
    result = router.execute(StepRole.ORIENT, prompt="x", timeout_minutes=5)
    assert result.ok


def test_execute_model_override():
    router = make_router()
    # Override model — note: mock backend ignores model name
    result = router.execute(StepRole.ORIENT, prompt="x", model="mock-override")
    assert result.ok


def test_execute_engine_override_claude():
    import contextlib
    router = make_router()
    # claude engine redirects to CLAUDE backend — not configured, expect RuntimeError
    with contextlib.suppress(RuntimeError):
        router.execute(StepRole.ORIENT, prompt="x", engine="claude")


# ---------------------------------------------------------------------------
# get_stats() and reset_stats()
# ---------------------------------------------------------------------------


def test_get_stats_empty():
    router = ExecutionRouter()
    stats = router.get_stats()
    assert stats["budget_usd"] == 0.0


def test_reset_stats():
    router = make_router()
    router.execute(StepRole.ORIENT, prompt="x")
    router.reset_stats()
    stats = router.get_stats()
    assert stats["budget_usd"] == 0.0
    assert len(stats) == 1  # only budget_usd key


# ---------------------------------------------------------------------------
# dry_run()
# ---------------------------------------------------------------------------


def test_dry_run_with_mock_backend():
    backends = {Backend.MOCK: BackendConfig(type=Backend.MOCK)}
    config = DEFAULT_ROUTE_CONFIG.model_copy(deep=True)
    for rule in config.rules:
        rule.backend = Backend.MOCK
        rule.retry_models = []

    router = ExecutionRouter(config=config, backends=backends)
    results = router.dry_run()
    assert isinstance(results, list)
    assert all(isinstance(t, tuple) and len(t) == 3 for t in results)


def test_dry_run_no_backend_returns_false():
    router = ExecutionRouter()  # no backends configured
    results = router.dry_run()
    assert all(reachable is False for _, _, reachable in results)


# ---------------------------------------------------------------------------
# _HeartbeatWatcher
# ---------------------------------------------------------------------------


def test_heartbeat_watcher_context_manager():
    # Should not raise
    with _HeartbeatWatcher(step_name="test", interval=10000):
        pass  # enters and exits immediately


def test_heartbeat_watcher_stop():
    watcher = _HeartbeatWatcher(step_name="test", interval=10000)
    watcher.__enter__()
    watcher.__exit__(None, None, None)
    # Thread should be stopped
    assert watcher._stop.is_set()
