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
from typing import Any

logger = logging.getLogger(__name__)


# Literals checked against the full model text output.
# Must be unambiguous API-error phrases — NOT generic words that could appear
# in model-written prose (e.g. progress-note descriptions of past rate limits).
_RATE_LIMIT_TEXT_LITERALS = (
    # Claude Code / Anthropic surfaced messages.
    "You've hit your limit",
    "This request would exceed your account's rate limit. Please try again later.",
    "Your account has hit a rate limit.",
    # OpenCode source-level messages (verbose enough to be unambiguous).
    "Free usage exceeded, subscribe to Go https://opencode.ai/go",
    # Provider pass-through messages observed through OpenCode.
    (
        "Upstream error from Alibaba: Request rate increased too quickly. "
        "To ensure system stability, please adjust your client logic to scale "
        "requests more smoothly over time."
    ),
    "Too many requests, the rate limit is 8000000 tokens per minute.",
    "concurrency limit exceeded for account, please retry later",
)

# Short/generic literals only matched against stderr / process error strings,
# NOT against model-generated text (where they appear in historical prose).
_RATE_LIMIT_ERROR_ONLY_LITERALS = (
    "Too Many Requests",
    "Rate Limited",
)

# Combined set for convenience — used when searching only the error field.
_RATE_LIMIT_ALL_LITERALS = _RATE_LIMIT_TEXT_LITERALS + _RATE_LIMIT_ERROR_ONLY_LITERALS


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
    THINKING_LOOP = "thinking_loop"


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
    idle_timeout_seconds:
        Kill the subprocess if no new output bytes arrive for this many seconds.
        ``None`` uses the backend's built-in default (``_IDLE_HANG_SECONDS``).
    cwd:
        Working directory for the subprocess.  ``None`` inherits the caller's
        current directory.  Used by ``OpenCodeBackend`` to run opencode inside
        a specific project directory.
    """

    def __init__(
        self,
        type: Backend,
        binary_path: str | None = None,
        api_key_source: str | None = None,
        env_overrides: dict[str, str] | None = None,
        timeout_seconds: int = 300,
        extra_args: list[str] | None = None,
        execwrap_path: str | None = None,
        rtk_path: str | None = None,
        stream_output: bool = False,
        idle_timeout_seconds: int | None = None,
        cwd: str | None = None,
        # OpenCode-specific: when False, do not override XDG_DATA_HOME and do
        # not seed auth from env. This allows using opencode's own OAuth/login.
        opencode_isolate_xdg: bool = True,
    ) -> None:
        self.type = type
        self.binary_path = binary_path
        self.api_key_source = api_key_source
        self.env_overrides: dict[str, str] = env_overrides or {}
        self.timeout_seconds = timeout_seconds
        self.extra_args: list[str] = extra_args or []
        self.execwrap_path = execwrap_path
        self.rtk_path = rtk_path
        self.stream_output = stream_output
        self.idle_timeout_seconds = idle_timeout_seconds
        self.cwd = cwd
        self.opencode_isolate_xdg = opencode_isolate_xdg


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
    files_accessed: list[str] = field(default_factory=list)
    """Files read/written by tool calls during this step."""
    auth_failed_snippet: str = ""
    """Literal opencode error line when OAuth/provider auth failed.
    Empty when no auth failure was detected. Set by OpencodeBackend.run."""

    def __post_init__(self) -> None:
        self.token_estimate = max(1, len(self.text) // 4)

    @property
    def ok(self) -> bool:
        if self.auth_failed:
            return False
        return self.exit_code == 0

    @property
    def timed_out(self) -> bool:
        return self.exit_code == 124

    @property
    def rate_limited(self) -> bool:
        return self.rate_limit_snippet != ""

    @property
    def auth_failed(self) -> bool:
        return self.auth_failed_snippet != ""

    @property
    def rate_limit_snippet(self) -> str:
        """Return the sentence/snippet that triggered rate-limit detection.

        Scans the model's text output only against unambiguous API-error
        phrases (``_RATE_LIMIT_TEXT_LITERALS``).  Short/generic phrases like
        "Rate Limited" are checked **only** against ``self.error`` (process
        stderr/error field) to avoid false positives when the model writes
        progress notes that reference historical rate-limit events.
        """

        def _find(haystack: str, literals: tuple[str, ...]) -> str:
            for literal in literals:
                idx = haystack.lower().find(literal.lower())
                if idx == -1:
                    continue
                start = idx
                end = idx + len(literal)
                line_start = haystack.rfind("\n", 0, start)
                line_end = haystack.find("\n", end)
                line_start = 0 if line_start == -1 else line_start + 1
                if line_end == -1:
                    line_end = len(haystack)
                snippet = haystack[line_start:line_end].strip()
                return (snippet or haystack[start:end].strip())[:500]
            return ""

        # Text output: only unambiguous, verbose API-error phrases.
        if self.text:
            hit = _find(self.text, _RATE_LIMIT_TEXT_LITERALS)
            if hit:
                return hit

        # Error field: all literals including short generic ones.
        if self.error:
            hit = _find(self.error, _RATE_LIMIT_ALL_LITERALS)
            if hit:
                return hit

        return ""

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


def _resolve_binary(binary_path: str | None, name: str) -> str:
    """Return an absolute path to the binary, raising if not found."""
    if binary_path:
        p = Path(binary_path)
        if p.exists() and p.is_file():
            return str(p)
        raise FileNotFoundError(f"{name} binary not found: {binary_path}")
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"{name} not found in PATH. Set binary_path in BackendConfig.")


def _resolve_api_key(source: str | None) -> str | None:
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


def _build_env(config: BackendConfig, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build the subprocess environment, merging overrides."""
    env = os.environ.copy()
    env.update(config.env_overrides)
    if extra:
        env.update(extra)
    return env


