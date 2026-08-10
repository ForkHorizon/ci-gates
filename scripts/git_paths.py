from __future__ import annotations

import os
import sys


def split_git_paths(output: bytes | str) -> list[str]:
    if isinstance(output, bytes):
        return [os.fsdecode(value) for value in output.split(b"\0") if value]
    return [value for value in output.split("\0") if value]


def git_output_text(output: bytes | str) -> str:
    if isinstance(output, bytes):
        return output.decode(sys.getfilesystemencoding(), errors="backslashreplace")
    return output
