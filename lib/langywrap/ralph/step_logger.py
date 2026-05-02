"""
langywrap.ralph.step_logger — Operator-friendly logging for ralph loops.

Merges the best of the old bash ralph loop (timestamps on every line,
per-step log files, heartbeat monitoring, master session log, failure tails)
with langywrap's Unicode step banners and token-stats tables.

Usage::

    from langywrap.ralph.step_logger import StepLogger

    logger = StepLogger(logs_dir=state_dir / "logs")
    logger.log("RalphLoop starting")

    log_path = logger.open_step(
        "orient", model="nvidia/google/gemma-4-31b-it",
        engine="opencode", timeout_minutes=30,
    )
    logger.start_heartbeat("orient", log_path)
    # ... AI runs ...
    logger.stop_heartbeat()
    logger.close_step("orient", output=text, success=True, duration=42.3)

    logger.close()
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from datetime import datetime
from pathlib import Path


class StepLogger:
    """
    Timestamped, file-backed logger for a ralph loop run.

    Features
    --------
    - Every ``log()`` call is prefixed with ``[YYYY-MM-DD HH:MM:SS] [ralph]``
      and written to both stdout and a persistent master log file.
    - ``open_step()`` creates a per-step log file and appends the log path
      + ``tail -f`` monitor command to the step banner.
    - ``start_heartbeat()`` spawns a daemon thread that prints a heartbeat
      every 5 minutes while an AI step is running.  The heartbeat reports
      elapsed time and whether the step log file is growing.
    - ``close_step()`` stops the heartbeat, writes the AI output to the
      per-step log file, and prints a completion/failure line.  On failure
      it also tails the last 10 lines of output.
    - ``close()`` flushes and closes the master log file handle.
    """

    TAG = "ralph"
    HEARTBEAT_INTERVAL_S = 300  # 5 minutes

    def __init__(self, logs_dir: Path) -> None:
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.master_log: Path = logs_dir / f"ralph_master_{ts}.log"
        # line-buffered so every write flushes immediately
        self._master_fh = self.master_log.open("a", encoding="utf-8", buffering=1)

        self._heartbeat_thread: threading.Thread | None = None
        self._stop_hb: threading.Event = threading.Event()
        # Most recently opened per-step log (used by close_step)
        self._current_step_log: Path | None = None
        self._hb_pid_baseline: set[int] = set()
        self._hb_cpu_ticks: dict[int, int] = {}
        self._hb_last_proc_activity: float = 0.0

    # ------------------------------------------------------------------
    # Primary log method — replaces runner._log
    # ------------------------------------------------------------------

    def log(self, msg: str) -> None:
        """Emit a timestamped message to stdout and the master log file.

        Multi-line messages are split so every line carries its own timestamp.
        Empty messages emit a single blank timestamped line.
        """
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for line in msg.splitlines() or [""]:
            out = f"[{ts}] [{self.TAG}] {line}"
            print(out)
            with contextlib.suppress(OSError):  # disk full — don't crash the loop
                self._master_fh.write(out + "\n")

    # ------------------------------------------------------------------
    # Per-step log lifecycle
    # ------------------------------------------------------------------

    def open_step(
        self,
        step_name: str,
        *,
        model: str = "",
        engine: str = "",
        tools: str = "",
        timeout_minutes: int = 30,
    ) -> Path:
        """Create a per-step log file and emit the extra banner fields.

        Called *after* the main ``┌── STEP: ... ──`` lines have been
        emitted by ``run_cycle``, so this appends Engine / Tools / Log /
        Monitor fields before the step actually runs.

        Returns the path to the per-step log file (created but empty).
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = self.logs_dir / f"{ts}_{step_name}.log"
        log_path.touch()  # create now so `tail -f` can start immediately
        self._current_step_log = log_path

        if engine and engine != "auto":
            self.log(f"  │   Engine:  {engine}")
        if tools:
            self.log(f"  │   Tools:   {tools}")
        self.log(f"  │   Log:     {log_path}")
        self.log(f"  │   Monitor: tail -f {log_path}")

        return log_path

    def start_heartbeat(self, step_name: str, log_path: Path) -> None:
        """Spawn a daemon thread that prints a heartbeat every 5 minutes.

        The heartbeat reports elapsed time and any live log growth.

        Important: the per-step log is typically written only when the step
        closes, so a 0B file does not imply a hang. We only warn when a log
        file exists and had prior live growth that then stalls.
        """
        self._hb_pid_baseline = self._descendant_pids(os.getpid())
        self._hb_cpu_ticks = {}
        self._hb_last_proc_activity = time.monotonic()
        self._stop_hb.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(step_name, log_path),
            daemon=True,
            name=f"ralph-heartbeat-{step_name}",
        )
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        """Signal the heartbeat thread to stop and wait for it to exit."""
        self._stop_hb.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5)
            self._heartbeat_thread = None

    def close_step(
        self,
        step_name: str,
        output: str,
        *,
        success: bool = True,
        duration: float = 0.0,
    ) -> None:
        """Finish a step: stop heartbeat, write log, emit completion line.

        On failure, also tails the last 10 lines of output so the operator
        can see what went wrong without opening the log file.
        """
        self.stop_heartbeat()

        # Write full AI output to per-step log
        if self._current_step_log is not None and output:
            with contextlib.suppress(OSError):
                self._current_step_log.write_text(output, encoding="utf-8")

        size_b = len(output.encode("utf-8"))
        dur_str = f" in {duration:.1f}s" if duration > 0 else ""
        status = "COMPLETED" if success else "FAILED"
        self.log(f"  [{step_name}] {status} ({size_b:,}B{dur_str})")

        if not success and output:
            tail = output.splitlines()[-10:]
            self.log(f"  [{step_name}] Last output:")
            for line in tail:
                self.log(f"    {line}")

    # ------------------------------------------------------------------
    # Session teardown
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Stop any running heartbeat and close the master log file handle."""
        self.stop_heartbeat()
        with contextlib.suppress(OSError):
            self._master_fh.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _heartbeat_loop(self, step_name: str, log_path: Path) -> None:
        """Background heartbeat: emits a progress line every HEARTBEAT_INTERVAL_S."""
        elapsed_s = 0
        last_size = 0
        saw_live_output = False

        while not self._stop_hb.wait(timeout=self.HEARTBEAT_INTERVAL_S):
            elapsed_s += self.HEARTBEAT_INTERVAL_S
            minutes = elapsed_s // 60
            proc_hint = self._subprocess_hint()

            try:
                size = log_path.stat().st_size
            except FileNotFoundError:
                size = 0

            delta = size - last_size
            if delta > 0:
                saw_live_output = True

            if size == 0:
                if proc_hint:
                    self.log(f"  [heartbeat {minutes}m] still running — {proc_hint}")
                else:
                    self.log(
                        f"  [heartbeat {minutes}m] still running — no live step-log output yet"
                    )
            elif delta == 0 and saw_live_output and elapsed_s > self.HEARTBEAT_INTERVAL_S:
                if proc_hint and (
                    "waiting on subprocesses" in proc_hint or "likely waiting" in proc_hint
                ):
                    self.log(
                        f"  [heartbeat {minutes}m] still running — no step-log growth; "
                        f"{proc_hint} ({size:,}B)"
                    )
                else:
                    self.log(
                        f"  [heartbeat {minutes}m] WARNING live output stalled — "
                        f"{step_name} may be hung ({size:,}B)"
                    )
                    if proc_hint:
                        self.log(f"  [heartbeat {minutes}m] hint: {proc_hint}")
            else:
                msg = f"  [heartbeat {minutes}m] still running — {size:,}B (+{delta:,}B)"
                if delta == 0 and proc_hint:
                    msg = f"{msg}; {proc_hint}"
                self.log(msg)
            last_size = size

    def _subprocess_hint(self) -> str:
        snapshots = self._snapshot_descendants()
        if not snapshots:
            return ""

        now = time.monotonic()
        active = False
        current_ticks: dict[int, int] = {}
        summary: list[str] = []

        for pid, name, state, cpu_ticks in snapshots:
            prev = self._hb_cpu_ticks.get(pid)
            current_ticks[pid] = cpu_ticks
            if prev is None or cpu_ticks > prev:
                active = True
            if len(summary) < 3:
                summary.append(f"{name}[{pid}:{state}]")

        self._hb_cpu_ticks = current_ticks
        if active:
            self._hb_last_proc_activity = now
            return f"waiting on subprocesses ({', '.join(summary)})"

        idle_m = int((now - self._hb_last_proc_activity) // 60)
        if idle_m >= 10:
            return f"subprocesses appear idle for {idle_m}m ({', '.join(summary)})"
        return f"subprocesses alive, likely waiting ({', '.join(summary)})"

    def _snapshot_descendants(self) -> list[tuple[int, str, str, int]]:
        rows: list[tuple[int, str, str, int]] = []
        seen = set(self._hb_pid_baseline)
        queue = list(self._descendant_pids(os.getpid()))
        while queue:
            pid = queue.pop()
            if pid in seen:
                continue
            seen.add(pid)
            snap = self._read_proc_snapshot(pid)
            if snap is None:
                continue
            rows.append(snap)
            queue.extend(self._children_of(pid))
        return rows

    def _descendant_pids(self, root_pid: int) -> set[int]:
        out: set[int] = set()
        queue = [root_pid]
        while queue:
            pid = queue.pop()
            for child in self._children_of(pid):
                if child in out:
                    continue
                out.add(child)
                queue.append(child)
        return out

    def _children_of(self, pid: int) -> list[int]:
        path = Path(f"/proc/{pid}/task/{pid}/children")
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError:
            return []
        if not raw:
            return []
        children: list[int] = []
        for token in raw.split():
            with contextlib.suppress(ValueError):
                children.append(int(token))
        return children

    def _read_proc_snapshot(self, pid: int) -> tuple[int, str, str, int] | None:
        stat_path = Path(f"/proc/{pid}/stat")
        cmd_path = Path(f"/proc/{pid}/cmdline")
        try:
            stat = stat_path.read_text(encoding="utf-8")
        except OSError:
            return None

        close_idx = stat.rfind(")")
        if close_idx == -1:
            return None
        rest = stat[close_idx + 2 :].split()
        if len(rest) < 13:
            return None

        state = rest[0]
        with contextlib.suppress(ValueError):
            cpu_ticks = int(rest[11]) + int(rest[12])
            name = "proc"
            with contextlib.suppress(OSError):
                cmdline = (
                    cmd_path.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace")
                )
                cmdline = cmdline.strip()
                if cmdline:
                    name = Path(cmdline.split()[0]).name
            return (pid, name, state, cpu_ticks)
        return None
