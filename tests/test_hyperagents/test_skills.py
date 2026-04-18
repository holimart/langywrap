from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from langywrap.hyperagents.skills import Skill, SkillLibrary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_library(tmp_path: Path) -> SkillLibrary:
    return SkillLibrary(library_dir=tmp_path / "skills")


def make_skill(name: str = "test-skill", **kwargs) -> Skill:
    kwargs.setdefault("description", f"Test skill: {name}")
    return Skill(name=name, **kwargs)


# ---------------------------------------------------------------------------
# SkillLibrary init + persistence
# ---------------------------------------------------------------------------


def test_init_creates_library_dir(tmp_path):
    lib_dir = tmp_path / "nested" / "skills"
    SkillLibrary(library_dir=lib_dir)
    assert lib_dir.exists()


def test_empty_library_has_no_skills(tmp_path):
    lib = make_library(tmp_path)
    assert lib.all_skills() == []


def test_register_and_get(tmp_path):
    lib = make_library(tmp_path)
    skill = make_skill("my-skill")
    lib.register(skill)
    retrieved = lib.get("my-skill")
    assert retrieved is not None
    assert retrieved.name == "my-skill"


def test_register_saves_catalog(tmp_path):
    lib = make_library(tmp_path)
    lib.register(make_skill("s1"))
    assert lib.catalog_path.exists()
    data = json.loads(lib.catalog_path.read_text())
    assert "s1" in data


def test_catalog_persists_across_instances(tmp_path):
    lib = make_library(tmp_path)
    lib.register(make_skill("persistent"))

    lib2 = make_library(tmp_path)
    assert lib2.get("persistent") is not None


def test_get_returns_none_for_missing(tmp_path):
    lib = make_library(tmp_path)
    assert lib.get("nonexistent") is None


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------


def test_search_by_query(tmp_path):
    lib = make_library(tmp_path)
    lib.register(make_skill("lean-proof", description="Lean theorem prover helper"))
    lib.register(make_skill("ruff-check", description="Python lint runner"))

    results = lib.search(query="lean")
    names = [s.name for s in results]
    assert "lean-proof" in names
    assert "ruff-check" not in names


def test_search_by_tag(tmp_path):
    lib = make_library(tmp_path)
    lib.register(make_skill("s1", tags=["lean", "math"]))
    lib.register(make_skill("s2", tags=["python"]))

    results = lib.search(tags=["lean"])
    names = [s.name for s in results]
    assert "s1" in names
    assert "s2" not in names


def test_search_by_category(tmp_path):
    lib = make_library(tmp_path)
    lib.register(make_skill("s1", category="lean"))
    lib.register(make_skill("s2", category="quality"))

    results = lib.search(category="lean")
    assert all(s.category == "lean" for s in results)


def test_search_by_language(tmp_path):
    lib = make_library(tmp_path)
    lib.register(make_skill("s1", language="python"))
    lib.register(make_skill("s2", language="bash"))

    results = lib.search(language="python")
    assert all(s.language == "python" for s in results)


def test_search_sorted_by_utility(tmp_path):
    lib = make_library(tmp_path)
    lib.register(make_skill("low", utility_score=0.1))
    lib.register(make_skill("high", utility_score=0.9))

    results = lib.search()
    assert results[0].name == "high"


def test_search_no_filter_returns_all(tmp_path):
    lib = make_library(tmp_path)
    lib.register(make_skill("a"))
    lib.register(make_skill("b"))
    assert len(lib.search()) == 2


# ---------------------------------------------------------------------------
# get_by_utility()
# ---------------------------------------------------------------------------


def test_get_by_utility_filters_low(tmp_path):
    lib = make_library(tmp_path)
    lib.register(make_skill("s1", utility_score=0.9))
    lib.register(make_skill("s2", utility_score=0.1))

    results = lib.get_by_utility(min_score=0.5)
    names = [s.name for s in results]
    assert "s1" in names
    assert "s2" not in names


def test_get_by_utility_limits_n(tmp_path):
    lib = make_library(tmp_path)
    for i in range(20):
        lib.register(make_skill(f"s{i}", utility_score=float(i) / 20))
    results = lib.get_by_utility(min_score=0.0, n=5)
    assert len(results) <= 5


# ---------------------------------------------------------------------------
# record_usage()
# ---------------------------------------------------------------------------


def test_record_usage_success_increases_score(tmp_path):
    lib = make_library(tmp_path)
    skill = make_skill("s1", utility_score=0.0, success_count=0, failure_count=1)
    lib.register(skill)
    lib.record_usage("s1", success=True)
    updated = lib.get("s1")
    assert updated.success_count == 1
    assert updated.utility_score > 0.0


