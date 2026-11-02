#!/usr/bin/env python3
"""Install the CI Scope git hooks once per device through a global core.hooksPath."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HOOKS = ("pre-commit", "pre-push")
GATES = Path(__file__).resolve().parents[1]


class InstallError(RuntimeError):
    pass


def global_hooks_path() -> str:
    result = subprocess.run(
        ["git", "config", "--global", "--get", "core.hooksPath"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


def install(hooks_dir: Path, gates: Path = GATES, *, set_config: bool = True) -> list[Path]:
    """Write the hooks and the CLI wrapper into `hooks_dir`; point git at it unless another path is configured."""
    current = global_hooks_path()
    if set_config and current and Path(current).expanduser().resolve() != hooks_dir.resolve():
        raise InstallError(f"core.hooksPath is already set to {current}; not overwriting it")
    hooks_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in HOOKS:
        target = hooks_dir / name
        shutil.copyfile(gates / "scripts/hooks/ci-scope-hook", target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written.append(target)
    wrapper = hooks_dir / "ci-scope-check"
    wrapper.write_text(f'#!/bin/sh\nexec python3 "{gates / "scripts/ci_scope_cli.py"}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    written.append(wrapper)
    if set_config:
        subprocess.run(["git", "config", "--global", "core.hooksPath", str(hooks_dir)], check=True)
    return written


def main(argv: list[str]) -> int:
    hooks_dir = (
        Path(argv[0]) if argv else Path(os.environ.get("CI_SCOPE_HOOKS_DIR", Path.home() / ".config/ci-scope/hooks"))
    )
    try:
        written = install(hooks_dir)
    except InstallError as error:
        print(f"install_hooks: {error}", file=sys.stderr)
        return 2
    print(f"Installed {len(written)} files in {hooks_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
