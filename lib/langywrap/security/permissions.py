"""
langywrap.security.permissions — Config models, loading, merging, and matching.

Key design decisions vs. the original intercept-enhanced.py:
  - load_permissions() walks the full config hierarchy instead of stopping at
    the first file found (first-found-wins bug).
  - merge_permissions() applies a strict priority rule: a DENY at any level
    is final — project config cannot un-deny a system-level denial.
  - match_pattern() preserves the original cmd:arg / cmd:* / regex: semantics
    while handling the wildcard-only shorthand (no colon).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class PermissionRule(BaseModel):
    """A single permission rule loaded from permissions.yaml."""

    pattern: str
    reason: Optional[str] = None
    message: Optional[str] = None
    suggestion: Optional[str] = None
    alternatives: Optional[List[str]] = None
    # action is stored redundantly for rules that live in the flat 'custom' list
    action: Optional[str] = None  # "deny" | "ask" | "allow"

    model_config = ConfigDict(extra="allow")


class PermissionsConfig(BaseModel):
    """Parsed contents of a permissions.yaml file."""

    version: str = "1.0"
    mode: str = "restrictive"  # restrictive | permissive | paranoid
    deny: List[PermissionRule] = Field(default_factory=list)
    ask: List[PermissionRule] = Field(default_factory=list)
    allow: List[PermissionRule] = Field(default_factory=list)

    # source path — set after loading; not part of the YAML schema
    _source: Optional[Path] = None

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------

def _parse_command(command: str) -> Tuple[str, str]:
    """Return (program, args_string) from a shell command string."""
    parts = command.split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def match_pattern(command: str, pattern: str) -> bool:
    """
    Return True when *command* matches *pattern*.

    Pattern formats
    ---------------
    ``cmd``          — matches when the command program equals ``cmd``
                       (no colon ⇒ wildcard args)
    ``cmd:*``        — same as above, explicit wildcard
    ``cmd:arg``      — command program equals ``cmd`` AND args contain ``arg``
    ``regex:<expr>`` — full-command regex match (case-insensitive)
    ``*``            — matches everything
    """
    command = command.strip()
    if not command:
        return False

    # Full-command regex
    if pattern.startswith("regex:"):
        expr = pattern[6:]
        return bool(re.search(expr, command, re.IGNORECASE))

    # Split on first colon only
    if ":" in pattern:
        cmd_pattern, arg_pattern = pattern.split(":", 1)
    else:
        cmd_pattern = pattern
        arg_pattern = "*"

    prog, args_str = _parse_command(command)

    # Match program name — prefix match so "mkfs" catches "mkfs.ext4"
    if cmd_pattern != "*":
        if prog != cmd_pattern and not prog.startswith(cmd_pattern + ".") and not prog.startswith(cmd_pattern + "/"):
            return False

    # Match arguments
    if arg_pattern == "*":
        return True

    # Regex match inside args (cmd:regex:expr format)
    if arg_pattern.startswith("regex:"):
        expr = arg_pattern[6:]
        return bool(re.search(expr, args_str, re.IGNORECASE))

    # Substring match inside the args string
    return arg_pattern in args_str


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_CONFIG_FILENAME = "permissions.yaml"

# Default bundled config lives next to this file
_BUNDLED_DEFAULTS = Path(__file__).parent / "defaults" / _CONFIG_FILENAME


def _load_yaml(path: Path) -> PermissionsConfig:
    """Parse a single permissions.yaml into a PermissionsConfig."""
    with path.open("r") as fh:
        raw = yaml.safe_load(fh) or {}

    def _rules(key: str) -> List[PermissionRule]:
        return [PermissionRule(**r) for r in (raw.get(key) or [])]

    deny_rules = _rules("deny")

    # Integrate data_theft_prevention into deny rules if present
    dtp = raw.get("data_theft_prevention")
    if dtp and dtp.get("enabled", False):
        for sf in dtp.get("sensitive_files") or []:
            deny_rules.append(PermissionRule(
                pattern=f"regex:(?:cat|head|tail|less|more|cp|scp|rsync)\\s+.*{re.escape(sf['pattern'].replace('**/', ''))}",
                reason=sf.get("reason", "Sensitive file access"),
                message=sf.get("message", ""),
                suggestion=sf.get("suggestion", ""),
            ))
        for bd in dtp.get("blocked_destinations") or []:
            deny_rules.append(PermissionRule(
                pattern=f"regex:(?:curl|wget|http|nc)\\s+.*{re.escape(bd['domain'])}",
                reason=bd.get("reason", "Blocked destination"),
                message=bd.get("message", ""),
                suggestion=bd.get("suggestion", ""),
            ))
        for bp in dtp.get("blocked_patterns") or []:
            # Convert "base64:*.env" → regex matching "base64 ... .env"
            parts = bp["pattern"].split(":", 1)
            if len(parts) == 2:
                cmd_part, file_part = parts
                file_glob = file_part.replace("*", ".*")
                deny_rules.append(PermissionRule(
                    pattern=f"regex:{re.escape(cmd_part)}\\s+.*{file_glob}",
                    reason=bp.get("reason", "Blocked pattern"),
                    message=bp.get("message", ""),
                    suggestion=bp.get("suggestion", ""),
                ))

    cfg = PermissionsConfig(
        version=str(raw.get("version", "1.0")),
        mode=str(raw.get("mode", "restrictive")),
        deny=deny_rules,
        ask=_rules("ask"),
        allow=_rules("allow"),
    )
    cfg._source = path
    return cfg


def load_permissions(project_dir: Path) -> PermissionsConfig:
    """
    Load and merge all permissions configs in the hierarchy.

    Search order (lowest → highest priority):
      1. Bundled defaults   (langywrap package)
      2. Project-local      (<project_dir>/.langywrap/permissions.yaml)
      3. System-wide        (~/.langywrap/permissions.yaml)

    All found files are merged via merge_permissions().
    """
    candidates: List[Path] = []

    if _BUNDLED_DEFAULTS.exists():
        candidates.append(_BUNDLED_DEFAULTS)

    project_cfg = project_dir / ".langywrap" / _CONFIG_FILENAME
    if project_cfg.exists():
        candidates.append(project_cfg)

    system_cfg = Path.home() / ".langywrap" / _CONFIG_FILENAME
    if system_cfg.exists():
        candidates.append(system_cfg)

    if not candidates:
        return PermissionsConfig()

    configs = [_load_yaml(p) for p in candidates]
    return merge_permissions(*configs)


# ---------------------------------------------------------------------------
# Config merging — the critical fix over the original interceptor
# ---------------------------------------------------------------------------

def merge_permissions(*configs: PermissionsConfig) -> PermissionsConfig:
    """
    Merge multiple PermissionsConfig objects into one.

    Rules
    -----
    * **DENY wins at any level.**  If a pattern is denied in *any* config
      (system, project, or defaults) it remains denied in the merged result.
      A project config cannot remove a system-level denial.
    * **ASK** rules from all configs are unioned.  A deny rule for the same
      pattern still beats an ask rule.
    * **ALLOW** rules from all configs are unioned, but are superseded by any
      matching deny or ask rule.
    * The ``mode`` from the last (highest-priority) config wins.
    * The ``version`` from the last config wins.

    This fixes the first-found-wins bug in the original interceptor where
    ``load_permissions_config()`` returned after the first file it discovered,
    meaning system-level denials could be silently skipped if a project config
    happened to be found first.
    """
    if not configs:
        return PermissionsConfig()

    merged_deny: List[PermissionRule] = []
    merged_ask: List[PermissionRule] = []
    merged_allow: List[PermissionRule] = []

    seen_deny_patterns: set[str] = set()
    seen_ask_patterns: set[str] = set()
    seen_allow_patterns: set[str] = set()

    for cfg in configs:
        for rule in cfg.deny:
            if rule.pattern not in seen_deny_patterns:
                merged_deny.append(rule)
                seen_deny_patterns.add(rule.pattern)

        for rule in cfg.ask:
            # Only add ask if no deny already covers this pattern
            if rule.pattern not in seen_deny_patterns and rule.pattern not in seen_ask_patterns:
                merged_ask.append(rule)
                seen_ask_patterns.add(rule.pattern)

        for rule in cfg.allow:
            if (
                rule.pattern not in seen_deny_patterns
                and rule.pattern not in seen_ask_patterns
                and rule.pattern not in seen_allow_patterns
            ):
                merged_allow.append(rule)
                seen_allow_patterns.add(rule.pattern)

    # Use settings from the last (highest-priority) config
    last = configs[-1]
    return PermissionsConfig(
        version=last.version,
        mode=last.mode,
        deny=merged_deny,
        ask=merged_ask,
        allow=merged_allow,
    )
