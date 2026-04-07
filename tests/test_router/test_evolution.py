"""Tests for route config evolution (HyperAgents pattern)."""

from __future__ import annotations

from pathlib import Path

import pytest

from langywrap.hyperagents.archive import AgentVariant, Archive
from langywrap.hyperagents.mutations import MutationType, mutate


class TestArchive:
    def test_empty_archive(self, tmp_path: Path) -> None:
        archive = Archive(tmp_path / "archive")
        assert len(archive.all_variants()) == 0
        assert archive.select_parent() is None

    def test_add_and_retrieve(self, tmp_path: Path) -> None:
        archive = Archive(tmp_path / "archive")
        variant = AgentVariant(
            config={"routes": {"orient": {"model": "haiku"}}},
            fitness_score=0.8,
        )
        archive.add(variant)
        assert archive.get(variant.id) is not None
        assert len(archive.all_variants()) == 1

    def test_persistence(self, tmp_path: Path) -> None:
        archive_dir = tmp_path / "archive"
        archive = Archive(archive_dir)
        variant = AgentVariant(config={"test": True}, fitness_score=0.5)
        archive.add(variant)

        # Reload
        archive2 = Archive(archive_dir)
        assert len(archive2.all_variants()) == 1

    def test_select_parent_best(self, tmp_path: Path) -> None:
        archive = Archive(tmp_path / "archive")
        for score in [0.1, 0.5, 0.9]:
            archive.add(AgentVariant(config={}, fitness_score=score))
        best = archive.select_parent("best")
        assert best is not None
        assert best.fitness_score == 0.9

    def test_prune(self, tmp_path: Path) -> None:
        archive = Archive(tmp_path / "archive")
        for i in range(10):
            archive.add(AgentVariant(config={}, fitness_score=float(i) / 10))
        removed = archive.prune(keep_top=5)
        assert removed == 5
        assert len(archive.all_variants()) == 5


class TestMutations:
    def test_mutate_creates_child(self) -> None:
        parent = AgentVariant(
            config={"routes": {"orient": {"model": "haiku", "timeout_minutes": 20}}},
            fitness_score=0.5,
        )
        child = mutate(parent, n_mutations=1)
        assert child.parent_id == parent.id
        assert child.generation == parent.generation + 1
        assert len(child.mutations) >= 1

    def test_mutate_changes_config(self) -> None:
        parent = AgentVariant(
            config={
                "routes": {
                    "orient": {"model": "haiku", "timeout_minutes": 20, "backend": "claude"},
                    "execute": {"model": "kimi", "timeout_minutes": 120, "backend": "opencode"},
                }
            },
        )
        # Run many mutations to ensure at least one changes something
        changed = False
        for _ in range(20):
            child = mutate(parent, n_mutations=3)
            if child.config != parent.config:
                changed = True
                break
        assert changed
