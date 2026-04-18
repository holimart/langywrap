from __future__ import annotations

from unittest.mock import patch

from langywrap.quality.lean import (
    LeanCheckResult,
    _parse_lean_errors,
    check_axioms,
    check_stale_oleans,
    count_sorries,
    lean_build,
    lean_retry_loop,
)

# ---------------------------------------------------------------------------
# _parse_lean_errors
# ---------------------------------------------------------------------------


def test_parse_lean_errors_finds_error_colon():
    output = "foo.lean:10:5: error: unknown identifier"
    errors = _parse_lean_errors(output)
    assert len(errors) == 1
    assert "error:" in errors[0].lower()


def test_parse_lean_errors_case_insensitive():
    output = "Error: something went wrong"
    errors = _parse_lean_errors(output)
    assert len(errors) == 1


def test_parse_lean_errors_no_errors():
    output = "Build succeeded\nAll good"
    errors = _parse_lean_errors(output)
    assert errors == []


def test_parse_lean_errors_multiple():
    output = "a.lean:1:1: error: A\nb.lean:2:2: error: B\nok line"
    errors = _parse_lean_errors(output)
    assert len(errors) == 2


# ---------------------------------------------------------------------------
# count_sorries
# ---------------------------------------------------------------------------


def test_count_sorries_finds_sorry(tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("theorem foo : 1 = 1 := sorry\n")
    sorries = count_sorries(tmp_path)
    assert len(sorries) == 1
    assert sorries[0].line == 1


def test_count_sorries_skips_line_comment(tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("-- sorry this is a comment\n")
    sorries = count_sorries(tmp_path)
    assert sorries == []


def test_count_sorries_skips_block_comment(tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("/- sorry -/\ntheorem ok : True := trivial\n")
    sorries = count_sorries(tmp_path)
    assert sorries == []


def test_count_sorries_multiple_files(tmp_path):
    (tmp_path / "A.lean").write_text("theorem a : 1 = 1 := sorry\n")
    (tmp_path / "B.lean").write_text("theorem b : 2 = 2 := sorry\n")
    sorries = count_sorries(tmp_path)
    assert len(sorries) == 2


def test_count_sorries_empty_file(tmp_path):
    (tmp_path / "Empty.lean").write_text("")
    sorries = count_sorries(tmp_path)
    assert sorries == []


# ---------------------------------------------------------------------------
# check_stale_oleans
# ---------------------------------------------------------------------------


def test_check_stale_oleans_detects_stale(tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("-- lean\n")

    olean = tmp_path / "Foo.olean"
    olean.write_text("-- olean\n")

    # Make .olean older than .lean (olean mtime < lean mtime → stale)
    import os
    lean_mtime = lean_file.stat().st_mtime
    os.utime(str(olean), (lean_mtime - 10, lean_mtime - 10))

    stale = check_stale_oleans(tmp_path)
    assert "Foo.lean" in stale[0]


def test_check_stale_oleans_not_stale_when_olean_newer(tmp_path):
    lean_file = tmp_path / "Bar.lean"
    lean_file.write_text("-- lean\n")

    olean = tmp_path / "Bar.olean"
    olean.write_text("-- olean\n")

    import os
    lean_mtime = lean_file.stat().st_mtime
    # olean newer than lean — not stale
    os.utime(str(olean), (lean_mtime + 10, lean_mtime + 10))

    stale = check_stale_oleans(tmp_path)
    assert stale == []


def test_check_stale_oleans_no_olean(tmp_path):
    (tmp_path / "Baz.lean").write_text("-- lean\n")
    stale = check_stale_oleans(tmp_path)
    assert stale == []


# ---------------------------------------------------------------------------
# check_axioms
# ---------------------------------------------------------------------------


def test_check_axioms_finds_custom(tmp_path):
    (tmp_path / "Ax.lean").write_text("axiom myAxiom : Nat\n")
    result = check_axioms(tmp_path)
    assert any("myAxiom" in r for r in result)


def test_check_axioms_skips_standard_propext(tmp_path):
    (tmp_path / "Ax.lean").write_text("axiom propext : ∀ {a b : Prop}, a ↔ b → a = b\n")
    result = check_axioms(tmp_path)
    assert result == []


def test_check_axioms_skips_quot_sound(tmp_path):
    (tmp_path / "Ax.lean").write_text("axiom Quot.sound : True\n")
    result = check_axioms(tmp_path)
    assert result == []


def test_check_axioms_skips_classical_choice(tmp_path):
    (tmp_path / "Ax.lean").write_text("axiom Classical.choice : True\n")
    result = check_axioms(tmp_path)
    assert result == []


def test_check_axioms_no_lean_files(tmp_path):
    result = check_axioms(tmp_path)
    assert result == []


# ---------------------------------------------------------------------------
# lean_build
# ---------------------------------------------------------------------------


def test_lean_build_success(tmp_path):
    with patch("langywrap.quality.lean.run_subprocess", return_value=(True, "Build OK", 0)):
        result = lean_build(tmp_path)
    assert result.passed is True
    assert result.output == "Build OK"


def test_lean_build_failure(tmp_path):
    output = "foo.lean:1:1: error: unknown identifier\n"
    with patch("langywrap.quality.lean.run_subprocess", return_value=(False, output, 1)):
        result = lean_build(tmp_path)
    assert result.passed is False
    assert len(result.errors) >= 1


def test_lean_build_with_targets(tmp_path):
    captured = {}

    def fake_run(cmd, cwd=None, timeout=300):
        captured["cmd"] = cmd
        return True, "", 0

    with patch("langywrap.quality.lean.run_subprocess", side_effect=fake_run):
        lean_build(tmp_path, targets=["Foo"])
    assert "Foo" in captured["cmd"]


# ---------------------------------------------------------------------------
# lean_retry_loop
# ---------------------------------------------------------------------------


def test_lean_retry_loop_succeeds_first_try(tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("")
    success = LeanCheckResult(passed=True, output="")
    with patch("langywrap.quality.lean.lean_build", return_value=success):
        ok, msg = lean_retry_loop(tmp_path, lean_file, fix_prompt_template="Fix $ERRORS")
    assert ok is True
    assert msg == ""


def test_lean_retry_loop_fails_returns_prompt(tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("")
    fail_result = LeanCheckResult(passed=False, output="error: bad", errors=["error: bad"])
    with patch("langywrap.quality.lean.lean_build", return_value=fail_result):
        ok, msg = lean_retry_loop(
            tmp_path, lean_file, fix_prompt_template="Fix $ERRORS", max_retries=3
        )
    assert ok is False
    assert "Fix" in msg or "error" in msg


def test_lean_retry_loop_all_retries_exhausted(tmp_path):
    lean_file = tmp_path / "Foo.lean"
    lean_file.write_text("")
    fail_result = LeanCheckResult(
        passed=False, output="error: persistent", errors=["error: persistent"]
    )
    with patch("langywrap.quality.lean.lean_build", return_value=fail_result):
        ok, msg = lean_retry_loop(
            tmp_path, lean_file, fix_prompt_template="$ERRORS", max_retries=1
        )
    assert ok is False
