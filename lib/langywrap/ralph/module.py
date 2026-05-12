"""
langywrap.ralph.module — DSPy-style Module runner for ralph loops.

Defines ralph pipelines as Python classes with ``forward()`` methods.
Steps are class attributes (the *genome*); ``forward()`` is the *program*.

HyperAgent compatibility:
    - Random mutations: patch step attributes via ``apply_overrides()``
    - Meta-mutations: rewrite ``forward()`` source code via diffs
    - ``export_genome()`` → flat dict for archive serialization

Usage::

    from langywrap.ralph.module import Module, step, match, gate

    class MyPipeline(Module):
        prompts = "research/prompts"
        state   = "research"

        orient   = step("haiku",  "orient.md",  fail_fast=True)
        execute  = step("sonnet", "execute.md", timeout=120)
        finalize = step("kimi",   "finalize.md")

        def forward(self, cycle: int):
            self.orient()
            self.execute()
            if gate("./just check"):
                self.finalize()

    # Run:
    from langywrap.ralph.module import ModuleRunner
    runner = ModuleRunner(MyPipeline(), project_dir=Path("."))
    runner.run(budget=20)
"""

from __future__ import annotations

import contextlib
import inspect
import logging
import re
import subprocess
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from langywrap.ralph.config import ModelSubstitution, substitute_model_name
from langywrap.ralph.context import build_full_prompt, build_orient_context
from langywrap.ralph.state import CycleResult, RalphState

log = logging.getLogger(__name__)

# Router import — graceful fallback
try:
    from langywrap.router import ExecutionRouter  # type: ignore[import]
except ImportError:
    ExecutionRouter = None  # type: ignore[assignment,misc]

# Model aliases (shared with pipeline.py)
_MODEL_ALIASES: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
    "kimi": "nvidia/moonshotai/kimi-k2.6",
    "gemma4": "openrouter/google/gemma-4-31b-it",
    "gemma4-nvidia": "nvidia/google/gemma-4-31b-it",
    "gemma4-openrouter": "openrouter/google/gemma-4-31b-it:free",
}


def _resolve_model(name: str) -> str:
    return _MODEL_ALIASES.get(name, name)


# ---------------------------------------------------------------------------
# StepDef — class-level step definition (descriptor)
# ---------------------------------------------------------------------------


class StepDef:
    """Step definition. Becomes a callable :class:`BoundStep` on instances.

    Used as a class attribute on :class:`Module` subclasses::

        class MyPipeline(Module):
            orient = step("haiku", "orient.md", fail_fast=True)
    """

    def __init__(
        self,
        model: str = "sonnet",
        prompt: str = "",
        *,
        timeout: int = 30,
        tools: list[str] | None = None,
        fail_fast: bool = False,
        enabled: bool = True,
    ) -> None:
        self.model = model
        self.prompt = prompt
        self.timeout = timeout
        self.tools = tools or ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]
        self.fail_fast = fail_fast
        self.enabled = enabled
        self._attr_name: str = ""  # set by __set_name__

    def __set_name__(self, owner: type, name: str) -> None:
        self._attr_name = name

    def __get__(self, obj: Module | None, objtype: type | None = None) -> StepDef | BoundStep:
        if obj is None:
            return self  # class-level access returns the definition
        # Instance-level: return a bound callable step
        cache_key = f"_bound_{self._attr_name}"
        bound = obj.__dict__.get(cache_key)
        if bound is None:
            bound = BoundStep(self, obj)
            obj.__dict__[cache_key] = bound
        return bound

    def copy(self, **overrides: Any) -> StepDef:
        """Return a copy with overrides applied."""
        new = StepDef(
            model=overrides.get("model", self.model),
            prompt=overrides.get("prompt", self.prompt),
            timeout=overrides.get("timeout", self.timeout),
            tools=overrides.get("tools", list(self.tools)),
            fail_fast=overrides.get("fail_fast", self.fail_fast),
            enabled=overrides.get("enabled", self.enabled),
        )
        new._attr_name = self._attr_name
        return new


