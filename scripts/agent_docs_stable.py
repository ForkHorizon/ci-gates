"""Keep AGENTS.md and CLAUDE.md free of volatile facts so the prompt prefix stays stable and cacheable."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from added_lines import added_lines
except ModuleNotFoundError:
    from .added_lines import added_lines

DOC_NAMES = {"agents.md", "claude.md"}
ALLOW = re.compile(r"allow-volatile:\s*(?!-->)(\S.*?)\s*(?:-->|$)")
RULES = (
    ("no-date", r"\b20\d{2}-\d{2}-\d{2}\b|\b\d{1,2}\.\d{1,2}\.20\d{2}\b", "dates go stale; link to a dated source"),
    (
        "no-updated-marker",
        r"(?i)\b(?:last\s+updated|updated\s+on|as\s+of|current(?:ly)?\s+status)\b",
        "'as of'/'last updated' markers make the file change on every edit",
    ),
    ("no-commit-sha", r"\b[0-9a-f]{40}\b", "commit SHAs change constantly; reference a branch or tag"),
    ("no-pr-number", r"(?i)\b(?:pr|pull request|issue)\s*#\d+\b", "PR and issue numbers belong in git history"),
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule_id: str
    message: str


def scan_text(text: str, selected: set[int] | None = None) -> list[tuple[int, str, str]]:
    findings = []
    for number, line in enumerate(text.splitlines(), start=1):
        if selected is not None and number not in selected:
            continue
        allow = ALLOW.search(line)
        if allow and allow.group(1):
            continue
        findings.extend((number, rule, message) for rule, pattern, message in RULES if re.search(pattern, line))
    return findings


def check(root: Path, mode: str, git_mode: str, base: str, head: str) -> list[Finding]:
    root = root.resolve()
    additions = added_lines(root, git_mode, base, head) if mode == "new" else {}
    results = []
    for path in sorted(root.rglob("*.md")):
        if path.name.lower() not in DOC_NAMES or path.is_symlink() or ".git" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        selected = additions.get(relative, set()) if mode == "new" else None
        if mode == "new" and not selected:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        results.extend(Finding(relative, number, rule, message) for number, rule, message in scan_text(text, selected))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=("new", "all"), default="new")
    parser.add_argument("--git-mode", choices=("worktree", "committed"), default="worktree")
    parser.add_argument("--base", default="HEAD~1")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    try:
        findings = check(args.root, args.mode, args.git_mode, args.base, args.head)
    except (OSError, RuntimeError) as error:
        print(f"agent-docs-stable: {error}", file=sys.stderr)
        return 2
    for finding in findings:
        print(f"{finding.path}:{finding.line}  {finding.rule_id}  {finding.message}")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
