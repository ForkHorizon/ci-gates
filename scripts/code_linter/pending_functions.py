from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .model import FunctionBlock
from .signatures import pending_body_braces

if TYPE_CHECKING:
    from .functions import FunctionScanState


def clear_pending(state: FunctionScanState) -> None:
    state.pending = None
    state.pending_signature = []


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
        and ("=" in stripped or "=>" in stripped)
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
    elif closes and not opens and (language != "csharp" or signature.count("(") == signature.count(")")):
        state.results.append((name, start, max(1, line_number - start), params))
        clear_pending(state)
