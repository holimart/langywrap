"""Mutation operators for agent variant evolution.

Implements both random mutations (cheap) and meta-mutations (expensive,
using an LLM to analyze performance and propose intelligent changes).
"""

from __future__ import annotations

import contextlib
import copy
import random
import uuid
from enum import Enum
from typing import TYPE_CHECKING, Any

from langywrap.hyperagents.archive import AgentVariant

if TYPE_CHECKING:
    from langywrap.router.router import ExecutionRouter


class MutationType(str, Enum):
    SWAP_MODEL = "swap_model"
    CHANGE_TIMEOUT = "change_timeout"
    ADD_STEP = "add_step"
    REMOVE_STEP = "remove_step"
    CHANGE_RETRY_CHAIN = "change_retry_chain"
    MODIFY_PROMPT_TEMPLATE = "modify_prompt_template"
    CHANGE_REVIEW_FREQUENCY = "change_review_frequency"
    SWAP_QUALITY_GATE = "swap_quality_gate"
    CHANGE_SKILL_SELECTION = "change_skill_selection"
    SWAP_BACKEND = "swap_backend"


# Available models for swapping
AVAILABLE_MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "nvidia/moonshotai/kimi-k2.5",
    "nvidia/deepseek/deepseek-r1",
    "openai/gpt-4o",
    "openai/gpt-5.2",
    "openai/o3-mini",
]

AVAILABLE_BACKENDS = ["claude", "opencode", "openrouter", "direct_api"]

# Steps that can be added (optional steps not in default pipeline)
OPTIONAL_STEPS = ["adversarial", "validate", "lean_retry"]

# Model used by the meta-agent to suggest intelligent mutations. No role
# indirection — caller names the model directly (opus-class is the right
# default; override per project if you want it cheaper).
META_REVIEW_MODEL = "claude-opus-4-6"
META_REVIEW_ENGINE = "claude"
META_REVIEW_TIMEOUT_MINUTES = 45


def mutate(
    parent: AgentVariant,
    mutation_types: list[MutationType] | None = None,
    n_mutations: int = 1,
) -> AgentVariant:
    """Apply random mutations to create a child variant."""
    child_config = copy.deepcopy(parent.config)
    applied: list[str] = []

    if mutation_types is None:
        mutation_types = [
            MutationType.SWAP_MODEL,
            MutationType.CHANGE_TIMEOUT,
            MutationType.CHANGE_RETRY_CHAIN,
            MutationType.CHANGE_REVIEW_FREQUENCY,
            MutationType.SWAP_BACKEND,
        ]

    for _ in range(n_mutations):
        mt = random.choice(mutation_types)
        desc = _apply_mutation(child_config, mt)
        if desc:
            applied.append(desc)

    return AgentVariant(
        id=str(uuid.uuid4())[:12],
        generation=parent.generation + 1,
        parent_id=parent.id,
        config=child_config,
        mutations=applied,
        project_origin=parent.project_origin,
    )


def _apply_mutation(config: dict[str, Any], mt: MutationType) -> str | None:
    """Apply a single mutation to config. Returns description or None."""
    routes = config.get("routes", {})
    steps = config.get("steps", [])

    if mt == MutationType.SWAP_MODEL:
        if not routes:
            return None
        role = random.choice(list(routes.keys()))
        old_model = routes[role].get("model", "unknown")
        new_model = random.choice([m for m in AVAILABLE_MODELS if m != old_model])
        routes[role]["model"] = new_model
        return f"swap_model:{role}:{old_model}->{new_model}"

    elif mt == MutationType.CHANGE_TIMEOUT:
        if not routes:
            return None
        role = random.choice(list(routes.keys()))
        old_timeout = routes[role].get("timeout_minutes", 30)
        factor = random.choice([0.5, 0.75, 1.25, 1.5, 2.0])
        new_timeout = max(5, int(old_timeout * factor))
        routes[role]["timeout_minutes"] = new_timeout
        return f"change_timeout:{role}:{old_timeout}->{new_timeout}min"

    elif mt == MutationType.CHANGE_RETRY_CHAIN:
        if not routes:
            return None
        role = random.choice(list(routes.keys()))
        n_retries = random.randint(1, 4)
        retry_models = random.sample(AVAILABLE_MODELS, min(n_retries, len(AVAILABLE_MODELS)))
        routes[role]["retry_models"] = retry_models
        return f"change_retry:{role}:chain={retry_models}"

    elif mt == MutationType.CHANGE_REVIEW_FREQUENCY:
        old_n = config.get("review_every_n", 10)
        new_n = random.choice([5, 8, 10, 12, 15, 20])
        config["review_every_n"] = new_n
        return f"change_review_freq:{old_n}->{new_n}"

    elif mt == MutationType.SWAP_BACKEND:
        if not routes:
            return None
        role = random.choice(list(routes.keys()))
        old_backend = routes[role].get("backend", "claude")
        new_backend = random.choice([b for b in AVAILABLE_BACKENDS if b != old_backend])
        routes[role]["backend"] = new_backend
        return f"swap_backend:{role}:{old_backend}->{new_backend}"

    elif mt == MutationType.ADD_STEP:
        existing_names = [s.get("name") for s in steps]
        candidates = [s for s in OPTIONAL_STEPS if s not in existing_names]
        if not candidates:
            return None
        new_step = random.choice(candidates)
        steps.append({"name": new_step, "enabled": True})
        config["steps"] = steps
        return f"add_step:{new_step}"

    elif mt == MutationType.REMOVE_STEP:
        removable = [s for s in steps if s.get("name") in OPTIONAL_STEPS]
        if not removable:
            return None
        to_remove = random.choice(removable)
        steps.remove(to_remove)
        config["steps"] = steps
        return f"remove_step:{to_remove.get('name')}"

    elif mt == MutationType.MODIFY_PROMPT_TEMPLATE:
        # Flag for meta-agent rewrite — stores a marker
        if not routes:
            return None
        role = random.choice(list(routes.keys()))
        config.setdefault("prompt_modifications", {})[role] = "pending_meta_rewrite"
        return f"flag_prompt_rewrite:{role}"

    elif mt == MutationType.CHANGE_SKILL_SELECTION:
        skills = config.get("selected_skills", [])
        action = random.choice(["add", "remove", "swap"])
        if action == "add":
            skills.append(f"auto_skill_{random.randint(100, 999)}")
        elif action == "remove" and skills:
            skills.pop(random.randrange(len(skills)))
        elif action == "swap" and skills:
            idx = random.randrange(len(skills))
            skills[idx] = f"auto_skill_{random.randint(100, 999)}"
        config["selected_skills"] = skills
        return f"change_skills:{action}"

    return None


