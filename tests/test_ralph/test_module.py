"""Tests for langywrap.ralph.module — Module-based forward() runner."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from langywrap.ralph.module import (
    BoundStep,
    Module,
    ModuleRunner,
    StepDef,
    gate,
    gate_output,
    load_module_config,
    match,
    step,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class SimplePipeline(Module):
    """Minimal pipeline for testing."""

    prompts = "prompts"
    state = "state"
    scope = "Test scope"
    gates = []
    git = []
    hygiene_every = None

    orient = step("haiku", "orient.md", fail_fast=True)
    execute = step("sonnet", "execute.md", timeout=120)
    finalize = step("kimi", "finalize.md")

    def forward(self, cycle: int):
        self.orient()
        self.execute()
        self.finalize()


class ConditionalPipeline(Module):
    """Pipeline with match() and conditional logic."""

    prompts = "prompts"
    state = "state"
    gates = []
    git = []
    hygiene_every = None

    orient = step("haiku", "orient.md")
    plan = step("opus", "plan.md")
    execute = step("sonnet", "execute.md", timeout=120)
    validate = step("gpt-5.2", "validate.md")
    finalize = step("kimi", "finalize.md")

    def forward(self, cycle: int):
        self.orient()
        self.plan()

        cycle_type = match(self.plan,
            lean=r"sorry.*fill|\.lean",
            research=r"web.?research|arXiv",
        )

        if cycle_type == "lean":
            self.execute(model="kimi")
        elif cycle_type == "research":
            self.execute(model="kimi", inject="## RESEARCH DIRECTIVE")
        else:
            self.execute()

        import re
        if re.search(r"unconditional", self.execute.output, re.IGNORECASE):
            self.validate()

        self.finalize()


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    """Create a prompts directory with stub templates."""
    d = tmp_path / "prompts"
    d.mkdir()
    for name in ["orient", "plan", "execute", "validate", "finalize",
                  "engineer", "review", "adversarial"]:
        (d / f"{name}.md").write_text(f"# {name} prompt template\n")
    return d


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    """Create state directory with required files."""
    d = tmp_path / "state"
    d.mkdir()
    (d / "steps").mkdir()
    (d / "tasks.md").write_text("- [ ] **[P1] Test task**\n  - Status: PENDING\n")
    (d / "progress.md").write_text("# Progress\n")
    (d / "plan.md").write_text("# Plan\n")
    (d / "cycle_count.txt").write_text("0")
    return d


# ---------------------------------------------------------------------------
# StepDef
# ---------------------------------------------------------------------------


class TestStepDef:
    def test_creation(self):
        s = step("haiku", "orient.md", fail_fast=True)
        assert isinstance(s, StepDef)
        assert s.model == "haiku"
        assert s.prompt == "orient.md"
        assert s.fail_fast is True

    def test_defaults(self):
        s = step()
        assert s.model == "sonnet"
        assert s.timeout == 30
        assert s.enabled is True

    def test_copy(self):
        s = step("haiku", "orient.md")
        s._attr_name = "orient"
        s2 = s.copy(model="sonnet", timeout=60)
        assert s2.model == "sonnet"
        assert s2.timeout == 60
        assert s2._attr_name == "orient"
        # Original unchanged
        assert s.model == "haiku"

    def test_descriptor_class_access(self):
        """Accessing step on class returns StepDef."""
        assert isinstance(SimplePipeline.orient, StepDef)
        assert SimplePipeline.orient.model == "haiku"

    def test_descriptor_instance_access(self):
        """Accessing step on instance returns BoundStep."""
        m = SimplePipeline()
        bound = m.orient
        assert isinstance(bound, BoundStep)
        assert bound.name == "orient"
        assert bound.model == "haiku"

    def test_descriptor_caching(self):
        """Same BoundStep returned on repeated access."""
        m = SimplePipeline()
        b1 = m.orient
        b2 = m.orient
        assert b1 is b2


# ---------------------------------------------------------------------------
# BoundStep
# ---------------------------------------------------------------------------


class TestBoundStep:
    def test_initial_state(self):
        m = SimplePipeline()
        b = m.orient
        assert b.output == ""
        assert b.success is False

    def test_call_stub_mode(self, prompts_dir, state_dir, tmp_path):
        """Step call in stub mode (no router) returns stub output."""
        m = SimplePipeline()
        m.prompts = "prompts"
        m.state = "state"
        m.verbose = False

        ModuleRunner(m, project_dir=tmp_path, router=None)
        m._cycle_num = 1
        m._orient_context = ""

        output = m.orient()
        assert "STUB" in output
        assert m.orient.output == output

    def test_disabled_step(self, prompts_dir, state_dir, tmp_path):
        """Disabled step is skipped."""
        m = SimplePipeline()
        m.verbose = False
        ModuleRunner(m, project_dir=tmp_path, router=None)

        # Disable execute
        m.apply_overrides({"execute.enabled": False})
        m._cycle_num = 1
        m._orient_context = ""

        output = m.execute()
        assert "SKIPPED" in output
        assert not m.execute.success


# ---------------------------------------------------------------------------
# match()
# ---------------------------------------------------------------------------


class TestMatch:
    def test_matching(self, prompts_dir, state_dir, tmp_path):
        m = SimplePipeline()
        m.verbose = False
        ModuleRunner(m, project_dir=tmp_path, router=None)
        m._cycle_num = 1
        m._orient_context = ""

        # Simulate plan output
        m.orient()
        bound = m.execute
        bound.output = "This cycle involves sorry filling in .lean files"

        ct = match(bound,
            lean=r"sorry.*fill|\.lean",
            research=r"web.?research",
        )
        assert ct == "lean"

    def test_no_match(self):
        m = SimplePipeline()
        bound = m.orient
        bound.output = "nothing special here"
        ct = match(bound, lean=r"\.lean", research=r"arXiv")
        assert ct == ""

    def test_empty_output(self):
        m = SimplePipeline()
        bound = m.orient
        assert match(bound, lean=r"test") == ""

    def test_first_match_wins(self):
        m = SimplePipeline()
        bound = m.orient
        bound.output = "this matches both lean and research"
        ct = match(bound,
            lean=r"lean",
            research=r"research",
        )
        assert ct == "lean"


# ---------------------------------------------------------------------------
# gate()
# ---------------------------------------------------------------------------


class TestGate:
    def test_passing_gate(self):
        assert gate("true") is True

    def test_failing_gate(self):
        assert gate("false") is False

    def test_gate_output(self):
        passed, output = gate_output("echo hello")
        assert passed is True
        assert "hello" in output

    def test_gate_timeout(self):
        assert gate("sleep 10", timeout=1) is False

    def test_gate_output_timeout_and_exception(self, monkeypatch):
        import subprocess

        def timeout_run(*args, **kwargs):
            raise subprocess.TimeoutExpired("cmd", 1)

        monkeypatch.setattr("langywrap.ralph.module.subprocess.run", timeout_run)
        passed, output = gate_output("cmd", timeout=1)
        assert passed is False
        assert "timed out" in output

        def error_run(*args, **kwargs):
            raise OSError("boom")

        monkeypatch.setattr("langywrap.ralph.module.subprocess.run", error_run)
        passed, output = gate_output("cmd")
        assert passed is False
        assert output == "boom"


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------


class TestModule:
    def test_step_collection(self):
        m = SimplePipeline()
        assert "orient" in m._step_defs
        assert "execute" in m._step_defs
        assert "finalize" in m._step_defs
        assert len(m._step_defs) == 3

    def test_export_genome(self):
        m = SimplePipeline()
        genome = m.export_genome()
        assert genome["orient"]["model"] == "haiku"
        assert genome["execute"]["model"] == "sonnet"
        assert genome["execute"]["timeout"] == 120
        assert genome["finalize"]["model"] == "kimi"

    def test_apply_overrides(self):
        m = SimplePipeline()
        m.apply_overrides({
            "orient.model": "sonnet",
            "execute.timeout": 180,
        })
        assert m._step_defs["orient"].model == "sonnet"
        assert m._step_defs["execute"].timeout == 180

    def test_apply_overrides_clears_bound_cache(self):
        m = SimplePipeline()
        # Access to create cache
        _ = m.orient
        assert "_bound_orient" in m.__dict__

        m.apply_overrides({"orient.model": "opus"})
        # Cache cleared
        assert "_bound_orient" not in m.__dict__
        # New access gets updated value
        assert m.orient.model == "opus"

    def test_disable_step(self):
        m = SimplePipeline()
        m.apply_overrides({"execute.enabled": False})
        assert m._step_defs["execute"].enabled is False

    def test_get_forward_source(self):
        m = SimplePipeline()
        src = m.get_forward_source()
        assert "self.orient()" in src
        assert "self.execute()" in src

    def test_get_source_file(self):
        m = SimplePipeline()
        path = m.get_source_file()
        assert path is not None
        assert path.name == "test_module.py"

    def test_forward_not_implemented(self):
        class EmptyModule(Module):
            pass

        m = EmptyModule()
        with pytest.raises(NotImplementedError):
            m.forward(1)


# ---------------------------------------------------------------------------
# ModuleRunner
# ---------------------------------------------------------------------------


class TestModuleRunner:
    def test_creation(self, prompts_dir, state_dir, tmp_path):
        m = SimplePipeline()
        m.verbose = False
        runner = ModuleRunner(m, project_dir=tmp_path, router=None)
        assert runner.project_dir == tmp_path
        assert runner.prompts_dir == tmp_path / "prompts"
        assert m._runner is runner

    def test_dry_run(self, prompts_dir, state_dir, tmp_path):
        m = SimplePipeline()
        m.verbose = False
        runner = ModuleRunner(m, project_dir=tmp_path, router=None)

        report = runner.dry_run()
        assert report["module"] == "SimplePipeline"
        assert "orient" in report["steps"]
        assert "execute" in report["steps"]
        assert "finalize" in report["steps"]
        assert report["steps"]["orient"]["prompt_exists"] is True
        assert "genome" in report
        assert "forward_source" in report

    def test_run_stub_mode(self, prompts_dir, state_dir, tmp_path):
        """Full run in stub mode (no router)."""
        m = SimplePipeline()
        m.verbose = False
        runner = ModuleRunner(m, project_dir=tmp_path, router=None, budget=2)

        results = runner.run(budget=2, resume=False)
        assert len(results) >= 1  # runs until budget or no pending tasks

    def test_resume(self, prompts_dir, state_dir, tmp_path):
        """Resume from prior state raises without flag."""
        m = SimplePipeline()
        m.verbose = False

        # Set cycle count to simulate prior run
        (state_dir / "cycle_count.txt").write_text("5")

        runner = ModuleRunner(m, project_dir=tmp_path, router=None)
        with pytest.raises(RuntimeError, match="prior cycles"):
            runner.run(budget=1)

        # With resume=True it works
        results = runner.run(budget=1, resume=True)
        assert len(results) == 1

    def test_conditional_forward(self, prompts_dir, state_dir, tmp_path):
        """Conditional pipeline with match()."""
        m = ConditionalPipeline()
        m.verbose = False
        runner = ModuleRunner(m, project_dir=tmp_path, router=None, budget=1)

        results = runner.run(budget=1)
        assert len(results) == 1
        # All steps should have run (stub mode)
        assert "orient" in m._outputs
        assert "plan" in m._outputs
        assert "execute" in m._outputs


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------


class TestModuleLoader:
    def test_load_module_class(self, tmp_path: Path):
        """Load Module subclass from ralph.py."""
        langywrap_dir = tmp_path / ".langywrap"
        langywrap_dir.mkdir()

        ralph_py = langywrap_dir / "ralph.py"
        ralph_py.write_text(textwrap.dedent("""\
            from langywrap.ralph.module import Module, step

            class TestPipeline(Module):
                prompts = "prompts"
                state = "state"
                orient = step("haiku", "orient.md")

                def forward(self, cycle):
                    self.orient()
        """))

        module = load_module_config(tmp_path)
        assert module is not None
        assert type(module).__name__ == "TestPipeline"
        assert "orient" in module._step_defs

    def test_load_module_instance(self, tmp_path: Path):
        """Load pre-instantiated Module from 'module' attribute."""
        langywrap_dir = tmp_path / ".langywrap"
        langywrap_dir.mkdir()

        ralph_py = langywrap_dir / "ralph.py"
        ralph_py.write_text(textwrap.dedent("""\
            from langywrap.ralph.module import Module, step

            class MyPipeline(Module):
                orient = step("haiku", "orient.md")
                def forward(self, cycle):
                    self.orient()

            module = MyPipeline()
        """))

        mod = load_module_config(tmp_path)
        assert mod is not None
        assert isinstance(mod, Module)

    def test_no_module_returns_none(self, tmp_path: Path):
        """No ralph.py → None."""
        assert load_module_config(tmp_path) is None

    def test_no_module_subclass(self, tmp_path: Path):
        """ralph.py without Module subclass → None."""
        langywrap_dir = tmp_path / ".langywrap"
        langywrap_dir.mkdir()
        ralph_py = langywrap_dir / "ralph.py"
        ralph_py.write_text("x = 42\n")

        assert load_module_config(tmp_path) is None

    def test_pipeline_config_not_module(self, tmp_path: Path):
        """ralph.py with Pipeline (not Module) → not loaded as Module."""
        langywrap_dir = tmp_path / ".langywrap"
        langywrap_dir.mkdir()
        ralph_py = langywrap_dir / "ralph.py"
        ralph_py.write_text(textwrap.dedent("""\
            from langywrap.ralph.pipeline import Pipeline, Step
            config = Pipeline(steps=[Step("orient", model="haiku")])
        """))

        # Module loader should not pick up Pipeline configs
        mod = load_module_config(tmp_path)
        assert mod is None


# ---------------------------------------------------------------------------
# HyperAgent integration
# ---------------------------------------------------------------------------


class TestHyperAgentIntegration:
    def test_genome_roundtrip(self):
        """Export genome → apply overrides → verify."""
        m = SimplePipeline()
        genome = m.export_genome()

        # Simulate mutation
        genome["orient"]["model"] = "opus"
        genome["execute"]["timeout"] = 180

        m.apply_overrides({
            "orient.model": genome["orient"]["model"],
            "execute.timeout": genome["execute"]["timeout"],
        })

        genome2 = m.export_genome()
        assert genome2["orient"]["model"] == "opus"
        assert genome2["execute"]["timeout"] == 180

    def test_meta_mutation_source(self):
        """Meta-agent can read forward() source for diff generation."""
        m = ConditionalPipeline()
        src = m.get_forward_source()
        assert "cycle_type = match(self.plan," in src
        assert "self.execute(model=\"kimi\")" in src
        assert "self.validate()" in src

    def test_source_file_path(self):
        """Source file path available for meta-mutation diffs."""
        m = SimplePipeline()
        path = m.get_source_file()
        assert path is not None
        assert path.exists()

    def test_multiple_overrides(self):
        """Apply many mutations at once."""
        m = SimplePipeline()
        m.apply_overrides({
            "orient.model": "opus",
            "orient.timeout": 60,
            "execute.model": "kimi",
            "execute.timeout": 180,
            "execute.fail_fast": True,
            "finalize.enabled": False,
        })

        assert m._step_defs["orient"].model == "opus"
        assert m._step_defs["orient"].timeout == 60
        assert m._step_defs["execute"].model == "kimi"
        assert m._step_defs["execute"].timeout == 180
        assert m._step_defs["execute"].fail_fast is True
        assert m._step_defs["finalize"].enabled is False

    def test_unknown_step_ignored(self):
        """Override for non-existent step is silently ignored."""
        m = SimplePipeline()
        m.apply_overrides({"nonexistent.model": "opus"})
        # No error, no change
        assert len(m._step_defs) == 3

    def test_invalid_override_key_ignored(self):
        m = SimplePipeline()
        before = m._step_defs["orient"].model
        m.apply_overrides({"orient": "bad"})
        assert m._step_defs["orient"].model == before

    def test_get_forward_source_handles_inspect_error(self, monkeypatch):
        m = SimplePipeline()
        monkeypatch.setattr(
            "langywrap.ralph.module.inspect.getsource",
            lambda obj: (_ for _ in ()).throw(OSError()),
        )
        assert m.get_forward_source() == ""

    def test_get_source_file_handles_inspect_error(self, monkeypatch):
        m = SimplePipeline()
        monkeypatch.setattr(
            "langywrap.ralph.module.inspect.getfile",
            lambda obj: (_ for _ in ()).throw(TypeError()),
        )
        assert m.get_source_file() is None

    def test_execute_step_with_router_success(self, prompts_dir, state_dir, tmp_path):
        class Router:
            def execute(self, **kwargs):
                self.kwargs = kwargs
                return type("Result", (), {"text": "router output"})()

        router = Router()
        m = SimplePipeline()
        m.verbose = False
        ModuleRunner(m, project_dir=tmp_path, router=router)
        m._cycle_num = 1
        m._orient_context = "context"

        output = m.orient(inject="extra")

        assert output == "router output"
        assert m.orient.success is True
        assert (state_dir / "steps" / "orient.md").read_text(encoding="utf-8") == "router output"
        assert router.kwargs["model"].startswith("claude-")
        assert router.kwargs["tag"] == "orient"

    def test_execute_step_missing_prompt_and_abort(self, prompts_dir, state_dir, tmp_path):
        m = SimplePipeline()
        m.verbose = False
        ModuleRunner(m, project_dir=tmp_path, router=object())
        m._cycle_num = 1
        m._orient_context = ""

        output = m._execute_step("missing", "m", "absent.md", 1, [], fail_fast=True)
        assert output[1] is False
        assert "no prompt template" in output[0]

        m._abort = True
        skipped = m._execute_step("later", "m", "orient.md", 1, [])
        assert "SKIPPED" in skipped[0]

    def test_execute_step_router_timeout_sets_abort(
        self, prompts_dir, state_dir, tmp_path, monkeypatch
    ):
        class Router:
            def execute(self, **kwargs):
                raise TimeoutError("hung")

        monkeypatch.setattr("langywrap.ralph.module.time.sleep", lambda seconds: None)
        m = SimplePipeline()
        m.verbose = False
        ModuleRunner(m, project_dir=tmp_path, router=Router())
        m._cycle_num = 1
        output, success = m._execute_step("orient", "m", "orient.md", 1, [], fail_fast=True)

        assert success is False
        assert "TIMEOUT" in output
        assert m._abort is True

    def test_execute_step_router_error_sets_abort(self, prompts_dir, state_dir, tmp_path):
        class Router:
            def execute(self, **kwargs):
                raise RuntimeError("bad api")

        m = SimplePipeline()
        m.verbose = False
        ModuleRunner(m, project_dir=tmp_path, router=Router())
        m._cycle_num = 1
        output, success = m._execute_step("orient", "m", "orient.md", 1, [], fail_fast=True)

        assert success is False
        assert "bad api" in output
        assert m._abort is True


# ---------------------------------------------------------------------------
# Inner loop pattern
# ---------------------------------------------------------------------------


class TestInnerLoop:
    def test_retry_loop_in_forward(self, prompts_dir, state_dir, tmp_path):
        """Verify a forward() with explicit retry loop works."""

        class LoopPipeline(Module):
            prompts = "prompts"
            state = "state"
            gates = []
            git = []
            hygiene_every = None
            verbose = False

            engineer = step("kimi", "engineer.md")
            review = step("sonnet", "review.md")

            def forward(self, cycle: int):
                for _attempt in range(3):
                    self.engineer()
                    self.review()
                    if "LGTM" in self.review.output:
                        break

        m = LoopPipeline()
        runner = ModuleRunner(m, project_dir=tmp_path, router=None)
        results = runner.run(budget=1)
        assert len(results) == 1
        # In stub mode, review output won't contain LGTM,
        # so it runs all 3 iterations
        assert "engineer" in m._outputs
        assert "review" in m._outputs

    def test_escalation_in_forward(self, prompts_dir, state_dir, tmp_path):
        """Model escalation within a loop."""

        class EscalatePipeline(Module):
            prompts = "prompts"
            state = "state"
            gates = []
            git = []
            hygiene_every = None
            verbose = False

            engineer = step("kimi", "engineer.md")
            review = step("sonnet", "review.md")
            _models_used: list[str] = []

            def forward(self, cycle: int):
                models = ["kimi", "kimi", "sonnet", "opus"]
                for _attempt, model in enumerate(models):
                    self.engineer(model=model)
                    # Track which model was used (for test assertion)
                    type(self)._models_used.append(model)
                    self.review()
                    if "LGTM" in self.review.output:
                        break

        m = EscalatePipeline()
        EscalatePipeline._models_used = []
        runner = ModuleRunner(m, project_dir=tmp_path, router=None)
        runner.run(budget=1)
        # All 4 models used (LGTM never appears in stub)
        assert EscalatePipeline._models_used == ["kimi", "kimi", "sonnet", "opus"]
