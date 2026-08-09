from __future__ import annotations

from pathlib import Path

from .model import Issue

_SOURCE_WHITESPACE_CONTROLS = frozenset("\t\n\r")
_C_STYLE_WHITESPACE_CONTROLS = frozenset("\t\n\v\f\r")
_LANGUAGE_WHITESPACE_CONTROLS = {
    "c": _C_STYLE_WHITESPACE_CONTROLS,
    "cpp": _C_STYLE_WHITESPACE_CONTROLS,
    "objective_c": _C_STYLE_WHITESPACE_CONTROLS,
    "csharp": _C_STYLE_WHITESPACE_CONTROLS,
    "dart": _C_STYLE_WHITESPACE_CONTROLS,
    "javascript": _C_STYLE_WHITESPACE_CONTROLS,
    "typescript": _C_STYLE_WHITESPACE_CONTROLS,
    "php": _C_STYLE_WHITESPACE_CONTROLS,
    "shell": _C_STYLE_WHITESPACE_CONTROLS,
    "python": frozenset("\t\n\f\r"),
    "java": frozenset("\t\n\f\r"),
    "kotlin": frozenset("\t\n\f\r"),
    "scala": frozenset("\t\n\f\r"),
    "swift": frozenset("\t\n\f\r"),
    "groovy": frozenset("\t\n\f\r"),
    "ruby": frozenset("\t\n\f\r"),
    "go": _SOURCE_WHITESPACE_CONTROLS,
    "rust": _SOURCE_WHITESPACE_CONTROLS,
    "json": _SOURCE_WHITESPACE_CONTROLS,
    "yaml": _SOURCE_WHITESPACE_CONTROLS,
    "toml": _SOURCE_WHITESPACE_CONTROLS,
}


def decode_source(raw: bytes, relative: Path, language: str | None) -> tuple[str | None, Issue | None]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = raw.count(b"\n", 0, exc.start) + 1
        return None, Issue(relative, line, "encoding", "Source is not valid UTF-8.")

    allowed_controls = _LANGUAGE_WHITESPACE_CONTROLS.get(language, _SOURCE_WHITESPACE_CONTROLS)
    for index, character in enumerate(text):
        codepoint = ord(character)
        is_control = codepoint < 0x20 or 0x7F <= codepoint <= 0x9F
        if is_control and character not in allowed_controls:
            line = text.count("\n", 0, index) + 1
            return None, Issue(
                relative,
                line,
                "binary_source",
                f"Source contains forbidden control character U+{codepoint:04X}.",
            )
    return text, None
