#!/usr/bin/env python3
"""Run a trusted CI Scope manifest in one prepared workspace."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ci_scope_adapters import DEFAULT_AI_MODEL
from ci_scope_ai import AIContext, ExplanationContext, run_ai, run_explanations
from ci_scope_local import print_quiet, write_compact_result
from ci_scope_manifest import ManifestError
from ci_scope_models import CheckSpec
from ci_scope_process import CANCELLED, run_process
from check_reporting import write_report
from ci_scope_report import build_report
from ci_scope_run_support import prepare_manifest, print_validation
import ci_scope_worker as _worker
from ci_scope_worker import RunContext


def run_check(check: CheckSpec, context: RunContext) -> dict:
    _worker.run_process = run_process
    return _worker.run_check(check, context)


ADAPTERS = {
    "code-linter",
    "python-quality",
    "python-pytest",
    "forbidden-constructs",
    "duplicate-blocks",
    "web-quality",
    "web-test",
    "go-quality",
    "swift-quality",
    "swift-compile",
    "slop-review",
}
GATE_NAMES = {
    "code-linter": "Code Linter",
    "python-quality": "Python Quality Gate",
    "python-pytest": "Python Tests",
    "forbidden-constructs": "Forbidden Constructs",
    "duplicate-blocks": "Duplicate Blocks",
    "web-quality": "Web Quality Gate",
    "web-test": "Web Tests",
    "go-quality": "Go Quality Gate",
    "swift-quality": "Swift Quality Gate",
    "swift-compile": "Swift Compile Gate",
}


def ready_checks(
    checks: list[CheckSpec],
    results: dict[str, dict],
    included_ids: set[str] | None = None,
) -> list[CheckSpec]:
    included_ids = included_ids or {check.id for check in checks}
    ready = []
    for check in checks:
        if check.id in results:
            continue
        dependencies = [dependency for dependency in check.depends_on if dependency in included_ids]
        if all(dependency in results for dependency in dependencies):
            if any(results[dependency]["status"] not in {"passed"} for dependency in dependencies):
                results[check.id] = {
                    "id": check.id,
                    "type": check.type,
                    "status": "skipped",
                    "required": check.required,
                    "duration_ms": 0,
                    "reason": "dependency failed",
                }
            else:
                ready.append(check)
    return ready


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


def _run_ordinary(
    checks: list[CheckSpec],
    context: RunContext,
    results: dict[str, dict],
    events: list[dict],
) -> int:
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
                        "duration_ms": 0,
                        "reason": "run cancelled",
                    }
            break
        ready = ready_checks(checks, results, {check.id for check in checks})
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
    started_at = datetime.now(UTC)
    started = time.monotonic()
    manifest, digest = prepare_manifest(args)
    if args.validate_only:
        print_validation(manifest, digest, args.tier)
        return 0
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    checks = list(manifest.active_checks)
    if args.tier == "fast":
        checks = [check for check in checks if check.speed == "fast"]
    if args.local:
        checks = [check for check in checks if check.type != "slop-review"]
    locks = {resource: threading.Lock() for check in checks for resource in check.resources}
    context = RunContext(args, manifest, Path(args.gates).resolve(), output, locks)
    results: dict[str, dict] = {}
    events: list[dict] = []
    ordinary = [check for check in checks if not check.ai]
    ai = [check for check in checks if check.ai]
    ordinary_ms = _run_ordinary(ordinary, context, results, events)
    ai_started = time.monotonic()
    if not args.local:
        run_explanations(
            ordinary,
            context,
            results,
            events,
            ExplanationContext(CANCELLED, run_process, GATE_NAMES, DEFAULT_AI_MODEL),
        )
        run_ai(ai, context, results, events, AIContext(CANCELLED, run_check))
    ai_ms = round((time.monotonic() - ai_started) * 1000)
    report = build_report(args, manifest, digest, results, checks)
    write_report(output, events, report, timings=(ordinary_ms, ai_ms), preserve_paths=args.quiet)
    finished_at = datetime.now(UTC)
    if args.result_file:
        write_compact_result(args.result_file, report, manifest, args, (started_at, finished_at))
    if args.quiet:
        print_quiet(report, output, round(time.monotonic() - started, 1), args.tail)
    else:
        print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--gates", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--event", default="pull_request")
    parser.add_argument("--base", default="HEAD~1")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--result-file",
        type=Path,
        help="Write a compact local result for the macOS app.",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        help="Optional signed control-plane policy record; failure blocks execution before manifest loading",
    )
    parser.add_argument("--policy-repository", help="Repository identity expected by the policy record")
    parser.add_argument(
        "--policy-branch",
        help="Protected branch identity expected by the policy record",
    )
    parser.add_argument("--policy-base-sha", help="Approved base commit expected by the policy record")
    parser.add_argument(
        "--allowed-signers",
        type=Path,
        help="OpenSSH allowed signers file for policy verification",
    )
    parser.add_argument(
        "--allow-unsigned-policy",
        action="store_true",
        help="Disable signature verification for local development only",
    )
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--tier", choices=("fast", "full"), default="full")
    parser.add_argument("--mode", choices=("all", "changed", "worktree"), default=None)
    parser.add_argument("--validate-only", action="store_true")
    return parser


def _add_policy_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print only a one-line success or failed-check logs.",
    )
    parser.add_argument("--local", action="store_true", help="Disable AI explanations and slop-review.")
    parser.add_argument("--tail", type=int, default=30, help="Number of log lines to print per failure.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    _add_policy_arguments(parser)
    args = parser.parse_args(argv)
    if args.parallel < 1 or args.timeout < 1 or args.tail < 1:
        parser.error("--parallel, --timeout, and --tail must be positive")
    try:
        return run(args)
    except (ManifestError, OSError, ValueError) as error:
        print(f"ci-scope executor error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