def _seed_opencode_auth(xdg_tmp: str) -> None:
    """Populate temp XDG auth from known persistent opencode auth locations.

    OpenCode stores provider/OAuth auth under XDG data directories. Ralph runs
    each call with an isolated temporary ``XDG_DATA_HOME`` to avoid sqlite lock
    contention, so we opportunistically merge any persistent auth.json files
    into the temp directory. Missing or malformed files are ignored.

    Per-provider merge strategy: for each provider key (openai, anthropic, ...)
    pick the candidate with the LATEST ``expires`` for OAuth entries. Non-OAuth
    entries (api-key) use last-seen wins. Prevents a stale ``~/.local/share``
    refresh token from clobbering a fresh snap-stored one just because it
    happens to sort later.
    """
    candidates: list[Path] = []

    current_xdg = os.environ.get("XDG_DATA_HOME")
    if current_xdg:
        candidates.append(Path(current_xdg) / "opencode" / "auth.json")

    candidates.append(Path.home() / ".local" / "share" / "opencode" / "auth.json")

    snap_roots = [Path.home() / "snap" / "code", Path.home() / "snap" / "code-insiders"]
    for snap_root in snap_roots:
        if not snap_root.exists():
            continue
        # Snap paths look like ~/snap/code/<rev>/.local/share/opencode/auth.json
        # (not ~/snap/code/<rev>/opencode/auth.json) — match the real layout.
        snap_auths = sorted(
            snap_root.glob("*/.local/share/opencode/auth.json"), reverse=True
        )
        candidates.extend(snap_auths)

    merged: dict[str, Any] = {}
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            incumbent = merged.get(key)
            if _is_fresher_auth(incumbent, value):
                merged[key] = value

    if not merged:
        return

    auth_dir = Path(xdg_tmp) / "opencode"
    auth_dir.mkdir(parents=True, exist_ok=True)
    (auth_dir / "auth.json").write_text(json.dumps(merged), encoding="utf-8")


def _is_fresher_auth(incumbent: Any, candidate: Any) -> bool:
    """Return True when ``candidate`` should replace ``incumbent`` in the merge.

    For OAuth entries (both sides have ``expires``) prefer the later expiry.
    For anything else (api-keys, missing incumbent) fall back to last-seen wins.
    """
    if incumbent is None:
        return True
    if not (isinstance(incumbent, dict) and isinstance(candidate, dict)):
        return True
    inc_exp = incumbent.get("expires")
    cand_exp = candidate.get("expires")
    if isinstance(inc_exp, (int, float)) and isinstance(cand_exp, (int, float)):
        return cand_exp > inc_exp
    return True


