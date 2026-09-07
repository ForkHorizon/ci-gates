"""Build the stable report for a unified CI Scope run."""

from __future__ import annotations

import argparse
import os

from ci_scope_models import ResolvedManifest


def build_report(args: argparse.Namespace, manifest: ResolvedManifest, digest: str, results: dict[str, dict]) -> dict:
    ordered = [
        results.get(check.id, {"id": check.id, "status": "infra_error", "reason": "not scheduled"})
        for check in manifest.active_checks
    ]
    passed = all(
        result.get("status") == "passed"
        or (result.get("status") == "skipped" and result.get("reason") != "dependency failed")
        or not result.get("required", True)
        for result in ordered
    )
    return {
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
        "status": "passed" if passed else "failed",
    }
