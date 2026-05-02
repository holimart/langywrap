"""Tests for langywrap.ralph.pipeline — Python-first pipeline config."""

from __future__ import annotations

from pathlib import Path

import pytest
from langywrap.ralph.pipeline import (
    Gate,
    Loop,
    Match,
    Periodic,
    Pipeline,
    Retry,
    Step,
    Throttle,
    _parse_when,
    _resolve_model,
    load_pipeline_config,
)

# ---------------------------------------------------------------------------
# Model aliases
# ---------------------------------------------------------------------------


class TestModelAliases:
    def test_known_aliases(self):
        assert _resolve_model("haiku") == "claude-haiku-4-5-20251001"
        assert _resolve_model("sonnet") == "claude-sonnet-4-6"
        assert _resolve_model("opus") == "claude-opus-4-6"
        assert _resolve_model("kimi") == "nvidia/moonshotai/kimi-k2.5"

    def test_passthrough(self):
        assert _resolve_model("openai/gpt-5.2") == "openai/gpt-5.2"
        assert _resolve_model("custom-model") == "custom-model"


# ---------------------------------------------------------------------------
# When expression parsing
# ---------------------------------------------------------------------------


class TestParseWhen:
    def test_basic(self):
        step, pattern = _parse_when("execute =~ /unconditional/")
        assert step == "execute"
        assert pattern == "unconditional"

    def test_complex_pattern(self):
        step, pattern = _parse_when("execute =~ /sorry.*filled|axiom.*added/")
        assert step == "execute"
        assert pattern == "sorry.*filled|axiom.*added"

    def test_invalid(self):
        with pytest.raises(ValueError, match="Invalid when"):
            _parse_when("bad expression")


# ---------------------------------------------------------------------------
# Step
# ---------------------------------------------------------------------------


class TestStep:
    def test_basic(self):
        s = Step("orient", model="haiku", prompt="orient.md")
        assert s.name == "orient"
        assert s.model == "haiku"
        assert s.prompt == "orient.md"
        assert s.timeout == 30
        assert s.fail_fast is False

    def test_with_fallback(self):
        s = Step("execute", model="kimi", fallback="sonnet")
        assert s.fallback == "sonnet"

    def test_with_builtin(self):
        s = Step("orient", builtin="orient")
        assert s.builtin == "orient"

    def test_with_retry(self):
        s = Step("execute", retry=Retry(
            gate=Gate("./check.sh"),
            attempts=5,
            model="kimi",
        ))
        assert s.retry is not None
        assert s.retry.attempts == 5
        assert s.retry.gate is not None
        assert s.retry.gate.command == "./check.sh"

    def test_with_when(self):
        s = Step("validate", when="execute =~ /unconditional/")
        assert s.when == "execute =~ /unconditional/"

    def test_with_per_cycle(self):
        s = Step("execute", per_cycle={"lean": {"model": "kimi"}})
        assert s.per_cycle["lean"]["model"] == "kimi"

    def test_with_detects_cycle(self):
        s = Step("plan", detects_cycle=Match(
            lean=r"sorry.*fill",
            research=r"web.?research",
        ))
        assert s.detects_cycle is not None
        assert "lean" in s.detects_cycle.rules
        assert "research" in s.detects_cycle.rules


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


class TestGate:
    def test_basic(self):
        g = Gate("./just check")
        assert g.command == "./just check"
        assert g.timeout == 10
        assert g.required is True

    def test_optional(self):
        g = Gate("lake build", timeout=15, required=False)
        assert g.required is False
        assert g.timeout == 15


# ---------------------------------------------------------------------------
# Match
# ---------------------------------------------------------------------------


class TestMatch:
    def test_kwargs_as_rules(self):
        m = Match(lean=r"sorry.*fill", research=r"web.?research")
        assert m.rules["lean"] == r"sorry.*fill"
        assert m.rules["research"] == r"web.?research"
        assert m.source == "plan"

    def test_custom_source(self):
        m = Match(source="orient", lean=r"test")
        assert m.source == "orient"


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


