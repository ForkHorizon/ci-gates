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

_METHOD_NAME = r"(?:#[A-Za-z_$][A-Za-z0-9_$]*|[A-Za-z_$][A-Za-z0-9_$]*|\[[^\]]+\])"
_METHOD_PATTERN = re.compile(
    r"^(?P<prefix>(?:(?:[A-Za-z_$][A-Za-z0-9_$]*|\*)\s+)*?)"
    r"(?P<generator>\*)?\s*(?P<name>" + _METHOD_NAME + r")"
    r"\s*(?:<[^(){};]*>)?\s*\("
)
_FIELD_ARROW_PATTERN = re.compile(
    r"^(?P<prefix>(?:(?:[A-Za-z_$][A-Za-z0-9_$]*|\*)\s+)*?)"
    r"(?P<name>#[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s+)?"
    r"(?:\([^()]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>"
)


def method_name(line: str, typescript: bool = False) -> str | None:
    match = _METHOD_PATTERN.match(line.strip())
    if not match:
        return None
    name = match.group("name")
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
    match = _FIELD_ARROW_PATTERN.match(line.strip())
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


def is_typescript_method_declaration(signature: str, name: str) -> bool:
    if not name or "(" not in signature or ")" not in signature:
        return False
    if not re.search(r"\b(?:public|private|protected|abstract|declare)\b", signature):
        return False
    return method_name(signature, typescript=True) == name


def has_complete_method_header(signature: str) -> bool:
    if signature.count("(") != signature.count(")"):
        return False
    close = signature.rfind(")")
    if close < 0:
        return False
    suffix = signature[close + 1 :].strip()
    if suffix.endswith("{"):
        suffix = suffix[:-1].rstrip()
    return not suffix or suffix.startswith(":")


def should_reject_incomplete_method(
    language: str,
    pending_arrow: bool,
    name: str,
    signature: str,
    braces: tuple[int, int],
) -> bool:
    return (
        language in {"javascript", "typescript"}
        and not pending_arrow
        and name != "<anonymous>"
        and bool(braces[0])
        and not bool(braces[1])
        and not has_complete_method_header(signature)
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
