"""Quiet local output and compact results for the macOS app."""

from __future__ import annotations

from datetime import datetime
import subprocess
from pathlib import Path

from check_reporting import safe_text, write_result
from ci_scope_models import ResolvedManifest


def write_compact_result(path, report, manifest: ResolvedManifest, args, timestamps: tuple[datetime, datetime]):
    checks = report.get("checks", [])
    threshold = manifest.slow_ms or 20_000
    compact = {
        "status": report["status"],
        "tier": args.tier,
        "started_at": timestamps[0].isoformat(),
        "finished_at": timestamps[1].isoformat(),
        "git_head": _git_value(args.root, "rev-parse", "HEAD"),
        "dirty": bool(_git_value(args.root, "status", "--porcelain")),
        "checks": [{key: check.get(key) for key in ("id", "status", "duration_ms")} for check in checks],
        "slow": [check["id"] for check in checks if check.get("duration_ms", 0) > threshold],
    }
    write_result(path, compact, preserve_paths=args.quiet)


def _git_value(root: Path, *arguments: str) -> str:
    result = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def print_quiet(report, output: Path, elapsed: float, tail: int):
    checks = report.get("checks", [])
    failures = [
        check
        for check in checks
        if check.get("status") in {"failed", "timed_out", "infra_error", "cancelled"}
        or (check.get("status") == "skipped" and check.get("reason") == "dependency failed")
    ]
    if not failures:
        print(f"OK  {len(checks)} checks, {elapsed:.1f}s")
        return
    for check in failures:
        reason = safe_text(check.get("detail") or check.get("reason") or check["status"], preserve_paths=True)
        if reason.startswith("command failed:"):
            reason = "failed"
        print(f"FAIL {check['id']}  {reason[:200]}")
        log_path = (output / check.get("log", f"logs/{check['id']}.log")).resolve()
        if log_path.is_file():
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-tail:]:
                print(line)
        print(f"full log: {log_path}")
