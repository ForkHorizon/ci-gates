from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from .model import FunctionBlock
from .ruby import ruby_function_lengths
from .shell import shell_function_lengths
from .scanner import scan_c_style_lines
from .signatures import count_params_in_signature, detect_brace_function


FunctionResult = tuple[str, int, int, int]
PendingFunction = tuple[str, int, int, bool]


@dataclass
class FunctionScanState:
    results: list[FunctionResult] = field(default_factory=list)
    active: list[FunctionBlock] = field(default_factory=list)
    pending: PendingFunction | None = None
    pending_signature: list[str] = field(default_factory=list)
    brace_depth: int = 0


def function_lengths(text: str, language: str) -> list[tuple[str, int, int, int]]:
    if language == "python":
        return python_function_lengths(text)
    if language == "ruby":
        return ruby_function_lengths(text)
    if language == "shell":
        return shell_function_lengths(text)
    return brace_function_lengths(text, language)


def python_function_lengths(text: str) -> list[tuple[str, int, int, int]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end_line = getattr(node, "end_lineno", node.lineno)
            pos_args = getattr(node.args, "posonlyargs", [])
            pcount = (
                len(pos_args)
                + len(node.args.args)
                + len(node.args.kwonlyargs)
                + (1 if node.args.vararg else 0)
                + (1 if node.args.kwarg else 0)
            )
            results.append((node.name, node.lineno, end_line - node.lineno + 1, pcount))
    return results


def clear_pending(state: FunctionScanState) -> None:
    state.pending = None
    state.pending_signature = []


def track_signature(state: FunctionScanState, clean: str, line_number: int, language: str) -> None:
    detected = detect_brace_function(clean.strip(), language)
    if detected:
        arrow = bool(
            language in {"javascript", "typescript"}
            and "=>" not in clean
            and re.search(r"\b(?:const|let|var)\s+\w+\s*=", clean)
            and not re.search(r"=\s*\{", clean)
        )
        state.pending_signature = [clean]
        params = count_params_in_signature(clean, detected, language)
        state.pending = (detected, line_number, params, arrow)
    elif state.pending:
        state.pending_signature.append(clean)
        signature = "\n".join(state.pending_signature)
        params = count_params_in_signature(signature, state.pending[0], language)
        state.pending = (*state.pending[:2], params, state.pending[3])


def finish_pending_line(
    state: FunctionScanState,
    stripped: str,
    line_number: int,
    language: str,
    braces: tuple[int, int],
) -> None:
    if not state.pending:
        return
    signature = "\n".join(state.pending_signature)
    confirmed = not state.pending[3] or "=>" in signature
    name, start, params, _ = state.pending
    opens, closes = braces
    if confirmed and opens:
        state.active.append(FunctionBlock(name, start, state.brace_depth, params))
        clear_pending(state)
    elif confirmed and not opens and not closes and ("=" in stripped or "=>" in stripped):
        incomplete = stripped.endswith(",") or (len(state.pending_signature) > 1 and not stripped.endswith(";"))
        if not incomplete:
            state.results.append((name, start, 1, params))
            clear_pending(state)
    elif stripped.endswith(";"):
        declaration = bool(
            (language in {"csharp", "java"} and re.search(r"\b(?:abstract|extern|native)\b", signature))
            or (language == "typescript" and re.search(r"\bdeclare\s+function\b", signature))
        )
        if declaration:
            state.results.append((name, start, line_number - start + 1, params))
        clear_pending(state)
    elif closes and not opens:
        state.results.append((name, start, max(1, line_number - start), params))
        clear_pending(state)


def close_functions(state: FunctionScanState, line_number: int) -> None:
    while state.active and state.brace_depth <= state.active[-1].parent_depth:
        block = state.active.pop()
        length = line_number - block.start_line + 1
        state.results.append((block.name, block.start_line, length, block.param_count))


def brace_function_lengths(text: str, language: str) -> list[FunctionResult]:
    state = FunctionScanState()
    for line_number, (_, clean, _) in enumerate(scan_c_style_lines(text, language), start=1):
        track_signature(state, clean, line_number, language)
        opens, closes = clean.count("{"), clean.count("}")
        finish_pending_line(state, clean.strip(), line_number, language, (opens, closes))
        state.brace_depth = max(0, state.brace_depth + opens - closes)
        close_functions(state, line_number)
    line_count = len(text.splitlines())
    for block in reversed(state.active):
        length = line_count - block.start_line + 1
        state.results.append((block.name, block.start_line, length, block.param_count))
    return state.results
