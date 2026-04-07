"""
langywrap.ralph.context — Prompt context helpers for the Ralph loop.

build_orient_context: the 11x compression function (delegates to RalphState).
inject_scope_restriction: adds scope header to any prompt.
substitute_template: $-variable substitution for prompt templates.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langywrap.ralph.state import RalphState


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def build_orient_context(state: "RalphState", max_recent_cycles: int = 3) -> str:
    """Return the pre-digested context string for the ORIENT step.

    Delegates to RalphState.build_orient_context — this function exists as a
    standalone entry point so callers do not need to hold a state reference.
    """
    return state.build_orient_context(max_recent_cycles=max_recent_cycles)


def inject_scope_restriction(prompt: str, restriction: str) -> str:
    """Prepend a CRITICAL SCOPE RESTRICTION block to a prompt.

    If restriction is empty, the prompt is returned unchanged.
    """
    if not restriction or not restriction.strip():
        return prompt
    header = (
        "CRITICAL SCOPE RESTRICTION\n"
        "==========================\n"
        f"{restriction.strip()}\n"
        "==========================\n\n"
    )
    return header + prompt


def substitute_template(template: str, context: dict) -> str:
    """Replace $VAR and ${VAR} placeholders in a prompt template.

    Standard substitution variables (all uppercase):
        $PROJECT_ROOT   — absolute path of the project directory
        $CYCLE_NUM      — current cycle number (int)
        $STATE_DIR      — absolute path of the state directory
        $STEPS_DIR      — absolute path of the steps/ output directory
        $DATE           — today's date (YYYY-MM-DD)

    Any extra keys in `context` are also substituted.
    Unknown variables are left as-is.
    """
    result = template
    for key, value in context.items():
        # Support both $KEY and ${KEY} forms
        result = result.replace(f"${{{key}}}", str(value))
        result = result.replace(f"${key}", str(value))
    return result


def build_project_header(
    project_dir: Path,
    state_dir: Path,
    cycle_num: int,
    scope_restriction: str = "",
    extra: dict | None = None,
) -> str:
    """Build the standard project-context header injected before every prompt.

    This is the equivalent of ralph_loop.sh's build_prompt() HEADER block.
    """
    from datetime import date

    steps_dir = state_dir / "steps"
    lines: list[str] = [
        "# Project Context",
        "",
        f"Working directory: {project_dir}",
        f"Current cycle:     {cycle_num}",
        f"Date:              {date.today().isoformat()}",
        "",
        "Key locations:",
        f"  Project root:  {project_dir}",
        f"  Loop state:    {state_dir}  (tasks.md, progress.md, plan.md)",
        f"  Step outputs:  {steps_dir}",
    ]

    if extra:
        for label, path in extra.items():
            lines.append(f"  {label}: {path}")

    if scope_restriction:
        lines += [
            "",
            "CRITICAL SCOPE RESTRICTION:",
            scope_restriction.strip(),
        ]

    lines += ["", "---", ""]
    return "\n".join(lines)


def build_full_prompt(
    template: str,
    project_dir: Path,
    state_dir: Path,
    cycle_num: int,
    orient_context: str = "",
    scope_restriction: str = "",
    extra_context: dict | None = None,
    is_orient_step: bool = False,
) -> str:
    """Compose the final prompt sent to the AI engine.

    Structure:
        [project header]
        [orient context — only for orient step]
        [scope restriction if not already in header]
        [template body with $-variables substituted]
    """
    from datetime import date

    sub_context: dict = {
        "PROJECT_ROOT": str(project_dir),
        "CYCLE_NUM": str(cycle_num),
        "STATE_DIR": str(state_dir),
        "STEPS_DIR": str(state_dir / "steps"),
        "DATE": date.today().isoformat(),
    }
    if extra_context:
        sub_context.update(extra_context)

    header = build_project_header(
        project_dir=project_dir,
        state_dir=state_dir,
        cycle_num=cycle_num,
        scope_restriction=scope_restriction,
        extra=extra_context,
    )

    body = substitute_template(template, sub_context)

    if is_orient_step and orient_context:
        return header + "\n" + orient_context + "\n\n---\n\n" + body

    return header + body
