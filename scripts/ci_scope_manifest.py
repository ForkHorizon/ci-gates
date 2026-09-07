"""Fail-closed manifest contract for the unified CI Scope runner.

The manifest selects named checks from :data:`CHECK_CATALOG`; it never carries
shell commands.  Keep this module dependency free because it is loaded before
any project code is executed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
from typing import Any

try:
    from ci_scope_models import CheckSpec, ResolvedManifest
except ModuleNotFoundError:  # Imported as scripts.ci_scope_manifest by tests and tools.
    from .ci_scope_models import CheckSpec, ResolvedManifest


MANIFEST_VERSION = 1
EVENTS = frozenset({"pull_request", "push", "merge_group", "workflow_dispatch", "schedule"})
CHECK_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")


class ManifestError(ValueError):
    """Raised when a project manifest cannot be trusted or resolved."""


@dataclass(frozen=True)
class CheckDefinition:
    """Trusted metadata for one executable adapter."""

    type: str
    required: bool
    default_config: str | None = None
    allowed_params: frozenset[str] = frozenset()
    resources: frozenset[str] = frozenset()
    ai: bool = False


# Commands and their argument handling live in the executor's adapters.  This
# table is intentionally the only source of executable check types.
CHECK_CATALOG: dict[str, CheckDefinition] = {
    "code-linter": CheckDefinition(
        "code-linter", True, ".code-linter.json", frozenset({"mode", "coverage_mode", "explain_model"})
    ),
    "python-quality": CheckDefinition("python-quality", True, None, frozenset({"explain_model"})),
    "go-quality": CheckDefinition("go-quality", True, None, frozenset({"explain_model"})),
    "swift-quality": CheckDefinition(
        "swift-quality",
        True,
        ".swift-quality-gate.json",
        frozenset({"run_build", "explain_model"}),
        frozenset({"xcode"}),
    ),
    "swift-compile": CheckDefinition(
        "swift-compile", True, ".swift-compile-gate.json", frozenset({"explain_model"}), frozenset({"xcode"})
    ),
    "slop-review": CheckDefinition(
        "slop-review", False, ".slop-review.json", frozenset({"model"}), frozenset({"ollama"}), True
    ),
}

_MANIFEST_FIELDS = frozenset({"version", "checks"})
_CHECK_FIELDS = frozenset(
    {"id", "type", "config", "workdir", "params", "depends_on", "events", "resources", "required"}
)


def _error(path: str, message: str) -> ManifestError:
    return ManifestError(f"{path}: {message}")


def _text(value: object, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise _error(path, "must be a string")
    if not allow_empty and not value:
        raise _error(path, "must not be empty")
    if value != value.strip():
        raise _error(path, "must not have leading or trailing whitespace")
    if "\x00" in value:
        raise _error(path, "must not contain NUL")
    return value


def _relative_path(value: object, path: str) -> str:
    value = _text(value, path)
    candidate = Path(value)
    if candidate.is_absolute() or value in {".", ".."} or ".." in candidate.parts:
        raise _error(path, "must be a relative path inside the project")
    return candidate.as_posix()


def _list_of_strings(value: object, path: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _error(path, "must be an array")
    if nonempty and not value:
        raise _error(path, "must not be empty")
    result = tuple(_text(item, f"{path}[{index}]") for index, item in enumerate(value))
    if len(set(result)) != len(result):
        raise _error(path, "must not contain duplicates")
    return result


def _check_path(root: Path, relative: str, path: str, *, directory: bool) -> None:
    root = root.resolve()
    target = (root / relative).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as error:
        raise _error(path, "resolves outside the project root") from error
    if target.exists() and target.is_dir() != directory:
        kind = "directory" if directory else "file"
        raise _error(path, f"must point to a {kind}")


def _validate_params(value: object, definition: CheckDefinition, path: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _error(path, "must be an object")
    if any(not isinstance(key, str) for key in value):
        raise _error(path, "parameter names must be strings")
    unknown = sorted(set(value) - definition.allowed_params)
    if unknown:
        raise _error(path, f"unknown parameter(s): {', '.join(unknown)}")
    return dict(value)


def _validate_manifest_shape(manifest: object) -> tuple[int, list[Mapping[str, Any]]]:
    if not isinstance(manifest, dict):
        raise _error("manifest", "must be an object")
    unknown = sorted(set(manifest) - _MANIFEST_FIELDS, key=str)
    if unknown:
        raise _error("manifest", f"unknown field(s): {', '.join(unknown)}")
    version = manifest.get("version")
    if isinstance(version, bool) or version != MANIFEST_VERSION:
        raise _error("version", f"must be {MANIFEST_VERSION}")
    checks = manifest.get("checks")
    if not isinstance(checks, list) or not checks:
        raise _error("checks", "must be a non-empty array")
    result: list[Mapping[str, Any]] = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise _error(f"checks[{index}]", "must be an object")
        unknown = sorted(set(check) - _CHECK_FIELDS, key=str)
        if unknown:
            raise _error(f"checks[{index}]", f"unknown field(s): {', '.join(unknown)}")
        result.append(check)
    return version, result


def _resolve_check(entry: Mapping[str, Any], index: int, root: Path, seen: set[str]) -> CheckSpec:
    prefix = f"checks[{index}]"
    check_id = _text(entry.get("id"), f"{prefix}.id")
    if CHECK_ID.fullmatch(check_id) is None:
        raise _error(f"{prefix}.id", "must match lowercase kebab-case identifier rules")
    if check_id in seen:
        raise _error(f"{prefix}.id", "duplicates an earlier check")
    seen.add(check_id)
    check_type = _text(entry.get("type"), f"{prefix}.type")
    definition = CHECK_CATALOG.get(check_type)
    if definition is None:
        raise _error(f"{prefix}.type", f"unknown check type {check_type!r}")
    required = entry.get("required", definition.required)
    if not isinstance(required, bool):
        raise _error(f"{prefix}.required", "must be a boolean")
    if required != definition.required:
        raise _error(f"{prefix}.required", f"is fixed by the trusted catalog to {definition.required}")
    config_value = entry.get("config", definition.default_config)
    config = None if config_value is None else _relative_path(config_value, f"{prefix}.config")
    if config is not None:
        _check_path(root, config, f"{prefix}.config", directory=False)
        if "config" in entry and not (root / config).resolve().is_file():
            raise _error(f"{prefix}.config", "must point to an existing file")
    workdir = _relative_path(entry["workdir"], f"{prefix}.workdir") if "workdir" in entry else "."
    _check_path(root, workdir, f"{prefix}.workdir", directory=True)
    depends_on = _list_of_strings(entry.get("depends_on", []), f"{prefix}.depends_on")
    events = _list_of_strings(entry.get("events", []), f"{prefix}.events")
    unknown_events = sorted(set(events) - EVENTS)
    if unknown_events:
        raise _error(f"{prefix}.events", f"unknown event(s): {', '.join(unknown_events)}")
    resources = _list_of_strings(entry.get("resources", sorted(definition.resources)), f"{prefix}.resources")
    invalid = sorted(set(resources) - definition.resources)
    if invalid:
        raise _error(f"{prefix}.resources", f"not trusted for {check_type}: {', '.join(invalid)}")
    params = _validate_params(entry.get("params"), definition, f"{prefix}.params")
    return CheckSpec(
        check_id, check_type, config, workdir, params, depends_on, events, resources, required, definition.ai
    )


def resolve_manifest(
    manifest: Mapping[str, Any], *, root: Path, event: str | None = None, source: Path | None = None
) -> ResolvedManifest:
    """Validate and resolve a decoded manifest against ``root``.

    ``event`` only selects active checks; all checks are validated so an
    invalid inactive entry cannot hide in a green run.
    """

    version, entries = _validate_manifest_shape(manifest)
    root = Path(root).resolve()
    if not root.is_dir():
        raise _error("root", "must be an existing directory")
    if event is not None and event not in EVENTS:
        raise _error("event", f"must be one of: {', '.join(sorted(EVENTS))}")

    seen: set[str] = set()
    specs = [_resolve_check(entry, index, root, seen) for index, entry in enumerate(entries)]

    ids = {spec.id for spec in specs}
    for spec in specs:
        unknown = sorted(set(spec.depends_on) - ids)
        if unknown:
            raise _error(f"checks[{spec.id}].depends_on", f"unknown check(s): {', '.join(unknown)}")
    _ensure_acyclic(specs)
    return ResolvedManifest(version, tuple(specs), root, source or Path("<memory>"), event)


def _ensure_acyclic(specs: list[CheckSpec]) -> None:
    dependencies = {spec.id: set(spec.depends_on) for spec in specs}
    visited: set[str] = set()
    active: set[str] = set()

    def visit(check_id: str) -> None:
        if check_id in active:
            raise _error("checks", f"dependency cycle includes {check_id!r}")
        if check_id in visited:
            return
        active.add(check_id)
        for dependency in dependencies[check_id]:
            visit(dependency)
        active.remove(check_id)
        visited.add(check_id)

    for check_id in dependencies:
        visit(check_id)


def load_manifest(path: Path) -> dict[str, Any]:
    """Load a JSON manifest and reject malformed JSON with a stable error."""

    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise _error("manifest", f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise _error("manifest", f"invalid JSON at line {error.lineno}, column {error.colno}") from error
    if not isinstance(value, dict):
        raise _error("manifest", "must contain a JSON object")
    return value


def resolve_manifest_file(path: Path, *, root: Path, event: str | None = None) -> ResolvedManifest:
    path = Path(path)
    return resolve_manifest(load_manifest(path), root=root, event=event, source=path.resolve())


def validate_only(path: Path, *, root: Path, event: str | None = None) -> ResolvedManifest:
    """Public validation entry point for the future ``run-checks`` CLI."""

    return resolve_manifest_file(path, root=root, event=event)


def canonical_manifest(manifest: ResolvedManifest) -> dict[str, Any]:
    """Return JSON-safe resolved data for diagnostics and GitHub summaries."""

    return {
        "version": manifest.version,
        "checks": [
            {
                "id": check.id,
                "type": check.type,
                "config": check.config,
                "workdir": check.workdir,
                "params": dict(check.params),
                "depends_on": list(check.depends_on),
                "events": list(check.events),
                "resources": list(check.resources),
                "required": check.required,
                "ai": check.ai,
            }
            for check in manifest.checks
        ],
    }
