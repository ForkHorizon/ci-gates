from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .cpp_operators import cpp_operator_signature_complete
from .cpp_destructors import cpp_destructor_has_body, cpp_destructor_signature_complete
from .javascript_methods import (
    has_method_body_brace,
    is_typescript_method_declaration,
    should_reject_incomplete_method,
)
from .model import FunctionBlock
from .signatures import matching_paren, parameter_start

if TYPE_CHECKING:
    from .functions import FunctionScanState


def pending_body_braces(
    signature: str,
    name: str,
    language: str,
    braces: tuple[int, int],
) -> tuple[tuple[int, int], bool]:
    waiting = (
        name == "<anonymous>"
        and language in {"javascript", "typescript", "php"}
        and re.search(r"\bfunction\b", signature)
    )
    if waiting:
        parameter_index, _ = parameter_start(signature, name, language)
        parameter_end = matching_paren(signature, parameter_index)
        if parameter_end < 0:
            return (0, 0), True
        body = signature[parameter_end + 1 :]
        return (body.count("{"), body.count("}")), True
    if language not in {"javascript", "typescript"} or name == "<anonymous>":
        return braces, False
    parameter_index, _ = parameter_start(signature, name, language)
    parameter_end = matching_paren(signature, parameter_index)
    if parameter_end < 0:
        return (0, 0), False
    body = signature[parameter_end + 1 :]
    if body.lstrip().startswith(":"):
        annotation = body.lstrip()[1:].lstrip()
        if annotation.startswith("{"):
            depth = 0
            close = -1
            for index, char in enumerate(annotation):
                depth += (char == "{") - (char == "}")
                if depth == 0:
                    close = index
                    break
            body = annotation[close + 1 :] if close >= 0 else ""
    return (body.count("{"), body.count("}")), False


def clear_pending(state: FunctionScanState) -> None:
    state.pending = None
    state.pending_signature = []


def reject_incomplete_cpp_special(
    state: FunctionScanState,
    signature: str,
    name: str,
    stripped: str,
    context: tuple[str, tuple[int, int]],
) -> bool:
    language, braces = context
    if language != "cpp" or not (braces[0] or braces[1]):
        return False
    if name.startswith("operator") and not cpp_operator_signature_complete(signature):
        clear_pending(state)
        return True
    if name.startswith("~"):
        if not cpp_destructor_signature_complete(signature):
            clear_pending(state)
            return True
        if not cpp_destructor_has_body(signature) and stripped.endswith(";"):
            clear_pending(state)
        return not cpp_destructor_has_body(signature)
    return False


def finish_expression_body(
    state: FunctionScanState,
    stripped: str,
    name: str,
    start: int,
    params: int,
) -> None:
    incomplete = stripped.endswith(",") or (len(state.pending_signature) > 1 and not stripped.endswith(";"))
    if not incomplete:
        state.results.append((name, start, 1, params))
        state.result_positions.append((start, state.current_source_column))
        clear_pending(state)


def finish_declaration(
    state: FunctionScanState,
    signature: str,
    context: tuple[str, int, int, int, str, bool],
) -> None:
    name, start, params, line_number, language, allow_bare = context
    declaration = bool(
        (language in {"csharp", "java"} and re.search(r"\b(?:abstract|extern|native)\b", signature))
        or (language == "typescript" and re.search(r"\bdeclare\s+function\b", signature))
        or (language == "typescript" and is_typescript_method_declaration(signature, name, allow_bare))
    )
    if declaration:
        state.results.append((name, start, line_number - start + 1, params))
        state.result_positions.append((start, state.current_source_column))
    clear_pending(state)


def declaration_scope_active(state: FunctionScanState) -> bool:
    return state.brace_depth in state.javascript_declaration_scopes or (
        state.brace_depth + 1 in state.javascript_declaration_scopes
    )


def finish_pending_declaration(
    state: FunctionScanState,
    stripped: str,
    pending: tuple[str, int, int, bool],
    line_number: int,
    language: str,
) -> bool:
    signature = "\n".join(state.pending_signature)
    name, start, params, _ = pending
    if not stripped.endswith(";") and not (
        language == "typescript"
        and ";" in signature
        and is_typescript_method_declaration(signature, name, declaration_scope_active(state))
    ):
        return False
    finish_declaration(
        state,
        signature,
        (name, start, params, line_number, language, declaration_scope_active(state)),
    )
    return True


def finish_pending_closing_brace(
    state: FunctionScanState,
    pending: tuple[str, int, int, bool],
    line_number: int,
    language: str,
    braces: tuple[int, int],
) -> bool:
    signature = "\n".join(state.pending_signature)
    name, start, params, _ = pending
    opens, closes = braces
    if not closes or opens or (language == "csharp" and signature.count("(") != signature.count(")")):
        return False
    if (
        language in {"javascript", "typescript"}
        and name != "<anonymous>"
        and not has_method_body_brace(signature, name)
    ):
        clear_pending(state)
        return True
    state.results.append((name, start, max(1, line_number - start), params))
    state.result_positions.append((start, state.current_source_column))
    clear_pending(state)
    return True


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
    if reject_incomplete_cpp_special(state, signature, name, stripped, (language, braces)):
        return
    if should_reject_incomplete_method(language, state.pending[3], name, signature):
        clear_pending(state)
        return
    (opens, closes), waiting_for_function_body = pending_body_braces(signature, name, language, braces)
    if confirmed and opens:
        state.active.append(FunctionBlock(name, start, state.brace_depth, params))
        state.active_columns[id(state.active[-1])] = state.current_source_column
        clear_pending(state)
    elif (
        confirmed
        and not waiting_for_function_body
        and not opens
        and not closes
        and (language != "csharp" or ";" in signature)
        and ("=" in stripped or "=>" in stripped)
    ):
        finish_expression_body(state, stripped, name, start, params)
    elif finish_pending_declaration(
        state, stripped, state.pending, line_number, language
    ) or finish_pending_closing_brace(state, state.pending, line_number, language, (opens, closes)):
        return


def close_functions(state: FunctionScanState, line_number: int) -> None:
    while state.active and state.brace_depth <= state.active[-1].parent_depth:
        block = state.active.pop()
        length = line_number - block.start_line + 1
        state.results.append((block.name, block.start_line, length, block.param_count))
        state.result_positions.append((block.start_line, state.active_columns.pop(id(block), 0)))
