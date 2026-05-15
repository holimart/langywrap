"""Tests for `langywrap.ralph.progress_dedupe`."""

from __future__ import annotations

from langywrap.ralph.progress_dedupe import (
    dedupe_progress,
    merge_or_append,
)


# ---------------------------------------------------------------------------
# merge_or_append
# ---------------------------------------------------------------------------


class TestMergeOrAppend:
    def test_empty_input_appends_fresh_block(self):
        out = merge_or_append(
            "", 1, ["## Cycle 1 — 2026-01-01", "Outcome: COMPLETED", "Duration: 10s"]
        )
        assert "## Cycle 1 — 2026-01-01" in out
        assert "Outcome: COMPLETED" in out
        assert "Duration: 10s" in out

    def test_no_existing_block_appends(self):
        existing = "# Progress Log\n\nSome intro text.\n"
        out = merge_or_append(
            existing, 5, ["## Cycle 5 — 2026-01-01", "Outcome: COMPLETED"]
        )
        assert out.startswith("# Progress Log")
        assert "## Cycle 5 — 2026-01-01" in out
        assert "Outcome: COMPLETED" in out

    def test_merges_into_existing_narrative(self):
        existing = (
            "# Progress\n\n"
            "## Cycle 7 — 2026-01-01\n"
            "TASK_TYPE: research\n"
            "**Task:** Investigate B33 bound.\n"
            "**Outcome:** PARTIAL\n"
            "---\n"
        )
        out = merge_or_append(
            existing,
            7,
            [
                "## Cycle 7 — 2026-01-01",
                "Outcome: COMPLETED",
                "### Confirmation Chain",
                "- ORIENT_CONFIRMED: yes",
                "Duration: 100.0s",
            ],
        )
        # Only one cycle 7 header.
        assert out.count("## Cycle 7") == 1
        # Narrative preserved.
        assert "TASK_TYPE: research" in out
        assert "**Task:** Investigate B33 bound." in out
        # Skeletal lines injected.
        assert "Duration: 100.0s" in out
        assert "ORIENT_CONFIRMED: yes" in out
        # Header didn't get duplicated inside the body.
        first = out.index("## Cycle 7")
        rest = out[first + 1 :]
        assert "## Cycle 7" not in rest

    def test_does_not_duplicate_metric_keys(self):
        existing = (
            "## Cycle 9 — 2026-01-01\n"
            "TASK_TYPE: lean\n"
            "Duration: 50.0s\n"
        )
        out = merge_or_append(
            existing,
            9,
            ["## Cycle 9 — 2026-01-01", "Duration: 75.5s", "Outcome: PARTIAL"],
        )
        # Existing Duration wins; no second Duration line added.
        assert out.count("Duration:") == 1
        assert "Duration: 50.0s" in out
        assert "Outcome: PARTIAL" in out

    def test_injects_before_trailing_separator(self):
        existing = (
            "## Cycle 3 — 2026-01-01\n"
            "TASK_TYPE: research\n"
            "**Outcome:** DONE\n"
            "---\n"
        )
        out = merge_or_append(
            existing, 3, ["## Cycle 3 — 2026-01-01", "Duration: 20s"]
        )
        # `---` must remain at the end of the block.
        lines = out.splitlines()
        # Drop trailing blank lines for the check.
        while lines and lines[-1] == "":
            lines.pop()
        assert lines[-1] == "---"
        assert "Duration: 20s" in out

    def test_merges_into_first_block_when_multiple_exist(self):
        # Two cycle-4 blocks exist (e.g. execute prepended one, finalize
        # prepended another on top). The runner should merge into the
        # FIRST (= freshest, top-prepended) block.
        existing = (
            "## Cycle 4 — 2026-01-02\n"
            "TASK_TYPE: lean\n"
            "**Task:** new\n"
            "\n"
            "## Cycle 4 — 2026-01-01\n"
            "TASK_TYPE: research\n"
            "**Task:** old\n"
        )
        out = merge_or_append(
            existing, 4, ["## Cycle 4 — 2026-01-02", "Duration: 99s"]
        )
        # Duration must be in the FIRST cycle-4 block (i.e. before "**Task:** old").
        idx_task_old = out.index("**Task:** old")
        idx_duration = out.index("Duration: 99s")
        assert idx_duration < idx_task_old

    def test_preserves_trailing_newline(self):
        existing = "## Cycle 1 — 2026-01-01\nTASK_TYPE: x\n"
        out = merge_or_append(
            existing, 1, ["## Cycle 1 — 2026-01-01", "Duration: 1s"]
        )
        assert out.endswith("\n")


# ---------------------------------------------------------------------------
# dedupe_progress
# ---------------------------------------------------------------------------


