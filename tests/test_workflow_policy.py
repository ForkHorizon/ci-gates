import unittest

from scripts.workflow_policy import validate_workflow_text


SHA = "a" * 40

VALID_V2 = """\
name: trusted quality
on:
  pull_request:
    types: [opened, synchronize]
jobs:
  gate:
    if: github.event.pull_request.head.repo.full_name == github.repository
    runs-on:
      group: ci-scope-v2-trusted
      labels: [self-hosted, macOS, ARM64, ci-scope-v2]
    routing-generation: v2
    uses: ForkHorizon/ci-gates/.github/workflows/code-linter.yml@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
"""

VALID_V1 = """\
name: legacy quality
on: push
jobs:
  gate:
    runs-on: [self-hosted, macOS, ARM64, ci-scope]
    steps:
      - run: echo ok
"""


class WorkflowPolicyTests(unittest.TestCase):
    def test_valid_v2_workflow_and_manifest_pass(self):
        manifest = {
            "source_sha": SHA,
            "approved_origins": ["ForkHorizon/ci-gates"],
        }
        self.assertEqual(validate_workflow_text(VALID_V2, manifest=manifest), [])

    def test_valid_v1_workflow_passes_without_manifest_validation(self):
        self.assertEqual(validate_workflow_text(VALID_V1), [])

    def test_explicit_v1_generation_remains_compatible(self):
        workflow = VALID_V1.replace("    runs-on:", "    routing-generation: v1\n    runs-on:")
        self.assertEqual(validate_workflow_text(workflow), [])

    def test_external_fork_cannot_use_trusted_group(self):
        workflow = VALID_V2.replace(
            "if: github.event.pull_request.head.repo.full_name == github.repository",
            "if: github.event.pull_request.head.repo.full_name != github.repository",
        )
        self.assertTrue(any("external fork" in issue for issue in validate_workflow_text(workflow)))

    def test_pull_request_target_head_checkout_is_blocked(self):
        workflow = VALID_V1.replace("on: push", "on: pull_request_target\n").replace(
            "- run: echo ok",
            "- uses: actions/checkout@v4\n        with:\n          ref: ${{ github.event.pull_request.head.sha }}",
        )
        self.assertTrue(any("untrusted pull request head" in issue for issue in validate_workflow_text(workflow)))

    def test_production_reusable_workflow_cannot_float_on_main(self):
        workflow = VALID_V2.replace("@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "@main")
        self.assertTrue(any("floating @main" in issue for issue in validate_workflow_text(workflow)))
        self.assertEqual(validate_workflow_text(workflow, production=False), [])

    def test_routing_group_and_labels_must_match_generation(self):
        workflow = VALID_V2.replace("ci-scope-v2-trusted", "ci-scope-v1").replace("ci-scope-v2]", "ci-scope-v1]")
        issues = validate_workflow_text(workflow)
        self.assertTrue(any("group" in issue for issue in issues))
        self.assertTrue(any("labels" in issue for issue in issues))

    def test_v1_and_v2_routing_fields_are_mutually_exclusive(self):
        workflow = VALID_V2.replace("runs-on:\n", "runs-on: [self-hosted, macOS]\n")
        self.assertTrue(any("v1 and v2" in issue for issue in validate_workflow_text(workflow)))

    def test_unapproved_reusable_workflow_origin_is_blocked(self):
        workflow = VALID_V2.replace("ForkHorizon/ci-gates", "evil/example")
        self.assertTrue(any("not approved" in issue for issue in validate_workflow_text(workflow)))

    def test_missing_manifest_source_sha_fails_closed(self):
        issues = validate_workflow_text(VALID_V2, manifest={})
        self.assertTrue(any("source SHA" in issue for issue in issues))

    def test_missing_check_input_source_sha_fails_closed(self):
        issues = validate_workflow_text(VALID_V2, manifest={"check_input": {}})
        self.assertTrue(any("source SHA" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
