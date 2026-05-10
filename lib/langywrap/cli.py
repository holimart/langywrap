"""langywrap CLI — entry point for all orchestration commands."""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import click

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class _StreamFormatter(logging.Formatter):
    """Format DEBUG lines with a visual indent so they don't break the main flow.

    DEBUG lines (stream events, verbose trace) are indented with ``    │ ``
    so they nest visually inside the step banner.  Every embedded newline in
    the message is also indented so multi-line debug blobs stay coherent.
    INFO/WARNING/ERROR lines use the plain format unchanged.
    """

    _PLAIN = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
    _DEBUG = "%(asctime)s DEBUG [%(name)s]"

    def __init__(self) -> None:
        super().__init__(datefmt="%H:%M:%S")
        self._plain_fmt = logging.Formatter(self._PLAIN, datefmt="%H:%M:%S")
        self._debug_prefix_fmt = logging.Formatter(self._DEBUG, datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        if record.levelno != logging.DEBUG:
            return self._plain_fmt.format(record)

        # Build prefix: "HH:MM:SS DEBUG [module]"
        prefix = self._debug_prefix_fmt.format(record)
        indent = " " * (len(prefix) + 1)
        msg = record.getMessage()

        # A leading \n in the message signals "emit a blank separator first"
        separator = ""
        if msg.startswith("\n"):
            separator = "    │"
            msg = msg.lstrip("\n")

        lines = msg.splitlines() or [""]
        formatted_lines = []
        for i, line in enumerate(lines):
            if len(line) > 200:
                line = line[:197] + "…"
            if i == 0:
                formatted_lines.append(f"    │ {prefix} {line}")
            else:
                formatted_lines.append(f"    │ {indent}{line}")

        if separator:
            formatted_lines.insert(0, separator)
        return "\n".join(formatted_lines)


def _setup_logging(level: int) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_StreamFormatter())
    logging.root.setLevel(level)
    logging.root.addHandler(handler)


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(package_name="langywrap")
@click.option("-v", "--verbose", count=True, help="Increase verbosity (-v=INFO, -vv=DEBUG).")
@click.pass_context
def main(ctx: click.Context, verbose: int) -> None:
    """Universal AI agent orchestration toolkit."""
    if verbose >= 2:
        level = logging.DEBUG
    elif verbose >= 1:
        level = logging.INFO
    else:
        level = logging.WARNING
    _setup_logging(level)


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
# integrations
# ---------------------------------------------------------------------------


@main.group("integration")
def integration() -> None:
    """Wire optional tools into supported AI runtimes."""


@integration.group("openwolf")
def integration_openwolf() -> None:
    """Manage OpenWolf project memory integration."""


@integration_openwolf.command("status")
@click.argument("repo", type=click.Path(exists=True), default=".")
def openwolf_status_cmd(repo: str) -> None:
    """Show OpenWolf binary, .wolf, Claude hook, and OpenCode plugin status."""
    from langywrap.integrations.openwolf import openwolf_status

    status = openwolf_status(Path(repo).resolve())
    click.echo(json.dumps(status, indent=2, default=str))


@integration_openwolf.command("wire")
@click.argument("repo", type=click.Path(exists=True), default=".")
@click.option("--init", "do_init", is_flag=True, help="Run `openwolf init` first if needed.")
@click.option("--no-claude", is_flag=True, help="Do not wire Claude Code hooks.")
@click.option("--no-opencode", is_flag=True, help="Do not install OpenCode plugin.")
@click.option(
    "--langywrap-only",
    is_flag=True,
    help="Install hooks/plugins that activate only for langywrap-launched runs.",
)
def openwolf_wire_cmd(
    repo: str,
    do_init: bool,
    no_claude: bool,
    no_opencode: bool,
    langywrap_only: bool,
) -> None:
    """Wire OpenWolf into Claude Code and OpenCode for a project."""
    from langywrap.integrations.openwolf import wire_openwolf

    result = wire_openwolf(
        Path(repo).resolve(),
        init=do_init,
        claude=not no_claude,
        opencode=not no_opencode,
        langywrap_only=langywrap_only,
    )
    click.echo(json.dumps(result, indent=2, default=str))


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
# mcp
# ---------------------------------------------------------------------------


@main.group()
def mcp() -> None:
    """Manage project-level MCP server registrations."""


