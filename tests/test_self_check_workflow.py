from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "self-check.yml"
CHECKOUT_SHA = "d23441a48e516b6c34aea4fa41551a30e30af803"


class SelfCheckWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_runs_for_pull_requests_merge_queue_and_main(self):
        self.assertIn("  pull_request:\n", self.workflow)
        self.assertIn("  merge_group:\n", self.workflow)
        self.assertIn("    branches: [main]\n", self.workflow)

    def test_uses_read_only_checkout_of_the_revision_under_test(self):
        self.assertIn(f"uses: actions/checkout@{CHECKOUT_SHA}", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertNotIn("repository: ForkHorizon/ci-gates", self.workflow)
        self.assertNotIn("ref: main", self.workflow)

    def test_runs_all_local_validation_layers(self):
        expected_commands = (
            "python3 -m compileall",
            "python3 -m unittest discover",
            "python3 scripts/code-linter.py",
            "ruff check",
            "ruff format --check",
            "actionlint@v1.7.12",
            "git diff --check",
        )
        for command in expected_commands:
            with self.subTest(command=command):
                self.assertIn(command, self.workflow)

    def test_repository_uses_default_linter_policy(self):
        config = json.loads((ROOT / ".code-linter.json").read_text(encoding="utf-8"))
        self.assertEqual(config, {})

    def test_code_linter_workflow_exposes_coverage_mode(self):
        workflow = (ROOT / ".github" / "workflows" / "code-linter.yml").read_text(encoding="utf-8")
        self.assertIn("timeout-minutes: 15", workflow)
        self.assertIn("coverage-mode:", workflow)
        self.assertIn("COVERAGE_MODE: ${{ inputs['coverage-mode'] }}", workflow)
        self.assertIn('coverage_args+=(--coverage-mode "$COVERAGE_MODE")', workflow)
        self.assertIn('--coverage-mode "$COVERAGE_MODE"', workflow)


if __name__ == "__main__":
    unittest.main()
