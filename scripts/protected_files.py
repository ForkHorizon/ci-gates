"""Compare lint-relevant parts of protected config files against a server-held baseline.

Mirrors CI-Scope-Web `protected-files-contract.ts`; both sides must produce identical fingerprints.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

LINT_SECTION = re.compile(r"^\s*\[\[?\s*(?:workspace\.)?lints(?:[.\s\]]|$)")
PYTHON_TOOL_SECTION = re.compile(r"^\s*\[\s*tool\.(?:ruff|pytest|mypy|pyright)(?:[.\s\]]|$)")
SECTION_HEADER = re.compile(r"^\s*\[")
SCRIPT_NAME = re.compile(r"^(?:pre|post)?(?:test|lint|typecheck|check|build)(?::.*)?$")


@dataclass(frozen=True)
class Violation:
    path: str
    kind: str  # "modified" | "deleted" | "added"


def matches_pattern(pattern: str, path: str) -> bool:
    source = ""
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*" and pattern[index + 1 : index + 2] == "*":
            if pattern[index + 2 : index + 3] == "/":
                source += "(?:.*/)?"
                index += 2
            else:
                source += ".*"
                index += 1
        elif char == "*":
            source += "[^/]*"
        elif char == "?":
            source += "[^/]"
        else:
            source += re.escape(char)
        index += 1
    return re.fullmatch(source, path) is not None


def select_protected_paths(paths: Iterable[str], patterns: Iterable[str]) -> list[str]:
    patterns = list(patterns)
    return sorted(path for path in paths if any(matches_pattern(pattern, path) for pattern in patterns))


def _toml_sections(content: str, header: re.Pattern[str]) -> str:
    kept: list[str] = []
    inside = False
    for line in re.split(r"\r?\n", content):
        if SECTION_HEADER.match(line):
            inside = header.match(line) is not None
        stripped = line.strip()
        if inside and stripped and not stripped.startswith("#"):
            kept.append(stripped)
    return "\n".join(kept)


def _sorted_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _package_json_scope(content: str) -> str:
    try:
        parsed = json.loads(content)
    except ValueError:
        return content  # not parseable: any change at all counts
    scripts = parsed.get("scripts") if isinstance(parsed, dict) else None
    scripts = scripts if isinstance(scripts, dict) else {}
    kept = {name: value for name, value in scripts.items() if SCRIPT_NAME.match(name)}
    eslint = parsed.get("eslintConfig") if isinstance(parsed, dict) else None
    return _sorted_json({"scripts": kept, "eslintConfig": eslint})


def protected_scope(path: str, content: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if name == "Cargo.toml":
        return _toml_sections(content, LINT_SECTION)
    if name == "pyproject.toml":
        return _toml_sections(content, PYTHON_TOOL_SECTION)
    if name == "package.json":
        return _package_json_scope(content)
    return content


def fingerprint_file(path: str, content: str) -> str:
    return hashlib.sha256(protected_scope(path, content).encode("utf-8")).hexdigest()


def check_protected_files(
    baseline: dict[str, str],
    observed: dict[str, str | None],
    patterns: Iterable[str],
) -> list[Violation]:
    """`baseline` maps path to fingerprint; `observed` maps path to file text (None = missing)."""
    patterns = list(patterns)
    seen: set[str] = set()
    violations: list[Violation] = []
    for path, content in observed.items():
        if path not in baseline and not any(matches_pattern(pattern, path) for pattern in patterns):
            continue
        seen.add(path)
        expected = baseline.get(path)
        if content is None:
            if expected is not None:
                violations.append(Violation(path, "deleted"))
        elif expected is None:
            violations.append(Violation(path, "added"))
        elif fingerprint_file(path, content) != expected:
            violations.append(Violation(path, "modified"))
    violations.extend(Violation(path, "deleted") for path in baseline if path not in seen)
    return sorted(violations, key=lambda item: item.path)
