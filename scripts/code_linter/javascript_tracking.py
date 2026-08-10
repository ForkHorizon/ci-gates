from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .javascript_candidates import (
    javascript_candidate_continues,
    javascript_header_candidate,
    javascript_new_method_start,
)
from .javascript_methods import detect_javascript_method
from .javascript_generics import generic_parameter_opening
from .signatures import count_params_in_signature, detect_brace_function


if TYPE_CHECKING:
    from .functions import FunctionScanState


def clear_javascript_candidate(state: FunctionScanState) -> None:
    state.javascript_candidate, state.javascript_candidate_start = [], 0


def javascript_method_body_header(text: str) -> bool:
    return bool(detect_javascript_method(text.rsplit("{", 1)[-1], True))


def javascript_line_fragments(clean: str, allow_continuation: bool = False) -> list[str]:
    leading_close = clean.find("}")
    if (
        leading_close >= 0
        and clean[: leading_close + 1].strip() == "}"
        and re.search(r"(?:#?[A-Za-z_$][A-Za-z0-9_$]*|\[[^]]+\])\s*\(", clean[leading_close + 1 :])
    ):
        return [clean[: leading_close + 1], clean[leading_close + 1 :]]
    if not allow_continuation and not re.search(
        r"\bclass\b|\binterface\b|\bnamespace\b|\bexport\s+default\b|\bmodule\.exports\b|"
        r"\b(?:const|let|var)\s+[A-Za-z_$][A-Za-z0-9_$]*\s*=\s*\{|"
        r"\breturn\s*\{|\b[A-Za-z_$][A-Za-z0-9_$]*\s*\(\s*(?:\(\s*)*\{",
        clean,
    ):
        return [clean]
    opening = clean.find("{")
    if opening < 0:
        return [clean]
    initial_function = re.search(r"\bfunction\s*\*?\s*[A-Za-z_$][A-Za-z0-9_$]*\s*\([^{}]*\)\s*$", clean[:opening])
    fragments = [clean[: opening + 1]] if initial_function else []
    start, depth, body_depth = (opening + 1 if initial_function else 0), 1, 0
    for index in range(opening + 1, len(clean)):
        char = clean[index]
        if char == "{":
            previous = clean[:index].rstrip()[-1:]
            nested_object = depth > 1 and re.search(
                r"(?:\breturn|[A-Za-z_$][A-Za-z0-9_$]*)\s*\(?\s*$", clean[start:index]
            )
            if nested_object:
                fragments.append(clean[start : index + 1].lstrip(" ,"))
                start, body_depth = index + 1, 0
            if previous in {")", "]"} and (depth == 1 or javascript_method_body_header(clean[start:index])):
                body_depth = depth + 1
            depth += 1
        elif char == "}":
            depth -= 1
            if body_depth and depth == body_depth - 1:
                fragments.append(clean[start : index + 1].lstrip(" ,"))
                start, body_depth = index + 1, 0
        elif char == ";" and depth == 1:
            fragments.append(clean[start : index + 1].lstrip(" ,"))
            start = index + 1
    if not fragments:
        return [clean]
    remainder = clean[start:].lstrip(" ,")
    if remainder.strip():
        fragments.append(remainder)
    return fragments


