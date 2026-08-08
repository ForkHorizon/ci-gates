from __future__ import annotations

import fnmatch
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

from _progress import progress
from swift_compile_common import escape_github_message, fail, shell_display, truncate
from swift_compile_model import WarningRecord
from swift_compile_result import BuildResult, WarningPolicy


def run_and_collect(command: Sequence[str], root: Path, config: dict, policy: WarningPolicy) -> BuildResult:
    print("$ " + " ".join(shell_display(part) for part in command), flush=True)
    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except FileNotFoundError as exc:
        fail(f"Unable to run compile command: {exc}")

    critical_warnings = []
    assert process.stdout is not None
    progress("compiling", detail="Starting build")
    last_progress_detail = None
    for line in process.stdout:
        print(line, end="", flush=True)
        detail = compiling_file(line)
        if detail and detail != last_progress_detail:
            progress("compiling", detail=detail)
            last_progress_detail = detail
        warning = parse_warning_line(line)
        if warning and is_critical_warning(root, warning, config, policy):
            critical_warnings.append(warning)

    return BuildResult(process.wait(), critical_warnings)


def compiling_file(line: str) -> str | None:
    match = re.search(r"(?:CompileSwift|Compiling).*?([^\s,]+\.swift)\b", line)
    if not match:
        return None
    return match.group(1)


def parse_warning_line(line: str) -> WarningRecord | None:
    text = line.strip()
    if "warning:" not in text.lower():
        return None

    for pattern in (
        r"^(?P<path>.*?):(?P<line>\d+):(?P<column>\d+):\s*warning:\s*(?P<message>.*)$",
        r"^(?P<path>.*?):(?P<line>\d+):\s*warning:\s*(?P<message>.*)$",
    ):
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            return WarningRecord(
                raw_line=text,
                path=match.group("path"),
                line=int(match.group("line")),
                message=match.group("message").strip(),
            )

    match = re.search(r"warning:\s*(?P<message>.*)$", text, flags=re.IGNORECASE)
    if match:
        return WarningRecord(raw_line=text, path=None, line=None, message=match.group("message").strip())
    return None


def is_critical_warning(root: Path, warning: WarningRecord, config: dict, policy: WarningPolicy) -> bool:
    if warning.path and should_ignore(normalized_warning_path(root, warning.path), config["ignore"]):
        return False

    searchable = "\n".join(value for value in [warning.raw_line, warning.path or "", warning.message] if value)
    if any(pattern.search(searchable) for pattern in policy.exclude_patterns):
        return False
    if policy.fail_on_any_warning:
        return True
    return any(pattern.search(searchable) for pattern in policy.include_patterns)


def normalized_warning_path(root: Path, warning_path: str) -> str:
    clean_path = warning_path.removeprefix("file://")
    path = Path(clean_path)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(root).as_posix()
        except ValueError:
            return path.as_posix().lstrip("/")
    return path.as_posix().lstrip("./")


def should_ignore(relative_path: str, patterns: Sequence[str]) -> bool:
    parts = relative_path.split("/")
    basename = parts[-1]
    for pattern in patterns:
        normalized = str(pattern).strip().replace("\\", "/")
        if not normalized:
            continue
        if "/" not in normalized:
            if any(part == normalized for part in parts):
                return True
            if fnmatch.fnmatch(basename, normalized):
                return True
            continue
        if fnmatch.fnmatch(relative_path, normalized):
            return True
        if fnmatch.fnmatch(relative_path, f"**/{normalized}"):
            return True
    return False


def annotate_critical_warnings(root: Path, warnings: Sequence[WarningRecord]) -> None:
    for warning in warnings[:10]:
        message = escape_github_message(truncate(warning.message or warning.raw_line.strip(), 400))
        if warning.path:
            path = normalized_warning_path(root, warning.path)
            line = f",line={warning.line}" if warning.line else ""
            print(f"::error file={path}{line},title=critical_warning::{message}")
        else:
            print(f"::error title=critical_warning::{message}")
    if len(warnings) > 10:
        print(f"::notice::Swift Compile Gate suppressed {len(warnings) - 10} additional critical warning annotations.")