# Unambiguous auth-failure markers emitted by opencode on OAuth refresh /
# provider 401 / 403. Scanned against both stdout (``text``) and the raw
# subprocess output. Kept short and specific — a stray "401" in a scan result
# should not detonate the loop.
_AUTH_FAILURE_MARKERS: tuple[str, ...] = (
    "Token refresh failed",
    '"statusCode":401',
    '"statusCode":403',
    '"message":"Unauthorized"',
    '"message":"Forbidden"',
    '"name":"AuthError"',
)


def _detect_auth_failure(text: str, raw: bytes) -> str:
    """Return a short error message if opencode output indicates an auth failure.

    Returns empty string when no auth failure is detected. Matching is literal
    and limited to the narrow set of markers above to avoid false positives.
    """
    haystack = (text or "") + "\n" + raw.decode(errors="replace")
    for marker in _AUTH_FAILURE_MARKERS:
        idx = haystack.find(marker)
        if idx == -1:
            continue
        line_start = haystack.rfind("\n", 0, idx) + 1
        line_end = haystack.find("\n", idx)
        if line_end == -1:
            line_end = len(haystack)
        snippet = haystack[line_start:line_end].strip()
        if len(snippet) > 400:
            snippet = snippet[:400] + "…"
        return snippet
    return ""


def wrap_cmd(
    cmd: list[str],
    execwrap_path: str | None = None,
    rtk_path: str | None = None,
    *,
    shell_mode: bool = False,
) -> list[str]:
    """Apply execwrap and/or RTK wrapping to a command.

    execwrap supersedes RTK: it runs ``rtk rewrite`` internally on every shell
    command it processes, so a separate outer RTK prefix is redundant.

    shell_mode=False  (default) — execwrap launcher mode: ``[execwrap, cmd…]``
    shell_mode=True             — execwrap shell mode:    ``[execwrap, -c, "cmd string"]``

    When execwrap is absent, RTK is prepended directly.  The ``./`` prefix is
    stripped from the first token so RTK's dispatcher sees a plain binary name
    while all other arguments (including ``uv run``) are preserved.
    """
    if execwrap_path and Path(execwrap_path).exists():
        if shell_mode:
            import shlex as _shlex

            return [execwrap_path, "-c", _shlex.join(cmd)]
        return [execwrap_path] + cmd
    if rtk_path and Path(rtk_path).exists():
        first = cmd[0].lstrip("./") if cmd[0].startswith("./") else cmd[0]
        return [rtk_path, first, *cmd[1:]]
    return cmd


# Default idle-hang threshold: if no new bytes arrive for this many seconds,
# the process is considered hung and killed.  Generous enough for slow TTFT
# on large prompts (Kimi K2.5 can take 60-90s) but catches dead connections.
_IDLE_HANG_SECONDS = 900  # 15 minutes


def _sync_project_mcp_config(project_dir: str | None) -> Path | None:
    """Sync .langywrap/mcp.json into .mcp.json when present."""
    if not project_dir:
        return None
    repo = Path(project_dir)
    manifest = repo / ".langywrap" / "mcp.json"
    if not manifest.exists():
        return None
    try:
        from langywrap.mcp_config import sync_langywrap_mcp_manifest

        return sync_langywrap_mcp_manifest(repo)
    except Exception:
        return None


@dataclass
class _StreamResult:
    """Outcome of :func:`_run_with_idle_watchdog`."""

    raw: bytes
    exit_code: int
    error: str
    idle_timeout: bool
    duration: float


def _log_stream_event(obj: dict[str, Any]) -> None:
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
        texts: list[str] = []
        tool_names: list[str] = []
        for block in content:
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_names.append(block.get("name", "?"))
        preview = " ".join(texts)[:160]
        # Blank line before each assistant turn for visual separation
        if tool_names:
            tools_line = "  tools:\n" + "\n".join(f"    • {t}" for t in tool_names)
            logger.debug(
                "\n[stream] assistant — %d tool_use(s), %s tokens  text: %s\n%s",
                len(tool_names),
                out_tok,
                preview or "(none)",
                tools_line,
            )
        else:
            logger.debug(
                "\n[stream] assistant — %s tokens: %s",
                out_tok,
                preview,
            )

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
            "\n[stream] ── result ── %s turns  stop=%s  cost=$%s  %sms",
            turns,
            stop,
            cost,
            dur,
        )

    elif etype == "rate_limit_event":
        info = obj.get("rate_limit_info", {})
        status = info.get("status", "?")
        resets = info.get("resetsAt", "?")
        logger.debug("[stream] rate_limit — status=%s resets=%s", status, resets)

    else:
        # Unknown event — show type and first 120 chars of JSON
        logger.debug("[stream] %s.%s: %.120s", etype, subtype, json.dumps(obj))


