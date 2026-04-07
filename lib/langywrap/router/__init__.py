"""
langywrap.router — ExecutionRouter: AI backend routing for Ralph-pattern loops.

Routes workflow steps (orient, plan, execute, critic, finalize, review, …) to
different AI backends (claude CLI, opencode CLI, OpenRouter API, direct API)
with configurable model selection per step role, retry/fallback chains,
peak-hour throttling, and HyperAgent-driven config evolution.

Public API
----------
ExecutionRouter   — central dispatch; routes steps and handles retries
RouteConfig       — routing configuration (rules, timeouts, backends)
RouteRule         — a single role→model→backend routing rule
StepRole          — enum of step roles (orient, plan, execute, …)
Backend           — enum of backend types (CLAUDE, OPENCODE, OPENROUTER, …)
BackendConfig     — per-backend configuration (binary path, auth, timeouts)
SubagentResult    — result from a backend run() call
ModelTier         — cost tier enum (CHEAP, MID, EXPENSIVE)
RouteEvolver      — HyperAgent-driven RouteConfig evolution
RouteConfigVariant— versioned config with fitness score and mutation history

Utility functions
-----------------
load_route_config(project_dir)  — load from .langywrap/router.yaml
save_route_config(config, dir)  — persist config to .langywrap/router.yaml
DEFAULT_ROUTE_CONFIG            — built-in default (crunchdaoobesity pattern)

Example
-------
    from pathlib import Path
    from langywrap.router import (
        ExecutionRouter, Backend, BackendConfig, StepRole,
        load_route_config,
    )

    config = load_route_config(Path("/my/project"))
    backends = {
        Backend.CLAUDE: BackendConfig(type=Backend.CLAUDE),
        Backend.OPENROUTER: BackendConfig(
            type=Backend.OPENROUTER,
            api_key_source="OPENROUTER_API_KEY",
        ),
    }
    router = ExecutionRouter(config, backends)
    result = router.execute(StepRole.ORIENT, prompt, context={"cycle_number": 1})
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
    create_backend,
)
from .config import (
    DEFAULT_ROUTE_CONFIG,
    ModelTier,
    RouteConfig,
    RouteRule,
    StepRole,
    load_route_config,
    save_route_config,
)
from .evolution import RouteConfigVariant, RouteEvolver
from .router import ExecutionRouter

__all__ = [
    # Core router
    "ExecutionRouter",
    # Config models
    "RouteConfig",
    "RouteRule",
    "StepRole",
    "ModelTier",
    "DEFAULT_ROUTE_CONFIG",
    "load_route_config",
    "save_route_config",
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
    "create_backend",
    # Evolution
    "RouteEvolver",
    "RouteConfigVariant",
]
