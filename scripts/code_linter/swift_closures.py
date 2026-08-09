from __future__ import annotations

import re
from typing import Protocol

from .model import FunctionBlock
from .signatures import count_params_in_signature, detect_brace_function
from .swift_syntax import detect_swift


class SwiftClosureScanState(Protocol):
    active: list[FunctionBlock]
    brace_depth: int
    pending: tuple[str, int, int, bool] | None
    pending_signature: list[str]
    swift_candidate: list[str]
    swift_candidate_start: int
    swift_candidate_parent_depth: int
    swift_candidate_open: bool


SWIFT_BLOCK_WORDS = {
    "catch",
    "class",
    "do",
    "else",
    "enum",
    "extension",
    "for",
    "func",
    "guard",
    "if",
    "init",
    "protocol",
    "repeat",
    "struct",
    "subscript",
    "switch",
    "while",
}


def clear_swift_candidate(state: SwiftClosureScanState) -> None:
    state.swift_candidate = []
    state.swift_candidate_start = 0
    state.swift_candidate_parent_depth = 0
    state.swift_candidate_open = False


def swift_closure_context(prefix: str) -> bool:
    """Return whether a Swift brace could begin a closure, not a block."""
    stripped = prefix.strip()
    if not stripped:
        return False
    first_word = re.match(r"[A-Za-z_][A-Za-z0-9_]*", stripped)
    if first_word and first_word.group(0) in SWIFT_BLOCK_WORDS:
        return False
    return bool(
        re.search(r"(?:=|\(|,|:|\b(?:return|throw|yield\s+return))\s*$", stripped)
        or re.search(
            r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
            r"\s*(?:\([^{}]*\))?\s*$",
            stripped,
        )
    )


def swift_candidate_possible(clean: str) -> bool:
    if not clean.strip() or ";" in clean or "}" in clean:
        return False
    if "{" in clean:
        return swift_closure_context(clean[: clean.find("{")])
    return swift_closure_context(clean)


def track_swift_signature(state: SwiftClosureScanState, clean: str, line_number: int) -> None:
    if state.pending:
        state.pending_signature.append(clean)
        signature = "\n".join(state.pending_signature)
        params = count_params_in_signature(signature, state.pending[0], "swift")
        state.pending = (*state.pending[:2], params, state.pending[3])
        return

    if state.swift_candidate:
        if not state.swift_candidate_open and "{" in clean:
            prefix = "\n".join([*state.swift_candidate, clean[: clean.find("{")]])
            if not swift_closure_context(prefix):
                clear_swift_candidate(state)
                return
            state.swift_candidate_start = line_number
            state.swift_candidate_parent_depth = state.brace_depth
            state.swift_candidate_open = True
        state.swift_candidate.append(clean)
        signature = "\n".join(state.swift_candidate)
        if state.swift_candidate_open and detect_swift(signature):
            params = count_params_in_signature(signature, "<anonymous>", "swift")
            state.active.append(
                FunctionBlock(
                    "<anonymous>",
                    state.swift_candidate_start,
                    state.swift_candidate_parent_depth,
                    params,
                )
            )
            clear_swift_candidate(state)
        elif state.swift_candidate_open and "}" in clean:
            clear_swift_candidate(state)
        return

    detected = detect_brace_function(clean.strip(), "swift")
    if detected:
        state.pending_signature = [clean]
        params = count_params_in_signature(clean, detected, "swift")
        state.pending = (detected, line_number, params, False)
        return

    if swift_candidate_possible(clean):
        state.swift_candidate = [clean]
        state.swift_candidate_start = line_number
        state.swift_candidate_parent_depth = state.brace_depth
        state.swift_candidate_open = "{" in clean
