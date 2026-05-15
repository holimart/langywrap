"""progress.md cycle-block merge + dedupe utilities.

The ralph loop has two writers to progress.md:
  * The LLM finalize step prepends a rich narrative block (TASK_TYPE,
    Task, Outcome, Rigor, Files, New tasks, Next).
  * The runner appends a skeletal block (Outcome, Confirmation Chain,
    Quality gate, Git commit, Duration).

Historically these collided — the same cycle ended up with two (or
more) `## Cycle N` headers, and validate_progress masked the conflict
by deduping on max(n). This module replaces "append a new block" with
"merge into the most recent existing block for this cycle (if any) or
append".

Two public entrypoints:

  * ``merge_or_append(progress_text, cycle_num, lines)`` — used at
    runtime by RalphState.append_progress to inject the skeletal
    fields into the narrative block the LLM just wrote.

  * ``dedupe_progress(progress_text)`` — one-shot historical cleanup:
    for each cycle number that has multiple blocks, keep the richest
    block (the one with TASK_TYPE if any, else the longest) and merge
    any unique metric/confirmation lines from its siblings into it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CYCLE_HDR_RE = re.compile(r"^## Cycle (\d+)\b.*$")
TASK_TYPE_RE = re.compile(r"^\s*TASK_TYPE:\s*([A-Za-z_][\w]*)\s*$")
# Lines we recognize as "skeletal metric" content that the runner emits.
# These are safe to copy between sibling blocks without semantic drift.
METRIC_LINE_PREFIXES = (
    "Outcome:",
    "Task:",
    "Quality gate:",
    "Git commit:",
    "Duration:",
)
CONFIRMED_RE = re.compile(r"^- [A-Z_]+_CONFIRMED:\s*(yes|NO|no)\s*$")
CONFIRMATION_HDR = "### Confirmation Chain"


@dataclass
class _Block:
    """A `## Cycle N — …` block sliced out of progress.md."""

    n: int
    start: int  # line index of header (inclusive)
    end: int    # line index AFTER last body line (exclusive)
    lines: list[str]

    @property
    def body(self) -> list[str]:
        return self.lines[self.start : self.end]

    @property
    def has_task_type(self) -> bool:
        return any(TASK_TYPE_RE.match(ln) for ln in self.body)

    @property
    def size(self) -> int:
        return self.end - self.start


def _slice_blocks(lines: list[str]) -> list[_Block]:
    """Return one _Block per `## Cycle N` header in file order."""
    headers: list[tuple[int, int]] = []
    for i, ln in enumerate(lines):
        m = CYCLE_HDR_RE.match(ln)
        if m:
            headers.append((i, int(m.group(1))))
    blocks: list[_Block] = []
    for k, (i, n) in enumerate(headers):
        end = headers[k + 1][0] if k + 1 < len(headers) else len(lines)
        blocks.append(_Block(n=n, start=i, end=end, lines=lines))
    return blocks


def _is_metric_line(line: str) -> bool:
    """Return True if `line` is a known skeletal-metric line worth merging."""
    s = line.lstrip()
    if s.startswith(METRIC_LINE_PREFIXES):
        return True
    if CONFIRMED_RE.match(s):
        return True
    return s == CONFIRMATION_HDR


def _metric_key(line: str) -> str:
    """Identity key for a metric line — same prefix means same datum.

    For `Outcome: COMPLETED` and `Outcome: PARTIAL`, the key is `Outcome:`
    so we don't add two Outcome lines to the same merged block.
    """
    s = line.lstrip()
    if CONFIRMED_RE.match(s):
        # e.g. "- ORIENT_CONFIRMED: yes" → key is "- ORIENT_CONFIRMED:"
        return s.split(":", 1)[0] + ":"
    if s == CONFIRMATION_HDR:
        return CONFIRMATION_HDR
    for prefix in METRIC_LINE_PREFIXES:
        if s.startswith(prefix):
            return prefix
    return s


def _injection_anchor(block_body: list[str]) -> int:
    """Where in the block body to insert merged metric lines.

    Inject just before a trailing `---` separator if present, else before
    any trailing blank lines, else at the end. Returns an offset within
    `block_body` (0-based).
    """
    n = len(block_body)
    # Walk back past trailing blanks
    j = n
    while j > 0 and block_body[j - 1].strip() == "":
        j -= 1
    # If the last non-blank line is `---`, inject before it
    if j > 0 and block_body[j - 1].strip() == "---":
        return j - 1
    return j


def _merge_lines_into_block(
    block_body: list[str], new_lines: list[str]
) -> list[str]:
    """Return a new body with `new_lines` injected (deduped by metric key).

    Lines that look like cycle headers (`## Cycle N …`) are skipped — the
    caller may have included them for the append-only path, but in a
    merge we already have a header.
    """
    existing_keys = {_metric_key(ln) for ln in block_body if _is_metric_line(ln)}
    to_inject: list[str] = []
    for ln in new_lines:
        if not ln.strip():
            continue
        if CYCLE_HDR_RE.match(ln):
            continue
        if _is_metric_line(ln):
            key = _metric_key(ln)
            if key in existing_keys:
                continue
            existing_keys.add(key)
        to_inject.append(ln)
    if not to_inject:
        return list(block_body)
    anchor = _injection_anchor(block_body)
    out = list(block_body[:anchor])
    # Ensure a blank line before the injected section if the previous line
    # is non-blank and not the cycle header.
    if out and out[-1].strip() != "":
        out.append("")
    out.extend(to_inject)
    out.extend(block_body[anchor:])
    return out


def merge_or_append(
    progress_text: str, cycle_num: int, skeletal_lines: list[str]
) -> str:
    """Inject `skeletal_lines` into the last `## Cycle <cycle_num>` block,
    or append a new block if none exists.

    `skeletal_lines` should be the runner's confirmation/metric lines
    WITHOUT a leading `## Cycle …` header — the header is added only when
    appending a new block.

    Trailing newline behavior is preserved: if input ends with `\\n`, so
    does output.
    """
    has_trailing_nl = progress_text.endswith("\n")
    lines = progress_text.splitlines()
    blocks = _slice_blocks(lines)
    same_cycle = [b for b in blocks if b.n == cycle_num]

    if not same_cycle:
        # No existing block — append a fresh one.
        tail = "" if not lines or lines[-1] == "" else "\n"
        body = "\n".join(skeletal_lines)
        out = progress_text + tail + body + ("\n" if has_trailing_nl else "")
        return out

    # FIRST block in file order is the MOST RECENT write: the finalize
    # step prepends, so the freshest narrative ends up at the top.
    target = same_cycle[0]
    target_body = target.body
    new_body = _merge_lines_into_block(target_body, skeletal_lines)
    new_lines = lines[: target.start] + new_body + lines[target.end :]
    out = "\n".join(new_lines)
    if has_trailing_nl:
        out += "\n"
    return out


# ---------------------------------------------------------------------------
# Historical cleanup
# ---------------------------------------------------------------------------


@dataclass
class DedupeReport:
    cycles_with_duplicates: int
    blocks_removed: int
    blocks_kept: int
    metric_lines_merged: int


def _choose_canonical(group: list[_Block]) -> _Block:
    """Pick which block of a duplicate group to keep.

    Rule: prefer the FIRST block that has a TASK_TYPE line. The legacy
    finalize prompts prepend, so the freshest narrative ends up at the
    top of the file — that's the one we want as canonical (it also
    matches what `validate_progress` reads). If no block has TASK_TYPE,
    keep the longest block, breaking ties by file-order earliest.
    """
    tt_blocks = [b for b in group if b.has_task_type]
    if tt_blocks:
        return tt_blocks[0]
    return max(group, key=lambda b: (b.size, -b.start))


def dedupe_progress(progress_text: str) -> tuple[str, DedupeReport]:
    """One-shot deduplication of `## Cycle N` blocks.

    For each cycle number with >1 blocks:
      * pick a canonical block (see `_choose_canonical`)
      * merge any unique metric/confirmation lines from the other blocks
        into the canonical block (via `_merge_lines_into_block`)
      * drop the other blocks entirely.

    Block order in the resulting file is preserved relative to the
    canonical blocks; non-canonical duplicates simply disappear.
    """
    has_trailing_nl = progress_text.endswith("\n")
    lines = progress_text.splitlines()
    blocks = _slice_blocks(lines)
    if not blocks:
        return progress_text, DedupeReport(0, 0, 0, 0)

    by_cycle: dict[int, list[_Block]] = {}
    for b in blocks:
        by_cycle.setdefault(b.n, []).append(b)

    # Decide canonical block per cycle and gather lines-to-merge per canonical.
    canonical_starts: set[int] = set()
    merge_payload: dict[int, list[str]] = {}
    duplicate_cycles = 0
    blocks_removed = 0
    metric_lines_merged = 0
    for _n, group in by_cycle.items():
        if len(group) == 1:
            canonical_starts.add(group[0].start)
            continue
        duplicate_cycles += 1
        canonical = _choose_canonical(group)
        canonical_starts.add(canonical.start)
        blocks_removed += len(group) - 1
        # Collect metric lines from non-canonical siblings.
        merge_lines: list[str] = []
        for b in group:
            if b.start == canonical.start:
                continue
            for ln in b.body:
                if _is_metric_line(ln):
                    merge_lines.append(ln)
        merge_payload[canonical.start] = merge_lines

    # Rebuild the file. Walk blocks in original file order. Keep canonical
    # blocks (with merged lines injected). Drop non-canonical duplicates.
    out_chunks: list[list[str]] = []
    # Lines before the first cycle block:
    first_start = blocks[0].start
    if first_start > 0:
        out_chunks.append(lines[:first_start])

    for k, b in enumerate(blocks):
        next_start = blocks[k + 1].start if k + 1 < len(blocks) else len(lines)
        if b.start not in canonical_starts:
            # Drop this block entirely AND any lines after it up to next header.
            continue
        body = b.body
        if b.start in merge_payload and merge_payload[b.start]:
            before = len(body)
            body = _merge_lines_into_block(body, merge_payload[b.start])
            # Approximate the count of merged lines for the report.
            metric_lines_merged += max(0, len(body) - before)
        out_chunks.append(body)
        # Preserve inter-block separator lines IF the next block is also canonical
        # (otherwise its leading lines belong to a dropped block, skip).
        if next_start > b.end:
            tail = lines[b.end : next_start]
            # If the next block exists and is canonical, keep tail as-is.
            # Otherwise (next block is dropped duplicate), skip tail.
            if k + 1 < len(blocks) and blocks[k + 1].start in canonical_starts:
                out_chunks.append(tail)

    out_lines: list[str] = []
    for chunk in out_chunks:
        out_lines.extend(chunk)
    text = "\n".join(out_lines)
    if has_trailing_nl and not text.endswith("\n"):
        text += "\n"

    blocks_kept = sum(len(g) for g in by_cycle.values()) - blocks_removed
    return text, DedupeReport(
        cycles_with_duplicates=duplicate_cycles,
        blocks_removed=blocks_removed,
        blocks_kept=blocks_kept,
        metric_lines_merged=metric_lines_merged,
    )
