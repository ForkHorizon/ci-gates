from __future__ import annotations

import re


_MARKER = re.compile(r"<<<[-~]?(?:['\"])?([A-Za-z_][A-Za-z0-9_]*)")


def marker_at(line: str, index: int) -> str | None:
    if index and line[index - 1] == "<":
        return None
    match = _MARKER.match(line, index)
    return match.group(1) if match else None


def closes_marker(line: str, marker: str) -> bool:
    return line.strip().rstrip(";") == marker