class TestDedupeProgress:
    def test_noop_on_clean_input(self):
        text = (
            "## Cycle 1 — 2026-01-01\nTASK_TYPE: research\n"
            "## Cycle 2 — 2026-01-02\nTASK_TYPE: lean\n"
        )
        out, report = dedupe_progress(text)
        assert out == text
        assert report.cycles_with_duplicates == 0
        assert report.blocks_removed == 0

    def test_collapses_top_and_bottom_writer(self):
        # Simulates riemann2's pattern: rich block at top, skeletal at
        # bottom, both for the same cycle.
        text = (
            "# Header\n\n"
            "## Cycle 10 — 2026-01-01\n"
            "TASK_TYPE: research\n"
            "**Task:** Investigate.\n"
            "**Outcome:** PARTIAL\n"
            "---\n\n"
            "## Cycle 10 — 2026-01-01\n"
            "Outcome: COMPLETED\n"
            "### Confirmation Chain\n"
            "- ORIENT_CONFIRMED: yes\n"
            "Duration: 200.0s\n"
        )
        out, report = dedupe_progress(text)
        # Exactly one cycle 10 header.
        assert out.count("## Cycle 10") == 1
        # Narrative survived.
        assert "TASK_TYPE: research" in out
        assert "**Task:** Investigate." in out
        # Skeletal merged in.
        assert "Duration: 200.0s" in out
        assert "ORIENT_CONFIRMED: yes" in out
        # Report.
        assert report.cycles_with_duplicates == 1
        assert report.blocks_removed == 1

    def test_picks_block_with_task_type_when_one_is_skeletal(self):
        text = (
            "## Cycle 5 — 2026-01-01\nOutcome: COMPLETED\nDuration: 30s\n"
            "## Cycle 5 — 2026-01-02\nTASK_TYPE: lean\n**Task:** Lean work.\n"
        )
        out, report = dedupe_progress(text)
        # The TASK_TYPE block wins.
        assert "TASK_TYPE: lean" in out
        assert "**Task:** Lean work." in out
        # And inherits the Duration line from the dropped skeletal sibling.
        assert "Duration: 30s" in out
        # Only one cycle 5 header.
        assert out.count("## Cycle 5") == 1
        assert report.cycles_with_duplicates == 1

    def test_three_blocks_one_cycle(self):
        # Cycle 12 has THREE blocks (two narrative + one skeletal). In
        # file order: hygiene narrative (top, freshest prepend),
        # research narrative (older prepend), skeletal (bottom append).
        text = (
            "## Cycle 12 — 2026-01-02\nTASK_TYPE: hygiene\n**Task:** B.\n"
            "## Cycle 12 — 2026-01-01\nTASK_TYPE: research\n**Task:** A.\n"
            "## Cycle 12 — 2026-01-02\nOutcome: COMPLETED\nDuration: 50s\n"
        )
        out, report = dedupe_progress(text)
        assert out.count("## Cycle 12") == 1
        # The FIRST TASK_TYPE block wins (hygiene), per _choose_canonical.
        assert "TASK_TYPE: hygiene" in out
        assert "**Task:** B." in out
        # The later TASK_TYPE block is gone.
        assert "**Task:** A." not in out
        # Skeletal merged into hygiene block.
        assert "Duration: 50s" in out
        assert report.blocks_removed == 2

    def test_preserves_intro_text(self):
        text = (
            "# Ralph Loop Progress Log\n\n"
            "Some preamble.\n\n"
            "## Cycle 1 — 2026-01-01\nTASK_TYPE: research\n"
            "## Cycle 1 — 2026-01-02\nOutcome: COMPLETED\n"
        )
        out, _ = dedupe_progress(text)
        assert out.startswith("# Ralph Loop Progress Log")
        assert "Some preamble." in out
        assert out.count("## Cycle 1") == 1

    def test_unrelated_cycles_unaffected(self):
        text = (
            "## Cycle 1 — 2026-01-01\nTASK_TYPE: research\n**Task:** A.\n"
            "## Cycle 2 — 2026-01-01\nTASK_TYPE: lean\n**Task:** B.\n"
            "## Cycle 2 — 2026-01-01\nOutcome: COMPLETED\nDuration: 99s\n"
            "## Cycle 3 — 2026-01-01\nTASK_TYPE: hygiene\n**Task:** C.\n"
        )
        out, report = dedupe_progress(text)
        assert "**Task:** A." in out
        assert "**Task:** B." in out
        assert "**Task:** C." in out
        assert out.count("## Cycle 1") == 1
        assert out.count("## Cycle 2") == 1
        assert out.count("## Cycle 3") == 1
        assert "Duration: 99s" in out
        assert report.cycles_with_duplicates == 1


# ---------------------------------------------------------------------------
# Integration: dedupe is idempotent
# ---------------------------------------------------------------------------


def test_dedupe_is_idempotent():
    text = (
        "## Cycle 1 — 2026-01-01\nTASK_TYPE: research\n**Task:** A.\n"
        "## Cycle 1 — 2026-01-01\nOutcome: COMPLETED\nDuration: 10s\n"
    )
    once, _ = dedupe_progress(text)
    twice, report = dedupe_progress(once)
    assert once == twice
    assert report.cycles_with_duplicates == 0


def test_merge_after_dedupe_is_stable():
    """Running the runtime merge after the historical dedupe should not
    re-introduce duplication."""
    text = (
        "## Cycle 1 — 2026-01-01\nTASK_TYPE: research\n**Task:** A.\n"
        "## Cycle 1 — 2026-01-01\nOutcome: COMPLETED\nDuration: 10s\n"
    )
    cleaned, _ = dedupe_progress(text)
    out = merge_or_append(
        cleaned, 1, ["## Cycle 1 — 2026-01-01", "Duration: 10s"]
    )
    assert out.count("## Cycle 1") == 1
    assert out.count("Duration:") == 1
