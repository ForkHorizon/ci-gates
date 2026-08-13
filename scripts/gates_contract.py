"""Validation for the workflow-facing CI Scope routing contract."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping


V1 = "v1"
V2 = "v2"
V2_TRUSTED_GROUP = "ci-scope-v2-trusted"
V2_LABEL = "ci-scope-v2"
V1_APPROVED_GROUPS = frozenset({"ci-scope", "ci-scope-broker"})
CANARY_ONLY = "canary-only"
MAX_GROUP_LENGTH = 100
MAX_LABEL_LENGTH = 100
MAX_LABELS = 32


class RoutingContractError(ValueError):
    """Raised when routing input cannot be safely accepted."""


def _error(field: str, message: str) -> RoutingContractError:
    return RoutingContractError(f"{field}: {message}")


def _text(field: str, value: object, limit: int) -> str:
    if not isinstance(value, str):
        raise _error(field, "must be a string")
    if not value or not value.strip():
        raise _error(field, "must not be empty")
    if value != value.strip():
        raise _error(field, "must not have leading or trailing whitespace")
    if len(value) > limit:
        raise _error(field, f"must be at most {limit} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise _error(field, "must not contain control characters")
    return value


def _normalise_aliases(values: dict[str, object]) -> dict[str, object]:
    aliases = {
        "routing-generation": "generation",
        "runner-group": "group",
        "runner-labels": "labels",
        "workflow_contract_version": "workflow-contract-version",
        "trust_fixture_mode": "trust-fixture-mode",
    }
    for alias, canonical in aliases.items():
        if alias not in values:
            continue
        if canonical in values:
            raise _error("routing", f"mixed {alias} and {canonical} inputs")
        values[canonical] = values.pop(alias)
    return values


ALLOWED_FIELDS = frozenset({"generation", "group", "labels", "workflow-contract-version", "trust-fixture-mode"})


def _validate_context(routing: Mapping[str, object], environment: str, trusted_input: bool) -> None:
    if not isinstance(routing, Mapping):
        raise _error("routing", "must be an object")
    if environment not in {"production", "canary"}:
        raise _error("environment", "must be production or canary")
    if not isinstance(trusted_input, bool):
        raise _error("trusted_input", "must be boolean")


def _canonical_values(routing: Mapping[str, object]) -> dict[str, object]:
    values = dict(routing)
    if any(not isinstance(field, str) for field in values):
        raise _error("routing", "field names must be strings")
    values = _normalise_aliases(values)
    unknown = sorted(set(values) - ALLOWED_FIELDS)
    if unknown:
        raise _error("routing", f"unknown field(s): {', '.join(unknown)}")
    for field in ("generation", "group", "labels"):
        if field not in values:
            raise _error(field, "is required")
    return values


def _validate_generation(values: Mapping[str, object]) -> str:
    generation = values["generation"]
    if not isinstance(generation, str):
        raise _error("generation", "must be a string")
    if generation not in {V1, V2}:
        raise _error("generation", "must be v1 or v2; unknown generations are rejected")
    return generation


def _validate_labels(value: object) -> list[str]:
    if not isinstance(value, list):
        raise _error("labels", "must be an array")
    if not value:
        raise _error("labels", "must not be empty")
    if len(value) > MAX_LABELS:
        raise _error("labels", f"must contain at most {MAX_LABELS} entries")
    labels = [_text(f"labels[{index}]", label, MAX_LABEL_LENGTH) for index, label in enumerate(value)]
    if len({label.casefold() for label in labels}) != len(labels):
        raise _error("labels", "must not contain duplicates")
    return labels


def _validate_identity(values: Mapping[str, object], generation: str) -> tuple[str, list[str]]:
    group = _text("group", values["group"], MAX_GROUP_LENGTH)
    labels = _validate_labels(values["labels"])
    if generation == V2 and group != V2_TRUSTED_GROUP:
        raise _error("group", f"v2 requires {V2_TRUSTED_GROUP!r}")
    if generation == V2 and V2_LABEL not in labels:
        raise _error("labels", f"v2 requires the {V2_LABEL!r} label")
    if generation == V1 and (group == V2_TRUSTED_GROUP or V2_LABEL in labels):
        raise _error("routing", "v1 and v2 routing inputs must not be mixed")
    return group, labels


def _validate_trust(group: str, environment: str, trusted_input: bool) -> None:
    approved = (*V1_APPROVED_GROUPS, V2_TRUSTED_GROUP)
    if environment == "production" and not trusted_input and group not in approved:
        raise _error("group", "production rejects arbitrary groups from untrusted input")


def _add_optional_fields(
    result: dict[str, object], values: Mapping[str, object], generation: str, environment: str
) -> None:
    if "workflow-contract-version" in values:
        version = _text("workflow-contract-version", values["workflow-contract-version"], 16)
        normalised = version if version in {V1, V2} else f"v{version}" if version in {"1", "2"} else None
        if normalised is None:
            raise _error("workflow-contract-version", "must be v1, v2, 1, or 2")
        if normalised != generation:
            raise _error("workflow-contract-version", "must match generation")
        result["workflow-contract-version"] = normalised
    if "trust-fixture-mode" in values:
        _validate_fixture_mode(values["trust-fixture-mode"], generation, environment)
        result["trust-fixture-mode"] = CANARY_ONLY


def _validate_fixture_mode(value: object, generation: str, environment: str) -> None:
    if value != CANARY_ONLY:
        raise _error("trust-fixture-mode", "only canary-only is supported")
    if environment != "canary":
        raise _error("trust-fixture-mode", "canary-only is forbidden in production")
    if generation != V2:
        raise _error("trust-fixture-mode", "canary-only requires v2 routing")


def validate_routing(
    routing: Mapping[str, object],
    *,
    environment: str = "production",
    trusted_input: bool = False,
) -> dict[str, object]:
    """Validate and return a detached, canonical routing object.

    ``trusted_input`` is intentionally explicit: production may only receive the
    v1 default group or the v2 dedicated group from an untrusted workflow input.
    """

    _validate_context(routing, environment, trusted_input)
    values = _canonical_values(routing)
    generation = _validate_generation(values)
    group, labels = _validate_identity(values, generation)
    _validate_trust(group, environment, trusted_input)
    result: dict[str, object] = {"generation": generation, "group": group, "labels": labels}
    _add_optional_fields(result, values, generation, environment)
    return result


validate_routing_object = validate_routing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a CI Scope routing contract JSON object.")
    parser.add_argument("input", nargs="?", default="-", help="JSON file, or - for stdin")
    parser.add_argument("--environment", choices=("production", "canary"), default="production")
    parser.add_argument("--trusted-input", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.input == "-":
            routing = json.load(sys.stdin)
        else:
            with open(args.input, encoding="utf-8") as source:
                routing = json.load(source)
        validated = validate_routing(routing, environment=args.environment, trusted_input=args.trusted_input)
    except (OSError, json.JSONDecodeError, RoutingContractError) as error:
        print(f"routing contract error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(validated, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
