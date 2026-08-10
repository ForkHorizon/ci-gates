from __future__ import annotations

import re
import shutil
import subprocess

from .model import Issue
from .scanner import scan_c_style_lines

SHELL_FUNCTION = re.compile(r"^(?:function\s+)?([A-Za-z_][A-Za-z0-9_-]*)\s*(?:\(\s*\))?\s*\{")
SHELL_FUNCTION_DECLARATION = re.compile(
    r"^(?:function\s+([A-Za-z_][A-Za-z0-9_-]*)(?:\s*\(\s*\))?|([A-Za-z_][A-Za-z0-9_-]*)\s*\(\s*\))\s*$"
)
SHELL_OPEN = re.compile(r"^(?:if|for|while|until|case|select)\b")
SHELL_CLOSE = re.compile(r"^(?:fi|done|esac)\b")


def shell_logical_statement(
    raw: str, clean: str, line_number: int, continuation: tuple[str, int] | None
) -> tuple[str, int, tuple[str, int] | None]:
    statement = clean.strip()
    if continuation is None:
        return statement, line_number, None
    prefix, start_line = continuation
    if statement and not raw.lstrip().startswith("#"):
        return f"{prefix} {statement}", start_line, None
    declaration = SHELL_FUNCTION_DECLARATION.fullmatch(prefix)
    if declaration:
        return "", start_line, (declaration.group(1) or declaration.group(2), start_line)
    return "", start_line, None


def shell_syntax_issues(relative: str, text: str) -> list[Issue]:
    bash = shutil.which("bash")
    if bash is None:
        return [Issue(relative, 1, "syntax_unavailable", "bash is required to validate shell syntax.")]
    result = subprocess.run([bash, "-n"], input=text, text=True, capture_output=True, check=False)
    if result.returncode == 0:
        return []
    line = shell_error_line(result.stderr)
    detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "invalid shell syntax"
    return [Issue(relative, line, "syntax_error", f"Shell syntax error: {detail}.")]


def shell_error_line(message: str) -> int:
    match = re.search(r": line (\d+):", message)
    return int(match.group(1)) if match else 1


def shell_function_lengths(text: str) -> list[tuple[str, int, int, int]]:
    results: list[tuple[str, int, int, int]] = []
    active: list[tuple[str, int, int]] = []
    pending: tuple[str, int] | None = None
    continuation: tuple[str, int] | None = None
    brace_depth = 0
    for line_number, (raw, clean, _) in enumerate(scan_c_style_lines(text, "shell"), start=1):
        statement, start_line, continued_pending = shell_logical_statement(raw, clean, line_number, continuation)
        continuation = None
        if continued_pending is not None:
            pending = continued_pending
        match = SHELL_FUNCTION.match(statement)
        start_depth = brace_depth
        if match:
            pending = None
            active.append((match.group(1), start_line, start_depth))
        elif pending is not None and statement == "{":
            name, start = pending
            active.append((name, start, start_depth))
            pending = None
        elif statement or not (not raw.strip() or raw.lstrip().startswith("#")):
            pending = None
        if not match and pending is None:
            if statement.endswith("\\"):
                continuation = (statement.removesuffix("\\").rstrip(), start_line)
            else:
                declaration = SHELL_FUNCTION_DECLARATION.fullmatch(statement)
                if declaration:
                    pending = (declaration.group(1) or declaration.group(2), start_line)
        brace_depth += clean.count("{") - clean.count("}")
        while active and brace_depth <= active[-1][2]:
            name, start, _ = active.pop()
            results.append((name, start, line_number - start + 1, 0))
    line_count = len(text.splitlines())
    for name, start, _ in active:
        results.append((name, start, line_count - start + 1, 0))
    return results


def shell_nesting_issues(relative: str, text: str, max_depth: int) -> list[Issue]:
    issues: list[Issue] = []
    depth = 0
    for line_number, (_, clean, _) in enumerate(scan_c_style_lines(text, "shell"), start=1):
        statement = clean.strip()
        if SHELL_CLOSE.match(statement):
            depth = max(0, depth - 1)
        if SHELL_OPEN.match(statement):
            depth += 1
            if depth > max_depth:
                issues.append(
                    Issue(relative, line_number, "nesting_depth", f"Nesting depth is {depth}; limit is {max_depth}.")
                )
    return issues
