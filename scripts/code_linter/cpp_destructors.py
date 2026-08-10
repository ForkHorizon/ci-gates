from __future__ import annotations

import re


_DESTRUCTOR = re.compile(
    r"(?:^|[;{}])\s*(?:\[\[[^\]]+\]\s*)*"
    r"(?:(?:inline|virtual|friend|constexpr|consteval|explicit)\s+)*"
    r"(?:(?:[A-Za-z_][A-Za-z0-9_]*\s*::\s*)*)"
    r"~(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\("
)


def detect_cpp_destructor(line: str) -> str | None:
    match = _DESTRUCTOR.search(line)
    return "~" + match.group("name") if match else None


def cpp_destructor_signature_complete(signature: str) -> bool:
    return signature.count("(") == signature.count(")")


def cpp_destructor_has_body(signature: str) -> bool:
    close = signature.find(")")
    return close >= 0 and "{" in signature[close + 1 :]
