"""Extended pipeline tests — covers export_genome, apply_overrides, Loop,
Periodic (hygiene/lookback/adversarial), to_route_config, and _infer_backend."""

from __future__ import annotations

from langywrap.ralph.pipeline import (
    Gate,
    Loop,
    Match,
    Periodic,
    Pipeline,
    Retry,
    Step,
    Throttle,
    _infer_backend,
)

# ---------------------------------------------------------------------------
# _infer_backend
# ---------------------------------------------------------------------------


class TestInferBackend:
    def test_claude_prefix(self):
        assert _infer_backend("claude-sonnet-4-6") == "direct_api"
        assert _infer_backend("claude-haiku-3") == "direct_api"

    def test_gpt_prefix_is_direct_api(self):
        assert _infer_backend("gpt-4o") == "direct_api"
        assert _infer_backend("o1-mini") == "direct_api"
        assert _infer_backend("o3-turbo") == "direct_api"

    def test_openrouter_prefix(self):
        assert _infer_backend("openrouter/moonshotai/kimi-k2.5") == "openrouter"

    def test_unknown_returns_opencode(self):
        assert _infer_backend("kimi-k2") == "opencode"
        assert _infer_backend("nvidia/moonshotai/kimi-k2.5") == "opencode"


# ---------------------------------------------------------------------------
# export_genome
# ---------------------------------------------------------------------------


class TestExportGenome:
    def test_basic_step_genome(self, tmp_path):
        p = Pipeline(
            prompts=str(tmp_path),
            steps=[
                Step("orient", model="haiku"),
                Step("execute", model="kimi", timeout=120),
            ],
        )
        genome = p.export_genome()
        assert "orient" in genome
        assert genome["orient"]["model"] == "haiku"
        assert "execute" in genome
        assert genome["execute"]["timeout"] == 120

    def test_step_with_fallback_in_genome(self, tmp_path):
        p = Pipeline(
            steps=[Step("execute", model="kimi", fallback="sonnet")]
        )
        genome = p.export_genome()
        assert genome["execute"]["fallback"] == "sonnet"

    def test_step_with_retry_in_genome(self, tmp_path):
        p = Pipeline(
            steps=[Step("execute", model="kimi", retry=Retry(attempts=3, model="sonnet"))]
        )
        genome = p.export_genome()
        assert genome["execute"]["retry"]["attempts"] == 3
        assert genome["execute"]["retry"]["model"] == "sonnet"

    def test_loop_in_genome(self, tmp_path):
        p = Pipeline(
            steps=[
                Loop("develop", max=5, steps=[
                    Step("engineer", model="kimi"),
                ])
            ]
        )
        genome = p.export_genome()
        assert "develop" in genome
        assert genome["develop"]["max"] == 5

    def test_periodic_step_in_genome(self, tmp_path):
        p = Pipeline(
            steps=[Step("orient", model="haiku")],
            periodic=[
                Periodic(every=12, step=Step("adversarial", model="sonnet"))
            ],
        )
        genome = p.export_genome()
        assert "periodic.adversarial" in genome
        assert genome["periodic.adversarial"]["every"] == 12


# ---------------------------------------------------------------------------
# apply_overrides
# ---------------------------------------------------------------------------


class TestApplyOverrides:
    def test_override_model(self):
        p = Pipeline(steps=[Step("orient", model="haiku")])
        p2 = p.apply_overrides({"orient.model": "sonnet"})
        step = next(s for s in p2.steps if isinstance(s, Step) and s.name == "orient")
        assert step.model == "sonnet"
        # Original unchanged
        orig = next(s for s in p.steps if isinstance(s, Step) and s.name == "orient")
        assert orig.model == "haiku"

    def test_override_timeout(self):
        p = Pipeline(steps=[Step("execute", model="kimi", timeout=30)])
        p2 = p.apply_overrides({"execute.timeout": 120})
        step = next(s for s in p2.steps if isinstance(s, Step) and s.name == "execute")
        assert step.timeout == 120

    def test_override_enabled(self):
        p = Pipeline(steps=[Step("execute", model="kimi")])
        p2 = p.apply_overrides({"execute.enabled": False})
        step = next(s for s in p2.steps if isinstance(s, Step) and s.name == "execute")
        assert step.enabled is False

    def test_override_fail_fast(self):
        p = Pipeline(steps=[Step("orient", model="haiku")])
        p2 = p.apply_overrides({"orient.fail_fast": True})
        step = next(s for s in p2.steps if isinstance(s, Step) and s.name == "orient")
        assert step.fail_fast is True

    def test_override_fallback(self):
        p = Pipeline(steps=[Step("execute", model="kimi")])
        p2 = p.apply_overrides({"execute.fallback": "sonnet"})
        step = next(s for s in p2.steps if isinstance(s, Step) and s.name == "execute")
        assert step.fallback == "sonnet"

    def test_override_loop_max(self):
        p = Pipeline(steps=[Loop("develop", max=3)])
        p2 = p.apply_overrides({"develop.max": 7})
        loop = next(s for s in p2.steps if isinstance(s, Loop) and s.name == "develop")
        assert loop.max == 7

    def test_bad_key_no_dot_ignored(self):
        p = Pipeline(steps=[Step("orient", model="haiku")])
        # Should not raise
        p2 = p.apply_overrides({"nodot": "value"})
        assert isinstance(p2, Pipeline)

    def test_step_not_found_ignored(self):
        p = Pipeline(steps=[Step("orient", model="haiku")])
        p2 = p.apply_overrides({"nonexistent.model": "sonnet"})
        # Original step unchanged
        step = next(s for s in p2.steps if isinstance(s, Step) and s.name == "orient")
        assert step.model == "haiku"