def _print_stream_text(obj: dict[str, Any]) -> None:
    """Print human-readable text from a stream-json event to stdout.

    Handles both claude (stream-json) and opencode (--format json) event shapes.
    Only prints text content; ignores tool-use bookkeeping.
    """

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
_FILE_TOOLS = frozenset(
    {
        "Read",
        "Write",
        "Edit",
        "MultiEdit",
        "NotebookEdit",
        "read",
        "write",
        "edit",
        "view",
        "str_replace_based_edit_tool",
    }
)


def _extract_stream_stats(raw: bytes) -> tuple[int, int, list[str]]:
    """Parse a stream-json / opencode JSON byte stream and extract usage stats.

    Returns:
        (input_tokens, output_tokens, files_accessed)

    Token counts come from the ``result`` event (final totals) or the last
    ``assistant`` event usage block.  File paths come from ``tool_use`` blocks
    whose tool name is in ``_FILE_TOOLS``.
    """
    input_tokens = 0
    output_tokens = 0
    files: list[str] = []
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
        part = obj.get("part", {}) if isinstance(obj.get("part"), dict) else {}

        # Final result event — has total usage for the session.
        if etype == "result":
            usage = obj.get("usage", {})
            if usage:
                input_tokens = usage.get("input_tokens", input_tokens)
                output_tokens = usage.get("output_tokens", output_tokens)
            continue

        # OpenCode step-finish event — carries the clearest token totals.
        if etype == "step_finish":
            tokens = part.get("tokens", {}) if isinstance(part, dict) else {}
            if tokens:
                input_tokens = max(input_tokens, int(tokens.get("input", 0) or 0))
                output_tokens = max(output_tokens, int(tokens.get("output", 0) or 0))
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

        # OpenCode tool event with nested part/state input.
        if etype == "tool_use":
            tool_name = part.get("tool", "") if isinstance(part, dict) else ""
            if tool_name not in _FILE_TOOLS:
                continue
            state = part.get("state", {}) if isinstance(part, dict) else {}
            inp = state.get("input", {}) if isinstance(state, dict) else {}
            path = (
                inp.get("filePath")
                or inp.get("file_path")
                or inp.get("path")
                or inp.get("target_file")
            )
            if path and path not in seen_files:
                seen_files.add(path)
                files.append(path)

    return input_tokens, output_tokens, files