@mcp.command("register")
@click.option("--repo", default=".", show_default=True, help="Target repository root.")
@click.option("--name", required=True, help="MCP server name.")
@click.option("--command", "command_", required=True, help="Server command.")
@click.option("--arg", "args", multiple=True, help="Repeat for multiple command arguments.")
@click.option("--env", "env_vars", multiple=True, help="Environment entries in KEY=VALUE form.")
def mcp_register(
    repo: str, name: str, command_: str, args: tuple[str, ...], env_vars: tuple[str, ...]
) -> None:
    """Register one MCP server into .mcp.json."""
    from langywrap.mcp_config import register_mcp_server

    env: dict[str, str] = {}
    for item in env_vars:
        if "=" not in item:
            raise click.ClickException(f"Invalid --env value: {item!r} (expected KEY=VALUE)")
        key, value = item.split("=", 1)
        env[key] = value

    config_path = Path(repo).resolve() / ".mcp.json"
    register_mcp_server(
        config_path,
        name=name,
        command=command_,
        args=list(args),
        env=env or None,
    )
    click.echo(f"Registered MCP server '{name}' in {config_path}")


@mcp.command("sync")
@click.option("--repo", default=".", show_default=True, help="Target repository root.")
def mcp_sync(repo: str) -> None:
    """Sync .langywrap/mcp.json into project .mcp.json."""
    from langywrap.mcp_config import sync_langywrap_mcp_manifest

    out_path = sync_langywrap_mcp_manifest(Path(repo).resolve())
    click.echo(f"Synced MCP config to {out_path}")


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


def _build_router(project_dir: Path, ralph_cfg: Any | None = None) -> ExecutionRouter:  # noqa: F821
    """Build an ExecutionRouter from project config, wiring backends + execwrap.

    Discovers:
      - .exec/execwrap.bash for security wrapping
      - .langywrap/ralph.py or ralph.yaml for the pipeline spec
      - opencode binary at ~/.opencode/bin/opencode or PATH
      - .env for API keys (NVIDIA_API_KEY, OPENROUTER_API_KEY)
    """
    from langywrap.ralph.config import load_ralph_config
    from langywrap.router.backends import Backend, BackendConfig
    from langywrap.router.router import (
        ExecutionRouter,
        _infer_backend_from_model,
        _resolve_engine_backend,
    )

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

    # Resolve the pipeline's step list — that's where model+engine live now.
    if ralph_cfg is None:
        ralph_cfg = load_ralph_config(project_dir)

    from langywrap.helpers.discovery import find_execwrap, find_rtk

    execwrap = find_execwrap(project_dir)
    rtk = find_rtk(project_dir)
    env_overrides = {
        "LANGYWRAP_OPENWOLF": "1",
        "EXECWRAP_PROJECT_DIR": str(project_dir),
    }

    # Discover CLI binaries for dry-run visibility and stable runtime lookup.
    claude_bin = shutil.which("claude")
    if not claude_bin:
        claude_path = Path.home() / ".local" / "bin" / "claude"
        if claude_path.exists():
            claude_bin = str(claude_path)

    opencode_bin = shutil.which("opencode")
    if not opencode_bin:
        oc_path = Path.home() / ".opencode" / "bin" / "opencode"
        if oc_path.exists():
            opencode_bin = str(oc_path)

    # Build backend configs for every backend actually referenced by a step.
    backends: dict[Backend, BackendConfig] = {}

    used_backends: set[Backend] = set()
    max_step_timeout = 1800  # seconds
    for step in ralph_cfg.steps:
        if step.builtin:
            continue
        backend = _resolve_engine_backend(step.engine) or _infer_backend_from_model(step.model)
        used_backends.add(backend)
        max_step_timeout = max(max_step_timeout, step.timeout_minutes * 60)
    used_backends.add(Backend.CLAUDE)  # default fallback backend

    import logging as _logging

    stream_output = _logging.getLogger().isEnabledFor(_logging.INFO)

    if Backend.CLAUDE in used_backends:
        backends[Backend.CLAUDE] = BackendConfig(
            type=Backend.CLAUDE,
            binary_path=claude_bin,
            execwrap_path=execwrap,
            rtk_path=rtk,
            env_overrides=env_overrides,
            timeout_seconds=max_step_timeout,
            stream_output=stream_output,
            cwd=str(project_dir),
        )

    if Backend.OPENCODE in used_backends:
        backends[Backend.OPENCODE] = BackendConfig(
            type=Backend.OPENCODE,
            binary_path=opencode_bin,
            execwrap_path=execwrap,
            rtk_path=rtk,
            env_overrides=env_overrides,
            timeout_seconds=max_step_timeout,
            stream_output=stream_output,
            cwd=str(project_dir),
        )

    if Backend.OPENROUTER in used_backends:
        backends[Backend.OPENROUTER] = BackendConfig(
            type=Backend.OPENROUTER,
            api_key_source="OPENROUTER_API_KEY",
            rtk_path=rtk,
            env_overrides=env_overrides,
            timeout_seconds=max_step_timeout,
        )

    if Backend.DIRECT_API in used_backends:
        backends[Backend.DIRECT_API] = BackendConfig(
            type=Backend.DIRECT_API,
            rtk_path=rtk,
            env_overrides=env_overrides,
            timeout_seconds=max_step_timeout,
        )

    throttle_window: tuple[int, int] | None = None
    if ralph_cfg.throttle_utc_start is not None and ralph_cfg.throttle_utc_end is not None:
        throttle_window = (ralph_cfg.throttle_utc_start, ralph_cfg.throttle_utc_end)

    router = ExecutionRouter(backends=backends, peak_hours=throttle_window)
    return router


