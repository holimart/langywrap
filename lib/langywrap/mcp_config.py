"""Helpers for project-level MCP server registration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _manifest_to_opencode_mcp(manifest_servers: dict[str, Any]) -> dict[str, Any]:
    translated: dict[str, Any] = {}
    for name, entry in manifest_servers.items():
        command = entry.get("command")
        args = entry.get("args", [])
        env = entry.get("env")
        timeout = entry.get("timeout")
        if not isinstance(command, str):
            raise ValueError(f"MCP server {name!r} is missing string 'command'")
        item: dict[str, Any] = {
            "type": "local",
            "command": [command, *list(args)],
            "enabled": True,
        }
        if env:
            item["environment"] = env
        if timeout:
            item["timeout"] = timeout
        translated[name] = item
    return translated


def register_mcp_server(
    config_path: Path,
    *,
    name: str,
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = _read_json(config_path)
    servers = data.setdefault("mcpServers", {})
    entry: dict[str, Any] = {"command": command}
    if args:
        entry["args"] = args
    if env:
        entry["env"] = env
    servers[name] = entry
    _write_json(config_path, data)
    return data


def sync_langywrap_mcp_manifest(repo_path: Path) -> Path:
    manifest_path = repo_path / ".langywrap" / "mcp.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    manifest = _read_json(manifest_path)
    servers = manifest.get("mcpServers")
    if not isinstance(servers, dict):
        raise ValueError(".langywrap/mcp.json must contain an object at key 'mcpServers'")

    out_path = repo_path / "opencode.json"
    out = _read_json(out_path)
    out_mcp = out.setdefault("mcp", {})
    out_mcp.update(_manifest_to_opencode_mcp(servers))
    _write_json(out_path, out)
    return out_path