def test_record_usage_failure_decreases_score(tmp_path):
    lib = make_library(tmp_path)
    skill = make_skill("s1", utility_score=1.0, success_count=5, failure_count=0)
    lib.register(skill)
    lib.record_usage("s1", success=False)
    updated = lib.get("s1")
    assert updated.failure_count == 1
    assert updated.utility_score < 1.0


def test_record_usage_unknown_skill_noop(tmp_path):
    lib = make_library(tmp_path)
    lib.record_usage("nonexistent", success=True)  # no raise


def test_record_usage_sets_last_used(tmp_path):
    lib = make_library(tmp_path)
    skill = make_skill("s1")
    assert skill.last_used is None
    lib.register(skill)
    lib.record_usage("s1", success=True)
    updated = lib.get("s1")
    assert updated.last_used is not None


# ---------------------------------------------------------------------------
# _parse_skill_output()
# ---------------------------------------------------------------------------


def test_parse_skill_output_no_new_skills(tmp_path):
    lib = make_library(tmp_path)
    result = lib._parse_skill_output("NO_NEW_SKILLS")
    assert result == []


def test_parse_skill_output_creates_skill(tmp_path):
    lib = make_library(tmp_path)
    text = """\
SKILL_ACTION: create
SKILL_NAME: my-new-skill
SKILL_TYPE: helper
SKILL_LANGUAGE: python
SKILL_CATEGORY: quality
SKILL_DESCRIPTION: A useful helper
SKILL_TAGS: python,test
SKILL_CONTENT:
def hello(): pass
END_SKILL
"""
    skills = lib._parse_skill_output(text)
    assert len(skills) == 1
    assert skills[0].name == "my-new-skill"
    assert lib.get("my-new-skill") is not None


def test_parse_skill_output_update_skill(tmp_path):
    lib = make_library(tmp_path)
    # Pre-register
    skill_file = tmp_path / "skills" / "existing.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text("# old")
    existing = make_skill("existing", file_path=skill_file)
    lib.register(existing)

    text = """\
SKILL_ACTION: update
SKILL_NAME: existing
SKILL_CONTENT:
# new content
END_SKILL
"""
    skills = lib._parse_skill_output(text)
    assert len(skills) == 1
    assert skills[0].version == 2


def test_parse_skill_output_multiple_skills(tmp_path):
    lib = make_library(tmp_path)
    text = """\
SKILL_ACTION: create
SKILL_NAME: alpha
SKILL_TYPE: helper
SKILL_LANGUAGE: python
SKILL_CATEGORY: general
SKILL_DESCRIPTION: Alpha
SKILL_TAGS: a
SKILL_CONTENT:
pass
END_SKILL
SKILL_ACTION: create
SKILL_NAME: beta
SKILL_TYPE: helper
SKILL_LANGUAGE: bash
SKILL_CATEGORY: general
SKILL_DESCRIPTION: Beta
SKILL_TAGS: b
SKILL_CONTENT:
echo ok
END_SKILL
"""
    skills = lib._parse_skill_output(text)
    assert len(skills) == 2


# ---------------------------------------------------------------------------
# compose()
# ---------------------------------------------------------------------------


def test_compose_with_file_content(tmp_path):
    lib = make_library(tmp_path)
    skill_file = tmp_path / "skills" / "my-cmd.md"
    skill_file.write_text("# My Command\nDo stuff.")
    lib.register(make_skill("my-cmd", file_path=skill_file))

    composed = lib.compose(["my-cmd"])
    assert "My Command" in composed
    assert "Do stuff" in composed


def test_compose_missing_skill_skipped(tmp_path):
    lib = make_library(tmp_path)
    composed = lib.compose(["nonexistent"])
    assert composed == ""


def test_compose_no_file_uses_description(tmp_path):
    lib = make_library(tmp_path)
    skill = make_skill(
        "nodisk",
        description="Description only",
        file_path=Path("/nonexistent/path.md"),
    )
    lib.register(skill)
    composed = lib.compose(["nodisk"])
    assert "Description only" in composed


# ---------------------------------------------------------------------------
# export_for_project()
# ---------------------------------------------------------------------------


