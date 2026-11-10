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
    from rust_tests import cargo_test_keys, rust_tests, tests_lost
    from test_approvals import ApprovalState, all_approved, change_item, load_approvals
except ModuleNotFoundError:
    from .added_lines import added_lines
    from .rust_tests import cargo_test_keys, rust_tests, tests_lost
    from .test_approvals import ApprovalState, all_approved, change_item, load_approvals

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
    r"|#\[ignore\b|#\[cfg\(any\(\)\)\]"
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


def _show(root: Path, rev: str, path: str) -> str | None:
    result = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=root, capture_output=True, text=True, check=False)
    return None if result.returncode else result.stdout


def _rust_files_now(root: Path, skip: str) -> dict[str, int]:
    """Tests defined in every Rust file of the checkout except `skip` (the file being removed)."""
    listed = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.rs").split("\0")
    found: dict[str, int] = {}
    for path in filter(None, listed):
        if path == skip or not (root / path).is_file():
            continue
        for name, asserts in rust_tests((root / path).read_text(encoding="utf-8", errors="replace")).items():
            found[name] = max(found.get(name, 0), asserts)
    return found


def _moved_intact(root: Path, base_rev: str, path: str) -> bool:
    """A deleted Rust test file is a move when every test in it, with at least its assertions, lives on elsewhere."""
    old = rust_tests(_show(root, base_rev, path) or "") if path.endswith(".rs") else {}
    return bool(old) and not tests_lost(old, _rust_files_now(root, path))


def _cargo_test_config_changed(root: Path, revisions: tuple[str, str, str], path: str) -> bool:
    git_mode, base, head = revisions
    old = _show(root, base if git_mode == "committed" else "HEAD", path) or ""
    new = (
        _show(root, head, path)
        if git_mode == "committed"
        else (root / path).read_text(encoding="utf-8", errors="replace")
    )
    return cargo_test_keys(old) != cargo_test_keys(new or "")


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


def _runner_finding(
    root: Path, revisions: tuple[str, str, str], change: tuple[str, str], state: ApprovalState, findings: list[Finding]
) -> None:
    """Changes to what tests are built or run: not approvable as test edits, they weaken the check itself. Only the
    owner's protected-file approval of this exact content clears them."""
    status, new = change
    if _config_approved(root, revisions, new, state):
        return
    if status == "M" and PurePosixPath(new).name == "Cargo.toml" and _cargo_test_config_changed(root, revisions, new):
        findings.append(
            Finding("high", new, "test-build-config-changed", "Cargo.toml changes which tests are built or run")
        )
    elif status in "MR" and any(re.search(pattern, new) for pattern in RUNNER_FILES):
        findings.append(Finding("high", new, "runner-config-changed", "test runner configuration changed"))
    elif status == "M" and PurePosixPath(new).name == "package.json" and _package_script_changed(root, *revisions, new):
        findings.append(Finding("high", new, "runner-config-changed", "package.json scripts.test changed"))


def _config_approved(root: Path, revisions: tuple[str, str, str], path: str, state: ApprovalState) -> bool:
    if path not in state.config_approved:
        return False
    git_mode, base, head = revisions
    now, before = (None, "HEAD") if git_mode == "worktree" else (head, base)
    return change_item(root, (now, before), "modified", path)["fingerprint"] in state.config_approved[path]


def _test_edit(
    root: Path, revisions: tuple[str, str, str], status: str, old: str, new: str
) -> tuple[str, str, str, list[dict]]:
    """(rule id, path, message, items) of an edit to an existing test file; the items are what the owner approves."""
    git_mode, base, head = revisions
    now, before = (None, "HEAD") if git_mode == "worktree" else (head, base)
    if status == "D":
        return "test-deleted", old, "existing test file was deleted", [change_item(root, (now, before), "deleted", old)]
    if status == "R":
        items = [change_item(root, (now, before), "deleted", old), change_item(root, (now, before), "added", new)]
        return "test-renamed", old, f"existing test file was renamed to {new}", items
    message = "existing test file has removed or changed lines"
    return "test-modified", new, message, [change_item(root, (now, before), "modified", new)]


def scan(root: Path, git_mode: str, base: str, head: str, config: Path | None = None) -> list[Finding]:
    return scan_with_approvals(root, (git_mode, base, head), config, ApprovalState())


def scan_with_approvals(
    root: Path, revisions: tuple[str, str, str], config: Path | None, state: ApprovalState
) -> list[Finding]:
    """Findings for edits that weaken tests. `state.approved` (the owner's decisions) clears edits to existing
    tests; the items of the edits left are appended to `state.requests` so a gate can ask the owner about them."""
    git_mode, base, head = revisions
    root = root.resolve()
    extra, excluded = _config(config)
    revision = _revision(git_mode, base, head)
    findings: list[Finding] = []
    for status, old, new in _changes(root, revision):
        if status == "M" and is_test_path(new, extra, excluded):
            weakened = bool(_deleted_lines(root, revision, new))
        elif status in "DR" and is_test_path(old, extra, excluded):
            weakened = not (status == "D" and _moved_intact(root, base if git_mode == "committed" else "HEAD", old))
        else:
            weakened = False
            _runner_finding(root, (git_mode, base, head), (status, new), state, findings)
        if weakened:
            rule, path, message, items = _test_edit(root, (git_mode, base, head), status, old, new)
            if not all_approved(items, state.approved):
                findings.append(Finding("high", path, rule, message))
                state.requests.extend(items)
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


ASK_HINT = (
    "No owner request exists for these edits yet. To create one for exactly this content, commit with "
    "CI_SCOPE_TEST_EDIT_REASON='why the tests change' (the CI Scope git hook sends it); the owner then approves "
    "it in the Inbox."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=("new", "all"), default="new", help="accepted for adapter symmetry")
    parser.add_argument("--git-mode", choices=("worktree", "committed"), default="worktree")
    parser.add_argument("--base", default="HEAD~1")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--approved", type=Path, help="JSON of the owner's approved test edits (path, fingerprint).")
    parser.add_argument("--config-approved", type=Path, help="JSON of the owner's approved protected files.")
    parser.add_argument("--request-out", type=Path, help="Write the unapproved test edits here as request items.")
    args = parser.parse_args(argv)
    try:
        state = ApprovalState(load_approvals(args.approved), config_approved=load_approvals(args.config_approved))
        findings = scan_with_approvals(args.root, (args.git_mode, args.base, args.head), args.config, state)
        if args.request_out is not None:
            args.request_out.write_text(json.dumps(state.requests), encoding="utf-8")
    except (OSError, ValueError, RuntimeError) as error:
        print(f"test-protection: {error}", file=sys.stderr)
        return 2
    for finding in findings:
        print(f"{finding.path}  {finding.severity}  {finding.rule_id}  {finding.message}")
    if state.requests and args.request_out is None:
        print(ASK_HINT)
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
