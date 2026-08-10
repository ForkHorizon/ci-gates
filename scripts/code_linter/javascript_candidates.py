from __future__ import annotations

import re

from .javascript_generics import generic_parameter_opening


def javascript_arrow_assignment_candidate(line: str) -> bool:
    return bool(
        re.match(
            r"^\s*(?:(?:export\s+)?(?:const|let|var)\s+[A-Za-z_$][A-Za-z0-9_$]*|module\.exports)\s*=\s*(?:\(|<)",
            line,
        )
    )


def javascript_assignment_name(line: str) -> str | None:
    match = re.match(
        r"^\s*(?:(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)|module\.exports)\s*=",
        line,
    )
    return match.group(1) if match and match.group(1) else None


def javascript_semicolon_fragments(clean: str, allow_continuation: bool = False) -> list[str]:
    if allow_continuation:
        return [clean]
    split_inside_braces = bool(re.search(r"\bdeclare\b", clean))
    parts: list[str] = []
    start = 0
    depths = {"(": 0, "[": 0, "{": 0}
    for index, char in enumerate(clean):
        if char in depths:
            depths[char] += 1
        elif char == ")":
            depths["("] = max(0, depths["("] - 1)
        elif char == "]":
            depths["["] = max(0, depths["["] - 1)
        elif char == "}":
            depths["{"] = max(0, depths["{"] - 1)
        elif char == ";" and not depths["("] and not depths["["] and (split_inside_braces or not depths["{"]):
            parts.append(clean[start : index + 1].strip())
            start = index + 1
    remainder = clean[start:].strip()
    if remainder:
        parts.append(remainder)
    return parts or [clean]


def javascript_header_candidate(line: str) -> bool:
    stripped = line.strip()
    if not stripped or ";" in stripped:
        return False
    field_start = re.match(
        r"^(?:(?:async|static|abstract|declare|override|public|private|protected|readonly)\s+)*"
        r"#?[A-Za-z_$][A-Za-z0-9_$]*\s*=\s*(?:\(|<)",
        stripped,
    )
    generic_start = re.match(
        r"^(?:(?:async|static|get|set|abstract|declare|override|public|private|protected|readonly)\s+)*"
        r"#?[A-Za-z_$][A-Za-z0-9_$]*\s*<",
        stripped,
    )
    if "{" in stripped and not field_start and not generic_start:
        return False
    arrow_assignment = javascript_arrow_assignment_candidate(stripped)
    if "=" in stripped and not field_start and not arrow_assignment:
        return False
    return bool(
        re.match(
            r"^(?:async|static|get|set|abstract|declare|override|public|private|"
            r"protected|readonly|\*|#|\[|\(|\]|[A-Za-z_$][A-Za-z0-9_$]*$)",
            stripped,
        )
        or stripped.endswith("<")
        or field_start
        or generic_start
        or arrow_assignment
    )


def javascript_candidate_continues(candidate: list[str], clean: str) -> bool:
    stripped = clean.strip()
    if not stripped or ";" in stripped:
        return False
    text = " ".join(candidate)
    if javascript_arrow_assignment_candidate(text) and text.count("(") > text.count(")"):
        return True
    if "<" in text and generic_parameter_opening(text, text.find("<")) < 0:
        return True
    if "{" in text and "}" not in text:
        return True
    if "=" in stripped and "=>" not in stripped:
        return False
    text = text.lstrip()
    return bool(
        text.startswith("[")
        or ("<" in text and re.match(r"[A-Za-z_$][A-Za-z0-9_$]*\s*<", text))
        or javascript_header_candidate(clean)
    )


def javascript_new_method_start(line: str, signature: str = "") -> bool:
    stripped = line.strip()
    if signature.count("(") > signature.count(")") or signature.count("[") > signature.count("]"):
        return False
    header = stripped.split("{", 1)[0].split(";", 1)[0].rstrip()
    if not header or "=" in header:
        return False
    method_start = bool(
        re.match(
            r"^(?:(?:async|static|get|set|abstract|declare|override|public|private|"
            r"protected|readonly)\b\s+|\*\s*|#|\[)",
            header,
        )
        or re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*\s*\(", header)
    )
    return method_start
