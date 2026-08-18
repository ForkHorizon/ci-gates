import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.release_enforcement import validate_release, validate_routing_inputs


MANIFEST = json.loads((ROOT / "tests/fixtures/release-manifest-v2.json").read_text())
UNRESOLVED_PROVENANCE = json.loads((ROOT / "tests/fixtures/release-provenance-unresolved.json").read_text())
WORKFLOW_SHA = "0123456789abcdef0123456789abcdef01234567"
WORKER_DEPLOYMENT_ID = "11111111-2222-3333-4444-555555555555"


def valid_manifest(**overrides):
    value = dict(
        MANIFEST,
        workflow_sha=WORKFLOW_SHA,
        worker_deployment_id=WORKER_DEPLOYMENT_ID,
    )
    value.update(overrides)
    return value


def valid_provenance(value):
    # Synthetic evidence IDs exercise the handoff shape; they are not external proof.
    return {
        "workflow_sha": {
            "value": value["workflow_sha"],
            "source": "github-actions",
            "evidence_id": "fixture-github-run",
            "verified": True,
        },
        "worker_deployment_id": {
            "value": value["worker_deployment_id"],
            "source": "cloudflare-workers",
            "evidence_id": "fixture-worker-deployment",
            "verified": True,
        },
    }


def valid_vps_manifest(**overrides):
    value = valid_manifest(deployment_kind="vps", control_plane_endpoint="https://ci.example.test/api/ci/v2")
    del value["worker_deployment_id"]
    value.update(overrides)
    return value


def valid_vps_provenance(value):
    return {
        "workflow_sha": {
            "value": value["workflow_sha"],
            "source": "github-actions",
            "evidence_id": "fixture-github-run",
            "verified": True,
        },
        "control_plane_endpoint": {
            "value": value["control_plane_endpoint"],
            "source": "vps-control-plane",
            "evidence_id": "fixture-vps-deployment",
            "verified": True,
        },
    }


class ReleaseEnforcementTests(unittest.TestCase):
    def test_production_fixture_is_pinned_and_valid(self):
        workflow = (ROOT / "tests/fixtures/production-caller.yml").read_text()
        self.assertEqual(
            validate_release(
                valid_manifest(),
                environment="production",
                workflow_text=workflow,
                external_provenance=valid_provenance(valid_manifest()),
            ),
            [],
        )

    def test_vps_manifest_uses_endpoint_provenance(self):
        value = valid_vps_manifest()
        self.assertEqual(
            validate_release(
                value,
                environment="production",
                external_provenance=valid_vps_provenance(value),
            ),
            [],
        )

    def test_self_declared_workflow_sha_is_not_release_evidence(self):
        errors = validate_release(valid_manifest(), environment="production")
        self.assertTrue(any("external_provenance is required" in error for error in errors))

    def test_observed_workflow_sha_is_not_verifiable_provenance(self):
        errors = validate_release(
            valid_manifest(),
            environment="production",
            observed_workflow_sha="a" * 40,
        )
        self.assertIn(
            "observed_workflow_sha is not verifiable evidence; supply external_provenance",
            errors,
        )

    def test_unresolved_provenance_fixture_fails_closed(self):
        errors = validate_release(
            valid_manifest(),
            environment="production",
            external_provenance=UNRESOLVED_PROVENANCE,
        )
        self.assertIn("external_provenance.workflow_sha is not verified", errors)
        self.assertIn("external_provenance.worker_deployment_id is not verified", errors)

    def test_shape_only_external_values_do_not_prove_release(self):
        value = valid_manifest()
        shape_only = {
            "workflow_sha": {"value": value["workflow_sha"]},
            "worker_deployment_id": {"value": value["worker_deployment_id"]},
        }
        errors = validate_release(
            value,
            environment="production",
            external_provenance=shape_only,
        )
        self.assertIn("external_provenance.workflow_sha is not verified", errors)
        self.assertIn("external_provenance.worker_deployment_id is not verified", errors)

    def test_external_provenance_must_match_manifest_claims(self):
        value = valid_manifest()
        provenance = valid_provenance(value)
        provenance["workflow_sha"]["value"] = "a" * 40
        errors = validate_release(
            value,
            environment="production",
            external_provenance=provenance,
        )
        self.assertIn(
            "workflow_sha does not match independently supplied external provenance",
            errors,
        )

    def test_manifest_environment_must_match_enforcement_context(self):
        errors = validate_release(
            valid_manifest(environment="canary"),
            environment="production",
            external_provenance=valid_provenance(valid_manifest(environment="canary")),
        )
        self.assertIn("manifest environment does not match enforcement environment", errors)

    def test_unverified_worker_deployment_placeholder_blocks_release(self):
        errors = validate_release(
            MANIFEST,
            environment="production",
            external_provenance=UNRESOLVED_PROVENANCE,
        )
        self.assertTrue(any("worker_deployment_id" in error for error in errors))

    def test_canary_requires_v2_and_sha_ref(self):
        self.assertEqual(
            validate_routing_inputs(
                {
                    "generation": "v2",
                    "group": "ci-scope-v2-canary",
                    "labels": ["self-hosted", "macOS", "ARM64", "ci-scope-v2"],
                    "workflow-contract-version": "v2",
                    "trust-fixture-mode": "canary-only",
                },
                environment="canary",
                gates_ref=MANIFEST["gates_ref"],
            ),
            [],
        )

    def test_canary_fixture_uses_current_manifest_gate_pin(self):
        canary = (ROOT / ".github/workflows/v2-canary.yml").read_text()
        self.assertEqual(
            canary.count(f"gates-ref: {MANIFEST['ci_gates_sha']}"),
            2,
        )

    def test_invalid_routing_and_floating_release_ref_fail_closed(self):
        errors = validate_routing_inputs(
            {
                "generation": "v2",
                "group": "untrusted",
                "labels": ["self-hosted"],
                "workflow-contract-version": "v2",
            },
            environment="production",
            gates_ref="main",
        )
        self.assertTrue(any("routing contract" in error for error in errors))
        self.assertTrue(any("gates-ref" in error for error in errors))

    def test_manifest_ref_must_match_gate_sha(self):
        value = valid_manifest(gates_ref="a" * 40)
        self.assertTrue(
            any(
                "gates_ref does not match" in error
                for error in validate_release(
                    value,
                    environment="production",
                    external_provenance=valid_provenance(value),
                )
            )
        )

    def test_reusable_workflow_use_ref_must_match_manifest_sha(self):
        workflow = (ROOT / "tests/fixtures/production-caller.yml").read_text()
        mismatched = workflow.replace(f"@{MANIFEST['ci_gates_sha']}", "@" + "a" * 40)
        errors = validate_release(
            valid_manifest(),
            environment="production",
            workflow_text=mismatched,
            external_provenance=valid_provenance(valid_manifest()),
        )
        self.assertTrue(any("workflow ci-gates uses ref does not match ci_gates_sha" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
