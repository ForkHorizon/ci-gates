from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys

try:
    from added_lines import added_lines
except ModuleNotFoundError:
    from .added_lines import added_lines


EXTENSIONS = {".py", ".go", ".swift", ".ts", ".tsx", ".js", ".mjs", ".cs"}
EXCLUDED_PARTS = {
    "tests",
    "test",
    "fixtures",
    "node_modules",
    "vendor",
    "Pods",
    ".build",
}
COMMENT = re.compile(r"^(?:#|//|/\*|\*/|\*\s)")
IMPORT = re.compile(r"^(?:import\s|from\s+\S+\s+import\s)")
CLOSER = re.compile(r"^[\s\]\[{}(),;]+$")


@dataclass(frozen=True)
class CheckOptions:
    mode: str
    git_mode: str
    base: str
    head: str
    min_lines: int
    config: Path | None


def significant_lines(lines: list[str]) -> list[str]:
    result = []
    for line in lines:
        value = " ".join(line.split())
        if value and not COMMENT.match(value) and not IMPORT.match(value) and not CLOSER.fullmatch(value):
            result.append(value)
    return result


def find_duplicates(
    files: dict[str, list[str]], added: dict[str, set[int]], min_lines: int = 10
) -> list[tuple[str, str]]:
    occurrences = {}
    for path, lines in files.items():
        for key, start, end, _line_numbers in _windows(lines, min_lines):
            occurrences.setdefault(key, []).append((path, start, end))
    matches = []
    for path, lines in files.items():
        selected = added.get(path, set())
        for key, start, end, line_numbers in _windows(lines, min_lines):
            if not line_numbers.issubset(selected):
                continue
            other = next(
                (item for item in occurrences[key] if item[0] != path or item[2] < start or item[1] > end),
                None,
            )
            if other:
                matches.append((path, other[0], start, end, other[1], other[2]))
    return _merge_matches(matches)


def _windows(lines: list[str], width: int):
    significant = _significant_indexed(lines)
    for offset in range(len(significant) - width + 1):
        window = significant[offset : offset + width]
        body = "\n".join(value for _, value in window)
        yield (
            hashlib.sha256(body.encode()).digest(),
            window[0][0],
            window[-1][0],
            {line for line, _ in window},
        )


def _significant_indexed(lines: list[str]):
    return [
        (index, value)
        for index, raw in enumerate(lines, 1)
        if (value := " ".join(raw.split()))
        and not COMMENT.match(value)
        and not IMPORT.match(value)
        and not CLOSER.fullmatch(value)
    ]


def _merge_matches(matches):
    merged = []
    for path, other, start, end, other_start, other_end in sorted(matches):
        prior = next(
            (item for item in reversed(merged) if item[0] == path and item[1] == other and start <= item[3]),
            None,
        )
        if prior:
            prior[3] = max(prior[3], end)
            prior[5] = max(prior[5], other_end)
        else:
            merged.append([path, other, start, end, other_start, other_end])
    return [
        (f"{path}:{start}-{end}", f"{other}:{other_start}-{other_end}")
        for path, other, start, end, other_start, other_end in merged
    ]


def _source_files(root: Path, excludes: list[str]):
    for directory, names, filenames in os.walk(root):
        names[:] = [
            name
            for name in names
            if name not in EXCLUDED_PARTS and not any(Path(name).match(pattern) for pattern in excludes)
        ]
        for name in filenames:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if (
                path.suffix.lower() in EXTENSIONS
                and ".compiled." not in name
                and ".generated." not in name
                and not path.is_symlink()
                and not any(Path(relative).match(pattern) for pattern in excludes)
            ):
                yield relative, path


def check(root: Path, request: CheckOptions):
    root = root.resolve()
    options = (
        json.loads(request.config.read_text(encoding="utf-8")) if request.config and request.config.is_file() else {}
    )
    if not isinstance(options, dict) or set(options) - {"exclude", "min_lines"}:
        raise ValueError("config accepts only exclude and min_lines")
    excludes = options.get("exclude", [])
    min_lines = options.get("min_lines", request.min_lines)
    if (
        not isinstance(excludes, list)
        or not all(isinstance(item, str) for item in excludes)
        or isinstance(min_lines, bool)
        or not isinstance(min_lines, int)
        or not 2 <= min_lines <= 100
    ):
        raise ValueError("exclude must be strings and min_lines must be between 2 and 100")
    files = {name: path.read_text(encoding="utf-8").splitlines() for name, path in _source_files(root, excludes)}
    additions = (
        added_lines(root, request.git_mode, request.base, request.head)
        if request.mode == "new"
        else {path: set(range(1, len(lines) + 1)) for path, lines in files.items()}
    )
    return find_duplicates(files, additions, min_lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Detect duplicated blocks in added source lines.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=("new", "all"), default="new")
    parser.add_argument("--git-mode", choices=("worktree", "committed"), default="worktree")
    parser.add_argument("--base", default="HEAD~1")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--min-lines", type=int, default=10)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    try:
        matches = check(
            args.root,
            CheckOptions(
                args.mode,
                args.git_mode,
                args.base,
                args.head,
                args.min_lines,
                args.config,
            ),
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"duplicate-blocks: {error}", file=sys.stderr)
        return 2
    for added, existing in matches:
        print(f"{added}  duplicates  {existing}")
    return int(bool(matches))


if __name__ == "__main__":
    raise SystemExit(main())
