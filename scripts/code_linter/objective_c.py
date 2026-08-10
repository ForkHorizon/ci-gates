from __future__ import annotations

import re


_METHOD_START = re.compile(r"^\s*[-+]\s*\(")
_METHOD_PREFIX = re.compile(r"^\s*[-+](?:\s*\(|\s*$)")
_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"


def objective_c_method_start(line: str) -> bool:
    return bool(_METHOD_PREFIX.match(line))


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
        if char in "{;" and not any(depths.values()):
            return signature[start:index]
        if char in depths:
            depths[char] += 1
        elif char in closing:
            depths[closing[char]] = max(0, depths[closing[char]] - 1)
    return signature[start:]


def _top_level_selector_labels(remainder: str) -> list[tuple[str, int]]:
    labels: list[tuple[str, int]] = []
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
                labels.append((match.group(0).strip(), index))
    return labels


def _matching_double_close(text: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _unary_selector_name(remainder: str) -> str | None:
    match = re.match(r"^\s*(" + _IDENTIFIER + r")\b", remainder)
    if not match:
        return None
    tail = remainder[match.end() :].strip()
    while tail:
        attribute = re.match(r"__attribute__\s*\(\(", tail)
        if not attribute:
            return None
        close = _matching_double_close(tail, attribute.end() - 2)
        if close < 0:
            return None
        tail = tail[close + 1 :].strip()
    return match.group(1)


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
        for index, (_, colon) in enumerate(labels):
            next_colon = labels[index + 1][1] if index + 1 < len(labels) else len(remainder)
            argument = remainder[colon + 1 : next_colon].strip()
            if not argument.startswith("("):
                return None
        return "".join(f"{label}:" for label, _ in labels)
    return _unary_selector_name(remainder)


def objective_c_parameter_count(signature: str) -> int:
    """Count selector arguments, treating an ellipsis as a variadic argument."""
    selector = objective_c_selector(signature)
    if selector is None:
        return 0
    return selector.count(":") + int("..." in signature)
