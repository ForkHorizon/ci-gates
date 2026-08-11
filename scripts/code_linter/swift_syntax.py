from __future__ import annotations

import re


SWIFT_TYPE_DECLARATION = re.compile(
    r"^(?:(?:@\w+(?:\([^{}]*\))?|"
    r"(?:public|private|fileprivate|internal|open|final|indirect|nonisolated)\s+))*"
    r"(class|struct|enum|protocol|extension|actor)\b"
)


def swift_type_declaration_kind(line: str) -> str | None:
    match = SWIFT_TYPE_DECLARATION.match(line.strip())
    return match.group(1) if match else None


def detect_swift(line: str) -> str | None:
    type_kind = swift_type_declaration_kind(line)
    if type_kind:
        opening = line.find("{")
        line = line[opening + 1 :] if opening >= 0 else ""
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
