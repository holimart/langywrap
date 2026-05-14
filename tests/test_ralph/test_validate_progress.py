"""Tests for the TASK_TYPE inheritance postflight validator."""

from __future__ import annotations

from pathlib import Path

import pytest
from langywrap.ralph.validate_progress import (
    extract_latest_progress_task_type,
    extract_orient_task_type,
    main,
    validate,
)

# ---------------------------------------------------------------------------
# extract_orient_task_type
# ---------------------------------------------------------------------------


def test_extract_orient_task_type_from_canonical_header() -> None:
    text = "# Orient — Cycle 42\n\nTASK_TYPE: lean\n\n## Selected Task\n"
    assert extract_orient_task_type(text) == "lean"


def test_extract_orient_task_type_returns_none_when_missing() -> None:
    assert extract_orient_task_type("# Orient — Cycle 1\n\nno label here\n") is None


# ---------------------------------------------------------------------------
# extract_latest_progress_task_type
# ---------------------------------------------------------------------------


def _progress(*cycles: tuple[int, str | None]) -> str:
    parts: list[str] = []
    for n, ttype in cycles:
        parts.append(f"## Cycle {n} — Demo")
        if ttype is not None:
            parts.append(f"TASK_TYPE: {ttype}")
        parts.append("body line\n")
    return "\n".join(parts)


def test_latest_progress_picks_highest_cycle_number() -> None:
    text = _progress((10, "lean"), (12, "research"), (11, "lean"))
    n, ttype = extract_latest_progress_task_type(text)
    assert (n, ttype) == (12, "research")


def test_latest_progress_returns_none_on_empty() -> None:
    assert extract_latest_progress_task_type("") == (None, None)


def test_latest_progress_returns_none_task_type_when_label_missing() -> None:
    text = _progress((5, None))
    n, ttype = extract_latest_progress_task_type(text)
    assert n == 5
    assert ttype is None


# ---------------------------------------------------------------------------
# validate() — the core compare logic
# ---------------------------------------------------------------------------


def _write(tmp: Path, name: str, content: str) -> Path:
    path = tmp / name
    path.write_text(content, encoding="utf-8")
    return path


def test_validate_ok_when_task_types_match(tmp_path: Path) -> None:
    orient = _write(tmp_path, "orient.md", "TASK_TYPE: lean\n")
    progress = _write(tmp_path, "progress.md", _progress((7, "lean")))
    ok, msg = validate(orient, progress)
    assert ok, msg
    assert "ok" in msg
    assert "lean" in msg


def test_validate_fails_on_documentation_misstamp(tmp_path: Path) -> None:
    # This is exactly the riemann2 bug: orient says lean, finalize stamped
    # documentation.
    orient = _write(tmp_path, "orient.md", "TASK_TYPE: lean\n")
    progress = _write(tmp_path, "progress.md", _progress((1589, "documentation")))
    ok, msg = validate(orient, progress)
    assert not ok
    assert "1589" in msg
    assert "lean" in msg
    assert "documentation" in msg


def test_validate_fails_on_missing_orient_token(tmp_path: Path) -> None:
    orient = _write(tmp_path, "orient.md", "# Orient — Cycle 3\n\nno token here\n")
    progress = _write(tmp_path, "progress.md", _progress((3, "research")))
    ok, msg = validate(orient, progress)
    assert not ok
    assert "TASK_TYPE" in msg


def test_validate_fails_on_missing_progress_block(tmp_path: Path) -> None:
    orient = _write(tmp_path, "orient.md", "TASK_TYPE: lean\n")
    progress = _write(tmp_path, "progress.md", "# Progress log\n\nno cycles yet\n")
    ok, msg = validate(orient, progress)
    assert not ok
    assert "no `## Cycle" in msg or "## Cycle" in msg


def test_validate_fails_when_progress_block_lacks_task_type(tmp_path: Path) -> None:
    orient = _write(tmp_path, "orient.md", "TASK_TYPE: lean\n")
    progress = _write(tmp_path, "progress.md", _progress((4, None)))
    ok, msg = validate(orient, progress)
    assert not ok
    assert "lean" in msg
    assert "4" in msg


def test_validate_fails_on_missing_orient_file(tmp_path: Path) -> None:
    progress = _write(tmp_path, "progress.md", _progress((1, "lean")))
    ok, msg = validate(tmp_path / "missing.md", progress)
    assert not ok
    assert "orient" in msg.lower()


def test_validate_fails_on_missing_progress_file(tmp_path: Path) -> None:
    orient = _write(tmp_path, "orient.md", "TASK_TYPE: lean\n")
    ok, msg = validate(orient, tmp_path / "missing.md")
    assert not ok
    assert "progress" in msg.lower()


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def test_main_exits_zero_on_match(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    orient = _write(tmp_path, "orient.md", "TASK_TYPE: lean\n")
    progress = _write(tmp_path, "progress.md", _progress((10, "lean")))
    rc = main(["--orient", str(orient), "--progress", str(progress)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "ok" in captured.out


def test_main_exits_one_on_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    orient = _write(tmp_path, "orient.md", "TASK_TYPE: lean\n")
    progress = _write(tmp_path, "progress.md", _progress((10, "documentation")))
    rc = main(["--orient", str(orient), "--progress", str(progress)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "documentation" in captured.err
    assert "lean" in captured.err
