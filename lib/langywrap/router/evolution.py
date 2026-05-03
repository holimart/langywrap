"""
langywrap.router.evolution — HyperAgent-driven pipeline evolution.

StepEvolver maintains a population of ``Pipeline`` variants, each with a
fitness score derived from real ralph-cycle metrics (quality, speed, cost).
The evolver selects parents by weighted fitness+novelty, applies random
mutations to the ``Step`` list, and saves variants to disk for persistence.

Mutation operators (mirroring the prior RouteEvolver operators, retargeted
to ``Step`` objects now that routing lives on the pipeline DSL):
  - swap_model        : change the model for one step
  - change_timeout    : increase or decrease a step timeout
  - change_retry      : add/remove a model from a step's fallback chain
  - swap_engine       : change the engine for one step
  - change_tier       : change tier (rewrites model to a matching one)
  - toggle_enabled    : enable/disable an optional step

Archive format: one JSON file per variant in ``archive_dir/``.
Each file: ``<variant_id>.json`` containing a PipelineVariant dict.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import random
import time
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from langywrap.ralph.pipeline import Pipeline, Step

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model tiers (cost buckets for the mutation search space)
# ---------------------------------------------------------------------------


class ModelTier(str, Enum):
    """Cost/capability tier for a model. Used by ``change_tier`` to pick
    replacements. Not stored on ``Step`` — the evolver recomputes tier by
    looking up the model in ``_MODELS_BY_TIER``."""

    CHEAP = "cheap"
    MID = "mid"
    EXPENSIVE = "expensive"


_MODELS_BY_TIER: dict[ModelTier, list[str]] = {
    ModelTier.CHEAP: [
        "claude-haiku-4-5-20251001",
        "openrouter/moonshotai/kimi-k2.6",
        "openrouter/mistralai/mistral-nemo",
        "openrouter/google/gemini-flash-1.5",
        "openrouter/meta-llama/llama-3.1-8b-instruct:free",
    ],
    ModelTier.MID: [
        "claude-sonnet-4-6",
        "openrouter/moonshotai/kimi-k2.6",
        "openrouter/mistralai/mistral-large-2411",
        "openrouter/google/gemini-pro-1.5",
        "openrouter/nvidia/llama-3.1-nemotron-70b-instruct",
    ],
    ModelTier.EXPENSIVE: [
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "openrouter/openai/gpt-4o",
        "openrouter/anthropic/claude-3-5-sonnet",
    ],
}


def _tier_for_model(model: str) -> ModelTier:
    """Look up the tier a model belongs to; default to CHEAP if unknown."""
    for tier, models in _MODELS_BY_TIER.items():
        if model in models:
            return tier
    return ModelTier.CHEAP


_ALL_ENGINES = ["claude", "opencode", "openrouter"]

_MUTATION_NAMES = [
    "swap_model",
    "change_timeout",
    "change_retry",
    "swap_engine",
    "change_tier",
    "toggle_enabled",
]


# ---------------------------------------------------------------------------
# PipelineVariant
# ---------------------------------------------------------------------------


class PipelineVariant(BaseModel):
    """A versioned ``Pipeline`` with evolutionary metadata.

    Fields
    ------
    variant_id:
        Unique string identifier (derived from content hash).
    pipeline:
        The actual pipeline (pydantic model; persistable as JSON).
    fitness_score:
        Scalar fitness (higher = better). Typically a weighted combination
        of quality, speed, and cost metrics from real ralph cycles.
    generation:
        Which generation produced this variant (0 = seed/default).
    parent_id:
        variant_id of the parent, or ``""`` for seed variants.
    mutations:
        List of mutation descriptions applied from parent → this variant.
    created_at:
        Unix timestamp when this variant was created.
    metrics_history:
        List of raw metric dicts recorded via ``record_result()``.
    """

    variant_id: str = ""
    pipeline: Pipeline
    fitness_score: float = 0.0
    generation: int = 0
    parent_id: str = ""
    mutations: list[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    metrics_history: list[dict[str, Any]] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if not self.variant_id:
            self.variant_id = self._compute_id()

    def _compute_id(self) -> str:
        content = self.pipeline.model_dump_json(exclude_none=True)
        h = hashlib.sha256(f"{content}{self.created_at}".encode()).hexdigest()[:12]
        return f"v{self.generation}_{h}"

    def update_fitness(self, metrics: dict[str, Any]) -> None:
        """Compute and update ``fitness_score`` from raw metrics.

        Default formula (tunable):
          fitness = quality * 0.5 - cost_usd * 0.3 - avg_seconds * 0.0002
                    - (failures / cycles) * 0.4
        """
        quality = float(metrics.get("quality", 0.0))
        cost_usd = float(metrics.get("cost_usd", 0.0))
        avg_seconds = float(metrics.get("avg_seconds", 0.0))
        failures = int(metrics.get("failures", 0))
        cycles = int(metrics.get("cycles", 1))

        failure_penalty = failures / max(cycles, 1) * 0.4

        self.fitness_score = (
            quality * 0.5
            - cost_usd * 0.3
            - avg_seconds * 0.0002
            - failure_penalty
        )
        self.metrics_history.append(metrics)

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# StepEvolver
# ---------------------------------------------------------------------------


class StepEvolver:
    """Maintains a population of ``PipelineVariant`` and evolves it over time.

    Parameters
    ----------
    seed_pipeline:
        Pipeline used when the archive is empty. Callers pass their
        project's ``.langywrap/ralph.py`` pipeline here.
    archive_dir:
        Directory where variant JSON files are stored. Created if missing.
    rng_seed:
        Optional seed for reproducible mutations (useful for testing).
    """

    def __init__(
        self,
        seed_pipeline: Pipeline,
        archive_dir: Path,
        rng_seed: int | None = None,
    ) -> None:
        self._archive_dir = archive_dir
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        self._rng = random.Random(rng_seed)
        self._population: list[PipelineVariant] = []
        self._load_archive()
        if not self._population:
            seed = PipelineVariant(
                pipeline=seed_pipeline,
                fitness_score=0.0,
                generation=0,
                parent_id="",
                mutations=["seed:default"],
            )
            self._population.append(seed)
            self._save_variant(seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def mutate(self, parent: PipelineVariant) -> PipelineVariant:
        """Apply a random mutation to ``parent`` and return a new variant."""
        mutation_name = self._rng.choice(_MUTATION_NAMES)
        new_pipeline, description = self._apply_mutation(parent.pipeline, mutation_name)

        child = PipelineVariant(
            pipeline=new_pipeline,
            fitness_score=0.0,
            generation=parent.generation + 1,
            parent_id=parent.variant_id,
            mutations=parent.mutations + [description],
            created_at=time.time(),
        )
        self._population.append(child)
        self._save_variant(child)
        logger.info(
            "Mutated %s → %s via %s",
            parent.variant_id, child.variant_id, description,
        )
        return child

    def select_parent(self) -> PipelineVariant:
        """Select a parent for the next mutation (fitness + novelty)."""
        if len(self._population) == 1:
            return self._population[0]

        scores = self._compute_selection_scores()
        total = sum(scores)
        if total <= 0:
            return self._rng.choice(self._population)

        r = self._rng.uniform(0, total)
        cumulative = 0.0
        for variant, score in zip(self._population, scores, strict=True):
            cumulative += score
            if r <= cumulative:
                return variant
        return self._population[-1]

    def record_result(self, variant_id: str, metrics: dict[str, Any]) -> None:
        """Update fitness for ``variant_id`` after observing a ralph cycle."""
        for variant in self._population:
            if variant.variant_id == variant_id:
                variant.update_fitness(metrics)
                self._save_variant(variant)
                logger.info(
                    "Recorded result for %s: fitness=%.4f",
                    variant_id, variant.fitness_score,
                )
                return
        logger.warning("record_result: variant_id %r not found", variant_id)

    def get_best(self) -> PipelineVariant:
        """Return the highest-fitness variant with at least one recorded result."""
        scored = [v for v in self._population if v.metrics_history]
        if not scored:
            return self._population[0]
        return max(scored, key=lambda v: v.fitness_score)

    def get_explorative(self) -> PipelineVariant:
        """Return a mutated child of a randomly selected parent."""
        parent = self.select_parent()
        return self.mutate(parent)

    def list_variants(self) -> list[PipelineVariant]:
        """Return the population sorted by fitness descending."""
        return sorted(self._population, key=lambda v: v.fitness_score, reverse=True)

    # ------------------------------------------------------------------
    # Mutation operators
    # ------------------------------------------------------------------

    def _apply_mutation(
        self,
        pipeline: Pipeline,
        mutation_name: str,
    ) -> tuple[Pipeline, str]:
        ops = {
            "swap_model": self._mut_swap_model,
            "change_timeout": self._mut_change_timeout,
            "change_retry": self._mut_change_retry,
            "swap_engine": self._mut_swap_engine,
            "change_tier": self._mut_change_tier,
            "toggle_enabled": self._mut_toggle_enabled,
        }
        op = ops.get(mutation_name, self._mut_swap_model)
        return op(pipeline)

    def _clone(self, pipeline: Pipeline) -> tuple[Pipeline, list[Step]]:
        """Return a deep-copy of the pipeline and a list of its Step items."""
        new = copy.deepcopy(pipeline)
        steps = [s for s in new.steps if isinstance(s, Step)]
        return new, steps

    def _pick_step(self, steps: list[Step]) -> int:
        return self._rng.randrange(len(steps))

    def _mut_swap_model(self, pipeline: Pipeline) -> tuple[Pipeline, str]:
        new, steps = self._clone(pipeline)
        if not steps:
            return new, "swap_model:noop"
        idx = self._pick_step(steps)
        step = steps[idx]
        tier = _tier_for_model(step.model)
        candidates = [m for m in _MODELS_BY_TIER[tier] if m != step.model]
        if not candidates:
            candidates = _MODELS_BY_TIER[ModelTier.CHEAP]
        new_model = self._rng.choice(candidates)
        old_model = step.model
        step.model = new_model
        return new, f"swap_model:{step.name}:{old_model}→{new_model}"

    def _mut_change_timeout(self, pipeline: Pipeline) -> tuple[Pipeline, str]:
        new, steps = self._clone(pipeline)
        if not steps:
            return new, "change_timeout:noop"
        idx = self._pick_step(steps)
        step = steps[idx]
        old_t = step.timeout
        factor = self._rng.choice([0.5, 0.75, 1.25, 1.5, 2.0])
        new_t = max(5, int(old_t * factor))
        step.timeout = new_t
        return new, f"change_timeout:{step.name}:{old_t}min→{new_t}min"

    def _mut_change_retry(self, pipeline: Pipeline) -> tuple[Pipeline, str]:
        new, steps = self._clone(pipeline)
        if not steps:
            return new, "change_retry:noop"
        idx = self._pick_step(steps)
        step = steps[idx]
        tier = _tier_for_model(step.model)
        pool = _MODELS_BY_TIER.get(tier, _MODELS_BY_TIER[ModelTier.CHEAP])

        # The chain is ``step.fallback`` (single model). Add or remove it.
        action = self._rng.choice(["add", "remove"])
        if action == "remove" and step.fallback:
            removed = step.fallback
            step.fallback = ""
            return new, f"change_retry:{step.name}:remove:{removed}"
        candidates = [m for m in pool if m != step.model]
        if not candidates:
            return new, "change_retry:noop"
        new_fb = self._rng.choice(candidates)
        step.fallback = new_fb
        return new, f"change_retry:{step.name}:add:{new_fb}"

    def _mut_swap_engine(self, pipeline: Pipeline) -> tuple[Pipeline, str]:
        new, steps = self._clone(pipeline)
        if not steps:
            return new, "swap_engine:noop"
        idx = self._pick_step(steps)
        step = steps[idx]
        candidates = [e for e in _ALL_ENGINES if e != step.engine]
        if not candidates:
            return new, "swap_engine:noop"
        new_engine = self._rng.choice(candidates)
        old_engine = step.engine
        step.engine = new_engine
        return new, f"swap_engine:{step.name}:{old_engine}→{new_engine}"

    def _mut_change_tier(self, pipeline: Pipeline) -> tuple[Pipeline, str]:
        new, steps = self._clone(pipeline)
        if not steps:
            return new, "change_tier:noop"
        idx = self._pick_step(steps)
        step = steps[idx]
        old_tier = _tier_for_model(step.model)
        new_tier = self._rng.choice([t for t in ModelTier if t != old_tier])
        pool = _MODELS_BY_TIER.get(new_tier, [])
        if pool:
            step.model = self._rng.choice(pool)
        return new, f"change_tier:{step.name}:{old_tier.value}→{new_tier.value}"

    def _mut_toggle_enabled(self, pipeline: Pipeline) -> tuple[Pipeline, str]:
        new, steps = self._clone(pipeline)
        if not steps:
            return new, "toggle_enabled:noop"
        idx = self._pick_step(steps)
        step = steps[idx]
        old = step.enabled
        step.enabled = not old
        return new, f"toggle_enabled:{step.name}:{old}→{step.enabled}"

    # ------------------------------------------------------------------
    # Selection scoring
    # ------------------------------------------------------------------

    def _compute_selection_scores(self) -> list[float]:
        fitnesses = [max(0.0, v.fitness_score) for v in self._population]
        max_f = max(fitnesses) if fitnesses else 1.0
        max_f = max_f or 1.0

        scores: list[float] = []
        for variant, raw_f in zip(self._population, fitnesses, strict=True):
            fitness_norm = raw_f / max_f
            novelty = 1.0 / (1.0 + len(variant.metrics_history))
            score = fitness_norm * 0.7 + novelty * 0.3
            scores.append(max(score, 0.01))
        return scores

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _variant_path(self, variant_id: str) -> Path:
        return self._archive_dir / f"{variant_id}.json"

    def _save_variant(self, variant: PipelineVariant) -> None:
        path = self._variant_path(variant.variant_id)
        try:
            path.write_text(variant.model_dump_json(indent=2))
        except Exception as exc:
            logger.error("Failed to save variant %s: %s", variant.variant_id, exc)

    def _load_archive(self) -> None:
        self._population = []
        for path in sorted(self._archive_dir.glob("v*.json")):
            try:
                data = json.loads(path.read_text())
                variant = PipelineVariant.model_validate(data)
                self._population.append(variant)
            except Exception as exc:
                logger.warning("Skipping corrupt archive file %s: %s", path.name, exc)
        logger.info(
            "Loaded %d variants from archive %s", len(self._population), self._archive_dir
        )
