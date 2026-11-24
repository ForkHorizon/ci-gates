"""Telling JavaScript regex literals apart from division and JSX `/>`."""

from __future__ import annotations

import re
from collections.abc import Sequence


def starts_javascript_regex(output: Sequence[str]) -> bool:
    prefix = "".join(output).rstrip()
    if not prefix:
        return True
    return prefix[-1] in "=(:,[!&|?{};" or bool(
        re.search(r"\b(?:return|throw|case|delete|typeof|void|new|in|of)\s*$", prefix)
    )


def in_jsx_tag(output: Sequence[str]) -> bool:
    # `<B c="d" />`: the `/` closes a JSX tag opened on this line, not a regex.
    prefix = "".join(output)
    start = prefix.rfind("<")
    return start >= 0 and prefix[start + 1 : start + 2].isalpha() and ">" not in prefix[start:]


def consume_javascript_regex(line: str, index: int) -> int | None:
    """Skip a regex literal; None when the line has no closing `/` (not a regex)."""
    in_class = False
    index += 1
    while index < len(line):
        if line[index] == "\\" and index + 1 < len(line):
            index += 2
        elif line[index] == "[":
            in_class = True
            index += 1
        elif line[index] == "]":
            in_class = False
            index += 1
        elif line[index] == "/" and not in_class:
            index += 1
            while index < len(line) and line[index].isalpha():
                index += 1
            return index
        else:
            index += 1
    # Regex literals cannot span lines: never carry "regex" state over.
    return None


def skip_javascript_regex(line: str, index: int, language: str, output: Sequence[str]) -> int | None:
    """Index after a regex literal starting at `index`, or None when there is none."""
    if line[index] != "/" or language not in {"javascript", "typescript"} or not starts_javascript_regex(output):
        return None
    if line.startswith("/>", index) and in_jsx_tag(output):
        return None
    return consume_javascript_regex(line, index)
