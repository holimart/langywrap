"""langywrap — universal AI agent orchestration toolkit.

Provides execution security, ralph loop orchestration, quality gates,
compound engineering, project templating, and an execution router for
AI coding tools. Wraps and orchestrates Claude, OpenCode/Kimi, ChatGPT,
and other models.
"""

__version__ = "0.1.2"

# Convenience exports
from .tagged_tools import ToolTag, parse_tool_tags

__all__ = [
    "ToolTag",
    "parse_tool_tags",
]