def _run_with_idle_watchdog(
    cmd: list[str],
    *,
    env: dict[str, str],
    timeout: int,
    idle_hang_seconds: int = _IDLE_HANG_SECONDS,
    stdin_data: bytes | None = None,
    use_setsid: bool = False,
    stream_output: bool = False,
    cwd: str | None = None,
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
    chunks: list[bytes] = []
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
            cwd=cwd,
        )
    except Exception as exc:
        return _StreamResult(
            raw=b"",
            exit_code=1,
            error=str(exc),
            idle_timeout=False,
            duration=time.monotonic() - t0,
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
                        # Truncate: raw/binary/garbled lines are rarely useful in full
                        logger.debug("[stream] (raw) %.120s", line)
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
                    elapsed,
                    cur_bytes,
                    int(idle_secs),
                )
            else:
                logger.info(
                    "[watchdog] %ds elapsed, %dB output, receiving data",
                    elapsed,
                    cur_bytes,
                )
            last_progress_log = now

        # Idle hang check
        if idle_secs >= idle_hang_seconds:
            idle_killed = True
            logger.info(
                "Idle watchdog: no output for %ds (threshold %ds) — killing process",
                int(idle_secs),
                idle_hang_seconds,
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
    parts: list[str] = []
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
        self,
        prompt: str,
        model: str,
        timeout: int,
        *,
        tools: list[str] | None = None,
    ) -> SubagentResult:
        effective_timeout = min(timeout, self.config.timeout_seconds)
        tool_args: list[str] = []
        if tools:
            tool_args = ["--allowedTools", ",".join(tools)]
        cmd = wrap_cmd(
            [
                self._binary,
                "--model",
                model,
                "--dangerously-skip-permissions",
                "--print",
                "--output-format",
                "stream-json",
                "--verbose",
                *tool_args,
                *self.config.extra_args,
            ],
            self.config.execwrap_path,
            self.config.rtk_path,
        )
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
        self,
        prompt: str,
        model: str,
        timeout: int,
        *,
        tools: list[str] | None = None,
    ) -> SubagentResult:
        effective_timeout = min(timeout, self.config.timeout_seconds)

        xdg_tmp: str | None = None
        try:
            _sync_project_mcp_config(self.config.cwd)
            if self.config.opencode_isolate_xdg:
                xdg_tmp = tempfile.mkdtemp(prefix="opencode_")
                _seed_opencode_auth(xdg_tmp)

            cmd = wrap_cmd(
                [
                    self._binary,
                    "run",
                    "--model",
                    model,
                    "--format",
                    "json",
                    *self.config.extra_args,
                ],
                self.config.execwrap_path,
                self.config.rtk_path,
            )

            overrides: dict[str, str] = {
                "__EXECWRAP_ACTIVE": "1",
                "SHELL": "/bin/bash",
            }
            if xdg_tmp is not None:
                overrides["XDG_DATA_HOME"] = xdg_tmp

            env = _build_env(self.config, overrides)

            sr = _run_with_idle_watchdog(
                cmd,
                env=env,
                timeout=effective_timeout,
                stdin_data=prompt.encode(),
                use_setsid=True,
                stream_output=self.config.stream_output,
                idle_hang_seconds=self.config.idle_timeout_seconds or _IDLE_HANG_SECONDS,
                cwd=self.config.cwd,
            )

            text = self._extract_text(sr.raw)
            in_tok, out_tok, files = _extract_stream_stats(sr.raw)
            auth_snippet = _detect_auth_failure(text, sr.raw)

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
                auth_failed_snippet=auth_snippet,
            )
        finally:
            if xdg_tmp is not None:
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
        parts: list[str] = []
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
        self,
        prompt: str,
        model: str,
        timeout: int,
        *,
        tools: list[str] | None = None,
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
        self,
        prompt: str,
        model: str,
        timeout: int,
        *,
        tools: list[str] | None = None,
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
        except ImportError as err:
            raise ImportError("Anthropic SDK not installed. Run: pip install anthropic") from err

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
        except ImportError as err:
            raise ImportError("OpenAI SDK not installed. Run: pip install openai") from err

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
        self,
        prompt: str,
        model: str,
        timeout: int,
        *,
        tools: list[str] | None = None,
    ) -> SubagentResult:
        effective_timeout = min(timeout, self.config.timeout_seconds)

        # The mock command: either from env override or echo the prompt
        mock_response = self.config.env_overrides.get("MOCK_RESPONSE", "")
        mock_command = self.config.env_overrides.get("MOCK_COMMAND", "")

        if mock_command:
            # Run an actual bash command (for security testing)
            cmd: list[str] = ["bash", "-c", mock_command]
        elif mock_response:
            # Echo a fixed response
            cmd = ["bash", "-c", f"echo {json.dumps(mock_response)}"]
        else:
            # Echo back the first line of the prompt as response
            first_line = prompt.split("\n")[0][:200]
            cmd = ["bash", "-c", f"echo 'MOCK_RESPONSE: {json.dumps(first_line)}'"]

        cmd = wrap_cmd(cmd, self.config.execwrap_path, self.config.rtk_path)

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
# ThinkingLoopBackend — multi-turn agentic loop with tool dispatch
# ---------------------------------------------------------------------------

_TLOOP_TOOL_PATTERN = re.compile(
    r"\[(?P<tag>SEARCH_WEB|RUN_CODE|LOAD_DATA|SEARCH_COMPLETE):\s*(?P<args>[^\]]*)\]"
    r"|"
    r"\[(?P<wtag>WRITE_CODE|WRITE_TEST):\s*(?P<wname>[^\]]+)\]\n(?P<wbody>.*?)\n\[/(?P=wtag)\]",
    re.DOTALL,
)

