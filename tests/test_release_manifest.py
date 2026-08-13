import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("release_manifest", SCRIPTS / "release_manifest.py")
release_manifest = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = release_manifest
spec.loader.exec_module(release_manifest)


SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "fedcba9876543210fedcba9876543210fedcba98"


def manifest(**overrides):
    value = {
        "ci_gates_sha": SHA,
        "workflow_sha": OTHER_SHA,
        "routing_generation": "v2",
        "group": "ci-scope-v2-trusted",
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

    def test_sha_and_expected_sha_must_be_pinned(self):
        errors = release_manifest.validate_manifest(manifest(ci_gates_sha="main"), expected_ci_gates_sha=OTHER_SHA)
        self.assertTrue(any("ci_gates_sha" in error for error in errors))
        self.assertTrue(any("expected_ci_gates_sha" in error for error in errors))

    def test_routing_and_versions_are_bounded(self):
        errors = release_manifest.validate_manifest(
            manifest(
                group="ci-scope-v2-trusted",
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
