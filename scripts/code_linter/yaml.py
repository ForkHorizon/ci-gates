from __future__ import annotations

from .model import Issue


FLOW_PAIRS = {
    "]": "[",
    "}": "{",
}


def yaml_syntax_issues(relative: str, text: str) -> list[Issue]:
    """Check portable YAML lexical rules without adding a parser dependency."""
    block_scalar_indent: int | None = None
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if raw_line.startswith("\t"):
            return [Issue(relative, line_number, "syntax_error", "YAML indentation must use spaces, not tabs.")]
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if block_scalar_indent is not None:
            if not raw_line.strip() or indent > block_scalar_indent:
                continue
            block_scalar_indent = None
        content = strip_comment(raw_line).rstrip()
        if not content.strip():
            continue
        fragment = content.lstrip(" ")
        if fragment in {"---", "..."}:
            continue
        if fragment.startswith("-"):
            fragment = fragment[1:].lstrip(" ")
        colon = mapping_colon(fragment)
        value = fragment[colon + 1 :].lstrip() if colon >= 0 else fragment
        if value in {"|", ">", "|-", "|+", ">-", ">+"}:
            block_scalar_indent = indent
            continue
        error = fragment_error(value)
        if error:
            return [Issue(relative, line_number, "syntax_error", f"YAML syntax error: {error}.")]
    return []


def strip_comment(line: str) -> str:
    quote = ""
    escaped = False
    for index, character in enumerate(line):
        if quote == '"' and escaped:
            escaped = False
            continue
        if quote == '"' and character == "\\":
            escaped = True
            continue
        if character in {"'", '"'}:
            if not quote:
                quote = character
            elif quote == character:
                quote = ""
        elif character == "#" and not quote and (index == 0 or line[index - 1].isspace()):
            return line[:index]
    return line


def mapping_colon(fragment: str) -> int:
    quote = ""
    escaped = False
    for index, character in enumerate(fragment):
        if quote == '"' and escaped:
            escaped = False
            continue
        if quote == '"' and character == "\\":
            escaped = True
            continue
        if character in {"'", '"'}:
            if not quote:
                quote = character
            elif quote == character:
                quote = ""
        elif character == ":" and not quote and (index + 1 == len(fragment) or fragment[index + 1].isspace()):
            return index
    return -1


def fragment_error(fragment: str) -> str | None:
    quote = ""
    escaped = False
    stack: list[str] = []
    for character in fragment:
        if quote == '"' and escaped:
            escaped = False
            continue
        if quote == '"' and character == "\\":
            escaped = True
            continue
        if quote:
            if character == quote:
                quote = ""
            continue
        if character in {"'", '"'}:
            quote = character
        elif character in "[{":
            stack.append(character)
        elif character in FLOW_PAIRS and (not stack or stack.pop() != FLOW_PAIRS[character]):
            return "unexpected closing flow collection delimiter"
    if quote:
        return "unterminated quoted scalar"
    if stack:
        return "unterminated flow collection"
    return None
