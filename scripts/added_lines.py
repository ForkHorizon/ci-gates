from __future__ import annotations

import subprocess
from pathlib import Path


def parse_hunks(diff_text: str) -> set[int]:
    added = set()
    line_number = None
    old_remaining = new_remaining = 0
    for line in diff_text.splitlines():
        if line.startswith("@@"):
            header = line.split("@@", 2)[1].split(" ")
            old_range = next(part[1:] for part in header if part.startswith("-"))
            new_range = next(part[1:] for part in header if part.startswith("+"))
            line_number = int(new_range.partition(",")[0])
            old_remaining = int(old_range.split(",", 1)[1]) if "," in old_range else 1
            new_remaining = int(new_range.split(",", 1)[1]) if "," in new_range else 1
            continue
        if line_number is None or line.startswith("\\"):
            continue
        if line.startswith("+"):
            added.add(line_number)
            line_number += 1
            new_remaining -= 1
        elif line.startswith(" "):
            line_number += 1
            old_remaining -= 1
            new_remaining -= 1
        elif line.startswith("-"):
            old_remaining -= 1
        if old_remaining <= 0 and new_remaining <= 0:
            line_number = None
    return added


def added_lines(root: Path, mode: str, base: str = "HEAD~1", head: str = "HEAD") -> dict[str, set[int]]:
    root = Path(root).resolve()
    revision = f"{base}...{head}" if mode == "committed" else "HEAD"
    names = _git(root, "diff", "--name-only", "-z", "--diff-filter=ACMRT", revision, "--").split("\0")
    result = {}
    for name in filter(None, names):
        path = root / name
        if path.is_file() and not path.is_symlink():
            diff = _git(root, "diff", "--no-ext-diff", "--unified=0", revision, "--", name)
            result[name] = parse_hunks(diff)
    if mode == "worktree":
        untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
        for name in filter(None, untracked):
            path = root / name
            if path.is_file() and not path.is_symlink():
                result[name] = set(range(1, len(path.read_text(encoding="utf-8").splitlines()) + 1))
    return result


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout
