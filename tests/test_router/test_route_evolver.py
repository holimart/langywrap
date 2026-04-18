from __future__ import annotations

from pathlib import Path

import pytest
from langywrap.router.config import DEFAULT_ROUTE_CONFIG
from langywrap.router.evolution import RouteConfigVariant, RouteEvolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_evolver(tmp_path: Path, seed: int = 42) -> RouteEvolver:
    return RouteEvolver(archive_dir=tmp_path / "archive", rng_seed=seed)


# ---------------------------------------------------------------------------
# RouteConfigVariant
# ---------------------------------------------------------------------------


def test_variant_id_auto_computed():
    v = RouteConfigVariant(config=DEFAULT_ROUTE_CONFIG)
    assert v.variant_id.startswith("v0_")


def test_variant_id_explicit_preserved():
    v = RouteConfigVariant(config=DEFAULT_ROUTE_CONFIG, variant_id="custom_id")
    assert v.variant_id == "custom_id"


def test_variant_defaults():
    v = RouteConfigVariant(config=DEFAULT_ROUTE_CONFIG)
    assert v.fitness_score == 0.0
    assert v.generation == 0
    assert v.parent_id == ""
    assert v.metrics_history == []


def test_update_fitness_sets_score():
    v = RouteConfigVariant(config=DEFAULT_ROUTE_CONFIG)
    m = {"quality": 1.0, "cost_usd": 0.0, "avg_seconds": 0.0, "failures": 0, "cycles": 1}
    v.update_fitness(m)
    assert v.fitness_score == pytest.approx(0.5)


def test_update_fitness_appends_history():
    v = RouteConfigVariant(config=DEFAULT_ROUTE_CONFIG)
    metrics = {"quality": 0.8, "cost_usd": 0.01, "avg_seconds": 10.0, "failures": 1, "cycles": 5}
    v.update_fitness(metrics)
    assert len(v.metrics_history) == 1
    assert v.metrics_history[0] == metrics


def test_update_fitness_penalty():
    v = RouteConfigVariant(config=DEFAULT_ROUTE_CONFIG)
    m = {"quality": 0.0, "cost_usd": 0.0, "avg_seconds": 0.0, "failures": 5, "cycles": 5}
    v.update_fitness(m)
    assert v.fitness_score < 0.0


def test_compute_id_deterministic():
    v1 = RouteConfigVariant(config=DEFAULT_ROUTE_CONFIG, created_at=12345.0)
    v2 = RouteConfigVariant(config=DEFAULT_ROUTE_CONFIG, created_at=12345.0)
    assert v1.variant_id == v2.variant_id


# ---------------------------------------------------------------------------
# RouteEvolver — init
# ---------------------------------------------------------------------------


def test_evolver_creates_archive_dir(tmp_path):
    arch = tmp_path / "arch"
    RouteEvolver(archive_dir=arch, rng_seed=0)
    assert arch.exists()


def test_evolver_seeds_population(tmp_path):
    ev = make_evolver(tmp_path)
    assert len(ev._population) == 1
    assert ev._population[0].generation == 0


def test_evolver_saves_seed_file(tmp_path):
    make_evolver(tmp_path)
    files = list((tmp_path / "archive").glob("v*.json"))
    assert len(files) == 1


def test_evolver_loads_existing_archive(tmp_path):
    ev1 = make_evolver(tmp_path)
    seed_id = ev1._population[0].variant_id

    ev2 = make_evolver(tmp_path)
    ids = [v.variant_id for v in ev2._population]
    assert seed_id in ids


# ---------------------------------------------------------------------------
# mutate()
# ---------------------------------------------------------------------------


def test_mutate_returns_child(tmp_path):
    ev = make_evolver(tmp_path)
    parent = ev._population[0]
    child = ev.mutate(parent)
    assert child.generation == 1
    assert child.parent_id == parent.variant_id
    assert len(child.mutations) > 0


def test_mutate_adds_to_population(tmp_path):
    ev = make_evolver(tmp_path)
    ev.mutate(ev._population[0])
    assert len(ev._population) == 2


def test_mutate_saves_child_to_disk(tmp_path):
    ev = make_evolver(tmp_path)
    child = ev.mutate(ev._population[0])
    path = tmp_path / "archive" / f"{child.variant_id}.json"
    assert path.exists()


# ---------------------------------------------------------------------------
# select_parent()
# ---------------------------------------------------------------------------


def test_select_parent_single(tmp_path):
    ev = make_evolver(tmp_path)
    parent = ev.select_parent()
    assert parent.variant_id == ev._population[0].variant_id


def test_select_parent_multiple(tmp_path):
    ev = make_evolver(tmp_path)
    parent = ev._population[0]
    ev.mutate(parent)
    ev.mutate(parent)
    selected = ev.select_parent()
    assert selected in ev._population


# ---------------------------------------------------------------------------
# record_result()
# ---------------------------------------------------------------------------


def test_record_result_updates_fitness(tmp_path):
    ev = make_evolver(tmp_path)
    vid = ev._population[0].variant_id
    m = {"quality": 1.0, "cost_usd": 0.0, "avg_seconds": 0.0, "failures": 0, "cycles": 1}
    ev.record_result(vid, m)
    assert ev._population[0].fitness_score == pytest.approx(0.5)


def test_record_result_unknown_id_noop(tmp_path):
    ev = make_evolver(tmp_path)
    ev.record_result("nonexistent_id", {"quality": 1.0})  # no raise


# ---------------------------------------------------------------------------
# get_best()
# ---------------------------------------------------------------------------


def test_get_best_no_scored_returns_first(tmp_path):
    ev = make_evolver(tmp_path)
    best = ev.get_best()
    assert best == ev._population[0]


def test_get_best_returns_highest_scored(tmp_path):
    ev = make_evolver(tmp_path)
    parent = ev._population[0]
    child = ev.mutate(parent)

    base = {"cost_usd": 0.0, "avg_seconds": 0.0, "failures": 0, "cycles": 1}
    ev.record_result(parent.variant_id, {**base, "quality": 0.1})
    ev.record_result(child.variant_id, {**base, "quality": 1.0})

    best = ev.get_best()
    assert best.variant_id == child.variant_id


# ---------------------------------------------------------------------------
# list_variants()
# ---------------------------------------------------------------------------


def test_list_variants_sorted_descending(tmp_path):
    ev = make_evolver(tmp_path)
    parent = ev._population[0]
    ev.mutate(parent)
    variants = ev.list_variants()
    scores = [v.fitness_score for v in variants]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# get_explorative()
# ---------------------------------------------------------------------------


def test_get_explorative_returns_child(tmp_path):
    ev = make_evolver(tmp_path)
    child = ev.get_explorative()
    assert child.generation >= 1


# ---------------------------------------------------------------------------
# Mutation operators (direct)
# ---------------------------------------------------------------------------


def test_mut_swap_model(tmp_path):
    ev = make_evolver(tmp_path)
    cfg = DEFAULT_ROUTE_CONFIG.model_copy(deep=True)
    new_cfg, desc = ev._mut_swap_model(cfg)
    assert "swap_model" in desc


def test_mut_change_timeout(tmp_path):
    ev = make_evolver(tmp_path)
    cfg = DEFAULT_ROUTE_CONFIG.model_copy(deep=True)
    new_cfg, desc = ev._mut_change_timeout(cfg)
    assert "change_timeout" in desc


def test_mut_change_retry(tmp_path):
    ev = make_evolver(tmp_path)
    cfg = DEFAULT_ROUTE_CONFIG.model_copy(deep=True)
    new_cfg, desc = ev._mut_change_retry(cfg)
    assert "change_retry" in desc


def test_mut_change_review_n(tmp_path):
    ev = make_evolver(tmp_path)
    cfg = DEFAULT_ROUTE_CONFIG.model_copy(deep=True)
    new_cfg, desc = ev._mut_change_review_n(cfg)
    assert "change_review_n" in desc


def test_mut_swap_backend(tmp_path):
    ev = make_evolver(tmp_path)
    cfg = DEFAULT_ROUTE_CONFIG.model_copy(deep=True)
    new_cfg, desc = ev._mut_swap_backend(cfg)
    assert "swap_backend" in desc or "noop" in desc


def test_mut_change_tier(tmp_path):
    ev = make_evolver(tmp_path)
    cfg = DEFAULT_ROUTE_CONFIG.model_copy(deep=True)
    new_cfg, desc = ev._mut_change_tier(cfg)
    assert "change_tier" in desc


# ---------------------------------------------------------------------------
# _compute_selection_scores()
# ---------------------------------------------------------------------------


def test_compute_selection_scores_all_positive(tmp_path):
    ev = make_evolver(tmp_path)
    ev.mutate(ev._population[0])
    scores = ev._compute_selection_scores()
    assert all(s > 0 for s in scores)


def test_compute_selection_scores_zero_fitness(tmp_path):
    ev = make_evolver(tmp_path)
    # All variants have fitness 0 → should still return positive scores via novelty
    scores = ev._compute_selection_scores()
    assert all(s >= 0.01 for s in scores)


# ---------------------------------------------------------------------------
# _load_archive with corrupt file
# ---------------------------------------------------------------------------


def test_load_archive_skips_corrupt(tmp_path):
    arch = tmp_path / "archive"
    arch.mkdir()
    # Write corrupt json
    (arch / "v0_corrupt.json").write_text("not json{{{")
    ev = RouteEvolver(archive_dir=arch, rng_seed=0)
    # Should still have seed (from fresh init)
    assert len(ev._population) >= 1


# ---------------------------------------------------------------------------
# export_best()
# ---------------------------------------------------------------------------


def test_export_best_writes_file(tmp_path):
    ev = make_evolver(tmp_path)
    path = ev.export_best(tmp_path)
    assert path.exists()
