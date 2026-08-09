from __future__ import annotations

import json

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
    return yaml_duplicate_key_issues(relative, text)


def yaml_duplicate_key_issues(relative: str, text: str) -> list[Issue]:
    """Reject repeated keys in block and flow mappings without a YAML library."""
    scopes = [{"indent": -1, "sequence": False, "keys": set(), "empty": False}]
    block_scalar_indent: int | None = None
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
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
        sequence_item = fragment.startswith("-") and (len(fragment) == 1 or fragment[1].isspace())
        if sequence_item:
            fragment = fragment[1:].lstrip(" ")
        colon = mapping_colon(fragment)
        if colon < 0:
            _close_yaml_scopes(scopes, indent)
            continue
        value = fragment[colon + 1 :].lstrip()
        if value in {"|", ">", "|-", "|+", ">-", ">+"}:
            block_scalar_indent = indent
        key = _normalized_yaml_key(fragment[:colon])
        scope = _yaml_mapping_scope(scopes, indent, sequence_item)
        if key in scope["keys"]:
            return [Issue(relative, line_number, "duplicate_key", f"Duplicate YAML key {key!r}.")]
        scope["keys"].add(key)
        scope["empty"] = not value
        flow_issue = _flow_duplicate_key_issue(relative, line_number, content)
        if flow_issue:
            return [flow_issue]
    return []


def _close_yaml_scopes(scopes: list[dict], indent: int) -> None:
    while len(scopes) > 1 and scopes[-1]["indent"] >= indent:
        scopes.pop()


def _yaml_mapping_scope(scopes: list[dict], indent: int, sequence_item: bool) -> dict:
    if sequence_item:
        _close_yaml_scopes(scopes, indent)
        scope = {"indent": indent, "sequence": True, "keys": set(), "empty": False}
        scopes.append(scope)
        return scope
    while len(scopes) > 1 and scopes[-1]["indent"] > indent:
        scopes.pop()
    current = scopes[-1]
    if current["indent"] == indent:
        return current
    if current["sequence"] and not current["empty"] and indent > current["indent"]:
        return current
    scope = {"indent": indent, "sequence": False, "keys": set(), "empty": False}
    scopes.append(scope)
    if current["sequence"]:
        current["empty"] = False
    return scope


def _normalized_yaml_key(raw_key: str) -> str:
    key = raw_key.strip()
    if key.startswith("?"):
        key = key[1:].lstrip()
    if len(key) >= 2 and key[0] == key[-1] == "'":
        return key[1:-1].replace("''", "'")
    if len(key) >= 2 and key[0] == key[-1] == '"':
        try:
            decoded = json.loads(key)
        except json.JSONDecodeError:
            return key
        if isinstance(decoded, str):
            return decoded
    return key


def _flow_duplicate_key_issue(relative: str, line_number: int, content: str) -> Issue | None:
    stack: list[dict] = []
    quote = ""
    escaped = False
    for character in content:
        if quote:
            quote, escaped = _flow_quoted_character(stack, character, quote, escaped)
            continue
        if character in {"'", '"'}:
            quote = character
            _flow_append_key(stack, character)
            continue
        issue = _flow_collection_character(stack, character, relative, line_number)
        if issue:
            return issue
    return None


def _flow_quoted_character(stack: list[dict], character: str, quote: str, escaped: bool) -> tuple[str, bool]:
    if quote == '"' and escaped:
        return quote, False
    if quote == '"' and character == "\\":
        return quote, True
    _flow_append_key(stack, character)
    return ("" if character == quote else quote), False


def _flow_append_key(stack: list[dict], character: str) -> None:
    if stack and stack[-1]["kind"] == "map" and stack[-1]["expect_key"]:
        stack[-1]["key"] += character


def _flow_collection_character(stack: list[dict], character: str, relative: str, line_number: int) -> Issue | None:
    if character == "{":
        stack.append({"kind": "map", "expect_key": True, "key": "", "keys": set()})
    elif character == "[":
        stack.append({"kind": "sequence"})
    elif character in "}]" and stack:
        stack.pop()
    elif character == "," and stack and stack[-1]["kind"] == "map":
        stack[-1]["expect_key"] = True
        stack[-1]["key"] = ""
    elif character == ":" and stack and stack[-1]["kind"] == "map" and stack[-1]["expect_key"]:
        key = _normalized_yaml_key(stack[-1]["key"])
        if key in stack[-1]["keys"]:
            return Issue(relative, line_number, "duplicate_key", f"Duplicate YAML key {key!r}.")
        stack[-1]["keys"].add(key)
        stack[-1]["expect_key"] = False
    else:
        _flow_append_key(stack, character)
    return None


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
