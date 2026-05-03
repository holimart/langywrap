"""Tests for the (refactored) ExecutionRouter using MockBackend."""

from __future__ import annotations

import pytest
from langywrap.router.backends import (
    Backend,
    BackendConfig,
    SubagentResult,
)
from langywrap.router.router import (
    DryRunResult,
    ExecutionRouter,
    _classify_failed_result,
    _estimate_cost,
    _HeartbeatWatcher,
    _infer_backend_from_model,
    _ModelStats,
    _resolve_engine_backend,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_router() -> ExecutionRouter:
    """ExecutionRouter with only the MOCK backend wired up."""
    backends = {Backend.MOCK: BackendConfig(type=Backend.MOCK)}
    return ExecutionRouter(backends=backends, default_backend=Backend.MOCK)


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
# _resolve_engine_backend
# ---------------------------------------------------------------------------


def test_resolve_engine_auto_returns_none():
    assert _resolve_engine_backend("auto") is None
    assert _resolve_engine_backend("") is None
    assert _resolve_engine_backend(None) is None


def test_resolve_engine_explicit():
    assert _resolve_engine_backend("claude") == Backend.CLAUDE
    assert _resolve_engine_backend("opencode") == Backend.OPENCODE


def test_resolve_engine_unknown_warns_none():
    # Unknown engine returns None (caller infers from model) — and emits a warning.
    assert _resolve_engine_backend("not-a-real-engine") is None


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


def test_router_init_defaults():
    router = ExecutionRouter()
    assert router._backends == {}
    assert router._default_backend == Backend.CLAUDE


def test_router_init_peak_hours():
    router = ExecutionRouter(peak_hours=(9, 17))
    assert router._peak_hours == (9, 17)


# ---------------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------------


def test_execute_success():
    router = make_router()
    result = router.execute(prompt="hello", model="mock-model", engine="auto", tag="orient")
    assert result.ok
    assert "hello" in result.text


def test_execute_accumulates_stats():
    router = make_router()
    router.execute(prompt="test prompt", model="mock-model", engine="auto", tag="orient")
    stats = router.get_stats()
    assert stats["budget_usd"] >= 0.0
    assert len(stats) > 1  # budget_usd + at least one model


def test_execute_tools_string():
    router = make_router()
    result = router.execute(
        prompt="do it", model="mock-model", engine="auto", tools="Bash,Read", tag="execute"
    )
    assert result.ok


def test_execute_tools_list():
    router = make_router()
    result = router.execute(
        prompt="do it", model="mock-model", engine="auto", tools=["Bash", "Read"], tag="execute"
    )
    assert result.ok


def test_execute_timeout_override():
    router = make_router()
    result = router.execute(
        prompt="x", model="mock-model", engine="auto", timeout_minutes=5, tag="orient"
    )
    assert result.ok


def test_execute_missing_backend_raises():
    """If the engine maps to a backend we did not configure, execute raises."""
    router = ExecutionRouter()  # no backends at all
    with pytest.raises(RuntimeError):
        router.execute(prompt="x", model="claude-sonnet-4-6", engine="claude", tag="orient")


def test_execute_retry_models_chain():
    """After a non-hang failure, the next model in the retry chain is tried."""
    # We use the MOCK backend which replies "OK" to everything — so there's no
    # failure to trigger the chain. Sanity-check that retry_models is accepted
    # and the call returns cleanly.
    router = make_router()
    result = router.execute(
        prompt="x",
        model="mock-model",
        engine="auto",
        retry_models=["mock-fallback"],
        retry_max=2,
        tag="execute",
    )
    assert result.ok


# ---------------------------------------------------------------------------
# get_stats() and reset_stats()
# ---------------------------------------------------------------------------


def test_get_stats_empty():
    router = ExecutionRouter()
    stats = router.get_stats()
    assert stats["budget_usd"] == 0.0


def test_reset_stats():
    router = make_router()
    router.execute(prompt="x", model="mock-model", engine="auto", tag="orient")
    router.reset_stats()
    stats = router.get_stats()
    assert stats["budget_usd"] == 0.0
    assert len(stats) == 1  # only budget_usd key


# ---------------------------------------------------------------------------
# dry_run()
# ---------------------------------------------------------------------------


def test_dry_run_with_mock_backend():
    router = make_router()
    targets = [
        ("mock-model", "auto"),
        ("another-mock", "auto"),
    ]
    results = router.dry_run(targets)
    assert isinstance(results, list)
    assert all(isinstance(t, tuple) and len(t) == 3 for t in results)


def test_dry_run_detailed_no_backend_has_reason():
    router = ExecutionRouter()  # no backends configured
    results = router.dry_run_detailed([("claude-haiku-4-5-20251001", "claude")])
    assert results == [
        DryRunResult(
            model="claude-haiku-4-5-20251001",
            backend="claude",
            reachable=False,
            reason="backend_not_configured",
            detail="No backend configured for claude",
        )
    ]


def test_dry_run_detailed_detects_opencode_model_not_configured(tmp_path):
    shim = tmp_path / "opencode"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "models" ]]; then\n'
        "  printf '%s\\n' 'openai/gpt-5.5'\n"
        "  exit 0\n"
        "fi\n"
        "exit 99\n"
    )
    shim.chmod(0o755)

    router = ExecutionRouter(
        backends={Backend.OPENCODE: BackendConfig(type=Backend.OPENCODE, binary_path=str(shim))},
        default_backend=Backend.OPENCODE,
    )
    results = router.dry_run_detailed([("nvidia/moonshotai/kimi-k2.6", "opencode")])
    assert len(results) == 1
    assert results[0].reachable is False
    assert results[0].reason == "model_not_configured"
    assert "provider.nvidia.models.moonshotai/kimi-k2.6" in results[0].detail


def test_classify_failed_result_detects_opencode_model_not_found():
    result = SubagentResult(
        text='ProviderModelNotFoundError: data: { providerID: "nvidia" }',
        exit_code=1,
        duration_seconds=0.1,
        model_used="nvidia/moonshotai/kimi-k2.6",
        backend_used=Backend.OPENCODE,
    )
    reason, _ = _classify_failed_result(result)
    assert reason == "model_not_configured"


def test_classify_failed_result_detects_missing_key_auth():
    result = SubagentResult(
        text="Missing API key for NVIDIA",
        exit_code=1,
        duration_seconds=0.1,
        model_used="nvidia/moonshotai/kimi-k2.6",
        backend_used=Backend.OPENCODE,
    )
    reason, _ = _classify_failed_result(result)
    assert reason == "auth_failed"


def test_dry_run_no_backend_returns_false():
    router = ExecutionRouter()  # no backends configured
    results = router.dry_run([("claude-haiku-4-5-20251001", "claude")])
    assert all(reachable is False for _, _, reachable in results)


def test_dry_run_with_explicit_timeout():
    router = make_router()
    results = router.dry_run([("mock-model", "auto", 30)])
    assert len(results) == 1


# ---------------------------------------------------------------------------
# _HeartbeatWatcher
# ---------------------------------------------------------------------------


def test_heartbeat_watcher_context_manager():
    with _HeartbeatWatcher(step_name="test", interval=10000):
        pass


def test_heartbeat_watcher_stop():
    watcher = _HeartbeatWatcher(step_name="test", interval=10000)
    watcher.__enter__()
    watcher.__exit__(None, None, None)
    assert watcher._stop.is_set()
