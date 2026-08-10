from __future__ import annotations

import re


_METHOD_START = re.compile(r"^\s*[-+]\s*\(")
_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
_UNARY_SELECTOR = re.compile(r"^\s*(" + _IDENTIFIER + r")\s*(?:\{|;|$)")


def objective_c_method_start(line: str) -> bool:
    return bool(_METHOD_START.match(line))


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


def _declaration_remainder(signature: str, start: int) -> str:
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    for index in range(start, len(signature)):
        char = signature[index]
        if char in depths:
            depths[char] += 1
        elif char in closing:
            depths[closing[char]] = max(0, depths[closing[char]] - 1)
        elif char in "{;" and not any(depths.values()):
            return signature[start:index]
    return signature[start:]


def _top_level_selector_labels(remainder: str) -> list[str]:
    labels = []
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    for index, char in enumerate(remainder):
        if char in depths:
            depths[char] += 1
        elif char in closing:
            depths[closing[char]] = max(0, depths[closing[char]] - 1)
        elif char == ":" and not any(depths.values()):
            match = re.search(_IDENTIFIER + r"\s*$", remainder[:index])
            if match:
                labels.append(match.group(0).strip())
    return labels


def objective_c_selector(signature: str) -> str | None:
    """Return an Objective-C selector name from a method signature."""
    start = _METHOD_START.match(signature)
    if not start:
        return None
    opening = signature.find("(", start.start())
    closing = _matching_close_parenthesis(signature, opening)
    if closing < 0:
        return None
    remainder = _declaration_remainder(signature, closing + 1)
    labels = _top_level_selector_labels(remainder)
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
