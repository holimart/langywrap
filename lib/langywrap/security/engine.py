"""
langywrap.security.engine — SecurityEngine and PermissionDecision.

Config hierarchy (lowest → highest authority):
  bundled defaults  →  project (.langywrap/)  →  system (~/.langywrap/)

System-level DENY rules are never overridable by project config.
This guarantee is enforced inside merge_permissions(); the engine
just loads in the correct order.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .audit import AuditLogger
from .permissions import (
    _BUNDLED_DEFAULTS,
    _CONFIG_FILENAME,
    PermissionRule,
    PermissionsConfig,
    _load_yaml,
    match_pattern,
    merge_permissions,
)

# ---------------------------------------------------------------------------
# Decision enum
# ---------------------------------------------------------------------------


class PermissionDecision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class SecurityResult:
    decision: PermissionDecision
    rule: PermissionRule | None = None
    message: str = ""
    suggestion: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision == PermissionDecision.ALLOW

    @property
    def denied(self) -> bool:
        return self.decision == PermissionDecision.DENY


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class SecurityEngine:
    """
    Central security enforcement point.

    Parameters
    ----------
    project_dir : Path
        Root of the project being guarded.  The engine will look for
        ``<project_dir>/.langywrap/permissions.yaml``.
    system_dir : Path, optional
        System-wide config directory.  Defaults to ``~/.langywrap``.
        System-level DENY rules can never be overridden by project config.
    project_name : str, optional
        Label used in audit-log entries.  Defaults to the project dir name.
    enable_audit : bool
        Write audit log entries.  Default True.
    """

    def __init__(
        self,
        project_dir: Path | str,
        system_dir: Path | str | None = None,
        project_name: str | None = None,
        enable_audit: bool = True,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.system_dir = Path(system_dir).resolve() if system_dir else Path.home() / ".langywrap"
        self.project_name = project_name or self.project_dir.name

        self._config = self._build_config()

        self._audit: AuditLogger | None = None
        if enable_audit:
            self._audit = AuditLogger(project=self.project_name)

    # ------------------------------------------------------------------
    # Config assembly
    # ------------------------------------------------------------------

    def _build_config(self) -> PermissionsConfig:
        """
        Load all config layers and merge them.

        Order matters: later layers in merge_permissions() have higher
        precedence for mode/version, but DENY rules from *any* layer
        always win.

        Layers:
          1. Bundled package defaults
          2. Project-local  (.langywrap/permissions.yaml)
          3. System-wide    (~/.langywrap/permissions.yaml)
        """
        layers = []

        if _BUNDLED_DEFAULTS.exists():
            layers.append(_load_yaml(_BUNDLED_DEFAULTS))

        project_cfg = self.project_dir / ".langywrap" / _CONFIG_FILENAME
        if project_cfg.exists():
            layers.append(_load_yaml(project_cfg))

        system_cfg = self.system_dir / _CONFIG_FILENAME
        if system_cfg.exists():
            layers.append(_load_yaml(system_cfg))

        if not layers:
            return PermissionsConfig()

        return merge_permissions(*layers)

    # ------------------------------------------------------------------
    # Core check logic
    # ------------------------------------------------------------------

    def _find_rule(self, command: str, rules: list[PermissionRule]) -> PermissionRule | None:
        for rule in rules:
            if match_pattern(command, rule.pattern):
                return rule
        return None

    def check(self, command: str) -> SecurityResult:
        """
        Evaluate *command* against the merged permission config.

        Returns a SecurityResult with decision ALLOW / DENY / ASK.
        Does NOT execute the command and does NOT prompt the user.
        ASK means "caller should prompt before executing".
        """
        command = command.strip()

        # 1. DENY — checked first; highest priority
        deny_rule = self._find_rule(command, self._config.deny)
        if deny_rule:
            result = SecurityResult(
                decision=PermissionDecision.DENY,
                rule=deny_rule,
                message=(deny_rule.message or f"Command blocked: {deny_rule.reason or 'policy'}"),
                suggestion=deny_rule.suggestion or "",
            )
            if self._audit:
                self._audit.log_event(
                    command=command,
                    decision=PermissionDecision.DENY,
                    rule=deny_rule,
                    project=self.project_name,
                )
            return result

        # 2. ASK — requires human confirmation before execution
        ask_rule = self._find_rule(command, self._config.ask)
        if ask_rule:
            result = SecurityResult(
                decision=PermissionDecision.ASK,
                rule=ask_rule,
                message=ask_rule.message or f"Confirmation required: {ask_rule.reason or ''}",
                suggestion=ask_rule.suggestion or "",
            )
            if self._audit:
                self._audit.log_event(
                    command=command,
                    decision=PermissionDecision.ASK,
                    rule=ask_rule,
                    project=self.project_name,
                )
            return result

        # 3. ALLOW — explicit or implicit (default-allow)
        allow_rule = self._find_rule(command, self._config.allow)
        result = SecurityResult(
            decision=PermissionDecision.ALLOW,
            rule=allow_rule,
            message=(
                (allow_rule.reason or "Allowed by rule")
                if allow_rule
                else "No matching deny/ask rule — allowed by default"
            ),
        )
        if self._audit:
            self._audit.log_event(
                command=command,
                decision=PermissionDecision.ALLOW,
                rule=allow_rule,
                project=self.project_name,
            )
        return result

    # ------------------------------------------------------------------
    # Check + execute
    # ------------------------------------------------------------------

    def check_and_exec(
        self,
        command: str,
        confirm_callback: Callable[[SecurityResult], bool] | None = None,
        **subprocess_kwargs: Any,
    ) -> subprocess.CompletedProcess[Any]:
        """
        Check the command and, if permitted, execute it.

        Parameters
        ----------
        command : str
            Shell command string to check and run.
        confirm_callback : callable, optional
            Called when decision is ASK.  Signature: ``(SecurityResult) -> bool``.
            If the callback returns False (or is None), execution is aborted
            and a PermissionError is raised.
        **subprocess_kwargs
            Forwarded verbatim to ``subprocess.run()``.

        Returns
        -------
        subprocess.CompletedProcess

        Raises
        ------
        PermissionError
            When the command is DENY or ASK without approval.
        """
        result = self.check(command)

        if result.decision == PermissionDecision.DENY:
            lines = [f"[langywrap] DENIED: {result.message}"]
            if result.suggestion:
                lines.append(f"Suggestion: {result.suggestion}")
            if result.rule and result.rule.alternatives:
                lines.append("Alternatives:")
                lines.extend(f"  • {a}" for a in result.rule.alternatives)
            raise PermissionError("\n".join(lines))

        if result.decision == PermissionDecision.ASK:
            approved = False
            if confirm_callback is not None:
                approved = bool(confirm_callback(result))
            if not approved:
                if self._audit:
                    self._audit.log_event(
                        command=command,
                        decision=PermissionDecision.DENY,
                        rule=result.rule,
                        project=self.project_name,
                        extra={"reason": "user_declined_ask"},
                    )
                raise PermissionError(
                    f"[langywrap] Execution cancelled (ASK not confirmed): {command!r}"
                )
            # Log the user-approved execution
            if self._audit:
                self._audit.log_event(
                    command=command,
                    decision=PermissionDecision.ALLOW,
                    rule=result.rule,
                    project=self.project_name,
                    extra={"reason": "user_approved_ask"},
                )

        # Execute
        kwargs: dict[str, Any] = {"shell": True}
        kwargs.update(subprocess_kwargs)
        return subprocess.run(command, **kwargs)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Re-read all config files from disk."""
        self._config = self._build_config()

    @property
    def config(self) -> PermissionsConfig:
        """The merged PermissionsConfig currently in use."""
        return self._config
