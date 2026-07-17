#!/usr/bin/env python3
"""Explain a failed CI gate with a local Ollama model.

Runs on the self-hosted runner after a gate fails, sends the log tail and a
diff summary to Ollama, and publishes the explanation to the job summary.
Advisory only: this script always exits 0 so it can never mask or cause a
gate failure. Stdlib-only, like the other ci-gates scripts.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from collections.abc import Sequence

LOG_TAIL_CHARS = 8000
DIFF_TAIL_CHARS = 8000
REQUEST_TIMEOUT_SECONDS = 300

PROMPT_TEMPLATE = """You are a CI failure analyst. The GitHub Actions gate "{gate}" failed.

Below are the tail of the gate log and a summary of the changes under test.
Explain the failure to the developer:
1. What exactly failed (quote the decisive log lines).
2. Which file/line is responsible, if identifiable.
3. Why it violates the gate.
4. What to change, in one or two sentences. Do NOT rewrite the code.

Be specific and concise. Use Markdown. If the log shows several independent
problems, list each one.

## Gate log (tail)
```
{log}
```

## Changes under test
{diff}
"""


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    try:
        explanation = explain(args)
    except Exception as exc:
        print(f"::notice title=Failure explainer::Skipped: {exc}")
        return 0
    publish(args.gate, args.model, explanation)
    return 0


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Explain a failed gate via local Ollama.")
    parser.add_argument("--log", required=True, help="Path to the captured gate log.")
    parser.add_argument("--gate", required=True, help="Human-readable gate name.")
    parser.add_argument("--base", default="", help="Base ref for the diff summary.")
    parser.add_argument(
        "--model",
        default=os.environ.get("CI_GATES_EXPLAIN_MODEL", "qwen3-coder:30b-a3b-q4_K_M"),
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
    )
    return parser.parse_args(argv)


def explain(args: argparse.Namespace) -> str:
    log_text = tail(Path(args.log).read_text(encoding="utf-8", errors="replace"), LOG_TAIL_CHARS)
    prompt = PROMPT_TEMPLATE.format(gate=args.gate, log=log_text, diff=diff_summary(args.base))
    return generate(args.host, args.model, prompt)


def diff_summary(base: str) -> str:
    if not base:
        return "(no diff context available)"
    stat = run_git(["git", "diff", "--stat", f"{base}...HEAD"])
    diff = run_git(["git", "diff", "--unified=1", f"{base}...HEAD"])
    if not stat and not diff:
        return "(no diff context available)"
    return f"```\n{stat}\n```\n\n```diff\n{tail(diff, DIFF_TAIL_CHARS)}\n```"


def run_git(command: list[str]) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def generate(host: str, model: str, prompt: str) -> str:
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": 16384, "temperature": 0.2},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{host.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        body = json.loads(response.read().decode("utf-8"))
    text = str(body.get("response", "")).strip()
    if not text:
        raise RuntimeError("Ollama returned an empty response.")
    return text


def publish(gate: str, model: str, explanation: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    report = f"## Why {gate} failed\n\n{explanation}\n\n_Analysis by `{model}` on the runner._\n"
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report)
    else:
        print(report)
    first_line = explanation.splitlines()[0][:400]
    print(f"::notice title=Why {gate} failed::{escape_github_message(first_line)}")


def tail(text: str, limit: int) -> str:
    stripped = text.strip()
    return stripped if len(stripped) <= limit else "...\n" + stripped[-limit:]


def escape_github_message(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
