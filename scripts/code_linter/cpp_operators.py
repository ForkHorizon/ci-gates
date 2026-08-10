from __future__ import annotations

import re


_OPERATOR_TOKEN = (
    r"(?:\(\)|\[\]|->\*|->|<<=|>>=|<=>|==|!=|<=|>=|<<|>>|"
    r"\+=|-=|\*=|/=|%=|\^=|&=|\|=|\+\+|--|&&|\|\||"
    r"\+|-|\*|/|%|\^|&|\||!|=|<|>|,|~|"
    r"new(?:\[\])?|delete(?:\[\])?|"
    r"[A-Za-z_][A-Za-z0-9_]*(?:\s*::\s*[A-Za-z_][A-Za-z0-9_]*)*(?:\s*[&*])?)"
)
_CPP_OPERATOR = re.compile(r"\boperator\s*(?P<name>" + _OPERATOR_TOKEN + r")\s*\(")
_CPP_OPERATOR_MODIFIERS = {
    "explicit",
    "inline",
    "friend",
    "static",
    "virtual",
    "constexpr",
    "consteval",
    "constinit",
}


def _formatted_operator_name(name: str) -> str:
    name = name.strip()
    return f"operator {name}" if name[0].isalpha() else f"operator{name}"


def _operator_prefix_is_declaration(prefix: str, name: str) -> bool:
    prefix = prefix.strip()
    if not prefix or prefix.endswith("."):
        return not prefix and name[0].isalpha()
    if re.search(r"\b(?:return|throw|case)\b", prefix):
        return False
    if prefix.endswith("::"):
        words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", prefix)
        return name[0].isalpha() or len(words) > 1
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", prefix)
    remaining = [word for word in words if word not in _CPP_OPERATOR_MODIFIERS]
    return bool(remaining) or (name[0].isalpha() and not remaining)


def detect_cpp_operator(line: str) -> str | None:
    match = _CPP_OPERATOR.search(line)
    if not match or not _operator_prefix_is_declaration(line[: match.start()], match.group("name")):
        return None
    return _formatted_operator_name(match.group("name"))


def cpp_operator_signature_complete(signature: str) -> bool:
    return signature.count("(") == signature.count(")")


def cpp_operator_parameter_start(signature: str, name: str | None) -> int:
    if not name or not name.startswith("operator"):
        return -1
    operator = re.search(r"\boperator\b", signature)
    if not operator:
        return -1
    start = signature.find("(", operator.end())
    if start < 0:
        return -1
    if signature.startswith("()", start):
        start = signature.find("(", start + 2)
    return start
