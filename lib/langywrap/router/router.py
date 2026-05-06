"""
langywrap.router.router — ExecutionRouter: pure backend dispatcher.

ExecutionRouter is a thin multiplexer. It takes a model + engine + timeout
(everything the caller already knows from the pipeline DSL) and runs the
prompt on the matching backend with retries, hang detection, rate-limit
backoff, and peak-hour throttling. There is no RouteConfig/RouteRule/role
indirection — the caller tells the router exactly what to run.

Usage::

    from langywrap.router import ExecutionRouter
    from langywrap.router.backends import Backend, BackendConfig

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
"""

from __future__ import annotations

import datetime
import logging
import subprocess
import threading
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .backends import (
    Backend,
    BackendConfig,
    SubagentResult,
    create_backend,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DryRunResult:
    """Detailed connectivity result for a single model/backend target."""

    model: str
    backend: str
    reachable: bool
    reason: str = ""
    detail: str = ""

    def as_tuple(self) -> tuple[str, str, bool]:
        """Backward-compatible result shape used by older callers."""
        return (self.model, self.backend, self.reachable)


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
_COST_PER_1K_TOKENS: dict[str, float] = {
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


def _trim_detail(text: str, limit: int = 240) -> str:
    """Collapse diagnostic text to one short display line."""
    line = " ".join((text or "").strip().split())
    if len(line) > limit:
        return line[: limit - 1] + "…"
    return line


def _classify_failed_result(result: SubagentResult) -> tuple[str, str]:
    """Map backend output to a dry-run failure category and detail."""
    result_parts = (result.error, result.text, result.raw_output.decode(errors="replace"))
    combined = "\n".join(part for part in result_parts if part)
    lower = combined.lower()

    if "providermodelnotfounderror" in lower or "model not found:" in lower:
        return "model_not_configured", _trim_detail(combined)
    if result.auth_failed:
        return "auth_failed", _trim_detail(result.auth_failed_snippet or combined)
    if any(
        marker in lower
        for marker in (
            "api key",
            "apikey",
            "unauthorized",
            "forbidden",
            'statuscode":401',
            'statuscode":403',
            "missing credentials",
            "no credentials",
        )
    ):
        return "auth_failed", _trim_detail(combined)
    if result.rate_limited:
        return "rate_limited", _trim_detail(result.rate_limit_snippet or combined)
    if result.timed_out:
        return "timeout", _trim_detail(combined)
    if result.exit_code != 0:
        return "backend_error", _trim_detail(combined)
    return "unexpected_response", _trim_detail(result.text or combined)


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
        self._thread: threading.Thread | None = None

    def __enter__(self) -> _HeartbeatWatcher:
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
    Pure backend dispatcher: runs a prompt on a specified model/engine
    with retries, hang detection, rate-limit backoff, and peak-hour
    throttling. The caller owns the routing decision — no RouteConfig.

    Parameters
    ----------
    backends:
        Map of ``Backend`` → ``BackendConfig``. Only backends listed here
        can be used; calls that target an unlisted backend raise.
    rate_limit_backoff_seconds:
        How long to wait after a rate-limit response. Default 600s.
    peak_hours:
        Optional ``(start_hour, end_hour)`` UTC window during which
        ``execute()`` blocks until off-peak. ``None`` = no throttling.
    default_backend:
        Fallback when no backend is configured for the resolved model
        and the caller did not pin ``engine``.
    """

    def __init__(
        self,
        backends: dict[Backend, BackendConfig] | None = None,
        *,
        rate_limit_backoff_seconds: int = _RATE_LIMIT_BACKOFF_SECONDS,
        peak_hours: tuple[int, int] | None = None,
        default_backend: Backend = Backend.CLAUDE,
    ) -> None:
        self._backends: dict[Backend, BackendConfig] = backends or {}
        self._rate_limit_backoff = rate_limit_backoff_seconds
        self._peak_hours = peak_hours
        self._default_backend = default_backend
        self._stats: dict[str, _ModelStats] = defaultdict(_ModelStats)
        self._budget_usd: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        prompt: str,
        *,
        model: str,
        engine: str = "auto",
        timeout_minutes: int = 30,
        tools: str | list[str] | None = None,
        retry_models: list[str] | None = None,
        retry_max: int = 2,
        abort_on_hang: bool = False,
        tag: str = "",
    ) -> SubagentResult:
        """
        Run ``prompt`` on ``model`` via ``engine``, with retries and
        hang/rate-limit handling.

        Parameters
        ----------
        prompt:
            Full prompt text (caller is responsible for enrichment, scope
            headers, cycle context, etc.).
        model:
            Resolved model id (e.g. ``claude-haiku-4-5-20251001``).
        engine:
            One of ``claude|opencode|openrouter|direct_api|auto``. When
            ``"auto"``, backend is inferred from the model prefix.
        timeout_minutes:
            Per-attempt wall-clock timeout.
        tools:
            Tool allow-list (passed through if the backend supports it).
            May be a comma-joined string or a list.
        retry_models:
            Fallback chain. If the primary model fails (non-hang), the
            dispatcher advances to the next entry.
        retry_max:
            Maximum total attempts across all models in the chain.
        abort_on_hang:
            If True, return immediately on first hang. Use for
            ``fail_fast`` steps so a hung API call doesn't eat hours.
        tag:
            Short label used only in log lines (typically ``step.name``).

        Returns the first successful result, or the last failure result
        if retries are exhausted. Never raises on transient errors —
        callers inspect ``result.ok``.
        """
        self._wait_for_off_peak()

        label = tag or model
        model_chain = [model] + list(retry_models or [])
        max_attempts = retry_max + 1  # first attempt + retries
        timeout_seconds = timeout_minutes * 60

        engine_backend = _resolve_engine_backend(engine)

        last_result: SubagentResult | None = None
        attempt = 0
        model_idx = 0
        hang_streak = 0

        while attempt < max_attempts:
            current_model = model_chain[min(model_idx, len(model_chain) - 1)]

            # Pick backend: explicit engine > per-model inference > default
            if engine_backend is not None:
                target_backend = engine_backend
            else:
                target_backend = _infer_backend_from_model(current_model)

            backend_cfg = self._backends.get(target_backend) or self._backends.get(
                self._default_backend
            )
            if backend_cfg is None:
                raise RuntimeError(
                    f"No backend configured for {target_backend.value!r}. "
                    f"Pass a backends dict to ExecutionRouter.__init__."
                )

            backend = create_backend(backend_cfg)
            logger.info(
                "[%s] attempt %d/%d — model=%s backend=%s",
                label,
                attempt + 1,
                max_attempts,
                current_model,
                target_backend.value,
            )

            tool_list: list[str] | None = None
            if tools:
                if isinstance(tools, str):
                    tool_list = [t.strip() for t in tools.split(",") if t.strip()]
                else:
                    tool_list = list(tools)

            with _HeartbeatWatcher(step_name=f"{label}[{current_model}]"):
                result = backend.run(
                    prompt=prompt,
                    model=current_model,
                    timeout=timeout_seconds,
                    tools=tool_list,
                )

            with self._lock:
                self._stats[current_model].record(result)
                self._budget_usd += _estimate_cost(current_model, result.token_estimate)

            last_result = result

            if result.rate_limited:
                snippet = result.rate_limit_snippet or "<no snippet captured>"
                logger.warning(
                    "[%s] Rate limited (detected in output: %r). Waiting %ds…",
                    label,
                    snippet,
                    self._rate_limit_backoff,
                )
                time.sleep(self._rate_limit_backoff)
                attempt += 1
                continue

            if result.ok:
                logger.info(
                    "[%s] completed — model=%s tokens≈%d duration=%.1fs",
                    label,
                    current_model,
                    result.token_estimate,
                    result.duration_seconds,
                )
                return result

            if result.hung:
                hang_kind = "idle-timeout" if result.idle_timeout else "no-output"
                if abort_on_hang:
                    logger.warning(
                        "[%s] API hang on %s (%s, %dB output). "
                        "abort_on_hang=True — returning failure immediately.",
                        label,
                        current_model,
                        hang_kind,
                        len(result.raw_output),
                    )
                    return result
                hang_streak += 1
                backoff = min(
                    _HANG_BACKOFF_BASE * (2 ** (hang_streak - 1)),
                    _HANG_BACKOFF_MAX,
                )
                logger.warning(
                    "[%s] API hang on %s (%s, %dB output). "
                    "Retrying same model after %ds backoff… (hang #%d)",
                    label,
                    current_model,
                    hang_kind,
                    len(result.raw_output),
                    backoff,
                    hang_streak,
                )
                time.sleep(backoff)
                continue

            hang_streak = 0

            if result.timed_out:
                if model_idx + 1 < len(model_chain):
                    logger.warning(
                        "[%s] Timeout on %s (%dB output). Advancing to fallback model %s.",
                        label,
                        current_model,
                        len(result.raw_output),
                        model_chain[model_idx + 1],
                    )
                    attempt += 1
                    model_idx += 1
                    continue
                logger.warning(
                    "[%s] Genuine timeout (%dB output). No fallback — giving up.",
                    label,
                    len(result.raw_output),
                )
                break

            combined = (result.error + " " + result.text).lower()
            if "may not exist" in combined or "you may not have access" in combined:
                logger.error(
                    "[%s] Permanent failure on %s — model unavailable. Not retrying. (%s)",
                    label,
                    current_model,
                    result.error[:200],
                )
                break

            logger.warning(
                "[%s] Failed (exit=%d): %s",
                label,
                result.exit_code,
                result.error[:200],
            )
            attempt += 1
            if model_idx + 1 < len(model_chain):
                model_idx += 1

        assert last_result is not None
        logger.error(
            "[%s] Exhausted all %d attempts. Last exit=%d.",
            label,
            attempt,
            last_result.exit_code,
        )
        return last_result

    def _check_opencode_model_registered(
        self,
        model: str,
        backend_cfg: BackendConfig,
    ) -> DryRunResult | None:
        """Return a failure if OpenCode's active config does not list model."""
        if "/" not in model:
            return None

        provider, model_id = model.split("/", 1)
        binary = backend_cfg.binary_path or "opencode"
        try:
            proc = subprocess.run(
                [binary, "models", provider],
                cwd=backend_cfg.cwd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.info("dry_run: could not preflight opencode models: %s", exc)
            return None

        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            return DryRunResult(
                model=model,
                backend=Backend.OPENCODE.value,
                reachable=False,
                reason="model_not_configured",
                detail=_trim_detail(
                    output or f"opencode models {provider} exited {proc.returncode}"
                ),
            )

        listed = {line.strip() for line in output.splitlines() if line.strip()}
        if model not in listed and model_id not in listed:
            return DryRunResult(
                model=model,
                backend=Backend.OPENCODE.value,
                reachable=False,
                reason="model_not_configured",
                detail=(
                    f"OpenCode active config does not list {model}. "
                    f"Add provider.{provider}.models.{model_id}."
                ),
            )
        return None

    def dry_run_detailed(
        self,
        targets: Iterable[tuple[str, str]] | Iterable[tuple[str, str, int]],
    ) -> list[DryRunResult]:
        """
        Ping each (model, engine) or (model, engine, timeout_s) target.

        Returns one :class:`DryRunResult` per unique ``(model, backend)``.
        It distinguishes common operator-actionable failures such as
        ``model_not_configured`` and ``auth_failed``.
        """
        results: list[DryRunResult] = []
        ping_prompt = "Reply with exactly: PONG"

        seen: set[tuple[str, str]] = set()

        for item in targets:
            if len(item) == 2:
                model, engine = item
                timeout_s = 60
            else:
                model, engine, timeout_s = item  # type: ignore[misc]

            engine_backend = _resolve_engine_backend(engine) or _infer_backend_from_model(model)
            key = (model, engine_backend.value)
            if key in seen:
                continue
            seen.add(key)

            backend_cfg = self._backends.get(engine_backend) or self._backends.get(
                self._default_backend
            )
            if backend_cfg is None:
                logger.warning("dry_run: no backend configured for %s", engine_backend.value)
                results.append(
                    DryRunResult(
                        model=model,
                        backend=engine_backend.value,
                        reachable=False,
                        reason="backend_not_configured",
                        detail=f"No backend configured for {engine_backend.value}",
                    )
                )
                continue

            if engine_backend is Backend.OPENCODE:
                model_failure = self._check_opencode_model_registered(model, backend_cfg)
                if model_failure is not None:
                    results.append(model_failure)
                    continue

            try:
                backend = create_backend(backend_cfg)
                result = backend.run(
                    prompt=ping_prompt,
                    model=model,
                    timeout=min(180, timeout_s),
                )
                reachable = result.ok and (
                    "PONG" in result.text.upper()
                    or (
                        len(result.text) > 500
                        and not result.auth_failed
                        and not result.rate_limited
                    )
                )
                reason = "ok" if reachable else _classify_failed_result(result)[0]
                detail = "" if reachable else _classify_failed_result(result)[1]
                logger.info(
                    "dry_run: %s/%s → %s (%s, exit=%d, %dB)",
                    engine_backend.value,
                    model,
                    "OK" if reachable else "FAIL",
                    reason,
                    result.exit_code,
                    len(result.raw_output),
                )
                results.append(
                    DryRunResult(
                        model=model,
                        backend=engine_backend.value,
                        reachable=reachable,
                        reason=reason,
                        detail=detail,
                    )
                )
            except Exception as exc:
                logger.error("dry_run: %s/%s → exception: %s", engine_backend.value, model, exc)
                results.append(
                    DryRunResult(
                        model=model,
                        backend=engine_backend.value,
                        reachable=False,
                        reason="exception",
                        detail=_trim_detail(str(exc)),
                    )
                )

        return results

    def dry_run(
        self,
        targets: Iterable[tuple[str, str]] | Iterable[tuple[str, str, int]],
    ) -> list[tuple[str, str, bool]]:
        """Backward-compatible dry run returning ``(model, backend, ok)`` tuples."""
        return [result.as_tuple() for result in self.dry_run_detailed(targets)]

    def get_stats(self) -> dict[str, Any]:
        """
        Return accumulated stats per model.

        Returns a dict keyed by model name, each value containing:
          calls, tokens, failures, timeouts, rate_limits,
          total_seconds, total_cost_usd

        Plus a top-level ``budget_usd`` key with the total estimated spend.
        """
        with self._lock:
            out: dict[str, Any] = {"budget_usd": self._budget_usd}
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
                        round(stats.total_seconds / stats.calls, 2) if stats.calls else 0.0
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
        if self._peak_hours is None:
            return
        start_h, end_h = self._peak_hours
        while True:
            now_utc = datetime.datetime.now(datetime.UTC)
            hour = now_utc.hour
            if start_h <= hour < end_h:
                wait_minutes = (end_h - hour) * 60 - now_utc.minute
                logger.info(
                    "Peak hours %02d:00–%02d:00 UTC active. Waiting ~%d min…",
                    start_h,
                    end_h,
                    wait_minutes,
                )
                time.sleep(300)
            else:
                break


def _resolve_engine_backend(engine: str | None) -> Backend | None:
    """Return the Backend for an explicit ``engine`` string, or None for 'auto'."""
    if not engine or engine == "auto":
        return None
    engine_map = {
        "claude": Backend.CLAUDE,
        "opencode": Backend.OPENCODE,
        "openrouter": Backend.OPENROUTER,
        "direct_api": Backend.DIRECT_API,
    }
    backend = engine_map.get(engine)
    if backend is None:
        logger.warning("Unknown engine %r, inferring from model", engine)
    return backend
