from __future__ import annotations

import ast
import re

from .model import Issue
from .ruby import RUBY_BLOCK_START, RUBY_DEF_PATTERN, is_endless_ruby_method, ruby_code_lines
from .scanner import CStyleScanState, brace_events, scan_c_style_line, scan_c_style_lines

NESTING_KEYWORD = re.compile(
    r"^\s*(?:\}\s*)*"
    r"(?:[A-Za-z_][A-Za-z0-9_]*:\s*)?(?:await\s+)?"
    r"\b(?:if|else|for|foreach|while|switch|try|catch|guard|do|repeat|when|"
    r"lock|using|synchronized|loop|match|select|defer)\b"
)


def check_nesting_depth(relative: str, text: str, language: str, max_depth: int) -> list[Issue]:
    if language == "python":
        return python_nesting_issues(relative, text, max_depth)
    if language == "ruby":
        return ruby_nesting_issues(relative, text, max_depth)
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
    if language not in {"csharp", "java", "javascript", "typescript", "kotlin"}:
        return []
    issues = []
    indents: list[int] = []
    for line_number, (_, clean, _) in enumerate(scan_c_style_lines(text, language), start=1):
        if not clean.strip():
            continue
        indent = len(clean) - len(clean.lstrip())
        while indents and indent <= indents[-1]:
            indents.pop()
        match = NESTING_KEYWORD.search(clean)
        if not match or "{" in clean[match.end() :] or clean.rstrip().endswith(";"):
            continue
        indents.append(indent)
        if len(indents) > max_depth:
            issues.append(nesting_issue(relative, line_number, len(indents), max_depth))
    return issues


def php_alternative_nesting_issues(relative: str, text: str, max_depth: int) -> list[Issue]:
    issues = []
    depth = 0
    state = CStyleScanState()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        clean, _ = scan_c_style_line(raw_line, "php", state)
        if re.search(r"\b(?:endif|endforeach|endfor|endwhile|endswitch)\s*;", clean):
            depth = max(0, depth - 1)
        if re.search(r"^\s*(?:if|foreach|for|while|switch)\b.*:\s*$", clean):
            depth += 1
            if depth > max_depth:
                issues.append(nesting_issue(relative, line_number, depth, max_depth))
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
    for event in brace_events(text, language, NESTING_KEYWORD):
        if not event.triggered:
            continue
        if event.kind == "open":
            depth += 1
            if depth > max_depth:
                issues.append(nesting_issue(relative, event.line, depth, max_depth))
        elif event.kind == "close":
            depth -= 1
    return issues
