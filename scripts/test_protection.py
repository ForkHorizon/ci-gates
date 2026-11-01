"""Detect agent edits that weaken existing tests: modified/deleted/renamed test files, runner config changes, new skips."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

try:
    from added_lines import added_lines
except ModuleNotFoundError:
    from .added_lines import added_lines

TEST_PATTERNS = (
    r"(^|/)tests?/",
    r"(^|/)Tests/",
    r"(^|/)__tests__/",
    r"(^|/)Assets/Tests/",
    r"_test\.go$",
    r"_test\.py$",
    r"(^|/)test_[^/]*\.py$",
    r"\.(spec|test)\.(ts|tsx|js|jsx|mjs|cjs)$",
    r"Tests?\.(swift|cs|kt|java)$",
)
RUNNER_FILES = (
    r"(^|/)(pytest|tox)\.ini$",
    r"(^|/)conftest\.py$",
    r"(^|/)(jest|vitest)\.config\.[a-z]+$",
    r"(^|/)Makefile$",
)
SKIP_MARKERS = re.compile(
    r"\.skip\(|\b(?:xit|xdescribe|xtest)\(|@Disabled\b|\bt\.Skip(?:Now|f)?\(|pytest\.mark\.skip|@unittest\.skip|XCTSkip\b"
)
ALLOW = re.compile(r"allow-skip:\s*\S")


@dataclass(frozen=True)
class Finding:
    severity: str
    path: str
    rule_id: str
    message: str


def is_test_path(path: str, extra: tuple[str, ...] = (), excluded: tuple[str, ...] = ()) -> bool:
    if any(re.search(pattern, path) for pattern in excluded):
        return False
    return any(re.search(pattern, path) for pattern in (*TEST_PATTERNS, *extra))


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout


def _revision(git_mode: str, base: str, head: str) -> str:
    return f"{base}...{head}" if git_mode == "committed" else "HEAD"


def _changes(root: Path, revision: str) -> list[tuple[str, str, str]]:
    """(status, old_path, new_path) for every changed path."""
    output = _git(root, "diff", "--name-status", "-M", "-z", revision, "--").split("\0")
    changes, index = [], 0
    while index < len(output) and output[index]:
        status = output[index][0]
        if status in "RC":
            changes.append((status, output[index + 1], output[index + 2]))
            index += 3
        else:
            changes.append((status, output[index + 1], output[index + 1]))
            index += 2
    return changes


def _deleted_lines(root: Path, revision: str, path: str) -> int:
    row = _git(root, "diff", "--numstat", revision, "--", path).split("\t")
    return int(row[1]) if len(row) > 1 and row[1].isdigit() else 1


def _package_test_script(root: Path, rev: str, path: str) -> str | None:
    result = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=root, capture_output=True, text=True, check=False)
    if result.returncode:
        return None
    try:
        return json.loads(result.stdout).get("scripts", {}).get("test")
    except (ValueError, AttributeError):
        return None


def _package_script_changed(root: Path, git_mode: str, base: str, head: str, path: str) -> bool:
    old = _package_test_script(root, base if git_mode == "committed" else "HEAD", path)
    if git_mode == "committed":
        return old != _package_test_script(root, head, path)
    try:
        new = json.loads((root / path).read_text(encoding="utf-8")).get("scripts", {}).get("test")
    except (OSError, ValueError, AttributeError):
        new = None
    return old != new


def _config(path: Path | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if path is None or not path.is_file():
        return (), ()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) - {"patterns", "exclude"}:
        raise ValueError("config accepts only patterns and exclude")
    lists = []
    for key in ("patterns", "exclude"):
        items = value.get(key, [])
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise ValueError(f"{key} must be an array of regular expressions")
        for item in items:
            re.compile(item)
        lists.append(tuple(items))
    return lists[0], lists[1]


def scan(root: Path, git_mode: str, base: str, head: str, config: Path | None = None) -> list[Finding]:
    root = root.resolve()
    extra, excluded = _config(config)
    revision = _revision(git_mode, base, head)
    findings: list[Finding] = []
    for status, old, new in _changes(root, revision):
        if status == "M" and is_test_path(new, extra, excluded):
            if _deleted_lines(root, revision, new):
                findings.append(
                    Finding("high", new, "test-modified", "existing test file has removed or changed lines")
                )
        elif status == "D" and is_test_path(old, extra, excluded):
            findings.append(Finding("high", old, "test-deleted", "existing test file was deleted"))
        elif status == "R" and is_test_path(old, extra, excluded):
            findings.append(Finding("high", old, "test-renamed", f"existing test file was renamed to {new}"))
        elif status in "MR" and any(re.search(pattern, new) for pattern in RUNNER_FILES):
            findings.append(Finding("high", new, "runner-config-changed", "test runner configuration changed"))
        elif (
            status == "M"
            and PurePosixPath(new).name == "package.json"
            and _package_script_changed(root, git_mode, base, head, new)
        ):
            findings.append(Finding("high", new, "runner-config-changed", "package.json scripts.test changed"))
    findings.extend(_skip_findings(root, (git_mode, base, head), (extra, excluded)))
    return findings


def _skip_findings(
    root: Path, revisions: tuple[str, str, str], patterns: tuple[tuple[str, ...], tuple[str, ...]]
) -> list[Finding]:
    findings = []
    for path, numbers in added_lines(root, *revisions).items():
        if not is_test_path(path, *patterns):
            continue
        lines = (root / path).read_text(encoding="utf-8", errors="replace").splitlines()
        for number in sorted(numbers):
            line = lines[number - 1] if number <= len(lines) else ""
            if SKIP_MARKERS.search(line) and not ALLOW.search(line):
                findings.append(
                    Finding("medium", f"{path}:{number}", "test-skip-added", "a skip marker was added to a test")
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=("new", "all"), default="new", help="accepted for adapter symmetry")
    parser.add_argument("--git-mode", choices=("worktree", "committed"), default="worktree")
    parser.add_argument("--base", default="HEAD~1")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    try:
        findings = scan(args.root, args.git_mode, args.base, args.head, args.config)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"test-protection: {error}", file=sys.stderr)
        return 2
    for finding in findings:
        print(f"{finding.path}  {finding.severity}  {finding.rule_id}  {finding.message}")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
