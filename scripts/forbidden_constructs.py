from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys

try:
    from added_lines import added_lines
except ModuleNotFoundError:
    from .added_lines import added_lines


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    rule_id: str
    message: str


@dataclass(frozen=True)
class ScanOptions:
    mode: str
    git_mode: str
    base: str
    head: str
    config: Path | None


RULES = {
    ".ts": [
        ("no-any", r":\s*any\b|\bas\s+any\b|<any>", "avoid explicit any"),
        (
            "no-ts-ignore",
            r"@ts-(?:ignore|nocheck)",
            "avoid TypeScript checking suppression",
        ),
        (
            "no-eslint-disable",
            r"eslint-disable(?:-next-line|-line)?\b",
            "eslint-disable needs a reason",
        ),
        (
            "no-empty-catch",
            r"catch(?:\s*\([^)]*\))?\s*\{\s*\}",
            "catch block must handle or explain the error",
        ),
    ],
    ".tsx": [],
    ".js": [],
    ".jsx": [],
    ".mjs": [],
    ".swift": [
        ("no-try-bang", r"\btry!", "avoid forced try"),
        ("no-force-cast", r"\bas!", "avoid forced casts"),
        (
            "no-swiftlint-disable",
            r"swiftlint:disable\b",
            "swiftlint:disable needs a reason",
        ),
        (
            "no-empty-catch",
            r"catch\s*\{\s*\}",
            "catch block must handle or explain the error",
        ),
    ],
    ".go": [
        (
            "no-ignored-error",
            r"_\s*=\s*err\b|_\s*=\s*(?:os\.(?:Chdir|Mkdir|MkdirAll|Remove|RemoveAll|WriteFile)|json\.Unmarshal)\s*\(",
            "do not discard a known error result",
        ),
        ("no-nolint", r"//\s*nolint\b", "nolint needs an allow marker and reason"),
    ],
    ".py": [
        (
            "no-type-ignore",
            r"#\s*type:\s*ignore\b",
            "type: ignore needs an allow marker and reason",
        ),
        (
            "no-noqa",
            r"#\s*noqa\b",
            "noqa needs an allow marker and reason",
        ),
        ("bare-except", r"^\s*except\s*:", "catch a specific exception"),
        (
            "no-broad-except-pass",
            r"^\s*except\s+(?:Exception|BaseException|[^:]+)\s*:\s*pass\s*(?:#.*)?$",
            "do not silently ignore an exception",
        ),
    ],
}
for extension in (".tsx", ".js", ".jsx", ".mjs"):
    RULES[extension] = RULES[".ts"]

ALLOW = re.compile(r"allow-([a-z][a-z0-9-]*):\s*(.*)")
SUPPORTED = set(RULES)
EXCLUDED_PARTS = {
    "tests",
    "test",
    "fixtures",
    "node_modules",
    "vendor",
    "Pods",
    ".build",
}


def scan_text(text: str, extension: str, added: set[int], *, mode: str = "new", rules=None) -> list[Violation]:
    lines = text.splitlines()
    selected = set(range(1, len(lines) + 1)) if mode == "all" else added
    findings = []
    for number in sorted(selected):
        if number < 1 or number > len(lines):
            continue
        line = lines[number - 1]
        marker = ALLOW.search(line)
        if marker and not marker.group(2).strip():
            findings.append(
                Violation(
                    "",
                    number,
                    "invalid-suppression",
                    f"allow-{marker.group(1)} needs a reason",
                )
            )
        for rule_id, pattern, message in _rules_for(extension.lower(), rules or {}):
            if not re.search(pattern, line) and not _empty_block(lines, number, rule_id):
                continue
            marker = _allow_marker(lines, number, rule_id, findings)
            if not marker:
                findings.append(Violation("", number, rule_id, message))
    return list(dict.fromkeys(findings))


def _rules_for(extension: str, overrides: dict) -> list[tuple[str, str, str]]:
    replaced = {rule[0]: rule for rule in overrides.get(extension, [])}
    defaults = [replaced.pop(rule[0], rule) for rule in RULES.get(extension, [])]
    return defaults + list(replaced.values())


