from __future__ import annotations

import ast
import re

from .model import Issue
from .ruby import RUBY_BLOCK_START, RUBY_DEF_PATTERN, is_endless_ruby_method, ruby_code_lines
from .scanner import CStyleScanState, brace_events, scan_c_style_line, scan_c_style_lines
from .shell import shell_nesting_issues

NESTING_KEYWORD = re.compile(
    r"^\s*(?:\}\s*)*"
    r"(?:[A-Za-z_][A-Za-z0-9_]*:\s*)?(?:await\s+)?"
    r"\b(?:if|else|for|foreach|while|switch|try|catch|guard|do|repeat|when|"
    r"lock|using|synchronized|loop|match|select|defer)\b"
)
INLINE_UNBRACED_KEYWORD = re.compile(r"(?<![A-Za-z0-9_.])(?:if|for|foreach|while|lock|using)\b")
UNBRACED_LANGUAGES = {
    "c",
    "cpp",
    "csharp",
    "dart",
    "groovy",
    "java",
    "javascript",
    "objective_c",
    "scala",
    "typescript",
    "kotlin",
}


def check_nesting_depth(relative: str, text: str, language: str, max_depth: int) -> list[Issue]:
    if language == "python":
        return python_nesting_issues(relative, text, max_depth)
    if language == "ruby":
        return ruby_nesting_issues(relative, text, max_depth)
    if language == "shell":
        return shell_nesting_issues(relative, text, max_depth)
    issues = c_style_nesting_issues(relative, text, language, max_depth)
    issues.extend(unbraced_nesting_issues(relative, text, language, max_depth))
    if language == "php":
        issues.extend(php_alternative_nesting_issues(relative, text, max_depth))
    return issues


def nesting_issue(relative: str, line: int, depth: int, max_depth: int) -> Issue:
    return Issue(
        path=relative,
        line=line,
        kind="nesting_depth",
        message=f"Nesting depth is {depth}; limit is {max_depth}.",
    )


def python_nesting_issues(relative: str, text: str, max_depth: int) -> list[Issue]:
    issues: list[Issue] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return issues

    match_types = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.With,
        ast.AsyncWith,
        getattr(ast, "Match", type(None)),
    )

    def walk(node: ast.AST, depth: int, parent: ast.AST | None = None) -> None:
        for child in ast.iter_child_nodes(node):
            next_depth = depth
            if isinstance(child, match_types):
                is_elif = (
                    isinstance(child, ast.If)
                    and isinstance(parent, ast.If)
                    and any(child is other for other in parent.orelse)
                )
                if not is_elif:
                    next_depth = depth + 1
                    if next_depth > max_depth:
                        issues.append(
                            nesting_issue(
                                relative,
                                getattr(child, "lineno", 1),
                                next_depth,
                                max_depth,
                            )
                        )
            walk(child, next_depth, parent=child)

    walk(tree, 0)
    return issues


def ruby_nesting_issues(relative: str, text: str, max_depth: int) -> list[Issue]:
    issues = []
    frames: list[bool] = []
    depth = 0
    for line_number, line in ruby_code_lines(text):
        stripped = line.strip()
        def_match = RUBY_DEF_PATTERN.match(stripped)
        endless = bool(def_match and is_endless_ruby_method(stripped[def_match.end() :]))
        declaration = None if endless else re.match(r"(?:def|class|module)\b", stripped)
        logical = not declaration and RUBY_BLOCK_START.search(line) is not None
        if declaration or logical:
            frames.append(logical)
            if logical:
                depth += 1
                if depth > max_depth:
                    issues.append(nesting_issue(relative, line_number, depth, max_depth))
        for _ in re.finditer(r"(^|[^A-Za-z0-9_])end([^A-Za-z0-9_]|$)", line):
            if frames and frames.pop():
                depth -= 1
    return issues


