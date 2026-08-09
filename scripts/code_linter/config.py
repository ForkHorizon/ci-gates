from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from . import config_io as _config_io
from .config_io import config_error, read_config_text
from .coverage import COVERAGE_MODES, DEFAULT_COVERAGE_EXCEPTIONS

config_read_error = _config_io.config_read_error
github_path = _config_io.github_path

LANGUAGE_BY_EXTENSION = {
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".hh": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".m": "objective_c",
    ".mm": "objective_c",
    ".dart": "dart",
    ".scala": "scala",
    ".sc": "scala",
    ".groovy": "groovy",
    ".gradle": "groovy",
    ".sh": "shell",
    ".bash": "shell",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".swift": "swift",
    ".cs": "csharp",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".py": "python",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".rb": "ruby",
}
LANGUAGE_BY_FILENAME = {".gitignore": "gitignore"}
SYNTAX_ONLY_LANGUAGES = {"gitignore", "yaml"}

DEFAULT_IGNORE = [
    ".ci-gates",
    ".git",
    ".svn",
    ".hg",
    ".build",
    ".dart_tool",
    ".gradle",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".tox",
    ".venv",
    "DerivedData",
    "Pods",
    "bin",
    "build",
    "dist",
    "node_modules",
    "obj",
    "out",
    "target",
    "vendor",
]

LIMIT_DEFAULTS = {
    "max_file_lines": 300,
    "max_function_lines": 50,
    "max_nesting_depth": 4,
    "max_parameters": 5,
    "max_comment_lines": 5,
    "max_doc_comment_lines": 50,
    "max_types_per_file": 2,
}
LIMIT_MAXIMUMS = {
    "max_file_lines": 2_000,
    "max_function_lines": 500,
    "max_nesting_depth": 20,
    "max_parameters": 50,
    "max_comment_lines": 200,
    "max_doc_comment_lines": 500,
    "max_types_per_file": 50,
}

MAX_FILE_BYTES = 1_000_000


