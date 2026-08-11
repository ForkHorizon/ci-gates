from __future__ import annotations

import re
from typing import TYPE_CHECKING

from . import javascript_tracking
from .swift_syntax import swift_type_declaration_kind

if TYPE_CHECKING:
    from .functions import FunctionScanState


def track_declaration_context(state: FunctionScanState, clean: str, language: str) -> None:
    state.type_scopes = [scope for scope in state.type_scopes if scope[0] <= state.brace_depth]
    state.swift_type_scopes = [scope for scope in state.swift_type_scopes if scope[0] <= state.brace_depth]
    state.method_scopes = [depth for depth in state.method_scopes if depth <= state.brace_depth]
    state.javascript_declaration_scopes = [
        depth for depth in state.javascript_declaration_scopes if depth <= state.brace_depth
    ]
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
        javascript_tracking.track_split_type_context(state, clean)
        class_pattern = r"\b(?:class|interface)(?:\s+[A-Za-z_$][A-Za-z0-9_$]*)?[^{}]*\{"
        object_pattern = r"(?:\b(?:const|let|var)\s+[A-Za-z_$][A-Za-z0-9_$]*\s*=\s*)\{"
        scope_matches = [
            *re.finditer(class_pattern, clean),
            *re.finditer(object_pattern, clean),
            *re.finditer(r"(?:\breturn\s*|\(\s*|,\s*)\{", clean),
            *re.finditer(r"\b[A-Za-z_$][A-Za-z0-9_$]*\s*\(\s*\{", clean),
            *re.finditer(r"\bexport\s+default\s*\{|\bmodule\.exports\s*=\s*\{", clean),
        ]
        for scope_match in scope_matches:
            depth = state.brace_depth + clean[: scope_match.end()].count("{")
            state.method_scopes.append(depth)
            if re.search(r"\binterface\b|\bdeclare\s+class\b", scope_match.group()) or (
                re.search(r"\bdeclare\b", clean) and "class" in scope_match.group()
            ):
                state.javascript_declaration_scopes.append(depth)
    if language == "swift":
        kind = swift_type_declaration_kind(clean)
        opening = clean.find("{")
        if kind and opening >= 0:
            state.swift_type_scopes.append((state.brace_depth + 1, kind))
