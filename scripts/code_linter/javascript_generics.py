from __future__ import annotations

import re


def generic_angle_open(text: str, index: int) -> bool:
    previous = text[index - 1] if index else ""
    if index + 1 >= len(text) or text[index + 1].isspace():
        return False
    return bool(
        (previous.isalnum() or previous in "_$=([{,")
        and re.match(r"[A-Za-z_$][\w$]*\s*(?:extends|[>,=])", text[index + 1 :])
    )


def generic_parameter_opening(signature: str, start: int = 0) -> int:
    depth = 0
    for index in range(start, len(signature)):
        char = signature[index]
        if char == "<":
            depth += 1
        elif char == ">" and (index == 0 or signature[index - 1] != "="):
            depth -= 1
        elif char == "(" and depth == 0:
            return index
    return -1


def method_generic_parameter_opening(signature: str, name: str) -> int:
    start = signature.find(name)
    if start < 0:
        return -1
    remainder = signature[start + len(name) :].lstrip()
    if remainder.startswith("="):
        remainder = remainder[1:].lstrip()
    if not remainder.startswith("<"):
        return -1
    opening = generic_parameter_opening(remainder)
    if opening < 0:
        return -1
    return signature.find(remainder) + opening
