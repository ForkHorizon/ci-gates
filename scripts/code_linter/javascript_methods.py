from __future__ import annotations

import re

from .declaration_helpers import CONTROL_WORDS

JAVASCRIPT_METHOD_MODIFIERS = {
    "async",
    "get",
    "set",
    "static",
}
TYPESCRIPT_METHOD_MODIFIERS = JAVASCRIPT_METHOD_MODIFIERS | {
    "abstract",
    "declare",
    "override",
    "public",
    "private",
    "protected",
    "readonly",
}

_METHOD_NAME = (
    r"(?:#[A-Za-z_$][A-Za-z0-9_$]*|[A-Za-z_$][A-Za-z0-9_$]*|"
    r"\[(?:[^\[\]]|\[[^\[\]]*\])+\]"
    r"|'(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\"|"
    r"(?:0[xX][0-9A-Fa-f_]+|0[bB][01_]+|0[oO][0-7_]+|"
    r"(?:\d[\d_]*|\.\d[\d_]*)(?:\.[\d_]*)?(?:[eE][+-]?[\d_]+)?n?))"
)
_METHOD_PATTERN = re.compile(
    r"^(?P<prefix>(?:(?:[A-Za-z_$][A-Za-z0-9_$]*|\*)\s+)*?)"
    r"(?P<generator>\*)?\s*(?P<name>" + _METHOD_NAME + r")"
    r"\s*(?:<[^();]*>)?\s*\("
)
_FIELD_ARROW_PATTERN = re.compile(
    r"^(?P<prefix>(?:(?:[A-Za-z_$][A-Za-z0-9_$]*|\*)\s+)*?)"
    r"(?P<name>#[A-Za-z_$][A-Za-z0-9_$]*|[A-Za-z_$][A-Za-z0-9_$]*)"
    r"\s*=\s*(?:async\s+)?"
    r"(?P<parameters>\([^()]*\)|[A-Za-z_$][A-Za-z0-9_$]*)"
    r"(?:\s*:\s*[^=]+?)?\s*=>"
)


def method_name(line: str, typescript: bool = False) -> str | None:
    stripped = line.strip()
    match = _METHOD_PATTERN.match(stripped)
    if not match:
        opening = stripped.find("{")
        if opening >= 0:
            match = _METHOD_PATTERN.match(stripped[opening + 1 :].lstrip())
    if not match:
        return None
    name = match.group("name")
    if name.startswith("[") and name.endswith("]"):
        name = "[" + " ".join(name[1:-1].split()) + "]"
    if name in CONTROL_WORDS:
        return None
    modifiers = set(match.group("prefix").split())
    allowed = TYPESCRIPT_METHOD_MODIFIERS if typescript else JAVASCRIPT_METHOD_MODIFIERS
    if not modifiers.issubset(allowed):
        return None
    if not typescript and modifiers & {
        "abstract",
        "declare",
        "public",
        "private",
        "protected",
        "override",
    }:
        return None
    return name


def field_arrow_name(line: str, typescript: bool = False) -> str | None:
    stripped = line.strip()
    match = _FIELD_ARROW_PATTERN.match(stripped)
    if not match:
        match = re.match(
            r"^(?P<prefix>(?:(?:[A-Za-z_$][A-Za-z0-9_$]*|\*)\s+)*?)"
            r"(?P<name>#[A-Za-z_$][A-Za-z0-9_$]*|[A-Za-z_$][A-Za-z0-9_$]*)"
            r"\s*=\s*(?:async\s+)?",
            stripped,
        )
        if match and "=>" not in stripped[match.end() :]:
            match = None
    if not match:
        return None
    modifiers = set(match.group("prefix").split())
    allowed = TYPESCRIPT_METHOD_MODIFIERS if typescript else JAVASCRIPT_METHOD_MODIFIERS
    if not modifiers.issubset(allowed):
        return None
    if not typescript and modifiers & {
        "abstract",
        "declare",
        "public",
        "private",
        "protected",
        "override",
    }:
        return None
    return match.group("name")


def detect_javascript_method(line: str, allow_method_fallback: bool, typescript: bool = False) -> str | None:
    if not allow_method_fallback:
        return None
    return method_name(line, typescript) or field_arrow_name(line, typescript)


