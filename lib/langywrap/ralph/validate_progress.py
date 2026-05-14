"""Postflight validator: enforce TASK_TYPE inheritance from orient.md.

The inline orient step writes ``TASK_TYPE: <type>`` at the top of
``orient.md`` based on the deterministically picked task. The LLM
finalize step is expected to copy that label verbatim into the new
cycle entry it appends to ``progress.md``. In practice, finalize prompts
that frame the agent as "state-update-only" cause the model to
mis-stamp every cycle as ``TASK_TYPE: documentation``, which breaks the
coverage-budget engine (every budget violates every cycle, nothing
actually rotates).

This module is a thin CLI wrapper that:

1. reads the structured ``TASK_TYPE:`` token from ``orient.md``;
2. reads the most-recent cycle block in ``progress.md`` and extracts
   its ``TASK_TYPE:`` value;
3. exits 0 if they match (and both exist), 1 otherwise with a
   diagnostic message suitable for inclusion in a retry context.

CLI::

    python -m langywrap.ralph.validate_progress \\
        --orient research/ralph/steps/orient.md \\
        --progress research/ralph/progress.md

Designed to be chained into the finalize Step's retry Gate via ``&&``::

    Gate("uv run python -m langywrap.ralph.lint_tasks autofix ... \\
          && uv run python -m langywrap.ralph.validate_progress \\
                --orient research/ralph/steps/orient.md \\
                --progress research/ralph/progress.md")
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from langywrap.ralph.markdown_todo import (
    dedupe_cycles,
    parse_cycle_blocks,
)

_ORIENT_TASK_TYPE_RE = re.compile(r"^\s*TASK_TYPE:\s*([a-z_]+)\s*$", re.MULTILINE)


def extract_orient_task_type(orient_text: str) -> str | None:
    """Return the TASK_TYPE label from the structured orient.md token.

    Orient writes ``TASK_TYPE: <type>`` as its second non-empty line
    (see ``runner._run_inline_orient``). We accept any top-of-file
    occurrence to stay robust to minor template drift.
    """
    match = _ORIENT_TASK_TYPE_RE.search(orient_text)
    return match.group(1).lower() if match else None


def extract_latest_progress_task_type(progress_text: str) -> tuple[int | None, str | None]:
    """Return ``(cycle_num, task_type)`` for the most recent cycle block.

    Uses the shared ``parse_cycle_blocks`` parser so the validator stays
    in lockstep with the coverage-budget engine's view of the same file.
    """
    blocks = dedupe_cycles(parse_cycle_blocks(progress_text))
    if not blocks:
        return None, None
    latest = max(blocks, key=lambda b: b.n)
    return latest.n, latest.task_type


def validate(orient_path: Path, progress_path: Path) -> tuple[bool, str]:
    """Compare orient TASK_TYPE vs latest progress TASK_TYPE.

    Returns ``(ok, message)``. ``ok`` is True only when both labels
    are present and equal. ``message`` is a one-paragraph diagnostic
    suitable for the LLM retry context.
    """
    if not orient_path.exists():
        return False, f"validate_progress: orient file not found at {orient_path}"
    if not progress_path.exists():
        return False, f"validate_progress: progress file not found at {progress_path}"

    orient_text = orient_path.read_text(encoding="utf-8")
    progress_text = progress_path.read_text(encoding="utf-8")

    expected = extract_orient_task_type(orient_text)
    if expected is None:
        return False, (
            f"validate_progress: orient.md ({orient_path}) is missing the "
            "structured `TASK_TYPE: <type>` token. The inline orient step "
            "writes this automatically; if it is missing the orient step "
            "did not run or its output was overwritten."
        )

    latest_n, observed = extract_latest_progress_task_type(progress_text)
    if latest_n is None:
        return False, (
            f"validate_progress: progress.md ({progress_path}) contains no "
            "`## Cycle N — …` blocks at all. Finalize must append a new "
            "cycle entry."
        )
    if observed is None:
        return False, (
            f"validate_progress: progress.md cycle {latest_n} block is "
            "missing the mandatory `TASK_TYPE: <type>` body line. Re-add "
            "it using the template in step4_finalize.md (copy the value "
            f"from orient.md, which is `{expected}`)."
        )
    if observed != expected:
        return False, (
            f"validate_progress: TASK_TYPE mismatch on cycle {latest_n}. "
            f"orient.md picked `{expected}` (this is the cycle's actual "
            f"work type) but progress.md was stamped `{observed}`. "
            "Finalize MUST copy orient's TASK_TYPE verbatim — do NOT label "
            "the cycle by finalize's own role (e.g. 'documentation' / "
            "'consolidation'). Edit progress.md so the cycle "
            f"{latest_n} block's `TASK_TYPE:` line reads `{expected}`."
        )

    return True, (
        f"validate_progress: ok — cycle {latest_n} TASK_TYPE=`{expected}` "
        "matches orient.md."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m langywrap.ralph.validate_progress",
        description=(
            "Verify that the latest progress.md cycle block's TASK_TYPE "
            "matches the structured token in orient.md."
        ),
    )
    parser.add_argument(
        "--orient",
        type=Path,
        required=True,
        help="Path to research/<state>/steps/orient.md.",
    )
    parser.add_argument(
        "--progress",
        type=Path,
        required=True,
        help="Path to research/<state>/progress.md.",
    )
    args = parser.parse_args(argv)

    ok, message = validate(args.orient, args.progress)
    stream = sys.stdout if ok else sys.stderr
    print(message, file=stream)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
