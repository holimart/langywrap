#!/usr/bin/env python3
"""Collect Ralph debugging context from coupled projects.

Reads project names and locations from the repo-root `.env` file:

    LANGYWRAP_PROJECTS=ktorobi,whitehacky
    LANGYWRAP_PROJECT_KTOROBI=/path/to/ktorobi
    LANGYWRAP_PROJECT_RIEMANN2=user@host:/path/to/riemann2

The collector writes one bundle per project containing dry-run output, git
history, tasks/progress files, latest Ralph step/log artifacts, and tmux status.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = REPO_ROOT / ".log" / "inspect-projects"
TEXT_SUFFIXES = {".md", ".txt", ".log", ".json", ".yaml", ".yml", ".toml", ".py"}


@dataclass(frozen=True)
class ProjectRef:
    name: str
    raw_location: str
    host: str | None
    path: str

    @property
    def is_remote(self) -> bool:
        return self.host is not None

    @property
    def tmux_session(self) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "-", PurePosixPath(self.path).name or self.name)
        return f"ralph-{safe}"


@dataclass
class CommandResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    cmd: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Ralph dry-run, state files, logs, git history, and tmux status."
    )
    parser.add_argument(
        "projects",
        nargs="*",
        help="Project names from LANGYWRAP_PROJECTS. Defaults to all projects.",
    )
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--commits", "-n", type=int, default=10, help="Latest git commits to fetch."
    )
    parser.add_argument(
        "--artifacts",
        type=int,
        default=20,
        help="Latest Ralph step/log artifacts to fetch per project.",
    )
    parser.add_argument(
        "--tmux-lines",
        type=int,
        default=120,
        help="Recent tmux pane lines to capture.",
    )
    parser.add_argument(
        "--skip-dry-run",
        action="store_true",
        help="Do not execute `langywrap ralph run --dry-run --no-tmux`.",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Fast mode: only resolve state paths and tmux status.",
    )
    parser.add_argument(
        "--progress-only",
        action="store_true",
        help="Fast mode: compare current git HEADs with the previous inspection baseline.",
    )
    parser.add_argument(
        "--no-update-latest",
        action="store_true",
        help="Do not update the persistent latest_state.json baseline after inspection.",
    )
    parser.add_argument(
        "--model-details",
        action="store_true",
        help="Print full per-step model/provider summaries after the status table.",
    )
    return parser.parse_args()


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise SystemExit(f"env file not found: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def parse_project_ref(name: str, location: str) -> ProjectRef:
    # Treat user@host:/path as remote, but avoid classifying local /path:with:colon.
    match = re.match(r"^([^/@:\s]+@[^:\s]+|[^/@:\s]+):(.+)$", location)
    if match and not location.startswith("/"):
        return ProjectRef(
            name=name, raw_location=location, host=match.group(1), path=match.group(2)
        )
    return ProjectRef(name=name, raw_location=location, host=None, path=location)


def load_projects(env: dict[str, str], requested: list[str]) -> list[ProjectRef]:
    names = [p.strip() for p in env.get("LANGYWRAP_PROJECTS", "").split(",") if p.strip()]
    if requested:
        wanted = set(requested)
        unknown = sorted(wanted - set(names))
        if unknown:
            raise SystemExit(f"unknown project(s): {', '.join(unknown)}")
        names = [name for name in names if name in wanted]
    projects: list[ProjectRef] = []
    for name in names:
        key = f"LANGYWRAP_PROJECT_{name.upper()}"
        location = env.get(key)
        if not location:
            raise SystemExit(f"missing {key} in env file")
        projects.append(parse_project_ref(name, location))
    return projects


def run_local(argv: list[str], *, cwd: str | None = None, timeout: int = 120) -> CommandResult:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            result.returncode == 0, result.returncode, result.stdout, result.stderr, argv
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics should continue after failures.
        return CommandResult(False, -1, "", str(exc), argv)


def run_remote(host: str, command: str, *, timeout: int = 120) -> CommandResult:
    # OpenSSH concatenates remote argv with spaces before the remote shell parses it.
    # Send one quoted command string so bash receives the full -lc payload intact.
    argv = ["ssh", host, shlex.join(["bash", "-lc", command])]
    return run_local(argv, timeout=timeout)


def run_project(project: ProjectRef, command: str, *, timeout: int = 120) -> CommandResult:
    if project.is_remote:
        remote_command = f"cd {shlex.quote(project.path)} && {command}"
        return run_remote(project.host or "", remote_command, timeout=timeout)
    return run_local(["bash", "-lc", command], cwd=project.path, timeout=timeout)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_command_result(path: Path, result: CommandResult) -> None:
    payload = [
        f"$ {shlex.join(result.cmd)}",
        f"returncode: {result.returncode}",
        "",
        "--- stdout ---",
        result.stdout,
        "",
        "--- stderr ---",
        result.stderr,
    ]
    write_text(path, "\n".join(payload))


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def extract_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for idx, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, end = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and not text[idx + end :].strip():
            return obj
    return None


def dry_run(project: ProjectRef, out_dir: Path, skip: bool) -> dict[str, Any] | None:
    if skip:
        write_text(out_dir / "dry_run.skipped.txt", "dry-run skipped by --skip-dry-run\n")
        return None
    result = run_project(project, "langywrap ralph run --dry-run --no-tmux .", timeout=300)
    write_command_result(out_dir / "dry_run.raw.txt", result)
    obj = extract_json_object(result.stdout)
    if obj is not None:
        write_text(out_dir / "dry_run.json", json.dumps(obj, indent=2, sort_keys=True) + "\n")
    return obj


def common_state_dirs(project: ProjectRef, dry_report: dict[str, Any] | None) -> list[str]:
    state_dirs: list[str] = []
    if dry_report and isinstance(dry_report.get("state_dir"), str):
        state_dirs.append(dry_report["state_dir"])
    for rel in ("ralph", "research", "research/ralph", "state"):
        candidate = str(PurePosixPath(project.path) / rel)
        if candidate not in state_dirs:
            state_dirs.append(candidate)
    return state_dirs


def first_existing_file(project: ProjectRef, paths: list[str]) -> str | None:
    tests = " || ".join(f"test -f {shlex.quote(path)}" for path in paths)
    result = run_project(project, tests, timeout=30)
    if not result.ok:
        return None
    for path in paths:
        test = run_project(project, f"test -f {shlex.quote(path)}", timeout=30)
        if test.ok:
            return path
    return None


def fetch_file(project: ProjectRef, remote_path: str, local_path: Path) -> bool:
    if project.is_remote:
        result = run_remote(project.host or "", f"cat {shlex.quote(remote_path)}", timeout=60)
    else:
        result = run_local(["cat", remote_path], timeout=60)
    if not result.ok:
        return False
    write_text(local_path, result.stdout)
    return True


def collect_state_files(
    project: ProjectRef, out_dir: Path, dry_report: dict[str, Any] | None
) -> dict[str, str | None]:
    state_dirs = common_state_dirs(project, dry_report)
    tasks_candidates = [str(PurePosixPath(d) / "tasks.md") for d in state_dirs]
    progress_candidates = [str(PurePosixPath(d) / "progress.md") for d in state_dirs]
    tasks_path = first_existing_file(project, tasks_candidates)
    progress_path = first_existing_file(project, progress_candidates)
    if tasks_path:
        fetch_file(project, tasks_path, out_dir / "state" / "tasks.md")
    if progress_path:
        fetch_file(project, progress_path, out_dir / "state" / "progress.md")
    return {"tasks_md": tasks_path, "progress_md": progress_path}


def collect_commits(project: ProjectRef, out_dir: Path, n: int) -> None:
    fmt = "%h %ad %an %d %s"
    command = (
        "git log "
        f"--date=iso --pretty=format:{shlex.quote(fmt)} "
        f"--stat -n {max(n, 0)}"
    )
    result = run_project(project, command, timeout=120)
    write_command_result(out_dir / "git" / "latest_commits.txt", result)


def collect_git_state(project: ProjectRef, out_dir: Path) -> dict[str, Any]:
    command = """python3 - <<'PY'
