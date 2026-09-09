#!/usr/bin/env python3
"""Run a trusted CI Scope manifest in one prepared workspace."""

from __future__ import annotations

import argparse
from contextlib import suppress
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from ci_scope_adapters import DEFAULT_AI_MODEL, commands_for
from ci_scope_ai import AIContext, ExplanationContext, run_ai, run_explanations
from ci_scope_manifest import ManifestError, resolve_manifest_file
from ci_scope_models import CheckSpec, ResolvedManifest
from check_reporting import BoundedLog, write_report
from ci_scope_report import build_report
from policy_preflight import PolicyError, preflight


ADAPTERS = {"code-linter", "python-quality", "go-quality", "swift-quality", "swift-compile", "slop-review"}
CANCELLED = threading.Event()
GATE_NAMES = {
    "code-linter": "Code Linter",
    "python-quality": "Python Quality Gate",
    "go-quality": "Go Quality Gate",
    "swift-quality": "Swift Quality Gate",
    "swift-compile": "Swift Compile Gate",
}


@dataclass(frozen=True)
class RunContext:
    args: argparse.Namespace
    manifest: ResolvedManifest
    gates: Path
    output: Path
    resource_locks: dict[str, threading.Lock]


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


def run_process(commands: list[list[str]], cwd: Path, timeout: int, log_path: Path) -> tuple[int, str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    deadline = started + timeout
    with log_path.open("w", encoding="utf-8") as raw_log:
        log = BoundedLog(raw_log)
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
    # The leader can exit while descendants remain in the session's process
    # group; always finish the group cleanup after the graceful wait.
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)


def ready_checks(checks: list[CheckSpec], results: dict[str, dict]) -> list[CheckSpec]:
    ready = []
    for check in checks:
        if check.id in results:
            continue
        if all(dependency in results for dependency in check.depends_on):
            if any(results[dependency]["status"] not in {"passed"} for dependency in check.depends_on):
                results[check.id] = {
                    "id": check.id,
                    "type": check.type,
                    "status": "skipped",
                    "required": check.required,
                    "reason": "dependency failed",
                }
            else:
                ready.append(check)
    return ready


def run_check(check: CheckSpec, context: RunContext) -> dict:
    started = time.monotonic()
    log_path = context.output / "logs" / f"{check.id}.log"
    try:
        args = context.args
        commands = commands_for(check, context.manifest.root, context.gates, (args.base, args.head), args.event)
        locks = [context.resource_locks[name] for name in sorted(check.resources)]
        for lock in locks:
            lock.acquire()
        try:
            code, detail = run_process(commands, context.manifest.root / check.workdir, args.timeout, log_path)
        finally:
            for lock in reversed(locks):
                lock.release()
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
    except (OSError, ValueError) as error:
        return {
            "id": check.id,
            "type": check.type,
            "status": "infra_error",
            "required": check.required,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "detail": str(error),
        }


def run(args: argparse.Namespace) -> int:
    CANCELLED.clear()
    previous_handlers = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, lambda _signum, _frame: CANCELLED.set())
    try:
        return _run(args)
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def _run_ordinary(checks: list[CheckSpec], context: RunContext, results: dict[str, dict], events: list[dict]) -> int:
    started = time.monotonic()
    while len(results) < len(checks):
        if CANCELLED.is_set():
            for check in checks:
                if check.id not in results:
                    results[check.id] = {
                        "id": check.id,
                        "type": check.type,
                        "status": "cancelled",
                        "required": check.required,
                        "reason": "run cancelled",
                    }
            break
        ready = ready_checks(checks, results)
        if not ready:
            break
        with ThreadPoolExecutor(max_workers=min(context.args.parallel, len(ready))) as pool:
            futures = {pool.submit(run_check, check, context): check for check in ready}
            for future in as_completed(futures):
                result = future.result()
                results[result["id"]] = result
                events.append({"step": result["id"], "status": result["status"]})
    return round((time.monotonic() - started) * 1000)


def _run(args: argparse.Namespace) -> int:
    policy_path = getattr(args, "policy", None)
    if policy_path is not None:
        policy_result = preflight(
            args.root,
            policy_path,
            repository=getattr(args, "policy_repository", None),
            branch=getattr(args, "policy_branch", None),
            base_sha=getattr(args, "policy_base_sha", None),
            require_signature=not getattr(args, "allow_unsigned_policy", False),
            allowed_signers=getattr(args, "allowed_signers", None),
        )
        if not policy_result.passed:
            raise PolicyError(f"{policy_result.status}: {policy_result.reason}")
    manifest_path = args.config.resolve()
    manifest = resolve_manifest_file(manifest_path, root=args.root.resolve(), event=args.event)
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if args.validate_only:
        print(
            json.dumps(
                {
                    "version": manifest.version,
                    "checks": [check.id for check in manifest.active_checks],
                    "manifest_sha256": digest,
                },
                indent=2,
            )
        )
        return 0
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    locks = {resource: threading.Lock() for check in manifest.active_checks for resource in check.resources}
    context = RunContext(args, manifest, Path(args.gates).resolve(), output, locks)
    results: dict[str, dict] = {}
    events: list[dict] = []
    ordinary = [check for check in manifest.active_checks if not check.ai]
    ai = [check for check in manifest.active_checks if check.ai]
    ordinary_ms = _run_ordinary(ordinary, context, results, events)
    ai_started = time.monotonic()
    run_explanations(
        ordinary, context, results, events, ExplanationContext(CANCELLED, run_process, GATE_NAMES, DEFAULT_AI_MODEL)
    )
    run_ai(ai, context, results, events, AIContext(CANCELLED, run_check))
    ai_ms = round((time.monotonic() - ai_started) * 1000)
    report = build_report(args, manifest, digest, results)
    write_report(output, events, report, ordinary_ms=ordinary_ms, ai_ms=ai_ms)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--gates", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--event", default="pull_request")
    parser.add_argument("--base", default="HEAD~1")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        help="Optional signed control-plane policy record; failure blocks execution before manifest loading",
    )
    parser.add_argument("--policy-repository", help="Repository identity expected by the policy record")
    parser.add_argument("--policy-branch", help="Protected branch identity expected by the policy record")
    parser.add_argument("--policy-base-sha", help="Approved base commit expected by the policy record")
    parser.add_argument("--allowed-signers", type=Path, help="OpenSSH allowed signers file for policy verification")
    parser.add_argument(
        "--allow-unsigned-policy",
        action="store_true",
        help="Disable signature verification for local development only",
    )
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    if args.parallel < 1 or args.timeout < 1:
        parser.error("--parallel and --timeout must be positive")
    try:
        return run(args)
    except (ManifestError, OSError, ValueError) as error:
        print(f"ci-scope executor error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
