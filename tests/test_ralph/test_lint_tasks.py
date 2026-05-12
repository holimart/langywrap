"""Tests for the tasks.md linter."""

from __future__ import annotations

from langywrap.ralph.lint_tasks import (
    SEV_AUTOFIXED,
    SEV_HARD_FAIL,
    LintConfig,
    autofix,
    lint,
)

UNIFIED = (
    "## Active\n"
    "- [ ] **[P0] task:do-thing** [research] Investigate the thing\n"
    "\n"
    "## Pending\n"
    "- [ ] **[P1] task:other** [fix] Fix the other\n"
)

LEGACY_PIN_LINE = (
    "## Pending\n"
    "- [ ] **[P0] task:stale** [diagnose] note "
    "(auto-pin cycle 42, policy: P2)\n"
)


def _cfg(**overrides: object) -> LintConfig:
    base = {
        "allowed_task_types": ("research", "fix", "diagnose"),
        "allowed_priorities": ("P0", "P1", "P2", "P3"),
    }
    base.update(overrides)
    return LintConfig(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_clean_unified_text_is_clean() -> None:
    report = lint(UNIFIED, _cfg())
    assert report.is_clean
    assert report.findings == []


def test_autofix_on_clean_text_yields_unchanged_text() -> None:
    report = autofix(UNIFIED, _cfg())
    assert report.is_clean
    assert report.fixed_text == UNIFIED


# ---------------------------------------------------------------------------
# Autofix rules
# ---------------------------------------------------------------------------


def test_strip_legacy_auto_pin_tag() -> None:
    report = autofix(LEGACY_PIN_LINE, _cfg())
    assert report.fixed_text is not None
    assert "auto-pin cycle" not in report.fixed_text
    assert any(f.rule == "strip_legacy_auto_pin_tag" for f in report.autofixed)
    assert report.is_clean


def test_strip_legacy_auto_pin_tag_only_runs_when_enabled() -> None:
    report = autofix(LEGACY_PIN_LINE, _cfg(strip_legacy_auto_pin_tag=False))
    assert report.fixed_text is not None
    assert "auto-pin cycle" in report.fixed_text


def test_trim_trailing_whitespace() -> None:
    text = (
        "## Pending\n"
        "- [ ] **[P0] task:keep** [fix] label   \n"
    )
    report = autofix(text, _cfg())
    assert report.fixed_text is not None
    assert not any(line.endswith(" ") for line in report.fixed_text.splitlines())
    assert any(f.rule == "trim_trailing_whitespace" for f in report.autofixed)


def test_collapse_blank_runs() -> None:
    text = (
        "## Pending\n\n\n\n\n"
        "- [ ] **[P0] task:k** [fix] x\n"
    )
    report = autofix(text, _cfg())
    assert report.fixed_text is not None
    # No run of more than two consecutive blank lines.
    blank_run = 0
    max_run = 0
    for line in report.fixed_text.splitlines():
        if line.strip() == "":
            blank_run += 1
            max_run = max(max_run, blank_run)
        else:
            blank_run = 0
    assert max_run <= 2
    assert any(f.rule == "collapse_blank_runs" for f in report.autofixed)


# ---------------------------------------------------------------------------
# Hard-fail rules
# ---------------------------------------------------------------------------


def test_unified_format_violation() -> None:
    text = (
        "## Pending\n"
        "- [ ] **research**: legacy ktorobi shape\n"
    )
    report = lint(text, _cfg())
    assert not report.is_clean
    assert any(f.rule == "unified_format" for f in report.hard_fails)


def test_legacy_format_allowed_when_configured() -> None:
    text = (
        "## Pending\n"
        "- [ ] **research**: legacy ktorobi shape\n"
    )
    report = lint(text, _cfg(allow_legacy_format=True))
    assert report.is_clean


def test_invalid_priority() -> None:
    text = "- [ ] **[P9] task:x** [fix] label\n"
    report = lint(text, _cfg())
    fails = [f for f in report.hard_fails if f.rule == "valid_priority"]
    assert len(fails) == 1


def test_invalid_task_type() -> None:
    text = "- [ ] **[P0] task:x** [made_up_type] label\n"
    report = lint(text, _cfg())
    fails = [f for f in report.hard_fails if f.rule == "valid_task_type"]
    assert len(fails) == 1


def test_any_task_type_accepted_when_allowed_empty() -> None:
    text = "- [ ] **[P0] task:x** [anything_goes] label\n"
    report = lint(text, _cfg(allowed_task_types=()))
    assert report.is_clean


def test_duplicate_slug_hard_fails() -> None:
    text = (
        "- [ ] **[P0] task:dup** [research] a\n"
        "- [ ] **[P1] task:dup** [fix] b\n"
    )
    report = lint(text, _cfg())
    fails = [f for f in report.hard_fails if f.rule == "unique_slug"]
    assert len(fails) == 1


def test_active_count_cap() -> None:
    text = (
        "## Active\n"
        "- [ ] **[P0] task:a** [fix] a\n"
        "- [ ] **[P0] task:b** [fix] b\n"
        "## Pending\n"
    )
    report = lint(text, _cfg())
    fails = [f for f in report.hard_fails if f.rule == "active_count"]
    assert len(fails) == 1


def test_active_count_respects_higher_cap_config() -> None:
    text = (
        "## Active\n"
        "- [ ] **[P0] task:a** [fix] a\n"
        "- [ ] **[P0] task:b** [fix] b\n"
        "## Pending\n"
    )
    report = lint(text, _cfg(max_active=2))
    assert not any(f.rule == "active_count" for f in report.hard_fails)


# ---------------------------------------------------------------------------
# Render & JSON output
# ---------------------------------------------------------------------------


def test_render_clean() -> None:
    out = lint(UNIFIED, _cfg()).render()
    assert "clean" in out


def test_render_includes_findings() -> None:
    text = "- [ ] **[P9] task:x** [fix] y\n"
    out = lint(text, _cfg()).render()
    assert "hard_fail" in out
    assert "valid_priority" in out


def test_to_json_shape() -> None:
    text = "- [ ] **[P9] task:x** [fix] y\n"
    report = lint(text, _cfg())
    import json

    data = json.loads(report.to_json())
    assert data["is_clean"] is False
    assert data["counts"]["hard_fail"] >= 1
    assert isinstance(data["findings"], list)


# ---------------------------------------------------------------------------
# Autofix + report combination
# ---------------------------------------------------------------------------


def test_autofix_keeps_hard_fails_in_report() -> None:
    text = (
        "- [ ] **[P0] task:k** [research] legacy "
        "(auto-pin cycle 3, policy: P1)   \n"
        "- [ ] **[P9] task:bad** [fix] invalid priority\n"
    )
    report = autofix(text, _cfg())
    # autofixes applied for tag strip + trailing ws
    assert any(f.severity == SEV_AUTOFIXED for f in report.findings)
    # but the bad-priority line still hard-fails
    assert any(f.severity == SEV_HARD_FAIL for f in report.findings)
    assert report.fixed_text is not None
    assert "auto-pin cycle" not in report.fixed_text