import json
import subprocess


def git(*args):
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "ok": result.returncode == 0,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "returncode": result.returncode,
    }


inside = git("rev-parse", "--is-inside-work-tree")
if not inside["ok"]:
    print(json.dumps({"ok": False, "error": inside["stderr"] or "not a git repository"}))
    raise SystemExit(0)

status = git("status", "--porcelain=v1", "--branch")
porcelain_lines = status["stdout"].splitlines() if status["ok"] else []
dirty_lines = [line for line in porcelain_lines if line and not line.startswith("##")]

state = {
    "ok": True,
    "commit": git("rev-parse", "HEAD")["stdout"],
    "short_commit": git("rev-parse", "--short", "HEAD")["stdout"],
    "branch": git("branch", "--show-current")["stdout"],
    "subject": git("log", "-1", "--format=%s")["stdout"],
    "author_date": git("log", "-1", "--format=%aI")["stdout"],
    "committer_date": git("log", "-1", "--format=%cI")["stdout"],
    "upstream": git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")["stdout"],
    "status_branch": porcelain_lines[0] if porcelain_lines else "",
    "dirty": bool(dirty_lines),
    "dirty_count": len(dirty_lines),
}
print(json.dumps(state, sort_keys=True))
PY"""
    result = run_project(project, command, timeout=60)
    write_command_result(out_dir / "git" / "state.raw.txt", result)
    state = extract_json_object(result.stdout) if result.ok else None
    if state is None:
        state = {
            "ok": False,
            "error": (
                result.stderr.strip()
                or result.stdout.strip()
                or "failed to collect git state"
            ),
        }
    write_text(
        out_dir / "git" / "state.json",
        json.dumps(state, indent=2, sort_keys=True) + "\n",
    )
    return state


def annotate_progress(
    project: ProjectRef,
    git_state: dict[str, Any],
    previous_state: dict[str, Any],
) -> dict[str, Any]:
    previous_projects = previous_state.get("projects")
    previous = (
        previous_projects.get(project.name, {}) if isinstance(previous_projects, dict) else {}
    )
    previous_git = previous.get("git", {}) if isinstance(previous, dict) else {}
    previous_commit = previous_git.get("commit") if isinstance(previous_git, dict) else None
    previous_short = previous_git.get("short_commit") if isinstance(previous_git, dict) else None
    previous_inspected_at = previous.get("inspected_at") if isinstance(previous, dict) else None
    current_commit = git_state.get("commit")
    comparable = bool(git_state.get("ok") and current_commit)
    has_baseline = bool(previous_commit)
    advanced = bool(comparable and has_baseline and current_commit != previous_commit)
    return {
        "previous_commit": previous_commit,
        "previous_short_commit": previous_short,
        "previous_inspected_at": previous_inspected_at,
        "has_baseline": has_baseline,
        "advanced_since_last": advanced,
    }


def shell_find_latest_artifacts(state_dirs: list[str], n: int) -> str:
    roots = ", ".join(repr(path) for path in state_dirs)
    return f"""python3 - <<'PY'
