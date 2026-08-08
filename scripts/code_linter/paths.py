from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import config_error


def collect_paths(root: Path, config: dict, args: argparse.Namespace) -> list[Path]:
    candidates = changed_paths(root, args.base, args.head) if args.mode == "changed" else all_repo_paths(root)
    if args.mode == "changed":
        config_relative = Path(args.config).as_posix().removeprefix("./")
        changed = {to_relative(root, path) for path in candidates}
        policy_changed = config_relative in changed or any(path.startswith(".github/workflows/") for path in changed)
        if policy_changed:
            candidates = all_repo_paths(root)

    include_extensions = set(config["include_extensions"])
    paths = []
    for path in candidates:
        if path.suffix.lower() not in include_extensions:
            continue
        if path.is_symlink():
            config_error(path, "Source symlinks are not allowed.")
        if not path.is_file():
            continue
        relative = to_relative(root, path)
        if should_ignore(relative, config["ignore"]):
            continue
        paths.append(path)
    return sorted(paths)


def changed_paths(root: Path, base: str, head: str) -> list[Path]:
    diff_args = [
        "git",
        "diff",
        "-z",
        "--name-only",
        "--diff-filter=ACMRT",
        f"{base}...{head}",
    ]
    result = subprocess.run(diff_args, cwd=root, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        diff_args = [
            "git",
            "diff",
            "-z",
            "--name-only",
            "--diff-filter=ACMRT",
            base,
            head,
        ]
        result = subprocess.run(diff_args, cwd=root, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        print(f"::error::Unable to collect changed files: {stderr}", file=sys.stderr)
        sys.exit(2)
    return [root / path for path in result.stdout.split("\0") if path]


def all_repo_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return [root / path for path in result.stdout.split("\0") if path]

    paths = []
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        for filename in filenames:
            paths.append(Path(current_root) / filename)
    return paths


def normalize_ignore_pattern(pattern: str) -> tuple[str, bool]:
    normalized = pattern.strip().replace("\\", "/")
    if normalized.startswith(("./", ".\\")):
        normalized = normalized[2:]
    normalized = normalized.removeprefix("/")
    is_directory = normalized.endswith("/")
    return normalized.rstrip("/"), is_directory


def matches_ignore_pattern(relative_path: str, pattern: str) -> bool:
    parts = relative_path.split("/")
    basename = parts[-1]
    normalized, is_directory = normalize_ignore_pattern(pattern)
    if not normalized:
        return False
    if is_directory and "/" not in normalized:
        return normalized in parts
    if is_directory:
        return relative_path.startswith(f"{normalized}/") or fnmatch.fnmatch(relative_path, f"**/{normalized}/*")
    if "/" not in normalized:
        return any(part == normalized for part in parts) or fnmatch.fnmatch(basename, normalized)
    return fnmatch.fnmatch(relative_path, normalized) or fnmatch.fnmatch(relative_path, f"**/{normalized}")


def should_ignore(relative_path: str, patterns: Sequence[str]) -> bool:
    return any(matches_ignore_pattern(relative_path, pattern) for pattern in patterns)


def to_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        # A symlink pointing outside the repo resolves out of `root`; report it
        # under the path git gave us rather than crashing the whole gate.
        return os.path.relpath(path, root).replace(os.sep, "/")
