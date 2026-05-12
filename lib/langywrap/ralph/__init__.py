"""
langywrap.ralph — Hybrid Python orchestrator for the Ralph loop.

Manages the autonomous AI research/engineering cycle:
orient → plan → execute → critic → finalize

Actual AI calls are routed through langywrap.router.ExecutionRouter.
Shell-level execwrap security stays in bash.

Public API::

    from langywrap.ralph import RalphLoop, RalphConfig, CycleResult, load_ralph_config

    config = load_ralph_config(Path("."))
    loop = RalphLoop(config, router=None)   # router=None for stub/dry-run mode
    results = loop.run(budget=20, resume=True)

Production cycle counts:
  riemann2:          675 cycles, 5-step, multi-model, lean retry
  crunchdaoobesity:  212 cycles, 4-step, orient context pre-digestion (~11x compression)
  llmtemplate:       generic template version
"""

from langywrap.ralph.config import (
    DEFAULT_STEPS,
    QualityGateConfig,
    RalphConfig,
    StepConfig,
    load_ralph_config,
)
from langywrap.ralph.coverage_budget import (
    CoverageBudget,
    CoverageReport,
    evaluate_coverage,
    filter_eligible_tasks,
)
from langywrap.ralph.lint_tasks import (
    LintConfig,
    LintFinding,
    LintReport,
    autofix as lint_autofix,
    lint as lint_tasks,
)
from langywrap.ralph.module import Module, ModuleRunner, StepDef
from langywrap.ralph.module import gate as module_gate
from langywrap.ralph.module import match as module_match
from langywrap.ralph.module import step as module_step
from langywrap.ralph.pipeline import (
    Gate,
    Loop,
    Match,
    Periodic,
    Pipeline,
    Retry,
    Step,
    Throttle,
)
from langywrap.ralph.runner import RalphLoop
from langywrap.ralph.state import CycleResult, RalphState, TaskEntry, TaskStatus

__all__ = [
    # Core
    "RalphLoop",
    "RalphConfig",
    "CycleResult",
    # Config (legacy)
    "StepConfig",
    "QualityGateConfig",
    "DEFAULT_STEPS",
    "load_ralph_config",
    # Pipeline (Python-first config)
    "Pipeline",
    "Step",
    "Loop",
    "Gate",
    "Match",
    "Retry",
    "Periodic",
    "Throttle",
    # Module (forward()-based runner)
    "Module",
    "ModuleRunner",
    "StepDef",
    "module_step",
    "module_match",
    "module_gate",
    # State
    "RalphState",
    "TaskEntry",
    "TaskStatus",
    # Anti-mode-collapse: coverage budgets + linter
    "CoverageBudget",
    "CoverageReport",
    "evaluate_coverage",
    "filter_eligible_tasks",
    "LintConfig",
    "LintFinding",
    "LintReport",
    "lint_tasks",
    "lint_autofix",
]