import pathlib

roots = [{roots}]
limit = {max(n, 0)}
suffixes = {{'.md', '.txt', '.log', '.json'}}
items = []

for root in roots:
    base = pathlib.Path(root)
    for subdir in ('steps', 'logs'):
        parent = base / subdir
        if not parent.exists():
            continue
        for child in parent.glob('**/*'):
            if child.is_file() and child.suffix.lower() in suffixes:
                try:
                    items.append((child.stat().st_mtime, str(child)))
                except OSError:
                    pass

for _, path in sorted(items, reverse=True)[:limit]:
    print(path)
PY"""


def list_latest_artifacts(project: ProjectRef, state_dirs: list[str], n: int) -> list[str]:
    command = shell_find_latest_artifacts(state_dirs, n)
    if project.is_remote:
        result = run_remote(project.host or "", command, timeout=120)
    else:
        result = run_local(["bash", "-lc", command], timeout=120)
    if not result.ok:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def artifact_local_name(path: str) -> str:
    pure = PurePosixPath(path)
    parent = pure.parent.name
    return f"{parent}__{pure.name}"


def collect_artifacts(
    project: ProjectRef,
    out_dir: Path,
    dry_report: dict[str, Any] | None,
    n: int,
) -> list[str]:
    artifacts = list_latest_artifacts(project, common_state_dirs(project, dry_report), n)
    copied: list[str] = []
    for path in artifacts:
        if PurePosixPath(path).suffix.lower() not in TEXT_SUFFIXES:
            continue
        local = out_dir / "artifacts" / artifact_local_name(path)
        if fetch_file(project, path, local):
            copied.append(path)
    write_text(out_dir / "artifacts" / "manifest.txt", "\n".join(copied) + ("\n" if copied else ""))
    return copied


def classify_tmux(
    text: str,
    pane_command: str,
    exists: bool,
    process_tree: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not exists:
        return {"exists": False, "state": "not-running", "input_like": False}
    process_tree = process_tree or []
    input_patterns = [
        r"Press Ctrl-D to close",
        r"Ralph finished",
        r"\bContinue\?",
        r"\[y/N\]|\[Y/n\]",
        r"Do you want",
        r"Press enter",
        r"Enter .*:",
        r"waiting for user input",
    ]
    input_like = any(re.search(pattern, text, re.IGNORECASE) for pattern in input_patterns)
    process_args = "\n".join(str(item.get("args") or "") for item in process_tree)
    active_process = bool(
        re.search(
            r"\b(langywrap|opencode|claude|openwolf|graphify|textify|uv|python3?)\b.*\bralph\b|\bralph\b.*\b(langywrap|opencode|claude|uv|python3?)\b",
            process_args,
            re.IGNORECASE,
        )
        or re.search(r"\b(opencode|claude)\b", process_args, re.IGNORECASE)
    )
    ralph_output = bool(re.search(r"\[ralph\]|RalphLoop starting|Cycle \d+/\d+", text))
    state = "awaiting-input-or-finished" if input_like else "running-or-idle"
    if active_process:
        state = "running"
    elif input_like:
        state = "awaiting-input-or-finished"
    elif ralph_output and not input_like:
        state = "running-or-idle"
    elif pane_command in {"bash", "zsh", "fish", "sh"}:
        state = "shell-open"
    return {
        "exists": True,
        "state": state,
        "input_like": input_like,
        "pane_command": pane_command,
        "active_process": active_process,
        "ralph_output": ralph_output,
    }


def process_tree_command(root_pid: str) -> str:
    return f"""python3 - <<'PY'
