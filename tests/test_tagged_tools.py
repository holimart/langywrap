from __future__ import annotations

import pytest
from langywrap.tagged_tools import ToolTag, parse_tool_tags


def test_simple_tag():
    tags = parse_tool_tags("[BASH: echo hello]")
    assert len(tags) == 1
    assert tags[0].name == "BASH"
    assert tags[0].args == "echo hello"


def test_multiple_tags():
    text = "[READ: foo.py] some text [WRITE: bar.py]"
    tags = parse_tool_tags(text)
    assert len(tags) == 2
    names = {t.name for t in tags}
    assert names == {"READ", "WRITE"}


def test_allowed_filter_passes():
    text = "[BASH: echo] [READ: file]"
    tags = parse_tool_tags(text, allowed={"BASH"})
    assert len(tags) == 1
    assert tags[0].name == "BASH"


def test_allowed_filter_blocks():
    text = "[BASH: echo] [READ: file]"
    tags = parse_tool_tags(text, allowed={"WRITE"})
    assert tags == []


def test_allowed_none_accepts_all():
    text = "[FOO: a] [BAR: b] [BAZ: c]"
    tags = parse_tool_tags(text, allowed=None)
    assert len(tags) == 3


def test_empty_text():
    assert parse_tool_tags("") == []


def test_no_tags_in_text():
    assert parse_tool_tags("no tags here at all") == []


def test_lowercase_name_not_matched():
    # Pattern only matches [A-Z0-9_]+
    tags = parse_tool_tags("[bash: echo]")
    assert tags == []


def test_tag_with_multiline_args():
    text = "[PROMPT: line1\nline2\nline3]"
    tags = parse_tool_tags(text)
    assert len(tags) == 1
    assert "line1" in tags[0].args
    assert "line3" in tags[0].args


def test_tool_tag_frozen():
    tag = ToolTag(name="X", args="y")
    with pytest.raises((AttributeError, TypeError)):
        tag.name = "Z"  # type: ignore[misc]


def test_with_numbers_and_underscores_in_name():
    tags = parse_tool_tags("[TOOL_123: some args]")
    assert len(tags) == 1
    assert tags[0].name == "TOOL_123"
