"""Generic square-bracket tool tag parsing.

Shared utility for projects using the pattern:

  [TOOL_NAME: args]

This is intentionally small and dependency-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolTag:
    name: str
    args: str


_DEFAULT_RE = re.compile(r"\[(?P<name>[A-Z0-9_]+):\s*(?P<args>.+?)\]", re.DOTALL)


def parse_tool_tags(text: str, *, allowed: set[str] | None = None) -> list[ToolTag]:
    """Parse `[NAME: args]` tags from text.

    Args:
        text: Raw model output.
        allowed: Optional allowlist of tool names.
    """
    if not text:
        return []
    out: list[ToolTag] = []
    for m in _DEFAULT_RE.finditer(text):
        name = (m.group("name") or "").strip()
        args = (m.group("args") or "").strip()
        if not name or not args:
            continue
        if allowed is not None and name not in allowed:
            continue
        out.append(ToolTag(name=name, args=args))
    return out
