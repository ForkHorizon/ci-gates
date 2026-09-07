#!/usr/bin/env python3
"""Run a trusted CI Scope manifest in one prepared workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ci_scope_manifest import ManifestError, CheckSpec, ResolvedManifest, resolve_manifest_file
from check_reporting import BoundedLog, write_report


ADAPTERS = {"code-linter", "python-quality", "go-quality", "swift-quality", "swift-compile", "slop-review"}
DEFAULT_AI_MODEL = "qwen3-coder:30b-a3b-q4_K_M"
CANCELLED = threading.Event()
GATE_NAMES = {
    "code-linter": "Code Linter",
    "python-quality": "Python Quality Gate",
    "go-quality": "Go Quality Gate",
    "swift-quality": "Swift Quality Gate",
    "swift-compile": "Swift Compile Gate",
}


def commands_for(check: CheckSpec, root: Path, gates: Path, base: str, head: str, event: str = "pull_request") -> list[list[str]]:
    python = sys.executable
    config = check.config
    if check.type == "code-linter":
        mode = str(check.params.get("mode", "auto"))
        if mode == "auto":
            mode = "changed" if event in {"pull_request", "merge_group"} else "all"
        command = [python, str(gates / "scripts/code-linter.py"), "--root", str(root)]
        command += ["--mode", mode]
        if mode == "changed":
            command += ["--base", base, "--head", head]
        if config:
            command += ["--config", config]
        coverage_mode = check.params.get("coverage_mode")
        if coverage_mode:
            command += ["--coverage-mode", str(coverage_mode)]
        guard = [
            python,
            str(gates / "scripts/policy_signature_guard.py"),
            "--root",
            str(root),
            "--base",
            base,
            "--head",
            head,
            "--allowed-signers",
            str(gates / "configs/allowed_signers"),
        ]
        return [guard, command] if mode == "changed" else [command]
    if check.type == "python-quality":
        workdir = root / check.workdir
        has_config = (workdir / "ruff.toml").is_file() or (workdir / ".ruff.toml").is_file()
        pyproject = workdir / "pyproject.toml"
        has_config = has_config or (pyproject.is_file() and "[tool.ruff" in pyproject.read_text(encoding="utf-8"))
        config_args = [] if has_config else ["--config", str(gates / "configs/ruff-strict.toml")]
        return [["ruff", "check", *config_args, "."], ["ruff", "format", "--check", *config_args, "."]]
    if check.type == "go-quality":
        return [
            ["go", "mod", "download"],
            ["go", "vet", "./..."],
            [sys.executable, "-c", "import subprocess,sys; files=subprocess.check_output(['gofmt','-l','.'], text=True); print(files, end=''); sys.exit(bool(files))"],
            ["golangci-lint", "run", "./..."],
        ]
    if check.type == "swift-quality":
        prefix = [python, str(gates / "scripts/swift-quality-gate.py"), "--root", str(root)]
        if config:
            prefix += ["--config", config]
        mode = "changed" if event in {"pull_request", "merge_group"} else "all"
        commands = []
        if check.params.get("run_build", True):
            commands.append([*prefix, "--stage", "build", "--mode", "all"])
        commands.append([*prefix, "--stage", "format", "--mode", mode, "--base", base, "--head", head])
        commands.append([*prefix, "--stage", "dead-code", "--mode", "all"])
        return commands
    if check.type == "swift-compile":
        command = [python, str(gates / "scripts/swift-compile-gate.py"), "--root", str(root)]
        if config:
            command += ["--config", config]
        return [command]
    if check.type == "slop-review":
        command = [python, str(gates / "scripts/slop-review.py"), "--base", base, "--head", head]
        if config:
            command += ["--config", config]
        command += ["--model", str(check.params.get("model", DEFAULT_AI_MODEL))]
        return [command]
    raise ManifestError(f"unsupported executor adapter: {check.type}")


def run_process(commands: list[list[str]], cwd: Path, timeout: int, log_path: Path) -> tuple[int, str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as raw_log:
        log = BoundedLog(raw_log)
        deadline = time.monotonic() + timeout
        for command in commands:
            if CANCELLED.is_set():
                return 130, "cancelled"
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=(os.name != "nt"),
                text=True,
            )
            try:
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
                        log.write(output or "")
                        code = process.returncode
                        break
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                pass
            if code != 0:
                return code, f"command failed: {command[0]}"
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
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # The leader can exit while descendants remain in the session's process
    # group; always finish the group cleanup after the graceful wait.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


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


def run_check(check: CheckSpec, args: argparse.Namespace, manifest: ResolvedManifest, gates: Path, output: Path,
              resource_locks: dict[str, threading.Lock] | None = None) -> dict:
    started = time.monotonic()
    log_path = output / "logs" / f"{check.id}.log"
    try:
        commands = commands_for(check, manifest.root, gates, args.base, args.head, getattr(args, "event", "pull_request"))
        locks = [resource_locks[name] for name in sorted(check.resources)] if resource_locks else []
        for lock in locks:
            lock.acquire()
        try:
            code, detail = run_process(commands, manifest.root / check.workdir, args.timeout, log_path)
        finally:
            for lock in reversed(locks):
                lock.release()
        status = "passed" if code == 0 else ("timed_out" if code == 124 else ("cancelled" if code == 130 else "failed"))
        return {"id": check.id, "type": check.type, "status": status, "required": check.required, "exit_code": code, "duration_ms": round((time.monotonic() - started) * 1000), "detail": detail, "log": str(log_path.relative_to(output))}
    except (OSError, ValueError) as error:
        return {"id": check.id, "type": check.type, "status": "infra_error", "required": check.required, "duration_ms": round((time.monotonic() - started) * 1000), "detail": str(error)}


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


def _run(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    manifest_path = args.config.resolve()
    manifest = resolve_manifest_file(manifest_path, root=root, event=args.event)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    gates = Path(args.gates).resolve()
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if args.validate_only:
        print(json.dumps({"version": manifest.version, "checks": [check.id for check in manifest.active_checks], "manifest_sha256": digest}, indent=2))
        return 0

    results: dict[str, dict] = {}
    events: list[dict] = []
    resource_locks = {resource: threading.Lock() for check in manifest.active_checks for resource in check.resources}
    ordinary = [check for check in manifest.active_checks if not check.ai]
    ai = [check for check in manifest.active_checks if check.ai]
    ordinary_started = time.monotonic()
    while len(results) < len(ordinary):
        if CANCELLED.is_set():
            for check in ordinary:
                if check.id not in results:
                    results[check.id] = {"id": check.id, "type": check.type, "status": "cancelled", "required": check.required, "reason": "run cancelled"}
            break
        ready = ready_checks(ordinary, results)
        if not ready:
            break
        with ThreadPoolExecutor(max_workers=min(args.parallel, len(ready))) as pool:
            futures = {pool.submit(run_check, check, args, manifest, gates, output, resource_locks): check for check in ready}
            for future in as_completed(futures):
                result = future.result()
                results[result["id"]] = result
                events.append({"step": result["id"], "status": result["status"]})
    ordinary_ms = round((time.monotonic() - ordinary_started) * 1000)
    ai_started = time.monotonic()
    for check in ordinary:
        if CANCELLED.is_set():
            break
        if check.type not in GATE_NAMES or results.get(check.id, {}).get("status") not in {"failed", "timed_out"}:
            continue
        model = check.params.get("explain_model", DEFAULT_AI_MODEL)
        if not model:
            continue
        log_path = output / "logs" / f"{check.id}.log"
        command = [
            sys.executable,
            str(gates / "scripts/explain-failure.py"),
            "--log",
            str(log_path),
            "--gate",
            GATE_NAMES[check.type],
            "--model",
            str(model),
            "--base",
            args.base,
        ]
        code, detail = run_process([command], manifest.root, args.timeout, output / "logs" / f"{check.id}-explain.log")
        events.append({"step": f"{check.id}-explain", "status": "passed" if code == 0 else "infra_error", "detail": detail})
    for check in ai:
        if CANCELLED.is_set():
            results[check.id] = {"id": check.id, "type": check.type, "status": "cancelled", "required": check.required, "reason": "run cancelled"}
            continue
        if any(results.get(dependency, {}).get("status") != "passed" for dependency in check.depends_on):
            results[check.id] = {"id": check.id, "type": check.type, "status": "skipped", "required": check.required, "reason": "dependency failed"}
            continue
        result = run_check(check, args, manifest, gates, output, resource_locks)
        results[check.id] = result
        events.append({"step": check.id, "status": result["status"]})
    ai_ms = round((time.monotonic() - ai_started) * 1000)
    ordered = [results.get(check.id, {"id": check.id, "status": "infra_error", "reason": "not scheduled"}) for check in manifest.active_checks]
    report = {
        "version": 1,
        "run": {
            "repository": os.environ.get("GITHUB_REPOSITORY"),
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "base": args.base,
            "head": args.head,
            "checked_sha": os.environ.get("GITHUB_SHA", args.head),
            "gates_sha": os.environ.get("CI_SCOPE_GATES_SHA"),
            "manifest_sha256": digest,
        },
        "manifest_sha256": digest,
        "event": args.event,
        "base": args.base,
        "head": args.head,
        "checks": ordered,
        "status": "passed" if all(
        result.get("status") == "passed"
        or (result.get("status") == "skipped" and result.get("reason") != "dependency failed")
        or not result.get("required", True)
        for result in ordered
    ) else "failed"}
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
