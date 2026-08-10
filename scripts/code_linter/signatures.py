from __future__ import annotations

import re

from .cpp_operators import cpp_operator_parameter_start
from .declaration_helpers import (
    CONTROL_WORDS,
    detect_c_family,
    detect_with_context,
)
from .literals import strip_strings
from .objective_c import objective_c_parameter_count, objective_c_selector
from .php_signatures import detect_php, php_parameter_start
from .swift_syntax import detect_swift
from .javascript_methods import detect_javascript, detect_typescript


def _javascript_parameter_start(signature: str) -> tuple[int, int]:
    function_expression = re.search(
        r"\b(?:async\s+)?function\s*\*?\s*(?:<[^(){}]*>)?\s*\(",
        signature,
    )
    if function_expression:
        return function_expression.end() - 1, 0
    arrow = re.search(r"\(([^()]*)\)\s*=>", signature)
    if arrow:
        return arrow.start(), 0
    bare = re.search(r"\b[A-Za-z_$][A-Za-z0-9_$]*\s*=>", signature)
    return -1, 1 if bare else 0


def _swift_parameter_start(signature: str) -> tuple[int, int]:
    marker = re.search(r"\bin\b", signature)
    if marker:
        close = marker.start() - 1
        while close >= 0 and signature[close].isspace():
            close -= 1
        if close >= 0 and signature[close] == ")":
            start = _matching_open_paren(signature, close)
            if start >= 0:
                return start, 0
    untyped = re.search(r"\{\s*(?:\[[^\]]*\]\s*)?([^{}]+?)\s+in\b", signature)
    if untyped:
        return -1, top_level_parameter_count(untyped.group(1))
    return signature.find("("), 0


def _csharp_parameter_start(signature: str) -> tuple[int, int]:
    match = csharp_lambda_match(signature)
    if match:
        start, _, _, bare = match
        return (-1, 1) if bare else (start, 0)
    return -1, 0


ANONYMOUS_PARAMETER_START = {
    "csharp": _csharp_parameter_start,
    "javascript": _javascript_parameter_start,
    "php": php_parameter_start,
    "swift": _swift_parameter_start,
    "typescript": _javascript_parameter_start,
}


def parameter_start(signature: str, name: str | None, language: str) -> tuple[int, int]:
    if name == "<anonymous>":
        parser = ANONYMOUS_PARAMETER_START.get(language)
        if parser:
            return parser(signature)
    if name and name.startswith("operator"):
        operator_start = cpp_operator_parameter_start(signature, name)
        if operator_start >= 0:
            return operator_start, 0
    if name and name != "<anonymous>":
        field_arrow = re.search(
            re.escape(name)
            + r"\s*=\s*(?:async\s+)?(?:\([^()]*\)|[A-Za-z_$][A-Za-z0-9_$]*)"
            + r"(?:\s*:\s*[^=,{]+)?\s*=>",
            signature,
        )
        if field_arrow:
            if "(" in field_arrow.group(0):
                return signature.find("(", field_arrow.start()), 0
            return -1, 1
        anchored = re.search(
            re.escape(name) + r"\s*(?:<[^<>]*>|\[[^\[\]]*\])?\s*\(",
            signature,
        )
        if anchored:
            return anchored.end() - 1, 0
    return signature.find("("), 0


