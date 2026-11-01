import argparse
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ci_scope_adapters import commands_for
from ci_scope_models import ResolvedManifest
from ci_scope_process import run_process


@dataclass(frozen=True)
class RunContext:
    args: argparse.Namespace
    manifest: ResolvedManifest
    gates: Path
    output: Path
    resource_locks: dict[str, threading.Lock]


def run_check(check, context: RunContext) -> dict:
    started = time.monotonic()
    log_path = context.output / "logs" / f"{check.id}.log"
    try:
        code, detail = _run_locked(check, context, log_path)
        return _result(check, context, log_path, (code, detail), started)
    except (OSError, ValueError) as error:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.touch(exist_ok=True)
        return {
            "id": check.id,
            "type": check.type,
            "status": "infra_error",
            "required": check.required,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "detail": str(error),
            "log": str(log_path.relative_to(context.output)),
        }


def _run_locked(check, context: RunContext, log_path: Path):
    args = context.args
    commands = commands_for(check, context.manifest.root, context.gates, (args.base, args.head), args.event)
    mode = getattr(args, "mode", None)
    if mode and check.type in {"code-linter", "swift-quality"}:
        commands = [command for command in commands if "policy_signature_guard.py" not in " ".join(command)]
        for command in commands:
            if "--mode" in command:
                command[command.index("--mode") + 1] = mode
    locks = [context.resource_locks[name] for name in sorted(check.resources)]
    for lock in locks:
        lock.acquire()
    try:
        return run_process(
            commands,
            context.manifest.root / check.workdir,
            args.timeout,
            log_path,
            preserve_paths=getattr(args, "quiet", False),
        )
    finally:
        for lock in reversed(locks):
            lock.release()


def _result(check, context, log_path, outcome, started):
    code, detail = outcome
    status = "passed" if code == 0 else ("timed_out" if code == 124 else ("cancelled" if code == 130 else "failed"))
    return {
        "id": check.id,
        "type": check.type,
        "status": status,
        "required": check.required,
        "exit_code": code,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "detail": detail,
        "log": str(log_path.relative_to(context.output)),
    }