def is_typescript_method_declaration(signature: str, name: str, allow_bare: bool = False) -> bool:
    if not name or "(" not in signature or ")" not in signature:
        return False
    if method_name(signature, typescript=True) != name:
        return False
    opening = method_parameter_opening(signature, name)
    close = matching_parenthesis(signature, opening)
    if close < 0:
        return False
    if ";" in signature[opening + 1 : close]:
        return False
    suffix = signature[close + 1 :].lstrip()
    if re.search(r"\b(?:public|private|protected|abstract|declare)\b", signature):
        return suffix.startswith((":", ";"))
    return suffix.startswith((":", ";")) if allow_bare else suffix.startswith(":")


def matching_parenthesis(signature: str, opening: int) -> int:
    if opening < 0:
        return -1
    depth = 0
    for index in range(opening, len(signature)):
        if signature[index] == "(":
            depth += 1
        elif signature[index] == ")":
            depth -= 1
            if depth == 0:
                return index
            if depth < 0:
                return -1
    return -1


def method_parameter_opening(signature: str, name: str) -> int:
    start = signature.find(name)
    if start < 0:
        return -1
    if name.startswith("["):
        depth = 0
        for index in range(start, len(signature)):
            if signature[index] == "[":
                depth += 1
            elif signature[index] == "]":
                depth -= 1
                if depth == 0:
                    return signature.find("(", index + 1)
        return -1
    return signature.find("(", start + len(name))


def has_complete_method_header(signature: str, name: str) -> bool:
    opening = method_parameter_opening(signature, name)
    if opening < 0:
        return False
    depth = 0
    close = -1
    for index in range(opening, len(signature)):
        if signature[index] == "(":
            depth += 1
        elif signature[index] == ")":
            depth -= 1
            if depth == 0:
                close = index
                break
            if depth < 0:
                return False
    if close < 0 or depth != 0:
        return False
    suffix = signature[close + 1 :]
    body = suffix.find("{")
    header = suffix[:body] if body >= 0 else suffix
    header = header.strip()
    return not header or header.startswith(":")


def has_method_body_brace(signature: str, name: str) -> bool:
    opening = method_parameter_opening(signature, name)
    if opening < 0:
        return False
    depth = 0
    for index in range(opening, len(signature)):
        if signature[index] == "(":
            depth += 1
        elif signature[index] == ")":
            depth = max(0, depth - 1)
        elif signature[index] == "{" and depth == 0:
            return True
    return False


def should_reject_incomplete_method(
    language: str,
    pending_arrow: bool,
    name: str,
    signature: str,
) -> bool:
    return (
        language in {"javascript", "typescript"}
        and not pending_arrow
        and name != "<anonymous>"
        and has_method_body_brace(signature, name)
        and not has_complete_method_header(signature, name)
    )


def detect_javascript(line: str, allow_method_fallback: bool = False) -> str | None:
    modern_method = detect_javascript_method(line, allow_method_fallback)
    if modern_method:
        return modern_method
    patterns = (
        r"\bfunction\s*\*?\s*([A-Za-z_$][A-Za-z0-9_$]*)(?:\s*<[^>]+>)?\s*\(",
        r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=.*=>",
        r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\(?\s*$",
        r"(?:static\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?.*=>",
        r"(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?\*?\s*"
        r"([A-Za-z_$][A-Za-z0-9_$]*)\s*\([^)]*\)\s*\{?",
    )
    for index, pattern in enumerate(patterns[:4]):
        match = re.search(pattern, line) if index < 3 else re.match(pattern, line)
        if match and match.group(1) not in CONTROL_WORDS:
            return match.group(1)
    object_method = re.search(
        r"\{\s*(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?\*?\s*"
        r"([A-Za-z_$][A-Za-z0-9_$]*)\s*\([^)]*\)\s*\{",
        line,
    )
    if object_method and object_method.group(1) not in CONTROL_WORDS:
        return object_method.group(1)
    if allow_method_fallback:
        method = re.match(patterns[4], line)
        if method and method.group(1) not in CONTROL_WORDS:
            return method.group(1)
    function_expression = re.search(
        r"\b(?:async\s+)?function\s*\*?\s*(?:<[^(){}]*>)?\s*\(",
        line,
    )
    if function_expression:
        return "<anonymous>"
    anonymous = re.search(
        r"(?:\([^()]*(?:\([^()]*\)[^()]*)*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>",
        line,
    )
    return "<anonymous>" if anonymous else None


def detect_typescript(line: str, allow_method_fallback: bool = False) -> str | None:
    modern_method = detect_javascript_method(line, allow_method_fallback, typescript=True)
    if modern_method:
        return modern_method
    return detect_javascript(line, allow_method_fallback)
