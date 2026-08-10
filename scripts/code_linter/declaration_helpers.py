from __future__ import annotations

import re

from .cpp_operators import detect_cpp_operator
from .cpp_destructors import detect_cpp_destructor
from .objective_c import objective_c_selector


CONTROL_WORDS = {
    "catch",
    "do",
    "else",
    "for",
    "foreach",
    "guard",
    "if",
    "lock",
    "repeat",
    "switch",
    "try",
    "using",
    "when",
    "while",
    "with",
}

DECLARATION_MODIFIERS = {
    "abstract",
    "async",
    "const",
    "extern",
    "final",
    "internal",
    "new",
    "override",
    "partial",
    "private",
    "protected",
    "public",
    "sealed",
    "static",
    "synchronized",
    "unsafe",
    "virtual",
}

C_FAMILY_LANGUAGES = {
    "c",
    "cpp",
    "csharp",
    "dart",
    "groovy",
    "java",
    "objective_c",
    "scala",
}


def _has_return_type(prefix: str) -> bool:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", prefix)
    return any(word not in DECLARATION_MODIFIERS for word in words)


def _matching_java_annotation_delimiter(text: str, start: int) -> int:
    pairs = {"(": ")", "[": "]", "{": "}"}
    opening = text[start]
    stack = [opening]
    quote = None
    escaped = False
    for index in range(start + 1, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char in pairs:
            stack.append(char)
        elif char in pairs.values():
            if not stack or pairs[stack[-1]] != char:
                return -1
            stack.pop()
            if not stack:
                return index
    return -1


def _strip_java_inline_annotations(line: str) -> str | None:
    remainder = line.lstrip()
    if not remainder.startswith("@"):
        return remainder
    while remainder.startswith("@"):
        annotation = re.match(r"@[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*", remainder)
        if not annotation:
            return None
        index = annotation.end()
        while index < len(remainder) and remainder[index].isspace():
            index += 1
        if index < len(remainder) and remainder[index] == "(":
            end = _matching_java_annotation_delimiter(remainder, index)
            if end < 0:
                return None
            index = end + 1
        remainder = remainder[index:].lstrip()
    return remainder


def is_c_family_declaration(
    line: str,
    match: re.Match[str],
    language: str,
    enclosing_types: frozenset[str],
) -> bool:
    prefix = line[: match.start(1)].strip()
    if _has_return_type(prefix):
        return True
    return language in C_FAMILY_LANGUAGES and match.group(1) in enclosing_types and not prefix.endswith(".")


def _matching_java_generic_delimiter(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "<":
            depth += 1
        elif text[index] == ">":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _detect_java_generic_method(line: str, prefix: str) -> str | None:
    opening = re.match(prefix + r"<", line)
    if not opening or "(" not in line:
        return None
    generic_end = _matching_java_generic_delimiter(line, opening.end() - 1)
    if generic_end < 0:
        return None
    before_parameters = line[: line.find("(")].rstrip()
    remainder = before_parameters[generic_end + 1 :]
    method = re.search(r"([A-Za-z_$][A-Za-z0-9_$]*)\s*$", remainder)
    if not method:
        return None
    return_type = remainder[: method.start()].strip()
    if not return_type or "." in return_type:
        return None
    return method.group(1)


_CSHARP_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
_CSHARP_TYPE_ARGUMENTS = r"(?:\s*<[^(){};]+>)?"
_CSHARP_EXPLICIT_INTERFACE = re.compile(
    r"^(?:\[[^]\n]+\]\s*)*"
    r"(?:(?:async|unsafe|readonly|ref|scoped)\s+)*"
    r"(?:[A-Za-z_][A-Za-z0-9_:.?]*(?:\s*<[^(){};]+>)?(?:\s*\[\])?)\s+"
    r"(?P<qualifier>(?:global::)?"
    + _CSHARP_IDENTIFIER
    + _CSHARP_TYPE_ARGUMENTS
    + r"(?:\s*\.\s*"
    + _CSHARP_IDENTIFIER
    + _CSHARP_TYPE_ARGUMENTS
    + r")*)\s*\.\s*"
    r"(?P<name>" + _CSHARP_IDENTIFIER + r")"
    r"(?:\s*<[^>]+>)?\s*\("
)


def detect_csharp_explicit_interface(line: str) -> str | None:
    match = _CSHARP_EXPLICIT_INTERFACE.match(line.strip())
    return match.group("name") if match else None


def detect_c_family(
    line: str,
    language: str = "",
    enclosing_types: frozenset[str] = frozenset(),
) -> str | None:
    candidate = _strip_java_inline_annotations(line) if language == "java" else line
    if candidate is None or "(" not in candidate:
        return None
    special = objective_c_selector(candidate) if language == "objective_c" else None
    if language == "cpp":
        special = detect_cpp_destructor(candidate) or detect_cpp_operator(candidate)
    elif language == "csharp":
        special = detect_csharp_explicit_interface(candidate)
    if special:
        return special
    prefix = (
        r"(?:\[[^\]]+\]\s*)*"
        r"(?:(?:public|private|protected|internal|static|virtual|override|async|"
        r"sealed|extern|unsafe|partial|new|final|synchronized|abstract)\s+)*"
    )
    if language == "java":
        generic_method = _detect_java_generic_method(candidate, prefix)
        if generic_method and generic_method not in CONTROL_WORDS:
            return generic_method
    patterns = (
        prefix + r"\S+\s+([A-Za-z_][A-Za-z0-9_]*)\s*<[^>]+>\s*\(",
        prefix + r"<[^>]+>\s+\S+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        prefix + r"(?:<[^>]+>\s+)?(?:[A-Za-z_][A-Za-z0-9_<>,\[\].?]+?\s+)?"
        r"([A-Za-z_][A-Za-z0-9_]*)(?:\s*<[^>]+>)?\s*\(",
    )
    for pattern in patterns:
        match = re.match(pattern, candidate)
        if (
            match
            and match.group(1) not in CONTROL_WORDS
            and is_c_family_declaration(candidate, match, language, enclosing_types)
        ):
            return match.group(1)
    return None


def detect_with_context(
    detector,
    line: str,
    language: str,
    enclosing_types: frozenset[str],
    allow_method_fallback: bool,
):
    if language in {"javascript", "typescript"}:
        return detector(line, allow_method_fallback)
    if language == "csharp":
        return detector(line, enclosing_types)
    if language in C_FAMILY_LANGUAGES:
        return detector(line, language, enclosing_types)
    return detector(line)
