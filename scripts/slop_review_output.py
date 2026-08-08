from __future__ import annotations

import argparse
import json
import os
import subprocess

from slop_review_policy import CACHE_DIR


def report(findings: list[dict], file_count: int, candidate_count: int) -> None:
    for finding in findings:
        message = f"[{finding['category']}] {finding['problem']}"
        print(f"::warning file={finding['path']},line={finding['line']},title=slop::{escape(message)}")

    if not findings:
        print(f"Slop review: no issues survived refutation across {file_count} file(s).")
    else:
        print(f"Slop review: {len(findings)} advisory finding(s) across {file_count} file(s).")
    write_summary(findings, file_count, candidate_count)


def write_summary(findings: list[dict], file_count: int, candidate_count: int) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    rows = [
        "## Slop review (advisory)",
        "",
        f"{file_count} file(s) reviewed, {candidate_count} candidate(s), {len(findings)} after refutation.",
        "",
    ]
    if findings:
        rows += ["| Severity | File:line | Category | Problem |", "|---|---|---|---|"]
        rows += [
            f"| {f['severity']} | `{f['path']}:{f['line']}` | {f['category']} | {escape_cell(f['problem'])} |"
            for f in findings
        ]
    else:
        rows.append("No issues survived the adversarial pass.")
    rows.append("\n_Advisory only — does not affect the merge decision._\n")
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(rows) + "\n")


def write_journal(args: argparse.Namespace, findings: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "repo": os.environ.get("GITHUB_REPOSITORY", ""),
        "pr": os.environ.get("GITHUB_REF_NAME", ""),
        "sha": os.environ.get("GITHUB_SHA", ""),
        "model": args.model,
        "findings": [{k: f[k] for k in ("path", "line", "category", "severity", "problem")} for f in findings],
    }
    with open(CACHE_DIR / "slop-review-journal.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def git(args: list[str]) -> str:
    result = subprocess.run(["git", *args], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def escape(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_cell(message: str) -> str:
    return message.replace("|", "\\|").replace("\n", " ")
