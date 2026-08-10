from __future__ import annotations

import re

from .signatures import detect_brace_function


def javascript_object_detection_tail(
    source: str,
    detected: str | None,
    language: str,
    enclosing_types: frozenset[str],
    allow_method_fallback: bool,
) -> str | None:
    opening = source.find("{")
    if opening < 0:
        return None
    tail = source[opening + 1 :].lstrip()
    tail_detected = detect_brace_function(tail, language, enclosing_types, allow_method_fallback)
    object_source = source.lstrip().lstrip("}").lstrip()
    object_prefix = re.match(
        r"^(?:[A-Za-z_$][A-Za-z0-9_$]*\s*\(\s*(?:\(\s*)*\{|\{\s*|class\s|declare\s+class\s|interface\s|declare\s+namespace\s|export\s+default\s|module\.exports)",
        object_source,
    )
    if not (tail_detected and object_prefix):
        return None
    object_start = object_source.startswith(
        ("{", "class ", "declare class ", "interface ", "declare namespace ", "export default ", "module.exports")
    )
    method_start = re.match(r"^[A-Za-z_$][A-Za-z0-9_$]*\s*\(\s*(?:\(\s*)*\{", object_source)
    if tail_detected == detected and not (method_start or object_start):
        return None
    if (
        object_source.startswith(("class ", "interface ", "declare namespace ", "export default ", "module.exports"))
        and tail.count("}") > tail.count("{")
        and tail.rstrip().endswith("}")
    ):
        tail = tail.rstrip()[:-1].rstrip()
    return tail
