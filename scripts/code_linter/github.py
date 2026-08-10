from __future__ import annotations

from collections.abc import Iterable


def format_github_command(
    command: str,
    *,
    properties: Iterable[tuple[str, object]] = (),
    data: object = "",
) -> str:
    """Format a workflow command while escaping all dynamic fields."""
    encoded_properties = ",".join(f"{name}={escape_github_property(str(value))}" for name, value in properties)
    prefix = f"::{command}"
    if encoded_properties:
        prefix += f" {encoded_properties}"
    return f"{prefix}::{escape_github_data(str(data))}"


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
        elif 0xDC80 <= codepoint <= 0xDCFF:
            escaped.append(f"%{codepoint - 0xDC00:02X}")
        elif codepoint < 0x20 or 0x7F <= codepoint <= 0x9F:
            escaped.append(f"%{codepoint:02X}")
        else:
            escaped.append(character)
    return "".join(escaped)
