"""Validation for the ci-gates release manifest contract."""

from datetime import datetime
import re
from collections.abc import Mapping
from urllib.parse import urlsplit

from scripts.gates_contract import RoutingContractError, validate_routing


SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
WORKER_DEPLOYMENT_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
DEPLOYMENT_KINDS = frozenset({"cloudflare-worker", "vps"})
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
OPTIONAL_FIELDS = frozenset(
    {"environment", "gates_ref", "worker_deployment_id", "deployment_kind", "control_plane_endpoint"}
)
KNOWN_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS


def _is_sha(value):
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None and value != "0" * 40


def _check_sha(errors, field, value):
    if not _is_sha(value):
        errors.append(f"{field} must be a full lowercase 40-character commit SHA")


def _check_worker_deployment_id(errors, value):
    if (
        not isinstance(value, str)
        or WORKER_DEPLOYMENT_ID_RE.fullmatch(value) is None
        or value == "00000000-0000-0000-0000-000000000000"
    ):
        errors.append(
            "worker_deployment_id must be a verified lowercase Worker deployment UUID; "
            "placeholder values are not accepted"
        )


def _check_control_plane_endpoint(errors, value):
    if not isinstance(value, str) or not value.strip():
        errors.append("control_plane_endpoint must be an absolute HTTPS URL")
        return
    parsed = None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        hostname = None
    if parsed is None or parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        errors.append("control_plane_endpoint must be an absolute HTTPS URL")


def _deployment_provenance_fields(manifest):
    if manifest.get("deployment_kind", "cloudflare-worker") == "vps":
        return {
            "workflow_sha": "github-actions",
            "control_plane_endpoint": "vps-control-plane",
        }
    return {
        "workflow_sha": "github-actions",
        "worker_deployment_id": "cloudflare-workers",
    }


def _provenance_value_is_valid(field, value):
    if field == "workflow_sha":
        return _is_sha(value)
    if field == "worker_deployment_id":
        return (
            isinstance(value, str)
            and WORKER_DEPLOYMENT_ID_RE.fullmatch(value) is not None
            and value != "00000000-0000-0000-0000-000000000000"
        )
    if field == "control_plane_endpoint":
        errors = []
        _check_control_plane_endpoint(errors, value)
        return not errors
    return False


def validate_external_provenance(manifest, provenance) -> list[str]:
    """Require independently supplied evidence for external release claims."""

    if not isinstance(provenance, Mapping):
        return ["external_provenance is required; manifest claims are not external evidence"]

    errors = []
    for field, source in _deployment_provenance_fields(manifest).items():
        entry = provenance.get(field)
        if not isinstance(entry, Mapping):
            errors.append(f"external_provenance.{field} is missing or not an evidence mapping")
            continue
        if entry.get("verified") is not True:
            errors.append(f"external_provenance.{field} is not verified")
        if entry.get("source") != source:
            errors.append(f"external_provenance.{field}.source must be {source}")
        if not isinstance(entry.get("evidence_id"), str) or not entry["evidence_id"].strip():
            errors.append(f"external_provenance.{field}.evidence_id is required")

        observed = entry.get("value")
        valid = _provenance_value_is_valid(field, observed)
        invalid_message = {
            "workflow_sha": "a full lowercase 40-character commit SHA",
            "worker_deployment_id": "a valid Worker deployment UUID",
            "control_plane_endpoint": "an absolute HTTPS URL",
        }[field]
        if not valid:
            errors.append(f"external_provenance.{field}.value must be {invalid_message}")
        elif manifest.get(field) != observed:
            errors.append(f"{field} does not match independently supplied external provenance")
    return errors


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


def _manifest_identity_errors(manifest):
    errors = []
    for field in ("ci_gates_sha", "workflow_sha", "rollback_target"):
        if field in manifest:
            _check_sha(errors, field, manifest[field])
    deployment_kind = manifest.get("deployment_kind", "cloudflare-worker")
    if deployment_kind not in DEPLOYMENT_KINDS:
        errors.append("deployment_kind must be cloudflare-worker or vps")
    if deployment_kind == "vps":
        if "worker_deployment_id" in manifest:
            errors.append("worker_deployment_id must be omitted for vps deployments")
        if "control_plane_endpoint" not in manifest:
            errors.append("control_plane_endpoint is required for vps deployments")
    elif "worker_deployment_id" not in manifest:
        errors.append("worker_deployment_id is required for cloudflare-worker deployments")
    if "worker_deployment_id" in manifest and deployment_kind != "vps":
        _check_worker_deployment_id(errors, manifest["worker_deployment_id"])
    if "control_plane_endpoint" in manifest:
        _check_control_plane_endpoint(errors, manifest["control_plane_endpoint"])
    if "gates_ref" in manifest:
        _check_sha(errors, "gates_ref", manifest["gates_ref"])
    if "environment" in manifest and manifest["environment"] not in {
        "production",
        "canary",
    }:
        errors.append("environment must be production or canary")
    return errors


def _manifest_expected_sha_errors(manifest, expected_ci_gates_sha):
    if expected_ci_gates_sha is None:
        return []
    if not _is_sha(expected_ci_gates_sha):
        return ["expected_ci_gates_sha must be a full lowercase 40-character commit SHA"]
    if manifest.get("ci_gates_sha") != expected_ci_gates_sha:
        return ["ci_gates_sha does not match expected_ci_gates_sha"]
    return []


def validate_manifest(manifest, *, expected_ci_gates_sha=None) -> list[str]:
    """Return contract violations; an empty list means the manifest is valid."""

    if not isinstance(manifest, Mapping):
        return ["manifest must be a mapping"]

    errors = []
    unknown = sorted(set(manifest) - KNOWN_FIELDS, key=str)
    missing = sorted(REQUIRED_FIELDS - set(manifest), key=str)
    errors.extend(f"unknown field: {field}" for field in unknown)
    errors.extend(f"missing field: {field}" for field in missing)

    errors.extend(_manifest_identity_errors(manifest))
    errors.extend(_manifest_expected_sha_errors(manifest, expected_ci_gates_sha))

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