import json
import subprocess

root = {root_pid!r}
if not root.isdigit():
    print("[]")
    raise SystemExit(0)

result = subprocess.run(
    ["ps", "-eo", "pid=,ppid=,stat=,comm=,args="],
    capture_output=True,
    text=True,
    check=False,
)
if result.returncode != 0:
    print("[]")
    raise SystemExit(0)

rows = []
children = {{}}
for line in result.stdout.splitlines():
    parts = line.strip().split(None, 4)
    if len(parts) < 5:
        continue
    pid, ppid, stat, comm, args = parts
    row = {{"pid": pid, "ppid": ppid, "stat": stat, "comm": comm, "args": args}}
    rows.append(row)
    children.setdefault(ppid, []).append(row)

seen = set()
stack = list(children.get(root, []))
descendants = []
while stack:
    row = stack.pop(0)
    pid = row["pid"]
    if pid in seen:
        continue
    seen.add(pid)
    descendants.append(row)
    stack.extend(children.get(pid, []))

print(json.dumps(descendants, sort_keys=True))
PY"""


def extract_tmux_error(text: str) -> dict[str, Any] | None:
    lines = text.splitlines()
    start_idx = 0
    for idx, line in enumerate(lines):
        if re.search(r"\[ralph\]\s+RalphLoop starting:", line):
            start_idx = idx
    scoped_lines = lines[start_idx:]
    markers = [
        r"Traceback \(most recent call last\):",
        r"\b(?:Error|ERROR|Exception|ValueError|RuntimeError|SystemExit):",
        r"Ralph finished \(exit \"?[1-9]\d*\"?\)",
        r"preflight .*hard-failed",
        r"hard-fail",
    ]
    match_idx = None
    for idx, line in enumerate(scoped_lines):
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in markers):
            match_idx = idx
            break
    if match_idx is None:
        return None

    start = max(match_idx - 6, 0)
    end = min(match_idx + 50, len(scoped_lines))
    excerpt = scoped_lines[start:end]
    headline = next((line.strip() for line in scoped_lines[match_idx:end] if line.strip()), "tmux error")
    return {
        "headline": headline[:240],
        "line": start_idx + match_idx + 1,
        "excerpt": "\n".join(excerpt).strip(),
    }


def collect_tmux_process_tree(project: ProjectRef, pane_pid: str, out_dir: Path) -> list[dict[str, Any]]:
    result = (
        run_remote(project.host or "", process_tree_command(pane_pid), timeout=20)
        if project.is_remote
        else run_local(["bash", "-lc", process_tree_command(pane_pid)], timeout=20)
    )
    write_command_result(out_dir / "tmux" / "process_tree.raw.txt", result)
    try:
        data = json.loads(result.stdout) if result.ok else []
    except json.JSONDecodeError:
        data = []
    return data if isinstance(data, list) else []


def collect_tmux(project: ProjectRef, out_dir: Path, lines: int) -> dict[str, Any]:
    session = project.tmux_session
    exists_cmd = f"tmux has-session -t {shlex.quote(session)}"
    exists = (
        run_remote(project.host or "", exists_cmd, timeout=20)
        if project.is_remote
        else run_local(["bash", "-lc", exists_cmd], timeout=20)
    )
    if not exists.ok:
        status = classify_tmux("", "", False) | {"session": session}
        write_text(out_dir / "tmux" / "status.json", json.dumps(status, indent=2) + "\n")
        return status

    pane_cmd = f"tmux display-message -p -t {shlex.quote(session)} '#{{pane_current_command}}'"
    pane_pid_cmd = f"tmux display-message -p -t {shlex.quote(session)} '#{{pane_pid}}'"
    capture_cmd = f"tmux capture-pane -p -S -{max(lines, 1)} -t {shlex.quote(session)}"
    pane_result = (
        run_remote(project.host or "", pane_cmd, timeout=20)
        if project.is_remote
        else run_local(["bash", "-lc", pane_cmd], timeout=20)
    )
    pane_pid_result = (
        run_remote(project.host or "", pane_pid_cmd, timeout=20)
        if project.is_remote
        else run_local(["bash", "-lc", pane_pid_cmd], timeout=20)
    )
    capture_result = (
        run_remote(project.host or "", capture_cmd, timeout=20)
        if project.is_remote
        else run_local(["bash", "-lc", capture_cmd], timeout=20)
    )
    pane_command = pane_result.stdout.strip().splitlines()[-1] if pane_result.stdout.strip() else ""
    pane_pid = pane_pid_result.stdout.strip().splitlines()[-1] if pane_pid_result.stdout.strip() else ""
    pane_text = capture_result.stdout
    write_command_result(out_dir / "tmux" / "pane_capture.txt", capture_result)
    process_tree = collect_tmux_process_tree(project, pane_pid, out_dir)
    error = extract_tmux_error(pane_text)
    if error is not None:
        write_text(out_dir / "tmux" / "error.txt", error["excerpt"] + "\n")
    status = classify_tmux(pane_text, pane_command, True, process_tree) | {
        "session": session,
        "pane_pid": pane_pid,
        "process_count": len(process_tree),
        "process_tree": process_tree,
        "error": error,
    }
    write_text(
        out_dir / "tmux" / "status.json", json.dumps(status, indent=2, sort_keys=True) + "\n"
    )
    return status


def extract_replace_model_specs(tmux_status: dict[str, Any]) -> list[str]:
    """Return live --replace-model specs from the captured Ralph process args."""
    specs: list[str] = []
    process_tree = tmux_status.get("process_tree")
    if not isinstance(process_tree, list):
        return specs

    for row in process_tree:
        if not isinstance(row, dict):
            continue
        args = str(row.get("args") or "")
        if "ralph" not in args or "run" not in args or "--replace-model" not in args:
            continue
        try:
            tokens = shlex.split(args)
        except ValueError:
            continue
        for idx, token in enumerate(tokens):
            if token == "--replace-model" and idx + 1 < len(tokens):
                specs.append(tokens[idx + 1])
            elif token.startswith("--replace-model="):
                specs.append(token.split("=", 1)[1])

    unique_specs: list[str] = []
    for spec in specs:
        if spec not in unique_specs:
            unique_specs.append(spec)
    return unique_specs


def collect_model_mix(
    project: ProjectRef,
    out_dir: Path,
    replacement_specs: list[str],
) -> dict[str, Any]:
    """Collect effective model-provider mix by loading the project config directly."""
    specs_json = json.dumps(replacement_specs)
    helper_lib = model_mix_helper_lib(project)
    command = f"""python3 - <<'PY'
