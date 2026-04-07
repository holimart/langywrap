"""
langywrap.ralph.runner — RalphLoop: the Python orchestrator for the ralph cycle.

Manages the orient → plan → execute → critic → finalize pipeline.
Actual AI calls go through ExecutionRouter; shell wrapping for execwrap stays bash.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langywrap.ralph.config import RalphConfig, StepConfig
from langywrap.ralph.context import build_full_prompt, build_orient_context
from langywrap.ralph.state import CycleResult, RalphState

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ExecutionRouter import — graceful fallback so ralph is importable standalone
# ---------------------------------------------------------------------------

try:
    from langywrap.router import ExecutionRouter  # type: ignore[import]
except ImportError:
    ExecutionRouter = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# RalphLoop
# ---------------------------------------------------------------------------


class RalphLoop:
    """Python orchestrator for the ralph autonomous research/engineering cycle.

    Usage::

        config = load_ralph_config(Path("."))
        router = ExecutionRouter(config)   # or None for dry-run
        loop = RalphLoop(config, router)
        results = loop.run(budget=20)
    """

    def __init__(
        self,
        config: RalphConfig,
        router: Optional["ExecutionRouter"] = None,
    ) -> None:
        self.config = config
        self.router = router
        self.state = RalphState(
            config.resolved_state_dir,
            tasks_file=config.resolved_tasks_file,
            progress_file=config.resolved_progress_file,
        )
        self._log = self._make_logger()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        budget: Optional[int] = None,
        resume: bool = False,
    ) -> list[CycleResult]:
        """Main loop. Runs up to `budget` cycles and returns all CycleResults.

        Args:
            budget:  Max cycles; defaults to config.budget.
            resume:  If True, continue from the last completed cycle number.
                     If False and prior state exists, raises RuntimeError
                     unless the state dir is empty.
        """
        max_cycles = budget if budget is not None else self.config.budget
        results: list[CycleResult] = []

        # Determine starting cycle
        last_cycle = self.state.get_cycle_count()
        if last_cycle > 0 and not resume:
            raise RuntimeError(
                f"State dir has {last_cycle} prior cycles. "
                "Pass resume=True to continue, or clear the state dir."
            )

        start_cycle = last_cycle + 1
        end_cycle = last_cycle + max_cycles

        self._log(f"RalphLoop starting: cycles {start_cycle}–{end_cycle}")
        self._log(f"  Project:   {self.config.project_dir}")
        self._log(f"  State dir: {self.config.resolved_state_dir}")
        self._log(f"  Steps:     {[s.name for s in self.config.steps]}")

        for cycle_num in range(start_cycle, end_cycle + 1):
            pending = self.state.pending_count()
            if pending == 0:
                self._log(f"Cycle {cycle_num}: no pending tasks — loop complete.")
                break

            # Peak-hour throttle
            self._wait_if_peak_hours()

            self._log(f"\n{'='*60}")
            self._log(f"Cycle {cycle_num}/{end_cycle}  ({pending} pending tasks)")
            self._log(f"{'='*60}")

            # Hygiene injection
            if (
                self.config.hygiene_every_n
                and cycle_num % self.config.hygiene_every_n == 0
            ):
                qg_cmd = self.config.quality_gate.command if self.config.quality_gate else ""
                injected = self.state.inject_hygiene_task(
                    cycle_num,
                    template=self.config.hygiene_template,
                    quality_gate_cmd=qg_cmd,
                )
                if injected:
                    self._log(f"  [hygiene] Injected maintenance task for cycle {cycle_num}")

            # Periodic task injections (lookback, etc.)
            for pt in self.config.periodic_tasks:
                every = pt.get("every", 0)
                if every and cycle_num % every == 0:
                    marker = pt.get("marker", "periodic")
                    template = pt.get("template", "")
                    if template:
                        from datetime import date
                        rendered = template.format(
                            cycle=cycle_num,
                            date=date.today().isoformat(),
                        )
                        injected = self.state.inject_periodic_task(
                            cycle_num, marker=marker, content=rendered,
                        )
                        if injected:
                            self._log(f"  [{marker}] Injected task for cycle {cycle_num}")

            # Check for adversarial every-N cycle
            is_adversarial = (
                self.config.adversarial_every_n
                and cycle_num > 1
                and cycle_num % self.config.adversarial_every_n == 0
            )
            if is_adversarial:
                self._log("  ADVERSARIAL CYCLE (every-N trigger)")
                result = self._run_adversarial_cycle(cycle_num)
            else:
                result = self.run_cycle(cycle_num)
            results.append(result)

            # Persist cycle count
            self.state.set_cycle_count(cycle_num)

            # Append progress
            self.state.append_progress(result)

            # Review milestone
            if cycle_num % self.config.review_every_n == 0:
                self._log(f"\n=== Review milestone: cycle {cycle_num} ===")
                self._print_review(results)

            # Stagnation check
            if len(results) >= 4 and self.detect_stagnation(n_cycles=4):
                self._log("WARNING: stagnation detected — last 4 cycles identical outcome. Consider diversifying tasks.")

            self._log(f"Cycle {cycle_num} done in {result.duration_seconds:.1f}s")

        self._log(f"\nRalphLoop finished: {len(results)} cycles.")
        return results

    def run_cycle(self, cycle_num: int) -> CycleResult:
        """Execute a single full pipeline cycle.

        Matches the proven riemann2 orchestration order:
        1. Clear steps/ dir
        2. Build orient context (pre-digested)
        3. Run pipeline steps (filtered by pipeline=True):
           - Check depends_on, run_if condition
           - Detect cycle type after plan step (model override for execute)
           - Cycle-type-aware prompt injection for execute
           - Retry loop (conditional on cycle type if retry_if_cycle_types set)
           - Fail-fast: skip remaining steps if fail_fast step fails
        4. Adversarial milestone trigger (content-based)
        5. Quality gates (primary + additional)
        6. Git commit
        """
        t_start = time.monotonic()
        result = CycleResult(cycle_number=cycle_num)

        # Fresh steps dir
        self.state.clear_steps()

        # Pre-digest state
        orient_ctx = build_orient_context(self.state, max_recent_cycles=3)
        self._log(f"  Orient context: {len(orient_ctx)} chars")

        # Cycle type is detected after plan step (needs plan.md content)
        cycle_type = ""

        # Accumulated tokens from completed steps (for depends_on checks)
        confirmed_outputs: dict[str, str] = {}  # step_name → output text
        abort_remaining = False

        # Only run steps with pipeline=True
        pipeline_steps = [s for s in self.config.steps if s.pipeline]

        for step in pipeline_steps:
            if abort_remaining:
                self._log(f"\n  ┌── STEP: {step.name.upper()} ──")
                self._log(f"  └── {step.name}: SKIPPED (fail-fast from prior step)")
                continue

            self._log(f"\n  ┌── STEP: {step.name.upper()} ──")
            self._log(f"  │   Timeout: {step.timeout_minutes}m")
            if step.model:
                self._log(f"  │   Model:   {step.model}")

            # Every-N check (e.g. review every 10th cycle)
            if step.every_n > 0 and cycle_num % step.every_n != 0:
                self._log(f"  └── {step.name}: SKIPPED (every {step.every_n} cycles)")
                continue

            # Check depends_on
            missing = self._check_depends_on(step, confirmed_outputs)
            if missing:
                self._log(f"  │   BLOCKED — missing tokens: {missing}")
                self._log(f"  └── {step.name}: SKIPPED (dependency not met)")
                result.confirmed_tokens[step.name] = False
                if step.fail_fast:
                    abort_remaining = True
                continue

            # Conditional step execution (run_if_step + run_if_pattern)
            if step.run_if_step and step.run_if_pattern:
                prior_output = confirmed_outputs.get(step.run_if_step, "")
                if not re.search(step.run_if_pattern, prior_output, re.IGNORECASE):
                    self._log(f"  └── {step.name}: SKIPPED (condition not met: "
                              f"{step.run_if_step} !~ /{step.run_if_pattern}/)")
                    continue

            # Cycle-type gating: skip step if cycle type doesn't match
            if step.run_if_cycle_types and cycle_type not in step.run_if_cycle_types:
                self._log(f"  └── {step.name}: SKIPPED (cycle type '{cycle_type}' "
                          f"not in {step.run_if_cycle_types})")
                continue

            # Mutual exclusion: if output_as slot already filled by a prior
            # variant, skip this step (e.g. execute.lean already wrote 'execute')
            output_key = step.output_as or step.name
            if output_key in result.steps_completed:
                self._log(f"  └── {step.name}: SKIPPED ('{output_key}' already produced)")
                continue

            cycle_ctx = {
                "cycle_num": cycle_num,
                "orient_context": orient_ctx,
                "confirmed_outputs": confirmed_outputs,
                "cycle_type": cycle_type,
                "cycle_prompt_extra": step.prompt_extra,
            }

            output, success = self._run_step_with_retries(
                step, cycle_ctx, cycle_type=cycle_type,
            )

            # Save output to steps/{output_key}.md
            out_path = self.state.step_output_path(output_key)
            out_path.write_text(output, encoding="utf-8")
            result.steps_completed[output_key] = out_path

            # Check confirmation token
            confirmed = self._check_token(output, step.confirmation_token)
            result.confirmed_tokens[output_key] = confirmed

            if confirmed:
                confirmed_outputs[output_key] = output
                self._log(f"  └── {step.name}: CONFIRMED ({step.confirmation_token})")
            else:
                confirmed_outputs[output_key] = output  # always store for run_if checks
                if step.confirmation_token:
                    self._log(f"  └── {step.name}: token '{step.confirmation_token}' NOT FOUND")
                else:
                    self._log(f"  └── {step.name}: done (no token check)")

            # Fail-fast check
            if step.fail_fast and not success:
                self._log(f"  └── {step.name}: FAIL-FAST — aborting remaining steps")
                abort_remaining = True

            # Detect cycle type after plan step (needs fresh plan.md)
            if step.name == "plan" and success:
                cycle_type = self._detect_cycle_type()
                if cycle_type:
                    self._log(f"  Cycle type: {cycle_type.upper()}")

        # Adversarial milestone trigger (content-based)
        if not abort_remaining and self._should_trigger_adversarial_milestone(confirmed_outputs):
            self._log("\n  ADVERSARIAL MILESTONE TRIGGER")
            self._run_adversarial_step(cycle_num, confirmed_outputs)

        # Quality gates (primary + additional)
        all_gates = []
        if self.config.quality_gate:
            all_gates.append(self.config.quality_gate)
        all_gates.extend(self.config.quality_gates)

        for i, gate in enumerate(all_gates):
            label = gate.command.split()[0] if gate.command else f"gate-{i}"
            self._log(f"\n  Quality gate ({label})...")
            qg_pass = self._run_quality_gate(gate)
            if i == 0:
                result.quality_gate_passed = qg_pass
            elif result.quality_gate_passed is True and not qg_pass:
                result.quality_gate_passed = False
            self._log(f"  Quality gate ({label}): {'PASS' if qg_pass else 'FAIL'}")

        # Git commit
        if self.config.git_commit_after_cycle:
            plan_summary = self._extract_plan_summary()
            commit_hash = self.safe_git_commit(cycle_num, plan_summary)
            result.git_commit_hash = commit_hash

        result.duration_seconds = time.monotonic() - t_start
        return result

    def run_step(
        self,
        step: StepConfig,
        cycle_context: dict,
    ) -> tuple[str, bool]:
        """Build prompt, call router/engine, return (output_text, success).

        Includes hang detection: if the call times out with tiny output (<2KB),
        retries up to config.max_hang_retries times before giving up.

        Falls back to a stub if no router is available (useful for testing).
        """
        prompt = self.build_prompt(step, cycle_context)

        if self.router is None:
            import logging
            logging.getLogger("langywrap.ralph").warning(
                "No router configured — running in stub mode. "
                "Configure .langywrap/router.yaml to enable AI execution."
            )
            self._log(f"    [STUB] No router — would run {step.name} with {len(prompt)} char prompt")
            return f"# {step.name} STUB\n{step.confirmation_token} stub=true\n", True

        max_attempts = self.config.max_hang_retries + 1
        for attempt in range(1, max_attempts + 1):
            try:
                result = self.router.execute(
                    role=step.role,
                    prompt=prompt,
                    timeout_minutes=step.timeout_minutes,
                    model=step.model or None,
                    tools=step.tools,
                    engine=step.engine,
                )
                return result.text, True
            except TimeoutError as exc:
                # Hang detection: timeout with tiny output → retry
                output_size = len(str(exc))
                if attempt < max_attempts and output_size < 2000:
                    self._log(f"    [{step.name}] API hang (timeout, {output_size}B). "
                              f"Retry {attempt}/{self.config.max_hang_retries}...")
                    time.sleep(15)
                    continue
                self._log(f"    [{step.name}] Timeout after {attempt} attempt(s): {exc}")
                return f"# {step.name} TIMEOUT\n{exc}\n", False
            except Exception as exc:
                err_str = str(exc).lower()
                # Rate limit detection
                if any(kw in err_str for kw in ("rate limit", "429", "too many requests")):
                    if attempt < max_attempts:
                        self._log(f"    [{step.name}] Rate limited. Waiting 10m before retry...")
                        time.sleep(600)
                        continue
                self._log(f"    ERROR in {step.name}: {exc}")
                return f"# {step.name} ERROR\n{exc}\n", False

        return f"# {step.name} FAILED after {max_attempts} attempts\n", False

    def build_prompt(self, step: StepConfig, context: dict) -> str:
        """Load template file, inject project header + orient context + scope.

        If context contains 'cycle_prompt_extra' (from cycle type detection),
        it is appended after the template for execute-role steps.
        """
        template_path = step.prompt_template
        if not template_path.exists():
            raise FileNotFoundError(f"Prompt template not found: {template_path}")

        template = template_path.read_text(encoding="utf-8")
        cycle_num: int = context.get("cycle_num", 0)
        orient_context: str = context.get("orient_context", "")

        # Inject cycle-type-specific prompt extra (e.g. research directive)
        prompt_extra: str = context.get("cycle_prompt_extra", "")
        if prompt_extra:
            template = template + "\n\n---\n\n" + prompt_extra

        # Inject retry error context if present
        retry_error: str = context.get("retry_error", "")
        retry_attempt: int = context.get("retry_attempt", 0)
        if retry_error and retry_attempt:
            template = template + (
                f"\n\n---\n\n## Retry Context (attempt {retry_attempt})\n\n"
                f"The previous attempt failed. Error output:\n\n```\n{retry_error[:5000]}\n```\n"
            )

        is_orient = step.name == "orient"

        return build_full_prompt(
            template=template,
            project_dir=self.config.project_dir,
            state_dir=self.config.resolved_state_dir,
            cycle_num=cycle_num,
            orient_context=orient_context if is_orient else "",
            scope_restriction=self.config.scope_restriction,
            is_orient_step=is_orient,
        )

    # ------------------------------------------------------------------
    # Quality gate
    # ------------------------------------------------------------------

    def quality_gate(self) -> bool:
        """Run the primary configured quality gate command. Returns True on pass."""
        if not self.config.quality_gate:
            return True
        return self._run_quality_gate(self.config.quality_gate)

    def _run_quality_gate(self, qg: "QualityGateConfig") -> bool:
        """Run a single quality gate. Returns True on pass."""
        from langywrap.ralph.config import QualityGateConfig  # noqa: F811

        cwd = (
            Path(qg.working_dir) if qg.working_dir else self.config.project_dir
        )
        timeout_sec = qg.timeout_minutes * 60

        self._log(f"    Running: {qg.command}")
        try:
            proc = subprocess.run(
                qg.command,
                shell=True,
                cwd=cwd,
                timeout=timeout_sec,
                capture_output=True,
                text=True,
            )
            passed = proc.returncode == 0
            if not passed:
                self._log(f"    Quality gate FAILED (exit {proc.returncode})")
                if proc.stdout:
                    self._log(f"    stdout: {proc.stdout[-500:]}")
                if proc.stderr:
                    self._log(f"    stderr: {proc.stderr[-500:]}")
            return passed
        except subprocess.TimeoutExpired:
            self._log(f"    Quality gate TIMED OUT ({qg.timeout_minutes}m)")
            return False
        except Exception as exc:
            self._log(f"    Quality gate ERROR: {exc}")
            return False

    # ------------------------------------------------------------------
    # Git commit
    # ------------------------------------------------------------------

    def safe_git_commit(self, cycle_num: int, plan_summary: str = "") -> Optional[str]:
        """Stage git_add_paths, scan for secrets, commit, return short hash.

        Returns None if commit was skipped or failed.
        """
        project_dir = self.config.project_dir

        # Check git is initialized
        git_dir = project_dir / ".git"
        if not git_dir.exists():
            self._log("    No .git directory — skipping commit.")
            return None

        # Stage explicit paths
        if self.config.git_add_paths:
            for path in self.config.git_add_paths:
                try:
                    subprocess.run(
                        ["git", "add", path],
                        cwd=project_dir,
                        capture_output=True,
                        check=True,
                    )
                except subprocess.CalledProcessError as exc:
                    self._log(f"    git add {path} failed: {exc.stderr}")

        # Secret scan on staged files
        secret_hit = self._scan_staged_for_secrets()
        if secret_hit:
            self._log(f"    SECRET SCAN: potential secret in staged file: {secret_hit}")
            self._log("    Aborting commit — manually review and unstage.")
            return None

        # Check if there's anything staged
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=project_dir,
            capture_output=True,
        )
        if result.returncode == 0:
            # Nothing staged
            self._log("    No staged changes — skipping commit.")
            return None

        # Build commit message
        summary = plan_summary or f"ralph cycle {cycle_num}"
        msg = f"chore(ralph): cycle {cycle_num} — {summary}"

        try:
            subprocess.run(
                ["git", "commit", "-m", msg],
                cwd=project_dir,
                capture_output=True,
                check=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            self._log(f"    git commit failed: {exc.stderr}")
            return None

        # Get the short hash
        try:
            hash_result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=project_dir,
                capture_output=True,
                check=True,
                text=True,
            )
            commit_hash = hash_result.stdout.strip()
            self._log(f"    Committed: {commit_hash}")
            return commit_hash
        except subprocess.CalledProcessError:
            return None

    # ------------------------------------------------------------------
    # Stagnation detection
    # ------------------------------------------------------------------

    def detect_stagnation(self, n_cycles: int = 4) -> bool:
        """Return True if the last n_cycles all share the same outcome.

        Reads the last N lines of progress.md for 'Outcome:' entries.
        """
        if not self.state.progress_file.exists():
            return False
        text = self.state.progress_file.read_text(encoding="utf-8")
        outcomes = re.findall(r"^Outcome:\s*(\w+)", text, re.MULTILINE)
        if len(outcomes) < n_cycles:
            return False
        recent = outcomes[-n_cycles:]
        return len(set(recent)) == 1

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------

    def dry_run(self) -> dict:
        """Validate setup without running any AI calls.

        Returns a dict with validation results.
        """
        report: dict = {
            "project_dir": str(self.config.project_dir),
            "state_dir": str(self.config.resolved_state_dir),
            "prompts_dir": str(self.config.resolved_prompts_dir),
            "steps": [],
            "state_files": {},
            "router": None,
            "quality_gate": None,
        }

        # Check state files
        for fname in ["tasks.md", "progress.md", "plan.md"]:
            p = self.config.resolved_state_dir / fname
            report["state_files"][fname] = {
                "exists": p.exists(),
                "size": p.stat().st_size if p.exists() else 0,
            }

        # Check step templates
        for step in self.config.steps:
            entry = {
                "name": step.name,
                "template": str(step.prompt_template),
                "template_exists": step.prompt_template.exists(),
                "template_size": (
                    step.prompt_template.stat().st_size
                    if step.prompt_template.exists()
                    else 0
                ),
                "role": str(step.role),
                "timeout_minutes": step.timeout_minutes,
                "confirmation_token": step.confirmation_token,
            }
            report["steps"].append(entry)

        # Router + backends
        if self.router is not None:
            router_info: dict = {
                "type": type(self.router).__name__,
                "config_name": getattr(self.router._config, "name", "?"),
                "backends": {},
                "routing": [],
            }
            for backend_enum, backend_cfg in self.router._backends.items():
                router_info["backends"][backend_enum.value] = {
                    "binary": backend_cfg.binary_path,
                    "execwrap": backend_cfg.execwrap_path,
                }
            # Show how each step would be routed
            for step in self.config.steps:
                try:
                    from langywrap.router.config import StepRole as RouterStepRole
                    role = RouterStepRole(step.role.value)
                    rule = self.router.route(role)
                    # Show effective model/engine (step config takes priority)
                    effective_model = step.model or rule.model
                    effective_backend = rule.backend.value
                    if step.engine and step.engine != "auto":
                        effective_backend = step.engine
                    entry: dict[str, Any] = {
                        "step": step.name,
                        "model": effective_model,
                        "backend": effective_backend,
                        "timeout_minutes": step.timeout_minutes,
                        "retry_models": rule.retry_models,
                    }
                    if step.run_if_cycle_types:
                        entry["when_cycle"] = step.run_if_cycle_types
                    if step.output_as:
                        entry["output_as"] = step.output_as
                    router_info["routing"].append(entry)
                except (LookupError, ValueError):
                    router_info["routing"].append({
                        "step": step.name,
                        "error": f"no rule for role={step.role.value}",
                    })
            report["router"] = router_info
        else:
            report["router"] = "None (stub mode)"

        # Quality gate
        if self.config.quality_gate:
            report["quality_gate"] = {
                "command": self.config.quality_gate.command,
                "timeout_minutes": self.config.quality_gate.timeout_minutes,
                "required": self.config.quality_gate.required,
            }

        # Cycle count
        report["cycle_count"] = self.state.get_cycle_count()
        report["pending_tasks"] = self.state.pending_count()

        return report

    # ------------------------------------------------------------------
    # Step retry loop
    # ------------------------------------------------------------------

    def _run_step_with_retries(
        self,
        step: StepConfig,
        cycle_context: dict,
        cycle_type: str = "",
    ) -> tuple[str, bool]:
        """Run a step, then optionally retry if retry_count > 0.

        If retry_gate_command is set, run it after each attempt. If it exits 0,
        stop retrying (success). If non-zero, inject error output and retry.

        If retry_if_cycle_types is set, retries only run when cycle_type matches.
        """
        output, success = self.run_step(step, cycle_context)

        if step.retry_count <= 0 or not step.retry_gate_command:
            return output, success

        # Check if retries are conditional on cycle type
        if step.retry_if_cycle_types and cycle_type not in step.retry_if_cycle_types:
            self._log(f"    [{step.name}] Retry skipped (cycle type '{cycle_type}' "
                      f"not in {step.retry_if_cycle_types})")
            return output, success

        for attempt in range(1, step.retry_count + 1):
            # Run gate command to check if retry is needed
            gate_pass, gate_output = self._run_gate_command(step.retry_gate_command)
            if gate_pass:
                self._log(f"    [{step.name}] Gate passed after {attempt - 1} retries")
                return output, True

            self._log(f"    [{step.name}] Gate failed — retry {attempt}/{step.retry_count}")

            # Build retry step with error context injected
            retry_step = step
            if step.retry_model:
                retry_step = step.model_copy(update={"model": step.retry_model})
            if step.retry_prompt_template:
                retry_step = retry_step.model_copy(
                    update={"prompt_template": step.retry_prompt_template}
                )

            # Inject gate error into context
            retry_ctx = dict(cycle_context)
            retry_ctx["retry_error"] = gate_output
            retry_ctx["retry_attempt"] = attempt

            output, success = self.run_step(retry_step, retry_ctx)

        # Final gate check after last retry
        gate_pass, _ = self._run_gate_command(step.retry_gate_command)
        if gate_pass:
            self._log(f"    [{step.name}] Gate passed after {step.retry_count} retries")
            return output, True

        self._log(f"    [{step.name}] Gate still failing after {step.retry_count} retries")
        return output, success

    def _run_gate_command(self, command: str) -> tuple[bool, str]:
        """Run a gate command, return (passed, combined_output)."""
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self.config.project_dir,
                timeout=600,
                capture_output=True,
                text=True,
            )
            combined = (proc.stdout or "") + (proc.stderr or "")
            return proc.returncode == 0, combined
        except subprocess.TimeoutExpired:
            return False, "Gate command timed out (10m)"
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # Peak-hour throttle
    # ------------------------------------------------------------------

    def _wait_if_peak_hours(self) -> None:
        """Block until off-peak if throttle is configured."""
        start = self.config.throttle_utc_start
        end = self.config.throttle_utc_end
        if start is None or end is None:
            return

        while True:
            now = datetime.now(timezone.utc)
            hour = now.hour

            if self.config.throttle_weekdays_only and now.weekday() >= 5:
                return  # weekend

            if start <= hour < end:
                minutes_left = (end - hour) * 60 - now.minute
                self._log(f"  [PEAK HOURS] {now:%H:%M} UTC — pausing. "
                          f"Off-peak in ~{minutes_left}m.")
                time.sleep(60)  # re-check every minute
            else:
                return

    # ------------------------------------------------------------------
    # Cycle type detection
    # ------------------------------------------------------------------

    def _detect_cycle_type(self) -> str:
        """Classify the current cycle by matching plan.md against cycle_type_rules.

        Returns the cycle type name, or empty string if no rule matches.

        Uses last-match-wins semantics: when multiple rules match (e.g. a
        research plan that also mentions Lean terms), the rule defined later
        in the config takes priority.  Place more specific / narrower rules
        after broader ones in ``cycle_types``.
        """
        rules = self.config.cycle_type_rules
        if not rules:
            return ""

        plan = self.state.read_plan()
        if not plan:
            return ""

        best = ""
        for rule in rules:
            pattern = rule.get("pattern", "")
            if pattern and re.search(pattern, plan, re.IGNORECASE):
                best = rule.get("name", "")

        return best

    # ------------------------------------------------------------------
    # Adversarial cycles
    # ------------------------------------------------------------------

    def _run_adversarial_cycle(self, cycle_num: int) -> CycleResult:
        """Run a full adversarial cycle: adversarial step + finalize + git commit."""
        t_start = time.monotonic()
        result = CycleResult(cycle_number=cycle_num)

        self.state.clear_steps()
        orient_ctx = build_orient_context(self.state, max_recent_cycles=3)
        confirmed_outputs: dict[str, str] = {}

        # Run adversarial step
        self._run_adversarial_step(cycle_num, confirmed_outputs)

        # Run finalize step to update tasks based on adversarial findings
        finalize_step = self._find_step("finalize")
        if finalize_step:
            self._log(f"\n  ┌── STEP: FINALIZE (after adversarial) ──")
            output, success = self.run_step(finalize_step, {
                "cycle_num": cycle_num,
                "orient_context": orient_ctx,
                "confirmed_outputs": confirmed_outputs,
            })
            out_path = self.state.step_output_path(finalize_step.name)
            out_path.write_text(output, encoding="utf-8")
            result.steps_completed[finalize_step.name] = out_path
            self._log(f"  └── finalize: done")

        # Git commit
        if self.config.git_commit_after_cycle:
            commit_hash = self.safe_git_commit(cycle_num, "adversarial review")
            result.git_commit_hash = commit_hash

        result.duration_seconds = time.monotonic() - t_start
        return result

    def _run_adversarial_step(
        self,
        cycle_num: int,
        confirmed_outputs: dict[str, str],
    ) -> None:
        """Execute the adversarial step (from config or by name lookup)."""
        step_name = self.config.adversarial_step or "adversarial"
        adv_step = self._find_step(step_name)
        if not adv_step:
            # Try finding a step template named step_adversarial.md
            template = self.config.resolved_prompts_dir / "step_adversarial.md"
            if template.exists():
                from langywrap.ralph.config import StepRole
                adv_step = StepConfig(
                    name="adversarial",
                    prompt_template=template,
                    role=StepRole.CRITIC,
                    timeout_minutes=45,
                )
            else:
                self._log("    No adversarial step configured — skipping")
                return

        orient_ctx = build_orient_context(self.state, max_recent_cycles=3)
        output, success = self.run_step(adv_step, {
            "cycle_num": cycle_num,
            "orient_context": orient_ctx,
            "confirmed_outputs": confirmed_outputs,
        })

        out_path = self.state.step_output_path("adversarial")
        out_path.write_text(output, encoding="utf-8")

        if re.search(r"BROKEN|FATAL", output, re.IGNORECASE):
            self._log("    ADVERSARIAL FOUND ISSUES — check adversarial.md")
        else:
            self._log("    Adversarial: claims survived review")

    def _should_trigger_adversarial_milestone(
        self,
        confirmed_outputs: dict[str, str],
    ) -> bool:
        """Check if any adversarial_milestone_patterns match execute output."""
        patterns = self.config.adversarial_milestone_patterns
        if not patterns:
            return False

        execute_output = confirmed_outputs.get("execute", "")
        if not execute_output:
            return False

        for pattern in patterns:
            if re.search(pattern, execute_output, re.IGNORECASE):
                return True
        return False

    def _find_step(self, name: str) -> StepConfig | None:
        """Find a step by name in config.steps."""
        for step in self.config.steps:
            if step.name == name:
                return step
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_depends_on(
        self,
        step: StepConfig,
        confirmed_outputs: dict[str, str],
    ) -> list[str]:
        """Return list of missing dependency tokens (empty = all met)."""
        missing: list[str] = []
        for token in step.depends_on:
            found = any(token in output for output in confirmed_outputs.values())
            if not found:
                missing.append(token)
        return missing

    @staticmethod
    def _check_token(output: str, token: str) -> bool:
        """Return True if token appears anywhere in output (or token is empty)."""
        if not token:
            return True
        return token in output

    def _scan_staged_for_secrets(self) -> Optional[str]:
        """Check staged file names against config.secret_patterns.

        Returns the first suspicious filename, or None if clean.
        """
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=self.config.project_dir,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            return None

        staged_files = result.stdout.strip().splitlines()
        patterns = [re.compile(p, re.IGNORECASE) for p in self.config.secret_patterns]

        for fname in staged_files:
            for pat in patterns:
                if pat.search(fname):
                    return fname
        return None

    def _extract_plan_summary(self) -> str:
        """Extract first non-empty line from plan.md as commit message summary."""
        plan = self.state.read_plan()
        for line in plan.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:72]
        return ""

    def _print_review(self, results: list[CycleResult]) -> None:
        """Print a summary of results so far."""
        total = len(results)
        confirmed = sum(1 for r in results if r.fully_confirmed)
        qg_pass = sum(1 for r in results if r.quality_gate_passed is True)
        committed = sum(1 for r in results if r.git_commit_hash)
        self._log(f"  Cycles completed:    {total}")
        self._log(f"  Fully confirmed:     {confirmed}/{total}")
        self._log(f"  Quality gate pass:   {qg_pass}/{total}")
        self._log(f"  Git commits:         {committed}")

    def _make_logger(self):
        """Return a logging function that respects config.verbose."""
        def _log(msg: str) -> None:
            if self.config.verbose:
                print(msg)
            log.info(msg)
        return _log