def meta_mutate(
    parent: AgentVariant,
    router: ExecutionRouter,
) -> AgentVariant:
    """Use an expensive model to analyze performance and propose intelligent mutations.

    This is the DGM-H key innovation: the meta-agent examines the parent's
    metrics and configuration, then proposes targeted improvements rather
    than random changes.
    """
    prompt = f"""You are a meta-agent optimizing AI agent configurations.

Current agent variant (generation {parent.generation}):
- Fitness: {parent.fitness_score:.4f}
- Metrics: {parent.metrics}
- Config: {parent.config}
- Previous mutations: {parent.mutations}

Analyze the performance and suggest exactly 1-3 specific configuration changes.
For each change, output a line in this format:
MUTATION: <type>|<key>|<old_value>|<new_value>

Available mutation types: {[m.value for m in MutationType]}
Available models: {AVAILABLE_MODELS}
Available backends: {AVAILABLE_BACKENDS}

Focus on the weakest metrics. If cost is high, try cheaper models for non-critical steps.
If quality is low, try better models for critical steps (execute, critic).
If timeouts are frequent, increase timeout or switch to faster models.
"""

    try:
        from langywrap.router.backends import SubagentResult

        # Meta-reasoning: pick the most capable model we know about and dispatch
        # directly. The former StepRole.REVIEW routing rule is gone — callers
        # that need "the expensive model" name it here.
        result: SubagentResult = router.execute(
            prompt=prompt,
            model=META_REVIEW_MODEL,
            engine=META_REVIEW_ENGINE,
            timeout_minutes=META_REVIEW_TIMEOUT_MINUTES,
            tag="hyperagents.meta_review",
        )

        child_config = copy.deepcopy(parent.config)
        applied: list[str] = []

        for line in result.text.splitlines():
            if line.startswith("MUTATION:"):
                parts = line[9:].strip().split("|")
                if len(parts) >= 3:
                    desc = f"meta:{parts[0].strip()}:{parts[1].strip()}"
                    # Apply the mutation to config
                    _apply_meta_suggestion(child_config, parts)
                    applied.append(desc)

        if not applied:
            # Fallback to random mutation if meta-agent didn't produce parseable output
            return mutate(parent, n_mutations=2)

        return AgentVariant(
            id=str(uuid.uuid4())[:12],
            generation=parent.generation + 1,
            parent_id=parent.id,
            config=child_config,
            mutations=applied,
            project_origin=parent.project_origin,
        )

    except Exception as exc:
        import logging
        logging.getLogger("langywrap.hyperagents").warning(
            "meta_mutate failed, falling back to random mutation: %s", exc
        )
        return mutate(parent, n_mutations=2)


def _apply_meta_suggestion(config: dict[str, Any], parts: list[str]) -> None:
    """Apply a parsed meta-agent suggestion to config."""
    mutation_type = parts[0].strip()
    key = parts[1].strip()
    new_value = parts[-1].strip()

    routes = config.setdefault("routes", {})

    if mutation_type == MutationType.SWAP_MODEL.value and key in routes:
        routes[key]["model"] = new_value
    elif mutation_type == MutationType.CHANGE_TIMEOUT.value and key in routes:
        with contextlib.suppress(ValueError):
            routes[key]["timeout_minutes"] = int(new_value)
    elif mutation_type == MutationType.SWAP_BACKEND.value and key in routes:
        routes[key]["backend"] = new_value
    elif mutation_type == MutationType.CHANGE_REVIEW_FREQUENCY.value:
        with contextlib.suppress(ValueError):
            config["review_every_n"] = int(new_value)
