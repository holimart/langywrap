"""
langywrap.router.evolution — HyperAgent-driven RouteConfig evolution.

RouteEvolver maintains a population of RouteConfig variants, each with a
fitness score derived from real ralph-cycle metrics (quality, speed, cost).
The evolver selects parents by weighted fitness+novelty, applies random
mutations, and saves variants to disk for persistence across runs.

Mutation operators (mirroring riemann2 HyperAgent patterns):
  - swap_model        : change the model for one role
  - change_timeout    : increase or decrease a step timeout
  - change_retry      : add/remove a model from a retry chain
  - change_review_n   : adjust how often deep-review fires
  - swap_backend      : change the backend for one role
  - change_tier       : change ModelTier for a role (affects cost accounting)

Archive format: one JSON file per variant in ``archive_dir/``.
Each file: ``<variant_id>.json`` containing a RouteConfigVariant dict.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .backends import Backend
from .config import (
    DEFAULT_ROUTE_CONFIG,
    ModelTier,
    RouteConfig,
    RouteRule,
    save_route_config,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Available models per tier (the mutation search space)
# ---------------------------------------------------------------------------

_MODELS_BY_TIER: dict[ModelTier, list[str]] = {
    ModelTier.CHEAP: [
        "claude-haiku-4-5-20251001",
        "openrouter/moonshotai/kimi-k2.5",
        "openrouter/mistralai/mistral-nemo",
        "openrouter/google/gemini-flash-1.5",
        "openrouter/meta-llama/llama-3.1-8b-instruct:free",
    ],
    ModelTier.MID: [
        "claude-sonnet-4-5-20251001",
        "openrouter/moonshotai/kimi-k2.5",
        "openrouter/mistralai/mistral-large-2411",
        "openrouter/google/gemini-pro-1.5",
        "openrouter/nvidia/llama-3.1-nemotron-70b-instruct",
    ],
    ModelTier.EXPENSIVE: [
        "claude-opus-4-5-20251001",
        "claude-sonnet-4-5-20251001",
        "openrouter/openai/gpt-4o",
        "openrouter/anthropic/claude-3-5-sonnet",
    ],
}

_ALL_BACKENDS = [Backend.CLAUDE, Backend.OPENCODE, Backend.OPENROUTER]

_MUTATION_NAMES = [
    "swap_model",
    "change_timeout",
    "change_retry",
    "change_review_n",
    "swap_backend",
    "change_tier",
]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class RouteConfigVariant(BaseModel):
    """
    A versioned RouteConfig with evolutionary metadata.

    Fields
    ------
    variant_id:
        Unique string identifier (derived from content hash).
    config:
        The actual routing configuration.
    fitness_score:
        Scalar fitness (higher = better).  Typically a weighted combination of
        quality, speed, and cost metrics from real ralph cycles.
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
    config: RouteConfig
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
        """Deterministic ID: hash of config content + creation timestamp."""
        content = self.config.model_dump_json(exclude_none=True)
        h = hashlib.sha256(f"{content}{self.created_at}".encode()).hexdigest()[:12]
        return f"v{self.generation}_{h}"

    def update_fitness(self, metrics: dict[str, Any]) -> None:
        """
        Compute and update fitness_score from raw metrics.

        Default fitness formula (tunable):
          fitness = quality * 0.5 - cost_usd * 0.3 - avg_seconds * 0.0002

        Where:
          ``quality``     — 0.0–1.0 (fraction of cycles passing quality gate)
          ``cost_usd``    — total estimated cost in USD
          ``avg_seconds`` — average step duration in seconds
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
# RouteEvolver
# ---------------------------------------------------------------------------


class RouteEvolver:
    """
    Maintains a population of RouteConfigVariant and evolves it over time.

    Parameters
    ----------
    archive_dir:
        Directory where variant JSON files are stored.  Created if missing.
    rng_seed:
        Optional seed for reproducible mutations (useful for testing).
    """

    def __init__(
        self,
        archive_dir: Path,
        rng_seed: int | None = None,
    ) -> None:
        self._archive_dir = archive_dir
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        self._rng = random.Random(rng_seed)
        self._population: list[RouteConfigVariant] = []
        self._load_archive()
        if not self._population:
            # Seed with the default config
            seed = RouteConfigVariant(
                config=DEFAULT_ROUTE_CONFIG,
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

    def mutate(self, parent: RouteConfigVariant) -> RouteConfigVariant:
        """
        Apply a random mutation to ``parent`` and return a new variant.

        The mutation is recorded in ``mutations``.  The child's fitness_score
        starts at 0.0 (unscored) until ``record_result`` is called.
        """
        mutation_name = self._rng.choice(_MUTATION_NAMES)
        new_config, description = self._apply_mutation(parent.config, mutation_name)

        child = RouteConfigVariant(
            config=new_config,
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

    def select_parent(self) -> RouteConfigVariant:
        """
        Select a parent for the next mutation.

        Uses a combined fitness+novelty score:
          - fitness component: normalised fitness across population
          - novelty component: reward under-explored variants (fewer metrics_history entries)

        Returns the selected variant.
        """
        if len(self._population) == 1:
            return self._population[0]

        scores = self._compute_selection_scores()
        total = sum(scores)
        if total <= 0:
            return self._rng.choice(self._population)

        # Weighted random selection
        r = self._rng.uniform(0, total)
        cumulative = 0.0
        for variant, score in zip(self._population, scores, strict=True):
            cumulative += score
            if r <= cumulative:
                return variant
        return self._population[-1]

    def record_result(self, variant_id: str, metrics: dict[str, Any]) -> None:
        """
        Update fitness for ``variant_id`` after observing a ralph cycle.

        ``metrics`` dict should contain::

            {
                "quality": 0.85,      # fraction of cycles passing quality gate
                "cost_usd": 0.042,    # total estimated cost
                "avg_seconds": 45.2,  # avg step duration
                "failures": 2,        # failed steps
                "cycles": 10,         # total cycles observed
            }
        """
        for variant in self._population:
            if variant.variant_id == variant_id:
                variant.update_fitness(metrics)
                self._save_variant(variant)
                logger.info(
                    "Recorded result for %s: fitness=%.4f",
                    variant_id, variant.fitness_score,
                )
                return
        logger.warning("record_result: variant_id %r not found in population", variant_id)

    def get_best(self) -> RouteConfigVariant:
        """Return the highest-fitness variant with at least one recorded result."""
        scored = [v for v in self._population if v.metrics_history]
        if not scored:
            return self._population[0]
        return max(scored, key=lambda v: v.fitness_score)

    def get_explorative(self) -> RouteConfigVariant:
        """Return a mutated child of a randomly selected parent for exploration."""
        parent = self.select_parent()
        return self.mutate(parent)

    def list_variants(self) -> list[RouteConfigVariant]:
        """Return a copy of the current population, sorted by fitness descending."""
        return sorted(self._population, key=lambda v: v.fitness_score, reverse=True)

    def export_best(self, project_dir: Path) -> Path:
        """
        Write the best variant's RouteConfig to ``project_dir/.langywrap/router.yaml``.

        Returns the path written.
        """
        best = self.get_best()
        path = save_route_config(best.config, project_dir)
        logger.info("Exported best config (%s) to %s", best.variant_id, path)
        return path

    # ------------------------------------------------------------------
    # Mutation operators
    # ------------------------------------------------------------------

    def _apply_mutation(
        self,
        config: RouteConfig,
        mutation_name: str,
    ) -> tuple[RouteConfig, str]:
        """Dispatch to the named mutation operator. Returns (new_config, description)."""
        ops = {
            "swap_model": self._mut_swap_model,
            "change_timeout": self._mut_change_timeout,
            "change_retry": self._mut_change_retry,
            "change_review_n": self._mut_change_review_n,
            "swap_backend": self._mut_swap_backend,
            "change_tier": self._mut_change_tier,
        }
        op = ops.get(mutation_name, self._mut_swap_model)
        return op(config)

    def _clone_rules(self, config: RouteConfig) -> tuple[RouteConfig, list[RouteRule]]:
        """Return a new config and a mutable copy of its rules."""
        rules = [rule.model_copy(deep=True) for rule in config.rules]
        new_cfg = config.model_copy(deep=True)
        new_cfg.rules = rules
        return new_cfg, rules

    def _pick_rule(self, rules: list[RouteRule]) -> int:
        """Pick a random rule index."""
        return self._rng.randrange(len(rules))

    def _mut_swap_model(self, config: RouteConfig) -> tuple[RouteConfig, str]:
        """Swap the model for a randomly chosen rule."""
        new_cfg, rules = self._clone_rules(config)
        if not rules:
            return new_cfg, "swap_model:noop"
        idx = self._pick_rule(rules)
        rule = rules[idx]
        candidates = [
            m for m in _MODELS_BY_TIER.get(rule.tier, _MODELS_BY_TIER[ModelTier.CHEAP])
            if m != rule.model
        ]
        if not candidates:
            candidates = _MODELS_BY_TIER[ModelTier.CHEAP]
        new_model = self._rng.choice(candidates)
        old_model = rule.model
        rule.model = new_model
        description = f"swap_model:{rule.role.value}:{old_model}→{new_model}"
        return new_cfg, description

    def _mut_change_timeout(self, config: RouteConfig) -> tuple[RouteConfig, str]:
        """Increase or decrease a step timeout by 10–50%."""
        new_cfg, rules = self._clone_rules(config)
        if not rules:
            return new_cfg, "change_timeout:noop"
        idx = self._pick_rule(rules)
        rule = rules[idx]
        old_t = rule.timeout_minutes
        factor = self._rng.choice([0.5, 0.75, 1.25, 1.5, 2.0])
        new_t = max(5, int(old_t * factor))
        rule.timeout_minutes = new_t
        description = f"change_timeout:{rule.role.value}:{old_t}min→{new_t}min"
        return new_cfg, description

    def _mut_change_retry(self, config: RouteConfig) -> tuple[RouteConfig, str]:
        """Add or remove a model from a rule's retry chain."""
        new_cfg, rules = self._clone_rules(config)
        if not rules:
            return new_cfg, "change_retry:noop"
        idx = self._pick_rule(rules)
        rule = rules[idx]
        pool = _MODELS_BY_TIER.get(rule.tier, _MODELS_BY_TIER[ModelTier.CHEAP])

        action = self._rng.choice(["add", "remove"])
        if action == "remove" and rule.retry_models:
            removed = self._rng.choice(rule.retry_models)
            rule.retry_models = [m for m in rule.retry_models if m != removed]
            description = f"change_retry:{rule.role.value}:remove:{removed}"
        else:
            new_model = self._rng.choice(pool)
            if new_model not in rule.retry_models:
                rule.retry_models.append(new_model)
            description = f"change_retry:{rule.role.value}:add:{new_model}"

        return new_cfg, description

    def _mut_change_review_n(self, config: RouteConfig) -> tuple[RouteConfig, str]:
        """Adjust review_every_n by ±1 to ±5 cycles."""
        new_cfg, rules = self._clone_rules(config)
        old_n = new_cfg.review_every_n
        delta = self._rng.choice([-5, -3, -1, 1, 3, 5])
        new_n = max(1, old_n + delta)
        new_cfg.review_every_n = new_n
        description = f"change_review_n:{old_n}→{new_n}"
        return new_cfg, description

    def _mut_swap_backend(self, config: RouteConfig) -> tuple[RouteConfig, str]:
        """Change the backend for a randomly chosen rule."""
        new_cfg, rules = self._clone_rules(config)
        if not rules:
            return new_cfg, "swap_backend:noop"
        idx = self._pick_rule(rules)
        rule = rules[idx]
        candidates = [b for b in _ALL_BACKENDS if b != rule.backend]
        if not candidates:
            return new_cfg, "swap_backend:noop"
        new_backend = self._rng.choice(candidates)
        old_backend = rule.backend
        rule.backend = new_backend
        description = f"swap_backend:{rule.role.value}:{old_backend.value}→{new_backend.value}"
        return new_cfg, description

    def _mut_change_tier(self, config: RouteConfig) -> tuple[RouteConfig, str]:
        """
        Change the tier for a rule (may also change model to match new tier).
        """
        new_cfg, rules = self._clone_rules(config)
        if not rules:
            return new_cfg, "change_tier:noop"
        idx = self._pick_rule(rules)
        rule = rules[idx]
        old_tier = rule.tier
        new_tier = self._rng.choice([t for t in ModelTier if t != old_tier])
        rule.tier = new_tier
        # Also update the model to a plausible one for the new tier
        candidates = _MODELS_BY_TIER.get(new_tier, [])
        if candidates:
            rule.model = self._rng.choice(candidates)
        description = f"change_tier:{rule.role.value}:{old_tier.value}→{new_tier.value}"
        return new_cfg, description

    # ------------------------------------------------------------------
    # Selection scoring
    # ------------------------------------------------------------------

    def _compute_selection_scores(self) -> list[float]:
        """
        Compute per-variant selection weight = fitness_normalised * 0.7 + novelty * 0.3.

        Novelty = 1 / (1 + len(metrics_history))  — favour less-evaluated variants.
        """
        fitnesses = [max(0.0, v.fitness_score) for v in self._population]
        max_f = max(fitnesses) if fitnesses else 1.0
        max_f = max_f or 1.0  # avoid division by zero

        scores: list[float] = []
        for variant, raw_f in zip(self._population, fitnesses, strict=True):
            fitness_norm = raw_f / max_f
            novelty = 1.0 / (1.0 + len(variant.metrics_history))
            score = fitness_norm * 0.7 + novelty * 0.3
            scores.append(max(score, 0.01))  # minimum weight so all can be selected
        return scores

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _variant_path(self, variant_id: str) -> Path:
        return self._archive_dir / f"{variant_id}.json"

    def _save_variant(self, variant: RouteConfigVariant) -> None:
        path = self._variant_path(variant.variant_id)
        try:
            path.write_text(variant.model_dump_json(indent=2))
        except Exception as exc:
            logger.error("Failed to save variant %s: %s", variant.variant_id, exc)

    def _load_archive(self) -> None:
        """Load all variant JSON files from the archive directory."""
        self._population = []
        for path in sorted(self._archive_dir.glob("v*.json")):
            try:
                data = json.loads(path.read_text())
                variant = RouteConfigVariant.model_validate(data)
                self._population.append(variant)
            except Exception as exc:
                logger.warning("Skipping corrupt archive file %s: %s", path.name, exc)
        logger.info("Loaded %d variants from archive %s", len(self._population), self._archive_dir)
