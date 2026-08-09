from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from .model import FunctionBlock
from .ruby import ruby_function_lengths
from .shell import shell_function_lengths
from .scanner import scan_c_style_lines
from .signatures import (
    count_params_in_signature,
    csharp_lambda_match,
    detect_brace_function,
    pending_body_braces,
)
from .swift_closures import track_swift_signature


FunctionResult = tuple[str, int, int, int]
PendingFunction = tuple[str, int, int, bool]


@dataclass
class FunctionScanState:
    results: list[FunctionResult] = field(default_factory=list)
    active: list[FunctionBlock] = field(default_factory=list)
    pending: PendingFunction | None = None
    pending_signature: list[str] = field(default_factory=list)
    brace_depth: int = 0
    type_scopes: list[tuple[int, str]] = field(default_factory=list)
    method_scopes: list[int] = field(default_factory=list)
    csharp_candidate: list[str] = field(default_factory=list)
    csharp_candidate_start: int = 0
    swift_candidate: list[str] = field(default_factory=list)
    swift_candidate_start: int = 0
    swift_candidate_parent_depth: int = 0
    swift_candidate_open: bool = False


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


def clear_csharp_candidate(state: FunctionScanState) -> None:
    state.csharp_candidate = []
    state.csharp_candidate_start = 0


def track_declaration_context(state: FunctionScanState, clean: str, language: str) -> None:
    state.type_scopes = [scope for scope in state.type_scopes if scope[0] <= state.brace_depth]
    state.method_scopes = [depth for depth in state.method_scopes if depth <= state.brace_depth]
    if language in {
        "c",
        "cpp",
        "csharp",
        "java",
        "dart",
        "groovy",
        "objective_c",
        "scala",
    }:
        type_pattern = r"\b(?:class|struct|interface|record)\s+([A-Za-z_][A-Za-z0-9_]*)[^{}]*\{"
        for match in re.finditer(type_pattern, clean):
            depth = state.brace_depth + clean[: match.end()].count("{")
            state.type_scopes.append((depth, match.group(1)))
    if language in {"javascript", "typescript"}:
        class_pattern = r"\bclass(?:\s+[A-Za-z_$][A-Za-z0-9_$]*)?[^{}]*\{"
        object_pattern = r"(?:\b(?:const|let|var)\s+[A-Za-z_$][A-Za-z0-9_$]*\s*=\s*)\{"
        if re.search(class_pattern, clean) or re.search(object_pattern, clean):
            state.method_scopes.append(state.brace_depth + clean.count("{"))


def set_pending_signature(
    state: FunctionScanState,
    detected: str,
    signature: str,
    line_number: int,
    arrow: bool = False,
) -> None:
    state.pending_signature = signature.splitlines()
    params = count_params_in_signature(signature, detected, "csharp")
    state.pending = (detected, line_number, params, arrow)


def csharp_candidate_possible(clean: str) -> bool:
    stripped = clean.strip()
    if not stripped or ";" in stripped or "{" in stripped or "}" in stripped:
        return False
    return bool(
        "=" in stripped
        or re.search(r"\b(?:async|await|return|throw|yield)\b", stripped)
        or stripped.endswith(("(", ",", ":", "?"))
        or stripped.startswith("(")
    )


def track_csharp_signature(
    state: FunctionScanState,
    clean: str,
    line_number: int,
    enclosing_types: frozenset[str],
) -> None:
    if state.pending:
        state.pending_signature.append(clean)
        signature = "\n".join(state.pending_signature)
        params = count_params_in_signature(signature, state.pending[0], "csharp")
        state.pending = (*state.pending[:2], params, state.pending[3])
        return

    signature_lines = [*state.csharp_candidate, clean]
    signature = "\n".join(signature_lines)
    match = csharp_lambda_match(signature)
    if match:
        start = state.csharp_candidate_start or line_number
        lambda_line = start + signature[: match[0]].count("\n")
        set_pending_signature(state, "<anonymous>", signature, lambda_line, arrow=True)
        clear_csharp_candidate(state)
        return

    detected = detect_brace_function(clean.strip(), "csharp", enclosing_types)
    if detected and detected != "<anonymous>":
        set_pending_signature(state, detected, clean.strip(), line_number)
        clear_csharp_candidate(state)
        return

    if state.csharp_candidate:
        if ";" in clean or "{" in clean or "}" in clean:
            clear_csharp_candidate(state)
        else:
            state.csharp_candidate.append(clean)
    elif csharp_candidate_possible(clean):
        state.csharp_candidate = [clean]
        state.csharp_candidate_start = line_number


def track_signature(
    state: FunctionScanState,
    clean: str,
    line_number: int,
    language: str,
) -> None:
    enclosing_types = frozenset(name for _, name in state.type_scopes)
    if language == "csharp":
        track_csharp_signature(state, clean, line_number, enclosing_types)
        return
    if language == "swift":
        track_swift_signature(state, clean, line_number)
        return
    allow_method_fallback = language in {"javascript", "typescript"} and bool(state.method_scopes)
    detected = detect_brace_function(
        clean.strip(),
        language,
        enclosing_types,
        allow_method_fallback,
    )
    if detected:
        php_arrow = language == "php" and re.search(r"\bfn\s*\(", clean)
        arrow = bool(php_arrow) or bool(
            language in {"javascript", "typescript"}
            and detected != "<anonymous>"
            and "=>" not in clean
            and "function" not in clean
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
    (opens, closes), waiting_for_function_body = pending_body_braces(signature, name, language, braces)
    if confirmed and opens:
        state.active.append(FunctionBlock(name, start, state.brace_depth, params))
        clear_pending(state)
    elif (
        confirmed
        and not waiting_for_function_body
        and not opens
        and not closes
        and (language != "csharp" or ";" in signature)
        and ("=" in stripped or "=>" in stripped or language == "csharp")
    ):
        # Expression-bodied anonymous functions are intentionally one line;
        # call-like blocks are not classified as functions here.
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
        track_declaration_context(state, clean, language)
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
