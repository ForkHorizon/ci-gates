"""A small TOML reader that picks out the settings deciding which lint rules apply, however they are written.

Mirrors CI-Scope-Web toml-scope.ts; both sides must produce identical scopes (shared vectors in the tests).
"""

from __future__ import annotations

import re
from collections.abc import Callable


class _Scan:
    def __init__(self) -> None:
        self.text = ""
        self.quote = ""
        self.depth = 0


def _in_quote(content: str, index: int, scan: _Scan) -> int:
    char = content[index]
    if len(scan.quote) == 3:
        if not content.startswith(scan.quote, index):
            scan.text += char
            return index + 1
        scan.text += scan.quote
        scan.quote = ""
        return index + 3
    if char == "\\" and scan.quote == '"':
        scan.text += char + (content[index + 1] if index + 1 < len(content) else "")
        return index + 2
    if char == scan.quote:
        scan.quote = ""
    scan.text += char
    return index + 1


def _open_quote(content: str, index: int, scan: _Scan) -> int:
    char = content[index]
    scan.quote = char * 3 if content.startswith(char * 3, index) else char
    scan.text += scan.quote
    return index + len(scan.quote)


def _end_line(scan: _Scan, out: list[str]) -> None:
    if scan.depth > 0:
        scan.text += " "
        return
    if scan.text.strip():
        out.append(scan.text.strip())
    scan.text = ""
    scan.depth = 0


def _step(content: str, index: int, scan: _Scan, out: list[str]) -> int:
    char = content[index]
    if scan.quote:
        return _in_quote(content, index, scan)
    if char in "\"'":
        return _open_quote(content, index, scan)
    if char == "#":
        end = index
        while end < len(content) and content[end] != "\n":
            end += 1
        return end
    if char == "\n":
        _end_line(scan, out)
        return index + 1
    if char == "\r":
        return index + 1
    if char in "[{":
        scan.depth += 1
    if char in "]}":
        scan.depth -= 1
    if re.fullmatch(r"\s", char):
        scan.text += "" if scan.text == "" or scan.text.endswith(" ") else " "
    else:
        scan.text += char
    return index + 1


def toml_statements(content: str) -> list[str]:
    """Statements of a TOML document: comments dropped, whitespace outside strings collapsed, multi-line values joined."""
    out: list[str] = []
    scan = _Scan()
    index = 0
    while index < len(content):
        index = _step(content, index, scan, out)
    if scan.text.strip():
        out.append(scan.text.strip())
    return out


def dotted_parts(text: str) -> list[str]:
    """Splits a dotted key such as `workspace.lints."rust".dead_code`, unquoting quoted parts."""
    parts: list[str] = []
    current = ""
    quote = ""
    for char in text.strip():
        if quote:
            if char == quote:
                quote = ""
            else:
                current += char
        elif char in "\"'":
            quote = char
        elif char == ".":
            parts.append(current.strip())
            current = ""
        else:
            current += char
    parts.append(current.strip())
    return parts


def _split_at_equals(statement: str) -> tuple[str, str] | None:
    quote = ""
    for index, char in enumerate(statement):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "=":
            return statement[:index], statement[index + 1 :].strip()
    return None


def toml_scope(content: str, wanted: Callable[[list[str]], bool]) -> str:
    """Every setting whose full path `wanted` accepts, as sorted `path = value` lines."""
    table: list[str] = []
    found: list[str] = []
    for statement in toml_statements(content):
        if statement.startswith("["):
            header = re.sub(r"\]\]?$", "", re.sub(r"^\[\[?", "", statement))
            table = dotted_parts(header)
            continue
        pair = _split_at_equals(statement)
        if pair is None:
            continue
        path = [*table, *dotted_parts(pair[0])]
        if wanted(path):
            found.append(f"{'.'.join(path)} = {pair[1]}")
    return "\n".join(sorted(found))


def cargo_lint_path(path: list[str]) -> bool:
    return path[0] == "lints" or (len(path) > 1 and path[1] == "lints")


def python_tool_path(path: list[str]) -> bool:
    return path[0] == "tool" and len(path) > 1 and path[1] in {"ruff", "pytest", "mypy", "pyright"}
