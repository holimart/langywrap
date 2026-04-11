"""
langywrap.router.backends — AI backend implementations.

Each backend wraps a CLI tool or API and returns a SubagentResult.

Supported backends:
  ClaudeBackend     — ``claude --print`` via stdin (no ARG_MAX issue)
  OpenCodeBackend   — ``opencode run --format json`` with XDG isolation
  OpenRouterBackend — OpenRouter REST API via httpx
  DirectAPIBackend  — Anthropic / OpenAI SDK (direct)
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums and data models
# ---------------------------------------------------------------------------


class Backend(str, Enum):
    """Supported AI execution backends."""

    CLAUDE = "claude"
    OPENCODE = "opencode"
    OPENROUTER = "openrouter"
    DIRECT_API = "direct_api"
    MOCK = "mock"


class BackendConfig:
    """
    Configuration for a single backend instance.

    Parameters
    ----------
    type:
        Which backend to use.
    binary_path:
        Absolute path to the CLI binary (e.g. ``/home/martin/.opencode/bin/opencode``).
        ``None`` means search ``$PATH``.
    api_key_source:
        Path to an ``auth.json`` file whose ``"api_key"`` field is used,
        OR a plain environment variable name (e.g. ``"OPENROUTER_API_KEY"``).
        ``None`` means rely on the binary's own auth.
    env_overrides:
        Extra environment variables injected for every call to this backend.
    timeout_seconds:
        Hard per-call timeout *in seconds*.  Backends also accept a per-call
        ``timeout`` argument that can further reduce (but not raise) this.
    extra_args:
        Extra CLI flags appended verbatim before the model flag.
    execwrap_path:
        Optional path to ``execwrap.bash``.  When set, every subprocess call
        is prefixed with this wrapper (security hardening).
    rtk_path:
        Optional path to the ``rtk`` binary.  When set, every subprocess call
        is prefixed with ``rtk --`` for output compression/routing.
    """

    def __init__(
        self,
        type: Backend,
        binary_path: Optional[str] = None,
        api_key_source: Optional[str] = None,
        env_overrides: Optional[Dict[str, str]] = None,
        timeout_seconds: int = 300,
        extra_args: Optional[List[str]] = None,
        execwrap_path: Optional[str] = None,
        rtk_path: Optional[str] = None,
        stream_output: bool = False,
    ) -> None:
        self.type = type
        self.binary_path = binary_path
        self.api_key_source = api_key_source
        self.env_overrides: Dict[str, str] = env_overrides or {}
        self.timeout_seconds = timeout_seconds
        self.extra_args: List[str] = extra_args or []
        self.execwrap_path = execwrap_path
        self.rtk_path = rtk_path
        self.stream_output = stream_output


@dataclass
class SubagentResult:
    """
    Result returned by every backend ``run()`` call.

    Attributes
    ----------
    text:
        The raw text output from the model.
    exit_code:
        Process exit code (0 = success, 124 = timeout).
    duration_seconds:
        Wall-clock time the call took.
    model_used:
        Actual model string used (may differ from requested if fallback occurred).
    backend_used:
        Which backend produced this result.
    token_estimate:
        Rough token estimate (``len(text) // 4``).  Not billed tokens.
    raw_output:
        Full raw bytes from the subprocess (useful for JSON backends).
    error:
        Human-readable error description if exit_code != 0.
    """

    text: str
    exit_code: int
    duration_seconds: float
    model_used: str
    backend_used: Backend
    token_estimate: int = field(init=False)
    raw_output: bytes = field(default=b"", repr=False)
    error: str = ""
    idle_timeout: bool = False
    """True when the process was killed because it stopped producing output
    for longer than the idle threshold — a strong signal of an API hang,
    more reliable than just checking output size."""
    input_tokens: int = 0
    """Actual input tokens reported by the model (0 if not available)."""
    output_tokens: int = 0
    """Actual output tokens reported by the model (0 if not available)."""
    files_accessed: List[str] = field(default_factory=list)
    """Files read/written by tool calls during this step."""

    def __post_init__(self) -> None:
        self.token_estimate = max(1, len(self.text) // 4)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def timed_out(self) -> bool:
        return self.exit_code == 124

    @property
    def rate_limited(self) -> bool:
        return bool(
            re.search(
                r"rate.limit|hit your limit|too many requests|429",
                self.text + self.error,
                re.IGNORECASE,
            )
        )

    @property
    def hung(self) -> bool:
        """API hang detected by idle-timeout watchdog or size heuristic.

        Idle-timeout is the primary signal: the process produced no new
        output for ``_IDLE_HANG_SECONDS`` consecutive seconds.  This
        correctly handles slow TTFT (model thinking but hasn't started
        streaming yet is still "producing" connection data) while catching
        truly dead connections.

        Falls back to the legacy size heuristic (timed out + <2KB output)
        for backends that don't use the streaming Popen runner.
        """
        if self.idle_timeout:
            return True
        return self.timed_out and len(self.raw_output) < 2048


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_binary(binary_path: Optional[str], name: str) -> str:
    """Return an absolute path to the binary, raising if not found."""
    if binary_path:
        p = Path(binary_path)
        if p.exists() and p.is_file():
            return str(p)
        raise FileNotFoundError(f"{name} binary not found: {binary_path}")
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(
        f"{name} not found in PATH. Set binary_path in BackendConfig."
    )


def _resolve_api_key(source: Optional[str]) -> Optional[str]:
    """Resolve an API key from an auth.json file path or environment variable name."""
    if source is None:
        return None
    p = Path(source)
    if p.exists() and p.is_file():
        try:
            data = json.loads(p.read_text())
            return data.get("api_key") or data.get("apiKey")
        except (json.JSONDecodeError, OSError):
            pass
    # Treat as env var name
    return os.environ.get(source)


def _build_env(config: BackendConfig, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Build the subprocess environment, merging overrides."""
    env = os.environ.copy()
    env.update(config.env_overrides)
    if extra:
        env.update(extra)
    return env


def _prefix_execwrap(cmd: List[str], execwrap_path: Optional[str]) -> List[str]:
    """Prepend execwrap to a command list when configured."""
    if execwrap_path and Path(execwrap_path).exists():
        return [execwrap_path] + cmd
    return cmd


def _prefix_rtk(cmd: List[str], config: "BackendConfig") -> List[str]:
    """Prepend RTK output-compression wrapper when configured."""
    rtk_path = config.rtk_path
    if rtk_path and Path(rtk_path).exists():
        return [rtk_path, "--"] + cmd
    return cmd


# Default idle-hang threshold: if no new bytes arrive for this many seconds,
# the process is considered hung and killed.  Generous enough for slow TTFT
# on large prompts (Kimi K2.5 can take 60-90s) but catches dead connections.
_IDLE_HANG_SECONDS = 900  # 15 minutes


@dataclass
class _StreamResult:
    """Outcome of :func:`_run_with_idle_watchdog`."""

    raw: bytes
    exit_code: int
    error: str
    idle_timeout: bool
    duration: float


def _log_stream_event(obj: Dict[str, Any]) -> None:
    """Log a parsed stream-json event in a compact, human-readable form."""
    etype = obj.get("type", "?")
    subtype = obj.get("subtype", "")

    if etype == "system" and subtype == "init":
        model = obj.get("model", "?")
        logger.debug("[stream] init — model=%s cwd=%s", model, obj.get("cwd", "?"))

    elif etype == "system" and subtype == "hook_response":
        name = obj.get("hook_name", "?")
        outcome = obj.get("outcome", "?")
        logger.debug("[stream] hook %s → %s", name, outcome)

    elif etype == "assistant":
        msg = obj.get("message", {})
        content = msg.get("content", [])
        usage = msg.get("usage", {})
        out_tok = usage.get("output_tokens", "?")
        # Show first 200 chars of text content
        texts = []
        tool_uses = 0
        for block in content:
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_uses += 1
        preview = " ".join(texts)[:200]
        if tool_uses:
            logger.debug(
                "[stream] assistant — %d tool_use(s), %s output_tokens, text: %s",
                tool_uses, out_tok, preview or "(none)",
            )
        else:
            logger.debug("[stream] assistant — %s output_tokens: %s", out_tok, preview)

    elif etype == "tool_result":
        tool_id = obj.get("tool_use_id", "?")[:12]
        is_err = obj.get("is_error", False)
        logger.debug("[stream] tool_result %s%s", tool_id, " ERROR" if is_err else "")

    elif etype == "result":
        cost = obj.get("total_cost_usd", "?")
        dur = obj.get("duration_ms", "?")
        turns = obj.get("num_turns", "?")
        stop = obj.get("stop_reason", "?")
        logger.debug(
            "[stream] result — %s turns, stop=%s, cost=$%s, %sms",
            turns, stop, cost, dur,
        )

    elif etype == "rate_limit_event":
        info = obj.get("rate_limit_info", {})
        status = info.get("status", "?")
        resets = info.get("resetsAt", "?")
        logger.debug("[stream] rate_limit — status=%s resets=%s", status, resets)

    else:
        # Unknown event — show type and first 150 chars
        logger.debug("[stream] %s.%s: %.150s", etype, subtype, json.dumps(obj))


def _print_stream_text(obj: Dict[str, Any]) -> None:
    """Print human-readable text from a stream-json event to stdout.

    Handles both claude (stream-json) and opencode (--format json) event shapes.
    Only prints text content; ignores tool-use bookkeeping.
    """
    import sys

    etype = obj.get("type", "")

    # opencode: {"type": "text", "text": "..."}
    if etype == "text":
        text = obj.get("text", "")
        if text:
            print(text, end="", flush=True)
        return

    # claude stream-json: {"type": "assistant", "message": {"content": [...]}}
    if etype == "assistant":
        content = obj.get("message", {}).get("content", [])
        for block in content:
            if block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    print(text, end="", flush=True)
        return

    # result event: print a trailing newline so output ends cleanly
    if etype == "result":
        print("", flush=True)


# File-access tool names (both claude and opencode naming conventions).
_FILE_TOOLS = frozenset({
    "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
    "read", "write", "edit", "view", "str_replace_based_edit_tool",
})


def _extract_stream_stats(raw: bytes) -> tuple[int, int, List[str]]:
    """Parse a stream-json / opencode JSON byte stream and extract usage stats.

    Returns:
        (input_tokens, output_tokens, files_accessed)

    Token counts come from the ``result`` event (final totals) or the last
    ``assistant`` event usage block.  File paths come from ``tool_use`` blocks
    whose tool name is in ``_FILE_TOOLS``.
    """
    input_tokens = 0
    output_tokens = 0
    files: List[str] = []
    seen_files: set[str] = set()

    for line in raw.decode(errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = obj.get("type", "")

        # Final result event — has total usage for the session.
        if etype == "result":
            usage = obj.get("usage", {})
            if usage:
                input_tokens = usage.get("input_tokens", input_tokens)
                output_tokens = usage.get("output_tokens", output_tokens)
            continue

        # Assistant turn — usage + tool_use blocks.
        if etype == "assistant":
            msg = obj.get("message", {})
            if isinstance(msg, dict):
                usage = msg.get("usage", {})
                if usage:
                    input_tokens = max(input_tokens, usage.get("input_tokens", 0))
                    output_tokens = max(output_tokens, usage.get("output_tokens", 0))
                for block in msg.get("content", []):
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    name = block.get("name", "")
                    if name not in _FILE_TOOLS:
                        continue
                    inp = block.get("input", {})
                    path = inp.get("file_path") or inp.get("path") or inp.get("target_file")
                    if path and path not in seen_files:
                        seen_files.add(path)
                        files.append(path)

    return input_tokens, output_tokens, files


def _run_with_idle_watchdog(
    cmd: List[str],
    *,
    env: Dict[str, str],
    timeout: int,
    idle_hang_seconds: int = _IDLE_HANG_SECONDS,
    stdin_data: Optional[bytes] = None,
    use_setsid: bool = False,
    stream_output: bool = False,
) -> _StreamResult:
    """Run *cmd* with a Popen streaming reader + idle-timeout watchdog.

    Instead of buffering all output and only deciding "hung?" at the end,
    this streams stdout/stderr in a background thread.  A watchdog thread
    monitors ``last_byte_time`` — if no new bytes arrive for
    ``idle_hang_seconds``, the process group is killed and the result is
    tagged ``idle_timeout=True``.

    Parameters
    ----------
    cmd:
        Command to run.
    env:
        Full environment dict.
    timeout:
        Hard wall-clock timeout in seconds (same as subprocess.run).
    idle_hang_seconds:
        Kill the process if no new output bytes for this many seconds.
    stdin_data:
        Optional bytes to pipe to the process's stdin.
    use_setsid:
        If True, run the process in a new session (``setsid``) for
        process-group isolation — same as the original OpenCode backend.
    """
    t0 = time.monotonic()
    chunks: List[bytes] = []
    last_byte_time = time.monotonic()
    lock = threading.Lock()
    idle_killed = False

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=use_setsid,
        )
    except Exception as exc:
        return _StreamResult(
            raw=b"", exit_code=1, error=str(exc),
            idle_timeout=False, duration=time.monotonic() - t0,
        )

    # -- Reader thread: drains stdout into chunks[] --------------------------
    total_bytes = 0

    def _reader() -> None:
        nonlocal last_byte_time, total_bytes
        assert proc.stdout is not None
        while True:
            data = proc.stdout.read(4096)
            if not data:
                break
            with lock:
                chunks.append(data)
                last_byte_time = time.monotonic()
                total_bytes += len(data)
            for line in data.decode(errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if stream_output:
                        _print_stream_text(obj)
                    if logger.isEnabledFor(logging.DEBUG):
                        _log_stream_event(obj)
                except (json.JSONDecodeError, ValueError):
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("[stream] %s", line)
        proc.stdout.close()

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    # -- Send stdin if needed (e.g. claude --print) --------------------------
    if stdin_data is not None and proc.stdin is not None:
        try:
            proc.stdin.write(stdin_data)
            proc.stdin.close()
        except OSError:
            pass

    # -- Watchdog: polls every 5s, kills on idle or hard timeout -------------
    deadline = t0 + timeout
    poll_interval = 5
    last_progress_log = t0
    progress_log_interval = 30  # log output growth every 30s

    while proc.poll() is None:
        time.sleep(poll_interval)
        now = time.monotonic()

        # Hard timeout
        if now >= deadline:
            _kill_proc(proc, use_setsid)
            reader_thread.join(timeout=5)
            raw = b"".join(chunks)
            return _StreamResult(
                raw=raw,
                exit_code=124,
                error=f"Timeout after {timeout}s",
                idle_timeout=False,
                duration=now - t0,
            )

        # Periodic progress log (INFO level)
        with lock:
            idle_secs = now - last_byte_time
            cur_bytes = total_bytes
        if now - last_progress_log >= progress_log_interval:
            elapsed = int(now - t0)
            if idle_secs > 10:
                logger.info(
                    "[watchdog] %ds elapsed, %dB output, idle %ds",
                    elapsed, cur_bytes, int(idle_secs),
                )
            else:
                logger.info(
                    "[watchdog] %ds elapsed, %dB output, receiving data",
                    elapsed, cur_bytes,
                )
            last_progress_log = now

        # Idle hang check
        if idle_secs >= idle_hang_seconds:
            idle_killed = True
            logger.info(
                "Idle watchdog: no output for %ds (threshold %ds) — killing process",
                int(idle_secs), idle_hang_seconds,
            )
            _kill_proc(proc, use_setsid)
            break

    reader_thread.join(timeout=5)
    duration = time.monotonic() - t0
    raw = b"".join(chunks)

    exit_code = proc.returncode if proc.returncode is not None else 1
    error_msg = ""

    if idle_killed:
        exit_code = 124
        error_msg = (
            f"Idle timeout: no new output for {idle_hang_seconds}s "
            f"(total output: {len(raw)}B, wall time: {duration:.0f}s)"
        )

    return _StreamResult(
        raw=raw,
        exit_code=exit_code,
        error=error_msg,
        idle_timeout=idle_killed,
        duration=duration,
    )


def _kill_proc(proc: subprocess.Popen, session_leader: bool) -> None:  # type: ignore[type-arg]
    """Kill a process (and its group if setsid was used)."""
    try:
        if session_leader and proc.pid:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            if session_leader and proc.pid:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except (OSError, ProcessLookupError):
            pass


def _extract_text_from_stream_json(raw: bytes) -> str:
    """Extract the final result text from ``--output-format stream-json`` output.

    The stream contains newline-delimited JSON objects.  We look for:
    1. A ``{"type": "result", "result": "..."}`` event (preferred — final text).
    2. Falling back to concatenating ``content[].text`` from ``"type": "assistant"``
       message events.
    3. If neither is found, return the raw output decoded.
    """
    text = raw.decode(errors="replace")
    lines = text.strip().splitlines()

    # Pass 1: look for result event
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if obj.get("type") == "result" and "result" in obj:
            return obj["result"]

    # Pass 2: concatenate assistant message text blocks
    parts: List[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if obj.get("type") == "assistant":
            msg = obj.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "text":
                    parts.append(block["text"])
    if parts:
        return "\n".join(parts)

    # Pass 3: fallback — return raw text
    return text.strip()


# ---------------------------------------------------------------------------
# ClaudeBackend
# ---------------------------------------------------------------------------


class ClaudeBackend:
    """
    Runs ``claude --print --output-format stream-json --verbose`` with prompt
    piped to stdin.

    Notes
    -----
    - Uses ``stream-json`` so the idle watchdog can detect API hangs in
      real-time (``--print`` alone buffers all output until exit).
    - Uses stdin pipe (not ``-p``) to avoid ARG_MAX (E2BIG) on large prompts.
    - Sets ``__EXECWRAP_ACTIVE=1`` and ``-u CLAUDECODE`` to prevent recursive
      invocation inside claude hooks.
    - ``--dangerously-skip-permissions`` is intentional: the surrounding
      execwrap/security layer is the enforcement boundary.
    """

    def __init__(self, config: BackendConfig) -> None:
        self.config = config
        self._binary = _resolve_binary(config.binary_path, "claude")

    def run(
        self, prompt: str, model: str, timeout: int, *, tools: Optional[List[str]] = None,
    ) -> SubagentResult:
        effective_timeout = min(timeout, self.config.timeout_seconds)
        tool_args: List[str] = []
        if tools:
            tool_args = ["--allowedTools", ",".join(tools)]
        cmd = _prefix_execwrap(
            [
                self._binary,
                "--model", model,
                "--dangerously-skip-permissions",
                "--print",
                "--output-format", "stream-json",
                "--verbose",
                *tool_args,
                *self.config.extra_args,
            ],
            self.config.execwrap_path,
        )
        cmd = _prefix_rtk(cmd, self.config)
        env = _build_env(
            self.config,
            {
                "__EXECWRAP_ACTIVE": "1",
            },
        )
        # Unset CLAUDECODE to prevent recursive invocation detection
        env.pop("CLAUDECODE", None)

        # stream-json mode emits JSON events as they arrive, so the idle
        # watchdog can detect genuine API hangs (no bytes = no progress).
        sr = _run_with_idle_watchdog(
            cmd,
            env=env,
            timeout=effective_timeout,
            stdin_data=prompt.encode(),
            stream_output=self.config.stream_output,
        )

        text = _extract_text_from_stream_json(sr.raw)
        in_tok, out_tok, files = _extract_stream_stats(sr.raw)

        return SubagentResult(
            text=text,
            exit_code=sr.exit_code,
            duration_seconds=sr.duration,
            model_used=model,
            backend_used=Backend.CLAUDE,
            raw_output=sr.raw,
            error=sr.error,
            idle_timeout=sr.idle_timeout,
            input_tokens=in_tok,
            output_tokens=out_tok,
            files_accessed=files,
        )


# ---------------------------------------------------------------------------
# OpenCodeBackend
# ---------------------------------------------------------------------------


class OpenCodeBackend:
    """
    Runs ``opencode run --model X --format json`` with XDG_DATA_HOME isolation.

    The ``--format json`` flag makes opencode emit newline-delimited JSON events.
    We extract ``{"type":"text","text":"..."}`` lines to reconstruct the full
    model response.

    Notes
    -----
    - ``setsid`` is used for process-group isolation so a timeout kills all
      child processes (opencode can spawn subprocesses).
    - ``XDG_DATA_HOME`` is set to a fresh temp dir per call to prevent
      opencode's sqlite state from persisting between calls and causing lock
      contention.
    - ``SHELL=/bin/bash`` ensures tool scripts inside opencode work correctly.
    """

    def __init__(self, config: BackendConfig) -> None:
        self.config = config
        self._binary = _resolve_binary(
            config.binary_path,
            "opencode",
        )

    def run(
        self, prompt: str, model: str, timeout: int, *, tools: Optional[List[str]] = None,
    ) -> SubagentResult:
        effective_timeout = min(timeout, self.config.timeout_seconds)

        xdg_tmp = tempfile.mkdtemp(prefix="opencode_")
        try:
            cmd = _prefix_execwrap(
                [
                    self._binary,
                    "run",
                    "--model", model,
                    "--format", "json",
                    *self.config.extra_args,
                ],
                self.config.execwrap_path,
            )
            cmd = _prefix_rtk(cmd, self.config)

            env = _build_env(
                self.config,
                {
                    "__EXECWRAP_ACTIVE": "1",
                    "XDG_DATA_HOME": xdg_tmp,
                    "SHELL": "/bin/bash",
                },
            )

            sr = _run_with_idle_watchdog(
                cmd,
                env=env,
                timeout=effective_timeout,
                stdin_data=prompt.encode(),
                use_setsid=True,
                stream_output=self.config.stream_output,
            )

            text = self._extract_text(sr.raw)
            in_tok, out_tok, files = _extract_stream_stats(sr.raw)

            return SubagentResult(
                text=text,
                exit_code=sr.exit_code,
                duration_seconds=sr.duration,
                model_used=model,
                backend_used=Backend.OPENCODE,
                raw_output=sr.raw,
                error=sr.error,
                idle_timeout=sr.idle_timeout,
                input_tokens=in_tok,
                output_tokens=out_tok,
                files_accessed=files,
            )
        finally:
            # Clean up temp XDG dir
            import shutil as _shutil
            _shutil.rmtree(xdg_tmp, ignore_errors=True)

    @staticmethod
    def _extract_text(raw: bytes) -> str:
        """
        Parse opencode JSON event stream and extract model text content.

        opencode emits lines like:
          {"type":"text","text":"..."}
          {"type":"assistant","message":{"content":[{"type":"text","text":"..."}]}}
        """
        lines = raw.decode(errors="replace").splitlines()
        parts: List[str] = []
        for line in lines:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Direct text event
            if event.get("type") == "text" and isinstance(event.get("text"), str):
                parts.append(event["text"])
                continue
            # Assistant message with content array
            msg = event.get("message", {})
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))

        result = "".join(parts).strip()
        if not result:
            # Fall back to raw output (stripped of JSON)
            result = raw.decode(errors="replace").strip()
        return result


# ---------------------------------------------------------------------------
# OpenRouterBackend
# ---------------------------------------------------------------------------


class OpenRouterBackend:
    """
    Calls the OpenRouter chat completions API via httpx.

    OpenRouter is used for free or cheap model access (e.g. kimi-k2.5,
    mistral, gemini flash) without needing individual provider accounts.

    Requires: ``pip install httpx``
    API key: set ``OPENROUTER_API_KEY`` env var or pass via ``api_key_source``.
    """

    BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, config: BackendConfig) -> None:
        self.config = config
        self._api_key = _resolve_api_key(config.api_key_source) or os.environ.get(
            "OPENROUTER_API_KEY", ""
        )

    def run(
        self, prompt: str, model: str, timeout: int, *, tools: Optional[List[str]] = None,
    ) -> SubagentResult:
        effective_timeout = min(timeout, self.config.timeout_seconds)
        t0 = time.monotonic()
        text = ""
        exit_code = 0
        error_msg = ""
        raw_bytes = b""

        try:
            import httpx  # type: ignore

            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/langywrap/langywrap",
                "X-Title": "langywrap",
            }
            # Strip "openrouter/" prefix if present — OpenRouter expects
            # bare model IDs like "google/gemma-4-31b-it".
            api_model = model.removeprefix("openrouter/")
            payload = {
                "model": api_model,
                "messages": [{"role": "user", "content": prompt}],
            }
            with httpx.Client(timeout=effective_timeout) as client:
                response = client.post(self.BASE_URL, json=payload, headers=headers)
            raw_bytes = response.content
            if response.status_code == 429:
                exit_code = 1
                error_msg = f"Rate limited (HTTP 429): {response.text[:200]}"
            elif response.status_code != 200:
                exit_code = 1
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
            else:
                data = response.json()
                text = data["choices"][0]["message"]["content"]
        except ImportError:
            exit_code = 1
            error_msg = "httpx not installed. Run: pip install httpx"
        except Exception as exc:
            exit_code = 1
            error_msg = str(exc)

        duration = time.monotonic() - t0
        return SubagentResult(
            text=text,
            exit_code=exit_code,
            duration_seconds=duration,
            model_used=model,
            backend_used=Backend.OPENROUTER,
            raw_output=raw_bytes,
            error=error_msg,
        )


