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
import subprocess
import sys
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from _progress import progress

CACHE_DIR = Path.home() / "Library/Caches/ci-gates"

DEFAULT_CONFIG = {
    "include_extensions": [
        ".py",
        ".swift",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".cs",
        ".go",
        ".rs",
        ".rb",
        ".java",
        ".kt",
    ],
    "exclude_paths": [
        "node_modules/",
        "dist/",
        "build/",
        ".build/",
        "vendor/",
        "Pods/",
        "Assets/Plugins/",
        "Assets/Libs/",
        "Assets/TextMesh Pro/",
    ],
    "categories": [
        "swallowed-error",
        "speculative-abstraction",
        "misleading-name",
        "noise-comment",
        "fake-test",
        "dead-end-code",
        "insecure-pattern",
    ],
    "max_findings": 8,
    "max_candidates": 15,
    "max_file_diff_lines": 400,
    "refute_votes": 3,
}

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

FIND_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer"},
                    "category": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "problem": {"type": "string"},
                },
                "required": ["line", "category", "severity", "problem"],
            },
        }
    },
    "required": ["findings"],
}

REFUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_real": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["is_real", "reason"],
}

FIND_PROMPT = """You are a strict senior reviewer looking ONLY for AI-generated "slop"
in the added lines of this diff. Report at most {max} of the MOST serious issues.

Flag only these categories: {categories}
Definitions:
- swallowed-error: an exception/error caught and ignored, logged-and-continued, or a
  success value returned when the operation actually failed.
- speculative-abstraction: an interface/factory/config/wrapper with a single use that
  adds no behavior; indirection for its own sake (YAGNI).
- misleading-name: a name that claims behavior the code does not perform.
- noise-comment: a comment that only restates what the next line already says.
- fake-test: a test that asserts a mock/constant, or exercises nothing real.
- dead-end-code: unreachable branches, unused "just in case" parameters, no-op paths.
- insecure-pattern: secret literals, or SQL/shell/HTML built by string concatenation.

Rules:
- Consider ONLY lines marked with '+'. Report the exact shown line number.
- Do NOT report style, formatting, or anything a linter already catches.
- If nothing qualifies, return an empty list. Be conservative; precision over recall.

File: {path}
```
{diff}
```"""

REFUTE_PROMPT = """A first reviewer flagged the issue below. You are a second, skeptical
reviewer. Decide whether it is a REAL problem worth showing the author.

Set is_real=true if a competent engineer would agree the flagged code is a genuine
instance of the category. Set is_real=false ONLY if the claim is factually wrong,
purely stylistic/nitpicky, or a clear false positive.

Judge the code exactly as shown. For security, assume external inputs may be untrusted
(string-built SQL/shell IS injectable regardless of the caller). But REJECT findings that
depend on hypothetical misuse not present in the diff ("if this were ever logged",
"if called wrongly"), normal control flow described as a bug (an early-return guard is not
a swallowed error), errors that are propagated via `throws`/`throw`/`return err`, and
intentional defaults (`?? ""`) unless the masking is clearly harmful.

Category: {category}
Claim (line {line}): {problem}

File: {path}
```
{diff}
```"""


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
    parser.add_argument("--model", default=os.environ.get("CI_GATES_SLOP_MODEL", "qwen3-coder:30b-a3b-q4_K_M"))
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
    data = ollama_json(args, prompt, FIND_SCHEMA)
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
        verdict = ollama_json(args, prompt, REFUTE_SCHEMA, temperature=0.4)
        if verdict.get("is_real"):
            real += 1
    return real * 2 > max(1, votes)


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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
