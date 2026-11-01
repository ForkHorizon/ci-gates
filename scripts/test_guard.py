"""PreToolUse guard: refuse agent edits to existing (tracked) test files; new test files stay allowed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from test_protection import _config, is_test_path
except ModuleNotFoundError:
    from .test_protection import _config, is_test_path

OVERRIDE = "CI_SCOPE_ALLOW_TEST_EDIT"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def target_path(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    tool_input = payload.get("tool_input")
    value = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    return value if isinstance(value, str) and value else None


def blocked(root: Path, file_path: str) -> bool:
    absolute = Path(file_path) if Path(file_path).is_absolute() else root / file_path
    try:
        relative = absolute.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return False
    extra, excluded = _config(root / ".test-protection.json")
    if not is_test_path(relative, extra, excluded):
        return False
    return _git(root, "ls-files", "--error-unmatch", "--", relative).returncode == 0


def main(stdin_text: str, cwd: Path) -> int:
    if os.environ.get(OVERRIDE) == "1":
        return 0
    try:
        payload = json.loads(stdin_text)
    except ValueError:
        return 0
    file_path = target_path(payload)
    top = _git(cwd, "rev-parse", "--show-toplevel").stdout.strip()
    if not file_path or not top:
        return 0
    try:
        if blocked(Path(top), file_path):
            print(
                f"Existing test files are protected: {file_path}. Add a new test file instead of changing this one. "
                f"If a requirement really changed, ask the owner to allow it ({OVERRIDE}=1 for the session).",
                file=sys.stderr,
            )
            return 2
    except (OSError, ValueError) as error:
        print(f"test guard skipped: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.stdin.read(), Path.cwd()))
