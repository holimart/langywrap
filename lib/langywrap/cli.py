"""langywrap CLI — entry point for all orchestration commands."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import click


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(package_name="langywrap")
def main() -> None:
    """Universal AI agent orchestration toolkit."""


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


@main.group()
def install() -> None:
    """Install langywrap components globally or build from source."""


@install.command("system")
def install_system() -> None:
    """Install langywrap globally (pipx / system-wide)."""
    langywrap_dir = Path(__file__).parent.parent.parent
    script = langywrap_dir / "install.sh"
    if not script.exists():
        click.echo(f"install.sh not found at {script}", err=True)
        raise SystemExit(1)
    subprocess.run(["bash", str(script)], check=False)


@install.command("rtk")
def install_rtk() -> None:
    """Build and install the RTK (Router Toolkit) from source."""
    langywrap_dir = Path(__file__).parent.parent.parent
    script = langywrap_dir / "install.sh"
    if not script.exists():
        click.echo(f"install.sh not found at {script}", err=True)
        raise SystemExit(1)
    # install.sh with just RTK feature
    subprocess.run(["bash", str(script), "--defaults"], check=False)


# ---------------------------------------------------------------------------
# couple
# ---------------------------------------------------------------------------


@main.group()
def couple() -> None:
    """Couple langywrap to a downstream repository."""


@couple.command("add")
@click.argument("repo")
@click.option("--defaults", is_flag=True, help="Accept all defaults.")
@click.option("--minimal", is_flag=True, help="Security only.")
@click.option("--dry-run", is_flag=True, help="Preview changes.")
def couple_add(repo: str, defaults: bool, minimal: bool, dry_run: bool) -> None:
    """Couple a downstream repo (adds submodule + wiring)."""
    langywrap_dir = Path(__file__).parent.parent.parent
    script = langywrap_dir / "scripts" / "couple.sh"
    if not script.exists():
        click.echo(f"couple.sh not found at {script}", err=True)
        raise SystemExit(1)
    cmd = ["bash", str(script), str(Path(repo).resolve())]
    if defaults:
        cmd.append("--defaults")
    if minimal:
        cmd.append("--minimal")
    if dry_run:
        cmd.append("--dry-run")
    subprocess.run(cmd, check=False)


@couple.command("remove")
@click.argument("repo")
def couple_remove(repo: str) -> None:
    """Remove coupling from a downstream repo."""
    repo_path = Path(repo).resolve()
    removed = []
    for d in [".langywrap", ".exec"]:
        target = repo_path / d
        if target.exists():
            import shutil
            shutil.rmtree(target)
            removed.append(d)
    if removed:
        click.echo(f"Removed: {', '.join(removed)} from {repo_path}")
    else:
        click.echo(f"No coupling found in {repo_path}")


@couple.command("list")
def couple_list() -> None:
    """List all currently coupled repos."""
    langywrap_dir = Path(__file__).parent.parent.parent
    # Search for projects with .langywrap/config.yaml pointing back to us
    parent = langywrap_dir.parent
    coupled = []
    for d in sorted(parent.iterdir()):
        cfg = d / ".langywrap" / "config.yaml"
        if cfg.exists():
            coupled.append(d.name)
    if coupled:
        click.echo("Coupled repos:")
        for name in coupled:
            click.echo(f"  {name}")
    else:
        click.echo("No coupled repos found in parent directory.")


# ---------------------------------------------------------------------------
# scaffold
# ---------------------------------------------------------------------------


@main.group()
def scaffold() -> None:
    """Scaffold new projects from langywrap templates."""


@scaffold.command("new")
@click.argument("name")
@click.option("--template", "-t", default="default", show_default=True, help="Template name.")
@click.option("--output", "-o", default=".", show_default=True, help="Output directory.")
def scaffold_new(name: str, template: str, output: str) -> None:
    """Create a new project from a template."""
    from langywrap.template.scaffold import scaffold_project

    langywrap_dir = Path(__file__).parent.parent.parent
    target = scaffold_project(
        target_dir=Path(output).resolve(),
        name=name,
        langywrap_dir=langywrap_dir,
    )
    click.echo(f"Scaffolded {name} at {target}")


# ---------------------------------------------------------------------------
# compound
# ---------------------------------------------------------------------------


@main.group()
def compound() -> None:
    """Manage the compound engineering lesson hub."""


@compound.command("push")
@click.argument("lesson_file", type=click.Path(exists=True))
def compound_push(lesson_file: str) -> None:
    """Push a lesson file to the compound hub."""
    from langywrap.compound.propagate import push_to_hub

    path = push_to_hub(
        solution_path=Path(lesson_file),
        project_name=Path.cwd().name,
    )
    if path:
        click.echo(f"Pushed to hub: {path}")
    else:
        click.echo("Hub not found. Set up langywrap hub directory first.", err=True)
        raise SystemExit(1)


@compound.command("search")
@click.argument("query")
def compound_search(query: str) -> None:
    """Search compound lessons by keyword or tag."""
    from langywrap.compound.propagate import find_hub_dir
    from langywrap.compound.solutions import SolutionStore

    hub = find_hub_dir()
    if not hub:
        click.echo("Hub not found.", err=True)
        raise SystemExit(1)
    store = SolutionStore(hub / "docs" / "solutions")
    results = store.search(query=query)
    if not results:
        click.echo(f"No lessons matching '{query}'")
        return
    for s in results:
        tags = ", ".join(s.tags) if s.tags else ""
        click.echo(f"  {s.date}  {s.title}  [{tags}]")


# ---------------------------------------------------------------------------
# ralph — router wiring
# ---------------------------------------------------------------------------


def _build_router(project_dir: Path) -> "ExecutionRouter":
    """Build an ExecutionRouter from project config, wiring backends + execwrap.

    Discovers:
      - .exec/execwrap.bash for security wrapping
      - .langywrap/router.yaml for model routing
      - opencode binary at ~/.opencode/bin/opencode or PATH
      - .env for API keys (NVIDIA_API_KEY, OPENROUTER_API_KEY)
    """
    from langywrap.router.backends import Backend, BackendConfig
    from langywrap.router.config import load_route_config
    from langywrap.router.router import ExecutionRouter

    # Load .env if present
    env_file = project_dir / ".env"
    if env_file.exists():
        import os
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val

    # Try Python pipeline first (.langywrap/ralph.py)
    route_config = None
    from langywrap.ralph.pipeline import load_pipeline_config
    pipeline = load_pipeline_config(project_dir)
    if pipeline is not None:
        route_config = pipeline.to_route_config(project_dir)

    # Try v2 YAML config (models: section in ralph.yaml)
    if route_config is None:
        for cfg_candidate in [".langywrap/ralph.yaml", ".langywrap/ralph.yml", "ralph.yaml"]:
            cfg_path = project_dir / cfg_candidate
            if cfg_path.exists():
                import yaml as _yaml
                with cfg_path.open() as _fh:
                    _raw = _yaml.safe_load(_fh) or {}
                if "flow" in _raw:
                    from langywrap.ralph.config_v2 import build_route_config_from_v2
                    route_config = build_route_config_from_v2(_raw, project_dir)
                break

    if route_config is None:
        route_config = load_route_config(project_dir)

    # Discover execwrap
    execwrap = None
    for candidate in [
        project_dir / ".exec" / "execwrap.bash",
        Path.home() / ".langywrap" / "execwrap.bash",
    ]:
        if candidate.exists() and candidate.stat().st_mode & 0o111:
            execwrap = str(candidate)
            break

    # Discover opencode binary
    import shutil
    opencode_bin = shutil.which("opencode")
    if not opencode_bin:
        oc_path = Path.home() / ".opencode" / "bin" / "opencode"
        if oc_path.exists():
            opencode_bin = str(oc_path)

    # Build backend configs for all backends referenced in route rules
    backends: dict[Backend, BackendConfig] = {}

    used_backends = {rule.backend for rule in route_config.rules}
    used_backends.add(route_config.default_backend)

    # Derive backend timeout from the max step timeout in route rules.
    # BackendConfig.timeout_seconds caps per-call duration via
    # min(step_timeout, backend_timeout), so it must be >= the longest step.
    max_step_timeout = max(
        (rule.timeout_seconds for rule in route_config.rules),
        default=1800,
    )

    if Backend.CLAUDE in used_backends:
        backends[Backend.CLAUDE] = BackendConfig(
            type=Backend.CLAUDE,
            execwrap_path=execwrap,
            timeout_seconds=max_step_timeout,
        )

    if Backend.OPENCODE in used_backends:
        backends[Backend.OPENCODE] = BackendConfig(
            type=Backend.OPENCODE,
            binary_path=opencode_bin,
            execwrap_path=execwrap,
            timeout_seconds=max_step_timeout,
        )

    if Backend.OPENROUTER in used_backends:
        backends[Backend.OPENROUTER] = BackendConfig(
            type=Backend.OPENROUTER,
            api_key_source="OPENROUTER_API_KEY",
            timeout_seconds=max_step_timeout,
        )

    if Backend.DIRECT_API in used_backends:
        backends[Backend.DIRECT_API] = BackendConfig(
            type=Backend.DIRECT_API,
            timeout_seconds=max_step_timeout,
        )

    router = ExecutionRouter(route_config, backends)
    return router


# ---------------------------------------------------------------------------
# ralph
# ---------------------------------------------------------------------------


@main.group()
def ralph() -> None:
    """Orchestrate ralph loop (tree-search ML experimentation) runs."""


@ralph.command("run")
@click.argument("config", type=click.Path(exists=True), required=False, default=".")
@click.option("--dry-run", is_flag=True, help="Parse config without executing.")
@click.option("--budget", "-n", type=int, default=None, help="Max cycles.")
@click.option("--resume", is_flag=True, help="Resume from last cycle.")
@click.option("--stub", is_flag=True, help="Run in stub mode (no AI calls).")
def ralph_run(config: str, dry_run: bool, budget: int | None, resume: bool, stub: bool) -> None:
    """Start a ralph loop run from a config file or project dir."""
    project_dir = Path(config).resolve()
    if project_dir.is_file():
        project_dir = project_dir.parent

    # Try Module-based pipeline first (forward() runner)
    from langywrap.ralph.module import ModuleRunner, load_module_config

    module = load_module_config(project_dir)
    if module is not None:
        click.echo(f"Module pipeline: {type(module).__name__}")

        router = None
        if not stub:
            try:
                router = _build_router(project_dir)
            except Exception as exc:
                if not dry_run:
                    raise
                click.echo(f"Warning: router setup failed ({exc}), stub mode", err=True)

        # Extract throttle from module
        throttle_utc = ""
        # Check for a Throttle-like attribute or class-level config
        runner = ModuleRunner(
            module,
            project_dir=project_dir,
            router=router,
            budget=budget or 10,
        )

        if dry_run:
            report = runner.dry_run()
            click.echo(json.dumps(report, indent=2, default=str))
            return

        results = runner.run(budget=budget, resume=resume)
        click.echo(f"Completed {len(results)} cycles.")
        return

    # Fall back to declarative Pipeline or YAML config
    from langywrap.ralph.config import load_ralph_config
    from langywrap.ralph.runner import RalphLoop

    cfg = load_ralph_config(project_dir)

    router = None
    if not stub:
        try:
            router = _build_router(project_dir)
        except Exception as exc:
            if not dry_run:
                raise
            click.echo(f"Warning: router setup failed ({exc}), dry-run continues in stub mode", err=True)

    loop = RalphLoop(cfg, router=router)

    if dry_run:
        report = loop.dry_run()
        click.echo(json.dumps(report, indent=2, default=str))
        return

    results = loop.run(budget=budget, resume=resume)
    click.echo(f"Completed {len(results)} cycles.")
    confirmed = sum(1 for r in results if r.fully_confirmed)
    click.echo(f"Fully confirmed: {confirmed}/{len(results)}")


@ralph.command("status")
@click.argument("run_id", required=False)
def ralph_status(run_id: str | None) -> None:
    """Show status of the current or specified run."""
    from langywrap.ralph.config import load_ralph_config
    from langywrap.ralph.state import RalphState

    project_dir = Path.cwd()
    cfg = load_ralph_config(project_dir)
    state = RalphState(cfg.resolved_state_dir)

    cycle = state.get_cycle_count()
    pending = state.pending_count()
    plan = state.read_plan()
    plan_preview = plan.splitlines()[0] if plan.strip() else "(no plan)"

    click.echo(f"Project:  {project_dir.name}")
    click.echo(f"Cycle:    {cycle}")
    click.echo(f"Pending:  {pending} tasks")
    click.echo(f"Plan:     {plan_preview}")


@ralph.command("resume")
@click.argument("run_id", required=False, default=".")
@click.option("--budget", "-n", type=int, default=10, help="Max cycles.")
def ralph_resume(run_id: str, budget: int) -> None:
    """Resume a previously interrupted run."""
    from langywrap.ralph.config import load_ralph_config
    from langywrap.ralph.runner import RalphLoop

    project_dir = Path(run_id).resolve()
    if project_dir.is_file():
        project_dir = project_dir.parent
    cfg = load_ralph_config(project_dir)
    router = _build_router(project_dir)
    loop = RalphLoop(cfg, router=router)
    results = loop.run(budget=budget, resume=True)
    click.echo(f"Resumed and completed {len(results)} cycles.")


# ---------------------------------------------------------------------------
# harden
# ---------------------------------------------------------------------------


@main.group()
def harden() -> None:
    """Apply execution security hardening to repos or environments."""


@harden.command("repo")
@click.argument("path", type=click.Path(exists=True), default=".")
def harden_repo(path: str) -> None:
    """Harden a repo: install execwrap, hooks, and security policies."""
    langywrap_dir = Path(__file__).parent.parent.parent
    script = langywrap_dir / "scripts" / "couple.sh"
    if not script.exists():
        click.echo(f"couple.sh not found at {script}", err=True)
        raise SystemExit(1)
    # Minimal coupling = security only
    subprocess.run(
        ["bash", str(script), str(Path(path).resolve()), "--minimal"],
        check=False,
    )


@harden.command("wizard")
def harden_wizard() -> None:
    """Interactive step-by-step hardening wizard."""
    langywrap_dir = Path(__file__).parent.parent.parent
    script = langywrap_dir / "scripts" / "couple.sh"
    if not script.exists():
        click.echo(f"couple.sh not found at {script}", err=True)
        raise SystemExit(1)
    # Full interactive coupling
    subprocess.run(
        ["bash", str(script), str(Path.cwd())],
        check=False,
    )


# ---------------------------------------------------------------------------
# router
# ---------------------------------------------------------------------------


@main.group()
def router() -> None:
    """Manage the execution router (model dispatch configuration)."""


@router.command("show")
@click.argument("path", type=click.Path(exists=True), required=False, default=".")
def router_show(path: str) -> None:
    """Show the current router configuration."""
    from langywrap.router.config import load_route_config

    project_dir = Path(path).resolve()
    cfg = load_route_config(project_dir)
    click.echo(f"Router: {cfg.name}")
    click.echo(f"Description: {cfg.description}")
    click.echo(f"Review every: {cfg.review_every_n} cycles")
    click.echo(f"Default backend: {cfg.default_backend.value}")
    if cfg.peak_hours:
        click.echo(f"Peak hours: {cfg.peak_hours[0]:02d}:00-{cfg.peak_hours[1]:02d}:00 UTC")
    click.echo(f"\nRules ({len(cfg.rules)}):")
    for rule in cfg.rules:
        cond = f"  if {rule.conditions}" if rule.conditions else ""
        retry = f"  retry: {rule.retry_models}" if rule.retry_models else ""
        click.echo(
            f"  {rule.role.value:<12} {rule.model:<40} "
            f"{rule.backend.value:<10} {rule.tier.value:<6} "
            f"{rule.timeout_minutes}m{cond}{retry}"
        )


@router.command("test")
@click.option("--model", "-m", default=None, help="Test a specific model only.")
@click.argument("path", type=click.Path(exists=True), required=False, default=".")
def router_test(model: str | None, path: str) -> None:
    """Dry-run: ping all configured models (or one) and report reachability."""
    from langywrap.router.config import load_route_config
    from langywrap.router.router import ExecutionRouter

    project_dir = Path(path).resolve()
    cfg = load_route_config(project_dir)
    router_instance = ExecutionRouter(cfg)
    results = router_instance.dry_run()

    for role, model_name, reachable in results:
        if model and model not in model_name:
            continue
        status = click.style("OK", fg="green") if reachable else click.style("FAIL", fg="red")
        click.echo(f"  {role.value:<12} {model_name:<40} {status}")
