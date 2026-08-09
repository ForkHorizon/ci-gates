from __future__ import annotations

import re

from .literals import strip_ruby_comment
from .model import Issue
from .signatures import count_params_in_signature

RUBY_BLOCK_START = re.compile(r"^\s*(class|module|if|unless|case|begin|for|while|until)\b|(^|[^A-Za-z0-9_])do\b")
RUBY_DEF_PATTERN = re.compile(
    r"\s*def\s+((?:[A-Za-z_][A-Za-z0-9_]*(?:::|\.))?"
    r"(?:[A-Za-z_][A-Za-z0-9_]*[!?=]?|\[\]=?|[-+*/%<>=~&|^`]+))"
)
RUBY_HEREDOC_MARKER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def ruby_code_lines(text: str) -> list[tuple[int, str]]:
    return _ruby_code_scan(text)[0]


def _ruby_code_scan(text: str) -> tuple[list[tuple[int, str]], int | None]:
    lines = []
    heredoc_ends: list[tuple[str, int]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if heredoc_ends:
            if raw_line.strip() == heredoc_ends[0][0]:
                heredoc_ends.pop(0)
            lines.append((line_number, ""))
            continue
        clean_line = strip_ruby_comment(raw_line)
        heredoc_ends.extend((marker, line_number) for marker in _ruby_heredoc_markers(raw_line))
        lines.append((line_number, clean_line))
    opener_line = heredoc_ends[0][1] if heredoc_ends else None
    return lines, opener_line


def _ruby_heredoc_markers(line: str) -> list[str]:
    markers = []
    index = 0
    while index < len(line):
        if line[index] in {'"', "'"}:
            index = _skip_ruby_quote(line, index)
            continue
        if line[index] == "#":
            break
        if line[index] == "\\":
            index += 2
            continue
        if not line.startswith("<<", index) or line.startswith("<<<", index):
            index += 1
            continue
        marker_index = index + 2
        if marker_index < len(line) and line[marker_index] in "-~":
            marker_index += 1
        quote = None
        if marker_index < len(line) and line[marker_index] in {'"', "'"}:
            quote = line[marker_index]
            marker_index += 1
        match = RUBY_HEREDOC_MARKER.match(line, marker_index)
        if not match or (quote and (match.end() >= len(line) or line[match.end()] != quote)):
            index += 2
            continue
        markers.append(match.group())
        index = match.end() + bool(quote)
    return markers


def _skip_ruby_quote(line: str, index: int) -> int:
    quote = line[index]
    index += 1
    while index < len(line):
        if line[index] == "\\":
            index += 2
        elif line[index] == quote:
            return index + 1
        else:
            index += 1
    return index


def ruby_block_start(line: str) -> bool:
    stripped = line.strip()
    if re.match(r"(?:class|module)\b", stripped):
        return True
    match = RUBY_DEF_PATTERN.match(stripped)
    if match:
        return not is_endless_ruby_method(stripped[match.end() :])
    return RUBY_BLOCK_START.search(line) is not None


def ruby_syntax_issues(relative: str, text: str) -> list[Issue]:
    stack: list[int] = []
    clean_lines, heredoc_opener = _ruby_code_scan(text)
    for line_number, line in clean_lines:
        if ruby_block_start(line):
            stack.append(line_number)
        for _ in re.finditer(r"(^|[^A-Za-z0-9_])end([^A-Za-z0-9_]|$)", line):
            if not stack:
                return [Issue(relative, line_number, "syntax_error", "Unexpected Ruby 'end'.")]
            stack.pop()
    if heredoc_opener:
        return [Issue(relative, heredoc_opener, "syntax_error", "Ruby heredoc is missing its terminator.")]
    if stack:
        return [Issue(relative, stack[-1], "syntax_error", "Ruby block is missing 'end'.")]
    return []


def ruby_parameter_count(signature: str, name: str, first_line: str) -> int:
    def_match = RUBY_DEF_PATTERN.match(first_line)
    if not def_match or def_match.group(1) != name:
        return 0
    after_name = first_line[def_match.end() :].strip()
    if not after_name:
        return 0
    parameter_text = signature[def_match.end() :].lstrip()
    if not parameter_text.startswith("(") and is_endless_ruby_method(after_name):
        return 0
    if parameter_text.startswith("("):
        closing = matching_ruby_delimiter(parameter_text, "(", ")")
        if closing < 0:
            return 0
        parameter_text = parameter_text[1:closing]
    return count_ruby_parameters(parameter_text)


def matching_ruby_delimiter(text: str, opening: str, closing: str) -> int:
    depth = 0
    for index, char in enumerate(text):
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
    return -1


def count_ruby_parameters(parameters: str) -> int:
    return count_params_in_signature(f"({parameters})")


def ruby_function_lengths(text: str) -> list[tuple[str, int, int, int]]:
    stack: list[tuple[str, str, int, int]] = []
    results = []
    clean_lines = ruby_code_lines(text)
    source_lines = [line for _, line in clean_lines]

    for line_number, line in clean_lines:
        stripped = line.strip()
        if not stripped:
            continue

        def_match = RUBY_DEF_PATTERN.match(line)
        if def_match:
            name = def_match.group(1)
            signature = "\n".join(source_lines[line_number - 1 :])
            pcount = ruby_parameter_count(signature, name, line)
            if is_endless_ruby_method(line[def_match.end() :]):
                results.append((name, line_number, 1, pcount))
            else:
                stack.append(("def", name, line_number, pcount))
            continue

        if RUBY_BLOCK_START.search(line):
            stack.append(("block", "", line_number, 0))

        end_count = len(re.findall(r"(^|[^A-Za-z0-9_])end([^A-Za-z0-9_]|$)", line))
        for _ in range(end_count):
            if not stack:
                break
            kind, name, start_line, pcount = stack.pop()
            if kind == "def":
                results.append((name, start_line, line_number - start_line + 1, pcount))

    for kind, name, start_line, pcount in reversed(stack):
        if kind == "def":
            results.append((name, start_line, len(source_lines) - start_line + 1, pcount))
    return results


def is_endless_ruby_method(after_name: str) -> bool:
    """`def foo = 1` is a one-liner; `def foo(a = 1)` is not — the `=` in a
    default argument sits inside the parameter list, so skip that first."""
    rest = after_name.lstrip()
    if rest.startswith("("):
        depth = 0
        for index, char in enumerate(rest):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    rest = rest[index + 1 :]
                    break
        else:
            return False
    rest = rest.lstrip()
    return rest.startswith("=") and not rest.startswith(("==", "=~"))
