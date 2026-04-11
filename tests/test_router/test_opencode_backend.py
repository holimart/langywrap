"""Tests for OpenCodeBackend — verifies prompt delivery via stdin.

The critical bug (fixed in this patch): OpenCodeBackend passed the prompt
as a positional CLI argument instead of piping it via stdin.  This caused:

  1. Bash comment truncation: prompts starting with ``# ...`` were silently
     truncated when the shell interpreted ``#`` as a comment delimiter.
  2. ARG_MAX overflow: large prompts (>128KB) hit OS argument length limits.
  3. Shell metacharacter corruption: ``$``, backticks, quotes, etc. were
     interpreted by the shell instead of passed verbatim.

These tests use a small ``cat`` shim in place of the real ``opencode``
binary so they run without network access or API keys.
"""

from __future__ import annotations

import os
import stat
import textwrap
from pathlib import Path

import pytest

from langywrap.router.backends import BackendConfig, Backend, OpenCodeBackend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cat_shim(tmp_path: Path) -> str:
    """Create a tiny script that acts like ``opencode run`` but just cats stdin.

    Outputs the prompt wrapped in a JSON event so _extract_text picks it up,
    exactly like the real opencode ``--format json`` output.
    """
    shim = tmp_path / "opencode"
    shim.write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        # Ignore all flags (--model, --format, etc.) — just read stdin.
        prompt=$(cat)
        # Emit a single JSON text event with the prompt as content.
        printf '{"type":"text","text":"%s"}\\n' "$prompt"
    """))
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return str(shim)


@pytest.fixture
def opencode_config(cat_shim: str) -> BackendConfig:
    return BackendConfig(
        type=Backend.OPENCODE,
        binary_path=cat_shim,
        timeout_seconds=10,
    )


@pytest.fixture
def opencode_backend(opencode_config: BackendConfig) -> OpenCodeBackend:
    return OpenCodeBackend(opencode_config)


# ---------------------------------------------------------------------------
# Prompt delivery tests — the core regression suite
# ---------------------------------------------------------------------------


class TestPromptDeliveryViaStdin:
    """Verify the prompt reaches the subprocess intact via stdin."""

    def test_simple_prompt(self, opencode_backend: OpenCodeBackend) -> None:
        result = opencode_backend.run("Hello world", "test-model", timeout=10)
        assert result.ok
        assert "Hello world" in result.text

    def test_prompt_with_leading_hash(self, opencode_backend: OpenCodeBackend) -> None:
        """Regression: ``# Project Context`` was truncated by bash comment interpretation."""
        prompt = "# Project Context\n\nThis is the full prompt with instructions."
        result = opencode_backend.run(prompt, "test-model", timeout=10)
        assert result.ok
        assert "Project Context" in result.text
        assert "full prompt with instructions" in result.text

    def test_prompt_with_multiple_hashes(self, opencode_backend: OpenCodeBackend) -> None:
        prompt = "# Header 1\n## Header 2\n### Header 3\nBody text here."
        result = opencode_backend.run(prompt, "test-model", timeout=10)
        assert result.ok
        assert "Header 1" in result.text
        assert "Header 3" in result.text
        assert "Body text" in result.text

    def test_prompt_with_shell_metacharacters(self, opencode_backend: OpenCodeBackend) -> None:
        """Dollar signs, backticks, quotes must not be interpreted by the shell."""
        prompt = 'echo $HOME; `whoami`; "quoted"; $(cat /etc/passwd)'
        result = opencode_backend.run(prompt, "test-model", timeout=10)
        assert result.ok
        # The literal text must appear, not the expanded values
        assert "$HOME" in result.text
        assert "`whoami`" in result.text

    def test_large_prompt_no_truncation(self, opencode_backend: OpenCodeBackend) -> None:
        """Prompts larger than typical ARG_MAX (~128KB) must arrive intact."""
        # 200KB of repeated text — would fail E2BIG as a positional arg
        prompt = "Line of research context.\n" * 10_000
        assert len(prompt) > 200_000
        result = opencode_backend.run(prompt, "test-model", timeout=10)
        assert result.ok
        # The shim echoes back the prompt; verify size is in the ballpark
        assert len(result.text) > 100_000

    def test_prompt_not_in_command_args(self, cat_shim: str, tmp_path: Path) -> None:
        """Verify the prompt is NOT passed as a positional argument.

        We use a shim that logs its own ``$@`` to a file, then check that
        the prompt text does not appear in the argument list.
        """
        log_file = tmp_path / "args.log"
        spy_shim = tmp_path / "opencode_spy"
        spy_shim.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env bash
            # Log all positional args to a file
            printf '%s\\n' "$@" > {log_file}
            # Still consume stdin and emit JSON so the backend is happy
            prompt=$(cat)
            printf '{{"type":"text","text":"ok"}}\\n'
        """))
        spy_shim.chmod(spy_shim.stat().st_mode | stat.S_IEXEC)

        config = BackendConfig(
            type=Backend.OPENCODE,
            binary_path=str(spy_shim),
            timeout_seconds=10,
        )
        backend = OpenCodeBackend(config)
        secret_marker = "SECRET_PROMPT_MARKER_12345"
        backend.run(secret_marker, "test-model", timeout=10)

        args_logged = log_file.read_text()
        assert secret_marker not in args_logged, (
            "Prompt was passed as a positional argument instead of stdin! "
            f"Args logged: {args_logged[:500]}"
        )


# ---------------------------------------------------------------------------
# _extract_text unit tests
# ---------------------------------------------------------------------------


class TestExtractText:
    """Verify JSON event stream parsing."""

    def test_text_event(self) -> None:
        raw = b'{"type":"text","text":"Hello from model"}\n'
        assert OpenCodeBackend._extract_text(raw) == "Hello from model"

    def test_assistant_message_event(self) -> None:
        raw = b'{"type":"assistant","message":{"content":[{"type":"text","text":"Response here"}]}}\n'
        assert OpenCodeBackend._extract_text(raw) == "Response here"

    def test_multiple_events_concatenated(self) -> None:
        raw = (
            b'{"type":"step_start","timestamp":123}\n'
            b'{"type":"text","text":"Part 1 "}\n'
            b'{"type":"text","text":"Part 2"}\n'
            b'{"type":"step_finish","timestamp":456}\n'
        )
        assert OpenCodeBackend._extract_text(raw) == "Part 1 Part 2"

    def test_fallback_to_raw_when_no_json(self) -> None:
        raw = b"Plain text output without JSON\n"
        assert "Plain text output" in OpenCodeBackend._extract_text(raw)

    def test_empty_input(self) -> None:
        assert OpenCodeBackend._extract_text(b"") == ""