def test_export_for_project_copies_skill(tmp_path):
    lib = make_library(tmp_path)
    skill_file = tmp_path / "skills" / "export-me.py"
    skill_file.write_text("def exported(): pass")
    lib.register(make_skill("export-me", file_path=skill_file))

    count = lib.export_for_project(tmp_path / "project", ["export-me"])
    assert count == 1
    dest = tmp_path / "project" / ".langywrap" / "skills" / "export-me.py"
    assert dest.exists()


def test_export_for_project_missing_skill_skipped(tmp_path):
    lib = make_library(tmp_path)
    count = lib.export_for_project(tmp_path / "project", ["nonexistent"])
    assert count == 0


# ---------------------------------------------------------------------------
# scan_and_register_existing()
# ---------------------------------------------------------------------------


def test_scan_and_register_md_files(tmp_path):
    lib = make_library(tmp_path)
    scripts_dir = tmp_path / "commands"
    scripts_dir.mkdir()
    (scripts_dir / "my-tool.md").write_text("# Tool")
    (scripts_dir / "another.md").write_text("# Another")

    count = lib.scan_and_register_existing([scripts_dir])
    assert count == 2
    assert lib.get("my-tool") is not None


def test_scan_skips_underscore_files(tmp_path):
    lib = make_library(tmp_path)
    d = tmp_path / "d"
    d.mkdir()
    (d / "_private.md").write_text("# Private")
    (d / "public.md").write_text("# Public")

    count = lib.scan_and_register_existing([d])
    assert count == 1
    assert lib.get("_private") is None


def test_scan_skips_already_registered(tmp_path):
    lib = make_library(tmp_path)
    d = tmp_path / "d"
    d.mkdir()
    skill_file = d / "existing.md"
    skill_file.write_text("# Existing")
    lib.register(make_skill("existing", file_path=skill_file))

    count = lib.scan_and_register_existing([d])
    assert count == 0


def test_scan_nonexistent_dir_skipped(tmp_path):
    lib = make_library(tmp_path)
    count = lib.scan_and_register_existing([tmp_path / "does_not_exist"])
    assert count == 0


# ---------------------------------------------------------------------------
# _infer_category() static method
# ---------------------------------------------------------------------------


def test_infer_category_security(tmp_path):
    assert SkillLibrary._infer_category(Path("/foo/security/guard.sh")) == "security"


def test_infer_category_lean(tmp_path):
    assert SkillLibrary._infer_category(Path("/lean/proof.lean")) == "lean"


def test_infer_category_quality(tmp_path):
    assert SkillLibrary._infer_category(Path("/quality/lint.sh")) == "quality"


def test_infer_category_data(tmp_path):
    assert SkillLibrary._infer_category(Path("/data/duckdb_query.py")) == "data"


def test_infer_category_compound(tmp_path):
    assert SkillLibrary._infer_category(Path("/compound/solution.md")) == "compound"


def test_infer_category_meta(tmp_path):
    assert SkillLibrary._infer_category(Path("/meta/agent_tool.md")) == "meta"


def test_infer_category_general(tmp_path):
    assert SkillLibrary._infer_category(Path("/random/stuff.py")) == "general"


# ---------------------------------------------------------------------------
# reflect_and_write (with mocked router)
# ---------------------------------------------------------------------------


def test_reflect_and_write_returns_empty_on_no_new_skills(tmp_path):
    lib = make_library(tmp_path)
    mock_result = MagicMock()
    mock_result.text = "NO_NEW_SKILLS"
    mock_router = MagicMock()
    mock_router.execute.return_value = mock_result

    skills = lib.reflect_and_write({"output": "task done"}, mock_router)
    assert skills == []


def test_reflect_and_write_returns_empty_on_router_error(tmp_path):
    lib = make_library(tmp_path)
    mock_router = MagicMock()
    mock_router.execute.side_effect = RuntimeError("no connection")

    skills = lib.reflect_and_write({"output": "done"}, mock_router)
    assert skills == []


def test_reflect_and_write_creates_skill_on_valid_output(tmp_path):
    lib = make_library(tmp_path)
    mock_result = MagicMock()
    mock_result.text = """\
SKILL_ACTION: create
SKILL_NAME: reflect-skill
SKILL_TYPE: helper
SKILL_LANGUAGE: python
SKILL_CATEGORY: general
SKILL_DESCRIPTION: Auto-reflected
SKILL_TAGS: auto
SKILL_CONTENT:
pass
END_SKILL
"""
    mock_router = MagicMock()
    mock_router.execute.return_value = mock_result

    skills = lib.reflect_and_write({"task": "done"}, mock_router)
    assert len(skills) == 1
    assert skills[0].name == "reflect-skill"
