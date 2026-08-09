from __future__ import annotations

import ast
import io
import re
import tokenize
from collections.abc import Sequence

from .model import Issue
from .scanner import brace_events, scan_c_style_lines

DOC_LINE_PREFIXES = ("///", "//!")
LICENSE_HEADER_SCAN_LINES = 5
LICENSE_HEADER_MAX_LINES = 30


def python_comment_kinds(text: str) -> list[str | None]:
    """Real comment lines, via tokenize — a `#` opening a line inside a triple
    quoted string is string data, not a comment, and used to be counted."""
    lines = text.splitlines()
    comment_rows: dict[int, str] = {}
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            row, column = token.start
            if token.type != tokenize.COMMENT or row > len(lines):
                continue
            if lines[row - 1][:column].strip():
                continue  # trailing comment after code
            if row == 1 and token.string.startswith("#!"):
                continue
            comment_rows[row] = "doc" if token.string.startswith("#:") else "prose"
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Unparseable file: fall back to the prefix scan rather than reporting nothing.
        return [
            (
                "doc"
                if line.strip().startswith("#:")
                else "prose"
                if line.strip().startswith("#") and not (index == 0 and line.strip().startswith("#!"))
                else None
            )
            for index, line in enumerate(lines)
        ]
    return [comment_rows.get(row) for row in range(1, len(lines) + 1)]


def comment_line_kinds(text: str, language: str) -> list[str | None]:
    """Classify prose-only and documentation-only comment lines.

    Documentation comments (`///`, `//!`, `/** */`, `#:`) receive a separate
    limit so API documentation is allowed but cannot grow without bound.
    """
    if language == "python":
        return python_comment_kinds(text)

    if language == "ruby":
        flags = []
        for index, line in enumerate(text.splitlines()):
            stripped = line.strip()
            is_shebang = index == 0 and stripped.startswith("#!")
            flags.append("prose" if stripped.startswith("#") and not is_shebang else None)
        return flags

    if language == "shell":
        return ["prose" if is_comment else None for _, _, is_comment in scan_c_style_lines(text, language)]

    flags = []
    in_doc_block = False
    for raw, _, is_comment in scan_c_style_lines(text, language):
        stripped = raw.strip()
        if in_doc_block:
            is_doc = True
            in_doc_block = "*/" not in stripped
        elif stripped.startswith("/**"):
            is_doc = True
            in_doc_block = "*/" not in stripped[3:]
        else:
            is_doc = stripped.startswith(DOC_LINE_PREFIXES)
        flags.append("doc" if is_comment and is_doc else "prose" if is_comment else None)
    return flags


def comment_line_flags(text: str, language: str) -> list[bool]:
    """Return prose-comment flags; documentation comments are deliberately false."""
    return [kind == "prose" for kind in comment_line_kinds(text, language)]


def is_license_header(lines: Sequence[str]) -> bool:
    header = "\n".join(lines[:LICENSE_HEADER_SCAN_LINES]).lower()
    if re.search(r"\bspdx-license-identifier\s*:\s*\S+", header):
        return True
    return "copyright" in header and any(
        phrase in header
        for phrase in (
            "licensed under",
            "permission is hereby granted",
            "redistribution and use",
        )
    )


def comment_block_issue(
    relative: str,
    lines: list[str],
    block: tuple[int | None, str | None, int],
    limits: tuple[int, int],
) -> Issue | None:
    current_start, current_kind, count = block
    if current_start is None or current_kind is None:
        return None
    limit = limits[1] if current_kind == "doc" else limits[0]
    header_lines = lines[current_start - 1 : current_start - 1 + LICENSE_HEADER_SCAN_LINES]
    is_bounded_license = current_start == 1 and is_license_header(header_lines)
    allowed_limit = max(limit, LICENSE_HEADER_MAX_LINES) if is_bounded_license else limit
    if count <= allowed_limit:
        return None
    return Issue(
        path=relative,
        line=current_start,
        kind="doc_comment_block" if current_kind == "doc" else "comment_block",
        message=f"{current_kind.title()} comment block has {count} lines; limit is {allowed_limit}.",
    )


