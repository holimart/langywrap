"""Tests for the history-driven candidate-source synthesis."""

from __future__ import annotations

import textwrap

from langywrap.ralph.candidate_sources import (
    HygieneSource,
    PeriodicSource,
    sources_from_config,
    synthesize_candidates,
)

PROGRESS_EMPTY = ""

PROGRESS_LAST_HYGIENE_AT_3 = textwrap.dedent("""
## Cycle 1 — 2026-05-01
TASK_TYPE: scan
Outcome: ok

## Cycle 2 — 2026-05-02
TASK_TYPE: scan
Outcome: ok

## Cycle 3 — 2026-05-03
TASK_TYPE: hygiene
Outcome: ok
""").lstrip()


class TestHygieneSource:
    def test_empty_progress_fires_first_cycle(self):
        src = HygieneSource(every=5)
        out = src.candidates(cycle_num=1, progress_text=PROGRESS_EMPTY)
        # cycle_num=1, baseline=0, 1-0=1 < 5 -> no candidate yet
        assert out == []

    def test_empty_progress_fires_at_cycle_n(self):
        src = HygieneSource(every=5)
        out = src.candidates(cycle_num=5, progress_text=PROGRESS_EMPTY)
        assert len(out) == 1
        c = out[0]
        assert c.task_type == "hygiene"
        assert c.priority == "P2"
        assert c.slug == "synth-hygiene-cycle-5"
        assert c.is_open

    def test_recent_hygiene_suppresses_candidate(self):
        # Last hygiene at cycle 3, every=5, asking at cycle 7 -> 7-3=4 < 5
        src = HygieneSource(every=5)
        out = src.candidates(cycle_num=7, progress_text=PROGRESS_LAST_HYGIENE_AT_3)
        assert out == []

    def test_starvation_re_emits(self):
        # Last hygiene at cycle 3, every=5, asking at cycle 8 -> 8-3=5 >= 5
        src = HygieneSource(every=5)
        out = src.candidates(cycle_num=8, progress_text=PROGRESS_LAST_HYGIENE_AT_3)
        assert len(out) == 1

    def test_disabled_when_every_zero(self):
        src = HygieneSource(every=0)
        out = src.candidates(cycle_num=10, progress_text=PROGRESS_EMPTY)
        assert out == []


class TestPeriodicSource:
    def test_uses_marker_as_task_type_by_default(self):
        src = PeriodicSource(every=3, marker="lookback")
        out = src.candidates(cycle_num=3, progress_text=PROGRESS_EMPTY)
        assert len(out) == 1
        assert out[0].task_type == "lookback"
        assert out[0].slug == "synth-lookback-cycle-3"

    def test_explicit_task_type_overrides_marker(self):
        src = PeriodicSource(every=3, marker="lookback", task_type="research")
        out = src.candidates(cycle_num=3, progress_text=PROGRESS_EMPTY)
        assert out[0].task_type == "research"

    def test_custom_label(self):
        src = PeriodicSource(every=3, marker="lookback", label="Custom lookback {ignored}")
        out = src.candidates(cycle_num=3, progress_text=PROGRESS_EMPTY)
        assert out[0].label == "Custom lookback {ignored}"


class TestSynthesize:
    def test_merges_multiple_sources(self):
        sources = [
            HygieneSource(every=5),
            PeriodicSource(every=3, marker="lookback"),
        ]
        out = synthesize_candidates(
            sources, cycle_num=15, progress_text=PROGRESS_EMPTY
        )
        types = {c.task_type for c in out}
        assert types == {"hygiene", "lookback"}


class TestPriorityEscalation:
    def test_no_escalation_at_first_trigger(self):
        # every=5, baseline=0, cycle=5 → wait=5, excess=0 → P2
        src = HygieneSource(every=5)
        c = src.candidates(cycle_num=5, progress_text=PROGRESS_EMPTY)[0]
        assert c.priority == "P2"

    def test_one_step_late_bumps_one_level(self):
        # every=5, baseline=0, cycle=10 → wait=10, excess=5, step=every=5
        # levels = 5//5 = 1 → P2 → P1
        src = HygieneSource(every=5)
        c = src.candidates(cycle_num=10, progress_text=PROGRESS_EMPTY)[0]
        assert c.priority == "P1"

    def test_two_steps_late_bumps_two_levels(self):
        # every=5, cycle=15, wait=15, excess=10, levels=2 → P2 → P0
        src = HygieneSource(every=5)
        c = src.candidates(cycle_num=15, progress_text=PROGRESS_EMPTY)[0]
        assert c.priority == "P0"

    def test_floor_at_p0(self):
        src = HygieneSource(every=5)
        c = src.candidates(cycle_num=100, progress_text=PROGRESS_EMPTY)[0]
        assert c.priority == "P0"

    def test_custom_escalation_every(self):
        # every=5, escalation_every=1 → every cycle late bumps a level
        src = HygieneSource(every=5, escalation_every=1)
        c6 = src.candidates(cycle_num=6, progress_text=PROGRESS_EMPTY)[0]
        c7 = src.candidates(cycle_num=7, progress_text=PROGRESS_EMPTY)[0]
        c8 = src.candidates(cycle_num=8, progress_text=PROGRESS_EMPTY)[0]
        assert c6.priority == "P1"
        assert c7.priority == "P0"
        assert c8.priority == "P0"  # floor

    def test_escalation_disabled_with_negative(self):
        src = HygieneSource(every=5, escalation_every=-1)
        c = src.candidates(cycle_num=100, progress_text=PROGRESS_EMPTY)[0]
        assert c.priority == "P2"  # unchanged despite huge wait

    def test_escalation_uses_progress_baseline(self):
        # Last hygiene at cycle 3 (PROGRESS_LAST_HYGIENE_AT_3), every=5.
        # cycle=13, wait=10, excess=5, levels=1 → P1
        src = HygieneSource(every=5)
        c = src.candidates(cycle_num=13, progress_text=PROGRESS_LAST_HYGIENE_AT_3)[0]
        assert c.priority == "P1"


class TestSourcesFromConfig:
    def test_legacy_fields_produce_hygiene_source(self):
        srcs = sources_from_config(hygiene_every_n=5, periodic_tasks=[])
        assert len(srcs) == 1
        assert isinstance(srcs[0], HygieneSource)
        assert srcs[0].every == 5

    def test_legacy_periodic_tasks_produce_periodic_source(self):
        periodic = [{"every": 9, "marker": "lookback"}]
        srcs = sources_from_config(hygiene_every_n=None, periodic_tasks=periodic)
        assert len(srcs) == 1
        assert isinstance(srcs[0], PeriodicSource)
        assert srcs[0].every == 9
        assert srcs[0].marker == "lookback"

    def test_skips_zero_or_missing_cadence(self):
        periodic = [{"every": 0, "marker": "skip"}, {"marker": "no-every"}]
        srcs = sources_from_config(hygiene_every_n=0, periodic_tasks=periodic)
        assert srcs == []