class DuplicateJSONKeyError(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise DuplicateJSONKeyError(key)
        values[key] = value
    return values


DEFAULT_CONFIG = {
    **LIMIT_DEFAULTS,
    "include_extensions": sorted(LANGUAGE_BY_EXTENSION),
    "ignore": DEFAULT_IGNORE,
    "language_overrides": {},
    "coverage_mode": "report",
    "coverage_exceptions": DEFAULT_COVERAGE_EXCEPTIONS,
}


def initial_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    config["ignore"] = list(DEFAULT_IGNORE)
    config["include_extensions"] = list(DEFAULT_CONFIG["include_extensions"])
    config["language_overrides"] = {}
    config["coverage_exceptions"] = [dict(item) for item in DEFAULT_COVERAGE_EXCEPTIONS]
    return config


def language_for_path(path: Path) -> str | None:
    return LANGUAGE_BY_FILENAME.get(path.name.lower()) or LANGUAGE_BY_EXTENSION.get(path.suffix.lower())


def read_config(path: Path) -> dict:
    try:
        loaded = json.loads(read_config_text(path, config_error), object_pairs_hook=reject_duplicate_json_keys)
    except DuplicateJSONKeyError as exc:
        config_error(path, f"Duplicate JSON key {exc.key!r}.")
    except json.JSONDecodeError as exc:
        config_error(path, f"Invalid JSON config: {exc}")
    if not isinstance(loaded, dict):
        config_error(path, "Code Linter config must be a JSON object")
    unknown = sorted(set(loaded) - set(DEFAULT_CONFIG))
    if unknown:
        config_error(path, f"Unknown config key(s): {', '.join(unknown)}.")
    return loaded


def validate_extensions(config: dict, path: Path) -> list[str]:
    extensions = [
        (ext if ext.startswith(".") else f".{ext}").lower()
        for ext in config_list(config, "include_extensions", LANGUAGE_BY_EXTENSION, path)
    ]
    unsupported = sorted(set(extensions) - set(LANGUAGE_BY_EXTENSION))
    if unsupported:
        config_error(path, f"Unsupported source extension(s): {', '.join(unsupported)}.")
    if not extensions:
        config_error(path, "'include_extensions' must not be empty.")
    return extensions


def validate_overrides(config: dict, path: Path) -> dict:
    overrides = config.get("language_overrides", {})
    if not isinstance(overrides, dict):
        config_error(path, "'language_overrides' must be a JSON object.")
    valid_languages = set(LANGUAGE_BY_EXTENSION.values())
    validated_overrides = {}
    for language, values in overrides.items():
        if language not in valid_languages:
            config_error(path, f"Unknown language override: {language!r}.")
        if not isinstance(values, dict):
            config_error(path, f"Override for {language!r} must be a JSON object.")
        unknown = sorted(set(values) - set(LIMIT_DEFAULTS))
        if unknown:
            config_error(
                path,
                f"Unknown {language!r} override key(s): {', '.join(unknown)}.",
            )
        validated_overrides[language] = {key: config_int(values, key, LIMIT_DEFAULTS[key], path) for key in values}
    return validated_overrides


def load_config(path: Path) -> dict:
    config = initial_config()
    loaded = read_config(path) if path.exists() else {}
    config.update(loaded)
    if "ignore" in loaded:
        config["ignore"] = merge_ignore(loaded["ignore"], path)
        reject_blanket_ignores(config["ignore"], path)
    for key, fallback in LIMIT_DEFAULTS.items():
        config[key] = config_int(config, key, fallback, path)
    config["include_extensions"] = validate_extensions(config, path)
    config["language_overrides"] = validate_overrides(config, path)
    config["coverage_mode"] = validate_coverage_mode(config, path)
    config["coverage_exceptions"] = validate_coverage_exceptions(config, path)
    return config


def merge_ignore(loaded_ignore: object, path: Path) -> list[str]:
    if not isinstance(loaded_ignore, list) or not all(isinstance(item, str) for item in loaded_ignore):
        config_error(path, "'ignore' must be a JSON array of strings.")
    merged = list(DEFAULT_IGNORE)
    for item in loaded_ignore:  # type: ignore[union-attr]
        if item not in merged:
            merged.append(item)
    return merged


def reject_blanket_ignores(patterns: Sequence[str], path: Path) -> None:
    forbidden = {"*", "**", "**/*"}
    for extension in LANGUAGE_BY_EXTENSION:
        forbidden.update({f"*{extension}", f"**{extension}", f"**/*{extension}"})
    invalid = []
    for pattern in patterns:
        normalized = pattern.strip().replace("\\", "/").removeprefix("./").removeprefix("/")
        if normalized in forbidden:
            invalid.append(pattern)
    if invalid:
        config_error(
            path,
            f"Blanket source ignore pattern(s) are not allowed: {', '.join(invalid)}.",
        )


def validate_coverage_mode(config: dict, path: Path) -> str:
    mode = config.get("coverage_mode", "report")
    if mode not in COVERAGE_MODES:
        config_error(
            path,
            f"'coverage_mode' must be one of {', '.join(COVERAGE_MODES)}, got {mode!r}.",
        )
    return mode


def validate_coverage_exceptions(config: dict, path: Path) -> list[dict[str, str]]:
    exceptions = config.get("coverage_exceptions", [])
    if not isinstance(exceptions, list):
        config_error(path, "'coverage_exceptions' must be a JSON array of objects.")
    exceptions = [*DEFAULT_COVERAGE_EXCEPTIONS, *exceptions]

    validated: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, exception in enumerate(exceptions):
        if not isinstance(exception, dict):
            config_error(path, f"Coverage exception {index} must be a JSON object.")
        unknown = sorted(set(exception) - {"pattern", "reason"})
        if unknown:
            config_error(
                path,
                f"Coverage exception {index} has unknown key(s): {', '.join(unknown)}.",
            )
        pattern = exception.get("pattern")
        reason = exception.get("reason")
        if not isinstance(pattern, str) or not pattern.strip():
            config_error(path, f"Coverage exception {index} needs a non-empty 'pattern'.")
        if not isinstance(reason, str) or not reason.strip():
            config_error(path, f"Coverage exception {index} needs a non-empty 'reason'.")
        reject_blanket_ignores([pattern], path)
        key = (pattern, reason)
        if key not in seen:
            validated.append({"pattern": pattern, "reason": reason})
            seen.add(key)
    return validated


def config_list(config: dict, key: str, fallback: Iterable[str], path: Path) -> list[str]:
    value = config.get(key, fallback)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        config_error(path, f"'{key}' must be a JSON array of strings.")
    return list(value)  # type: ignore[arg-type]


def config_int(config: dict, key: str, fallback: int, path: Path) -> int:
    value = config.get(key, fallback)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        config_error(path, f"'{key}' must be a positive integer, got {value!r}.")
    if value > LIMIT_MAXIMUMS[key]:
        config_error(path, f"'{key}' must not exceed {LIMIT_MAXIMUMS[key]}, got {value}.")
    return value
