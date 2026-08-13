"""Validation for the ci-gates release manifest contract."""

from datetime import datetime
import re
from collections.abc import Mapping

from scripts.gates_contract import RoutingContractError, validate_routing


SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
MAX_VERSION = 1_000_000

REQUIRED_FIELDS = frozenset(
    {
        "ci_gates_sha",
        "workflow_sha",
        "routing_generation",
        "group",
        "labels",
        "progress_marker_version",
        "release_manifest_version",
        "activation_timestamp",
        "rollback_target",
    }
)


def _is_sha(value):
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def _check_sha(errors, field, value):
    if not _is_sha(value):
        errors.append(f"{field} must be a full lowercase 40-character commit SHA")


def _check_version(errors, field, value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_VERSION:
        errors.append(f"{field} must be a positive integer <= {MAX_VERSION}")


def _check_timestamp(errors, value):
    if not isinstance(value, str) or not value.strip():
        errors.append("activation_timestamp must be an ISO 8601 timestamp with timezone")
        return
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append("activation_timestamp must be an ISO 8601 timestamp with timezone")


def _check_routing(errors, generation, group, labels):
    try:
        validate_routing(
            {"generation": generation, "group": group, "labels": labels},
            trusted_input=True,
        )
    except RoutingContractError as error:
        errors.append(f"routing contract: {error}")


def validate_manifest(manifest, *, expected_ci_gates_sha=None) -> list[str]:
    """Return contract violations; an empty list means the manifest is valid."""

    if not isinstance(manifest, Mapping):
        return ["manifest must be a mapping"]

    errors = []
    unknown = sorted(set(manifest) - REQUIRED_FIELDS, key=str)
    missing = sorted(REQUIRED_FIELDS - set(manifest), key=str)
    errors.extend(f"unknown field: {field}" for field in unknown)
    errors.extend(f"missing field: {field}" for field in missing)

    for field in ("ci_gates_sha", "workflow_sha", "rollback_target"):
        if field in manifest:
            _check_sha(errors, field, manifest[field])
    if expected_ci_gates_sha is not None:
        if not _is_sha(expected_ci_gates_sha):
            errors.append("expected_ci_gates_sha must be a full lowercase 40-character commit SHA")
        elif manifest.get("ci_gates_sha") != expected_ci_gates_sha:
            errors.append("ci_gates_sha does not match expected_ci_gates_sha")

    if "routing_generation" in manifest:
        _check_routing(
            errors,
            manifest["routing_generation"],
            manifest.get("group"),
            manifest.get("labels"),
        )
    for field in ("progress_marker_version", "release_manifest_version"):
        if field in manifest:
            _check_version(errors, field, manifest[field])
    if "activation_timestamp" in manifest:
        _check_timestamp(errors, manifest["activation_timestamp"])
    return errors
