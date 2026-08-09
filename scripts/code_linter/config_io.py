from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from .github import format_github_command

ConfigErrorReporter = Callable[[Path, str], None]


def config_read_error(error: OSError | UnicodeError) -> str:
    if isinstance(error, UnicodeError):
        return "Unable to read Code Linter config: config must be UTF-8 encoded."
    detail = error.strerror or "I/O error"
    return f"Unable to read Code Linter config: {detail}."


def read_config_text(path: Path, report_error: ConfigErrorReporter) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        report_error(path, config_read_error(error))
    raise AssertionError("config error reporter returned without terminating")


def config_error(path: Path, message: str) -> None:
    print(
        format_github_command(
            "error",
            properties=(("file", github_path(path)),),
            data=message,
        ),
        file=sys.stderr,
    )
    sys.exit(2)


def github_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
