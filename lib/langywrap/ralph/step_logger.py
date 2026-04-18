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
import threading
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

            try:
                size = log_path.stat().st_size
            except FileNotFoundError:
                size = 0

            delta = size - last_size
            if delta > 0:
                saw_live_output = True

            if size == 0:
                self.log(f"  [heartbeat {minutes}m] still running — no live step-log output yet")
            elif delta == 0 and saw_live_output and elapsed_s > self.HEARTBEAT_INTERVAL_S:
                self.log(
                    f"  [heartbeat {minutes}m] WARNING live output stalled — "
                    f"{step_name} may be hung ({size:,}B)"
                )
            else:
                self.log(f"  [heartbeat {minutes}m] still running — {size:,}B (+{delta:,}B)")
            last_size = size
