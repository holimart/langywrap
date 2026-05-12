"""Model provider mix helpers for Ralph configs and inspection.

The functions here intentionally sit outside the CLI/runner so dry-run reports
and external inspectors use the same counting and provider bucketing logic.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from langywrap.ralph.aliases import BUILTIN_ALIASES
from langywrap.ralph.config import (
    ModelSubstitution,
    RalphConfig,
    StepConfig,
    apply_model_substitutions,
    load_ralph_config,
    parse_model_substitutions,
    substitute_model_name,
)


def provider_for_model(model: str) -> str:
    """Return the coarse provider bucket used in status output."""
    normalized = model.strip().lower()
    if not normalized:
        return "other"
    if (
        normalized.startswith("claude-")
        or normalized.startswith("anthropic/")
        or normalized.startswith("openrouter/anthropic/")
    ):
        return "anthropic"
    if (
        normalized.startswith("openai/")
        or normalized.startswith("gpt-")
        or normalized.startswith("o1-")
        or normalized.startswith("o3-")
        or normalized.startswith("o4-")
        or normalized.startswith("openrouter/openai/")
    ):
        return "openai"
    return "other"


def summarize_model_slots(slots: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize resolved model slots into provider percentages."""
    provider_counts: Counter[str] = Counter()
    model_counts: Counter[str] = Counter()

    for slot in slots:
        model = str(slot.get("model") or "")
        if not model:
            continue
        provider = provider_for_model(model)
        provider_counts[provider] += 1
        model_counts[model] += 1

    total = sum(provider_counts.values())
    providers = {}
    for provider in ("anthropic", "openai", "other"):
        count = provider_counts.get(provider, 0)
        providers[provider] = {
            "count": count,
            "percent": round((count / total) * 100, 1) if total else 0.0,
        }

    return {
        "total_slots": total,
        "providers": providers,
        "models": dict(sorted(model_counts.items())),
        "slots": slots,
    }


def config_model_mix(config: RalphConfig) -> dict[str, Any]:
    """Return primary model usage mix for a resolved RalphConfig."""
    slots: list[dict[str, Any]] = []
    retry_slots: list[dict[str, Any]] = []

    for step in config.steps:
        if step.builtin:
            continue
        if step.model:
            slots.append(_step_slot(step, step.model, role="primary"))
        if step.retry_model:
            retry_slots.append(_step_slot(step, step.retry_model, role="retry"))
        for model in step.retry_models:
            if model:
                retry_slots.append(_step_slot(step, model, role="fallback"))

    summary = summarize_model_slots(slots)
    summary["retry_and_fallback"] = summarize_model_slots(retry_slots)
    return summary


def project_model_mix(
    project_dir: Path,
    replacement_specs: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """Load a project like the Ralph CLI and return its effective model mix."""
    substitutions = parse_model_substitutions(replacement_specs)

    # Match CLI precedence: Module pipeline first, then declarative Pipeline/YAML.
    from langywrap.ralph.module import load_module_config

    module = load_module_config(project_dir)
    if module is not None:
        mix = module_model_mix(module, substitutions)
        mix["source"] = "module"
    else:
        config = load_ralph_config(project_dir)
        config = apply_model_substitutions(config, substitutions)
        mix = config_model_mix(config)
        mix["source"] = "config"

    mix["replacements"] = list(replacement_specs)
    return mix


def module_model_mix(module: Any, substitutions: list[ModelSubstitution] | None = None) -> dict[str, Any]:
    """Return model mix for a Module-based Ralph pipeline."""
    substitutions = substitutions or []
    slots: list[dict[str, Any]] = []

    for name, step_def in module._step_defs.items():
        if not step_def.enabled:
            continue
        model = BUILTIN_ALIASES.get(step_def.model, step_def.model)
        model = substitute_model_name(model, substitutions)
        if not model:
            continue
        slots.append(
            {
                "step": name,
                "model": model,
                "role": "primary",
                "pipeline": True,
                "timeout_minutes": step_def.timeout,
            }
        )

    return summarize_model_slots(slots)


def _step_slot(step: StepConfig, model: str, *, role: str) -> dict[str, Any]:
    slot: dict[str, Any] = {
        "step": step.name,
        "model": model,
        "role": role,
        "pipeline": step.pipeline,
        "timeout_minutes": step.timeout_minutes,
    }
    if step.run_if_cycle_types:
        slot["when_cycle"] = list(step.run_if_cycle_types)
    if step.output_as:
        slot["output_as"] = step.output_as
    return slot
