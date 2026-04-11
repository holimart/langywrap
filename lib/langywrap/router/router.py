"""
langywrap.router.router — ExecutionRouter: the central dispatch layer.

ExecutionRouter selects the right backend+model for each workflow step,
handles retries with model fallback, detects API hangs and rate limits,
enforces peak-hour throttling, and accumulates per-model stats.

Usage::

    from langywrap.router import ExecutionRouter, RouteConfig
    from langywrap.router.backends import Backend, BackendConfig
    from langywrap.router.config import load_route_config, StepRole

    config = load_route_config(Path("/path/to/project"))
    backends = {
        Backend.CLAUDE: BackendConfig(type=Backend.CLAUDE),
        Backend.OPENROUTER: BackendConfig(
            type=Backend.OPENROUTER,
            api_key_source="OPENROUTER_API_KEY",
        ),
    }
    router = ExecutionRouter(config, backends)
    result = router.execute(StepRole.ORIENT, prompt, context={"cycle_number": 3})
"""

from __future__ import annotations

import datetime
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from .backends import (
    Backend,
    BackendConfig,
    SubagentResult,
    create_backend,
)
from .config import (
    DEFAULT_ROUTE_CONFIG,
    RouteConfig,
    RouteRule,
    StepRole,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Backend inference from model name
# ---------------------------------------------------------------------------


def _infer_backend_from_model(model: str) -> Backend:
    """Infer the correct backend from a model identifier.

    Claude Code (Backend.CLAUDE) is reserved for Anthropic models only.
    Everything else defaults to opencode — including OpenRouter, NVIDIA NIM,
    OpenAI, Mistral, and any other provider prefix.
    """
    if model.startswith("claude-"):
        return Backend.CLAUDE
    return Backend.OPENCODE


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum output bytes to NOT consider a timeout as an API hang.
_HANG_OUTPUT_THRESHOLD = 2048

# Default backoff when a rate limit is detected (seconds).
_RATE_LIMIT_BACKOFF_SECONDS = 600  # 10 minutes

# Hang backoff: exponential sequence (seconds).  On hang, the router retries
# the same model indefinitely (hang #1=30s, #2=60s, …, capped at 300s).
# Hangs do NOT count against max_attempts and do NOT advance the model chain.
_HANG_BACKOFF_BASE = 30  # first wait
_HANG_BACKOFF_MAX = 300  # cap per wait

# Heartbeat interval (seconds) — logs a progress line while waiting.
_HEARTBEAT_INTERVAL = 60

# Rough USD cost per 1K tokens (very approximate, for budget tracking only)
_COST_PER_1K_TOKENS: Dict[str, float] = {
    # Claude family (input+output blended)
    "claude-haiku": 0.00025,
    "claude-sonnet": 0.003,
    "claude-opus": 0.015,
    # Free / open-source via OpenRouter
    "kimi": 0.0,
    "mistral-nemo": 0.0,
    "minimax": 0.0,
    "llama": 0.0,
    # GPT family
    "gpt-4o-mini": 0.00015,
    "gpt-4o": 0.005,
    "o1": 0.015,
}


def _estimate_cost(model: str, tokens: int) -> float:
    """Rough USD cost estimate for ``tokens`` tokens from ``model``."""
    model_lower = model.lower()
    for prefix, rate in _COST_PER_1K_TOKENS.items():
        if prefix in model_lower:
            return rate * tokens / 1000
    return 0.001 * tokens / 1000  # unknown model: assume $0.001/1K


# ---------------------------------------------------------------------------
# Per-model stats accumulator
# ---------------------------------------------------------------------------


@dataclass
class _ModelStats:
    calls: int = 0
    tokens: int = 0
    failures: int = 0
    timeouts: int = 0
    rate_limits: int = 0
    total_seconds: float = 0.0
    total_cost_usd: float = 0.0

    def record(self, result: SubagentResult) -> None:
        self.calls += 1
        self.tokens += result.token_estimate
        self.total_seconds += result.duration_seconds
        self.total_cost_usd += _estimate_cost(result.model_used, result.token_estimate)
        if not result.ok:
            self.failures += 1
        if result.timed_out:
            self.timeouts += 1
        if result.rate_limited:
            self.rate_limits += 1


# ---------------------------------------------------------------------------
# Heartbeat watcher
# ---------------------------------------------------------------------------


class _HeartbeatWatcher:
    """
    Logs a progress line every ``interval`` seconds while a subprocess runs.

    This mirrors the bash ``heartbeat`` pattern used in ralph_loop.sh — it
    keeps the terminal alive during long API calls so the operator knows the
    process hasn't stalled.

    Usage::

        with _HeartbeatWatcher(step_name="execute", interval=60):
            result = backend.run(...)
    """

    def __init__(self, step_name: str, interval: int = _HEARTBEAT_INTERVAL) -> None:
        self._step_name = step_name
        self._interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "_HeartbeatWatcher":
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _beat(self) -> None:
        elapsed = 0
        while not self._stop.wait(self._interval):
            elapsed += self._interval
            logger.info("[%s] still running… %ds elapsed", self._step_name, elapsed)


# ---------------------------------------------------------------------------
# ExecutionRouter
# ---------------------------------------------------------------------------


class ExecutionRouter:
    """
    Routes workflow steps to the correct backend/model and handles retries.

    Parameters
    ----------
    config:
        Routing configuration (rules, timeouts, review cadence).
    backends:
        Map of ``Backend`` → ``BackendConfig``.  Only backends listed here
        can be used; routes pointing to unlisted backends are skipped.
    rate_limit_backoff_seconds:
        How long to wait after a rate-limit response.  Default 600s.
    """

    def __init__(
        self,
        config: Optional[RouteConfig] = None,
        backends: Optional[Dict[Backend, BackendConfig]] = None,
        rate_limit_backoff_seconds: int = _RATE_LIMIT_BACKOFF_SECONDS,
    ) -> None:
        self._config = config or DEFAULT_ROUTE_CONFIG
        self._backends: Dict[Backend, BackendConfig] = backends or {}
        self._rate_limit_backoff = rate_limit_backoff_seconds
        self._stats: Dict[str, _ModelStats] = defaultdict(_ModelStats)
        self._budget_usd: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(self, role: StepRole, context: Optional[Dict[str, Any]] = None) -> RouteRule:
        """
        Select the best RouteRule for ``role`` given the current ``context``.

        Context keys recognised:
          ``cycle_number`` (int)  — current cycle; triggers review step every N cycles
          ``cycle_type``   (str)  — e.g. "lean"; matched against rule conditions
          ``last_result``  (SubagentResult | None) — previous step output

        Returns the matched RouteRule.  Raises ``LookupError`` when no rule is
        configured for ``role`` and there is no default.
        """
        ctx = context or {}

        # Automatic review promotion: if cycle_number is a multiple of review_every_n,
        # and the role is EXECUTE, promote to REVIEW.
        cycle_number = ctx.get("cycle_number")
        if (
            role == StepRole.EXECUTE
            and isinstance(cycle_number, int)
            and cycle_number > 0
            and cycle_number % self._config.review_every_n == 0
        ):
            review_rule = self._config.get_rule(StepRole.REVIEW, ctx)
            if review_rule:
                logger.info(
                    "Cycle %d: promoting execute→review (every %d cycles)",
                    cycle_number,
                    self._config.review_every_n,
                )
                return review_rule

        rule = self._config.get_rule(role, ctx)
        if rule is None:
            raise LookupError(
                f"No route rule configured for role={role.value!r}. "
                f"Add a rule to the RouteConfig or use DEFAULT_ROUTE_CONFIG."
            )
        return rule

    def execute(
        self,
        role: StepRole,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        timeout_minutes: Optional[int] = None,
        model: Optional[str] = None,
        tools: Optional[Union[str, List[str]]] = None,
        engine: Optional[str] = None,
        abort_on_hang: bool = False,
    ) -> SubagentResult:
        """
        Route ``role`` and run ``prompt`` against the selected backend+model.

        Handles:
          - Retry with fallback models on hang (exit 124, <2KB output)
          - Rate limit detection with configurable backoff
          - Peak-hour throttling (pause and resume)
          - Per-model stats accumulation

        Optional overrides from ralph step config:
          - timeout_minutes: override the route rule's timeout
          - model: override the route rule's model selection
          - tools: tool list hint (passed to backend if supported)
          - engine: engine hint (passed to backend if supported)
          - abort_on_hang: if True, return immediately on first hang (no retries,
            no backoff). Use for fail_fast steps to avoid waiting hours.

        Returns the first successful SubagentResult, or the last failure result
        if all retries are exhausted.
        """
        ctx = context or {}
        self._wait_for_off_peak()

        rule = self.route(role, ctx)

        # Apply caller overrides
        if timeout_minutes is not None:
            rule = rule.model_copy(update={"timeout_minutes": timeout_minutes})
        if model is not None:
            rule = rule.model_copy(update={"model": model})
        if engine and engine != "auto":
            engine_map = {
                "claude": Backend.CLAUDE,
                "opencode": Backend.OPENCODE,
                "openrouter": Backend.OPENROUTER,
                "direct_api": Backend.DIRECT_API,
            }
            if engine in engine_map:
                rule = rule.model_copy(update={"backend": engine_map[engine]})
            else:
                logger.warning("Unknown engine %r, ignoring override", engine)

        model_chain = [rule.model] + list(rule.retry_models)
        max_attempts = rule.retry_max + 1  # first attempt + retries

        last_result: Optional[SubagentResult] = None
        attempt = 0  # total attempts (across all models)
        model_idx = 0  # position in model_chain
        hang_streak = 0  # consecutive hangs on current model

        while attempt < max_attempts:
            model = model_chain[min(model_idx, len(model_chain) - 1)]

            # Re-infer backend per model in the chain (retry models may
            # need a different backend than the primary model).
            model_backend = _infer_backend_from_model(model)
            backend_cfg = self._backends.get(model_backend)
            if backend_cfg is None:
                # Fall back to rule's backend, then default
                backend_cfg = self._backends.get(rule.backend)
            if backend_cfg is None:
                backend_cfg = self._backends.get(self._config.default_backend)
            if backend_cfg is None:
                raise RuntimeError(
                    f"No backend configured for {model_backend.value!r}. "
                    f"Pass a backends dict to ExecutionRouter.__init__."
                )

            backend = create_backend(backend_cfg)
            logger.info(
                "[%s] attempt %d/%d — model=%s backend=%s",
                role.value, attempt + 1, max_attempts, model, model_backend.value,
            )

            # Parse tools from comma-separated string if needed
            tool_list = None
            if tools:
                if isinstance(tools, str):
                    tool_list = [t.strip() for t in tools.split(",") if t.strip()]
                else:
                    tool_list = list(tools)

            with _HeartbeatWatcher(step_name=f"{role.value}[{model}]"):
                result = backend.run(
                    prompt=prompt,
                    model=model,
                    timeout=rule.timeout_seconds,
                    tools=tool_list,
                )

            with self._lock:
                self._stats[model].record(result)
                self._budget_usd += _estimate_cost(model, result.token_estimate)

            last_result = result

            # Check rate limit BEFORE ok — a model can return exit_code=0 while
            # the response body contains "You've hit your limit" (NVIDIA/Kimi).
            if result.rate_limited:
                logger.warning(
                    "[%s] Rate limited (detected in output). Waiting %ds…",
                    role.value, self._rate_limit_backoff,
                )
                time.sleep(self._rate_limit_backoff)
                attempt += 1
                continue

            if result.ok:
                logger.info(
                    "[%s] completed — model=%s tokens≈%d duration=%.1fs",
                    role.value, model, result.token_estimate, result.duration_seconds,
                )
                return result

            if result.hung:
                hang_kind = "idle-timeout" if result.idle_timeout else "no-output"
                if abort_on_hang:
                    logger.warning(
                        "[%s] API hang on %s (%s, %dB output). "
                        "abort_on_hang=True — returning failure immediately.",
                        role.value, model, hang_kind, len(result.raw_output),
                    )
                    return result
                # Default: retry indefinitely on same model — do NOT advance
                # model or increment attempt. Hangs are transient; only real
                # failures (non-hang exit codes) count against max_attempts.
                hang_streak += 1
                backoff = min(
                    _HANG_BACKOFF_BASE * (2 ** (hang_streak - 1)),
                    _HANG_BACKOFF_MAX,
                )
                logger.warning(
                    "[%s] API hang on %s (%s, %dB output). "
                    "Retrying same model after %ds backoff… (hang #%d)",
                    role.value, model, hang_kind,
                    len(result.raw_output), backoff, hang_streak,
                )
                time.sleep(backoff)
                continue

            # Non-hang failure — reset hang streak
            hang_streak = 0

            if result.rate_limited:
                logger.warning(
                    "[%s] Rate limited. Waiting %ds…",
                    role.value, self._rate_limit_backoff,
                )
                time.sleep(self._rate_limit_backoff)
                attempt += 1
                continue

            if result.timed_out:
                # Genuine timeout (had substantial output) — don't retry
                logger.warning(
                    "[%s] Genuine timeout (%dB output). Not retrying.",
                    role.value, len(result.raw_output),
                )
                break

            # Permanent failure (model not found / no access) — no point retrying
            combined = (result.error + " " + result.text).lower()
            if "may not exist" in combined or "you may not have access" in combined:
                logger.error(
                    "[%s] Permanent failure on %s — model unavailable. "
                    "Not retrying. (%s)",
                    role.value, model, result.error[:200],
                )
                break

            # Other failure
            logger.warning(
                "[%s] Failed (exit=%d): %s",
                role.value, result.exit_code, result.error[:200],
            )
            attempt += 1

        assert last_result is not None
        logger.error(
            "[%s] Exhausted all %d attempts. Last exit=%d.",
            role.value, attempt, last_result.exit_code,
        )
        return last_result

    def dry_run(self) -> List[Tuple[StepRole, str, bool]]:
        """
        Ping every configured model/backend combination.

        Returns a list of ``(role, model, reachable)`` tuples.
        Does not modify stats.
        """
        results: List[Tuple[StepRole, str, bool]] = []
        ping_prompt = "Reply with exactly: PONG"

        seen: set[Tuple[str, str]] = set()  # (model, backend)

        for rule in self._config.rules:
            key = (rule.model, rule.backend.value)
            if key in seen:
                continue
            seen.add(key)

            backend_cfg = self._backends.get(rule.backend)
            if backend_cfg is None:
                logger.warning("dry_run: no backend configured for %s", rule.backend.value)
                results.append((rule.role, rule.model, False))
                continue

            try:
                backend = create_backend(backend_cfg)
                result = backend.run(
                    prompt=ping_prompt,
                    model=rule.model,
                    timeout=min(60, rule.timeout_seconds),
                )
                reachable = result.ok and "PONG" in result.text.upper()
                logger.info(
                    "dry_run: %s/%s → %s (exit=%d, %dB)",
                    rule.backend.value, rule.model,
                    "OK" if reachable else "FAIL",
                    result.exit_code, len(result.raw_output),
                )
                results.append((rule.role, rule.model, reachable))
            except Exception as exc:
                logger.error("dry_run: %s/%s → exception: %s", rule.backend.value, rule.model, exc)
                results.append((rule.role, rule.model, False))

        return results

    def get_stats(self) -> Dict[str, Any]:
        """
        Return accumulated stats per model.

        Returns a dict keyed by model name, each value containing:
          calls, tokens, failures, timeouts, rate_limits,
          total_seconds, total_cost_usd

        Plus a top-level ``budget_usd`` key with the total estimated spend.
        """
        with self._lock:
            out: Dict[str, Any] = {"budget_usd": self._budget_usd}
            for model, stats in self._stats.items():
                out[model] = {
                    "calls": stats.calls,
                    "tokens": stats.tokens,
                    "failures": stats.failures,
                    "timeouts": stats.timeouts,
                    "rate_limits": stats.rate_limits,
                    "total_seconds": round(stats.total_seconds, 2),
                    "total_cost_usd": round(stats.total_cost_usd, 6),
                    "avg_seconds": (
                        round(stats.total_seconds / stats.calls, 2)
                        if stats.calls else 0.0
                    ),
                }
            return out

    def reset_stats(self) -> None:
        """Clear all accumulated stats and budget."""
        with self._lock:
            self._stats.clear()
            self._budget_usd = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _wait_for_off_peak(self) -> None:
        """Block until we are outside peak hours (if configured)."""
        if self._config.peak_hours is None:
            return
        start_h, end_h = self._config.peak_hours
        while True:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            hour = now_utc.hour
            if start_h <= hour < end_h:
                wait_minutes = (end_h - hour) * 60 - now_utc.minute
                logger.info(
                    "Peak hours %02d:00–%02d:00 UTC active. Waiting ~%d min…",
                    start_h, end_h, wait_minutes,
                )
                time.sleep(300)  # check again in 5 minutes
            else:
                break
