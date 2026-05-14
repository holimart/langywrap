"""Agent variant archive — the growing population of agent configurations.

Implements the DGM-H pattern: an archive of agent variants where each variant
is a complete configuration (router config, step configs, prompt templates,
skill selections). New variants are created by mutating parents selected by
performance + novelty weighting.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class AgentVariant(BaseModel):
    """A single agent configuration variant in the archive."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    generation: int = 0
    parent_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    fitness_score: float = 0.0
    novelty_score: float = 0.0
    metrics: dict[str, Any] = Field(default_factory=dict)
    mutations: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    project_origin: str = ""

    def to_yaml(self) -> str:
        data = self.model_dump()
        data["created_at"] = data["created_at"].isoformat()
        text: str = yaml.dump(data, default_flow_style=False, sort_keys=False)
        return text

    @classmethod
    def from_yaml(cls, text: str) -> AgentVariant:
        data = yaml.safe_load(text)
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


class Archive:
    """Growing archive of agent variants with selection strategies."""

    def __init__(self, archive_dir: Path) -> None:
        self.archive_dir = Path(archive_dir)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._variants: dict[str, AgentVariant] = {}
        self._load_all()

    def _load_all(self) -> None:
        for f in self.archive_dir.glob("*.yaml"):
            try:
                variant = AgentVariant.from_yaml(f.read_text())
                self._variants[variant.id] = variant
            except Exception:
                continue

    def add(self, variant: AgentVariant) -> None:
        self._variants[variant.id] = variant
        path = self.archive_dir / f"{variant.id}.yaml"
        path.write_text(variant.to_yaml())

    def get(self, variant_id: str) -> AgentVariant | None:
        return self._variants.get(variant_id)

    def all_variants(self) -> list[AgentVariant]:
        return list(self._variants.values())

    def select_parent(self, strategy: str = "fitness_novelty") -> AgentVariant | None:
        """Select a parent variant for reproduction.

        Strategies:
            best: highest fitness
            novelty: highest novelty
            fitness_novelty: weighted combination (0.7 fitness + 0.3 novelty)
            random: uniform random
        """
        import random as rng

        variants = self.all_variants()
        if not variants:
            return None

        if strategy == "best":
            return max(variants, key=lambda v: v.fitness_score)
        elif strategy == "novelty":
            self._recompute_novelty()
            return max(variants, key=lambda v: v.novelty_score)
        elif strategy == "random":
            return rng.choice(variants)
        else:  # fitness_novelty
            self._recompute_novelty()
            scores = [v.fitness_score * 0.7 + v.novelty_score * 0.3 for v in variants]
            # Shift to positive for weighting
            min_score = min(scores) if scores else 0
            weights = [s - min_score + 0.01 for s in scores]
            return rng.choices(variants, weights=weights, k=1)[0]

    def get_best(self, n: int = 5) -> list[AgentVariant]:
        return sorted(self.all_variants(), key=lambda v: v.fitness_score, reverse=True)[:n]

    def get_lineage(self, variant_id: str) -> list[AgentVariant]:
        """Trace parent chain back to root."""
        lineage = []
        current = self.get(variant_id)
        while current:
            lineage.append(current)
            current = self.get(current.parent_id) if current.parent_id else None
        return lineage

    def _recompute_novelty(self) -> None:
        """Compute novelty as config distance from k-nearest neighbors."""
        variants = self.all_variants()
        if len(variants) < 2:
            for v in variants:
                v.novelty_score = 1.0
            return

        for v in variants:
            distances = []
            for other in variants:
                if other.id == v.id:
                    continue
                d = self._config_distance(v.config, other.config)
                distances.append(d)
            distances.sort()
            k = min(3, len(distances))
            v.novelty_score = sum(distances[:k]) / k if k > 0 else 0.0

    @staticmethod
    def _config_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
        """Simple distance: count differing keys at top level."""
        all_keys = set(list(a.keys()) + list(b.keys()))
        if not all_keys:
            return 0.0
        diffs = sum(1 for k in all_keys if str(a.get(k)) != str(b.get(k)))
        return diffs / len(all_keys)

    def prune(self, keep_top: int = 50) -> int:
        """Remove low-performing variants beyond threshold. Returns count removed."""
        if len(self._variants) <= keep_top:
            return 0

        sorted_variants = sorted(
            self._variants.values(), key=lambda v: v.fitness_score, reverse=True
        )
        to_remove = sorted_variants[keep_top:]
        removed = 0
        for v in to_remove:
            path = self.archive_dir / f"{v.id}.yaml"
            if path.exists():
                path.unlink()
            del self._variants[v.id]
            removed += 1
        return removed

    def update_fitness(self, variant_id: str, metrics: dict[str, Any]) -> None:
        """Update variant fitness based on evaluation metrics."""
        variant = self.get(variant_id)
        if not variant:
            return

        variant.metrics.update(metrics)

        # Fitness formula: quality - cost - failure penalty
        quality = metrics.get("quality_score", 0.0)
        cost = metrics.get("total_cost_usd", 0.0)
        duration = metrics.get("duration_seconds", 0.0)
        failures = metrics.get("failure_rate", 0.0)

        variant.fitness_score = quality * 0.5 - cost * 0.3 - duration * 0.0002 - failures * 0.4

        # Persist
        path = self.archive_dir / f"{variant.id}.yaml"
        path.write_text(variant.to_yaml())
