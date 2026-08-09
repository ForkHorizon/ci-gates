from __future__ import annotations

import re


def detect_swift(line: str) -> str | None:
    match = re.search(
        r"\bfunc\s+(?:`([^`]+)`|([A-Za-z_][A-Za-z0-9_]*)|([^\s<(]+))",
        line,
    )
    if match:
        return (match.group(1) or match.group(2) or match.group(3)).strip("`")
    for pattern, name in (
        (r"\bsubscript\s*[<(]", "subscript"),
        (r"\binit\s*\(", "init"),
        (r"\bdeinit\b", "deinit"),
    ):
        if re.search(pattern, line):
            return name
    # Only treat a brace as a closure when its header has Swift's `in` marker.
    # This deliberately does not classify ordinary call-like/control blocks.
    if re.search(r"\{(?:[^{}]|\([^()]*\))*\s+in\b", line):
        return "<anonymous>"
    return None
