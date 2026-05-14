"""Generic helpers for ralph-style markdown todo lists.

Optional companion to `taskdb.py`. Where `taskdb.py` handles the richer
`task:NAME` heading-style format used by langywrap-native projects, this
module handles the simpler **checkbox-style** convention used by ktorobi
and other downstream loops:

```
- [ ] **<task_type>**: <label> (auto-pin cycle N, policy: P<n>)
- [x] **profile**: cycle 100 follow-up (cycle 100)
```

Two design goals:

1. **Generic.** The module is agnostic to which task types or policy IDs a
   downstream project uses. Pass `allowed_types` to filter, or omit to
   accept any. Auto-pin tags are parsed structurally (cycle + policy ID).
2. **Mutation-safe.** Operator-written lines (no `auto-pin` tag) are never
   touched by `apply_auto_pins`. Only auto-pinned lines are subject to
   replacement or removal.

Downstream projects keep their policy logic local; this module supplies
the markdown parse/rewrite primitives.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

AUTO_PIN_RE = re.compile(r"\(auto-pin cycle (\d+), policy: (P\d+)\)")
TASK_LINE_RE = re.compile(r"^- \[( |x)\]\s+\*\*([a-z_][a-z_0-9]*)\*\*:\s*(.*)$")
CHECKBOX_PREFIX_RE = re.compile(r"^- \[( |x)\]\s+(.*)$")
# Unified task format used post-unification:
#   - [ ] **[P0] task:slug-name** [task_type] Human label
# Five groups: status, priority, slug, task_type, label.
UNIFIED_TASK_LINE_RE = re.compile(
    r"^- \[( |x)\]\s+\*\*\[(P\d)\]\s+task:([a-z][\w-]*)\*\*\s+\[([a-z_][\w_]*)\]\s+(.*)$"
)
CYCLE_HDR_RE = re.compile(r"^## Cycle (\d+)\b(.*)$")
CYCLE_TYPE_HINT_RE = re.compile(
    r"##\s*Cycle\s+\d+\s*—\s*([a-z_]+)\s*—",
    re.IGNORECASE,
)
TASK_TYPE_BODY_RE = re.compile(r"^\s*TASK_TYPE:\s*([a-z_]+)\s*$", re.MULTILINE)
# Markdown-table form: `| N | date | task_type | task_id | status | one-line |`
# Used by whitehacky (and any other repo whose finalize emits one row per cycle).
# Header row must contain columns named "N" (or "cycle") and "task_type".
TABLE_SEP_RE = re.compile(r"^\s*\|\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$")
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")


@dataclass
class CheckboxTask:
    """A parsed checkbox task line.

    Carries fields from either the legacy ktorobi format
    ``- [ ] **<task_type>**: <label>`` or the unified format
    ``- [ ] **[P0] task:slug** [task_type] <label>``.

    ``priority`` and ``slug`` are populated only by ``parse_unified_tasks``;
    callers consuming the legacy parser see them as empty strings.
    """

    line_no: int
    raw: str
    status: str  # ' ' or 'x'
    task_type: str
    label: str
    auto_pin_policy: str | None = None
    auto_pin_cycle: int | None = None
    priority: str = ""
    slug: str = ""

    @property
    def is_open(self) -> bool:
        return self.status == " "

    @property
    def is_auto_pin(self) -> bool:
        return self.auto_pin_policy is not None


@dataclass
class CycleBlock:
    """A parsed `## Cycle N — …` block from progress.md.

    `metrics` and `hashes` are project-specific bag of key→value pairs
    populated by a caller-supplied parser hook (see `parse_cycle_blocks`).
    """

    n: int
    task_type: str | None
    body: str
    metrics: dict[str, float] = field(default_factory=dict)
    hashes: dict[str, str] = field(default_factory=dict)


@dataclass
class AutoPin:
    """A pin issued by a finalize-time policy.

    `policy` is an opaque ID like 'P1'; the downstream project owns the
    namespace and the consumption semantics (which task types clear which
    policies).
    """

    policy: str
    task_type: str
    label: str
    cycle: int
    priority: str = "P2"

    def render(self) -> str:
        slug = re.sub(r"[^a-z0-9-]+", "-", f"auto-pin-{self.policy.lower()}-cycle-{self.cycle}")
        slug = re.sub(r"-+", "-", slug).strip("-") or "auto-pin"
        return (
            f"- [ ] **[{self.priority}] task:{slug}** [{self.task_type}] {self.label} "
            f"(auto-pin cycle {self.cycle}, policy: {self.policy})"
        )


def parse_checkbox_tasks(
    text: str,
    *,
    allowed_types: Iterable[str] | None = None,
) -> list[CheckboxTask]:
    """Parse all `- [ ] **type**: …` lines from a tasks.md-style document.

    Lines whose `task_type` is not in `allowed_types` (when given) are
    silently skipped. Operator-written meta-lines like
    `**[P2] Technical hygiene**` do not match and are skipped.
    """
    allowed = set(allowed_types) if allowed_types is not None else None
    out: list[CheckboxTask] = []
    for i, line in enumerate(text.splitlines()):
        m = TASK_LINE_RE.match(line)
        if not m:
            continue
        status, ttype, label = m.group(1), m.group(2), m.group(3)
        if allowed is not None and ttype not in allowed:
            continue
        pin = AUTO_PIN_RE.search(label)
        out.append(
            CheckboxTask(
                line_no=i,
                raw=line,
                status=" " if status != "x" else "x",
                task_type=ttype,
                label=label,
                auto_pin_policy=pin.group(2) if pin else None,
                auto_pin_cycle=int(pin.group(1)) if pin else None,
            )
        )
    return out


def parse_unified_tasks(text: str) -> list[CheckboxTask]:
    """Parse `- [ ] **[P0] task:slug** [type] label` lines (the unified format).

    Lines that don't match the strict regex are skipped (use the linter to
    surface malformed lines separately). Each result carries ``priority``,
    ``slug``, ``task_type``, and ``label`` populated.
    """
    out: list[CheckboxTask] = []
    for i, line in enumerate(text.splitlines()):
        m = UNIFIED_TASK_LINE_RE.match(line)
        if not m:
            continue
        status, prio, slug, ttype, label = m.groups()
        pin = AUTO_PIN_RE.search(label)
        out.append(
            CheckboxTask(
                line_no=i,
                raw=line,
                status=" " if status != "x" else "x",
                task_type=ttype,
                label=label,
                priority=prio,
                slug=slug,
                auto_pin_policy=pin.group(2) if pin else None,
                auto_pin_cycle=int(pin.group(1)) if pin else None,
            )
        )
    return out


def find_first_open_task(
    tasks: list[CheckboxTask],
    *,
    allowed_types: Iterable[str] | None = None,
) -> CheckboxTask | None:
    """Return the first `- [ ]` task. This is the orient pick.

    `allowed_types` lets callers re-filter without re-parsing.
    """
    allowed = set(allowed_types) if allowed_types is not None else None
    for t in tasks:
        if not t.is_open:
            continue
        if allowed is not None and t.task_type not in allowed:
            continue
        return t
    return None


def parse_cycle_blocks(
    text: str,
    *,
    metric_keys: Iterable[str] = (),
    hash_keys: Iterable[str] = (),
) -> list[CycleBlock]:
    """Parse `## Cycle N — …` blocks and (optionally) markdown-table cycle rows.

    `metric_keys` lists keys whose body lines look like `key(N) = <float>`
    (e.g. `floor(100) = 0.005`). Matched values land in `block.metrics[key]`.

    `hash_keys` lists keys whose body lines look like `key: <hexsha>` (e.g.
    `mem_hash: deadbeef...`). Matched values land in `block.hashes[key]`.

    Also detects markdown-table cycle ledgers of the form
    ``| N | date | task_type | … |`` (header must include columns named
    ``N`` or ``cycle`` plus ``task_type``). Each table row becomes a
    CycleBlock with ``n`` and ``task_type`` populated. Used by whitehacky
    and other repos whose finalize emits per-cycle table rows rather than
    heading blocks.

    Duplicate cycle numbers are returned as separate blocks; callers can
    dedupe by `n` if they want a single observation per cycle.
    """
    metric_keys = tuple(metric_keys)
    hash_keys = tuple(hash_keys)
    metric_res = {
        k: re.compile(rf"^\s*{re.escape(k)}\((\d+)\)\s*=\s*([0-9.eE+-]+)") for k in metric_keys
    }
    hash_res = {k: re.compile(rf"^\s*{re.escape(k)}:\s*([0-9a-f]+)") for k in hash_keys}
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if CYCLE_HDR_RE.match(ln)]
    starts.append(len(lines))
    blocks: list[CycleBlock] = []
    for idx in range(len(starts) - 1):
        hdr = CYCLE_HDR_RE.match(lines[starts[idx]])
        if not hdr:
            continue
        n = int(hdr.group(1))
        block_text = "\n".join(lines[starts[idx] : starts[idx + 1]])
        type_hint = CYCLE_TYPE_HINT_RE.search(block_text)
        body_type = TASK_TYPE_BODY_RE.search(block_text)
        task_type = (
            body_type.group(1).lower()
            if body_type
            else type_hint.group(1).lower()
            if type_hint
            else None
        )
        metrics: dict[str, float] = {}
        hashes: dict[str, str] = {}
        for ln in block_text.splitlines():
            for k, pat in metric_res.items():
                m = pat.match(ln)
                if m and int(m.group(1)) == n:
                    metrics[k] = float(m.group(2))
            for k, pat in hash_res.items():
                m = pat.match(ln)
                if m:
                    hashes[k] = m.group(1)
        blocks.append(
            CycleBlock(
                n=n,
                task_type=task_type,
                body=block_text,
                metrics=metrics,
                hashes=hashes,
            )
        )
    blocks.extend(_parse_cycle_table_rows(lines))
    return blocks


def _split_table_row(line: str) -> list[str]:
    m = TABLE_ROW_RE.match(line)
    if not m:
        return []
    inner = m.group(1)
    return [c.strip() for c in inner.split("|")]


def _parse_cycle_table_rows(lines: list[str]) -> list[CycleBlock]:
    """Detect `| N | date | task_type | … |` ledger rows and emit CycleBlocks.

    Multiple tables in the same document are supported. Header column
    names are matched case-insensitively. Rows whose `N` cell is not a
    pure integer are skipped (handles spillover prose around the table).
    """
    out: list[CycleBlock] = []
    i = 0
    while i < len(lines):
        cols = _split_table_row(lines[i])
        if not cols:
            i += 1
            continue
        names = [c.lower() for c in cols]
        cycle_col = None
        for cand in ("n", "cycle", "cycle_n"):
            if cand in names:
                cycle_col = names.index(cand)
                break
        if cycle_col is None or "task_type" not in names:
            i += 1
            continue
        type_col = names.index("task_type")
        # Optional separator row follows.
        j = i + 1
        if j < len(lines) and TABLE_SEP_RE.match(lines[j]):
            j += 1
        # Parse contiguous rows until non-row line.
        while j < len(lines):
            row_cols = _split_table_row(lines[j])
            if not row_cols:
                break
            if (
                cycle_col >= len(row_cols)
                or type_col >= len(row_cols)
                or not row_cols[cycle_col].isdigit()
            ):
                j += 1
                continue
            n = int(row_cols[cycle_col])
            tt = row_cols[type_col].lower() or None
            if tt and not re.fullmatch(r"[a-z_][a-z0-9_]*", tt):
                tt = None
            out.append(
                CycleBlock(
                    n=n,
                    task_type=tt,
                    body=lines[j],
                )
            )
            j += 1
        i = j
    return out


def dedupe_cycles(cycles: list[CycleBlock]) -> list[CycleBlock]:
    """Return one block per cycle number, preferring the richest observation.

    Richness order: non-None `task_type` beats None; any populated
    `metrics`/`hashes` beats empty. When both candidates have a
    `task_type`, a non-``finalize`` value beats ``finalize`` because the
    synthetic finalize marker emitted every cycle would otherwise
    drown out the real work type in budget rollups.
    """
    seen: dict[int, CycleBlock] = {}
    for c in cycles:
        existing = seen.get(c.n)
        if existing is None:
            seen[c.n] = c
            continue
        if existing.task_type is None and c.task_type is not None:
            seen[c.n] = c
            continue
        if (
            existing.task_type == "finalize"
            and c.task_type is not None
            and c.task_type != "finalize"
        ):
            seen[c.n] = c
            continue
        if not existing.metrics and c.metrics:
            seen[c.n] = c
            continue
        if not existing.hashes and c.hashes:
            seen[c.n] = c
    return [seen[n] for n in sorted(seen)]


@dataclass
class AutoPinLine:
    """A `- [ ]` / `- [x]` line carrying an `(auto-pin cycle N, policy: P<n>)` tag.

    Format-agnostic: works for any project that uses the tag suffix, regardless
    of how the rest of the line is structured (e.g. `**type**: label` vs
    `**[P0] task:slug** Title`). Use this for cross-format auto-pin operations
    like `apply_auto_pins`; use `parse_checkbox_tasks` when you also need
    structured access to `task_type` (ktorobi-style format).
    """

    line_no: int
    raw: str
    status: str
    policy: str
    cycle: int

    @property
    def is_open(self) -> bool:
        return self.status == " "


def parse_auto_pin_lines(text: str) -> list[AutoPinLine]:
    """Find every `- [ ]` / `- [x]` line containing an `(auto-pin …)` tag.

    Project-format-agnostic — relies only on the tag, not on the surrounding
    label structure.
    """
    out: list[AutoPinLine] = []
    for i, line in enumerate(text.splitlines()):
        m = CHECKBOX_PREFIX_RE.match(line)
        if not m:
            continue
        pin = AUTO_PIN_RE.search(line)
        if not pin:
            continue
        out.append(
            AutoPinLine(
                line_no=i,
                raw=line,
                status=" " if m.group(1) != "x" else "x",
                policy=pin.group(2),
                cycle=int(pin.group(1)),
            )
        )
    return out


def apply_auto_pins(
    tasks_text: str,
    new_pins: list[AutoPin],
    *,
    current_cycle: int,
    consumed_policies: set[str],
) -> str:
    """Rewrite tasks.md head with the new pin set.

    - Existing auto-pinned tasks whose policy ID is in `consumed_policies`
      (and which are still `- [ ]`) are removed: the current cycle satisfied
      them.
    - Existing auto-pinned tasks whose policy re-triggered are replaced (the
      new pin's `cycle=` value will be fresher).
    - Operator-written lines (no `auto-pin` tag) are never modified.
    - New pins are inserted at the first checkbox-line position, sorted by
      policy id (lexicographic on the `Pn` suffix).

    Project-agnostic: scans for the `(auto-pin …)` tag rather than relying on
    any specific task-label structure.
    """
    pin_policies = {p.policy for p in new_pins}
    lines = tasks_text.splitlines()
    drop_lines: set[int] = set()
    for t in parse_auto_pin_lines(tasks_text):
        if t.policy in pin_policies or (t.is_open and t.policy in consumed_policies):
            drop_lines.add(t.line_no)
    kept = [ln for i, ln in enumerate(lines) if i not in drop_lines]
    if not new_pins:
        return "\n".join(kept) + ("\n" if tasks_text.endswith("\n") else "")
    ordered = sorted(new_pins, key=_policy_sort_key)
    pin_text = [p.render() for p in ordered]
    insert_at = _find_pin_insertion_point(kept)
    out = kept[:insert_at] + pin_text + ([""] if pin_text else []) + kept[insert_at:]
    return "\n".join(out) + ("\n" if tasks_text.endswith("\n") else "")


def _policy_sort_key(pin: AutoPin) -> tuple[int, str]:
    m = re.match(r"P(\d+)", pin.policy)
    if m:
        return (int(m.group(1)), pin.policy)
    return (10**9, pin.policy)


def _find_pin_insertion_point(lines: list[str]) -> int:
    for i, ln in enumerate(lines):
        if CHECKBOX_PREFIX_RE.match(ln):
            return i
    return len(lines)


_PIN_BULLET_RE = re.compile(
    r"^\s+- Pinned:\s*cycle\s+(\d+)\s*\(was\s+(P\d+)(?:,\s*policy:\s*(P\d+))?\)\s*$"
)


def bump_priority(
    tasks_text: str,
    *,
    slug: str,
    new_priority: str,
    cycle: int,
    policy: str = "",
) -> str:
    """Rewrite the priority token on ``- [ ] **[Pn] task:slug**`` in-place.

    Replaces the auto-pin "insert a new P0 row" pattern with a small,
    targeted edit on the row that already exists. The original row's
    other content (task_type, label) is untouched.

    Semantics:
    - **Idempotent.** If the row already shows ``new_priority``, nothing
      is written. Safe to call every cycle.
    - **Lineage is appended once.** A sub-bullet
      ``  - Pinned: cycle N (was Pn, policy: Pm)`` is inserted directly
      after the bumped row the first time the priority changes. Existing
      pin sub-bullets for the same slug are not duplicated.
    - **Demotion supported.** Pass a lower priority to demote — the
      function does not enforce direction. Callers express intent.
    - **No-op when slug is absent.** Returns the input unchanged. Callers
      that need to warn must check themselves (parse first).

    The function never appends new rows, never touches operator-written
    lines that don't match the target slug, and never edits closed
    (``- [x] ...``) tasks. Slug match is exact and case-sensitive.
    """
    if not slug:
        return tasks_text
    # Match the target row regardless of current priority value.
    row_re = re.compile(
        rf"^(- \[ \]\s+\*\*\[)(P\d)(\]\s+task:{re.escape(slug)}\*\*)(.*)$"
    )
    keepends_lines = tasks_text.splitlines(keepends=True)
    out_lines: list[str] = []
    i = 0
    while i < len(keepends_lines):
        line = keepends_lines[i]
        line_no_nl = line.rstrip("\n")
        m = row_re.match(line_no_nl)
        if not m:
            out_lines.append(line)
            i += 1
            continue

        old_priority = m.group(2)
        if old_priority == new_priority:
            # Already at the desired level; preserve existing lineage bullets.
            out_lines.append(line)
            i += 1
            continue

        # Rewrite priority token.
        suffix = "\n" if line.endswith("\n") else ""
        rewritten = f"{m.group(1)}{new_priority}{m.group(3)}{m.group(4)}{suffix}"
        out_lines.append(rewritten)

        # Insert lineage bullet — but only if there isn't already a
        # Pinned bullet for the same (cycle, policy) directly below.
        bullet_text = f"  - Pinned: cycle {cycle} (was {old_priority}"
        if policy:
            bullet_text += f", policy: {policy}"
        bullet_text += ")"
        already_present = False
        j = i + 1
        while j < len(keepends_lines):
            nxt = keepends_lines[j].rstrip("\n")
            mb = _PIN_BULLET_RE.match(nxt)
            if mb is None:
                break
            if (
                int(mb.group(1)) == cycle
                and mb.group(2) == old_priority
                and (mb.group(3) or "") == policy
            ):
                already_present = True
                break
            j += 1

        if not already_present:
            out_lines.append(bullet_text + "\n")

        i += 1
    return "".join(out_lines)


__all__ = [
    "AUTO_PIN_RE",
    "AutoPin",
    "AutoPinLine",
    "CHECKBOX_PREFIX_RE",
    "CYCLE_HDR_RE",
    "CheckboxTask",
    "CycleBlock",
    "TASK_LINE_RE",
    "TASK_TYPE_BODY_RE",
    "UNIFIED_TASK_LINE_RE",
    "apply_auto_pins",
    "bump_priority",
    "dedupe_cycles",
    "find_first_open_task",
    "parse_auto_pin_lines",
    "parse_checkbox_tasks",
    "parse_cycle_blocks",
    "parse_unified_tasks",
]