class TestRetry:
    def test_basic(self):
        r = Retry(attempts=5, model="kimi", fallback="sonnet")
        assert r.attempts == 5
        assert r.model == "kimi"
        assert r.fallback == "sonnet"

    def test_with_gate(self):
        r = Retry(gate=Gate("./check.sh"), attempts=3)
        assert r.gate is not None
        assert r.gate.command == "./check.sh"

    def test_with_cycles(self):
        r = Retry(cycles=["lean", "mixed"])
        assert r.cycles == ["lean", "mixed"]


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


class TestLoop:
    def test_basic(self):
        lo = Loop("develop", max=5, until="review =~ /LGTM/", steps=[
            Step("engineer", model="kimi", prompt="engineer.md"),
            Step("review", model="sonnet", prompt="review.md"),
        ])
        assert lo.name == "develop"
        assert lo.max == 5
        assert len(lo.steps) == 2

    def test_with_escalate(self):
        lo = Loop("develop", max=3, escalate={
            2: {"engineer.model": "sonnet"},
            3: {"engineer.model": "opus"},
        })
        assert lo.escalate[2] == {"engineer.model": "sonnet"}


# ---------------------------------------------------------------------------
# Periodic
# ---------------------------------------------------------------------------


class TestPeriodic:
    def test_builtin(self):
        p = Periodic(every=5, builtin="hygiene")
        assert p.every == 5
        assert p.builtin == "hygiene"

    def test_with_step(self):
        p = Periodic(every=12,
                     step=Step("adversarial", model="sonnet", prompt="adv.md"),
                     or_when="execute =~ /milestone/")
        assert p.step is not None
        assert p.step.name == "adversarial"
        assert p.or_when == "execute =~ /milestone/"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TestPipeline:
    def test_minimal(self):
        p = Pipeline(steps=[
            Step("orient", model="haiku", prompt="orient.md"),
            Step("finalize", model="kimi", prompt="finalize.md"),
        ])
        assert len(p.steps) == 2

    def test_to_ralph_config(self, tmp_path: Path):
        """Pipeline → RalphConfig conversion."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "orient.md").write_text("Orient prompt")
        (prompts_dir / "execute.md").write_text("Execute prompt")
        (prompts_dir / "finalize.md").write_text("Finalize prompt")

        p = Pipeline(
            prompts="prompts",
            steps=[
                Step("orient", model="haiku", prompt="orient.md", fail_fast=True),
                Step("execute", model="kimi", prompt="execute.md", timeout=120,
                     fallback="sonnet"),
                Step("finalize", model="kimi", prompt="finalize.md"),
            ],
            gates=[Gate("./just check")],
            throttle=Throttle(utc="13-19"),
            git=["src/"],
            scope="Test scope",
        )

        cfg = p.to_ralph_config(tmp_path)

        assert cfg.project_dir == tmp_path
        assert len(cfg.steps) == 3
        assert cfg.steps[0].name == "orient"
        assert cfg.steps[0].model == "claude-haiku-4-5-20251001"

        assert cfg.steps[0].fail_fast is True
        assert cfg.steps[1].name == "execute"
        assert cfg.steps[1].model == "nvidia/moonshotai/kimi-k2.5"
        assert cfg.steps[1].timeout_minutes == 120
        assert cfg.steps[1].retry_count == 1  # from fallback
        assert cfg.steps[1].retry_model == "claude-sonnet-4-6"
        assert cfg.steps[2].name == "finalize"
        assert cfg.quality_gate is not None
        assert cfg.quality_gate.command == "./just check"
        assert cfg.throttle_utc_start == 13
        assert cfg.throttle_utc_end == 19
        assert cfg.git_add_paths == ["src/"]
        assert cfg.scope_restriction == "Test scope"

    def test_builtin_step_converts_to_step_config(self, tmp_path):
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        p = Pipeline(
            prompts="prompts",
            state="ralph",
            steps=[Step("orient", builtin="orient")],
        )
        cfg = p.to_ralph_config(tmp_path)
        assert cfg.steps[0].builtin == "orient"

    def test_cycle_types(self, tmp_path: Path):
        """Cycle type detection and per_cycle overrides."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "plan.md").write_text("Plan")
        (prompts_dir / "execute.md").write_text("Execute")

        p = Pipeline(
            prompts="prompts",
            steps=[
                Step("plan", model="opus", prompt="plan.md",
                     detects_cycle=Match(
                         lean=r"sorry.*fill",
                         research=r"web.?research",
                     )),
                Step("execute", model="sonnet", prompt="execute.md",
                     per_cycle={
                         "lean": {"model": "kimi"},
                         "research": {"model": "kimi"},
                     }),
            ],
        )

        cfg = p.to_ralph_config(tmp_path)

        assert len(cfg.cycle_type_rules) == 2
        lean_rule = next(r for r in cfg.cycle_type_rules if r["name"] == "lean")
        assert lean_rule["pattern"] == r"sorry.*fill"
        assert lean_rule["model"] == "nvidia/moonshotai/kimi-k2.5"

    def test_retry_config(self, tmp_path: Path):
        """Retry block → StepConfig retry fields."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "execute.md").write_text("Execute")
        (prompts_dir / "retry.md").write_text("Retry")

        p = Pipeline(
            prompts="prompts",
            steps=[
                Step("execute", model="sonnet", prompt="execute.md",
                     retry=Retry(
                         gate=Gate("./check.sh"),
                         attempts=5,
                         model="kimi",
                         prompt="retry.md",
                         fallback="sonnet",
                         cycles=["lean"],
                     )),
            ],
        )

        cfg = p.to_ralph_config(tmp_path)

        step = cfg.steps[0]
        assert step.retry_count == 5
        assert step.retry_gate_command == "./check.sh"
        assert step.retry_model == "nvidia/moonshotai/kimi-k2.5"
        assert step.retry_prompt_template == prompts_dir / "retry.md"
        assert step.retry_if_cycle_types == ["lean"]

    def test_adversarial_periodic(self, tmp_path: Path):
        """Adversarial periodic → adversarial config fields."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "orient.md").write_text("Orient")
        (prompts_dir / "adversarial.md").write_text("Adversarial")

        p = Pipeline(
            prompts="prompts",
            steps=[
                Step("orient", model="haiku", prompt="orient.md"),
            ],
            periodic=[
                Periodic(every=12,
                         step=Step("adversarial", model="sonnet",
                                   prompt="adversarial.md"),
                         or_when="execute =~ /milestone/"),
            ],
        )

        cfg = p.to_ralph_config(tmp_path)

        assert cfg.adversarial_every_n == 12
        assert cfg.adversarial_step == "adversarial"
        assert "milestone" in cfg.adversarial_milestone_patterns[0]
        # Adversarial step should be in steps list but not pipeline
        adv = next(s for s in cfg.steps if s.name == "adversarial")
        assert adv.pipeline is False
        assert adv.model == "claude-sonnet-4-6"

    def test_hygiene_periodic(self, tmp_path: Path):
        """Hygiene builtin → hygiene_every_n."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "orient.md").write_text("Orient")

        p = Pipeline(
            prompts="prompts",
            steps=[Step("orient", model="haiku", prompt="orient.md")],
            periodic=[Periodic(every=5, builtin="hygiene")],
        )

        cfg = p.to_ralph_config(tmp_path)
        assert cfg.hygiene_every_n == 5

    def test_lookback_periodic(self, tmp_path: Path):
        """Lookback builtin → periodic_tasks."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "orient.md").write_text("Orient")

        p = Pipeline(
            prompts="prompts",
            steps=[Step("orient", model="haiku", prompt="orient.md")],
            periodic=[Periodic(every=9, builtin="lookback", marker="lookback",
                               template="- [ ] Lookback cycle {cycle}")],
        )

        cfg = p.to_ralph_config(tmp_path)
        assert len(cfg.periodic_tasks) == 1
        assert cfg.periodic_tasks[0]["every"] == 9
        assert cfg.periodic_tasks[0]["marker"] == "lookback"

    def test_multiple_gates(self, tmp_path: Path):
        """Multiple gates → primary + additional."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "orient.md").write_text("Orient")

        p = Pipeline(
            prompts="prompts",
            steps=[Step("orient", model="haiku", prompt="orient.md")],
            gates=[
                Gate("./just check"),
                Gate("lake build", timeout=15, required=False),
            ],
        )

        cfg = p.to_ralph_config(tmp_path)
        assert cfg.quality_gate is not None
        assert cfg.quality_gate.command == "./just check"
        assert len(cfg.quality_gates) == 1
        assert cfg.quality_gates[0].command == "lake build"
        assert cfg.quality_gates[0].required is False


# ---------------------------------------------------------------------------
# HyperAgent genome
# ---------------------------------------------------------------------------


class TestGenome:
    def test_export(self):
        p = Pipeline(steps=[
            Step("orient", model="haiku"),
            Step("execute", model="kimi", timeout=120, fallback="sonnet"),
        ])
        genome = p.export_genome()
        assert genome["orient"]["model"] == "haiku"
        assert genome["execute"]["model"] == "kimi"
        assert genome["execute"]["timeout"] == 120
        assert genome["execute"]["fallback"] == "sonnet"

    def test_apply_overrides(self):
        p = Pipeline(steps=[
            Step("orient", model="haiku"),
            Step("execute", model="kimi", timeout=120),
        ])

        p2 = p.apply_overrides({
            "orient.model": "sonnet",
            "execute.timeout": 180,
        })

        assert p2.steps[0].model == "sonnet"  # type: ignore[union-attr]
        assert p2.steps[1].timeout == 180  # type: ignore[union-attr]
        # Original unchanged
        assert p.steps[0].model == "haiku"  # type: ignore[union-attr]

    def test_disable_step(self):
        p = Pipeline(steps=[
            Step("orient", model="haiku"),
            Step("validate", model="gpt-5.2"),
        ])

        p2 = p.apply_overrides({"validate.enabled": False})
        assert p2.steps[1].enabled is False  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Pipeline loader
# ---------------------------------------------------------------------------


class TestPipelineLoader:
    def test_load_from_file(self, tmp_path: Path):
        """Load Pipeline from a .langywrap/ralph.py file."""
        langywrap_dir = tmp_path / ".langywrap"
        langywrap_dir.mkdir()

        ralph_py = langywrap_dir / "ralph.py"
        ralph_py.write_text(
            "from langywrap.ralph.pipeline import Pipeline, Step\n"
            "config = Pipeline(steps=[Step('orient', model='haiku', prompt='orient.md')])\n"
        )

        pipeline = load_pipeline_config(tmp_path)
        assert pipeline is not None
        assert len(pipeline.steps) == 1
        assert pipeline.steps[0].name == "orient"  # type: ignore[union-attr]

    def test_no_file(self, tmp_path: Path):
        """Returns None if no ralph.py exists."""
        assert load_pipeline_config(tmp_path) is None

    def test_no_config_attr(self, tmp_path: Path):
        """Returns None if ralph.py has no 'config' attribute."""
        langywrap_dir = tmp_path / ".langywrap"
        langywrap_dir.mkdir()

        ralph_py = langywrap_dir / "ralph.py"
        ralph_py.write_text("x = 42\n")

        assert load_pipeline_config(tmp_path) is None


# ---------------------------------------------------------------------------
# Loop conversion
# ---------------------------------------------------------------------------


class TestLoopConversion:
    def test_loop_to_steps(self, tmp_path: Path):
        """Loop inner steps are expanded into regular StepConfigs."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "engineer.md").write_text("Engineer")
        (prompts_dir / "review.md").write_text("Review")

        p = Pipeline(
            prompts="prompts",
            steps=[
                Loop("develop", max=5, until="review =~ /LGTM/", steps=[
                    Step("engineer", model="kimi", prompt="engineer.md", timeout=60),
                    Step("review", model="sonnet", prompt="review.md", timeout=20),
                ]),
            ],
        )

        cfg = p.to_ralph_config(tmp_path)
        assert len(cfg.steps) == 2
        assert cfg.steps[0].name == "engineer"
        assert cfg.steps[1].name == "review"


# ---------------------------------------------------------------------------
# Route config generation
# ---------------------------------------------------------------------------


class TestStepDispatchInfo:
    def test_step_retry_chain_populated(self, tmp_path: Path):
        """``Step.fallback`` becomes ``StepConfig.retry_models``."""
        p = Pipeline(steps=[
            Step("orient", model="haiku"),
            Step("execute", model="kimi", fallback="sonnet"),
            Step("finalize", model="kimi"),
        ])

        cfg = p.to_ralph_config(tmp_path)
        by_name = {s.name: s for s in cfg.steps}

        assert by_name["orient"].model == "claude-haiku-4-5-20251001"
        assert by_name["execute"].model == "nvidia/moonshotai/kimi-k2.5"
        assert "claude-sonnet-4-6" in by_name["execute"].retry_models
