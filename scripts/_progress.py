"""Shared stdout progress marker for CI Scope's local log tailer.

Prints a `::ci-scope-progress::` line, following the same GitHub Actions
workflow-command convention (`::error::`, `::notice::`, `::group::`) already
used by these scripts. GitHub Actions ignores unrecognized command names, so
this is harmless noise there and meaningful only to the broker tailing the
job's local log file.
"""

import argparse
import json
import re

from code_linter.github import format_github_command


SCHEMA_VERSION = 1
MAX_TEXT_LENGTH = 200
MAX_INTEGER = 1_000_000
_REDACTED = "[REDACTED]"
_REDACTED_PATH = "[REDACTED_PATH]"

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?i)\b(?:token|secret|password|passwd|credential|api[_-]?key|access[_-]?key|private[_-]?key)\b"
        r"\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"(?i)\bhttps?://[^/\s:@]+:[^@\s]+@"),
)
_ABSOLUTE_PATH_PATTERN = re.compile(r"(?i)file:///[^\s,;]+|(?<![\w:/])/[^\s,;]+|[A-Za-z]:[\\/][^\s,;]+|\\\\[^\s,;]+")


class ProgressContractError(ValueError):
    """Raised when a progress marker cannot be represented safely."""


def _redact(value, *, field, limit=MAX_TEXT_LENGTH):
    if not isinstance(value, str):
        raise ProgressContractError(f"{field} must be a string")

    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    redacted = _ABSOLUTE_PATH_PATTERN.sub(_REDACTED_PATH, redacted)
    return redacted[:limit]


def _validate_integer(value, *, field):
    if type(value) is not int or value < 0 or value > MAX_INTEGER:
        raise ProgressContractError(f"{field} must be a non-negative bounded integer")
    return value


def progress(step, current=None, total=None, detail=None):
    step = _redact(step, field="step")
    if not step.strip():
        raise ProgressContractError("step must not be empty")

    if current is not None:
        current = _validate_integer(current, field="current")
    if total is not None:
        total = _validate_integer(total, field="total")
    if current is not None and total is not None and current > total:
        raise ProgressContractError("current must not be greater than total")

    payload = {"step": step}
    if current is not None:
        payload["current"] = current
    if total is not None:
        payload["total"] = total
    if detail is not None:
        payload["detail"] = _redact(detail, field="detail")
    payload["version"] = SCHEMA_VERSION
    print(
        format_github_command("ci-scope-progress", data=f" {json.dumps(payload)}"),
        flush=True,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Emit a CI Scope live-progress marker.")
    parser.add_argument("--step", required=True)
    parser.add_argument("--current", type=int)
    parser.add_argument("--total", type=int)
    parser.add_argument("--detail")
    args = parser.parse_args(argv)
    try:
        progress(args.step, current=args.current, total=args.total, detail=args.detail)
    except ProgressContractError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
