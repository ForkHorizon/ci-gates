from __future__ import annotations

import ast
import json

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: report an explicit capability gap.
    tomllib = None

from .model import Issue
from .ruby import ruby_syntax_issues
from .shell import shell_syntax_issues
from .scanner import CStyleScanState, scan_c_style_line


def check_syntax(relative: str, text: str, language: str) -> list[Issue]:
    if language == "python":
        try:
            ast.parse(text)
        except SyntaxError as exc:
            return [
                Issue(
                    relative,
                    exc.lineno or 1,
                    "syntax_error",
                    f"Python syntax error: {exc.msg}.",
                )
            ]
        return []
    if language == "ruby":
        return ruby_syntax_issues(relative, text)
    if language == "shell":
        return shell_syntax_issues(relative, text)
    if language in {"json", "toml"}:
        return config_syntax_issues(relative, text, language)
    return c_style_syntax_issues(relative, text, language)


def config_syntax_issues(relative: str, text: str, language: str) -> list[Issue]:
    if language == "toml" and tomllib is None:
        return [Issue(relative, 1, "syntax_unavailable", "Python 3.11+ is required to validate TOML syntax.")]
    try:
        json.loads(text) if language == "json" else tomllib.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        line = getattr(exc, "lineno", 1) or 1
        label = "JSON" if language == "json" else "TOML"
        return [Issue(relative, line, "syntax_error", f"{label} syntax error: {exc}.")]
    return []


def c_style_syntax_issues(relative: str, text: str, language: str) -> list[Issue]:
    state = CStyleScanState()
    depth = 0
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        clean, _ = scan_c_style_line(raw_line, language, state)
        for char in clean:
            depth += char == "{"
            depth -= char == "}"
            if depth < 0:
                return [
                    Issue(
                        relative,
                        line_number,
                        "syntax_error",
                        "Unexpected closing brace.",
                    )
                ]
    if state.block_depth or state.quote:
        return [
            Issue(
                relative,
                max(1, len(text.splitlines())),
                "syntax_error",
                "Unterminated comment or string.",
            )
        ]
    if depth:
        return [
            Issue(
                relative,
                max(1, len(text.splitlines())),
                "syntax_error",
                f"File has {depth} unclosed brace(s).",
            )
        ]
    return []