def matching_paren(signature: str, start: int) -> int:
    depth = 0
    for index in range(start, len(signature)):
        if signature[index] == "(":
            depth += 1
        elif signature[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def top_level_parameter_count(parameters: str) -> int:
    if not parameters.strip():
        return 0
    depth = 0
    count = 1
    for char in parameters:
        if char in "(<{[":
            depth += 1
        elif char in ")>}]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            count += 1
    return count


def count_params_in_signature(signature_line: str, name: str | None = None, language: str = "") -> int:
    signature = strip_strings(signature_line, language)
    if language == "objective_c" and objective_c_selector(signature) is not None:
        return objective_c_parameter_count(signature)
    start, bare_count = parameter_start(signature, name, language)
    if start < 0:
        return bare_count
    end = matching_paren(signature, start)
    if end <= start:
        return 0
    return top_level_parameter_count(signature[start + 1 : end])


def pending_body_braces(
    signature: str,
    name: str,
    language: str,
    braces: tuple[int, int],
) -> tuple[tuple[int, int], bool]:
    waiting = (
        name == "<anonymous>"
        and language in {"javascript", "typescript", "php"}
        and re.search(r"\bfunction\b", signature)
    )
    if not waiting:
        if language in {"javascript", "typescript"} and name != "<anonymous>":
            parameter_index, _ = parameter_start(signature, name, language)
            parameter_end = matching_paren(signature, parameter_index)
            if parameter_end >= 0:
                body = signature[parameter_end + 1 :]
                return (body.count("{"), body.count("}")), False
            return (0, 0), False
        return braces, False
    parameter_index, _ = parameter_start(signature, name, language)
    parameter_end = matching_paren(signature, parameter_index)
    if parameter_end < 0:
        return (0, 0), True
    body = signature[parameter_end + 1 :]
    return (body.count("{"), body.count("}")), True


def detect_kotlin(line: str) -> str | None:
    match = re.search(
        r"\bfun\s+(?:<[^>]+>\s+)?(?:[A-Za-z_][A-Za-z0-9_<>?.]*\.)?"
        r"(?:`([^`]+)`|([A-Za-z_][A-Za-z0-9_]*))",
        line,
    )
    if match:
        return match.group(1) or match.group(2)
    return "constructor" if re.search(r"\bconstructor\s*\(", line) else None


def detect_go(line: str) -> str | None:
    match = re.search(
        r"\bfunc\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)"
        r"(?:\s*\[[^]]+\])?\s*\(",
        line,
    ) or re.match(r"\)\s*([A-Za-z_][A-Za-z0-9_]*)(?:\s*\[[^]]+\])?\s*\(", line)
    if match and match.group(1) not in CONTROL_WORDS:
        return match.group(1)
    return "<anonymous>" if re.search(r"\bfunc\s*\(", line) else None


def _matching_open_paren(signature: str, close: int) -> int:
    depth = 0
    for index in range(close, -1, -1):
        if signature[index] == ")":
            depth += 1
        elif signature[index] == "(":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _csharp_lambda_context(prefix: str) -> bool:
    prefix = prefix.rstrip()
    return not prefix or bool(
        re.search(
            r"(?:=|\(|,|:|\?|=>|\b(?:async|await|case|return|throw|yield\s+return))\s*$",
            prefix,
        )
    )


def csharp_lambda_match(signature: str) -> tuple[int, int, int, bool] | None:
    """Return parameter bounds and arrow position for a contextual C# lambda."""
    for arrow in re.finditer(r"=>", signature):
        before = signature[: arrow.start()].rstrip()
        if before.endswith(")"):
            parameter_end = len(before) - 1
            parameter_start = _matching_open_paren(before, parameter_end)
            if parameter_start < 0:
                continue
            prefix = before[:parameter_start]
            if _csharp_lambda_context(prefix):
                return parameter_start, parameter_end, arrow.start(), False
        else:
            bare = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", before)
            if bare and _csharp_lambda_context(before[: bare.start()]):
                return bare.start(1), bare.end(1), arrow.start(), True
    return None


def detect_csharp_lambda(line: str) -> str | None:
    return "<anonymous>" if csharp_lambda_match(line) else None


def detect_csharp(
    line: str,
    enclosing_types: frozenset[str] = frozenset(),
) -> str | None:
    destructor = re.match(r"~([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
    if destructor:
        return "~" + destructor.group(1)
    return detect_csharp_lambda(line) or detect_c_family(line, "csharp", enclosing_types)


def detect_rust(line: str) -> str | None:
    match = re.search(r"\bfn\s+([A-Za-z_][A-Za-z0-9_]*)\s*[<(]", line)
    return match.group(1) if match else None


def detect_brace_function(
    line: str,
    language: str,
    enclosing_types: frozenset[str] = frozenset(),
    allow_method_fallback: bool = False,
) -> str | None:
    if not line:
        return None
    first_word = re.match(r"(?:@\w+\s+)*(?:[A-Za-z_][A-Za-z0-9_]*)", line)
    if first_word and first_word.group(0).split()[0] in CONTROL_WORDS:
        return None
    detector = BRACE_FUNCTION_DETECTORS.get(language)
    if not detector:
        return None
    return detect_with_context(detector, line, language, enclosing_types, allow_method_fallback)


BRACE_FUNCTION_DETECTORS = {
    "c": detect_c_family,
    "cpp": detect_c_family,
    "csharp": detect_csharp,
    "dart": detect_c_family,
    "go": detect_go,
    "groovy": detect_c_family,
    "java": detect_c_family,
    "javascript": detect_javascript,
    "kotlin": detect_kotlin,
    "objective_c": detect_c_family,
    "php": detect_php,
    "rust": detect_rust,
    "scala": detect_c_family,
    "swift": detect_swift,
    "typescript": detect_typescript,
}