def check_comment_blocks(
    relative: str,
    text: str,
    language: str,
    max_comment_lines: int,
    max_doc_comment_lines: int = 50,
) -> list[Issue]:
    """Flag comment runs over their configured limit.

    Blank source lines inside a comment run do not reset its count, so prose
    cannot evade the limit by splitting into smaller visual paragraphs.
    """
    issues: list[Issue] = []
    current_start: int | None = None
    current_kind: str | None = None
    count = 0
    lines = text.splitlines()
    limits = (max_comment_lines, max_doc_comment_lines)

    for line_no, kind in enumerate(comment_line_kinds(text, language), start=1):
        if kind:
            if current_kind and kind != current_kind:
                current_kind = "prose"
            if count == 0:
                current_start = line_no
                current_kind = kind
            count += 1
            continue
        if current_kind and not lines[line_no - 1].strip():
            continue
        issue = comment_block_issue(relative, lines, (current_start, current_kind, count), limits)
        if issue is not None:
            issues.append(issue)
        count = 0
        current_start = None
        current_kind = None

    issue = comment_block_issue(relative, lines, (current_start, current_kind, count), limits)
    if issue is not None:
        issues.append(issue)
    return issues


TYPE_PATTERNS = {
    "c": r"\b(?:class|struct|union|enum)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "cpp": r"\b(?:class|struct|union|enum)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "objective_c": r"\b@(?:interface|protocol)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "dart": r"\b(?:class|mixin|enum|extension)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "scala": r"\b(?:class|trait|object|enum)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "groovy": r"\b(?:class|interface|trait|enum)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "csharp": r"\b(?:class|struct|interface|enum|record(?:\s+(?:class|struct))?)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "swift": r"\b(?:class|struct|enum|actor|protocol)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "go": r"\btype\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    # Bare `type X = …` aliases are omitted on purpose: they cost a reader
    # nothing, and three of them in a file is normal, not a structure problem.
    "typescript": r"\b(?:class|interface|enum)\s+([A-Za-z_$][A-Za-z0-9_$]*)",
    "javascript": r"\bclass\s+([A-Za-z_$][A-Za-z0-9_$]*)",
    "rust": r"\b(?:struct|enum|trait|union)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "php": r"\b(?:class|interface|enum|trait)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "kotlin": r"\b(?:class|interface|object|enum\s+class|typealias)\s+([A-Za-z_][A-Za-z0-9_]*)",
    "java": r"\b(?:class|interface|enum|record)\s+([A-Za-z_][A-Za-z0-9_]*)",
}

FALLBACK_TYPE_PATTERN = r"\b(?:class|struct|interface|enum|actor)\s+([A-Za-z_][A-Za-z0-9_]*)"


def brace_type_declarations(text: str, language: str) -> list[tuple[str, int]]:
    """Top-level type declarations only.

    A helper struct or enum nested inside the type it serves is one unit of
    reading, not two, so it doesn't count. Namespace/extension wrappers aren't
    type declarations either, so C# and Swift files still get counted properly.
    """
    pattern = re.compile(TYPE_PATTERNS.get(language, FALLBACK_TYPE_PATTERN))
    types: list[tuple[str, int]] = []
    inside_type = 0
    for event in brace_events(text, language, pattern):
        if event.kind == "trigger":
            if inside_type == 0 and event.match is not None:
                types.append((event.match.group(1), event.line))
        elif event.triggered:
            inside_type += 1 if event.kind == "open" else -1
    return types


def check_types_per_file(relative: str, text: str, language: str, max_types: int) -> list[Issue]:
    issues: list[Issue] = []
    types: list[tuple[str, int]] = []
    if language == "python":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            types = [(node.name, node.lineno) for node in tree.body if isinstance(node, ast.ClassDef)]
    elif language not in {"shell", "json", "toml"}:
        types = brace_type_declarations(text, language)

    if len(types) > max_types:
        first_violator = types[max_types]
        type_names = ", ".join(t[0] for t in types)
        issues.append(
            Issue(
                path=relative,
                line=first_violator[1],
                kind="types_per_file",
                message=f"File defines {len(types)} types ({type_names}); limit is {max_types}.",
            )
        )
    return issues
