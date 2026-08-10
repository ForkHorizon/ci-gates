from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import LANGUAGE_BY_EXTENSION, config_error, language_for_path
from .coverage import (
    UNSUPPORTED_SURFACE_BY_EXTENSION,
    UNSUPPORTED_SURFACE_BY_FILENAME,
    CoverageGap,
    PathInventory,
    unknown_text_surface,
)
from .github import format_github_command
from git_paths import git_output_text, split_git_paths


def collect_paths(root: Path, config: dict, args: argparse.Namespace) -> list[Path]:
    return list(collect_path_inventory(root, config, args).selected)


def collect_path_inventory(root: Path, config: dict, args: argparse.Namespace) -> PathInventory:
    candidates = candidate_paths(root, args)
    include_extensions = set(config["include_extensions"])
    policy_path = to_relative(root, root / args.config)
    scan_config = {**config, "_policy_path": policy_path}
    paths = []
    gaps = []
    for path in candidates:
        gap = coverage_gap_for(root, path, scan_config, include_extensions)
        if gap is not None:
            gaps.append(gap)
            continue
        if (
            to_relative(root, path) != policy_path
            and path.is_file()
            and (path.suffix.lower() in include_extensions or language_for_path(path) == "gitignore")
        ):
            paths.append(path)
    return PathInventory(tuple(sorted(paths)), tuple(sorted(gaps, key=lambda gap: gap.path)))


def candidate_paths(root: Path, args: argparse.Namespace) -> list[Path]:
    candidates = changed_paths(root, args.base, args.head) if args.mode == "changed" else all_repo_paths(root)
    if args.mode != "changed":
        return candidates
    config_relative = to_relative(root, root / args.config)
    changed = {to_relative(root, path) for path in candidates}
    policy_changed = config_relative in changed or any(path.startswith(".github/workflows/") for path in changed)
    return all_repo_paths(root) if policy_changed else candidates


def coverage_gap_for(root: Path, path: Path, config: dict, include_extensions: set[str]) -> CoverageGap | None:
    if path.is_symlink():
        config_error(path, "Repository symlinks are not allowed.")
    extension = path.suffix.lower()
    language = language_for_path(path)
    surface = unsupported_surface(path)
    relative = to_relative(root, path)
    if relative == config.get("_policy_path", ".code-linter.json") or not path.is_file():
        return None
    unknown = unknown_text_surface(path) if language is None and surface is None else None
    if isinstance(unknown, CoverageGap):
        return CoverageGap(relative, unknown.category, unknown.extension, unknown.message)
    source_like = language is not None or surface is not None or unknown is not None
    ignored_by = tuple(pattern for pattern in config["ignore"] if matches_ignore_pattern(relative, pattern))
    if ignored_by and source_like:
        category = "ignored_source" if extension in LANGUAGE_BY_EXTENSION else "ignored_unsupported_surface"
        return CoverageGap(
            relative,
            category,
            extension,
            f"Source-like file is skipped by ignore pattern(s): {', '.join(ignored_by)}.",
            ignored_by,
        )
    if language is not None and extension and extension not in include_extensions and language != "gitignore":
        return CoverageGap(
            relative,
            "excluded_extension",
            extension,
            f"Supported extension {extension!r} is not included by the active policy.",
        )
    if surface is not None or unknown is not None:
        if surface is not None:
            label, display_extension = surface
            category = "unsupported_surface"
            message = f"{label} surface is not structurally supported by Code Linter."
        else:
            assert unknown is not None
            label, display_extension = unknown
            category = "unknown_text_surface"
            message = f"{label.title()} is not mapped to a structural checker."
        return CoverageGap(
            relative,
            category,
            display_extension,
            message,
        )
    return None


def changed_paths(root: Path, base: str, head: str) -> list[Path]:
    diff_args = [
        "git",
        "diff",
        "-z",
        "--name-only",
        "--diff-filter=ACMRT",
        f"{base}...{head}",
    ]
    result = subprocess.run(diff_args, cwd=root, text=False, capture_output=True, check=False)
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
        result = subprocess.run(diff_args, cwd=root, text=False, capture_output=True, check=False)
    if result.returncode != 0:
        stderr = git_output_text(result.stderr).strip() or git_output_text(result.stdout).strip()
        message = f"Unable to collect changed files: {stderr}"
        print(format_github_command("error", data=message), file=sys.stderr)
        sys.exit(2)
    return [root / path for path in split_git_paths(result.stdout)]


def all_repo_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        text=False,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return [root / path for path in split_git_paths(result.stdout)]

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


def unsupported_surface(path: Path) -> tuple[str, str] | None:
    extension = path.suffix.lower()
    if extension in UNSUPPORTED_SURFACE_BY_EXTENSION:
        return UNSUPPORTED_SURFACE_BY_EXTENSION[extension], extension
    filename = path.name.lower()
    if filename in UNSUPPORTED_SURFACE_BY_FILENAME:
        return UNSUPPORTED_SURFACE_BY_FILENAME[filename], filename
    return None


def to_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        # A symlink pointing outside the repo resolves out of `root`; report it
        # under the path git gave us rather than crashing the whole gate.
        return os.path.relpath(path, root).replace(os.sep, "/")
