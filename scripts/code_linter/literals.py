from __future__ import annotations


def is_rust_lifetime(line: str, index: int, language: str) -> bool:
    """Return whether a quote starts a Rust lifetime instead of a char."""
    if language != "rust" or index + 1 >= len(line):
        return False
    following = line[index + 1]
    if not (following.isalpha() or following == "_"):
        return False
    return not (index + 2 < len(line) and line[index + 2] == "'")


def strip_strings(line: str, language: str = "") -> str:
    output = []
    quote: str | None = None
    escaped = False
    quotes = {'"', "'"} if language == "swift" else {'"', "'", "`"}
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            if escaped:
                escaped = False
                output.append(" ")
                index += 1
                continue
            if char == "\\":
                escaped = True
                output.append(" ")
                index += 1
                continue
            if char == quote:
                quote = None
            output.append(" ")
            index += 1
            continue
        if char in quotes:
            if is_rust_lifetime(line, index, language):
                output.append(char)
                index += 1
                continue
            quote = char
            output.append(" ")
        else:
            output.append(char)
        index += 1
    return "".join(output)


def strip_ruby_comment(line: str) -> str:
    output = []
    quote: str | None = None
    escaped = False
    for char in line:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            output.append(" ")
            continue
        if char in {'"', "'"}:
            quote = char
            output.append(" ")
        elif char == "#":
            break
        else:
            output.append(char)
    return "".join(output)
