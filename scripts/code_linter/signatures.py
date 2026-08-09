from __future__ import annotations

import re

from .literals import strip_strings


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
    typed = re.search(r"(?:\[[^\]]*\]\s*)?(\([^()]*\))\s*in\b", signature)
    if typed:
        return typed.start(1), 0
    untyped = re.search(r"\{\s*(?:\[[^\]]*\]\s*)?([^{}\n]+?)\s+in\b", signature)
    if untyped:
        return -1, top_level_parameter_count(untyped.group(1))
    return signature.find("("), 0


def _csharp_parameter_start(signature: str) -> tuple[int, int]:
    arrow = re.search(r"\(([^()]*)\)\s*=>", signature)
    if arrow:
        return arrow.start(), 0
    bare = re.search(r"\b[A-Za-z_][A-Za-z0-9_]*\s*=>", signature)
    return -1, 1 if bare else 0


ANONYMOUS_PARAMETER_START = {
    "csharp": _csharp_parameter_start,
    "javascript": _javascript_parameter_start,
    "swift": _swift_parameter_start,
    "typescript": _javascript_parameter_start,
}


def parameter_start(signature: str, name: str | None, language: str) -> tuple[int, int]:
    if name == "<anonymous>":
        parser = ANONYMOUS_PARAMETER_START.get(language)
        if parser:
            return parser(signature)
    if name and name.isidentifier():
        anchored = re.search(
            r"\b" + re.escape(name) + r"\b\s*(?:<[^<>]*>|\[[^\[\]]*\])?\s*\(",
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
        name == "<anonymous>" and language in {"javascript", "typescript"} and re.search(r"\bfunction\b", signature)
    )
    if not waiting:
        return braces, False
    parameter_index, _ = parameter_start(signature, name, language)
    parameter_end = matching_paren(signature, parameter_index)
    if parameter_end < 0:
        return (0, 0), True
    body = signature[parameter_end + 1 :]
    return (body.count("{"), body.count("}")), True


def detect_swift(line: str) -> str | None:
    match = re.search(r"\bfunc\s+(?:`([^`]+)`|([A-Za-z_][A-Za-z0-9_]*)|([^\s<(]+))", line)
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


def detect_javascript(line: str) -> str | None:
    patterns = (
        r"\bfunction\s*\*?\s*([A-Za-z_$][A-Za-z0-9_$]*)(?:\s*<[^>]+>)?\s*\(",
        r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=.*=>",
        r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\(?\s*$",
        r"(?:static\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?.*=>",
        r"(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?\*?\s*"
        r"([A-Za-z_$][A-Za-z0-9_$]*)\s*\([^)]*\)\s*\{?",
    )
    for index, pattern in enumerate(patterns):
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


def detect_csharp_lambda(line: str) -> str | None:
    if "=>" not in line:
        return None
    parenthesized = re.search(r"\(([^()]*)\)\s*=>", line)
    if parenthesized:
        prefix = line[: parenthesized.start()].rstrip()
        if prefix.endswith(("=", "(", ",", ":")):
            return "<anonymous>"
    bare = re.search(r"\b[A-Za-z_][A-Za-z0-9_]*\s*=>", line)
    if bare and line[: bare.start()].rstrip().endswith(("=", "(", ",", ":")):
        return "<anonymous>"
    return None


def detect_csharp(line: str) -> str | None:
    destructor = re.match(r"~([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
    if destructor:
        return "~" + destructor.group(1)
    return detect_csharp_lambda(line) or detect_c_family(line)


def detect_c_family(line: str) -> str | None:
    if "(" not in line:
        return None
    prefix = (
        r"(?:\[[^\]]+\]\s*)*"
        r"(?:(?:public|private|protected|internal|static|virtual|override|async|"
        r"sealed|extern|unsafe|partial|new|final|synchronized|abstract)\s+)*"
    )
    patterns = (
        prefix + r"\S+\s+([A-Za-z_][A-Za-z0-9_]*)\s*<[^>]+>\s*\(",
        prefix + r"<[^>]+>\s+\S+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        prefix + r"(?:<[^>]+>\s+)?(?:[A-Za-z_][A-Za-z0-9_<>,\[\].?]+?\s+)?"
        r"([A-Za-z_][A-Za-z0-9_]*)(?:\s*<[^>]+>)?\s*\(",
    )
    for pattern in patterns:
        match = re.match(pattern, line)
        if match and match.group(1) not in CONTROL_WORDS:
            return match.group(1)
    return None


def detect_rust(line: str) -> str | None:
    match = re.search(r"\bfn\s+([A-Za-z_][A-Za-z0-9_]*)\s*[<(]", line)
    return match.group(1) if match else None


def detect_php(line: str) -> str | None:
    match = re.search(r"\bfunction\s+&?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
    return match.group(1) if match else None


def detect_brace_function(line: str, language: str) -> str | None:
    if not line:
        return None
    first_word = re.match(r"(?:@\w+\s+)*(?:[A-Za-z_][A-Za-z0-9_]*)", line)
    if first_word and first_word.group(0).split()[0] in CONTROL_WORDS:
        return None
    detector = BRACE_FUNCTION_DETECTORS.get(language)
    return detector(line) if detector else None


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
    "typescript": detect_javascript,
}
