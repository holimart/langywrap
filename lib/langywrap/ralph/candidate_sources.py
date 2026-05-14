"""History-driven synthetic task candidates for inline orient.

A *candidate source* computes synthetic tasks at orient-time, without
mutating ``tasks.md``. Liveness ("should this task fire this cycle?") is
derived from ``progress.md`` — the existing cycle ledger — so no sidecar
state is needed. If a synthetic candidate is offered but outranked by a
higher-priority user task and not consumed, the source re-emits it on the
next cycle automatically (because progress.md still shows the same gap).

This replaces the pre-cycle ``state.inject_hygiene_task`` /
``state.inject_periodic_task`` writes. tasks.md stays agent-authored
(human + LLM) only; the orchestrator never appends rows.

Consumption is observed, not declared: a source's `task_type` showing up
in a later progress.md cycle entry means the candidate ran. The next
trigger fires `every` cycles after that.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from langywrap.ralph.markdown_todo import (
    CheckboxTask,
    dedupe_cycles,
    parse_cycle_blocks,
)

_PRIORITY_ORDER: tuple[str, ...] = ("P3", "P2", "P1", "P0")


def _last_cycle_with_task_type(progress_text: str, task_type: str) -> int | None:
    """Return the cycle number of the most recent progress.md entry tagged with `task_type`."""
    if not progress_text or not task_type:
        return None
    cycles = dedupe_cycles(parse_cycle_blocks(progress_text))
    matches = [c.n for c in cycles if c.task_type == task_type]
    return max(matches) if matches else None


def _escalate_priority(base: str, levels: int) -> str:
    """Shift `base` priority `levels` steps higher (toward P0). Floors at P0.

    Unknown priorities pass through unchanged so operators can override
    with bespoke strings (the picker still works on lexicographic order).
    """
    if levels <= 0 or base not in _PRIORITY_ORDER:
        return base
    idx = _PRIORITY_ORDER.index(base)
    idx = min(len(_PRIORITY_ORDER) - 1, idx + levels)
    return _PRIORITY_ORDER[idx]


@dataclass(frozen=True)
class HygieneSource:
    """Synthesize a hygiene task every N cycles if none has run recently.

    Liveness rule: if the last `progress.md` cycle tagged `task_type` is
    `>= every` cycles old (or no such cycle exists), emit a candidate.

    Escalation: starvation is observable from progress.md. When the
    candidate has been pending past its trigger (i.e. ``cycle_num -
    baseline > every``), bump the priority one P level for every
    ``escalation_every`` extra cycles of wait. Defaults to ``every`` so
    a hygiene every 5 cycles becomes P1 if still ignored after 10 cycles,
    P0 after 15, and stays at P0 from then on.
    """

    every: int
    task_type: str = "hygiene"
    priority: str = "P2"
    label_template: str = "Technical hygiene — cycle {cycle}"
    escalation_every: int = 0
    """Cycles of additional wait per priority bump. 0 → use ``every``. <0 → disabled."""

    def candidates(self, *, cycle_num: int, progress_text: str) -> list[CheckboxTask]:
        if self.every <= 0 or cycle_num <= 0:
            return []
        last = _last_cycle_with_task_type(progress_text, self.task_type)
        baseline = last if last is not None else 0
        wait = cycle_num - baseline
        if wait < self.every:
            return []
        priority = _escalation(self.priority, wait, self.every, self.escalation_every)
        label = self.label_template.format(cycle=cycle_num)
        return [
            CheckboxTask(
                line_no=-1,
                raw="",
                status=" ",
                task_type=self.task_type,
                label=label,
                priority=priority,
                slug=f"synth-{self.task_type}-cycle-{cycle_num}",
            )
        ]


@dataclass(frozen=True)
class PeriodicSource:
    """Generic every-N-cycles synthetic task (e.g. lookback, adversarial).

    `marker` doubles as `task_type` unless `task_type` is set explicitly.
    Inherits the linear-escalation behaviour of :class:`HygieneSource`.
    """

    every: int
    marker: str = "periodic"
    task_type: str = ""
    label: str = ""
    priority: str = "P2"
    escalation_every: int = 0

    @property
    def effective_task_type(self) -> str:
        return self.task_type or self.marker

    def candidates(self, *, cycle_num: int, progress_text: str) -> list[CheckboxTask]:
        if self.every <= 0 or cycle_num <= 0:
            return []
        ttype = self.effective_task_type
        last = _last_cycle_with_task_type(progress_text, ttype)
        baseline = last if last is not None else 0
        wait = cycle_num - baseline
        if wait < self.every:
            return []
        priority = _escalation(self.priority, wait, self.every, self.escalation_every)
        label = self.label or f"Periodic {self.marker} — cycle {cycle_num}"
        return [
            CheckboxTask(
                line_no=-1,
                raw="",
                status=" ",
                task_type=ttype,
                label=label,
                priority=priority,
                slug=f"synth-{self.marker}-cycle-{cycle_num}",
            )
        ]


def _escalation(
    base_priority: str,
    wait: int,
    every: int,
    escalation_every: int,
) -> str:
    """Compute escalated priority. wait = cycles since last observed run.

    ``escalation_every <= 0`` falls back to ``every`` (one bump per
    ``every`` extra cycles waited). To disable escalation entirely, set
    ``escalation_every < 0`` (negative).
    """
    if escalation_every < 0 or every <= 0:
        return base_priority
    step = escalation_every if escalation_every > 0 else every
    excess = wait - every
    if excess <= 0:
        return base_priority
    levels = excess // step
    return _escalate_priority(base_priority, levels)


CandidateSource = HygieneSource | PeriodicSource


def synthesize_candidates(
    sources: Iterable[CandidateSource],
    *,
    cycle_num: int,
    progress_text: str,
) -> list[CheckboxTask]:
    """Merge candidates from every source into a single flat list."""
    out: list[CheckboxTask] = []
    for src in sources:
        out.extend(src.candidates(cycle_num=cycle_num, progress_text=progress_text))
    return out


def sources_from_config(
    *,
    hygiene_every_n: int | None,
    periodic_tasks: list[dict] | None,
) -> list[CandidateSource]:
    """Build a candidate-source list from the legacy ``RalphConfig`` fields.

    Keeps the per-repo ``ralph.py`` configs unchanged: the same
    ``Periodic(every=N, builtin="hygiene")`` declaration still works,
    just without writing tasks.md.
    """
    sources: list[CandidateSource] = []
    if hygiene_every_n and hygiene_every_n > 0:
        sources.append(HygieneSource(every=int(hygiene_every_n)))
    for pt in periodic_tasks or []:
        every = int(pt.get("every", 0) or 0)
        if every <= 0:
            continue
        marker = str(pt.get("marker", "periodic") or "periodic")
        escalation_every = int(pt.get("escalation_every", 0) or 0)
        sources.append(
            PeriodicSource(
                every=every,
                marker=marker,
                task_type=str(pt.get("task_type", "") or ""),
                label=str(pt.get("label", "") or ""),
                escalation_every=escalation_every,
            )
        )
    return sources


__all__ = [
    "CandidateSource",
    "HygieneSource",
    "PeriodicSource",
    "sources_from_config",
    "synthesize_candidates",
]
