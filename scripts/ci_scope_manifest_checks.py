from pathlib import Path
from collections.abc import Mapping

try:
    from ci_scope_check_catalog import CHECK_CATALOG
    from ci_scope_models import CheckSpec

    try:
        from scripts.ci_scope_manifest import (
            CHECK_ID,
            EVENTS,
            _check_path,
            _error,
            _list_of_strings,
            _relative_path,
            _text,
            _validate_params,
        )
    except ModuleNotFoundError:
        from ci_scope_manifest import (
            CHECK_ID,
            EVENTS,
            _check_path,
            _error,
            _list_of_strings,
            _relative_path,
            _text,
            _validate_params,
        )
except ModuleNotFoundError:
    from .ci_scope_check_catalog import CHECK_CATALOG
    from .ci_scope_models import CheckSpec
    from .ci_scope_manifest import (
        CHECK_ID,
        EVENTS,
        _check_path,
        _error,
        _list_of_strings,
        _relative_path,
        _text,
        _validate_params,
    )


def resolve_check(entry: Mapping, index: int, root: Path, seen: set[str]) -> CheckSpec:
    prefix = f"checks[{index}]"
    check_id = _text(entry.get("id"), f"{prefix}.id")
    if CHECK_ID.fullmatch(check_id) is None:
        raise _error(f"{prefix}.id", "must match lowercase kebab-case identifier rules")
    if check_id in seen:
        raise _error(f"{prefix}.id", "duplicates an earlier check")
    seen.add(check_id)
    check_type, definition = _definition(entry, prefix)
    required = _required(entry, prefix, definition.required)
    config, workdir = _paths(entry, prefix, root, definition.default_config)
    depends_on, events, resources = _constraints(entry, prefix, check_type, definition.resources)
    params = _validate_params(entry.get("params"), definition, f"{prefix}.params")
    speed = entry.get("speed", "fast")
    if not isinstance(speed, str) or speed not in {"fast", "full"}:
        raise _error(f"{prefix}.speed", 'must be "fast" or "full"')
    return CheckSpec(
        check_id,
        check_type,
        config,
        workdir,
        params,
        depends_on,
        events,
        resources,
        required,
        definition.ai,
        speed,
    )


def _definition(entry: Mapping, prefix: str):
    check_type = _text(entry.get("type"), f"{prefix}.type")
    definition = CHECK_CATALOG.get(check_type)
    if definition is None:
        raise _error(f"{prefix}.type", f"unknown check type {check_type!r}")
    return check_type, definition


def _required(entry: Mapping, prefix: str, expected: bool) -> bool:
    required = entry.get("required", expected)
    if not isinstance(required, bool):
        raise _error(f"{prefix}.required", "must be a boolean")
    if required != expected:
        raise _error(f"{prefix}.required", f"is fixed by the trusted catalog to {expected}")
    return required


def _paths(entry: Mapping, prefix: str, root: Path, default_config: str | None):
    config_value = entry.get("config", default_config)
    config = None if config_value is None else _relative_path(config_value, f"{prefix}.config")
    if config is not None:
        _check_path(root, config, f"{prefix}.config", directory=False)
        if "config" in entry and not (root / config).resolve().is_file():
            raise _error(f"{prefix}.config", "must point to an existing file")
    workdir = _relative_path(entry["workdir"], f"{prefix}.workdir") if "workdir" in entry else "."
    _check_path(root, workdir, f"{prefix}.workdir", directory=True)
    return config, workdir


def _constraints(entry: Mapping, prefix: str, check_type: str, allowed_resources: frozenset[str]):
    depends_on = _list_of_strings(entry.get("depends_on", []), f"{prefix}.depends_on")
    events = _list_of_strings(entry.get("events", []), f"{prefix}.events")
    unknown_events = sorted(set(events) - EVENTS)
    if unknown_events:
        raise _error(f"{prefix}.events", f"unknown event(s): {', '.join(unknown_events)}")
    resources = _list_of_strings(entry.get("resources", sorted(allowed_resources)), f"{prefix}.resources")
    invalid = sorted(set(resources) - allowed_resources)
    if invalid:
        raise _error(f"{prefix}.resources", f"not trusted for {check_type}: {', '.join(invalid)}")
    return depends_on, events, resources
