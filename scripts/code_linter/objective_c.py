from __future__ import annotations

import re


_METHOD_START = re.compile(r"^\s*[-+]\s*\(")
_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
_SELECTOR_LABEL = re.compile(r"\b(" + _IDENTIFIER + r")\s*:")
_UNARY_SELECTOR = re.compile(r"^\s*(" + _IDENTIFIER + r")\s*(?:\{|;|$)")


def _matching_close_parenthesis(signature: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(signature)):
        if signature[index] == "(":
            depth += 1
        elif signature[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def objective_c_selector(signature: str) -> str | None:
    """Return an Objective-C selector name from a method signature."""
    start = _METHOD_START.match(signature)
    if not start:
        return None
    opening = signature.find("(", start.start())
    closing = _matching_close_parenthesis(signature, opening)
    if closing < 0:
        return None
    remainder = signature[closing + 1 :]
    labels = _SELECTOR_LABEL.findall(remainder)
    if labels:
        return "".join(f"{label}:" for label in labels)
    unary = _UNARY_SELECTOR.match(remainder)
    return unary.group(1) if unary else None


def objective_c_parameter_count(signature: str) -> int:
    """Count selector arguments, treating an ellipsis as a variadic argument."""
    selector = objective_c_selector(signature)
    if selector is None:
        return 0
    return selector.count(":") + int("..." in signature)
