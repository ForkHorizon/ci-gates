"""Run serial AI checks after ordinary checks complete."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from ci_scope_models import CheckSpec


@dataclass(frozen=True)
class AIContext:
    cancelled: threading.Event
    run_check: Callable


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
