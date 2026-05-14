"""Tests for langywrap.ralph.migrate_tasks — legacy → unified format."""

from __future__ import annotations

import textwrap

from langywrap.ralph.migrate_tasks import (
    DEFAULT_TYPE_MAP,
    _parse_type_map,
    migrate,
)


def test_bracketed_heading_with_default_codes():
    text = textwrap.dedent("""
        # backlog

        ### [P0-R] Read paper X <!-- task:read-paper-x -->
        ### [P2-L] Close sorry in Foo.lean <!-- task:foo-sorry -->
        ### [P1-H] Refresh tasks.md <!-- task:hygiene-refresh -->
    """).strip()
    report = migrate(text)
    assert report.bracketed_count == 3
    assert report.heading_checkbox_count == 0
    assert report.canonical_count == 0
    lines = report.migrated_text.splitlines()
    assert "- [ ] **[P0] task:read-paper-x** [research] Read paper X" in lines
    assert "- [ ] **[P2] task:foo-sorry** [lean] Close sorry in Foo.lean" in lines
    assert "- [ ] **[P1] task:hygiene-refresh** [hygiene] Refresh tasks.md" in lines


def test_heading_checkbox_open_and_closed():
    text = textwrap.dedent("""
        ### [ ] **[P0] task:alpha** [research] First task
        ### [x] **[P1] task:beta** [lean] Done task
    """).strip()
    report = migrate(text)
    assert report.heading_checkbox_count == 2
    assert report.bracketed_count == 0
    lines = report.migrated_text.splitlines()
    assert "- [ ] **[P0] task:alpha** [research] First task" in lines
    assert "- [x] **[P1] task:beta** [lean] Done task" in lines


def test_canonical_lines_pass_through():
    text = textwrap.dedent("""
        - [ ] **[P0] task:foo** [research] Foo
        - [x] **[P2] task:bar** [hygiene] Bar
    """).strip()
    report = migrate(text)
    assert report.canonical_count == 2
    assert report.bracketed_count == 0
    assert report.heading_checkbox_count == 0
    assert report.migrated_text.rstrip("\n") == text


def test_unmapped_type_code_keeps_line_and_records_warning():
    text = "### [P0-Q] Mystery task <!-- task:mystery -->"
    report = migrate(text)
    assert report.bracketed_count == 0
    assert report.unmapped_codes == {"Q"}
    # Line stays unchanged.
    assert report.migrated_text.splitlines()[0] == text


def test_custom_type_map_overrides_default():
    text = "### [P0-D] Data exploration <!-- task:eda -->"
    report = migrate(text, type_map={"D": "data"})
    assert report.bracketed_count == 1
    assert (
        report.migrated_text.splitlines()[0]
        == "- [ ] **[P0] task:eda** [data] Data exploration"
    )


def test_unrecognised_task_heading_emits_warning():
    text = textwrap.dedent("""
        ### [P1] No task slug here
        ### [P0-R] Good task <!-- task:good -->
    """).strip()
    report = migrate(text)
    assert report.bracketed_count == 1
    assert any("No task slug here" in w for w in report.warnings)


def test_mixed_document_preserved():
    text = textwrap.dedent("""
        # tasks.md

        ## P1 Tasks

        ### [P0-R] First <!-- task:first -->

        > blockquote

        ### [P1-L] Second <!-- task:second -->

        ## Completed

        ### [x] **[P2] task:third** [hygiene] Done
    """).strip()
    report = migrate(text)
    assert report.bracketed_count == 2
    assert report.heading_checkbox_count == 1
    lines = report.migrated_text.splitlines()
    assert "## P1 Tasks" in lines
    assert "## Completed" in lines
    assert "> blockquote" in lines


def test_preserves_trailing_newline():
    text = "- [ ] **[P0] task:foo** [research] x\n"
    report = migrate(text)
    assert report.migrated_text.endswith("\n")
    assert report.canonical_count == 1


def test_default_type_map_is_r_l_h():
    assert DEFAULT_TYPE_MAP == {"R": "research", "L": "lean", "H": "hygiene"}


def test_parse_type_map_basic():
    assert _parse_type_map("A=alpha,B=beta") == {"A": "alpha", "B": "beta"}


def test_parse_type_map_uppercases_code_and_strips_whitespace():
    assert _parse_type_map(" r = research , l = lean ") == {
        "R": "research",
        "L": "lean",
    }


def test_parse_type_map_rejects_multi_letter_code():
    import pytest

    with pytest.raises(ValueError, match="single letter"):
        _parse_type_map("RES=research")


def test_parse_type_map_rejects_missing_equals():
    import pytest

    with pytest.raises(ValueError, match="CODE=name"):
        _parse_type_map("research")