def _empty_block(lines: list[str], number: int, rule_id: str) -> bool:
    line = lines[number - 1].strip()
    if rule_id == "no-empty-catch":
        if re.search(r"\bcatch(?:\s*\([^)]*\))?\s*\{\s*$", line):
            return _neighbor_code_line(lines[number:]).strip() == "}"
        if line == "}":
            previous = _neighbor_code_line(reversed(lines[: number - 1])).strip()
            return bool(re.search(r"\bcatch(?:\s*\([^)]*\))?\s*\{\s*$", previous))
    if rule_id == "no-broad-except-pass":
        header = r"except\s+(?:Exception|BaseException|[^:]+)\s*:\s*$"
        if re.match(header, line):
            return _neighbor_code_line(lines[number:]).strip() == "pass"
        if re.match(r"pass(?:\s+#.*)?$", line):
            previous = _neighbor_code_line(reversed(lines[: number - 1]))
            return bool(
                re.match(header, previous.strip())
                and len(lines[number - 1]) - len(lines[number - 1].lstrip()) > len(previous) - len(previous.lstrip())
            )
    return False


def _neighbor_code_line(lines: Iterable[str]) -> str:
    return next(
        (line for line in lines if line.strip() and not line.lstrip().startswith(("#", "//"))),
        "",
    )


def _allow_marker(lines: list[str], number: int, rule_id: str, findings: list[Violation]) -> bool:
    for index in (number - 1, number - 2):
        if index < 0:
            continue
        match = ALLOW.search(lines[index])
        if match and match.group(1) == rule_id:
            if not match.group(2).strip():
                findings.append(
                    Violation(
                        "",
                        index + 1,
                        "invalid-suppression",
                        f"allow-{rule_id} needs a reason",
                    )
                )
            else:
                return True
    return False


def _config(path: Path | None) -> tuple[dict, list[str]]:
    if path is None or not path.is_file():
        return {}, []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) - {"overrides", "exclude"}:
        raise ValueError("config accepts only overrides and exclude")
    overrides = value.get("overrides", [])
    exclude = value.get("exclude", [])
    if (
        not isinstance(overrides, list)
        or not isinstance(exclude, list)
        or not all(isinstance(item, str) for item in exclude)
    ):
        raise ValueError("overrides and exclude must be arrays")
    rules = {}
    for item in overrides:
        if not isinstance(item, dict) or set(item) != {
            "extension",
            "id",
            "pattern",
            "message",
        }:
            raise ValueError("each override needs extension, id, pattern, and message")
        extension, rule_id, pattern, message = (item[key] for key in ("extension", "id", "pattern", "message"))
        if (
            not isinstance(extension, str)
            or not isinstance(rule_id, str)
            or not isinstance(pattern, str)
            or not isinstance(message, str)
            or extension not in SUPPORTED
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", rule_id)
            or len(pattern) > 200
            or not message.strip()
        ):
            raise ValueError("invalid forbidden-construct rule override")
        if len(rules.get(extension, [])) >= 100:
            raise ValueError("invalid forbidden-construct rule override")
        re.compile(pattern)
        rules.setdefault(extension, []).append((rule_id, pattern, message))
    return rules, exclude


def _files(root: Path):
    for directory, names, files in os.walk(root):
        names[:] = [name for name in names if name not in EXCLUDED_PARTS]
        for name in files:
            path = Path(directory) / name
            if path.suffix.lower() in SUPPORTED and not path.is_symlink():
                yield path


def check(root: Path, options: ScanOptions) -> list[Violation]:
    root = root.resolve()
    rules, excludes = _config(options.config)
    additions = added_lines(root, options.git_mode, options.base, options.head) if options.mode == "new" else {}
    results = []
    for path in _files(root):
        relative = path.relative_to(root).as_posix()
        if any(Path(relative).match(pattern) for pattern in excludes):
            continue
        selected = additions.get(relative, set())
        if options.mode == "all" or selected:
            results.extend(
                Violation(relative, item.line, item.rule_id, item.message)
                for item in scan_text(
                    path.read_text(encoding="utf-8"),
                    path.suffix,
                    selected,
                    mode=options.mode,
                    rules=rules,
                )
            )
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Find forbidden constructs in added source lines.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=("new", "all"), default="new")
    parser.add_argument("--git-mode", choices=("worktree", "committed"), default="worktree")
    parser.add_argument("--base", default="HEAD~1")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    try:
        results = check(
            args.root,
            ScanOptions(args.mode, args.git_mode, args.base, args.head, args.config),
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"forbidden-constructs: {error}", file=sys.stderr)
        return 2
    for result in results:
        print(f"{result.path}:{result.line}  {result.rule_id}  {result.message}")
    return int(bool(results))


if __name__ == "__main__":
    raise SystemExit(main())