# ---------------------------------------------------------------------------
# to_ralph_config — Loop handling
# ---------------------------------------------------------------------------


class TestToRalphConfigLoop:
    def test_loop_steps_expanded(self, tmp_path):
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "engineer.md").write_text("# Engineer\n")
        (prompts / "review.md").write_text("# Review\n")

        p = Pipeline(
            prompts=str(prompts),
            state=str(tmp_path / "ralph"),
            steps=[
                Loop("develop", max=5, steps=[
                    Step("engineer", model="kimi", prompt="engineer.md"),
                    Step("review", model="sonnet", prompt="review.md"),
                ])
            ],
        )
        cfg = p.to_ralph_config(tmp_path)
        step_names = [s.name for s in cfg.steps]
        assert "engineer" in step_names
        assert "review" in step_names

    def test_loop_with_gate_inside_skipped(self, tmp_path):
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "eng.md").write_text("# Eng\n")

        p = Pipeline(
            prompts=str(prompts),
            state=str(tmp_path / "ralph"),
            steps=[
                Loop("dev", max=3, steps=[
                    Step("eng", model="kimi", prompt="eng.md"),
                    Gate("./check.sh"),  # should be skipped
                ])
            ],
        )
        cfg = p.to_ralph_config(tmp_path)
        step_names = [s.name for s in cfg.steps]
        assert "eng" in step_names
        # Gate inside loop doesn't become a step
        assert "check.sh" not in " ".join(step_names)


# ---------------------------------------------------------------------------
# to_ralph_config — Periodic handling
# ---------------------------------------------------------------------------


class TestToRalphConfigPeriodic:
    def _prompts(self, tmp_path):
        prompts = tmp_path / "prompts"
        prompts.mkdir(exist_ok=True)
        (prompts / "orient.md").write_text("# Orient\n")
        (prompts / "adversarial.md").write_text("# Adversarial\n")
        return prompts

    def test_hygiene_periodic(self, tmp_path):
        prompts = self._prompts(tmp_path)
        p = Pipeline(
            prompts=str(prompts),
            state=str(tmp_path / "ralph"),
            steps=[Step("orient", model="haiku", prompt="orient.md")],
            periodic=[Periodic(every=5, builtin="hygiene")],
        )
        cfg = p.to_ralph_config(tmp_path)
        assert cfg.hygiene_every_n == 5

    def test_lookback_periodic(self, tmp_path):
        prompts = self._prompts(tmp_path)
        p = Pipeline(
            prompts=str(prompts),
            state=str(tmp_path / "ralph"),
            steps=[Step("orient", model="haiku", prompt="orient.md")],
            periodic=[
                Periodic(every=9, builtin="lookback", template="lookback task", marker="lb")
            ],
        )
        cfg = p.to_ralph_config(tmp_path)
        markers = [pt.get("marker") for pt in cfg.periodic_tasks]
        assert "lb" in markers

    def test_adversarial_periodic(self, tmp_path):
        prompts = self._prompts(tmp_path)
        p = Pipeline(
            prompts=str(prompts),
            state=str(tmp_path / "ralph"),
            steps=[Step("orient", model="haiku", prompt="orient.md")],
            periodic=[
                Periodic(
                    every=12,
                    step=Step("adversarial", model="sonnet", prompt="adversarial.md"),
                    or_when="execute =~ /axiom.*added/",
                )
            ],
        )
        cfg = p.to_ralph_config(tmp_path)
        assert cfg.adversarial_every_n == 12
        assert cfg.adversarial_milestone_patterns  # at least one pattern

    def test_template_only_periodic(self, tmp_path):
        prompts = self._prompts(tmp_path)
        p = Pipeline(
            prompts=str(prompts),
            state=str(tmp_path / "ralph"),
            steps=[Step("orient", model="haiku", prompt="orient.md")],
            periodic=[
                Periodic(every=7, template="do a thing every 7 cycles", marker="custom7")
            ],
        )
        cfg = p.to_ralph_config(tmp_path)
        markers = [pt.get("marker") for pt in cfg.periodic_tasks]
        assert "custom7" in markers


# ---------------------------------------------------------------------------
# to_ralph_config — Throttle
# ---------------------------------------------------------------------------