def step(
    model: str = "sonnet",
    prompt: str = "",
    *,
    timeout: int = 30,
    tools: list[str] | None = None,
    fail_fast: bool = False,
    enabled: bool = True,
) -> StepDef:
    """Create a step definition for use as a Module class attribute.

    Example::

        class MyPipeline(Module):
            orient = step("haiku", "orient.md", fail_fast=True)
    """
    return StepDef(
        model=model,
        prompt=prompt,
        timeout=timeout,
        tools=tools,
        fail_fast=fail_fast,
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# BoundStep — instance-level callable step
# ---------------------------------------------------------------------------


class BoundStep:
    """A step bound to a Module instance. Callable and holds output state.

    Usage in ``forward()``::

        output = self.execute()          # run with defaults
        output = self.execute(model="kimi")  # override model for this call
        output = self.execute(inject="extra prompt text")

        # Access last output:
        if re.search(r"pattern", self.execute.output):
            ...
    """

    def __init__(self, step_def: StepDef, module: Module) -> None:
        self._def = step_def
        self._module = module
        self.output: str = ""
        self.success: bool = False
        self.name: str = step_def._attr_name

    @property
    def model(self) -> str:
        return self._def.model

    @property
    def enabled(self) -> bool:
        return self._def.enabled

    def __call__(
        self,
        *,
        model: str | None = None,
        prompt: str | None = None,
        timeout: int | None = None,
        tools: list[str] | None = None,
        inject: str = "",
    ) -> str:
        """Execute this step via the Module's runner context.

        Args:
            model:   Override model for this call only.
            prompt:  Override prompt template for this call only.
            timeout: Override timeout for this call only.
            tools:   Override tool list for this call only.
            inject:  Extra text appended to the prompt.

        Returns:
            Step output text.
        """
        if not self._def.enabled:
            self._module._log(f"  [{self.name}] SKIPPED (disabled)")
            self.output = f"# {self.name} SKIPPED (disabled)\n"
            self.success = False
            return self.output

        effective_model = _resolve_model(model or self._def.model)
        runner = self._module._runner
        if runner is not None:
            effective_model = substitute_model_name(effective_model, runner.model_substitutions)
        effective_prompt = prompt or self._def.prompt
        effective_timeout = timeout or self._def.timeout
        effective_tools = tools or self._def.tools

        self.output, self.success = self._module._execute_step(
            name=self.name,
            model=effective_model,
            prompt=effective_prompt,
            timeout=effective_timeout,
            tools=effective_tools,
            inject=inject,
            fail_fast=self._def.fail_fast,
        )

        return self.output

    def __repr__(self) -> str:
        return f"BoundStep({self.name!r}, model={self._def.model!r})"


# ---------------------------------------------------------------------------
# Helper functions for use in forward()
# ---------------------------------------------------------------------------


def match(bound_step: BoundStep, **patterns: str) -> str:
    """Classify cycle type by matching step output against regex patterns.

    Returns the name of the first matching pattern, or "" if none match.

    Usage in ``forward()``::

        cycle_type = match(self.plan,
            lean=r"sorry.*fill|\\.lean|lake build",
            research=r"web.?research|literature|arXiv",
        )
        if cycle_type == "lean":
            self.execute(model="kimi")
    """
    text = bound_step.output
    if not text:
        return ""
    for name, pattern in patterns.items():
        if re.search(pattern, text, re.IGNORECASE):
            return name
    return ""


def gate(command: str, cwd: Path | None = None, timeout: int = 600) -> bool:
    """Run a shell command as a quality gate. Returns True if exit code 0.

    Usage in ``forward()``::

        if not gate("./lean-check.sh"):
            self.lean_fix()
    """
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        return False


def gate_output(command: str, cwd: Path | None = None, timeout: int = 600) -> tuple[bool, str]:
    """Run a gate command, return (passed, combined_output).

    Like :func:`gate` but also returns stdout+stderr for error injection.
    """
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, combined
    except subprocess.TimeoutExpired:
        return False, "Gate command timed out"
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Module — base class for pipeline definitions
# ---------------------------------------------------------------------------


class Module:
    """Base class for DSPy-style ralph pipeline definitions.

    Subclass and define:
      - Step attributes (the *genome* — HyperAgent-mutable)
      - ``forward(cycle)`` method (the *program* — meta-mutation-mutable)

    Example::

        class MyPipeline(Module):
            prompts = "research/prompts"
            state   = "research"
            scope   = "Do not modify data/"

            orient   = step("haiku",  "orient.md",  fail_fast=True)
            execute  = step("sonnet", "execute.md", timeout=120)
            finalize = step("kimi",   "finalize.md")

            def forward(self, cycle: int):
                self.orient()
                self.execute()
                self.finalize()
    """

    # Override in subclass:
    prompts: str = ""
    state: str = "ralph"
    tasks_file: str = ""  # Override path for tasks.md (relative to project_dir)
    progress_file: str = ""  # Override path for progress.md (relative to project_dir)
    scope: str = ""
    gates: list[str] = []
    git: list[str] = []
    secrets: list[str] = []
    hygiene_every: int | None = 5
    verbose: bool = True

    def __init__(self) -> None:
        # Collect all StepDef attributes
        self._step_defs: dict[str, StepDef] = {}
        for name in dir(type(self)):
            attr = getattr(type(self), name, None)
            if isinstance(attr, StepDef):
                if not attr._attr_name:
                    attr._attr_name = name
                self._step_defs[name] = attr

        # Runtime context (set by ModuleRunner before forward() call)
        self._runner: ModuleRunner | None = None
        self._cycle_num: int = 0
        self._orient_context: str = ""
        self._outputs: dict[str, str] = {}  # step_name → output
        self._abort: bool = False

    def forward(self, cycle: int) -> None:
        """Override this method to define your pipeline.

        Called once per cycle. Use ``self.step_name()`` to execute steps,
        ``match()`` to classify cycle types, ``gate()`` to run quality checks.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement forward()")

    # -----------------------------------------------------------------------
    # Step execution (called by BoundStep.__call__)
    # -----------------------------------------------------------------------

    def _execute_step(
        self,
        name: str,
        model: str,
        prompt: str,
        timeout: int,
        tools: list[str],
        inject: str = "",
        fail_fast: bool = False,
    ) -> tuple[str, bool]:
        """Execute a single step. Called by BoundStep.__call__().

        Routes through ExecutionRouter if available, otherwise stub mode.
        """
        if self._abort:
            self._log(f"  [{name}] SKIPPED (abort from prior fail_fast)")
            return f"# {name} SKIPPED (abort)\n", False

        self._log(f"\n  ┌── STEP: {name.upper()} ──")
        self._log(f"  │   Model:   {model}")
        self._log(f"  │   Timeout: {timeout}m")

        runner = self._runner
        if runner is None:
            self._log(f"  └── {name}: STUB (no runner)\n")
            output = f"# {name} STUB\n"
            self._outputs[name] = output
            return output, True

        # Resolve prompt template
        prompts_dir = runner.prompts_dir
        prompt_path = prompts_dir / prompt if prompt else prompts_dir / f"{name}.md"
        if not prompt_path.exists():
            for candidate in prompts_dir.glob(f"*_{name}*.md"):
                prompt_path = candidate
                break

        if not prompt_path.exists():
            self._log(f"  └── {name}: SKIP (no prompt template: {prompt_path})\n")
            return f"# {name} ERROR: no prompt template\n", False

        template = prompt_path.read_text(encoding="utf-8")
        if inject:
            template = template + "\n\n---\n\n" + inject

        is_orient = name == "orient"

        full_prompt = build_full_prompt(
            template=template,
            project_dir=runner.project_dir,
            state_dir=runner.state.state_dir,
            cycle_num=self._cycle_num,
            orient_context=self._orient_context if is_orient else "",
            scope_restriction=self.scope,
            is_orient_step=is_orient,
        )

        # Route through ExecutionRouter
        if runner.router is None:
            self._log(f"  └── {name}: STUB (no router)\n")
            output = f"# {name} STUB\n"
            self._outputs[name] = output
            return output, True

        tools_str = ",".join(tools)
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                result = runner.router.execute(
                    prompt=full_prompt,
                    model=model,
                    engine="auto",
                    timeout_minutes=timeout,
                    tools=tools_str,
                    tag=name,
                )
                output = result.text
                self._outputs[name] = output

                # Save to steps/ directory
                out_path = runner.state.step_output_path(name)
                out_path.write_text(output, encoding="utf-8")

                self._log(f"  └── {name}: done ({len(output)} chars)\n")
                return output, True

            except TimeoutError as exc:
                output_size = len(str(exc))
                if attempt < max_attempts and output_size < 2000:
                    self._log(f"  │   [{name}] API hang. Retry {attempt}/{max_attempts - 1}...")
                    time.sleep(15)
                    continue
                self._log(f"  └── {name}: TIMEOUT\n")
                output = f"# {name} TIMEOUT\n{exc}\n"
                self._outputs[name] = output
                if fail_fast:
                    self._abort = True
                return output, False

            except Exception as exc:
                self._log(f"  └── {name}: ERROR — {exc}\n")
                output = f"# {name} ERROR\n{exc}\n"
                self._outputs[name] = output
                if fail_fast:
                    self._abort = True
                return output, False

        output = f"# {name} FAILED after {max_attempts} attempts\n"
        self._outputs[name] = output
        if fail_fast:
            self._abort = True
        return output, False

    # -----------------------------------------------------------------------
    # Logging
    # -----------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        log.info(msg)
        if self.verbose and not log.isEnabledFor(logging.INFO):
            print(msg)

    # -----------------------------------------------------------------------
    # HyperAgent genome interface
    # -----------------------------------------------------------------------

    def export_genome(self) -> dict[str, Any]:
        """Export mutable step parameters as a flat dict.

        Random mutations operate on this dict::

            genome = module.export_genome()
            # {'orient': {'model': 'haiku', 'timeout': 30, ...}, ...}
        """
        genome: dict[str, Any] = {}
        for name, sd in self._step_defs.items():
            genome[name] = {
                "model": sd.model,
                "prompt": sd.prompt,
                "timeout": sd.timeout,
                "tools": list(sd.tools),
                "fail_fast": sd.fail_fast,
                "enabled": sd.enabled,
            }
        return genome

    def apply_overrides(self, overrides: dict[str, Any]) -> None:
        """Apply HyperAgent variant overrides (genome patches) in-place.

        Modifies the class-level StepDef attributes so that subsequent
        ``forward()`` calls use the new values.

        Example::

            module.apply_overrides({
                "orient.model": "sonnet",
                "execute.timeout": 180,
                "validate.enabled": False,
            })
        """
        for key, value in overrides.items():
            parts = key.split(".", 1)
            if len(parts) != 2:
                continue
            step_name, field = parts

            if step_name not in self._step_defs:
                continue

            old_def = self._step_defs[step_name]
            new_def = old_def.copy(**{field: value})
            self._step_defs[step_name] = new_def
            # Update class attribute so descriptor works
            setattr(type(self), step_name, new_def)
            # Clear bound step cache
            cache_key = f"_bound_{step_name}"
            self.__dict__.pop(cache_key, None)

    def get_forward_source(self) -> str:
        """Return the source code of this module's forward() method.

        Used by HyperAgent meta-mutations to analyze and rewrite the
        pipeline structure.
        """
        try:
            return inspect.getsource(self.forward)
        except (OSError, TypeError):
            return ""

    def get_source_file(self) -> Path | None:
        """Return the source file path of this Module subclass.

        Used by HyperAgent meta-mutations to apply diffs.
        """
        try:
            src = inspect.getfile(type(self))
            return Path(src)
        except (OSError, TypeError):
            return None


# ---------------------------------------------------------------------------
# ModuleRunner — orchestrates Module.forward() with full lifecycle
# ---------------------------------------------------------------------------


class ModuleRunner:
    """Runs a Module-based pipeline with full ralph loop lifecycle.

    Handles: cycle counting, orient context, hygiene injection, periodic tasks,
    adversarial triggers, quality gates, git commits, peak-hour throttle.

    Usage::

        module = MyPipeline()
        runner = ModuleRunner(module, project_dir=Path("."))
        results = runner.run(budget=20)
    """

    def __init__(
        self,
        module: Module,
        project_dir: Path,
        router: ExecutionRouter | None = None,
        *,
        budget: int = 10,
        throttle_utc: str = "",
        throttle_weekdays_only: bool = True,
        periodic: list[dict[str, Any]] | None = None,
        model_substitutions: list[ModelSubstitution] | None = None,
    ) -> None:
        self.module = module
        self.project_dir = project_dir.resolve()
        self.router = router
        self.budget = budget
        self.model_substitutions = model_substitutions or []

        # State directory
        state_rel = module.state or "ralph"
        tasks_path = (self.project_dir / module.tasks_file) if module.tasks_file else None
        progress_path = (self.project_dir / module.progress_file) if module.progress_file else None
        self.state = RalphState(
            self.project_dir / state_rel,
            tasks_file=tasks_path,
            progress_file=progress_path,
        )

        # Prompts directory
        if module.prompts:
            self.prompts_dir = self.project_dir / module.prompts
        else:
            self.prompts_dir = self.project_dir / state_rel / "prompts"

        # Throttle
        self._throttle_start: int | None = None
        self._throttle_end: int | None = None
        self._throttle_weekdays = throttle_weekdays_only
        if throttle_utc and "-" in throttle_utc:
            parts = throttle_utc.split("-")
            self._throttle_start = int(parts[0])
            self._throttle_end = int(parts[1])

        # Periodic tasks
        self._periodic = periodic or []

        # Wire module to runner
        module._runner = self

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def run(
        self,
        budget: int | None = None,
        resume: bool = False,
    ) -> list[CycleResult]:
        """Main loop. Runs up to ``budget`` cycles."""
        max_cycles = budget or self.budget
        results: list[CycleResult] = []

        last_cycle = self.state.get_cycle_count()
        if last_cycle > 0 and not resume:
            raise RuntimeError(
                f"State has {last_cycle} prior cycles. Pass resume=True to continue."
            )

        start = last_cycle + 1
        end = last_cycle + max_cycles

        self._log(f"ModuleRunner starting: cycles {start}–{end}")
        self._log(f"  Module:  {type(self.module).__name__}")
        self._log(f"  Project: {self.project_dir}")
        self._log(f"  Steps:   {list(self.module._step_defs.keys())}")

        for cycle_num in range(start, end + 1):
            pending = self.state.pending_count()
            if pending == 0:
                self._log(f"Cycle {cycle_num}: no pending tasks — done.")
                break

            self._wait_if_peak_hours()

            self._log(f"\n{'=' * 60}")
            self._log(f"Cycle {cycle_num}/{end}  ({pending} pending)")
            self._log(f"{'=' * 60}")

            # Hygiene injection
            if (
                self.module.hygiene_every is not None
                and self.module.hygiene_every > 0
                and cycle_num % self.module.hygiene_every == 0
            ):
                gate_cmd = self.module.gates[0] if self.module.gates else ""
                injected = self.state.inject_hygiene_task(
                    cycle_num,
                    quality_gate_cmd=gate_cmd,
                )
                if injected:
                    self._log(f"  [hygiene] Injected for cycle {cycle_num}")

            # Periodic task injections
            for pt in self._periodic:
                every = pt.get("every", 0)
                if every and cycle_num % every == 0:
                    marker = pt.get("marker", "periodic")
                    template = pt.get("template", "")
                    if template:
                        rendered = template.format(
                            cycle=cycle_num,
                            date=date.today().isoformat(),
                        )
                        injected = self.state.inject_periodic_task(
                            cycle_num,
                            marker=marker,
                            content=rendered,
                        )
                        if injected:
                            self._log(f"  [{marker}] Injected for cycle {cycle_num}")

            # Run cycle
            result = self._run_cycle(cycle_num)
            results.append(result)

            self.state.set_cycle_count(cycle_num)
            self.state.append_progress(result)

            self._log(f"Cycle {cycle_num} done in {result.duration_seconds:.1f}s")

        self._log(f"\nModuleRunner finished: {len(results)} cycles.")
        return results

    def dry_run(self) -> dict:
        """Validate setup without running AI calls."""
        report: dict[str, Any] = {
            "module": type(self.module).__name__,
            "project_dir": str(self.project_dir),
            "prompts_dir": str(self.prompts_dir),
            "steps": {},
            "genome": self.module.export_genome(),
            "forward_source": self.module.get_forward_source(),
        }
        from langywrap.ralph.model_mix import module_model_mix

        report["model_mix"] = module_model_mix(self.module, self.model_substitutions)

        for name, sd in self.module._step_defs.items():
            prompt_path = (
                self.prompts_dir / sd.prompt if sd.prompt else self.prompts_dir / f"{name}.md"
            )
            if not prompt_path.exists():
                for candidate in self.prompts_dir.glob(f"*_{name}*.md"):
                    prompt_path = candidate
                    break
            report["steps"][name] = {
                "model": substitute_model_name(_resolve_model(sd.model), self.model_substitutions),
                "prompt": str(prompt_path),
                "prompt_exists": prompt_path.exists(),
                "timeout": sd.timeout,
                "enabled": sd.enabled,
            }

        report["cycle_count"] = self.state.get_cycle_count()
        report["pending_tasks"] = self.state.pending_count()
        report["router"] = "configured" if self.router else "stub"

        return report

    # -----------------------------------------------------------------------
    # Single cycle execution
    # -----------------------------------------------------------------------

    def _run_cycle(self, cycle_num: int) -> CycleResult:
        """Execute one cycle: clear state, build context, call forward()."""
        t_start = time.monotonic()
        result = CycleResult(cycle_number=cycle_num)

        # Fresh steps dir
        self.state.clear_steps()

        # Pre-digest orient context
        orient_ctx = build_orient_context(self.state, max_recent_cycles=3)
        self._log(f"  Orient context: {len(orient_ctx)} chars")

        # Set up module context
        self.module._cycle_num = cycle_num
        self.module._orient_context = orient_ctx
        self.module._outputs = {}
        self.module._abort = False

        # Call forward() — the user-defined pipeline
        try:
            self.module.forward(cycle_num)
        except Exception as exc:
            self._log(f"  FORWARD ERROR: {exc}")
            log.exception("forward() raised")

        # Collect results
        for name, _output in self.module._outputs.items():
            out_path = self.state.step_output_path(name)
            if out_path.exists():
                result.steps_completed[name] = out_path

        # Quality gates
        for gate_cmd in self.module.gates:
            self._log(f"\n  Quality gate: {gate_cmd}")
            passed = gate(gate_cmd, cwd=self.project_dir)
            if result.quality_gate_passed is None:
                result.quality_gate_passed = passed
            elif not passed:
                result.quality_gate_passed = False
            self._log(f"  Gate: {'PASS' if passed else 'FAIL'}")

        # Git commit
        if self.module.git:
            commit_hash = self._safe_git_commit(cycle_num)
            result.git_commit_hash = commit_hash

        result.duration_seconds = time.monotonic() - t_start
        return result

    # -----------------------------------------------------------------------
    # Git
    # -----------------------------------------------------------------------

    def _safe_git_commit(self, cycle_num: int) -> str | None:
        """Stage paths, scan secrets, commit."""
        git_dir = self.project_dir / ".git"
        if not git_dir.exists():
            return None

        # Stage
        for path in self.module.git:
            with contextlib.suppress(subprocess.CalledProcessError):
                subprocess.run(
                    ["git", "add", path],
                    cwd=self.project_dir,
                    capture_output=True,
                    check=True,
                )

        # Secret scan
        secret_hit = self._scan_secrets()
        if secret_hit:
            self._log(f"  SECRET: {secret_hit} — aborting commit")
            return None

        # Check staged
        r = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=self.project_dir,
            capture_output=True,
        )
        if r.returncode == 0:
            return None

        # Commit
        summary = self._extract_commit_summary(cycle_num)
        msg = f"chore(ralph): cycle {cycle_num} — {summary or 'auto'}"

        try:
            subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=self.project_dir,
                capture_output=True,
                check=True,
                text=True,
            )
            h = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=self.project_dir,
                capture_output=True,
                check=True,
                text=True,
            )
            commit_hash = h.stdout.strip()
            self._log(f"  Committed: {commit_hash}")
            return commit_hash
        except subprocess.CalledProcessError:
            return None

    def _extract_commit_summary(self, cycle_num: int) -> str:
        """Prefer finalized one-line summaries over raw plan frontmatter."""
        summary = self._extract_progress_summary(cycle_num)
        if summary:
            return summary

        for text in (
            self.state.read_plan(),
            self.state.read_step_output("plan"),
            self.state.read_step_output("orient"),
            self.state.read_step_output("finalize"),
        ):
            summary = self._extract_first_meaningful_line(text)
            if summary:
                return summary

        return ""

    def _extract_progress_summary(self, cycle_num: int) -> str:
        if not self.state.progress_file.exists():
            return ""

        text = self.state.progress_file.read_text(encoding="utf-8")
        cycle_match = re.search(
            rf"^## Cycle {cycle_num}\b(.*?)(?=^## Cycle \d+\b|\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        if cycle_match:
            for line in cycle_match.group(1).splitlines():
                stripped = line.strip()
                if stripped.lower().startswith("one-line:"):
                    return stripped.split(":", 1)[1].strip()[:72]

        table_match = re.search(
            rf"^\|\s*{cycle_num}\s*\|.*?\|\s*([^|]+?)\s*\|$",
            text,
            re.MULTILINE,
        )
        if table_match:
            return table_match.group(1).strip()[:72]

        return ""

    @staticmethod
    def _extract_first_meaningful_line(text: str) -> str:
        in_fence = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if re.fullmatch(r"```\w*", line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if line == "---":
                continue
            if line.startswith(("#", "<", "{")):
                continue
            if line.endswith(":"):
                continue
            if re.match(r"^[A-Z_]+_CONFIRMED:\s*", line):
                continue
            if re.fullmatch(r"[-=*`~]{3,}", line):
                continue

            line = re.sub(r"^[-*+]\s+", "", line)
            line = re.sub(r"^\d+\.\s+", "", line)
            line = re.sub(r"^\*\*([^*]+):\*\*\s*", r"\1: ", line)
            line = re.sub(r"^[*_`]+|[*_`]+$", "", line).strip()
            if line:
                return line[:72]
        return ""

    def _scan_secrets(self) -> str | None:
        """Check staged filenames against secret patterns."""
        try:
            r = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            return None

        patterns = self.module.secrets or [
            r"\.env$",
            r"credentials",
            r"secret",
            r"api_key",
        ]
        compiled = [re.compile(p, re.IGNORECASE) for p in patterns]

        for fname in r.stdout.strip().splitlines():
            for pat in compiled:
                if pat.search(fname):
                    return fname
        return None

    # -----------------------------------------------------------------------
    # Throttle
    # -----------------------------------------------------------------------

    def _wait_if_peak_hours(self) -> None:
        start = self._throttle_start
        end = self._throttle_end
        if start is None or end is None:
            return

        while True:
            now = datetime.now(UTC)
            if self._throttle_weekdays and now.weekday() >= 5:
                return
            if start <= now.hour < end:
                self._log(f"  [PEAK] {now:%H:%M} UTC — pausing")
                time.sleep(60)
            else:
                return

    # -----------------------------------------------------------------------
    # Logging
    # -----------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        log.info(msg)
        if self.module.verbose and not log.isEnabledFor(logging.INFO):
            print(msg)


# ---------------------------------------------------------------------------
# Module loader — detect Module subclass in ralph.py
# ---------------------------------------------------------------------------


def load_module_config(project_dir: Path) -> Module | None:
    """Load a Module subclass from ``.langywrap/ralph.py`` if one exists.

    Imports the module, finds the first ``Module`` subclass instance
    (looks for ``module`` or ``config`` attribute, or instantiates the
    first Module subclass found).

    Returns None if no ralph.py or no Module subclass found.
    """
    ralph_py = project_dir / ".langywrap" / "ralph.py"
    if not ralph_py.exists():
        return None

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f"_ralph_module_{project_dir.name}",
        ralph_py,
    )
    if spec is None or spec.loader is None:
        return None

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    # Look for 'module' attribute first
    obj = getattr(mod, "module", None)
    if isinstance(obj, Module):
        return obj

    # Look for 'config' attribute that's a Module
    obj = getattr(mod, "config", None)
    if isinstance(obj, Module):
        return obj

    # Find first Module subclass and instantiate it
    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if isinstance(attr, type) and issubclass(attr, Module) and attr is not Module:
            return attr()

    return None
