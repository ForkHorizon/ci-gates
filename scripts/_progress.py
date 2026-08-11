# CI approval probe: harmless code-file comment; no runtime behavior change.
"""Shared stdout progress marker for CI Scope's local log tailer.

Prints a `::ci-scope-progress::` line, following the same GitHub Actions
workflow-command convention (`::error::`, `::notice::`, `::group::`) already
used by these scripts. GitHub Actions ignores unrecognized command names, so
this is harmless noise there and meaningful only to the broker tailing the
job's local log file.
"""

import argparse
import json

from code_linter.github import format_github_command


def progress(step, current=None, total=None, detail=None):
    payload = {"step": step}
    if current is not None:
        payload["current"] = current
    if total is not None:
        payload["total"] = total
    if detail is not None:
        payload["detail"] = str(detail)[:200]
    print(format_github_command("ci-scope-progress", data=f" {json.dumps(payload)}"), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Emit a CI Scope live-progress marker.")
    parser.add_argument("--step", required=True)
    parser.add_argument("--current", type=int)
    parser.add_argument("--total", type=int)
    parser.add_argument("--detail")
    args = parser.parse_args(argv)
    progress(args.step, current=args.current, total=args.total, detail=args.detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
