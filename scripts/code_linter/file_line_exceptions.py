from __future__ import annotations

from pathlib import Path

from .config_io import config_error


MAX_FILE_LINE_EXCEPTION = 5_000


def validate_file_line_exceptions(config: dict, path: Path) -> list[dict[str, object]]:
    exceptions = config.get("file_line_exceptions", [])
    if not isinstance(exceptions, list):
        config_error(path, "'file_line_exceptions' must be a JSON array of objects.")
    validated = []
    seen = set()
    for index, entry in enumerate(exceptions):
        validated.append(_validate_entry(entry, index, path, seen))
    return validated


def _validate_entry(entry: object, index: int, path: Path, seen: set[str]) -> dict:
    fields = {"path", "max_lines", "reason"}
    if not isinstance(entry, dict) or set(entry) != fields:
        config_error(path, f"File line exception {index} needs only path, max_lines, and reason.")
    relative = entry["path"]
    if not isinstance(relative, str) or not relative or relative != relative.strip():
        config_error(path, f"File line exception {index} needs a clean relative path.")
    candidate = Path(relative.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts or any(char in relative for char in "*?[]"):
        config_error(path, f"File line exception {index} must name one exact repository path.")
    normalized = candidate.as_posix()
    if not normalized or normalized == "." or normalized in seen:
        config_error(path, f"File line exception {index} has an empty or duplicate path.")
    maximum = entry["max_lines"]
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= MAX_FILE_LINE_EXCEPTION:
        config_error(
            path,
            f"File line exception {index} max_lines must be between 1 and {MAX_FILE_LINE_EXCEPTION}.",
        )
    reason = entry["reason"]
    if not isinstance(reason, str) or not reason.strip():
        config_error(path, f"File line exception {index} needs a non-empty reason.")
    seen.add(normalized)
    return {"path": normalized, "max_lines": maximum, "reason": reason.strip()}
