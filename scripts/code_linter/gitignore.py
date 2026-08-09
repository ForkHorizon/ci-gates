from __future__ import annotations

from .model import Issue


def gitignore_syntax_issues(relative: str, text: str) -> list[Issue]:
    """Validate the line-oriented syntax shared by gitignore files."""
    issues = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if "\x00" in raw_line:
            issues.append(Issue(relative, line_number, "syntax_error", "Gitignore patterns cannot contain NUL bytes."))
            continue
        pattern = raw_line.rstrip("\r")
        if not pattern or pattern.lstrip().startswith("#"):
            continue
        if pattern.startswith("\\#") or pattern.startswith("\\!"):
            continue
        if pattern.startswith("!"):
            pattern = pattern[1:]
        if not pattern:
            issues.append(Issue(relative, line_number, "syntax_error", "Gitignore negation needs a pattern."))
            continue
        if pattern.endswith("\\") and not pattern.endswith("\\\\"):
            issues.append(
                Issue(
                    relative,
                    line_number,
                    "syntax_error",
                    "Gitignore patterns cannot end with a single escape character.",
                )
            )
    return issues
