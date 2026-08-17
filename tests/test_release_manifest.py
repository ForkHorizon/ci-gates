import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS.parent))
spec = importlib.util.spec_from_file_location("release_manifest", SCRIPTS / "release_manifest.py")
release_manifest = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = release_manifest
spec.loader.exec_module(release_manifest)


SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "fedcba9876543210fedcba9876543210fedcba98"
WORKER_DEPLOYMENT_ID = "11111111-2222-3333-4444-555555555555"


def manifest(**overrides):
    value = {
        "ci_gates_sha": SHA,
        "workflow_sha": OTHER_SHA,
        "worker_deployment_id": WORKER_DEPLOYMENT_ID,
        "routing_generation": "v2",
        "group": "ci-scope-v2-canary",
        "labels": ["self-hosted", "macOS", "ARM64", "ci-scope-v2"],
        "progress_marker_version": 1,
        "release_manifest_version": 1,
        "activation_timestamp": "2026-08-13T12:00:00Z",
        "rollback_target": OTHER_SHA,
    }
    value.update(overrides)
    return value


class ReleaseManifestTests(unittest.TestCase):
    def test_valid_v2_manifest_and_expected_sha(self):
        self.assertEqual(
            release_manifest.validate_manifest(manifest(), expected_ci_gates_sha=SHA),
            [],
        )

    def test_missing_and_unknown_fields_fail_closed(self):
        value = manifest()
        del value["workflow_sha"]
        value["floating_ref"] = "main"
        errors = release_manifest.validate_manifest(value)
        self.assertIn("missing field: workflow_sha", errors)
        self.assertIn("unknown field: floating_ref", errors)

    def test_cloudflare_worker_deployment_id_is_required_and_must_not_be_placeholder(self):
        missing = manifest()
        del missing["worker_deployment_id"]
        self.assertIn(
            "worker_deployment_id is required for cloudflare-worker deployments",
            release_manifest.validate_manifest(missing),
        )
        errors = release_manifest.validate_manifest(
            manifest(worker_deployment_id="<required: verified Worker deployment UUID>")
        )
        self.assertTrue(any("worker_deployment_id" in error for error in errors))

    def test_vps_manifest_uses_control_plane_endpoint(self):
        value = manifest(
            deployment_kind="vps",
            control_plane_endpoint="https://ci.example.test/api/ci/v2",
        )
        del value["worker_deployment_id"]
        self.assertEqual(release_manifest.validate_manifest(value), [])

    def test_vps_manifest_requires_https_endpoint(self):
        value = manifest(deployment_kind="vps", control_plane_endpoint="http://ci.example.test")
        del value["worker_deployment_id"]
        errors = release_manifest.validate_manifest(value)
        self.assertIn("control_plane_endpoint must be an absolute HTTPS URL", errors)

    def test_sha_and_expected_sha_must_be_pinned(self):
        errors = release_manifest.validate_manifest(manifest(ci_gates_sha="main"), expected_ci_gates_sha=OTHER_SHA)
        self.assertTrue(any("ci_gates_sha" in error for error in errors))
        self.assertTrue(any("expected_ci_gates_sha" in error for error in errors))

    def test_zero_sha_is_not_release_provenance(self):
        errors = release_manifest.validate_manifest(manifest(workflow_sha="0" * 40))
        self.assertIn(
            "workflow_sha must be a full lowercase 40-character commit SHA",
            errors,
        )

    def test_routing_and_versions_are_bounded(self):
        errors = release_manifest.validate_manifest(
            manifest(
                group="ci-scope-v2-canary",
                labels=["self-hosted"],
                progress_marker_version=0,
                release_manifest_version=True,
            )
        )
        self.assertTrue(any("routing contract: labels: v2 requires" in error for error in errors))
        self.assertIn("progress_marker_version must be a positive integer <= 1000000", errors)
        self.assertIn("release_manifest_version must be a positive integer <= 1000000", errors)

    def test_timestamp_and_rollback_target_are_required_contract_values(self):
        errors = release_manifest.validate_manifest(manifest(activation_timestamp="tomorrow", rollback_target="main"))
        self.assertIn("activation_timestamp must be an ISO 8601 timestamp with timezone", errors)
        self.assertIn("rollback_target must be a full lowercase 40-character commit SHA", errors)


if __name__ == "__main__":
    unittest.main()
