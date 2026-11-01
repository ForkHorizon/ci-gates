"""Bounded execution helpers shared by CI Scope checks and explanations."""

from __future__ import annotations

from contextlib import suppress
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from check_reporting import BoundedLog


CANCELLED = threading.Event()


def _wait_process(process: subprocess.Popen[str], deadline: float, timeout: int, log: BoundedLog) -> tuple[int, str]:
    while True:
        if CANCELLED.is_set():
            terminate_process(process)
            output, _ = process.communicate()
            log.write(output or "")
            return 130, "cancelled"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            terminate_process(process)
            output, _ = process.communicate()
            log.write(output or "")
            return 124, f"timed out after {timeout}s"
        try:
            output, _ = process.communicate(timeout=min(1, remaining))
        except subprocess.TimeoutExpired:
            continue
        log.write(output or "")
        return process.returncode, "completed"


def _run_command(command: list[str], cwd: Path, deadline: float, timeout: int, log: BoundedLog) -> tuple[int, str]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=(os.name != "nt"),
        text=True,
    )
    return _wait_process(process, deadline, timeout, log)


def run_process(
    commands: list[list[str]], cwd: Path, timeout: int, log_path: Path, *, preserve_paths=False
) -> tuple[int, str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    deadline = started + timeout
    with log_path.open("w", encoding="utf-8") as raw_log:
        log = BoundedLog(raw_log, preserve_paths=preserve_paths)
        for command in commands:
            if CANCELLED.is_set():
                return 130, "cancelled"
            code, detail = _run_command(command, cwd, deadline, timeout, log)
            if code != 0:
                return code, detail if code in {124, 130} else f"command failed: {command[0]}"
    return code, f"{time.monotonic() - started:.3f}s"


def terminate_process(process: subprocess.Popen[object]) -> None:
    if os.name == "nt":
        if process.poll() is None:
            process.terminate()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=2)
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