# ---------------------------------------------------------------------------
# DirectAPIBackend
# ---------------------------------------------------------------------------


class DirectAPIBackend:
    """
    Calls Anthropic or OpenAI APIs directly via their Python SDKs.

    Detects which SDK to use based on the model name prefix:
      - ``claude-*``  → Anthropic SDK
      - ``gpt-*`` / ``o1-*`` / ``o3-*``  → OpenAI SDK

    Requires: ``pip install anthropic`` or ``pip install openai``
    """

    def __init__(self, config: BackendConfig) -> None:
        self.config = config
        self._api_key = _resolve_api_key(config.api_key_source)

    def run(
        self, prompt: str, model: str, timeout: int, *, tools: Optional[List[str]] = None,
    ) -> SubagentResult:
        effective_timeout = min(timeout, self.config.timeout_seconds)
        t0 = time.monotonic()
        text = ""
        exit_code = 0
        error_msg = ""
        raw_bytes = b""

        try:
            if model.startswith("claude"):
                text = self._run_anthropic(prompt, model, effective_timeout)
            else:
                text = self._run_openai(prompt, model, effective_timeout)
        except Exception as exc:
            exit_code = 1
            error_msg = str(exc)
            # Detect rate limit
            exc_str = str(exc).lower()
            if "rate" in exc_str or "429" in exc_str:
                error_msg = f"Rate limited: {exc}"

        duration = time.monotonic() - t0
        return SubagentResult(
            text=text,
            exit_code=exit_code,
            duration_seconds=duration,
            model_used=model,
            backend_used=Backend.DIRECT_API,
            raw_output=raw_bytes,
            error=error_msg,
        )

    def _run_anthropic(self, prompt: str, model: str, timeout: int) -> str:
        try:
            import anthropic  # type: ignore
        except ImportError:
            raise ImportError(
                "Anthropic SDK not installed. Run: pip install anthropic"
            )

        key = self._api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        client = anthropic.Anthropic(api_key=key, timeout=timeout)
        msg = client.messages.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text  # type: ignore

    def _run_openai(self, prompt: str, model: str, timeout: int) -> str:
        try:
            import openai  # type: ignore
        except ImportError:
            raise ImportError(
                "OpenAI SDK not installed. Run: pip install openai"
            )

        key = self._api_key or os.environ.get("OPENAI_API_KEY", "")
        client = openai.OpenAI(api_key=key, timeout=timeout)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# MockBackend — for testing that security + RTK layers are enforced
