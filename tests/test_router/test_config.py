"""Tests for ExecutionRouter configuration."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from langywrap.router.config import (
    DEFAULT_ROUTE_CONFIG,
    RouteConfig,
    RouteRule,
    StepRole,
    load_route_config,
    save_route_config,
)


class TestRouteConfig:
    def test_default_config_has_all_roles(self) -> None:
        config = DEFAULT_ROUTE_CONFIG
        roles_covered = {r.role for r in config.rules}
        required = {StepRole.ORIENT, StepRole.PLAN, StepRole.EXECUTE, StepRole.FINALIZE}
        assert required.issubset(roles_covered)

    def test_roundtrip_yaml(self, tmp_path: Path) -> None:
        config = DEFAULT_ROUTE_CONFIG
        path = tmp_path / "router.yaml"
        save_route_config(config, path)
        loaded = load_route_config(tmp_path)
        assert loaded.name == config.name
        assert len(loaded.rules) == len(config.rules)

    def test_review_every_n(self) -> None:
        config = DEFAULT_ROUTE_CONFIG
        assert config.review_every_n > 0


class TestRouteRule:
    def test_conditions_match(self) -> None:
        rule = RouteRule(
            role=StepRole.EXECUTE,
            model="kimi-k2.5",
            backend="opencode",
            conditions={"cycle_type": "lean"},
        )
        assert rule.conditions.get("cycle_type") == "lean"
