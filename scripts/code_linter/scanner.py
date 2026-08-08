from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .literals import is_rust_lifetime


@dataclass
class CStyleScanState:
    block_depth: int = 0
    quote: str | None = None


@dataclass
class BraceEvent:
    kind: str  # "trigger", "open" or "close"
    line: int
    triggered: bool = False
    match: re.Match[str] | None = None


def brace_events(text: str, language: str, trigger: re.Pattern[str]) -> Iterable[BraceEvent]:
    """Walks `{`/`}` pairs, tagging each pair with whether `trigger` opened it.

    The trigger may sit on an earlier line than its brace (Allman style), so a
    match is carried forward until a brace, a statement-ending `;` outside
    parentheses, or an assignment consumes it.
    """
    frames: list[bool] = []
    pending: re.Match[str] | None = None
    for line_no, (_, clean, _) in enumerate(scan_c_style_lines(text, language), start=1):
        match = trigger.search(clean)
        if match:
            pending = match
            yield BraceEvent("trigger", line_no, match=match)
        min_index = match.end() if match else (0 if pending else None)
        parens = 0
        assigned = False
        for index, char in enumerate(clean):
            live = min_index is not None and index >= min_index
            if char == "(":
                parens += 1
            elif char == ")":
                parens = max(0, parens - 1)
            elif char == "=" and live and parens == 0:
                assigned = True
            elif char == "{":
                triggered = pending is not None and live
                frames.append(triggered)
                yield BraceEvent("open", line_no, triggered, pending if triggered else None)
                pending, min_index = None, None
            elif char == "}":
                yield BraceEvent("close", line_no, frames.pop() if frames else False)
                if live:
                    pending, min_index = None, None
            elif char == ";" and live and parens == 0:
                pending, min_index = None, None
        if assigned and pending is not None:
            # `type Alias = string` / `let x = y` completed without a block.
            pending = None


def scan_c_style_lines(text: str, language: str) -> list[tuple[str, str, bool]]:
    state = CStyleScanState()
    scanned = []
    for raw_line in text.splitlines():
        clean, is_comment = scan_c_style_line(raw_line, language, state)
        scanned.append((raw_line, clean, is_comment))
    return scanned


def starts_javascript_regex(output: Sequence[str]) -> bool:
    prefix = "".join(output).rstrip()
    if not prefix:
        return True
    return prefix[-1] in "=(:,[!&|?{};" or bool(
        re.search(r"\b(?:return|throw|case|delete|typeof|void|new|in|of)\s*$", prefix)
    )


def scan_heredoc(line: str, language: str, state: CStyleScanState) -> tuple[str, bool] | None:
    if state.quote and state.quote.startswith("php-heredoc:"):
        marker = state.quote.removeprefix("php-heredoc:")
        if line.strip().rstrip(";") == marker:
            state.quote = None
        return "", False
    if language != "php":
        return None
    heredoc = re.search(r"<<<[-~]?(?:['\"])?([A-Z][A-Za-z0-9_]*)", line)
    if not heredoc:
        return None
    state.quote = f"php-heredoc:{heredoc.group(1)}"
    return line[: heredoc.start()], False


def consume_block_comment(line: str, index: int, language: str, state: CStyleScanState) -> int:
    if language == "swift" and line.startswith("/*", index):
        state.block_depth += 1
        return index + 2
    if line.startswith("*/", index):
        state.block_depth -= 1
        return index + 2
    return index + 1


def consume_active_quote(line: str, index: int, state: CStyleScanState) -> int:
    if state.quote == '"""':
        if line.startswith('"""', index):
            state.quote = None
            return index + 3
        return index + 1
    if state.quote == '@"':
        if line.startswith('""', index):
            return index + 2
        if line[index] == '"':
            state.quote = None
        return index + 1
    char = line[index]
    if char == "\\" and state.quote != "`" and index + 1 < len(line):
        return index + 2
    if char == state.quote:
        state.quote = None
    return index + 1


def consume_javascript_regex(line: str, index: int, state: CStyleScanState) -> int:
    state.quote = "/"
    in_class = False
    index += 1
    while index < len(line):
        if line[index] == "\\" and index + 1 < len(line):
            index += 2
        elif line[index] == "[":
            in_class = True
            index += 1
        elif line[index] == "]":
            in_class = False
            index += 1
        elif line[index] == "/" and not in_class:
            state.quote = None
            index += 1
            while index < len(line) and line[index].isalpha():
                index += 1
            break
        else:
            index += 1
    return index


def consume_quoted_literal(line: str, index: int) -> int:
    quote = line[index]
    index += 1
    while index < len(line):
        if line[index] == "\\" and index + 1 < len(line):
            index += 2
        elif line[index] == quote:
            return index + 1
        else:
            index += 1
    return index


def start_special_region(
    line: str, index: int, language: str, state: CStyleScanState
) -> tuple[int | None, bool] | None:
    if line.startswith("//", index) or (language == "php" and line[index] == "#"):
        return None, True
    if line.startswith("/*", index):
        state.block_depth = 1
        return index + 2, True
    if line.startswith('"""', index):
        state.quote = '"""'
        return index + 3, False
    if language == "csharp" and line.startswith('@"', index):
        state.quote = '@"'
        return index + 2, False
    return None


def scan_c_style_line(line: str, language: str, state: CStyleScanState) -> tuple[str, bool]:
    heredoc = scan_heredoc(line, language, state)
    if heredoc is not None:
        return heredoc
    output = []
    index = 0
    had_comment = False
    while index < len(line):
        if state.block_depth:
            had_comment = True
            index = consume_block_comment(line, index, language, state)
            continue
        if state.quote:
            index = consume_active_quote(line, index, state)
            continue
        special = start_special_region(line, index, language, state)
        if special:
            index, starts_comment = special
            had_comment = had_comment or starts_comment
            if index is None:
                break
            continue
        char = line[index]
        if char == "/" and language in {"javascript", "typescript"} and starts_javascript_regex(output):
            index = consume_javascript_regex(line, index, state)
            continue
        if char == "'" and is_rust_lifetime(line, index, language):
            output.append(char)
            index += 1
            continue
        if char in {'"', "'"}:
            index = consume_quoted_literal(line, index)
            continue
        if char == "`" and language not in {"swift", "kotlin"}:
            state.quote = char
            index += 1
            continue
        output.append(char)
        index += 1
    clean = "".join(output)
    return clean, had_comment and not clean.strip()
