"""Rust test inventory used by test-protection: which tests a file defines, and which Cargo keys change what runs."""

from __future__ import annotations

import re

_TEST_FN = re.compile(
    r"#\[(?:\w+::)*test\b[^\]]*\](?:\s*#\[[^\]]*\])*\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)\s*\("
)
_ASSERT = re.compile(r"\bassert\w*!")
_CARGO_KEY = re.compile(r"(autotests|autobenches|harness)\s*=|test\s*=\s*(?:true|false)\b")


def _body(text: str, start: int) -> str:
    """The braces after `start`; the rest of the file when they never balance."""
    depth, opened = 0, False
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth, opened = depth + 1, True
        elif char == "}" and opened:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:]


def rust_tests(text: str) -> dict[str, int]:
    """Test function name -> number of assert macros in its body. Duplicate names keep the larger count."""
    found: dict[str, int] = {}
    for match in _TEST_FN.finditer(text):
        count = len(_ASSERT.findall(_body(text, match.end())))
        found[match.group(1)] = max(found.get(match.group(1), 0), count)
    return found


def tests_lost(old: dict[str, int], new: dict[str, int]) -> list[str]:
    """Tests of `old` that are missing from `new` or carry fewer assertions there."""
    return sorted(name for name, asserts in old.items() if name not in new or new[name] < asserts)


def cargo_test_keys(text: str) -> list[str]:
    """Lines of a Cargo.toml that change which tests are built or run: `[[test]]` tables, autotests, harness, test = ..."""
    section, keys = "", []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            section = line
            if section == "[[test]]":
                keys.append(section)
        elif section == "[[test]]" or _CARGO_KEY.match(line):
            keys.append(f"{section} {line}")
    return sorted(keys)
