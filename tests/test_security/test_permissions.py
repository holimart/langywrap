"""Tests for security permissions module."""

from __future__ import annotations

from pathlib import Path

import pytest

from langywrap.security.permissions import (
    PermissionRule,
    PermissionsConfig,
    match_pattern,
    merge_permissions,
)


class TestMatchPattern:
    def test_exact_command_arg(self) -> None:
        assert match_pattern("rm -rf /", "rm:-rf")

    def test_wildcard(self) -> None:
        assert match_pattern("cat anything", "cat:*")

    def test_no_match(self) -> None:
        assert not match_pattern("ls -la", "rm:-rf")

    def test_regex_pattern(self) -> None:
        assert match_pattern("curl https://pastebin.com/upload", "curl:regex:pastebin")

    def test_bare_command(self) -> None:
        assert match_pattern("sudo apt install", "sudo")

    def test_substring_in_args(self) -> None:
        assert match_pattern("git push --force origin main", "git:--force")

    def test_prefix_match_mkfs_ext4(self) -> None:
        """mkfs pattern should catch mkfs.ext4, mkfs.xfs, etc."""
        assert match_pattern("mkfs.ext4 /dev/sda1", "mkfs")
        assert match_pattern("mkfs.xfs /dev/sdb", "mkfs")
        assert match_pattern("mkfs /dev/sda", "mkfs")

    def test_prefix_match_no_false_positive(self) -> None:
        """mkfs pattern should NOT match 'mkfsomething' (no dot separator)."""
        assert not match_pattern("mkfsomething /dev/sda", "mkfs")

    def test_full_command_regex(self) -> None:
        assert match_pattern("curl https://pastebin.com/upload", "regex:pastebin\\.com")
        assert not match_pattern("curl https://example.com", "regex:pastebin\\.com")

    def test_wildcard_star(self) -> None:
        assert match_pattern("anything at all", "*")

    def test_empty_command(self) -> None:
        assert not match_pattern("", "rm:-rf")
        assert not match_pattern("  ", "rm:-rf")


class TestMergePermissions:
    def test_system_deny_overrides_project_allow(self) -> None:
        system = PermissionsConfig(
            deny=[PermissionRule(pattern="rm:-rf", reason="system deny")],
        )
        project = PermissionsConfig(
            allow=[PermissionRule(pattern="rm:-rf", reason="project allow")],
        )
        merged = merge_permissions(system, project)

        deny_patterns = {r.pattern for r in merged.deny}
        allow_patterns = {r.pattern for r in merged.allow}

        assert "rm:-rf" in deny_patterns
        assert "rm:-rf" not in allow_patterns

    def test_both_denies_preserved(self) -> None:
        a = PermissionsConfig(
            deny=[PermissionRule(pattern="sudo", reason="a")],
        )
        b = PermissionsConfig(
            deny=[PermissionRule(pattern="dd", reason="b")],
        )
        merged = merge_permissions(a, b)
        patterns = {r.pattern for r in merged.deny}
        assert "sudo" in patterns
        assert "dd" in patterns

    def test_empty_configs(self) -> None:
        merged = merge_permissions(PermissionsConfig(), PermissionsConfig())
        assert len(merged.deny) == 0
        assert len(merged.allow) == 0


class TestPermissionsConfig:
    def test_roundtrip(self) -> None:
        config = PermissionsConfig(
            version="1.0",
            deny=[PermissionRule(pattern="sudo", reason="no root", message="blocked")],
            allow=[PermissionRule(pattern="cat:*", reason="safe")],
        )
        assert len(config.deny) == 1
        assert config.deny[0].pattern == "sudo"
