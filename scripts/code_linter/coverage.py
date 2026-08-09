from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


UNSUPPORTED_SURFACE_BY_EXTENSION = {
    ".zsh": "shell",
    ".fish": "shell",
    ".ps1": "PowerShell",
    ".bat": "Windows shell",
    ".cmd": "Windows shell",
    ".sql": "SQL",
    ".lua": "Lua",
    ".r": "R",
    ".pl": "Perl",
    ".pm": "Perl",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".erl": "Erlang",
    ".hrl": "Erlang header",
    ".fs": "F#",
    ".fsx": "F#",
    ".vb": "Visual Basic",
    ".jl": "Julia",
    ".hs": "Haskell",
    ".lhs": "Haskell",
    ".clj": "Clojure",
    ".cljs": "ClojureScript",
    ".sol": "Solidity",
    ".proto": "Protocol Buffers",
    ".graphql": "GraphQL",
    ".gql": "GraphQL",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".less": "Less",
    ".xml": "XML/config",
    ".jsonc": "JSONC/config",
    ".ini": "INI/config",
    ".cfg": "config",
    ".conf": "config",
    ".mk": "Make config",
}

NON_SOURCE_TEXT_EXTENSIONS = {
    ".adoc",
    ".csv",
    ".diff",
    ".lock",
    ".markdown",
    ".md",
    ".mdx",
    ".org",
    ".patch",
    ".po",
    ".pot",
    ".rst",
    ".tsv",
    ".txt",
}
NON_SOURCE_TEXT_FILENAMES = {
    "authors",
    "changelog",
    "changes",
    "contributors",
    "copying",
    "license",
    "notice",
    "readme",
    ".gitkeep",
    ".keep",
}

UNSUPPORTED_SURFACE_BY_FILENAME = {
    "dockerfile": "Docker build",
    "makefile": "Make build",
    "rakefile": "Ruby build",
    "gemfile": "Ruby dependency",
    "podfile": "CocoaPods dependency",
    "procfile": "process configuration",
}

COVERAGE_MODES = ("report", "strict")
DEFAULT_COVERAGE_EXCEPTIONS = []


@dataclass(frozen=True)
class CoverageGap:
    path: str
    category: str
    extension: str
    message: str
    ignored_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class PathInventory:
    selected: tuple[Path, ...]
    gaps: tuple[CoverageGap, ...]


def unknown_text_surface(path: Path) -> tuple[str, str] | None:
    """Return an auditable gap for text files outside known surface lists."""
    if path.suffix.lower() in NON_SOURCE_TEXT_EXTENSIONS or path.name.lower() in NON_SOURCE_TEXT_FILENAMES:
        return None
    try:
        sample = path.read_bytes()[:8192]
    except OSError:
        return None
    if b"\x00" in sample:
        return None
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return None
    label = path.suffix.lower() or "extensionless"
    return "unknown text/config", label
