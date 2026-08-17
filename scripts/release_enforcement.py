"""Fail-closed release and routing checks for gate consumers."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from scripts.gates_contract import RoutingContractError, validate_routing
    from scripts.release_manifest import validate_external_provenance, validate_manifest
    from scripts.workflow_policy import validate_workflow_text
except ModuleNotFoundError:  # direct `python scripts/release_enforcement.py`
    from gates_contract import RoutingContractError, validate_routing
    from release_manifest import validate_external_provenance, validate_manifest
    from workflow_policy import validate_workflow_text


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_GATES_REF_RE = re.compile(r"(?m)^\s*gates-ref\s*:\s*([^#\s]+)")
_GATES_WORKFLOW_USE_RE = re.compile(r"(?m)^\s*uses\s*:\s*ForkHorizon/ci-gates/\.github/workflows/[^@\s]+@([^\s#]+)")


def validate_routing_inputs(
    routing: Mapping[str, object],
    *,
    environment: str,
    gates_ref: object,
) -> list[str]:
    """Validate workflow routing and require immutable refs for v2 releases."""

    errors: list[str] = []
    validated = None
    try:
        validated = validate_routing(routing, environment=environment)
    except RoutingContractError as error:
        errors.append(f"routing contract: {error}")

    # v1 callers retain their historical `main` default. Release/canary v2
    # callers must opt into reproducible gate code explicitly.
    if (validated and validated["generation"] == "v2") or routing.get("generation") == "v2" or environment == "canary":
        errors.extend(_pinned_ref_errors(gates_ref, expected=None, field="gates-ref"))
    return errors


def validate_release(
    manifest: Mapping[str, object],
    *,
    environment: str,
    workflow_text: str | None = None,
    external_provenance: Mapping[str, object] | None = None,
    observed_workflow_sha: object = None,
) -> list[str]:
    """Validate a release manifest and its optional caller workflow."""

    errors = validate_manifest(manifest)
    if observed_workflow_sha is not None:
        errors.append("observed_workflow_sha is not verifiable evidence; supply external_provenance")
    errors.extend(validate_external_provenance(manifest, external_provenance))
    if environment not in {"production", "canary"}:
        errors.append("environment must be production or canary")
        return errors
    if "environment" in manifest and manifest.get("environment") != environment:
        errors.append("manifest environment does not match enforcement environment")

    gates_ref = manifest.get("gates_ref")
    errors.extend(
        _pinned_ref_errors(
            gates_ref,
            expected=manifest.get("ci_gates_sha"),
            field="gates_ref",
        )
    )
    if environment == "canary" and manifest.get("routing_generation") != "v2":
        errors.append("canary releases require routing_generation v2")

    if workflow_text is not None:
        errors.extend(_workflow_ref_errors(workflow_text, manifest.get("gates_ref")))
        errors.extend(_workflow_use_errors(workflow_text, manifest.get("ci_gates_sha")))
        policy_manifest = dict(manifest)
        policy_manifest["source_sha"] = manifest.get("workflow_sha")
        errors.extend(validate_workflow_text(workflow_text, manifest=policy_manifest))
    return _unique(errors)


def _pinned_ref_errors(value: object, *, expected: object, field: str) -> list[str]:
    errors = []
    if not isinstance(value, str) or not SHA_RE.fullmatch(value) or value == "0" * 40:
        errors.append(f"{field} must be a full lowercase 40-character commit SHA")
    elif expected is not None and value != expected:
        errors.append(f"{field} does not match ci_gates_sha")
    return errors


def _workflow_ref_errors(text: str, expected: object) -> list[str]:
    refs = [value.strip("'\"") for value in _GATES_REF_RE.findall(text)]
    if not refs:
        return ["workflow must declare a SHA-pinned gates-ref"]
    errors = []
    for ref in refs:
        errors.extend(_pinned_ref_errors(ref, expected=expected, field="workflow gates-ref"))
    return _unique(errors)


def _workflow_use_errors(text: str, expected: object) -> list[str]:
    """Ensure an external ci-gates reusable workflow is pinned to the manifest SHA."""

    refs = [value.strip("'\"") for value in _GATES_WORKFLOW_USE_RE.findall(text)]
    if not refs:
        return []
    errors: list[str] = []
    for ref in refs:
        errors.extend(_pinned_ref_errors(ref, expected=expected, field="workflow ci-gates uses ref"))
    return _unique(errors)


def _unique(errors: list[str]) -> list[str]:
    return list(dict.fromkeys(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="JSON release manifest")
    parser.add_argument("--environment", choices=("production", "canary"), required=True)
    parser.add_argument("--workflow", help="optional workflow text to validate")
    parser.add_argument("--provenance", required=True, help="JSON external provenance evidence")
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        workflow = Path(args.workflow).read_text(encoding="utf-8") if args.workflow else None
        provenance = json.loads(Path(args.provenance).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"release enforcement error: {error}", file=sys.stderr)
        return 2
    if not isinstance(manifest, Mapping):
        print("release enforcement error: manifest must be a mapping", file=sys.stderr)
        return 2
    errors = validate_release(
        manifest,
        environment=args.environment,
        workflow_text=workflow,
        external_provenance=provenance,
    )
    if errors:
        for error in errors:
            print(f"release enforcement error: {error}", file=sys.stderr)
        return 2
    print(f"Release enforcement passed: {args.environment}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
