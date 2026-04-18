"""
langywrap.ralph.context — Prompt context helpers for the Ralph loop.

build_orient_context: the 11x compression function (delegates to RalphState).
inject_scope_restriction: adds scope header to any prompt.
substitute_template: $-variable substitution for prompt templates.
build_enrichments: per-step opt-in external context (e.g. Graphify report).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from langywrap.ralph.state import RalphState


# Hard cap per enricher output. Graphify GRAPH_REPORT.md can be 100KB+;
# dumping it all blows context. ~20KB ≈ 5k tokens is enough for top-level
# communities and god nodes without overwhelming the prompt.
_ENRICHMENT_MAX_CHARS = 20_000


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def build_orient_context(state: RalphState, max_recent_cycles: int = 3) -> str:
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
    enrichments: list[str] | None = None,
) -> str:
    """Compose the final prompt sent to the AI engine.

    Structure:
        [project header]
        [orient context — only for orient step]
        [enrichment sections — per-step opt-in (e.g. ['graphify'])]
        [scope restriction if not already in header]
        [template body with $-variables substituted]

    ``enrichments`` is a list of enricher names resolved against
    ``ENRICHERS``. Unknown names are silently skipped. Missing source files
    (e.g. no graphify-out/) also silently skip — enrichment is advisory.
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

    enrichment_block = build_enrichments(project_dir, enrichments or [])

    parts: list[str] = [header]
    if is_orient_step and orient_context:
        parts.append(orient_context)
        parts.append("\n---\n")
    if enrichment_block:
        parts.append(enrichment_block)
        parts.append("\n---\n")
    parts.append(body)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Enrichment registry — per-step opt-in external context sources
# ---------------------------------------------------------------------------


def _read_graphify_report(project_dir: Path) -> str:
    """Read graphify-out/GRAPH_REPORT.md if present. Truncates to the cap.

    Silently returns '' if the file does not exist. Graphify writes this file
    after ``graphify .`` — absence means the graph has not been built yet and
    the loop should proceed unaided.
    """
    report = project_dir / "graphify-out" / "GRAPH_REPORT.md"
    if not report.is_file():
        return ""
    try:
        content = report.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(content) > _ENRICHMENT_MAX_CHARS:
        content = (
            content[:_ENRICHMENT_MAX_CHARS]
            + f"\n\n[... truncated at {_ENRICHMENT_MAX_CHARS} chars ...]"
        )
    return content


ENRICHERS: dict[str, Callable[[Path], str]] = {
    "graphify": _read_graphify_report,
}


def detect_enrichment_channels(
    project_dir: Path,
    step_enrichments: list[list[str]],
) -> dict[str, bool]:
    """Detect which Graphify delivery channels are wired in this project.

    Three channels can deliver the same graph data to the model:
        prompt   — any step with 'graphify' in its enrich list
        mcp      — .langywrap/mcp.json declares a graphify server
        hook     — .claude/settings.json has a PreToolUse hook mentioning graphify

    Enabling ≥2 wastes tokens: the model sees the same data twice.
    Returns a flags dict; the caller decides whether to warn.

    Parsing is intentionally tolerant — a raw substring check on the
    settings/mcp files is enough to catch the common case without
    pulling in full JSON schemas.
    """
    flags = {"prompt": False, "mcp": False, "hook": False}

    for enrich_list in step_enrichments:
        if "graphify" in enrich_list:
            flags["prompt"] = True
            break

    mcp_path = project_dir / ".langywrap" / "mcp.json"
    if mcp_path.is_file():
        try:
            blob = mcp_path.read_text(encoding="utf-8", errors="replace")
            if "graphify" in blob.lower():
                flags["mcp"] = True
        except OSError:
            pass

    for rel in (".claude/settings.json", ".claude/settings.local.json"):
        sp = project_dir / rel
        if sp.is_file():
            try:
                blob = sp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "graphify" in blob.lower() and "pretooluse" in blob.lower():
                flags["hook"] = True
                break

    return flags