class TestToRalphConfigThrottle:
    def test_throttle_sets_utc_range(self, tmp_path):
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "orient.md").write_text("# Orient\n")

        p = Pipeline(
            prompts=str(prompts),
            state=str(tmp_path / "ralph"),
            steps=[Step("orient", model="haiku", prompt="orient.md")],
            throttle=Throttle(utc="13-19"),
        )
        cfg = p.to_ralph_config(tmp_path)
        assert cfg.throttle_utc_start == 13
        assert cfg.throttle_utc_end == 19

    def test_no_throttle(self, tmp_path):
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "orient.md").write_text("# Orient\n")

        p = Pipeline(
            prompts=str(prompts),
            state=str(tmp_path / "ralph"),
            steps=[Step("orient", model="haiku", prompt="orient.md")],
        )
        cfg = p.to_ralph_config(tmp_path)
        assert cfg.throttle_utc_start is None
        assert cfg.throttle_utc_end is None


# ---------------------------------------------------------------------------
# to_ralph_config — step-level gate
# ---------------------------------------------------------------------------


class TestToRalphConfigStepGate:
    def test_step_gate_added_as_extra_gate(self, tmp_path):
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "execute.md").write_text("# Execute\n")

        p = Pipeline(
            prompts=str(prompts),
            state=str(tmp_path / "ralph"),
            steps=[
                Step("execute", model="kimi", prompt="execute.md",
                     gate=Gate("./just check", timeout=5))
            ],
        )
        cfg = p.to_ralph_config(tmp_path)
        # step-level gate goes to extra quality_gates
        extra_cmds = [qg.command for qg in cfg.quality_gates]
        assert "./just check" in extra_cmds


# ---------------------------------------------------------------------------
# Per-step routing is now inline on Step; no separate RouteConfig to build.
# These tests exercise the same surfaces via ``to_ralph_config`` + StepConfig.
# ---------------------------------------------------------------------------


class TestStepRoutingPropagation:
    def test_empty_pipeline_produces_empty_steps(self, tmp_path):
        p = Pipeline(steps=[])
        cfg = p.to_ralph_config(tmp_path)
        assert cfg.steps == []

    def test_steps_carry_model_and_timeout(self, tmp_path):
        p = Pipeline(
            steps=[
                Step("orient", model="haiku", timeout=15),
                Step("execute", model="kimi", timeout=120),
            ]
        )
        cfg = p.to_ralph_config(tmp_path)
        assert len(cfg.steps) == 2
        models = {s.name: s.model for s in cfg.steps}
        assert "haiku" in models["orient"]
        assert models["execute"] == "nvidia/moonshotai/kimi-k2.5"

    def test_loop_steps_flattened_into_config(self, tmp_path):
        p = Pipeline(
            steps=[
                Loop("dev", max=3, steps=[
                    Step("engineer", model="kimi"),
                    Step("review", model="sonnet"),
                ])
            ]
        )
        cfg = p.to_ralph_config(tmp_path)
        names = {s.name for s in cfg.steps}
        assert {"engineer", "review"}.issubset(names)

    def test_periodic_adversarial_step_added_non_pipeline(self, tmp_path):
        p = Pipeline(
            steps=[Step("orient", model="haiku")],
            periodic=[
                Periodic(every=12, step=Step("adversarial", model="sonnet"))
            ],
        )
        cfg = p.to_ralph_config(tmp_path)
        adv = next((s for s in cfg.steps if s.name == "adversarial"), None)
        assert adv is not None
        assert adv.pipeline is False


# ---------------------------------------------------------------------------
# Step — token alias
# ---------------------------------------------------------------------------


class TestStepTokenAlias:
    def test_token_kwarg_becomes_confirmation_token(self):
        s = Step("orient", model="haiku", token="ORIENT_CONFIRMED:")
        assert s.confirmation_token == "ORIENT_CONFIRMED:"


# ---------------------------------------------------------------------------
# Match
# ---------------------------------------------------------------------------


class TestMatch:
    def test_basic_rules(self):
        m = Match(lean=r"sorry.*fill", research=r"literature|arXiv")
        assert "lean" in m.rules
        assert "research" in m.rules

    def test_source_default(self):
        m = Match()
        assert m.source == "plan"


# ---------------------------------------------------------------------------
# Step with detects_cycle
# ---------------------------------------------------------------------------


class TestStepDetectsCycle:
    def test_to_ralph_config_with_detects_cycle(self, tmp_path):
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "plan.md").write_text("# Plan\n")

        p = Pipeline(
            prompts=str(prompts),
            state=str(tmp_path / "ralph"),
            steps=[
                Step(
                    "plan",
                    model="haiku",
                    prompt="plan.md",
                    detects_cycle=Match(lean=r"sorry.*fill", research=r"arXiv|literature"),
                )
            ],
        )
        cfg = p.to_ralph_config(tmp_path)
        rule_names = [r["name"] for r in cfg.cycle_type_rules]
        assert "lean" in rule_names
        assert "research" in rule_names
