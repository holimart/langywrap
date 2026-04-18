from __future__ import annotations

from unittest.mock import MagicMock, patch

from langywrap.hyperagents.archive import AgentVariant
from langywrap.hyperagents.mutations import (
    OPTIONAL_STEPS,
    MutationType,
    _apply_meta_suggestion,
    _apply_mutation,
    meta_mutate,
    mutate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_parent(routes=None, steps=None, **kwargs):
    config = {
        "routes": routes
        or {
            "orient": {
                "model": "claude-haiku-4-5-20251001",
                "timeout_minutes": 30,
                "backend": "claude",
            },
            "execute": {
                "model": "claude-sonnet-4-6",
                "timeout_minutes": 60,
                "backend": "opencode",
            },
        },
        "steps": steps or [],
        "review_every_n": 10,
    }
    config.update(kwargs)
    return AgentVariant(config=config, fitness_score=0.5)


# ---------------------------------------------------------------------------
# mutate()
# ---------------------------------------------------------------------------


def test_mutate_creates_child():
    parent = make_parent()
    child = mutate(parent, n_mutations=1)
    assert child.parent_id == parent.id
    assert child.generation == parent.generation + 1


def test_mutate_multiple_mutations():
    parent = make_parent()
    child = mutate(parent, n_mutations=3)
    assert len(child.mutations) >= 1  # at least 1 non-None mutation applied


def test_mutate_explicit_types():
    parent = make_parent()
    child = mutate(parent, mutation_types=[MutationType.SWAP_MODEL], n_mutations=1)
    assert any("swap_model" in m for m in child.mutations)


def test_mutate_preserves_project_origin():
    parent = make_parent()
    parent = parent.model_copy(update={"project_origin": "myproject"})
    child = mutate(parent)
    assert child.project_origin == "myproject"


# ---------------------------------------------------------------------------
# _apply_mutation — SWAP_MODEL
# ---------------------------------------------------------------------------


def test_apply_mutation_swap_model():
    config = {
        "routes": {"orient": {"model": "claude-haiku-4-5-20251001", "timeout_minutes": 30}},
        "steps": [],
    }
    desc = _apply_mutation(config, MutationType.SWAP_MODEL)
    assert desc is not None
    assert "swap_model" in desc
    assert config["routes"]["orient"]["model"] != "claude-haiku-4-5-20251001" or desc is not None


def test_apply_mutation_swap_model_no_routes():
    config = {"routes": {}, "steps": []}
    desc = _apply_mutation(config, MutationType.SWAP_MODEL)
    assert desc is None


# ---------------------------------------------------------------------------
# _apply_mutation — CHANGE_TIMEOUT
# ---------------------------------------------------------------------------


def test_apply_mutation_change_timeout():
    config = {
        "routes": {"orient": {"model": "x", "timeout_minutes": 30}},
        "steps": [],
    }
    desc = _apply_mutation(config, MutationType.CHANGE_TIMEOUT)
    assert desc is not None
    assert "change_timeout" in desc


def test_apply_mutation_change_timeout_no_routes():
    config = {"routes": {}, "steps": []}
    desc = _apply_mutation(config, MutationType.CHANGE_TIMEOUT)
    assert desc is None


# ---------------------------------------------------------------------------
# _apply_mutation — CHANGE_RETRY_CHAIN
# ---------------------------------------------------------------------------


def test_apply_mutation_change_retry_chain():
    config = {
        "routes": {"orient": {"model": "x", "timeout_minutes": 30}},
        "steps": [],
    }
    desc = _apply_mutation(config, MutationType.CHANGE_RETRY_CHAIN)
    assert desc is not None
    assert "change_retry" in desc
    assert "retry_models" in config["routes"]["orient"]


def test_apply_mutation_change_retry_no_routes():
    config = {"routes": {}, "steps": []}
    desc = _apply_mutation(config, MutationType.CHANGE_RETRY_CHAIN)
    assert desc is None


# ---------------------------------------------------------------------------
# _apply_mutation — CHANGE_REVIEW_FREQUENCY
# ---------------------------------------------------------------------------


def test_apply_mutation_change_review_frequency():
    config = {"routes": {}, "steps": [], "review_every_n": 10}
    desc = _apply_mutation(config, MutationType.CHANGE_REVIEW_FREQUENCY)
    assert desc is not None
    assert "change_review_freq" in desc
    assert config["review_every_n"] in [5, 8, 10, 12, 15, 20]


# ---------------------------------------------------------------------------
# _apply_mutation — SWAP_BACKEND
# ---------------------------------------------------------------------------


def test_apply_mutation_swap_backend():
    config = {
        "routes": {"orient": {"model": "x", "backend": "claude"}},
        "steps": [],
    }
    desc = _apply_mutation(config, MutationType.SWAP_BACKEND)
    assert desc is not None
    assert "swap_backend" in desc
    assert config["routes"]["orient"]["backend"] != "claude"


def test_apply_mutation_swap_backend_no_routes():
    config = {"routes": {}, "steps": []}
    desc = _apply_mutation(config, MutationType.SWAP_BACKEND)
    assert desc is None


# ---------------------------------------------------------------------------
# _apply_mutation — ADD_STEP
# ---------------------------------------------------------------------------


def test_apply_mutation_add_step():
    config = {"routes": {}, "steps": []}
    desc = _apply_mutation(config, MutationType.ADD_STEP)
    assert desc is not None
    assert "add_step" in desc
    assert len(config["steps"]) == 1


def test_apply_mutation_add_step_no_candidates():
    # All optional steps already present
    config = {
        "routes": {},
        "steps": [{"name": s, "enabled": True} for s in OPTIONAL_STEPS],
    }
    desc = _apply_mutation(config, MutationType.ADD_STEP)
    assert desc is None


# ---------------------------------------------------------------------------
# _apply_mutation — REMOVE_STEP
# ---------------------------------------------------------------------------


def test_apply_mutation_remove_step():
    config = {
        "routes": {},
        "steps": [{"name": "adversarial", "enabled": True}],
    }
    desc = _apply_mutation(config, MutationType.REMOVE_STEP)
    assert desc is not None
    assert "remove_step" in desc
    assert len(config["steps"]) == 0


def test_apply_mutation_remove_step_no_removable():
    config = {"routes": {}, "steps": [{"name": "orient", "enabled": True}]}
    desc = _apply_mutation(config, MutationType.REMOVE_STEP)
    assert desc is None


# ---------------------------------------------------------------------------
# _apply_mutation — MODIFY_PROMPT_TEMPLATE
# ---------------------------------------------------------------------------


def test_apply_mutation_modify_prompt_template():
    config = {
        "routes": {"orient": {"model": "x"}},
        "steps": [],
    }
    desc = _apply_mutation(config, MutationType.MODIFY_PROMPT_TEMPLATE)
    assert desc is not None
    assert "flag_prompt_rewrite" in desc
    assert "prompt_modifications" in config


def test_apply_mutation_modify_prompt_no_routes():
    config = {"routes": {}, "steps": []}
    desc = _apply_mutation(config, MutationType.MODIFY_PROMPT_TEMPLATE)
    assert desc is None


# ---------------------------------------------------------------------------
# _apply_mutation — CHANGE_SKILL_SELECTION
# ---------------------------------------------------------------------------


def test_apply_mutation_skill_add():
    config = {"routes": {}, "steps": [], "selected_skills": []}
    # Force "add" by patching random.choice to always return "add" for action
    def fake_choice(lst):
        if "add" in lst:
            return "add"
        return lst[0]

    with patch("random.choice", side_effect=fake_choice):
        desc = _apply_mutation(config, MutationType.CHANGE_SKILL_SELECTION)
    assert desc is not None
    assert "change_skills" in desc


def test_apply_mutation_skill_changes_config():
    config = {"routes": {}, "steps": [], "selected_skills": ["skill_a"]}
    desc = _apply_mutation(config, MutationType.CHANGE_SKILL_SELECTION)
    assert desc is not None


# ---------------------------------------------------------------------------
# _apply_meta_suggestion
# ---------------------------------------------------------------------------


def test_apply_meta_suggestion_swap_model():
    config = {"routes": {"orient": {"model": "old_model"}}}
    _apply_meta_suggestion(config, ["swap_model", "orient", "old_model", "new_model"])
    assert config["routes"]["orient"]["model"] == "new_model"


def test_apply_meta_suggestion_change_timeout():
    config = {"routes": {"orient": {"timeout_minutes": 30}}}
    _apply_meta_suggestion(config, ["change_timeout", "orient", "30", "60"])
    assert config["routes"]["orient"]["timeout_minutes"] == 60


def test_apply_meta_suggestion_change_timeout_invalid():
    config = {"routes": {"orient": {"timeout_minutes": 30}}}
    # Should suppress ValueError, leaving unchanged
    _apply_meta_suggestion(config, ["change_timeout", "orient", "30", "not_a_number"])
    assert config["routes"]["orient"]["timeout_minutes"] == 30


def test_apply_meta_suggestion_swap_backend():
    config = {"routes": {"orient": {"backend": "claude"}}}
    _apply_meta_suggestion(config, ["swap_backend", "orient", "claude", "opencode"])
    assert config["routes"]["orient"]["backend"] == "opencode"


def test_apply_meta_suggestion_change_review_frequency():
    config = {}
    _apply_meta_suggestion(config, ["change_review_frequency", "global", "10", "15"])
    assert config["review_every_n"] == 15


def test_apply_meta_suggestion_unknown_key_noop():
    config = {"routes": {"orient": {"model": "x"}}}
    # No matching route key
    _apply_meta_suggestion(config, ["swap_model", "nonexistent", "x", "y"])
    # Should not crash


# ---------------------------------------------------------------------------
# meta_mutate — fallback on error
# ---------------------------------------------------------------------------


def test_meta_mutate_fallback_on_router_error():
    parent = make_parent()
    mock_router = MagicMock()
    mock_router.execute.side_effect = RuntimeError("no connection")
    child = meta_mutate(parent, mock_router)
    # Should fall back to random mutate
    assert child.parent_id == parent.id
    assert child.generation == parent.generation + 1


def test_meta_mutate_fallback_on_no_parseable_mutations():
    parent = make_parent()
    mock_result = MagicMock()
    mock_result.text = "No mutations here"
    mock_router = MagicMock()
    mock_router.execute.return_value = mock_result
    child = meta_mutate(parent, mock_router)
    # Fallback to random mutate
    assert child.parent_id == parent.id


def test_meta_mutate_applies_parsed_mutations():
    parent = make_parent()
    mock_result = MagicMock()
    mock_result.text = "MUTATION: swap_model|orient|old|claude-sonnet-4-6"
    mock_router = MagicMock()
    mock_router.execute.return_value = mock_result
    child = meta_mutate(parent, mock_router)
    assert child.parent_id == parent.id
    assert any("meta:" in m for m in child.mutations)
