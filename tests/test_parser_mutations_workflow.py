from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "parser-mutations.yml"
SETUP_PYTHON_SHA = "ece7cb06caefa5fff74198d8649806c4678c61a1"
CHECKOUT_SHA = "d23441a48e516b6c34aea4fa41551a30e30af803"
HELPER_SPEC = importlib.util.spec_from_file_location(
    "parser_mutation_workflow_helper", ROOT / "tests" / "test_self_check_workflow.py"
)
assert HELPER_SPEC is not None
assert HELPER_SPEC.loader is not None
HELPER = importlib.util.module_from_spec(HELPER_SPEC)
sys.modules[HELPER_SPEC.name] = HELPER
HELPER_SPEC.loader.exec_module(HELPER)
workflow_job_commands = HELPER.workflow_job_commands


class ParserMutationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.commands = workflow_job_commands(cls.workflow, "parser-mutations")

    def test_workflow_is_manual_and_scheduled_not_implicitly_per_pull_request(self):
        self.assertIn("  workflow_dispatch:\n", self.workflow)
        self.assertIn("  schedule:\n", self.workflow)
        self.assertNotIn("  pull_request:\n", self.workflow)

    def test_workflow_uses_read_only_permissions(self):
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertNotIn("contents: write", self.workflow)

    def test_workflow_has_single_bounded_parser_mutation_job(self):
        self.assertIn("jobs:\n  parser-mutations:\n", self.workflow)
        self.assertIn("timeout-minutes: 15", self.workflow)
        self.assertEqual(self.workflow.count("  parser-mutations:"), 1)

    def test_workflow_provisions_pinned_python(self):
        self.assertIn(f"actions/setup-python@{SETUP_PYTHON_SHA}", self.workflow)
        self.assertIn('python-version: "3.11.9"', self.workflow)

    def test_workflow_checks_out_revision_without_credentials(self):
        self.assertIn(f"actions/checkout@{CHECKOUT_SHA}", self.workflow)
        self.assertIn("fetch-depth: 1", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)

    def test_workflow_runs_only_the_full_mutation_stage(self):
        self.assertEqual(self.commands, ["python3 scripts/run-parser-mutations.py"])

    def test_workflow_does_not_allow_a_subset_or_untrusted_mutation_command(self):
        self.assertNotIn("--mutation", "\n".join(self.commands))
        self.assertNotIn("--list", "\n".join(self.commands))
        self.assertNotIn("pip install", "\n".join(self.commands))

    def test_workflow_command_is_in_the_parser_mutation_job(self):
        self.assertEqual(workflow_job_commands(self.workflow, "parser-mutations"), self.commands)
        with self.assertRaises(ValueError):
            workflow_job_commands(self.workflow.replace("  parser-mutations:", "  other-job:", 1), "parser-mutations")


if __name__ == "__main__":
    unittest.main()
