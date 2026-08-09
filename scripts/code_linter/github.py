from __future__ import annotations


def escape_github_data(value: str) -> str:
    return _escape_github(value, property_value=False)


def escape_github_property(value: str) -> str:
    return _escape_github(value, property_value=True)


def _escape_github(value: str, *, property_value: bool) -> str:
    escaped = []
    for character in value:
        codepoint = ord(character)
        if character == "%":
            escaped.append("%25")
        elif character == "\r":
            escaped.append("%0D")
        elif character == "\n":
            escaped.append("%0A")
        elif property_value and character == ",":
            escaped.append("%2C")
        elif property_value and character == ":":
            escaped.append("%3A")
        elif codepoint < 0x20 or 0x7F <= codepoint <= 0x9F:
            escaped.append(f"%{codepoint:02X}")
        else:
            escaped.append(character)
    return "".join(escaped)
