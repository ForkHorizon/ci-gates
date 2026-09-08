"""Run serial AI checks after ordinary checks complete."""

from __future__ import annotations

import threading
import time
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ci_scope_models import CheckSpec


@dataclass(frozen=True)
class AIContext:
    cancelled: threading.Event
    run_check: Callable


@dataclass(frozen=True)
class ExplanationContext:
    cancelled: threading.Event
    run_process: Callable
    gate_names: Mapping[str, str]
    default_model: str


def run_explanations(
    checks: list[CheckSpec], context: object, results: dict[str, dict], events: list[dict], explanation: ExplanationContext
) -> None:
    args = context.args
    for check in checks:
        if explanation.cancelled.is_set():
            break
        if check.type not in explanation.gate_names or results.get(check.id, {}).get("status") not in {"failed", "timed_out"}:
            continue
        model = check.params.get("explain_model", explanation.default_model)
        if not model:
            continue
        log_path = context.output / "logs" / f"{check.id}.log"
        command = [
            sys.executable,
            str(context.gates / "scripts/explain-failure.py"),
            "--log", str(log_path), "--gate", explanation.gate_names[check.type],
            "--model", str(model), "--base", args.base,
        ]
        code, detail = explanation.run_process(
            [command], context.manifest.root, args.timeout, context.output / "logs" / f"{check.id}-explain.log"
        )
        events.append({"step": f"{check.id}-explain", "status": "passed" if code == 0 else "infra_error", "detail": detail})


def run_ai(
    checks: list[CheckSpec],
    context: object,
    results: dict[str, dict],
    events: list[dict],
    ai_context: AIContext,
) -> int:
    started = time.monotonic()
    for check in checks:
        if ai_context.cancelled.is_set():
            results[check.id] = {
                "id": check.id,
                "type": check.type,
                "status": "cancelled",
                "required": check.required,
                "reason": "run cancelled",
            }
            continue
        if any(results.get(dependency, {}).get("status") != "passed" for dependency in check.depends_on):
            results[check.id] = {
                "id": check.id,
                "type": check.type,
                "status": "skipped",
                "required": check.required,
                "reason": "dependency failed",
            }
            continue
        result = ai_context.run_check(check, context)
        results[check.id] = result
        events.append({"step": check.id, "status": result["status"]})
    return round((time.monotonic() - started) * 1000)
