from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .config_io import config_error


def reject_blanket_ignores(patterns: Sequence[str], path: Path, extensions: Sequence[str]) -> None:
    forbidden = {"*", "**", "**/*"}
    for extension in extensions:
        forbidden.update({f"*{extension}", f"**{extension}", f"**/*{extension}"})
    invalid = [
        pattern
        for pattern in patterns
        if pattern.strip().replace("\\", "/").removeprefix("./").removeprefix("/") in forbidden
    ]
    if invalid:
        config_error(
            path,
            f"Blanket source ignore pattern(s) are not allowed: {', '.join(invalid)}.",
        )
