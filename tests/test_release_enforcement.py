import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.release_enforcement import validate_release, validate_routing_inputs


MANIFEST = json.loads((ROOT / "tests/fixtures/release-manifest-v2.json").read_text())


class ReleaseEnforcementTests(unittest.TestCase):
    def test_production_fixture_is_pinned_and_valid(self):
        workflow = (ROOT / "tests/fixtures/production-caller.yml").read_text()
        self.assertEqual(validate_release(MANIFEST, environment="production", workflow_text=workflow), [])

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
        value = dict(MANIFEST, gates_ref="a" * 40)
        self.assertTrue(any("gates_ref does not match" in error for error in validate_release(value, environment="production")))

    def test_reusable_workflow_use_ref_must_match_manifest_sha(self):
        workflow = (ROOT / "tests/fixtures/production-caller.yml").read_text()
        mismatched = workflow.replace(f"@{MANIFEST['ci_gates_sha']}", "@" + "a" * 40)
        errors = validate_release(MANIFEST, environment="production", workflow_text=mismatched)
        self.assertTrue(any("workflow ci-gates uses ref does not match ci_gates_sha" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