def check_graphify_health(
    project_dir: Path,
    step_enrichments: list[list[str]],
    post_cycle_commands: list[str],
) -> dict[str, object]:
    """Preflight report for Graphify/Textify usage in a ralph pipeline.

    Returns a dict with these keys:
        uses_enrichment      — any step declares ``enrich=['graphify']``
        has_graphify_rebuild — ``post_cycle_commands`` contains a graphify update
        has_textify_extract  — ``post_cycle_commands`` contains a textify call
        graphify_installed   — the ``graphify`` CLI is on PATH
        textify_installed    — the ``textify`` CLI is on PATH (optional)
        issues               — list[str] of actionable messages

    Issues reported:
        - graphify enrichment requested but CLI not installed
        - post-cycle command references graphify/textify but CLI not installed
        - graphify enrichment is on but no post-cycle rebuild is configured
          (stale-graph hazard after the execute step mutates code)

    The function is pure — no side effects, no installation attempts. The
    runner decides what to do with the report (warn vs auto-install).
    """
    import shutil

    uses_enrichment = any("graphify" in e for e in step_enrichments)
    cmd_blob = " ".join(post_cycle_commands).lower()
    # ``graphify update <path>`` is the canonical LLM-free code-only refresh.
    # Older writeups used ``--update``; accept both for backward compatibility.
    has_graphify_rebuild = "graphify" in cmd_blob and (
        " update" in cmd_blob
        or "--update" in cmd_blob
        or "graphify ." in cmd_blob
        or "graphify -u" in cmd_blob
    )
    # ``graphify .`` (full build) triggers LLM extraction on docs/images/PDFs.
    # ``graphify update`` is code-only (tree-sitter, no LLM).
    uses_full_build = (
        "graphify" in cmd_blob
        and "graphify ." in cmd_blob
        and " update" not in cmd_blob
    )
    has_textify_extract = "textify" in cmd_blob

    graphify_installed = shutil.which("graphify") is not None
    textify_installed = shutil.which("textify") is not None

    issues: list[str] = []

    if uses_enrichment and not graphify_installed:
        issues.append(
            "A step declares enrich=['graphify'] but the 'graphify' CLI is not on PATH. "
            "Install via langywrap: ./just install (or ./just install-graphify)."
        )
    if has_graphify_rebuild and not graphify_installed:
        issues.append(
            "post_cycle_commands invokes graphify but the CLI is not on PATH. "
            "Install via langywrap: ./just install-graphify."
        )
    if has_textify_extract and not textify_installed:
        issues.append(
            "post_cycle_commands invokes textify but the CLI is not on PATH. "
            "Install via langywrap: ./just install-textify."
        )
    if uses_enrichment and not has_graphify_rebuild:
        issues.append(
            "enrich=['graphify'] is set on a step but no post_cycle_commands entry rebuilds "
            "the graph — expect stale GRAPH_REPORT.md after the execute step mutates code. "
            "Add 'graphify update .' to Pipeline.post_cycle_commands."
        )
    # Token-consumption warnings: graphify's initial/full build uses LLM subagents
    # for non-code files. Pre-flattening with textify is the LLM-free path.
    if uses_full_build and not has_textify_extract:
        issues.append(
            "post_cycle_commands runs 'graphify .' (full build) without a preceding "
            "'textify' step. Non-code files (PDFs, DOCX, images) will go through LLM "
            "extraction and consume tokens. Recommended: run 'textify docs graphify-in/docs' "
            "FIRST, then 'graphify update .' (code-only, LLM-free)."
        )
    if uses_enrichment and not has_textify_extract and not uses_full_build:
        # Enrichment on, rebuild may or may not be there — remind that the
        # *first-ever* graphify . outside the loop will LLM-extract docs.
        issues.append(
            "graphify enrichment is on but 'textify' is not in post_cycle_commands. "
            "The initial 'graphify .' build (outside the loop) WILL use LLM tokens for "
            "any PDFs/DOCX/images. Pre-flatten with textify to stay LLM-free, or accept "
            "the one-time token cost."
        )

    return {
        "uses_enrichment": uses_enrichment,
        "has_graphify_rebuild": has_graphify_rebuild,
        "has_textify_extract": has_textify_extract,
        "graphify_installed": graphify_installed,
        "textify_installed": textify_installed,
        "issues": issues,
    }


def build_enrichments(project_dir: Path, names: list[str]) -> str:
    """Resolve a list of enricher names to a concatenated markdown block.

    Each enricher gets its own section. Empty results are skipped so a
    missing graphify-out/ directory does not produce a blank header.
    Unknown names are silently ignored — future-compatible for pipelines
    authored against newer langywrap versions.
    """
    sections: list[str] = []
    for name in names:
        fn = ENRICHERS.get(name)
        if fn is None:
            continue
        body = fn(project_dir)
        if not body.strip():
            continue
        sections.append(f"## Enrichment: {name}\n\n{body}")
    return "\n\n".join(sections)