_TLOOP_PYPROJECT = """\
[project]
name = "analysis"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "numpy>=1.26",
    "pandas>=2.0",
    "matplotlib>=3.8",
    "seaborn>=0.13",
    "scipy>=1.11",
    "scikit-learn>=1.4",
    "plotly>=5.18",
    "statsmodels>=0.14",
    "pytest>=8.0",
    "kaleido>=0.2",
]
"""


def _tloop_parse_tool_calls(text: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for m in _TLOOP_TOOL_PATTERN.finditer(text):
        if m.group("tag"):
            calls.append({"type": m.group("tag"), "args": m.group("args").strip()})
        elif m.group("wtag"):
            calls.append(
                {
                    "type": m.group("wtag"),
                    "name": m.group("wname").strip(),
                    "body": m.group("wbody"),
                }
            )
    return calls


def _tloop_search_web(query: str) -> str:
    try:
        import httpx  # type: ignore
    except ImportError:
        return f"Search unavailable (httpx not installed): {query}"
    try:
        resp = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
            timeout=15,
        )
        data = resp.json()
        parts = []
        if data.get("AbstractText"):
            parts.append(f"**Summary**: {data['AbstractText']}")
        if data.get("AbstractURL"):
            parts.append(f"**Source**: {data['AbstractURL']}")
        for r in data.get("RelatedTopics", [])[:5]:
            if isinstance(r, dict) and r.get("Text"):
                parts.append(f"- {r['Text']}")
        return "\n".join(parts) if parts else f"No result for: {query}"
    except Exception as e:
        return f"Search failed: {e}"


def _tloop_write_code(filename: str, content: str, code_dir: Path) -> str:
    code_dir.mkdir(parents=True, exist_ok=True)
    (code_dir / filename).write_text(content)
    return f"Written: {code_dir / filename} ({len(content)} bytes)"


