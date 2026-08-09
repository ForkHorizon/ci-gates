from __future__ import annotations

import re


PHP_NAMED_FUNCTION = re.compile(r"\bfunction\s+&?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")
PHP_ANONYMOUS_FUNCTION = re.compile(r"\bfunction\s*&?\s*\(")
PHP_ARROW_FUNCTION = re.compile(r"\bfn\s*\(")
PHP_CLOSURE_PARAMETERS = re.compile(r"\b(?:function\s*&?\s*|fn\s*)\(")


def detect_php(line: str) -> str | None:
    named = PHP_NAMED_FUNCTION.search(line)
    if named:
        return named.group(1)
    if PHP_ANONYMOUS_FUNCTION.search(line) or PHP_ARROW_FUNCTION.search(line):
        return "<anonymous>"
    return None


def php_parameter_start(signature: str) -> tuple[int, int]:
    match = PHP_CLOSURE_PARAMETERS.search(signature)
    if match:
        return match.end() - 1, 0
    return signature.find("("), 0
