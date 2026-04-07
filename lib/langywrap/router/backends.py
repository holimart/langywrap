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
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


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
    ) -> None:
        self.type = type
        self.binary_path = binary_path
        self.api_key_source = api_key_source
        self.env_overrides: Dict[str, str] = env_overrides or {}
        self.timeout_seconds = timeout_seconds
        self.extra_args: List[str] = extra_args or []
        self.execwrap_path = execwrap_path


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
        """API hang: timed out AND produced very little output."""
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


# ---------------------------------------------------------------------------
# ClaudeBackend
# ---------------------------------------------------------------------------


class ClaudeBackend:
    """
    Runs ``claude --print`` with prompt piped to stdin.

    Notes
    -----
    - Uses stdin pipe (not ``-p``) to avoid ARG_MAX (E2BIG) on large prompts.
    - Sets ``__EXECWRAP_ACTIVE=1`` and ``-u CLAUDECODE`` to prevent recursive
      invocation inside claude hooks.
    - ``--dangerously-skip-permissions`` is intentional: the surrounding
      execwrap/secrity layer is the enforcement boundary.
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
                *tool_args,
                *self.config.extra_args,
            ],
            self.config.execwrap_path,
        )
        env = _build_env(
            self.config,
            {
                "__EXECWRAP_ACTIVE": "1",
            },
        )
        # Unset CLAUDECODE to prevent recursive invocation detection
        env.pop("CLAUDECODE", None)

        t0 = time.monotonic()
        raw = b""
        exit_code = 0
        error_msg = ""
        try:
            proc = subprocess.run(
                cmd,
                input=prompt.encode(),
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
            backend_used=Backend.CLAUDE,
            raw_output=raw,
            error=error_msg,
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
                    prompt,
                ],
                self.config.execwrap_path,
            )

            # Use setsid for process-group isolation
            setsid_cmd = ["setsid"] + cmd

            env = _build_env(
                self.config,
                {
                    "__EXECWRAP_ACTIVE": "1",
                    "XDG_DATA_HOME": xdg_tmp,
                    "SHELL": "/bin/bash",
                },
            )

            t0 = time.monotonic()
            raw = b""
            exit_code = 0
            error_msg = ""
            try:
                proc = subprocess.run(
                    setsid_cmd,
                    stdin=subprocess.DEVNULL,
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
            text = self._extract_text(raw)

            return SubagentResult(
                text=text,
                exit_code=exit_code,
                duration_seconds=duration,
                model_used=model,
                backend_used=Backend.OPENCODE,
                raw_output=raw,
                error=error_msg,
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
            payload = {
                "model": model,
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

        # Apply RTK if configured
        rtk_path = self.config.env_overrides.get("RTK_PATH", "")
        if rtk_path and Path(rtk_path).exists():
            # RTK wraps the command to compress output
            cmd = [rtk_path, "--"] + cmd

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
