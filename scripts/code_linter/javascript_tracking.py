from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .signatures import count_params_in_signature, detect_brace_function

if TYPE_CHECKING:
    from .functions import FunctionScanState


def track_javascript_signature(state: FunctionScanState, clean: str, line_number: int, language: str) -> None:
    enclosing_types = frozenset(name for _, name in state.type_scopes)
    allow_method_fallback = bool(state.method_scopes)
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
