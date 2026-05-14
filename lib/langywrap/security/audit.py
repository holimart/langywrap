"""
langywrap.security.audit — Structured audit logging for security decisions.

Log format: JSON-lines, one entry per line.
Default log location: ~/.langywrap/logs/{project}_audit.log
Override via: LANGYWRAP_LOG_DIR environment variable.
"""

from __future__ import annotations

import contextlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Avoid a circular import — PermissionDecision is imported lazily inside
# log_event() or passed in as its .value string-equivalent.


class AuditLogger:
    """
    Append-only JSON-lines audit logger.

    Parameters
    ----------
    project : str
        Project name used in the log filename and every log entry.
    log_dir : Path, optional
        Directory for log files.  Defaults to:
          - $LANGYWRAP_LOG_DIR  (env var)
          - ~/.langywrap/logs/
    """

    def __init__(
        self,
        project: str,
        log_dir: Path | str | None = None,
    ) -> None:
        self.project = project

        if log_dir is not None:
            self._log_dir = Path(log_dir)
        elif env_dir := os.environ.get("LANGYWRAP_LOG_DIR"):
            self._log_dir = Path(env_dir)
        else:
            self._log_dir = Path.home() / ".langywrap" / "logs"

        self._log_dir.mkdir(parents=True, exist_ok=True)

        # One log file per project
        safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in project)
        self._log_file = self._log_dir / f"{safe_name}_audit.log"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_event(
        self,
        command: str,
        decision: Any,            # PermissionDecision enum or str
        rule: Any = None,         # Optional[PermissionRule]
        project: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """
        Append one audit event to the log file.

        Parameters
        ----------
        command : str
            The full command string that was evaluated.
        decision : PermissionDecision | str
            The security decision (ALLOW / DENY / ASK).
        rule : PermissionRule, optional
            The rule that produced the decision.
        project : str, optional
            Override the project name for this entry.
        extra : dict, optional
            Any additional key/value pairs to include in the log entry.
        """
        entry: dict[str, Any] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "project":   project or self.project,
            "command":   command,
            "decision":  _decision_str(decision),
        }

        if rule is not None:
            entry["rule_pattern"] = getattr(rule, "pattern", str(rule))
            if reason := getattr(rule, "reason", None):
                entry["reason"] = reason

        if extra:
            entry.update(extra)

        self._append(entry)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append(self, entry: dict[str, Any]) -> None:
        """Write one JSON line to the log file (thread-safe enough for single-process use)."""
        line = json.dumps(entry, ensure_ascii=False)
        with self._log_file.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    # ------------------------------------------------------------------
    # Introspection helpers (useful for tests / dashboards)
    # ------------------------------------------------------------------

    @property
    def log_file(self) -> Path:
        """Absolute path to the active log file."""
        return self._log_file

    def read_events(self) -> list[dict[str, Any]]:
        """Return all logged events as a list of dicts (newest last)."""
        if not self._log_file.exists():
            return []
        events = []
        with self._log_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    with contextlib.suppress(json.JSONDecodeError):
                        events.append(json.loads(line))
        return events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decision_str(decision: Any) -> str:
    """Normalise PermissionDecision enum or plain string to uppercase string."""
    if hasattr(decision, "value"):
        return str(decision.value).upper()
    return str(decision).upper()
