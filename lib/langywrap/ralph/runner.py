"""
langywrap.ralph.runner — RalphLoop: the Python orchestrator for the ralph cycle.

Manages the orient → plan → execute → critic → finalize pipeline.
Actual AI calls go through ExecutionRouter; shell wrapping for execwrap stays bash.
"""

from __future__ import annotations

import logging
import os
import re
import select
import shlex
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langywrap.helpers.discovery import discovery_report, find_tool
from langywrap.integrations.openwolf import openwolf_status
from langywrap.ralph.config import QualityGateConfig, RalphConfig, StepConfig
from langywrap.ralph.context import (
    build_full_prompt,
    build_orient_context,
    check_graphify_health,
    detect_enrichment_channels,
)
from langywrap.ralph.state import CycleResult, RalphState
from langywrap.ralph.step_logger import StepLogger

try:
    from langywrap.router.backends import SubagentResult as _SubagentResult
except ImportError:
    _SubagentResult = None  # type: ignore[assignment,misc]

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ExecutionRouter import — graceful fallback so ralph is importable standalone
# ---------------------------------------------------------------------------

try:
    from langywrap.router import ExecutionRouter  # type: ignore[import]
    from langywrap.router.router import _infer_backend_from_model  # type: ignore[import]
except ImportError:
    ExecutionRouter = None  # type: ignore[assignment,misc]

    def _infer_backend_from_model(model: str) -> Any:  # type: ignore[no-redef]
        raise LookupError("router not available")


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
        router: ExecutionRouter | None = None,
    ) -> None:
        self.config = config
        self.router = router
        self.state = RalphState(
            config.resolved_state_dir,
            tasks_file=config.resolved_tasks_file,
            progress_file=config.resolved_progress_file,
        )
        self._step_logger = StepLogger(config.resolved_state_dir / "logs")
        self._log = self._step_logger.log

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        budget: int | None = None,
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
        consecutive_failures = 0

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

        self._verify_tool_discovery()
        self._warn_redundant_enrichment()
        self._verify_graphify_health()

        import os as _os

        from langywrap.ralph.prompt_audit import (
            audit_prompt_contracts,
            format_findings,
        )

        prompt_findings = audit_prompt_contracts(self.config)
        self._log(format_findings(prompt_findings))
        errors = [f for f in prompt_findings if f.severity == "error"]
        strict = _os.environ.get("RALPH_PROMPT_AUDIT_STRICT", "1") not in ("0", "")
        if errors and strict:
            raise RuntimeError(
                f"Prompt audit found {len(errors)} error(s) — refusing to start the "
                "loop. Re-run with `ralph run --dry-run` to inspect, then fix the "
                "prompts. Set RALPH_PROMPT_AUDIT_STRICT=0 to bypass (not recommended)."
            )

        for cycle_num in range(start_cycle, end_cycle + 1):
            pending = self.state.pending_count()
            if pending == 0:
                self._log(f"Cycle {cycle_num}: no pending tasks — loop complete.")
                break

            # Peak-hour throttle
            self._wait_if_peak_hours()

            self._log(f"\n{'=' * 60}")
            self._log(f"Cycle {cycle_num}/{end_cycle}  ({pending} pending tasks)")
            self._log(f"{'=' * 60}")

            # Hygiene injection
            if self.config.hygiene_every_n and cycle_num % self.config.hygiene_every_n == 0:
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
                            cycle_num,
                            marker=marker,
                            content=rendered,
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
                self._log(
                    "WARNING: stagnation detected — last 4 cycles identical outcome. "
                    "Consider diversifying tasks."
                )

            self._log(f"Cycle {cycle_num} done in {result.duration_seconds:.1f}s")
            self._log_cycle_stats(result)

            if self._is_failed_cycle(result):
                consecutive_failures += 1
                self._log(
                    "WARNING: cycle classified as FAILED "
                    f"({consecutive_failures}/"
                    f"{self.config.max_consecutive_failed_cycles} consecutive)"
                )
            else:
                consecutive_failures = 0

            if result.auth_failed:
                self._log(f"AUTH FAILURE — stopping loop. Snippet: {result.auth_failed_snippet!r}")
                break

            if result.rate_limited:
                self._log("Rate limit detected — stopping loop.")
                break

            if consecutive_failures >= self.config.max_consecutive_failed_cycles:
                self._log(
                    "Stopping loop: reached max consecutive failed cycles "
                    f"({self.config.max_consecutive_failed_cycles})."
                )
                break

        self._log(f"\nRalphLoop finished: {len(results)} cycles.")
        self._log_run_stats(results)
        self._step_logger.close()
        return results

    @staticmethod
    def _is_failed_cycle(result: CycleResult) -> bool:
        """Return True when a cycle should count toward failure streaks."""
        if result.quality_gate_passed is False:
            return True
        return not result.fully_confirmed

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
                self._log(f"  STEP: {step.name.upper()} — SKIPPED (fail-fast from prior step)")
                continue

            self._log(f"\n  ┌── STEP: {step.name.upper()} ──")
            self._log(f"  │   Timeout: {step.timeout_minutes}m")
            if step.model:
                self._log(f"  │   Model:   {step.model}")

            # Every-N check (e.g. review every 10th cycle)
            if step.every_n > 0 and cycle_num % step.every_n != 0:
                self._log(f"  └── {step.name}: SKIPPED (every {step.every_n} cycles)\n")
                continue

            # Check depends_on
            missing = self._check_depends_on(step, confirmed_outputs)
            if missing:
                self._log(f"  │   BLOCKED — missing tokens: {missing}")
                self._log(f"  └── {step.name}: SKIPPED (dependency not met)\n")
                result.confirmed_tokens[step.name] = False
                if step.fail_fast:
                    abort_remaining = True
                continue

            # Conditional step execution (run_if_step + run_if_pattern)
            if step.run_if_step and step.run_if_pattern:
                prior_output = confirmed_outputs.get(step.run_if_step, "")
                if not re.search(step.run_if_pattern, prior_output, re.IGNORECASE):
                    self._log(
                        f"  └── {step.name}: SKIPPED (condition not met: "
                        f"{step.run_if_step} !~ /{step.run_if_pattern}/)\n"
                    )
                    continue
                self._log(
                    f"  │   When: {step.run_if_step} =~ /{step.run_if_pattern}/ → MET"
                )

            # Cycle-type gating: skip step if cycle type doesn't match
            if step.run_if_cycle_types and cycle_type not in step.run_if_cycle_types:
                self._log(
                    f"  └── {step.name}: SKIPPED (cycle type '{cycle_type}' "
                    f"not in {step.run_if_cycle_types})\n"
                )
                continue

            # Mutual exclusion: if output_as slot already filled by a prior
            # variant, skip this step (e.g. execute.lean already wrote 'execute')
            output_key = step.output_as or step.name
            if output_key in result.steps_completed:
                self._log(f"  └── {step.name}: SKIPPED ('{output_key}' already produced)\n")
                continue

            cycle_ctx = {
                "cycle_num": cycle_num,
                "orient_context": orient_ctx,
                "confirmed_outputs": confirmed_outputs,
                "cycle_type": cycle_type,
                "cycle_prompt_extra": step.prompt_extra,
            }

            # Open per-step log + print Engine/Tools/Log/Monitor banner fields
            step_log = self._step_logger.open_step(
                step.name,
                model=step.model or "",
                engine=step.engine if step.engine != "auto" else "",
                tools=step.tools or "",
                timeout_minutes=step.timeout_minutes,
            )
            t_step_start = time.monotonic()
            self._step_logger.start_heartbeat(step.name, step_log)

            output, success, step_sr = self._run_step_with_retries(
                step,
                cycle_ctx,
                cycle_type=cycle_type,
            )

            step_duration = time.monotonic() - t_step_start
            self._step_logger.close_step(
                step.name,
                output,
                success=success,
                duration=step_duration,
            )

            # Accumulate token + file stats from this step.
            if step_sr is not None:
                result.input_tokens += step_sr.input_tokens
                result.output_tokens += step_sr.output_tokens
                model_key = step_sr.model_used or "unknown"
                prev_in, prev_out = result.tokens_by_model.get(model_key, (0, 0))
                result.tokens_by_model[model_key] = (
                    prev_in + step_sr.input_tokens,
                    prev_out + step_sr.output_tokens,
                )
                if step_sr.files_accessed:
                    result.files_accessed[output_key] = step_sr.files_accessed

            # Auth-failure detection: terminal, no retries, stops the whole
            # loop. OpenCode OAuth refresh 401 (or provider 401/403) will keep
            # failing on every subsequent step — retrying just burns cycles and
            # produces empty git commits. Surface the failure loudly so the
            # operator can re-auth and resume with --resume.
            if step_sr is not None and step_sr.auth_failed:
                snippet = step_sr.auth_failed_snippet or "<no snippet captured>"
                self._log(
                    f"  [{step.name}] AUTH FAILURE detected — stopping loop. "
                    f"No retries. Snippet: {snippet!r}"
                )
                self._log(
                    "  Re-authenticate the affected provider (e.g. "
                    "`opencode auth login`) then re-run with --resume."
                )
                # Persist output so the failing response is inspectable.
                # File path is keyed by ``step.name`` (per-step debug log) —
                # ``output_as`` is kept only as the logical key in
                # ``steps_completed`` / ``confirmed_outputs`` to drive
                # ``validates_plan`` and ``run_if_pattern`` lookups.
                out_path = self.state.step_output_path(step.name)
                out_path.write_text(output, encoding="utf-8")
                result.steps_completed[output_key] = out_path
                result.confirmed_tokens[output_key] = False
                result.auth_failed = True
                result.auth_failed_snippet = snippet
                # Skip post-cycle commands and the git commit on auth failure
                # so the loop doesn't churn out empty "progress" commits.
                result.duration_seconds = time.monotonic() - t_start
                return result

            # Rate-limit detection: the router is the single source of truth.
            # Do not rescan successful output here; that caused false positives
            # from ordinary JSON/tool output containing numbers like 429.
            if step_sr is not None and step_sr.rate_limited:
                snippet = step_sr.rate_limit_snippet or "<no snippet captured>"
                self._log(
                    f"  [{step.name}] Rate limited (detected in output: {snippet!r}) "
                    "— waiting 10m then retrying once..."
                )
                time.sleep(600)
                step_log2 = self._step_logger.open_step(
                    step.name,
                    model=step.model or "",
                    engine=step.engine if step.engine != "auto" else "",
                    tools=step.tools or "",
                    timeout_minutes=step.timeout_minutes,
                )
                t2 = time.monotonic()
                self._step_logger.start_heartbeat(step.name, step_log2)
                output, success, step_sr = self._run_step_with_retries(
                    step,
                    cycle_ctx,
                    cycle_type=cycle_type,
                )
                self._step_logger.close_step(
                    step.name,
                    output,
                    success=success,
                    duration=time.monotonic() - t2,
                )
                if step_sr is not None and step_sr.rate_limited:
                    snippet = step_sr.rate_limit_snippet or "<no snippet captured>"
                    self._log(f"  [{step.name}] Rate limited again — aborting cycle")
                    self._log(f"  [{step.name}] Matched snippet: {snippet!r}")
                    result.rate_limited = True
                    abort_remaining = True

            # Save output to steps/{step.name}.md (per-step debug log).
            # Two-tier file model:
            #   1. ``ralph/steps/<step.name>.md`` — runner-owned debug log of
            #      this step's text response. One file per step name, never
            #      collides with a sibling step variant.
            #   2. ``ralph/plan.md`` (and other state-dir files) — agent-owned
            #      canonical state. Written by the model via the Write tool
            #      when the prompt instructs it. The runner never touches
            #      these from the response stream.
            # ``output_as`` is now a logical key only (drives ``validates_plan``
            # gating and ``confirmed_outputs`` lookup); it does not name a
            # file path. Prompts must therefore not instruct the agent to
            # ``Write ralph/steps/<X>.md`` — those writes would be clobbered
            # by the runner's response-write here.
            out_path = self.state.step_output_path(step.name)
            out_path.write_text(output, encoding="utf-8")
            result.steps_completed[output_key] = out_path

            # Check confirmation token
            confirmed = success and self._check_token(output, step.confirmation_token)
            result.confirmed_tokens[output_key] = confirmed

            # Optional plan validation after the step that is expected to write plan.md.
            if step.validates_plan and self._plan_validation_enabled():
                plan_ok, plan_error = self._validate_plan(cycle_num)
                if not plan_ok:
                    self._log(f"  └── {step.name}: PLAN INVALID — {plan_error}")
                    retry_ctx = dict(cycle_ctx)
                    retry_ctx["plan_validation_error"] = plan_error
                    retry_ctx["retry_attempt"] = 1
                    self._log(f"  [{step.name}] Retrying once with validation feedback...")

                    step_log2 = self._step_logger.open_step(
                        step.name,
                        model=step.model or "",
                        engine=step.engine if step.engine != "auto" else "",
                        tools=step.tools or "",
                        timeout_minutes=step.timeout_minutes,
                    )
                    t2 = time.monotonic()
                    self._step_logger.start_heartbeat(step.name, step_log2)
                    output, success, step_sr = self._run_step_with_retries(
                        step,
                        retry_ctx,
                        cycle_type=cycle_type,
                    )
                    self._step_logger.close_step(
                        step.name,
                        output,
                        success=success,
                        duration=time.monotonic() - t2,
                    )

                    out_path.write_text(output, encoding="utf-8")
                    result.steps_completed[output_key] = out_path
                    confirmed = success and self._check_token(output, step.confirmation_token)
                    result.confirmed_tokens[output_key] = confirmed

                    plan_ok, plan_error = self._validate_plan(cycle_num)
                    if not plan_ok:
                        self._log(f"  └── {step.name}: PLAN INVALID after retry — {plan_error}\n")
                        result.confirmed_tokens[output_key] = False
                        abort_remaining = True
                        continue

            if confirmed:
                confirmed_outputs[output_key] = output
                self._log(f"  └── {step.name}: CONFIRMED ({step.confirmation_token})\n")
            else:
                confirmed_outputs[output_key] = output  # always store for run_if checks
                if step.confirmation_token:
                    self._log(f"  └── {step.name}: token '{step.confirmation_token}' NOT FOUND\n")
                else:
                    self._log(f"  └── {step.name}: done (no token check)\n")

            # Fail-fast check
            if step.fail_fast and not success:
                self._log(f"  └── {step.name}: FAIL-FAST — aborting remaining steps\n")
                abort_remaining = True

            # Detect cycle type after the configured source step (default 'plan').
            # Setting cycle_type_source='orient' lets orient drive plan branching.
            if step.name == self.config.cycle_type_source and success:
                cycle_type = self._detect_cycle_type(output)
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

        # Post-cycle commands (e.g. textify / graphify --update).
        # Run BEFORE commit so refreshed indices are staged together.
        self._run_post_cycle_commands(cycle_num)

        # Git commit
        if self.config.git_commit_after_cycle:
            commit_summary = self._extract_commit_summary(cycle_num)
            commit_hash = self.safe_git_commit(cycle_num, commit_summary)
            result.git_commit_hash = commit_hash

        result.duration_seconds = time.monotonic() - t_start
        return result

    def run_step(
        self,
        step: StepConfig,
        cycle_context: dict,
    ) -> tuple[str, bool, _SubagentResult | None]:
        """Build prompt, call router/engine, return (output_text, success, result).

        Includes hang detection: if the call times out with tiny output (<2KB),
        retries up to config.max_hang_retries times before giving up.

        Falls back to a stub if no router is available (useful for testing).
        """
        if step.builtin:
            output = self._run_builtin_step(step, cycle_context)
            self._log(
                f"  │   Builtin: {step.builtin} — produced {len(output):,} chars without LLM"
            )
            return output, True, None

        prompt = self.build_prompt(step, cycle_context)
        self._log(f"  │   Prompt:  {len(prompt):,} chars")

        if self.router is None:
            import logging

            logging.getLogger("langywrap.ralph").warning(
                "No router configured — running in stub mode. "
                "Configure .langywrap/router.yaml to enable AI execution."
            )
            self._log(
                f"    [STUB] No router — would run {step.name} with {len(prompt)} char prompt"
            )
            return f"# {step.name} STUB\n{step.confirmation_token} stub=true\n", True, None

        max_attempts = self.config.max_hang_retries + 1
        for attempt in range(1, max_attempts + 1):
            try:
                result = self.router.execute(
                    prompt=prompt,
                    model=step.model,
                    engine=step.engine,
                    timeout_minutes=step.timeout_minutes,
                    tools=step.tools,
                    retry_models=list(step.retry_models),
                    abort_on_hang=step.fail_fast,
                    tag=step.name,
                )
                return result.text, result.ok, result
            except TimeoutError as exc:
                # Hang detection: timeout with tiny output → retry
                output_size = len(str(exc))
                if attempt < max_attempts and output_size < 2000:
                    self._log(
                        f"    [{step.name}] API hang (timeout, {output_size}B). "
                        f"Retry {attempt}/{self.config.max_hang_retries}..."
                    )
                    time.sleep(15)
                    continue
                self._log(f"    [{step.name}] Timeout after {attempt} attempt(s): {exc}")
                return f"# {step.name} TIMEOUT\n{exc}\n", False, None
            except Exception as exc:
                self._log(f"    ERROR in {step.name}: {exc}")
                return f"# {step.name} ERROR\n{exc}\n", False, None

        return f"# {step.name} FAILED after {max_attempts} attempts\n", False, None

    def _run_builtin_step(self, step: StepConfig, cycle_context: dict) -> str:
        """Run a native non-LLM step implementation."""
        if step.builtin == "orient":
            from langywrap.ralph.taskdb import TaskDB

            db = TaskDB(self.config.project_dir, self.config.resolved_state_dir)
            return db.render_orient(confirmation_token=step.confirmation_token)
        if step.builtin == "inline_orient":
            return self._run_inline_orient(step, cycle_context)
        raise ValueError(f"Unknown builtin step: {step.builtin}")

    def _run_inline_orient(self, step: StepConfig, cycle_context: dict) -> str:
        """Inline (no-LLM) orient: lint preflight + coverage budget + task pick.

        Reads ``tasks.md`` and ``progress.md`` from the configured state dir,
        runs the linter in autofix mode (writing back to ``tasks.md`` if fixes
        applied), evaluates coverage budgets against the progress history,
        filters pending tasks to the union of violated types, and returns a
        deterministic ``orient.md`` payload naming the selected task.

        Raises ``ValueError`` on lint hard-fail or empty eligible set — the
        step framework treats this as a step failure.
        """
        from langywrap.ralph.coverage_budget import (
            CoverageBudget,
            evaluate_coverage,
            filter_eligible_tasks,
        )
        from langywrap.ralph.lint_tasks import LintConfig
        from langywrap.ralph.lint_tasks import autofix as lint_autofix
        from langywrap.ralph.markdown_todo import parse_unified_tasks

        state_dir = self.config.resolved_state_dir
        tasks_file = state_dir / "tasks.md"
        progress_file = state_dir / "progress.md"

        if not tasks_file.exists():
            raise ValueError(f"inline_orient: tasks file not found at {tasks_file}")
        tasks_text = tasks_file.read_text(encoding="utf-8")
        progress_text = progress_file.read_text(encoding="utf-8") if progress_file.exists() else ""

        # ── Preflight lint (autofix) ──────────────────────────────────────────
        lint_summary = "lint: skipped (preflight_lint disabled)"
        if step.preflight_lint:
            lint_config = LintConfig(
                allowed_task_types=tuple(step.allowed_task_types),
                allowed_priorities=(
                    tuple(step.allowed_priorities)
                    if step.allowed_priorities
                    else ("P0", "P1", "P2", "P3")
                ),
                max_active=step.max_active,
                allow_legacy_format=step.allow_legacy_format,
            )
            lint_report = lint_autofix(tasks_text, lint_config)
            if lint_report.fixed_text is not None and lint_report.fixed_text != tasks_text:
                tasks_file.write_text(lint_report.fixed_text, encoding="utf-8")
                tasks_text = lint_report.fixed_text
            if not lint_report.is_clean:
                raise ValueError(
                    "inline_orient: preflight lint hard-failed:\n"
                    + lint_report.render()
                )
            lint_summary = (
                f"lint: clean ({len(lint_report.autofixed)} autofix"
                + ("es" if len(lint_report.autofixed) != 1 else "")
                + " applied)"
            )

        # ── Coverage report ───────────────────────────────────────────────────
        budgets = [CoverageBudget(**b) for b in step.coverage_budgets]
        coverage = evaluate_coverage(progress_text, budgets)

        # ── Pick task ─────────────────────────────────────────────────────────
        parsed = parse_unified_tasks(tasks_text)
        pending = [t for t in parsed if t.is_open]
        eligible = filter_eligible_tasks(pending, coverage)
        # Stable order: priority (P0 first), then file order.
        eligible_sorted = sorted(eligible, key=lambda t: (t.priority, t.line_no))
        selected = eligible_sorted[0] if eligible_sorted else None

        if selected is None and pending and coverage.has_violations:
            # Budget violation with no eligible task — surface the deficit.
            raise ValueError(
                "inline_orient: coverage budgets violated but no pending task "
                f"of types {sorted(coverage.violated_types())} exists. "
                "Operator must add at least one such task (or relax the budget)."
            )
        if selected is None:
            raise ValueError("inline_orient: no pending task available to pick.")

        # ── Render output ─────────────────────────────────────────────────────
        # The literal ``TASK_TYPE: <type>`` line is the structured-output
        # contract that downstream consumers depend on:
        #   1. ``detects_cycle=Match(scan=r"TASK_TYPE:\\s*scan", ...)`` in
        #      per-repo ralph.py configs gates plan/execute branching on it.
        #   2. ``coverage_budget.evaluate_coverage`` reads ``TASK_TYPE:`` rows
        #      from progress.md (FINALIZE copies the orient label across) to
        #      decide which task types are under their floor.
        # Without this line every plan/execute step that has ``when_cycle=[…]``
        # is SKIPPED and the anti-mode-collapse engine stays dormant.
        # See: solutions/2026-05-12_inline_orient_missing_task_type_token.md
        cycle_num = cycle_context.get("cycle_num", 0)
        lines = [
            f"# Orient — Cycle {cycle_num}",
            "",
            f"TASK_TYPE: {selected.task_type}",
            "",
            "## Selected Task",
            f"- **[{selected.priority}] task:{selected.slug}** "
            f"[{selected.task_type}] {selected.label}",
            "",
            coverage.render_summary(),
            "",
            "## Picker Trace",
            f"- Pending tasks: {len(pending)}",
            f"- Eligible after coverage filter: {len(eligible)}",
            f"- Selected: `task:{selected.slug}` "
            f"(priority {selected.priority}, type {selected.task_type})",
            "",
            "## Linter",
            lint_summary,
            "",
        ]
        if step.confirmation_token:
            lines.append(step.confirmation_token)
            lines.append("")
        return "\n".join(lines)

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

        plan_validation_error: str = context.get("plan_validation_error", "")
        if plan_validation_error:
            template = template + (
                "\n\n---\n\n## Plan Validation Feedback\n\n"
                "The previous `research/plan.md` output did not satisfy the orchestrator "
                "contract. Rewrite the plan so it passes validation exactly.\n\n"
                f"Validation error: {plan_validation_error}\n"
            )

        wants_orient_ctx = step.includes_orient_context

        return build_full_prompt(
            template=template,
            project_dir=self.config.project_dir,
            state_dir=self.config.resolved_state_dir,
            cycle_num=cycle_num,
            orient_context=orient_context if wants_orient_ctx else "",
            scope_restriction=self.config.scope_restriction,
            is_orient_step=wants_orient_ctx,
            enrichments=step.enrich,
        )

    # ------------------------------------------------------------------
    # Quality gate
    # ------------------------------------------------------------------

    def quality_gate(self) -> bool:
        """Run the primary configured quality gate command. Returns True on pass."""
        if not self.config.quality_gate:
            return True
        return self._run_quality_gate(self.config.quality_gate)

    def _run_quality_gate(self, qg: QualityGateConfig) -> bool:
        """Run a single quality gate. Returns True on pass."""

        cwd = Path(qg.working_dir) if qg.working_dir else self.config.project_dir
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

    def safe_git_commit(self, cycle_num: int, plan_summary: str = "") -> str | None:
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
                    stderr = (
                        exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                    )
                    if "ignored by one of your .gitignore files" in stderr:
                        self._log(f"    git add {path} skipped (ignored by gitignore)")
                    else:
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
            if self.config.git_push_after_commit:
                self.safe_git_push()
            return commit_hash
        except subprocess.CalledProcessError:
            return None

    def safe_git_push(self) -> None:
        """Push committed changes, swallowing failures as advisory warnings."""
        project_dir = self.config.project_dir
        try:
            result = subprocess.run(
                ["git", "push"],
                cwd=project_dir,
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            self._log(f"    git push skipped: {exc}")
            return

        if result.returncode == 0:
            self._log("    Pushed commit to remote.")
            return

        stderr = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        self._log(f"    git push failed (ignored): {stderr}")

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
        """Validate setup without running a Ralph cycle.

        Returns a dict with validation results. Also prints the same
        enrichment-channel + graphify-health preflight as ``run()`` so
        operators catch missing CLIs before a full cycle. When a router is
        configured, this also performs lightweight model connectivity pings so
        missing provider config/API keys are caught before the loop starts.
        """
        tool_report = self._verify_tool_discovery()
        self._warn_redundant_enrichment()
        self._verify_graphify_health()

        from langywrap.ralph.prompt_audit import (
            audit_prompt_contracts,
            format_findings,
        )

        prompt_findings = audit_prompt_contracts(self.config)
        self._log(format_findings(prompt_findings))

        report: dict = {
            "project_dir": str(self.config.project_dir),
            "state_dir": str(self.config.resolved_state_dir),
            "prompts_dir": str(self.config.resolved_prompts_dir),
            "steps": [],
            "model_mix": {},
            "state_files": {},
            "router": None,
            "quality_gate": None,
            "tool_discovery": tool_report,
            "prompt_contracts": [f.as_dict() for f in prompt_findings],
        }
        from langywrap.ralph.model_mix import config_model_mix

        report["model_mix"] = config_model_mix(self.config)

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
                "builtin": step.builtin,
                "template": str(step.prompt_template),
                "template_exists": step.prompt_template.exists(),
                "template_size": (
                    step.prompt_template.stat().st_size if step.prompt_template.exists() else 0
                ),
                "timeout_minutes": step.timeout_minutes,
                "confirmation_token": step.confirmation_token,
            }
            if step.builtin:
                try:
                    preview = self._run_builtin_step(step, {"cycle_num": 0})
                    entry["builtin_preview"] = preview[:4000]
                    entry["builtin_preview_chars"] = len(preview)
                except Exception as exc:
                    entry["builtin_error"] = str(exc)
            report["steps"].append(entry)

        # Router + backends
        if self.router is not None:
            from langywrap.router.router import (
                _infer_backend_from_model,
                _resolve_engine_backend,
            )

            router_info: dict = {
                "type": type(self.router).__name__,
                "backends": {},
                "routing": [],
                "connectivity": [],
            }
            for backend_enum, backend_cfg in self.router._backends.items():
                router_info["backends"][backend_enum.value] = {
                    "binary": backend_cfg.binary_path,
                    "execwrap": backend_cfg.execwrap_path,
                    "rtk": backend_cfg.rtk_path,
                }
            # Show how each step would dispatch (resolved from Step fields alone).
            for step in self.config.steps:
                if step.builtin:
                    entry = {
                        "step": step.name,
                        "backend": "builtin",
                        "builtin": step.builtin,
                        "timeout_minutes": step.timeout_minutes,
                    }
                    if step.output_as:
                        entry["output_as"] = step.output_as
                    router_info["routing"].append(entry)
                    continue
                effective_model = step.model
                effective_backend_enum = _resolve_engine_backend(
                    step.engine
                ) or _infer_backend_from_model(effective_model)
                entry: dict[str, Any] = {
                    "step": step.name,
                    "model": effective_model,
                    "backend": effective_backend_enum.value,
                    "timeout_minutes": step.timeout_minutes,
                    "retry_models": list(step.retry_models),
                }
                if step.run_if_cycle_types:
                    entry["when_cycle"] = step.run_if_cycle_types
                if step.output_as:
                    entry["output_as"] = step.output_as
                router_info["routing"].append(entry)
            targets = [
                (step.model, step.engine, step.timeout_minutes * 60)
                for step in self.config.steps
                if not step.builtin
            ]
            router_info["connectivity"] = [
                {
                    "model": result.model,
                    "backend": result.backend,
                    "reachable": result.reachable,
                    "reason": result.reason,
                    "detail": result.detail,
                }
                for result in self.router.dry_run_detailed(targets)
            ]
            report["router"] = router_info
            report["mock_backend_probe"] = self._run_mock_backend_probe()
        else:
            report["router"] = "None (stub mode)"
            report["mock_backend_probe"] = self._run_mock_backend_probe()

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

    def _run_mock_backend_probe(self) -> dict[str, Any]:
        """Exercise backend wrapper plumbing without calling an external LLM."""
        from langywrap.helpers.discovery import find_execwrap, find_rtk, find_tool
        from langywrap.router.backends import Backend, BackendConfig, MockBackend, wrap_cmd

        execwrap_path = find_execwrap(self.config.project_dir)
        rtk_path = find_rtk(self.config.project_dir)
        mock_command = (
            "printf 'LANGYWRAP_OPENWOLF=%s\\n' \"${LANGYWRAP_OPENWOLF:-}\"; "
            "printf 'PWD=%s\\n' \"$PWD\"; "
            "printf 'SHELL=%s\\n' \"${SHELL:-}\"; "
            "printf 'BASH_ENV=%s\\n' \"${BASH_ENV:-}\"; "
            "printf 'EXECWRAP_PROJECT_DIR=%s\\n' \"${EXECWRAP_PROJECT_DIR:-}\"; "
            "command -v textify >/dev/null && printf 'TEXTIFY_ON_PATH=1\\n' || "
            "printf 'TEXTIFY_ON_PATH=0\\n'; "
            "command -v graphify >/dev/null && printf 'GRAPHIFY_ON_PATH=1\\n' || "
            "printf 'GRAPHIFY_ON_PATH=0\\n'; "
            "command -v openwolf >/dev/null && printf 'OPENWOLF_ON_PATH=1\\n' || "
            "printf 'OPENWOLF_ON_PATH=0\\n'"
        )
        env_overrides = {
            "LANGYWRAP_OPENWOLF": "1",
            "EXECWRAP_PROJECT_DIR": str(self.config.project_dir),
            # The mock probe intentionally runs many tiny shell builtins. Let
            # execwrap launcher mode set SHELL/BASH_ENV, but skip the nested
            # DEBUG trap or each printf/command-v pays full security preflight
            # cost and can exceed the 10s dry-run budget.
            "__EXECWRAP_ACTIVE": "1",
            "MOCK_COMMAND": mock_command,
        }
        discovered_dirs: list[str] = []
        for tool in ("textify", "graphify", "openwolf", "rtk"):
            path = find_tool(tool, self.config.project_dir)
            if path:
                discovered_dirs.append(str(Path(path).parent))
        if discovered_dirs:
            import os

            env_overrides["PATH"] = (
                os.pathsep.join(dict.fromkeys(discovered_dirs))
                + os.pathsep
                + os.environ.get("PATH", "")
            )

        cfg = BackendConfig(
            type=Backend.MOCK,
            execwrap_path=execwrap_path,
            rtk_path=rtk_path,
            env_overrides=env_overrides,
            timeout_seconds=10,
            cwd=str(self.config.project_dir),
        )
        expected_cmd = wrap_cmd(["bash", "-c", mock_command], execwrap_path, rtk_path)
        result = MockBackend(cfg).run("", "mock-preflight", timeout=10)
        text = result.text or ""
        rtk_probe_text = ""
        if execwrap_path and rtk_path:
            probe_env = os.environ.copy()
            probe_env.update(env_overrides)
            try:
                rtk_probe = subprocess.run(
                    [execwrap_path, "-c", "ls -l >/dev/null"],
                    cwd=self.config.project_dir,
                    env=probe_env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                rtk_probe_text = (rtk_probe.stdout or "") + (rtk_probe.stderr or "")
            except subprocess.TimeoutExpired as exc:
                rtk_probe_text = f"rtk probe timed out after {exc.timeout}s"
        probe_issues: list[str] = []
        probe_hints: list[str] = []
        execwrap_project_ok = f"EXECWRAP_PROJECT_DIR={self.config.project_dir}" in text
        rtk_outer_applied = bool(rtk_path and expected_cmd[:1] == [rtk_path])
        rtk_internal_applied = "RTK rewrite:" in rtk_probe_text
        rtk_wired = bool(rtk_path and (rtk_outer_applied or rtk_internal_applied))
        if execwrap_path and not execwrap_project_ok:
            probe_issues.append(
                "execwrap is applied, but EXECWRAP_PROJECT_DIR is not the target project"
            )
            probe_hints.append(
                "Run `../langywrap/scripts/couple.sh . --defaults` to install a "
                "project-local .exec/execwrap.bash, or set LANGYWRAP_EXECWRAP_PATH "
                "to a project-local wrapper."
            )
        if rtk_path and execwrap_path and not rtk_wired:
            probe_issues.append(
                "RTK is discovered, but execwrap did not show an internal RTK rewrite"
            )
            probe_hints.append(
                "Ensure execwrap can resolve RTK internally and that the resolved RTK "
                "directory is on PATH before rewritten commands execute."
            )
        probe = {
            "ran": True,
            "ok": result.ok,
            "exit_code": result.exit_code,
            "execwrap_path": execwrap_path,
            "rtk_path": rtk_path,
            "wrapped_command": expected_cmd,
            "execwrap_applied": bool(execwrap_path and expected_cmd[:1] == [execwrap_path]),
            "rtk_outer_applied": rtk_outer_applied,
            "rtk_internal_applied": rtk_internal_applied,
            "rtk_wired": rtk_wired,
            "openwolf_env": "LANGYWRAP_OPENWOLF=1" in text,
            "textify_on_path": "TEXTIFY_ON_PATH=1" in text,
            "graphify_on_path": "GRAPHIFY_ON_PATH=1" in text,
            "openwolf_on_path": "OPENWOLF_ON_PATH=1" in text,
            "cwd_is_project": f"PWD={self.config.project_dir}" in text,
            "execwrap_project_dir_is_project": execwrap_project_ok,
            "issues": probe_issues,
            "hints": probe_hints,
            "rtk_probe_output": rtk_probe_text[-2000:],
            "output": text[-2000:],
            "error": result.error,
        }
        self._log("  [mock backend probe]")
        self._log(
            "    "
            f"ok={probe['ok']} execwrap={probe['execwrap_applied']} "
            f"rtk_outer={probe['rtk_outer_applied']} "
            f"rtk_wired={probe['rtk_wired']} "
            f"openwolf_env={probe['openwolf_env']} "
            f"textify_path={probe['textify_on_path']} "
            f"graphify_path={probe['graphify_on_path']} "
            f"execwrap_project={probe['execwrap_project_dir_is_project']}"
        )
        if not result.ok:
            self._log(f"    error: {result.error}")
        for msg in probe_issues:
            self._log(f"    - {msg}")
        for hint in probe_hints:
            self._log(f"      fix: {hint}")
        return probe

    # ------------------------------------------------------------------
    # Step retry loop
    # ------------------------------------------------------------------

    def _run_step_with_retries(
        self,
        step: StepConfig,
        cycle_context: dict,
        cycle_type: str = "",
    ) -> tuple[str, bool, _SubagentResult | None]:
        """Run a step, then optionally retry if retry_count > 0.

        If retry_gate_command is set, run it after each attempt. If it exits 0,
        stop retrying (success). If non-zero, inject error output and retry.

        If retry_if_cycle_types is set, retries only run when cycle_type matches.
        """
        # Pre-gate: when gate_mode="before", run the gate first and skip the
        # LLM entirely if it already passes (e.g. fix/lint steps that are no-ops).
        if (
            step.retry_count > 0
            and step.retry_gate_command
            and step.retry_gate_mode == "before"
        ):
            pre_pass, _ = self._run_gate_command(step.retry_gate_command)
            if pre_pass:
                self._log(f"    [{step.name}] Gate already passing — LLM skipped")
                return "(gate passed pre-check — step skipped)", True, None

        output, success, sr = self.run_step(step, cycle_context)

        if step.retry_count <= 0 or not step.retry_gate_command:
            return output, success, sr

        if not success:
            self._log(
                f"    [{step.name}] Step execution failed before retry gate;"
                " preserving failure state"
            )
            return output, False, sr

        # Check if retries are conditional on cycle type
        if step.retry_if_cycle_types and cycle_type not in step.retry_if_cycle_types:
            self._log(
                f"    [{step.name}] Retry skipped (cycle type '{cycle_type}' "
                f"not in {step.retry_if_cycle_types})"
            )
            return output, success, sr

        for attempt in range(1, step.retry_count + 1):
            # Run gate command to check if retry is needed
            gate_pass, gate_output = self._run_gate_command(step.retry_gate_command)
            if gate_pass:
                self._log(f"    [{step.name}] Gate passed after {attempt - 1} retries")
                return output, success, sr

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

            output, success, sr = self.run_step(retry_step, retry_ctx)

        # Final gate check after last retry
        gate_pass, _ = self._run_gate_command(step.retry_gate_command)
        if gate_pass:
            self._log(f"    [{step.name}] Gate passed after {step.retry_count} retries")
            return output, success, sr

        self._log(f"    [{step.name}] Gate still failing after {step.retry_count} retries")
        return output, success, sr

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

    def _run_post_cycle_commands(self, cycle_num: int) -> None:
        """Run ``post_cycle_commands`` sequentially before commit.

        Each command is advisory: timeouts and non-zero exits are logged and
        the next command continues. The goal is that a broken graph rebuild
        never breaks the ralph cycle itself. Output is truncated in logs so
        verbose indexers (graphify, textify) don't swamp cycle reports.
        """
        commands = self.config.post_cycle_commands
        if not commands:
            return
        import subprocess

        timeout = max(5, int(self.config.post_cycle_command_timeout))
        self._log(f"\n  Post-cycle commands ({len(commands)}):")
        for cmd in commands:
            cmd = self._resolve_post_cycle_command(cmd)
            label = cmd if len(cmd) <= 80 else cmd[:77] + "..."
            self._log(f"    $ {label}")
            try:
                env = os.environ.copy()
                discovered_dirs = []
                for tool in ("graphify", "textify", "openwolf", "rtk"):
                    path = find_tool(tool, self.config.project_dir)
                    if path:
                        discovered_dirs.append(str(Path(path).parent))
                if discovered_dirs:
                    prefix = os.pathsep.join(dict.fromkeys(discovered_dirs))
                    env["PATH"] = prefix + os.pathsep + env.get("PATH", "")
                cp = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=self.config.project_dir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                self._log(f"    [warn] timed out after {timeout}s — skipped")
                continue
            except OSError as e:
                self._log(f"    [warn] {e} — skipped")
                continue
            if cp.returncode != 0:
                err = (cp.stderr or cp.stdout or "").strip().splitlines()
                tail = err[-1] if err else f"exit {cp.returncode}"
                self._log(f"    [warn] exit {cp.returncode}: {tail[:200]}")
            else:
                self._log("    ok")

    def _resolve_post_cycle_command(self, cmd: str) -> str:
        """Rewrite stale graphify/textify executable paths to discovered fallbacks."""
        try:
            parts = shlex.split(cmd)
        except ValueError:
            return cmd
        if not parts:
            return cmd
        exe = parts[0]
        name = Path(exe).name
        if name not in {"graphify", "textify", "openwolf", "rtk"}:
            return cmd
        exe_path = Path(exe)
        if not exe_path.is_absolute():
            exe_path = self.config.project_dir / exe_path
        if "/" not in exe or exe_path.exists():
            return cmd
        replacement = find_tool(name, self.config.project_dir)
        if replacement is None:
            return cmd
        parts[0] = replacement
        return shlex.join(parts)

    def _verify_tool_discovery(self) -> dict[str, Any]:
        """Log project/local/langywrap fallback discovery before dry-run/run."""
        report = discovery_report(self.config.project_dir)
        report["openwolf"] = openwolf_status(self.config.project_dir)
        self._log("  [tool preflight]")
        tools: dict[str, str | None] = report.get("tools", {})  # type: ignore[assignment]
        for name in ("execwrap", "rtk", "textify", "graphify", "openwolf"):
            path = tools.get(name)
            if path:
                self._log(f"    {name}: {path}")
            else:
                self._log(f"    {name}: not found")
        issues = report.get("issues") or []
        hints = report.get("hints") or {}
        if issues:
            self._log(f"    {len(issues)} issue(s):")
            for msg in issues:
                self._log(f"      - {msg}")
        if isinstance(hints, dict) and hints:
            self._log("    install/fix helpers:")
            for name, hint in hints.items():
                self._log(f"      - {name}: {hint}")
        ow = report.get("openwolf", {})
        if isinstance(ow, dict):
            ow_issues = ow.get("issues") or []
            self._log(
                "    openwolf wiring: "
                f"wolf_dir={bool(ow.get('wolf_dir'))} "
                f"claude_hooks={bool(ow.get('claude_hooks'))} "
                f"opencode_plugin={bool(ow.get('opencode_plugin'))}"
            )
            for msg in ow_issues:
                self._log(f"      - {msg}")
            ow_hints = ow.get("hints") or []
            if ow_hints:
                self._log("      OpenWolf helpers:")
                for hint in ow_hints:
                    self._log(f"        - {hint}")
        return report

    def _verify_graphify_health(self) -> None:
        """Preflight check for Graphify/Textify usage. Advisory only.

        Graphify and Textify ship as vendored submodules of langywrap and are
        installed by ``./just install`` (editable). The runner never mutates
        the Python environment at loop start — if a binary is missing, it
        points the operator at the install command and proceeds.

        Warnings reported:
          - enrich=['graphify'] set but graphify not on PATH
          - post_cycle_commands references graphify/textify but CLI missing
          - enrich=['graphify'] set but no post-cycle rebuild → stale graph
        """
        report = check_graphify_health(
            self.config.project_dir,
            [list(s.enrich) for s in self.config.steps],
            list(self.config.post_cycle_commands),
        )
        issues = report.get("issues") or []
        if issues:
            self._log(f"  [graphify preflight] {len(issues)} issue(s):")
            for msg in issues:
                self._log(f"    - {msg}")

    def _warn_redundant_enrichment(self) -> None:
        """Warn once at loop start if the same enrichment is wired via ≥2 channels.

        Graphify can feed the model via prompt injection, MCP tool calls, and
        PreToolUse hooks. Enabling more than one doubles/triples token cost for
        no added signal. This check is advisory — it never aborts the loop.
        """
        flags = detect_enrichment_channels(
            self.config.project_dir,
            [list(s.enrich) for s in self.config.steps],
        )
        active = [k for k, v in flags.items() if v]
        if len(active) >= 2:
            self._log(
                f"  [warn] Graphify active on {len(active)} channels ({', '.join(active)}). "
                "Pick ONE of: step.enrich=['graphify'] / .langywrap/mcp.json / "
                "PreToolUse hook — multiple paths duplicate context."
            )

    def _wait_if_peak_hours(self) -> None:
        """Block until off-peak if throttle is configured."""
        start = self.config.throttle_utc_start
        end = self.config.throttle_utc_end
        if start is None or end is None:
            return

        if self._should_skip_throttle():
            return

        while True:
            now = datetime.now(UTC)
            hour = now.hour

            if self.config.throttle_weekdays_only and now.weekday() >= 5:
                return  # weekend

            if start <= hour < end:
                minutes_left = (end - hour) * 60 - now.minute
                self._log(
                    f"  [PEAK HOURS] {now:%H:%M} UTC — pausing. Off-peak in ~{minutes_left}m. "
                    "Press ENTER to resume now."
                )
                if self._wait_or_enter(60):
                    self._log("  [PEAK HOURS] ENTER pressed — resuming immediately.")
                    return
            else:
                return

    @staticmethod
    def _wait_or_enter(seconds: float) -> bool:
        """Sleep up to ``seconds``, returning True if ENTER was pressed on stdin.

        Falls back to plain ``time.sleep`` when stdin is not an interactive TTY
        (e.g. under nohup, systemd, cron) so background runs behave unchanged.
        """
        try:
            if not sys.stdin.isatty():
                time.sleep(seconds)
                return False
            ready, _, _ = select.select([sys.stdin], [], [], seconds)
            if ready:
                sys.stdin.readline()
                return True
            return False
        except (OSError, ValueError):
            time.sleep(seconds)
            return False

    def _should_skip_throttle(self) -> bool:
        """Return True when the configured primary backend should bypass throttle."""
        skip_backends = {b.lower() for b in self.config.throttle_skip_backends}
        if not skip_backends:
            return False

        backend = self._primary_backend_name()
        return backend.lower() in skip_backends if backend else False

    def _primary_backend_name(self) -> str:
        """Infer the primary execution backend for this pipeline.

        Peak-hour throttling is checked before each cycle. Projects mark one
        step with ``primary=True``; if none is marked, throttling finds no
        backend to compare against and simply does not skip.
        """
        for step in self.config.steps:
            if not step.pipeline or not step.primary:
                continue
            if step.engine and step.engine != "auto":
                return step.engine
            if step.model:
                return _infer_backend_from_model(step.model).value
            break

        return ""

    def _plan_validation_enabled(self) -> bool:
        return bool(
            self.config.plan_must_contain
            or self.config.plan_must_match
            or self.config.plan_require_current_cycle
        )

    def _validate_plan(self, cycle_num: int) -> tuple[bool, str]:
        """Validate plan.md using repo-configured content requirements."""
        plan = self.state.read_plan()
        if not plan.strip():
            return False, "plan.md missing or empty"

        for required in self.config.plan_must_contain:
            if required not in plan:
                return False, f"missing required text: {required!r}"

        for pattern in self.config.plan_must_match:
            if not re.search(pattern, plan, re.IGNORECASE | re.MULTILINE):
                return False, f"missing required pattern: {pattern!r}"

        if self.config.plan_require_current_cycle:
            cycle_pattern = rf"\bcycle\s+{cycle_num}\b"
            if not re.search(cycle_pattern, plan, re.IGNORECASE):
                return False, f"plan does not mention cycle {cycle_num}"

        return True, ""

    # ------------------------------------------------------------------
    # Cycle type detection
    # ------------------------------------------------------------------

    def _detect_cycle_type(self, source_output: str = "") -> str:
        """Classify the current cycle by matching the source step's output
        against cycle_type_rules.

        ``source_output`` is the freshly produced text from the source step
        (orient or plan); falling back to reading plan.md preserves the
        legacy behaviour for callers that don't pass it.

        Returns the cycle type name, or empty string if no rule matches.

        Uses last-match-wins semantics: when multiple rules match, the rule
        defined later in the config takes priority. Place more specific /
        narrower rules after broader ones in ``cycle_types``.
        """
        rules = self.config.cycle_type_rules
        if not rules:
            return ""

        text = source_output or self.state.read_plan()
        if not text:
            return ""

        decision_rules = [r for r in rules if r.get("field")]
        if decision_rules:
            rule = decision_rules[-1]
            field = rule.get("field", "execute_type")
            default = rule.get("default", "execute") or "execute"
            allowed = {
                item.strip().lower()
                for item in rule.get("allowed", "execute|lean|research").split("|")
                if item.strip()
            }
            decision = self._extract_plan_decision_field(text, field).lower()
            if decision in {"mixed", "undecided", "unknown", "default", ""}:
                return default
            if decision in allowed:
                return decision
            self._log(
                f"  Planner decision {field}={decision!r} is invalid; "
                f"using default cycle type {default!r}"
            )
            return default

        best = ""
        for rule in rules:
            pattern = rule.get("pattern", "")
            if pattern and re.search(pattern, text, re.IGNORECASE):
                best = rule.get("name", "")

        return best

    @staticmethod
    def _extract_plan_decision_field(text: str, field: str) -> str:
        """Read a simple YAML-ish planner decision field from plan output."""
        field_re = re.escape(field)
        patterns = [
            rf"(?im)^\s*{field_re}\s*:\s*['\"]?([A-Za-z0-9_-]+)['\"]?\s*$",
            rf"(?im)^\s*{field_re}\s*=\s*['\"]?([A-Za-z0-9_-]+)['\"]?\s*$",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return ""

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
            self._log("\n  ┌── STEP: FINALIZE (after adversarial) ──")
            output, success, _ = self.run_step(
                finalize_step,
                {
                    "cycle_num": cycle_num,
                    "orient_context": orient_ctx,
                    "confirmed_outputs": confirmed_outputs,
                },
            )
            out_path = self.state.step_output_path(finalize_step.name)
            out_path.write_text(output, encoding="utf-8")
            result.steps_completed[finalize_step.name] = out_path
            self._log("  └── finalize: done\n")

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
                adv_step = StepConfig(
                    name="adversarial",
                    prompt_template=template,
                    timeout_minutes=45,
                )
            else:
                self._log("    No adversarial step configured — skipping")
                return

        orient_ctx = build_orient_context(self.state, max_recent_cycles=3)
        output, success, _ = self.run_step(
            adv_step,
            {
                "cycle_num": cycle_num,
                "orient_context": orient_ctx,
                "confirmed_outputs": confirmed_outputs,
            },
        )

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

        return any(re.search(pattern, execute_output, re.IGNORECASE) for pattern in patterns)

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

    def _scan_staged_for_secrets(self) -> str | None:
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
        """Read the latest finalized one-line summary for this cycle if present."""
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

    def _extract_plan_summary(self) -> str:
        """Return a short one-line summary from the current plan file.

        Kept for compatibility with callers/tests that used the old plan-only
        summary helper before commit summaries started preferring progress.md.
        """
        return self._extract_first_meaningful_line(self.state.read_plan())

    @staticmethod
    def _extract_first_meaningful_line(text: str) -> str:
        """Skip markdown boilerplate and transport noise when summarizing."""
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

    def _log_cycle_stats(self, result: CycleResult) -> None:
        """Print token and file-access stats for a completed cycle."""
        if not (result.tokens_by_model or result.files_accessed):
            return
        lines = [f"\n  ── Cycle {result.cycle_number} stats ──"]
        if result.tokens_by_model:
            col = max(len(m) for m in result.tokens_by_model) + 2
            lines.append(f"  {'Model':<{col}}  In        Out")
            lines.append(f"  {'-' * col}  --------  --------")
            for model, (in_tok, out_tok) in sorted(result.tokens_by_model.items()):
                lines.append(f"  {model:<{col}}  {in_tok:>8,}  {out_tok:>8,}")
            lines.append(
                f"  {'TOTAL':<{col}}  {result.input_tokens:>8,}  {result.output_tokens:>8,}"
            )
        if result.files_accessed:
            all_files: list[str] = []
            for step_files in result.files_accessed.values():
                all_files.extend(step_files)
            unique = list(dict.fromkeys(all_files))
            lines.append(f"  Files accessed: {len(unique)}")
            for f in unique:
                lines.append(f"    {f}")
        self._log("\n".join(lines))

    def _log_run_stats(self, results: list[CycleResult]) -> None:
        """Print aggregate token and file-access stats for the full run."""
        # Aggregate tokens per model across all cycles.
        run_by_model: dict[str, tuple[int, int]] = {}
        for r in results:
            for model, (in_tok, out_tok) in r.tokens_by_model.items():
                prev_in, prev_out = run_by_model.get(model, (0, 0))
                run_by_model[model] = (prev_in + in_tok, prev_out + out_tok)

        total_in = sum(r.input_tokens for r in results)
        total_out = sum(r.output_tokens for r in results)

        all_files: list[str] = []
        for r in results:
            for step_files in r.files_accessed.values():
                all_files.extend(step_files)
        unique_files = list(dict.fromkeys(all_files))

        if not (run_by_model or unique_files):
            return

        self._log("\n  ══ Run summary ══")
        if run_by_model:
            col = max(len(m) for m in run_by_model) + 2
            self._log(f"  {'Model':<{col}}  In        Out")
            self._log(f"  {'-' * col}  --------  --------")
            for model, (in_tok, out_tok) in sorted(run_by_model.items()):
                self._log(f"  {model:<{col}}  {in_tok:>8,}  {out_tok:>8,}")
            self._log(f"  {'TOTAL':<{col}}  {total_in:>8,}  {total_out:>8,}")
        if unique_files:
            self._log(f"  Unique files touched: {len(unique_files)}")
            for f in unique_files:
                self._log(f"    {f}")
        self._log("")

    # _make_logger removed — logging is now handled by StepLogger (step_logger.py).
    # self._log = self._step_logger.log (set in __init__)
