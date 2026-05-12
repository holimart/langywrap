"""Tests for `langywrap.ralph.markdown_todo` — generic checkbox-todo helpers."""

from __future__ import annotations

import textwrap

from langywrap.ralph.markdown_todo import (
    AutoPin,
    apply_auto_pins,
    dedupe_cycles,
    find_first_open_task,
    parse_auto_pin_lines,
    parse_checkbox_tasks,
    parse_cycle_blocks,
)


def test_parse_checkbox_tasks_basic():
    text = textwrap.dedent("""
        # backlog

        - [ ] **py_plugin**: do thing (auto-pin cycle 42, policy: P1)
        - [x] **profile**: prior work (cycle 5)
        - [ ] **diagnose**: hand-written
        - [ ] **[P2] Technical hygiene** — operator meta, not a task
        - not a task line
    """).strip()
    tasks = parse_checkbox_tasks(text)
    assert len(tasks) == 3
    assert tasks[0].is_open and tasks[0].is_auto_pin
    assert tasks[0].auto_pin_policy == "P1"
    assert tasks[0].auto_pin_cycle == 42
    assert tasks[1].status == "x"
    assert tasks[2].auto_pin_policy is None


def test_parse_checkbox_tasks_filters_by_allowed_types():
    text = textwrap.dedent("""
        - [ ] **py_plugin**: keep
        - [ ] **random_type**: skip
    """).strip()
    tasks = parse_checkbox_tasks(text, allowed_types={"py_plugin"})
    assert len(tasks) == 1
    assert tasks[0].task_type == "py_plugin"


def test_find_first_open_task_returns_first_pending():
    text = textwrap.dedent("""
        - [x] **profile**: done
        - [ ] **py_plugin**: target
        - [ ] **diagnose**: later
    """).strip()
    tasks = parse_checkbox_tasks(text)
    first = find_first_open_task(tasks)
    assert first is not None
    assert first.task_type == "py_plugin"


def test_find_first_open_task_returns_none_when_all_closed():
    text = "- [x] **profile**: done"
    assert find_first_open_task(parse_checkbox_tasks(text)) is None


def test_parse_cycle_blocks_with_metrics_and_hashes():
    text = textwrap.dedent("""
        ## Cycle 100 — profile — 2026-05-09
        TASK_TYPE: profile
        floor(100) = 0.0050
        ceiling(100) = 0.0040
        mem_hash: deadbeef
        smoke_set_hash: cafef00d

        ## Cycle 101 — 2026-05-10
        TASK_TYPE: diagnose
        floor(101) = 0.0055
    """).strip()
    blocks = parse_cycle_blocks(
        text,
        metric_keys=("floor", "ceiling"),
        hash_keys=("mem_hash", "smoke_set_hash"),
    )
    assert [b.n for b in blocks] == [100, 101]
    assert blocks[0].task_type == "profile"
    assert blocks[0].metrics == {"floor": 0.0050, "ceiling": 0.0040}
    assert blocks[0].hashes == {"mem_hash": "deadbeef", "smoke_set_hash": "cafef00d"}
    assert blocks[1].metrics == {"floor": 0.0055}
    assert blocks[1].hashes == {}


def test_parse_cycle_blocks_skips_metrics_for_other_cycle():
    text = textwrap.dedent("""
        ## Cycle 100 — 2026-05-09
        floor(99) = 0.0040
    """).strip()
    blocks = parse_cycle_blocks(text, metric_keys=("floor",))
    assert blocks[0].metrics == {}


def test_dedupe_cycles_keeps_richest_observation():
    text = textwrap.dedent("""
        ## Cycle 100 — 2026-05-09
        notes: skeleton

        ## Cycle 100 — profile — 2026-05-09
        TASK_TYPE: profile
        floor(100) = 0.0050
    """).strip()
    blocks = parse_cycle_blocks(text, metric_keys=("floor",))
    assert len(blocks) == 2
    deduped = dedupe_cycles(blocks)
    assert len(deduped) == 1
    assert deduped[0].task_type == "profile"
    assert deduped[0].metrics == {"floor": 0.0050}


