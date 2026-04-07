"""HyperAgent evolution engine.

Orchestrates the evolution loop: select parent -> mutate -> evaluate -> record.
Every coupled downstream repo participates by running ralph loops that feed
evaluation metrics back to the archive.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from langywrap.hyperagents.archive import AgentVariant, Archive
from langywrap.hyperagents.mutations import meta_mutate, mutate

if TYPE_CHECKING:
    from langywrap.router.router import ExecutionRouter


class HyperAgentEngine:
    """Drives agent evolution across coupled repos.

    The engine alternates between exploitation (use best config) and
    exploration (try mutated variant). Every Nth cycle, it uses an expensive
    model for meta-mutation instead of random mutation.
    """

    def __init__(
        self,
        archive: Archive,
        router: ExecutionRouter,
        project_dir: Path,
        meta_every_n: int = 5,
        explore_ratio: float = 0.3,
    ) -> None:
        self.archive = archive
        self.router = router
        self.project_dir = Path(project_dir)
        self.meta_every_n = meta_every_n
        self.explore_ratio = explore_ratio
        self._evolution_step = 0

    def evolve_step(self, metrics: dict[str, Any] | None = None) -> AgentVariant:
        """One evolution step: select parent, create child, return for evaluation.

        If metrics are provided, they're recorded for the most recent variant first.
        """
        self._evolution_step += 1

        parent = self.archive.select_parent("fitness_novelty")

        if parent is None:
            # Bootstrap: create initial variant from current config
            return self._create_seed_variant()

        # Decide: random mutation (cheap) vs meta-mutation (expensive)
        use_meta = (self._evolution_step % self.meta_every_n) == 0

        if use_meta:
            child = meta_mutate(parent, self.router)
        else:
            n_mutations = 1 if self._evolution_step < 10 else 2
            child = mutate(parent, n_mutations=n_mutations)

        child.project_origin = self.project_dir.name
        self.archive.add(child)
        return child

    def record_evaluation(self, variant_id: str, metrics: dict[str, Any]) -> None:
        """Update variant fitness after ralph cycle(s) complete."""
        self.archive.update_fitness(variant_id, metrics)

    def get_current_best(self) -> AgentVariant | None:
        """Best config for production use."""
        best = self.archive.get_best(n=1)
        return best[0] if best else None

    def get_explorative(self) -> AgentVariant:
        """Next variant to try (mutated from a parent)."""
        return self.evolve_step()

    def should_explore(self, cycle_num: int) -> bool:
        """Decide whether this cycle should explore or exploit.

        Uses explore_ratio: e.g., 0.3 means ~30% of cycles explore.
        """
        import random

        return random.random() < self.explore_ratio

    def apply_variant(self, variant: AgentVariant, project_dir: Path | None = None) -> None:
        """Write variant's config to a project's .langywrap/ directory."""
        target = Path(project_dir) if project_dir else self.project_dir
        langywrap_dir = target / ".langywrap"
        langywrap_dir.mkdir(parents=True, exist_ok=True)

        # Write router config from variant
        if "routes" in variant.config:
            router_path = langywrap_dir / "router.yaml"
            router_path.write_text(
                yaml.dump(variant.config["routes"], default_flow_style=False, sort_keys=False)
            )

        # Write ralph config overrides
        ralph_overrides = {
            k: v
            for k, v in variant.config.items()
            if k in ("review_every_n", "adversarial_every_n", "steps", "selected_skills")
        }
        if ralph_overrides:
            overrides_path = langywrap_dir / "ralph_overrides.yaml"
            overrides_path.write_text(
                yaml.dump(ralph_overrides, default_flow_style=False, sort_keys=False)
            )

        # Record which variant is active
        active_path = langywrap_dir / "active_variant.yaml"
        active_path.write_text(
            yaml.dump(
                {"variant_id": variant.id, "generation": variant.generation},
                default_flow_style=False,
            )
        )

    def _create_seed_variant(self) -> AgentVariant:
        """Create initial variant from project's current config."""
        config: dict[str, Any] = {}

        # Try to load existing router.yaml
        router_yaml = self.project_dir / ".langywrap" / "router.yaml"
        if router_yaml.exists():
            config["routes"] = yaml.safe_load(router_yaml.read_text()) or {}

        # Try to load existing ralph.yaml
        ralph_yaml = self.project_dir / ".langywrap" / "ralph.yaml"
        if ralph_yaml.exists():
            ralph_config = yaml.safe_load(ralph_yaml.read_text()) or {}
            config["review_every_n"] = ralph_config.get("review_every_n", 10)
            config["steps"] = ralph_config.get("steps", [])

        seed = AgentVariant(
            generation=0,
            config=config,
            fitness_score=0.5,  # Neutral starting fitness
            project_origin=self.project_dir.name,
            mutations=["seed"],
        )
        self.archive.add(seed)
        return seed
