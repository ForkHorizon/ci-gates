"""Compare lint-relevant parts of protected config files against a server-held baseline.

Mirrors CI-Scope-Web `protected-files-contract.ts`; both sides must produce identical fingerprints.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

try:
    from toml_scope import cargo_lint_path, python_tool_path, toml_scope
except ModuleNotFoundError:
    try:
        from .toml_scope import cargo_lint_path, python_tool_path, toml_scope
    except ImportError:  # loaded straight from its file, with neither the scripts folder nor a package around it
        import importlib.util
        import sys
        from pathlib import Path

        _spec = importlib.util.spec_from_file_location("toml_scope", Path(__file__).with_name("toml_scope.py"))
        _module = importlib.util.module_from_spec(_spec)
        sys.modules["toml_scope"] = _module
        _spec.loader.exec_module(_module)
        cargo_lint_path, python_tool_path, toml_scope = (
            _module.cargo_lint_path,
            _module.python_tool_path,
            _module.toml_scope,
        )


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


def _sorted_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _package_json_scope(content: str) -> str:
    try:
        parsed = json.loads(content)
    except ValueError:
        return content  # not parseable, so every byte counts
    scripts = parsed.get("scripts") if isinstance(parsed, dict) else None
    eslint = parsed.get("eslintConfig") if isinstance(parsed, dict) else None
    # Every script counts: a check may run any of them, and lifecycle scripts run on install.
    return _sorted_json({"scripts": scripts if isinstance(scripts, dict) else {}, "eslintConfig": eslint})


_LOCK_NAMES = frozenset(
    {"Cargo.lock", "uv.lock", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock"}
)
_URL_PATTERN = re.compile(r"(?:git\+)?(?:https?|ssh|git|file)://[^\s\"',)}\]]+|github:[^\s\"',)}\]]+")
_TARBALL = re.compile(r"\.(?:tgz|tar\.gz|zip)$")
_FRAGMENT = re.compile(r"#[0-9A-Za-z]{7,64}")


def is_lock_file(path: str) -> bool:
    return path.rsplit("/", 1)[-1] in _LOCK_NAMES


def _source_of(address: str) -> str:
    """The origin of a downloaded archive, or the whole address of anything else (a git repository, a path)."""
    bare = address.split("#", 1)[0]
    web = re.match(r"^(https?://[^/]+)/(.*)$", bare)
    return web.group(1) if web and _TARBALL.search(web.group(2)) else bare


def _line_sources(content: str, pattern: str) -> set[str]:
    found = set()
    for line in content.split("\n"):
        match = re.match(pattern, line)
        if match:
            found.add(_FRAGMENT.sub("", match.group(1)))
    return found


def lock_scope(path: str, content: str) -> str:
    """Where a lock file's packages come from, never which version. Mirrors CI-Scope-Web `lock-scope.ts`."""
    name = path.rsplit("/", 1)[-1]
    if name == "Cargo.lock":
        sources = _line_sources(content, r'^source = "(.*)"\s*$')
    elif name == "uv.lock":
        sources = _line_sources(content, r"^source = (\{.*\})\s*$")
    else:
        sources = {_source_of(address) for address in _URL_PATTERN.findall(content)}
    return "\n".join(sorted(sources))


def protected_scope(path: str, content: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if name == "Cargo.toml":
        return toml_scope(content, cargo_lint_path)
    if name == "pyproject.toml":
        return toml_scope(content, python_tool_path)
    if name == "package.json":
        return _package_json_scope(content)
    if is_lock_file(path):
        return lock_scope(path, content)
    return content


def fingerprint_file(path: str, content: str) -> str:
    return hashlib.sha256(protected_scope(path, content).encode("utf-8")).hexdigest()


def _matches_expected(path: str, content: str, expected: str) -> bool:
    """Lock files were once fingerprinted whole; a baseline taken then still matches until the owner replaces it."""
    if fingerprint_file(path, content) == expected:
        return True
    return is_lock_file(path) and hashlib.sha256(content.encode("utf-8")).hexdigest() == expected


def _violation_kind(path: str, content: str | None, expected: str | None, approved: set[str | None]) -> str | None:
    if content is None:
        return None if expected is None or None in approved else "deleted"
    if expected is not None and _matches_expected(path, content, expected):
        return None
    if fingerprint_file(path, content) in approved:
        return None
    return "added" if expected is None else "modified"


def check_protected_files(
    baseline: dict[str, str],
    observed: dict[str, str | None],
    patterns: Iterable[str],
    approved: dict[str, set[str | None]] | None = None,
) -> list[Violation]:
    """`baseline` maps path to fingerprint; `observed` maps path to file text (None = missing).

    `approved` maps a path to the fingerprints the owner approved for it (None = approved deletion).
    """
    patterns = list(patterns)
    approved = approved or {}
    seen: set[str] = set()
    violations: list[Violation] = []
    for path, content in observed.items():
        if path not in baseline and not any(matches_pattern(pattern, path) for pattern in patterns):
            continue
        seen.add(path)
        kind = _violation_kind(path, content, baseline.get(path), approved.get(path, set()))
        if kind:
            violations.append(Violation(path, kind))
    violations.extend(
        Violation(path, "deleted") for path in baseline if path not in seen and None not in approved.get(path, set())
    )
    return sorted(violations, key=lambda item: item.path)
