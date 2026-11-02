"""Rust rules for forbidden_constructs: lint suppressions an agent could use to silence checks."""

RUST_RULES = [
    (
        "no-lint-suppression",
        r"#!?\[[^\]]*\b(?:allow|expect)\s*\(",
        "lint suppression attributes need an allow marker and reason",
    ),
    (
        "no-rustfmt-skip",
        r"\brustfmt::skip\b|#!?\[rustfmt::skip",
        "rustfmt::skip needs an allow marker and reason",
    ),
]