# ---------------------------------------------------------------------------


class MockBackend:
    """
    A bash-based mock LLM backend for integration testing.

    Instead of calling an actual LLM, it runs the prompt through ``bash -c``
    via the same subprocess pipeline as real backends (including execwrap,
    security engine, and RTK output compression when configured).

    This verifies that:
    1. Commands routed through ExecutionRouter are subject to SecurityEngine
    2. RTK output compression is applied when configured
    3. The full execution pipeline works end-to-end without real API calls

    The mock "model" is just ``echo`` — it echoes the prompt back (or a
    configured response). For security testing, set ``mock_command`` to a
    dangerous command and verify it gets blocked.

    Usage::

        config = BackendConfig(
            type=Backend.MOCK,
            env_overrides={"MOCK_RESPONSE": "Hello from mock"},
            execwrap_path="/path/to/execwrap.bash",  # enables security layers
        )
        backend = MockBackend(config)
        result = backend.run("test prompt", "mock-model", timeout=30)
    """

    def __init__(self, config: BackendConfig) -> None:
        self.config = config

    def run(
        self, prompt: str, model: str, timeout: int, *, tools: Optional[List[str]] = None,
    ) -> SubagentResult:
        effective_timeout = min(timeout, self.config.timeout_seconds)

        # The mock command: either from env override or echo the prompt
        mock_response = self.config.env_overrides.get("MOCK_RESPONSE", "")
        mock_command = self.config.env_overrides.get("MOCK_COMMAND", "")

        if mock_command:
            # Run an actual bash command (for security testing)
            cmd: List[str] = ["bash", "-c", mock_command]
        elif mock_response:
            # Echo a fixed response
            cmd = ["bash", "-c", f"echo {json.dumps(mock_response)}"]
        else:
            # Echo back the first line of the prompt as response
            first_line = prompt.split("\n")[0][:200]
            cmd = ["bash", "-c", f"echo 'MOCK_RESPONSE: {json.dumps(first_line)}'"]

        # Apply execwrap if configured — this is the key: security layers fire
        cmd = _prefix_execwrap(cmd, self.config.execwrap_path)
        cmd = _prefix_rtk(cmd, self.config)

        env = _build_env(self.config)

        t0 = time.monotonic()
        raw = b""
        exit_code = 0
        error_msg = ""

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=effective_timeout,
                env=env,
            )
            raw = proc.stdout + proc.stderr
            exit_code = proc.returncode
            if exit_code != 0:
                error_msg = proc.stderr.decode(errors="replace").strip()
        except subprocess.TimeoutExpired:
            exit_code = 124
            error_msg = f"Timeout after {effective_timeout}s"
        except Exception as exc:
            exit_code = 1
            error_msg = str(exc)

        duration = time.monotonic() - t0
        text = raw.decode(errors="replace").strip()

        return SubagentResult(
            text=text,
            exit_code=exit_code,
            duration_seconds=duration,
            model_used=model,
            backend_used=Backend.MOCK,
            raw_output=raw,
            error=error_msg,
        )

    def run_with_security_check(
        self,
        command: str,
        model: str = "mock",
        timeout: int = 30,
        security_engine: Any = None,
    ) -> SubagentResult:
        """
        Run a command through the mock backend with explicit security check.

        This method first checks the command against the SecurityEngine,
        then runs it if allowed. Useful for testing security enforcement
        without needing execwrap configured.
        """
        if security_engine is not None:
            from langywrap.security.engine import PermissionDecision

            result = security_engine.check(command)
            if result.decision == PermissionDecision.DENY:
                return SubagentResult(
                    text="",
                    exit_code=2,
                    duration_seconds=0.0,
                    model_used=model,
                    backend_used=Backend.MOCK,
                    error=f"BLOCKED by SecurityEngine: {result.message}",
                )

        # Run the actual command
        self.config.env_overrides["MOCK_COMMAND"] = command
        return self.run("", model, timeout)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_backend(config: BackendConfig) -> "ClaudeBackend | OpenCodeBackend | OpenRouterBackend | DirectAPIBackend | MockBackend":
    """Instantiate the correct backend class from a BackendConfig."""
    mapping = {
        Backend.CLAUDE: ClaudeBackend,
        Backend.OPENCODE: OpenCodeBackend,
        Backend.OPENROUTER: OpenRouterBackend,
        Backend.DIRECT_API: DirectAPIBackend,
        Backend.MOCK: MockBackend,
    }
    cls = mapping.get(config.type)
    if cls is None:
        raise ValueError(f"Unknown backend type: {config.type}")
    return cls(config)