def unbraced_nesting_issues(relative: str, text: str, language: str, max_depth: int) -> list[Issue]:
    if language not in UNBRACED_LANGUAGES:
        return []
    issues = []
    indents: list[int] = []
    brace_depths = control_flow_brace_depths(text, language)
    for line_number, (_, clean, _) in enumerate(scan_c_style_lines(text, language), start=1):
        if not clean.strip():
            continue
        indent = len(clean) - len(clean.lstrip())
        while indents and indent <= indents[-1]:
            indents.pop()
        match = NESTING_KEYWORD.search(clean)
        inline_depth = inline_unbraced_depth(clean, language) if "{" not in clean else 0
        if not match or "{" in clean[match.end() :] or inline_depth == 0:
            continue
        if not clean.rstrip().endswith(";"):
            indents.extend([indent] * inline_depth)
        depth = brace_depths.get(line_number, 0) + len(indents)
        if clean.rstrip().endswith(";"):
            depth += inline_depth
        if depth > max_depth:
            issues.append(nesting_issue(relative, line_number, depth, max_depth))
    return issues


def php_alternative_nesting_issues(relative: str, text: str, max_depth: int) -> list[Issue]:
    issues = []
    depth = 0
    brace_depths = control_flow_brace_depths(text, "php")
    state = CStyleScanState()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        clean, _ = scan_c_style_line(raw_line, "php", state)
        if re.search(r"\b(?:endif|endforeach|endfor|endwhile|endswitch)\s*;", clean):
            depth = max(0, depth - 1)
        if re.search(r"^\s*(?:if|foreach|for|while|switch)\b.*:\s*$", clean):
            depth += 1
            effective_depth = depth + brace_depths.get(line_number, 0)
            if effective_depth > max_depth:
                issues.append(nesting_issue(relative, line_number, effective_depth, max_depth))
    return issues


def c_style_nesting_issues(relative: str, text: str, language: str, max_depth: int) -> list[Issue]:
    """Counts only braces a control-flow keyword opened.

    Counting every `{` made a type declaration, a method and each enclosing
    closure eat a level, so an ordinary `if` inside a SwiftUI body reported
    depth 7. Only `if`/`for`/`while`/... blocks are nesting a reader has to
    track, so those are the only frames that raise the depth.
    """
    issues: list[Issue] = []
    depth = 0
    php_alternative_before = php_alternative_depth_before(text) if language == "php" else {}
    for event in brace_events(text, language, NESTING_KEYWORD):
        if not event.triggered:
            continue
        if event.kind == "open":
            depth += 1
            effective_depth = depth + php_alternative_before.get(event.line, 0)
            if effective_depth > max_depth:
                issues.append(nesting_issue(relative, event.line, effective_depth, max_depth))
        elif event.kind == "close":
            depth -= 1
    return issues


def inline_unbraced_depth(line: str, language: str) -> int:
    if language not in UNBRACED_LANGUAGES:
        return 0
    depth = 0
    parentheses = 0
    index = 0
    while index < len(line):
        match = INLINE_UNBRACED_KEYWORD.match(line, index)
        if match and parentheses == 0:
            keyword = match.group(0)
            if keyword not in {"lock", "using"} or re.match(r"\s*\(", line[match.end() :]):
                depth += 1
            index = match.end()
            continue
        if line[index] == "(":
            parentheses += 1
        elif line[index] == ")":
            parentheses = max(0, parentheses - 1)
        index += 1
    return depth


def control_flow_brace_depths(text: str, language: str) -> dict[int, int]:
    depths: dict[int, int] = {}
    depth = 0
    events_by_line = {}
    for event in brace_events(text, language, NESTING_KEYWORD):
        events_by_line.setdefault(event.line, []).append(event)
    for line_number in range(1, len(text.splitlines()) + 1):
        for event in events_by_line.get(line_number, []):
            if not event.triggered:
                continue
            if event.kind == "open":
                depth += 1
            elif event.kind == "close":
                depth = max(0, depth - 1)
        depths[line_number] = depth
    return depths


def php_alternative_depth_before(text: str) -> dict[int, int]:
    before: dict[int, int] = {}
    depth = 0
    state = CStyleScanState()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        before[line_number] = depth
        clean, _ = scan_c_style_line(raw_line, "php", state)
        if re.search(r"\b(?:endif|endforeach|endfor|endwhile|endswitch)\s*;", clean):
            depth = max(0, depth - 1)
        if re.search(r"^\s*(?:if|foreach|for|while|switch)\b.*:\s*$", clean):
            depth += 1
    return before