def _tloop_execute_code(
    filename: str,
    code_dir: Path,
    timeout: int = 60,
    use_docker: bool = False,
    docker_image: str = "superpowerbi-sandbox:latest",
    docker_network: str = "none",
) -> str:
    filepath = code_dir / filename
    if not filepath.exists():
        return f"ERROR: File not found: {filepath}"

    pyproject = code_dir / "pyproject.toml"
    if not pyproject.exists():
        pyproject.write_text(_TLOOP_PYPROJECT)

    if use_docker:
        output_dir = code_dir / "docker_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "docker",
            "run",
            "--rm",
            "--network",
            docker_network,
            "--memory",
            "2g",
            "--cpus",
            "2",
            "--read-only",
            "--tmpfs",
            "/tmp:size=500m",
            "-v",
            f"{code_dir.resolve()}:/code:ro",
            "-v",
            f"{output_dir.resolve()}:/outputs:rw",
            docker_image,
            "uv",
            "run",
            f"/code/{filepath.name}",
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
            return (
                f"DOCKER EXIT {r.returncode}\n"
                f"STDOUT:\n{r.stdout[:4000]}\n"
                f"STDERR:\n{r.stderr[:2000]}"
            )
        except subprocess.TimeoutExpired:
            return f"DOCKER TIMEOUT after {timeout}s"
        except Exception as e:
            return f"DOCKER ERROR: {e}"
    else:
        try:
            r = subprocess.run(
                ["uv", "run", "--project", str(code_dir), str(filepath)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(code_dir),
            )
            out = r.stdout[:4000] if r.stdout else ""
            err = r.stderr[:2000] if r.stderr else ""
            if r.returncode == 0:
                return f"EXIT 0\nSTDOUT:\n{out}"
            return f"EXIT {r.returncode}\nSTDOUT:\n{out}\nSTDERR:\n{err}"
        except subprocess.TimeoutExpired:
            return f"TIMEOUT after {timeout}s"
        except FileNotFoundError:
            return "ERROR: uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"


def _tloop_run_tests(code_dir: Path, timeout: int = 60) -> str:
    try:
        r = subprocess.run(
            ["uv", "run", "--project", str(code_dir), "pytest", "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(code_dir),
        )
        return f"PYTEST EXIT {r.returncode}\n{(r.stdout + r.stderr)[:5000]}"
    except subprocess.TimeoutExpired:
        return "PYTEST TIMEOUT"
    except Exception as e:
        return f"PYTEST ERROR: {e}"


class ThinkingLoopBackendConfig(BackendConfig):
    """
    Configuration for the multi-turn ThinkingLoopBackend.

    Parameters
    ----------
    system_prompt:
        System prompt injected at the start of every loop conversation.
    max_rounds:
        Maximum number of LLM call→tool-dispatch iterations.
    use_docker:
        Run generated code inside a Docker sandbox (no network, read-only input).
    docker_image:
        Docker image tag for the sandbox.
    docker_network:
        Docker network mode (``"none"`` = no internet).
    working_dir:
        Directory where generated code files are written.  A temporary directory
        is created (and later deleted) when ``None``.
    on_progress:
        Optional callback invoked at key loop events.  Receives an event name
        and a data dict.  Events:

        ``"round_start"``   — ``{"round": int}``
        ``"model_output"``  — ``{"round": int, "text": str}``
        ``"tool_call"``     — ``{"type": str, "args": str}`` or
                              ``{"type": str, "name": str}`` for write calls
        ``"complete"``      — ``{"reason": "analysis_complete"|"no_tools"|"max_rounds"}``
    """

    def __init__(
        self,
        *,
        system_prompt: str = "",
        max_rounds: int = 12,
        use_docker: bool = False,
        docker_image: str = "superpowerbi-sandbox:latest",
        docker_network: str = "none",
        working_dir: Path | str | None = None,
        on_progress: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(type=Backend.THINKING_LOOP, **kwargs)
        self.system_prompt = system_prompt
        self.max_rounds = max_rounds
        self.use_docker = use_docker
        self.docker_image = docker_image
        self.docker_network = docker_network
        self.working_dir: Path | None = Path(working_dir) if working_dir else None
        self.on_progress = on_progress  # Callable[[str, dict], None] | None


class ThinkingLoopBackend:
    """
    Multi-turn agentic loop backend (Anthropic SDK).

    Runs a tool-call parse-and-dispatch loop:
      1. Send the initial prompt to Claude.
      2. Parse ``[TOOL_NAME: …]`` tags from the response.
      3. Execute tools: web search, code write/run.
      4. Feed results back and repeat until ``[ANALYSIS_COMPLETE]``
         or ``max_rounds`` is reached.

    The ``run()`` call blocks until the loop finishes and returns a single
    ``SubagentResult`` whose ``text`` field contains the final model output.

    Requires the ``anthropic`` package (``pip install anthropic``).
    """

    def __init__(self, config: BackendConfig) -> None:
        if not isinstance(config, ThinkingLoopBackendConfig):
            raise TypeError(
                "ThinkingLoopBackend requires ThinkingLoopBackendConfig, "
                f"got {type(config).__name__}"
            )
        self.config: ThinkingLoopBackendConfig = config  # type: ignore[assignment]

        # Resolve API key: env_overrides take priority over api_key_source lookup.
        api_key = ""
        if config.api_key_source:
            api_key = os.environ.get(config.api_key_source, "")
        api_key = config.env_overrides.get("ANTHROPIC_API_KEY", api_key) or api_key
        self._api_key = api_key

    def run(
        self,
        prompt: str,
        model: str,
        timeout: int,
        *,
        tools: list[str] | None = None,
    ) -> SubagentResult:
        import time

        start = time.monotonic()
        own_dir = False
        working_dir = self.config.working_dir

        if working_dir is None:
            working_dir = Path(tempfile.mkdtemp(prefix="tloop_"))
            own_dir = True

        code_dir = working_dir / "code"
        code_dir.mkdir(parents=True, exist_ok=True)

        try:
            text, files = self._run_loop(prompt, model, code_dir)
            return SubagentResult(
                text=text,
                exit_code=0,
                duration_seconds=time.monotonic() - start,
                model_used=model,
                backend_used=Backend.THINKING_LOOP,
                files_accessed=files,
            )
        except Exception as e:
            return SubagentResult(
                text="",
                exit_code=1,
                duration_seconds=time.monotonic() - start,
                model_used=model,
                backend_used=Backend.THINKING_LOOP,
                error=str(e),
            )
        finally:
            if own_dir and working_dir is not None:
                import shutil as _shu

                _shu.rmtree(working_dir, ignore_errors=True)

    def _run_loop(
        self,
        prompt: str,
        model: str,
        code_dir: Path,
    ) -> tuple[str, list[str]]:
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "anthropic package required for ThinkingLoopBackend: pip install anthropic"
            ) from exc

        client = anthropic.Anthropic(api_key=self._api_key)
        messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]
        files_accessed: list[str] = []
        final_text = ""
        emit = self.config.on_progress  # Callable[[str, dict], None] | None

        for round_num in range(self.config.max_rounds):
            if emit:
                emit("round_start", {"round": round_num})

            response = client.messages.create(
                model=model,
                max_tokens=8192,
                system=self.config.system_prompt,
                messages=messages,
            )
            assistant_text = response.content[0].text
            messages.append({"role": "assistant", "content": assistant_text})
            final_text = assistant_text

            if emit:
                emit("model_output", {"round": round_num, "text": assistant_text})

            if "[ANALYSIS_COMPLETE]" in assistant_text:
                if emit:
                    emit("complete", {"reason": "analysis_complete"})
                break

            tool_calls = _tloop_parse_tool_calls(assistant_text)
            if not tool_calls:
                if emit:
                    emit("complete", {"reason": "no_tools"})
                break

            results: list[str] = []
            for call in tool_calls:
                ctype = call["type"]
                if ctype == "SEARCH_WEB":
                    if emit:
                        emit("tool_call", {"type": ctype, "args": call["args"]})
                    r = _tloop_search_web(call["args"])
                    results.append(f"[SEARCH_RESULT: {call['args']}]\n{r}\n[/SEARCH_RESULT]")
                elif ctype in ("WRITE_CODE", "WRITE_TEST"):
                    if emit:
                        emit("tool_call", {"type": ctype, "name": call["name"]})
                    r = _tloop_write_code(call["name"], call["body"], code_dir)
                    files_accessed.append(str(code_dir / call["name"]))
                    results.append(f"[WRITE_RESULT: {call['name']}]\n{r}\n[/WRITE_RESULT]")
                elif ctype == "RUN_CODE":
                    fname = call["args"]
                    if emit:
                        emit("tool_call", {"type": ctype, "args": fname})
                    test_file = code_dir / f"test_{fname}"
                    if test_file.exists():
                        tr = _tloop_run_tests(code_dir)
                        results.append(f"[TEST_RESULT: test_{fname}]\n{tr}\n[/TEST_RESULT]")
                    r = _tloop_execute_code(
                        fname,
                        code_dir,
                        use_docker=self.config.use_docker,
                        docker_image=self.config.docker_image,
                        docker_network=self.config.docker_network,
                    )
                    results.append(f"[EXEC_RESULT: {fname}]\n{r}\n[/EXEC_RESULT]")
                elif ctype == "LOAD_DATA":
                    if emit:
                        emit("tool_call", {"type": ctype, "args": call["args"]})
                    results.append(
                        f"[DATA_INFO: {call['args']}]\n"
                        f"Dataset at {call['args']} — reference this path in your code.\n"
                        f"[/DATA_INFO]"
                    )
                elif ctype == "SEARCH_COMPLETE":
                    if emit:
                        emit("tool_call", {"type": ctype, "args": ""})
                    results.append(
                        "[SEARCH_COMPLETE_ACK]\nSearch phase complete.\n[/SEARCH_COMPLETE_ACK]"
                    )

            if results:
                messages.append({"role": "user", "content": "\n\n".join(results)})
        else:
            # Exhausted max_rounds without break
            if emit:
                emit("complete", {"reason": "max_rounds"})

        return final_text, files_accessed


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_backend(
    config: BackendConfig,
) -> (
    ClaudeBackend
    | OpenCodeBackend
    | OpenRouterBackend
    | DirectAPIBackend
    | MockBackend
    | ThinkingLoopBackend
):
    """Instantiate the correct backend class from a BackendConfig."""
    mapping = {
        Backend.CLAUDE: ClaudeBackend,
        Backend.OPENCODE: OpenCodeBackend,
        Backend.OPENROUTER: OpenRouterBackend,
        Backend.DIRECT_API: DirectAPIBackend,
        Backend.MOCK: MockBackend,
        Backend.THINKING_LOOP: ThinkingLoopBackend,
    }
    cls = mapping.get(config.type)
    if cls is None:
        raise ValueError(f"Unknown backend type: {config.type}")
    return cls(config)
