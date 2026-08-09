from __future__ import annotations

import re


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

DECLARATION_MODIFIERS = {
    "abstract",
    "async",
    "const",
    "extern",
    "final",
    "internal",
    "new",
    "override",
    "partial",
    "private",
    "protected",
    "public",
    "sealed",
    "static",
    "synchronized",
    "unsafe",
    "virtual",
}

C_FAMILY_LANGUAGES = {
    "c",
    "cpp",
    "csharp",
    "dart",
    "groovy",
    "java",
    "objective_c",
    "scala",
}


def _has_return_type(prefix: str) -> bool:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", prefix)
    return any(word not in DECLARATION_MODIFIERS for word in words)


def is_c_family_declaration(
    line: str,
    match: re.Match[str],
    language: str,
    enclosing_types: frozenset[str],
) -> bool:
    prefix = line[: match.start(1)].strip()
    if _has_return_type(prefix):
        return True
    return language in C_FAMILY_LANGUAGES and match.group(1) in enclosing_types and not prefix.endswith(".")


def detect_c_family(
    line: str,
    language: str = "",
    enclosing_types: frozenset[str] = frozenset(),
) -> str | None:
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
        if (
            match
            and match.group(1) not in CONTROL_WORDS
            and is_c_family_declaration(line, match, language, enclosing_types)
        ):
            return match.group(1)
    return None


def detect_with_context(
    detector,
    line: str,
    language: str,
    enclosing_types: frozenset[str],
    allow_method_fallback: bool,
):
    if language in {"javascript", "typescript"}:
        return detector(line, allow_method_fallback)
    if language == "csharp":
        return detector(line, enclosing_types)
    if language in C_FAMILY_LANGUAGES:
        return detector(line, language, enclosing_types)
    return detector(line)
