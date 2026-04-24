"""
langywrap.router — ExecutionRouter: pure backend dispatcher.

Runs a prompt on a (model, engine) pair with retries, hang detection,
rate-limit backoff, and peak-hour throttling. Routing decisions — which
model, which engine, what timeout — live on the pipeline's ``Step`` objects
and are passed to ``execute()`` directly. There is no RouteConfig/RouteRule
indirection.

Public API
----------
ExecutionRouter   — backend dispatcher
Backend           — enum of backend types (CLAUDE, OPENCODE, OPENROUTER, …)
BackendConfig     — per-backend configuration (binary path, auth, timeouts)
SubagentResult    — result from a backend run() call
StepEvolver       — pipeline-variant evolution
PipelineVariant   — versioned pipeline with fitness score + mutation history

Example
-------
    from langywrap.router import ExecutionRouter, Backend, BackendConfig

    backends = {
        Backend.CLAUDE: BackendConfig(type=Backend.CLAUDE),
        Backend.OPENROUTER: BackendConfig(
            type=Backend.OPENROUTER,
            api_key_source="OPENROUTER_API_KEY",
        ),
    }
    router = ExecutionRouter(backends=backends)
    result = router.execute(
        prompt="...",
        model="claude-haiku-4-5-20251001",
        engine="claude",
        timeout_minutes=15,
        tag="orient",
    )
    print(result.text)
"""

from .backends import (
    Backend,
    BackendConfig,
    ClaudeBackend,
    DirectAPIBackend,
    MockBackend,
    OpenCodeBackend,
    OpenRouterBackend,
    SubagentResult,
    ThinkingLoopBackend,
    ThinkingLoopBackendConfig,
    create_backend,
)
from .evolution import PipelineVariant, StepEvolver
from .router import ExecutionRouter

__all__ = [
    # Core router
    "ExecutionRouter",
    # Backend models
    "Backend",
    "BackendConfig",
    "SubagentResult",
    # Backend classes (for advanced use)
    "ClaudeBackend",
    "OpenCodeBackend",
    "OpenRouterBackend",
    "DirectAPIBackend",
    "MockBackend",
    "ThinkingLoopBackend",
    "ThinkingLoopBackendConfig",
    "create_backend",
    # Evolution
    "StepEvolver",
    "PipelineVariant",
]