import json
import sys
from pathlib import Path

helper_lib = {helper_lib!r}
if helper_lib:
    sys.path.insert(0, helper_lib)

from langywrap.ralph.model_mix import project_model_mix

specs = json.loads({specs_json!r})
print(json.dumps(project_model_mix(Path('.').resolve(), specs), sort_keys=True))
PY"""
    result = run_project(project, command, timeout=120)
    write_command_result(out_dir / "model_mix.raw.txt", result)
    obj = extract_json_object(result.stdout) if result.ok else None
    if obj is None:
        obj = {
            "ok": False,
            "error": result.stderr.strip() or result.stdout.strip() or "failed to collect model mix",
            "replacements": replacement_specs,
        }
    else:
        obj["ok"] = True
    write_text(out_dir / "model_mix.json", json.dumps(obj, indent=2, sort_keys=True) + "\n")
    return obj


def model_mix_helper_lib(project: ProjectRef) -> str:
    """Return langywrap/lib path to put on sys.path for direct config loading."""
    if project.is_remote:
        return str(PurePosixPath(project.path).parent / "langywrap" / "lib")
    return str(REPO_ROOT / "lib")


def inspect_project(
    project: ProjectRef,
    root_out: Path,
    args: argparse.Namespace,
    previous_state: dict[str, Any],
    inspected_at: str,
) -> dict[str, Any]:
    out_dir = root_out / project.name
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[inspect] {project.name}: {project.raw_location}")

    fast_mode = args.status_only or args.progress_only
    dry_report = dry_run(project, out_dir, args.skip_dry_run or fast_mode)
    git_state = collect_git_state(project, out_dir)
    progress = annotate_progress(project, git_state, previous_state)
    state_paths = collect_state_files(project, out_dir, dry_report)
    tmux_status = collect_tmux(project, out_dir, args.tmux_lines)
    replacement_specs = extract_replace_model_specs(tmux_status)
    model_mix = collect_model_mix(project, out_dir, replacement_specs)

    artifacts: list[str] = []
    if not fast_mode:
        collect_commits(project, out_dir, args.commits)
        artifacts = collect_artifacts(project, out_dir, dry_report, args.artifacts)

    summary = {
        "project": project.name,
        "location": project.raw_location,
        "is_remote": project.is_remote,
        "inspected_at": inspected_at,
        "mode": (
            "progress-only"
            if args.progress_only
            else "status-only"
            if args.status_only
            else "deep"
        ),
        "git": git_state,
        "progress": progress,
        "tasks_md": state_paths["tasks_md"],
        "progress_md": state_paths["progress_md"],
        "artifact_count": len(artifacts),
        "tmux": tmux_status,
        "model_mix": model_mix,
    }
    write_text(out_dir / "summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def print_summary_table(summaries: list[dict[str, Any]]) -> None:
    print(
        "\nproject         mode           git            progress      "
        "tmux                         models                     tasks.md"
    )
    print(
        "--------------  -------------  -------------  ------------  "
        "---------------------------  -------------------------  ----------------"
    )
    for summary in summaries:
        if "error" in summary:
            print(f"{summary.get('project', '?'):<14}  error        {summary['error']}")
            continue
        git_state = summary.get("git") or {}
        progress = summary.get("progress") or {}
        git_label = git_state.get("short_commit") or "unknown"
        if git_state.get("dirty"):
            git_label = f"{git_label}+dirty"
        if not git_state.get("ok", True):
            git_label = "git-error"
        if not progress.get("has_baseline"):
            progress_label = "new-baseline"
        else:
            progress_label = "advanced" if progress.get("advanced_since_last") else "unchanged"
        tmux = summary.get("tmux") or {}
        tmux_label = f"{tmux.get('session', '?')}:{tmux.get('state', '?')}"
        if tmux.get("error"):
            tmux_label = f"{tmux_label}+error"
        model_label = format_model_mix(summary.get("model_mix") or {})
        tasks = summary.get("tasks_md") or "missing"
        print(
            f"{summary['project']:<14}  {summary.get('mode', '?'):<13}  "
            f"{git_label:<13}  {progress_label:<12}  {tmux_label:<27}  "
            f"{model_label:<25}  {tasks}"
        )


def format_model_mix(model_mix: dict[str, Any]) -> str:
    if not model_mix:
        return "models: n/a"
    if model_mix.get("ok") is False:
        return "models: error"
    providers = model_mix.get("providers")
    if not isinstance(providers, dict):
        return "models: n/a"
    parts = []
    labels = [("anthropic", "anth"), ("openai", "oa"), ("other", "oth")]
    for provider, label in labels:
        data = providers.get(provider) or {}
        percent = data.get("percent", 0)
        parts.append(f"{label} {percent:g}%")
    return "/".join(parts)


def print_model_details(summaries: list[dict[str, Any]]) -> None:
    print("\nmodel details")
    print("-------------")
    for summary in summaries:
        if "error" in summary:
            continue
        project = summary.get("project", "?")
        model_mix = summary.get("model_mix") or {}
        print(f"\n{project}: {format_model_mix(model_mix)}")
        if model_mix.get("ok") is False:
            print(f"  error: {model_mix.get('error', 'unknown')}")
            continue
        replacements = model_mix.get("replacements") or []
        if replacements:
            print(f"  replacements: {', '.join(str(item) for item in replacements)}")
        source = model_mix.get("source")
        if source:
            print(f"  source: {source}")
        slots = model_mix.get("slots") or []
        if not slots:
            print("  slots: none")
            continue
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            step = slot.get("step", "?")
            role = slot.get("role", "primary")
            model = slot.get("model", "?")
            provider = provider_label(str(model))
            extra = []
            if slot.get("pipeline") is False:
                extra.append("non-pipeline")
            if slot.get("when_cycle"):
                extra.append("when=" + ",".join(str(x) for x in slot["when_cycle"]))
            suffix = f" ({'; '.join(extra)})" if extra else ""
            print(f"  {step:<18} {role:<8} {provider:<9} {model}{suffix}")


def provider_label(model: str) -> str:
    normalized = model.strip().lower()
    if (
        normalized.startswith("claude-")
        or normalized.startswith("anthropic/")
        or normalized.startswith("openrouter/anthropic/")
    ):
        return "anthropic"
    if (
        normalized.startswith("openai/")
        or normalized.startswith("gpt-")
        or normalized.startswith("o1-")
        or normalized.startswith("o3-")
        or normalized.startswith("o4-")
        or normalized.startswith("openrouter/openai/")
    ):
        return "openai"
    return "other"


def print_progress_table(summaries: list[dict[str, Any]]) -> None:
    print("\nproject         previous       current        status")
    print("--------------  -------------  -------------  ------------")
    for summary in summaries:
        if "error" in summary:
            print(
                f"{summary.get('project', '?'):<14}  error          "
                f"error          {summary['error']}"
            )
            continue
        git_state = summary.get("git") or {}
        progress = summary.get("progress") or {}
        previous = progress.get("previous_short_commit") or "none"
        current = git_state.get("short_commit") or "unknown"
        if not progress.get("has_baseline"):
            status = "new-baseline"
        else:
            status = "advanced" if progress.get("advanced_since_last") else "unchanged"
        print(f"{summary['project']:<14}  {previous:<13}  {current:<13}  {status}")


def build_latest_state(
    summaries: list[dict[str, Any]], inspected_at: str, bundle: Path
) -> dict[str, Any]:
    projects: dict[str, Any] = {}
    for summary in summaries:
        if "error" in summary:
            continue
        projects[summary["project"]] = {
            "inspected_at": inspected_at,
            "location": summary.get("location"),
            "is_remote": summary.get("is_remote"),
            "mode": summary.get("mode"),
            "git": summary.get("git"),
            "tmux": summary.get("tmux"),
            "model_mix": summary.get("model_mix"),
            "tasks_md": summary.get("tasks_md"),
            "progress_md": summary.get("progress_md"),
            "bundle": str(bundle),
        }
    return {"inspected_at": inspected_at, "bundle": str(bundle), "projects": projects}


def merge_latest_state(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    merged = dict(previous)
    previous_projects = previous.get("projects")
    current_projects = current.get("projects")
    projects = dict(previous_projects) if isinstance(previous_projects, dict) else {}
    if isinstance(current_projects, dict):
        projects.update(current_projects)
    merged.update(current)
    merged["projects"] = projects
    return merged


def main() -> int:
    args = parse_args()
    env = load_env(args.env_file)
    projects = load_projects(env, args.projects)
    if not projects:
        raise SystemExit("no projects configured")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    inspected_at = datetime.now().isoformat(timespec="seconds")
    root_out = args.out_dir / stamp
    root_out.mkdir(parents=True, exist_ok=True)
    latest_state_path = args.out_dir / "latest_state.json"
    previous_state = read_json_file(latest_state_path)

    summaries = []
    for project in projects:
        try:
            summaries.append(inspect_project(project, root_out, args, previous_state, inspected_at))
        except Exception as exc:  # noqa: BLE001 - continue collecting other projects.
            error = {"project": project.name, "error": str(exc)}
            summaries.append(error)
            write_text(root_out / project.name / "error.txt", str(exc) + "\n")
            print(f"[inspect] {project.name}: ERROR {exc}", file=sys.stderr)

    write_text(root_out / "summary.json", json.dumps(summaries, indent=2, sort_keys=True) + "\n")
    current_state = build_latest_state(summaries, inspected_at, root_out)
    write_text(
        root_out / "git_state.json",
        json.dumps(current_state, indent=2, sort_keys=True) + "\n",
    )
    if not args.no_update_latest:
        write_text(
            latest_state_path,
            json.dumps(merge_latest_state(previous_state, current_state), indent=2, sort_keys=True)
            + "\n",
        )
    if args.progress_only:
        print_progress_table(summaries)
    else:
        print_summary_table(summaries)
        if args.model_details:
            print_model_details(summaries)
    print(f"[inspect] wrote bundle: {root_out}")
    if not args.no_update_latest:
        print(f"[inspect] updated baseline: {latest_state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