def javascript_fragments_for_line(clean: str, language: str, method_scopes: list[int]) -> list[str]:
    return (
        [clean]
        if language not in {"javascript", "typescript"}
        else javascript_line_fragments(clean, bool(method_scopes))
    )


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
        r"^\s*(?:(?:export|declare|abstract)\s+)*(?:class|interface)\b[^{}]*$|"
        r"^\s*(?:(?:export\s+)?(?:const|let|var)\s+[A-Za-z_$][A-Za-z0-9_$]*\s*=|"
        r"export\s+default|module\.exports\s*=|return\s*\(|"
        r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)?\s*\()\s*$",
        clean,
    ):
        state.javascript_type_candidate = [clean]


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
        raw_tail = raw[raw.find("{") + 1 :].lstrip() if "{" in raw else ""
        raw_tail_detected = detect_brace_function(raw_tail, language, enclosing_types, allow_method_fallback)
        if (raw_detected and (raw_detected[0] in "'\"." or raw_detected[0].isdigit())) or (
            raw_tail_detected and raw_tail_detected[0] in "'\"."
        ):
            source = raw
    detected = detect_brace_function(source.strip(), language, enclosing_types, allow_method_fallback)
    if detected and (detected[0] in "'\"." or detected[0].isdigit()):
        return source
    opening = source.find("{")
    if opening >= 0:
        tail = source[opening + 1 :].lstrip()
        tail_detected = detect_brace_function(tail, language, enclosing_types, allow_method_fallback)
        object_prefix = re.match(
            r"^(?:[A-Za-z_$][A-Za-z0-9_$]*\s*\(\s*(?:\(\s*)*\{|\{\s*|class\s|interface\s|declare\s+namespace\s|export\s+default\s|module\.exports)",
            source.lstrip(),
        )
        if (
            tail_detected
            and object_prefix
            and (
                tail_detected != detected
                or re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*\s*\(\s*(?:\(\s*)*\{", source.lstrip())
                or source.lstrip().startswith(
                    ("{", "class ", "interface ", "declare namespace ", "export default ", "module.exports")
                )
            )
        ):
            declaration_prefix = source.lstrip().startswith(
                ("class ", "interface ", "declare namespace ", "export default ", "module.exports")
            )
            if declaration_prefix and tail.count("}") > tail.count("{") and tail.rstrip().endswith("}"):
                tail = tail.rstrip()[:-1].rstrip()
            return tail
    return source


def javascript_arrow_method(detected: str, clean: str) -> bool:
    arrow = clean.find("=>")
    assignment = clean.find("=")
    return bool(
        (
            detected != "<anonymous>"
            and arrow >= 0
            and assignment >= 0
            and assignment < arrow
            and not re.search(r"\)\s*\{", clean[:assignment])
        )
        or (
            detected != "<anonymous>"
            and "=>" not in clean
            and "function" not in clean
            and re.search(r"\b(?:const|let|var)\s+\w+\s*=", clean)
            and not re.search(r"=\s*\{", clean)
            and not re.search(r"\)\s*\{", clean)
        )
    )


def track_javascript_candidate(
    state: FunctionScanState,
    clean: str,
    language: str,
    enclosing_types: frozenset[str],
    allow_method_fallback: bool,
) -> bool:
    state.javascript_candidate.append(clean)
    candidate = "\n".join(state.javascript_candidate)
    detected = detect_brace_function(candidate, language, enclosing_types, allow_method_fallback)
    generic_incomplete = (
        language == "typescript" and "<" in candidate and generic_parameter_opening(candidate, candidate.find("<")) < 0
    )
    complete = detected is not None and (
        "{" in candidate or (language == "typescript" and ":" in candidate and candidate.rstrip().endswith(";"))
    )
    if complete and not generic_incomplete:
        state.pending_signature = candidate.splitlines()
        params = count_params_in_signature(candidate, detected, language)
        arrow = javascript_arrow_method(detected, candidate)
        state.pending = (detected, state.javascript_candidate_start, params, arrow)
        clear_javascript_candidate(state)
        return True
    if javascript_candidate_continues(state.javascript_candidate, clean):
        return True
    clear_javascript_candidate(state)
    return False


def track_javascript_signature(
    state: FunctionScanState,
    clean: str,
    line_number: int,
    language: str,
    raw: str | None = None,
) -> None:
    enclosing_types = frozenset(name for _, name in state.type_scopes)
    allow_method_fallback = bool(state.method_scopes or state.active)
    if ";" in clean:
        prefix, tail = (part.strip() for part in clean.split(";", 1))
        if (
            tail != clean
            and prefix.count("{") - prefix.count("}") <= 1
            and detect_brace_function(tail, language, enclosing_types, allow_method_fallback)
        ):
            state.pending, state.pending_signature, clean, raw = None, [], tail, tail
    if continue_pending_javascript(state, clean, language):
        return
    if state.javascript_candidate and track_javascript_candidate(
        state, clean, language, enclosing_types, allow_method_fallback
    ):
        return
    detection_line = javascript_detection_line(clean, raw, language, enclosing_types, allow_method_fallback)
    detected = detect_brace_function(detection_line.strip(), language, enclosing_types, allow_method_fallback)
    call_without_body = state.active and clean.rstrip().endswith("(") and "{" not in detection_line
    generic_header_incomplete = (
        language == "typescript"
        and "<" in clean
        and "{" in clean
        and generic_parameter_opening(clean, clean.find("<")) < 0
    )
    if detected and not call_without_body and not generic_header_incomplete:
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
