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
        or stripped.endswith("<")
    )


def javascript_candidate_continues(candidate: list[str], clean: str) -> bool:
    stripped = clean.strip()
    if not stripped or any(mark in stripped for mark in (";", "=")):
        return False
    text = " ".join(candidate).lstrip()
    if text.startswith("["):
        return True
    if "<" in text and re.match(r"[A-Za-z_$][A-Za-z0-9_$]*\s*<", text):
        return True
    return javascript_header_candidate(clean)


def javascript_new_method_start(line: str, signature: str = "") -> bool:
    stripped = line.strip()
    if signature.count("(") > signature.count(")") or signature.count("[") > signature.count("]"):
        return False
    header = stripped.split("{", 1)[0].split(";", 1)[0].rstrip()
    if not header or "=" in header:
        return False
    method_start = bool(
        re.match(
            r"^(?:(?:async|static|get|set|abstract|declare|override|public|private|"
            r"protected|readonly)\b\s+|\*\s*|#|\[)",
            header,
        )
        or re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*\s*\(", header)
    )
    return method_start


def javascript_header_complete(signature: str, language: str) -> bool:
    if "{" in signature:
        return True
    return language == "typescript" and ":" in signature and signature.rstrip().endswith(";")


def continue_pending_javascript(state: FunctionScanState, clean: str, language: str) -> bool:
    if not state.pending:
        return False
    if javascript_new_method_start(clean, "\n".join(state.pending_signature)):
        state.pending = None
        state.pending_signature = []
        return False
    state.pending_signature.append(clean)
    signature = "\n".join(state.pending_signature)
    params = count_params_in_signature(signature, state.pending[0], language)
    state.pending = (*state.pending[:2], params, state.pending[3])
    return True


def javascript_detection_line(
    clean: str,
    raw: str | None,
    language: str,
    enclosing_types: frozenset[str],
    allow_method_fallback: bool,
) -> str:
    source = clean
    if raw and raw != clean:
        raw_detected = detect_brace_function(raw.strip(), language, enclosing_types, allow_method_fallback)
        if raw_detected and (raw_detected[0] in "'\"." or raw_detected[0].isdigit()):
            source = raw
    detected = detect_brace_function(source.strip(), language, enclosing_types, allow_method_fallback)
    if detected and (detected[0] in "'\"." or detected[0].isdigit()):
        return source
    opening = source.find("{")
    if opening >= 0:
        tail = source[opening + 1 :].lstrip()
        if detect_brace_function(
            tail, language, enclosing_types, allow_method_fallback
        ) == detected and source.lstrip().startswith(("class ", "interface ")):
            if tail.rstrip().endswith("}"):
                tail = tail.rstrip()[:-1].rstrip()
            return tail
    return source


def javascript_arrow_method(detected: str, clean: str) -> bool:
    return bool(
        (detected != "<anonymous>" and "=>" in clean)
        or (
            detected != "<anonymous>"
            and "=>" not in clean
            and "function" not in clean
            and re.search(r"\b(?:const|let|var)\s+\w+\s*=", clean)
            and not re.search(r"=\s*\{", clean)
            and not re.search(r"\)\s*\{", clean)
        )
    )


def track_javascript_signature(
    state: FunctionScanState,
    clean: str,
    line_number: int,
    language: str,
    raw: str | None = None,
) -> None:
    enclosing_types = frozenset(name for _, name in state.type_scopes)
    allow_method_fallback = bool(state.method_scopes)
    if ";" in clean:
        tail = clean.split(";", 1)[-1].strip()
        if tail != clean and detect_brace_function(tail, language, enclosing_types, allow_method_fallback):
            state.pending = None
            state.pending_signature = []
            clean = tail
            raw = tail
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
        elif not javascript_candidate_continues(state.javascript_candidate, clean):
            clear_javascript_candidate(state)
        return
    detection_line = javascript_detection_line(clean, raw, language, enclosing_types, allow_method_fallback)
    detected = detect_brace_function(detection_line.strip(), language, enclosing_types, allow_method_fallback)
    if detected:
        arrow = javascript_arrow_method(detected, clean)
        state.pending_signature = [detection_line]
        params = count_params_in_signature(detection_line, detected, language)
        state.pending = (detected, line_number, params, arrow)
    elif state.pending:
        state.pending_signature.append(clean)
        signature = "\n".join(state.pending_signature)
        params = count_params_in_signature(signature, state.pending[0], language)
        state.pending = (*state.pending[:2], params, state.pending[3])
    elif allow_method_fallback and javascript_header_candidate(clean):
        state.javascript_candidate = [clean]
        state.javascript_candidate_start = line_number
