#!/usr/bin/env python3
"""Advisory AI-slop reviewer for pull-request diffs.

Sends each changed file's diff to a local Ollama model, asks for semantic
"slop" that deterministic linters cannot see (swallowed errors, speculative
abstractions, misleading names, noise comments, fake tests, dead-end code,
insecure string-built queries), then runs an adversarial second pass that
tries to refute each finding and keeps only the survivors. Emits GitHub
warning annotations, a job-summary table, and a calibration journal.

Advisory only: always exits 0, so it can never block a merge. Stdlib-only,
like the other ci-gates scripts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from _progress import progress
from slop_review_output import git, report, write_journal
from slop_review_policy import (
    DEFAULT_CONFIG,
    FIND_PROMPT,
    FIND_SCHEMA,
    REFUTE_PROMPT,
    REFUTE_SCHEMA,
    SEVERITY_RANK,
)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    try:
        run_review(args)
    except Exception as exc:  # advisory step must never fail the job
        print(f"::notice title=Slop review::Skipped: {exc}")
    return 0


def run_review(args: argparse.Namespace) -> None:
    config = load_config(Path(args.config))
    files = changed_files(args.base, args.head, config)
    if not files:
        progress("finding", detail="No reviewable files")
        print("Slop review: no reviewable files changed.")
        return

    candidates: list[dict] = []
    for index, path in enumerate(files, start=1):
        progress("finding", current=index, total=len(files), detail=path)
        diff = numbered_diff(args.base, args.head, path, config["max_file_diff_lines"])
        if diff:
            candidates.extend(find_candidates(args, config, path, diff))

    candidates = dedupe(candidates)[: config["max_candidates"]]
    if not candidates:
        progress("refuting", detail="No findings to verify")
    survivors = []
    for index, candidate in enumerate(candidates, start=1):
        progress("refuting", current=index, total=len(candidates), detail=f"{candidate['path']}:{candidate['line']}")
        if survives_refutation(args, candidate, config["refute_votes"]):
            survivors.append(candidate)
    survivors.sort(key=lambda f: SEVERITY_RANK.get(f["severity"], 3))
    survivors = survivors[: config["max_findings"]]

    report(survivors, len(files), len(candidates))
    write_journal(args, survivors)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Advisory AI-slop reviewer for PR diffs.")
    parser.add_argument("--base", required=True, help="Base ref (merge base of the PR).")
    parser.add_argument("--head", default="HEAD", help="Head ref.")
    parser.add_argument("--config", default=".slop-review.json")
    parser.add_argument("--model", default=os.environ.get("CI_GATES_SLOP_MODEL", "deepseek-chat"))
    parser.add_argument("--api-key", default=os.environ.get("DEEPSEEK_API_KEY", ""))
    parser.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
    return parser.parse_args(argv)


def load_config(path: Path) -> dict:
    config = {key: (list(value) if isinstance(value, list) else value) for key, value in DEFAULT_CONFIG.items()}
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"{path.name} must be a JSON object.")
        config.update(loaded)
    return config


def changed_files(base: str, head: str, config: dict) -> list[str]:
    out = git(["diff", "--name-only", "--diff-filter=ACMR", f"{base}...{head}"])
    includes = set(config["include_extensions"])
    files = []
    for name in out.splitlines():
        if Path(name).suffix not in includes:
            continue
        if any(name.startswith(prefix) or f"/{prefix}" in name for prefix in config["exclude_paths"]):
            continue
        files.append(name)
    return files


def numbered_diff(base: str, head: str, path: str, max_lines: int) -> str:
    raw = git(["diff", "--unified=8", f"{base}...{head}", "--", path])
    lines, new_line, in_hunk = [], 0, False
    for line in raw.splitlines():
        if line.startswith("@@"):
            new_line = parse_hunk_start(line)
            in_hunk = True
            lines.append(line)
        elif not in_hunk or line.startswith("\\"):
            continue
        elif line.startswith("+"):
            lines.append(f"+ {new_line:>5}  {line[1:]}")
            new_line += 1
        elif line.startswith("-"):
            lines.append(f"-        {line[1:]}")
        else:
            lines.append(f"  {new_line:>5}  {line[1:]}")
            new_line += 1
    if len(lines) > max_lines:
        lines = [*lines[:max_lines], f"... ({len(lines) - max_lines} more diff lines omitted)"]
    return "\n".join(lines)


def parse_hunk_start(header: str) -> int:
    plus = header.split("+", 1)[1]
    number = plus.split(",", 1)[0].split(" ", 1)[0]
    return int(number) if number.isdigit() else 1


def find_candidates(args: argparse.Namespace, config: dict, path: str, diff: str) -> list[dict]:
    prompt = FIND_PROMPT.format(
        max=config["max_findings"],
        categories=", ".join(config["categories"]),
        path=path,
        diff=diff,
    )
    data = llm_json(args, prompt, FIND_SCHEMA)
    allowed = set(config["categories"])
    findings = []
    for item in data.get("findings", []):
        if item.get("category") in allowed and isinstance(item.get("line"), int):
            findings.append(
                {
                    "path": path,
                    "line": item["line"],
                    "category": item["category"],
                    "severity": item.get("severity", "medium"),
                    "problem": str(item.get("problem", "")).strip(),
                    "diff": diff,
                }
            )
    return findings


def survives_refutation(args: argparse.Namespace, finding: dict, votes: int) -> bool:
    prompt = REFUTE_PROMPT.format(
        category=finding["category"],
        line=finding["line"],
        problem=finding["problem"],
        path=finding["path"],
        diff=finding["diff"],
    )
    real = 0
    for _ in range(max(1, votes)):
        verdict = llm_json(args, prompt, REFUTE_SCHEMA, temperature=0.4)
        if verdict.get("is_real"):
            real += 1
    return real * 2 > max(1, votes)


def llm_json(args: argparse.Namespace, prompt: str, schema: dict, temperature: float = 0.1) -> dict:
    if args.api_key:
        return deepseek_json(args, prompt, schema, temperature)
    return ollama_json(args, prompt, schema, temperature)


def deepseek_json(args: argparse.Namespace, prompt: str, _schema: dict, temperature: float = 0.1) -> dict:
    model = args.model if args.model and not args.model.startswith("qwen") else "deepseek-chat"
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": temperature,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {args.api_key}",
        },
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.loads(response.read().decode("utf-8"))
    try:
        content = body["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError):
        return {}


def ollama_json(args: argparse.Namespace, prompt: str, schema: dict, temperature: float = 0.1) -> dict:
    payload = json.dumps(
        {
            "model": args.model,
            "prompt": prompt,
            "stream": False,
            "format": schema,
            "options": {"num_ctx": 16384, "temperature": temperature},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{args.host.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.loads(response.read().decode("utf-8"))
    try:
        return json.loads(body.get("response", "") or "{}")
    except json.JSONDecodeError:
        return {}


def dedupe(candidates: list[dict]) -> list[dict]:
    seen, unique = set(), []
    for finding in candidates:
        key = (finding["path"], finding["line"], finding["category"])
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