# ---------------------------------------------------------------------------
# tmux helpers
# ---------------------------------------------------------------------------

_TMUX_GUARD = "LANGYWRAP_IN_TMUX"


def _tmux_session_name(project_dir: Path) -> str:
    """Derive a stable tmux session name from the project directory."""
    import re

    name = project_dir.name or "ralph"
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    return f"ralph-{name}"


def _tmux_available() -> bool:
    return shutil.which("tmux") is not None


def _tmux_session_exists(session: str) -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", session],
        capture_output=True,
    )
    return result.returncode == 0


def _launch_in_tmux(session: str, project_dir: Path, keep_pane: bool) -> None:
    """Spawn a detached tmux session running langywrap ralph run with guard set."""
    argv = [sys.argv[0], "ralph", "run", str(project_dir)]
    # Forward any extra args already on sys.argv after "run" and the config arg
    # (budget, resume, stub, --no-tmux — but not --tmux itself since we're inside now)
    skip_next = False
    capture = False
    skip_config = False  # skip the first positional after "run" — already added above
    for arg in sys.argv[1:]:
        if arg in ("ralph", "run"):
            if arg == "run":
                skip_config = True
            capture = True
            continue
        if not capture:
            continue
        if arg == "--no-tmux":
            continue
        if skip_next:
            argv.append(arg)
            skip_next = False
            continue
        if arg in ("--budget", "-n", "--replace-model"):
            argv.append(arg)
            skip_next = True
            continue
        if skip_config and not arg.startswith("-"):
            skip_config = False  # first positional = config path, already in argv
            continue
        argv.append(arg)

    # Add the guard so the child doesn't re-spawn
    env_prefix = f"{_TMUX_GUARD}=1"
    cmd_str = f"{env_prefix} {shlex.join(argv)}"
    if keep_pane:
        cmd_str += (
            r"; status=$?; printf '\nRalph finished (exit %s). "
            r"Press Ctrl-D to close.\n' \"$status\"; exec bash -i"
        )

    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session, "-x", "220", "-y", "50", cmd_str],
        check=True,
    )


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
@click.option("--no-tmux", is_flag=True, help="Run directly in current shell (skip tmux).")
@click.option("--no-keep-pane", is_flag=True, help="Close tmux pane immediately on exit.")
@click.option(
    "--replace-model",
    multiple=True,
    metavar="FROM=TO",
    help=(
        "Replace configured models for this run. FROM may be an exact model/alias "
        "or a shell glob, e.g. --replace-model '*kimi*=openai/gpt-5.3-codex'."
    ),
)
def ralph_run(
    config: str,
    dry_run: bool,
    budget: int | None,
    resume: bool,
    stub: bool,
    no_tmux: bool,
    no_keep_pane: bool,
    replace_model: tuple[str, ...],
) -> None:
    """Start a ralph loop run from a config file or project dir.

    By default spawns (or reuses) a tmux session named ralph-<project> and
    keeps the pane open after the loop exits so you can inspect output.
    Use --no-tmux to run directly in the current shell.
    """
    project_dir = Path(config).resolve()

    # tmux dispatch — skip if: already inside tmux guard, --no-tmux, dry-run,
    # already in a tmux session (TMUX env set), or tmux not available.
    in_guard = os.environ.get(_TMUX_GUARD) == "1"
    in_tmux_session = bool(os.environ.get("TMUX"))
    use_tmux = not no_tmux and not dry_run and not in_guard and not in_tmux_session

    if use_tmux:
        if not _tmux_available():
            click.echo("tmux not found — running directly.", err=True)
        else:
            session_dir = project_dir if project_dir.is_dir() else project_dir.parent
            session = _tmux_session_name(session_dir)
            if _tmux_session_exists(session):
                click.echo(f"Already running in tmux session '{session}'.")
                click.echo(f"Attach with:  tmux attach -t {session}")
                return
            _launch_in_tmux(session, project_dir, keep_pane=not no_keep_pane)
            click.echo(f"Started tmux session '{session}'.")
            click.echo(f"Attach with:  tmux attach -t {session}")
            return
    if project_dir.is_file():
        project_dir = project_dir.parent

    from langywrap.ralph.config import parse_model_substitutions

    try:
        model_substitutions = parse_model_substitutions(replace_model)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

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
        # Check for a Throttle-like attribute or class-level config
        runner = ModuleRunner(
            module,
            project_dir=project_dir,
            router=router,
            budget=budget or 10,
            model_substitutions=model_substitutions,
        )

        if dry_run:
            report = runner.dry_run()
            click.echo(json.dumps(report, indent=2, default=str))
            return

        results = runner.run(budget=budget, resume=resume)
        click.echo(f"Completed {len(results)} cycles.")
        return

    # Fall back to declarative Pipeline or YAML config
    from langywrap.ralph.config import (
        apply_model_substitutions,
        load_ralph_config,
    )
    from langywrap.ralph.runner import RalphLoop

    cfg = load_ralph_config(project_dir)
    cfg = apply_model_substitutions(cfg, model_substitutions)

    router = None
    if not stub:
        try:
            router = _build_router(project_dir, ralph_cfg=cfg)
        except Exception as exc:
            if not dry_run:
                raise
            click.echo(
                f"Warning: router setup failed ({exc}), dry-run continues in stub mode",
                err=True,
            )

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
    """Show how each pipeline step resolves to a model + backend."""
    from langywrap.ralph.config import load_ralph_config
    from langywrap.router.router import _infer_backend_from_model, _resolve_engine_backend

    project_dir = Path(path).resolve()
    cfg = load_ralph_config(project_dir)
    click.echo(f"Project: {project_dir.name}")
    if cfg.throttle_utc_start is not None and cfg.throttle_utc_end is not None:
        click.echo(f"Peak hours: {cfg.throttle_utc_start:02d}:00-{cfg.throttle_utc_end:02d}:00 UTC")
    click.echo(f"\nSteps ({len(cfg.steps)}):")
    for step in cfg.steps:
        backend = _resolve_engine_backend(step.engine) or _infer_backend_from_model(step.model)
        retry = f"  retry: {step.retry_models}" if step.retry_models else ""
        click.echo(
            f"  {step.name:<12} {step.model:<40} {backend.value:<10} {step.timeout_minutes}m{retry}"
        )


@router.command("test")
@click.option("--model", "-m", default=None, help="Test a specific model only.")
@click.argument("path", type=click.Path(exists=True), required=False, default=".")
def router_test(model: str | None, path: str) -> None:
    """Dry-run: ping every (model, engine) combination from the pipeline."""
    from langywrap.ralph.config import load_ralph_config

    project_dir = Path(path).resolve()
    cfg = load_ralph_config(project_dir)
    router_instance = _build_router(project_dir)

    targets = [(step.model, step.engine, step.timeout_minutes * 60) for step in cfg.steps]
    results = router_instance.dry_run_detailed(targets)

    for result in results:
        if model and model not in result.model:
            continue
        status = (
            click.style("OK", fg="green") if result.reachable else click.style("FAIL", fg="red")
        )
        reason = "" if result.reachable else f"  {result.reason}"
        detail = f" - {result.detail}" if result.detail else ""
        click.echo(f"  {result.model:<40} {result.backend:<10} {status}{reason}{detail}")
