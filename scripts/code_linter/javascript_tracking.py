from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .signatures import count_params_in_signature, detect_brace_function


if TYPE_CHECKING:
    from .functions import FunctionScanState


def clear_javascript_candidate(state: FunctionScanState) -> None:
    state.javascript_candidate = []
    state.javascript_candidate_start = 0


def track_split_type_context(state: FunctionScanState, clean: str) -> None:
    candidate = state.javascript_type_candidate
    if candidate:
        candidate.append(clean)
        if "{" in clean:
            depth = state.brace_depth + sum(line.count("{") for line in candidate)
            state.method_scopes.append(depth)
            text = " ".join(candidate)
            if re.search(r"\binterface\b|\bdeclare\s+class\b", text):
                state.javascript_declaration_scopes.append(depth)
            state.javascript_type_candidate = []
        elif "}" in clean or ";" in clean:
            state.javascript_type_candidate = []
    elif re.match(
        r"^\s*(?:(?:export|declare|abstract)\s+)*(?:class|interface)\b[^{}]*$",
        clean,
    ):
        state.javascript_type_candidate = [clean]


def javascript_header_candidate(line: str) -> bool:
    stripped = line.strip()
    if not stripped or any(mark in stripped for mark in (";", "=", "{")):
        return False
    return bool(
        re.match(
            r"^(?:async|static|get|set|abstract|declare|override|public|private|"
            r"protected|readonly|\*|#|\[|\(|\]|[A-Za-z_$][A-Za-z0-9_$]*$)",
            stripped,
        )
    )


def javascript_new_method_start(line: str) -> bool:
    stripped = line.strip()
    if not stripped or any(mark in stripped for mark in (";", "=", "{")):
        return False
    return bool(
        re.match(
            r"^(?:async|static|get|set|abstract|declare|override|public|private|"
            r"protected|readonly|\*|#|\[)",
            stripped,
        )
        or re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*\s*\(", stripped)
    )


def javascript_header_complete(signature: str, language: str) -> bool:
    if "{" in signature:
        return True
    return language == "typescript" and ":" in signature and signature.rstrip().endswith(";")


def continue_pending_javascript(state: FunctionScanState, clean: str, language: str) -> bool:
    if not state.pending:
        return False
    if javascript_new_method_start(clean):
        state.pending = None
        state.pending_signature = []
        return False
    state.pending_signature.append(clean)
    signature = "\n".join(state.pending_signature)
    params = count_params_in_signature(signature, state.pending[0], language)
    state.pending = (*state.pending[:2], params, state.pending[3])
    return True


def track_javascript_signature(state: FunctionScanState, clean: str, line_number: int, language: str) -> None:
    enclosing_types = frozenset(name for _, name in state.type_scopes)
    allow_method_fallback = bool(state.method_scopes)
    if continue_pending_javascript(state, clean, language):
        return
    if state.javascript_candidate:
        state.javascript_candidate.append(clean)
        candidate = "\n".join(state.javascript_candidate)
        detected = detect_brace_function(candidate, language, enclosing_types, allow_method_fallback)
        if detected and javascript_header_complete(candidate, language):
            state.pending_signature = candidate.splitlines()
            params = count_params_in_signature(candidate, detected, language)
            state.pending = (
                detected,
                state.javascript_candidate_start,
                params,
                False,
            )
            clear_javascript_candidate(state)
        elif "{" in clean or ";" in clean or "}" in clean or not javascript_header_candidate(clean):
            clear_javascript_candidate(state)
        return
    detected = detect_brace_function(clean.strip(), language, enclosing_types, allow_method_fallback)
    if detected:
        arrow = bool(
            (detected != "<anonymous>" and "=>" in clean)
            or (
                detected != "<anonymous>"
                and "=>" not in clean
                and "function" not in clean
                and re.search(r"\b(?:const|let|var)\s+\w+\s*=", clean)
                and not re.search(r"=\s*\{", clean)
            )
        )
        state.pending_signature = [clean]
        params = count_params_in_signature(clean, detected, language)
        state.pending = (detected, line_number, params, arrow)
    elif state.pending:
        state.pending_signature.append(clean)
        signature = "\n".join(state.pending_signature)
        params = count_params_in_signature(signature, state.pending[0], language)
        state.pending = (*state.pending[:2], params, state.pending[3])
    elif allow_method_fallback and javascript_header_candidate(clean):
        state.javascript_candidate = [clean]
        state.javascript_candidate_start = line_number
