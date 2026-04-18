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

import json
import stat
import textwrap
from pathlib import Path

import pytest
from langywrap.router.backends import Backend, BackendConfig, OpenCodeBackend

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
    shim.write_text(
        textwrap.dedent("""\
        #!/usr/bin/env bash
        # Ignore all flags (--model, --format, etc.) — just read stdin.
        prompt=$(cat)
        # Emit a single JSON text event with the prompt as content.
        printf '{"type":"text","text":"%s"}\\n' "$prompt"
    """)
    )
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
        spy_shim.write_text(
            textwrap.dedent(f"""\
            #!/usr/bin/env bash
            # Log all positional args to a file
            printf '%s\\n' "$@" > {log_file}
            # Still consume stdin and emit JSON so the backend is happy
            prompt=$(cat)
            printf '{{"type":"text","text":"ok"}}\\n'
        """)
        )
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
        raw = (
            b'{"type":"assistant","message":{"content":[{"type":"text","text":"Response here"}]}}\n'
        )
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


class TestProjectMcpConfig:
    def test_opencode_syncs_langywrap_mcp_and_runtime_can_launch_server(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".langywrap").mkdir()

        server_script = repo / "mcp_server.py"
        server_script.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import sys\n\n"
            "def send(obj):\n"
            "    sys.stdout.write(json.dumps(obj) + '\\n')\n"
            "    sys.stdout.flush()\n\n"
            "while True:\n"
            "    line = sys.stdin.readline()\n"
            "    if not line:\n"
            "        break\n"
            "    req = json.loads(line)\n"
            "    method = req.get('method')\n"
            "    if method == 'initialize':\n"
            "        send({'jsonrpc': '2.0', 'id': req['id'], 'result': {'protocolVersion': req['params']['protocolVersion'], 'capabilities': {'tools': {'listChanged': False}}, 'serverInfo': {'name': 'dummy', 'version': '1.0'}}})\n"
            "    elif method == 'tools/list':\n"
            "        send({'jsonrpc': '2.0', 'id': req['id'], 'result': {'tools': [{'name': 'dummy_lookup', 'description': 'Dummy MCP tool', 'inputSchema': {'type': 'object', 'properties': {}}}]}})\n"
            "    elif method == 'notifications/initialized':\n"
            "        continue\n"
            "    else:\n"
            "        send({'jsonrpc': '2.0', 'id': req.get('id'), 'result': {}})\n",
            encoding="utf-8",
        )
        server_script.chmod(server_script.stat().st_mode | stat.S_IEXEC)

        manifest = repo / ".langywrap" / "mcp.json"
        manifest.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "lawy": {
                            "command": "python3",
                            "args": [str(server_script)],
                        }
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        shim = repo / "opencode"
        shim.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import pathlib
                import subprocess
                import sys

                repo = pathlib.Path.cwd()
                cfg = json.loads((repo / "opencode.json").read_text(encoding="utf-8"))
                srv = cfg["mcp"]["lawy"]
                env = os.environ.copy()
                env.update(srv.get("environment", {}))
                proc = subprocess.Popen(
                    srv["command"],
                    cwd=str(repo),
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    text=True,
                )
                proc.stdin.write(json.dumps({
                    "jsonrpc": "2.0",
                    "id": 0,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "opencode", "version": "1.3.17"},
                    },
                }) + "\\n")
                proc.stdin.flush()
                init = json.loads(proc.stdout.readline())
                proc.stdin.write(json.dumps({
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }) + "\\n")
                proc.stdin.write(json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {},
                }) + "\\n")
                proc.stdin.flush()
                tools = json.loads(proc.stdout.readline())
                proc.terminate()
                proc.wait(timeout=5)
                text = "mcp=" + init["result"]["serverInfo"]["name"] + "/" + tools["result"]["tools"][0]["name"]
                print(json.dumps({"type": "text", "text": text}))
                """
            ),
            encoding="utf-8",
        )
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)

        config = BackendConfig(
            type=Backend.OPENCODE,
            binary_path=str(shim),
            timeout_seconds=10,
            cwd=str(repo),
            opencode_isolate_xdg=False,
        )
        backend = OpenCodeBackend(config)

        result = backend.run("hello", "test-model", timeout=10)

        assert result.ok
        assert result.text == "mcp=dummy/dummy_lookup"
        synced = json.loads((repo / "opencode.json").read_text(encoding="utf-8"))
        assert synced["mcp"]["lawy"]["type"] == "local"
        assert synced["mcp"]["lawy"]["command"][0] == "python3"
