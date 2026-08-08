from __future__ import annotations

import re
import sys
from pathlib import Path


def require_path(path: Path, key: str) -> None:
    if not path.exists():
        fail(f"{key} points to a missing path: {path}")


def fail(message: str) -> None:
    emit_error(message)
    sys.exit(2)


def emit_error(message: str) -> None:
    print(f"::error::{escape_github_message(message)}", file=sys.stderr)


def emit_file_error(path: str, line: int, title: str, message: str) -> None:
    print(f"::error file={path},line={line},title={title}::{escape_github_message(message)}", file=sys.stderr)


def as_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def stripped(value: object) -> str:
    return str(value or "").strip()


def trimmed_error(message: str, fallback: str) -> str:
    text = message.strip()
    return text if text else fallback


def shell_display(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def escape_github_message(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def truncate(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def github_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()