def test_apply_auto_pins_inserts_above_first_task():
    tasks = (
        textwrap.dedent("""
        # backlog

        - [ ] **profile**: hand-written follow-up
        - [x] **diagnose**: done
    """).strip()
        + "\n"
    )
    pin = AutoPin(policy="P1", task_type="py_plugin", label="do thing", cycle=42)
    out = apply_auto_pins(
        tasks,
        [pin],
        current_cycle=42,
        consumed_policies=set(),
    )
    lines = out.splitlines()
    pin_idx = next(i for i, ln in enumerate(lines) if "auto-pin cycle 42" in ln)
    profile_idx = next(i for i, ln in enumerate(lines) if "hand-written" in ln)
    assert pin_idx < profile_idx


def test_apply_auto_pins_clears_consumed_pin():
    tasks = (
        textwrap.dedent("""
        - [ ] **py_plugin**: stale pin (auto-pin cycle 40, policy: P1)
        - [ ] **profile**: operator follow-up
    """).strip()
        + "\n"
    )
    out = apply_auto_pins(
        tasks,
        [],
        current_cycle=42,
        consumed_policies={"P1"},
    )
    assert "auto-pin cycle 40" not in out
    assert "operator follow-up" in out


def test_apply_auto_pins_replaces_re_triggered_pin():
    tasks = (
        textwrap.dedent("""
        - [ ] **py_plugin**: old (auto-pin cycle 40, policy: P1)
        - [ ] **profile**: operator follow-up
    """).strip()
        + "\n"
    )
    pin = AutoPin(policy="P1", task_type="py_plugin", label="fresh", cycle=42)
    out = apply_auto_pins(
        tasks,
        [pin],
        current_cycle=42,
        consumed_policies=set(),
    )
    assert "auto-pin cycle 40" not in out
    assert "auto-pin cycle 42, policy: P1" in out
    assert "fresh" in out


def test_apply_auto_pins_preserves_operator_lines():
    tasks = (
        textwrap.dedent("""
        - [ ] **profile**: critical hand-written — DO NOT DELETE
        - [ ] **diagnose**: another operator task
    """).strip()
        + "\n"
    )
    pin = AutoPin(policy="P1", task_type="py_plugin", label="x", cycle=42)
    out = apply_auto_pins(
        tasks,
        [pin],
        current_cycle=42,
        consumed_policies={"P1", "P2"},
    )
    assert "DO NOT DELETE" in out
    assert "another operator task" in out


def test_parse_auto_pin_lines_works_across_task_formats():
    text = textwrap.dedent("""
        - [ ] **py_plugin**: ktorobi style (auto-pin cycle 10, policy: P1)
        - [ ] **[P0] task:foo** sportsmarket style (auto-pin cycle 11, policy: P2)
        - [x] **bar**: done pin (auto-pin cycle 5, policy: P3)
        - [ ] **profile**: operator line, no tag
        - random non-task line
    """).strip()
    pins = parse_auto_pin_lines(text)
    assert {(p.policy, p.cycle, p.is_open) for p in pins} == {
        ("P1", 10, True),
        ("P2", 11, True),
        ("P3", 5, False),
    }


def test_apply_auto_pins_works_on_sportsmarket_format():
    tasks = textwrap.dedent("""
        # Tasks

        ## Pending

        - [ ] **[P0] task:stale** Old auto-pin (auto-pin cycle 40, policy: P1)
        - [ ] **[P1] task:foo** Operator task
    """).strip() + "\n"
    pin = AutoPin(policy="P1", task_type="py_plugin", label="fresh", cycle=42)
    out = apply_auto_pins(
        tasks,
        [pin],
        current_cycle=42,
        consumed_policies=set(),
    )
    assert "auto-pin cycle 40" not in out
    assert "auto-pin cycle 42, policy: P1" in out
    assert "Operator task" in out  # operator line preserved


def test_apply_auto_pins_sorts_by_policy_id():
    tasks = "- [ ] **profile**: existing\n"
    pins = [
        AutoPin(policy="P10", task_type="fix", label="ten", cycle=1),
        AutoPin(policy="P2", task_type="diagnose", label="two", cycle=1),
        AutoPin(policy="P1", task_type="py_plugin", label="one", cycle=1),
    ]
    out = apply_auto_pins(tasks, pins, current_cycle=1, consumed_policies=set())
    lines = out.splitlines()
    p1 = next(i for i, ln in enumerate(lines) if "policy: P1)" in ln)
    p2 = next(i for i, ln in enumerate(lines) if "policy: P2)" in ln)
    p10 = next(i for i, ln in enumerate(lines) if "policy: P10)" in ln)
    assert p1 < p2 < p10
