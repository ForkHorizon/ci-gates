from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "self-check.yml"
CHECKOUT_SHA = "d23441a48e516b6c34aea4fa41551a30e30af803"


def read_block_command(lines, index, minimum_indent):
    block = []
    while index < len(lines):
        block_line = lines[index]
        block_indent = len(block_line) - len(block_line.lstrip())
        if block_line.strip() and block_indent <= minimum_indent:
            break
        if block_line.strip():
            block.append(block_line.strip())
        index += 1
    return "\n".join(block), index


def run_commands(workflow):
    lines = workflow.splitlines()
    steps_index = next(index for index, line in enumerate(lines) if line.strip() == "steps:")
    step_indent = next(
        len(line) - len(line.lstrip()) for line in lines[steps_index + 1 :] if line.strip().startswith("- ")
    )
    commands = []
    index = steps_index + 1
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if indent == step_indent and stripped.startswith("- "):
            index += 1
            continue
        if indent == step_indent + 2 and stripped.startswith("run:"):
            value = stripped[len("run:") :].strip()
            if value == "|":
                command, index = read_block_command(lines, index + 1, step_indent + 2)
                commands.append(command)
                continue
            commands.append(value)
        index += 1
    return commands


def workflow_job_commands(workflow, job_name):
    lines = workflow.splitlines()
    jobs_index = next(index for index, line in enumerate(lines) if line.strip() == "jobs:")
    job_marker = f"  {job_name}:"
    job_index = next(
        index for index, line in enumerate(lines[jobs_index + 1 :], jobs_index + 1) if line.rstrip() == job_marker
    )
    next_job = next(
        (
            index
            for index, line in enumerate(lines[job_index + 1 :], job_index + 1)
            if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":")
        ),
        len(lines),
    )
    return run_commands("\n".join(lines[job_index:next_job]))


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
            "python3 scripts/check-test-discovery.py",
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

    def test_test_discovery_guard_is_exact_and_precedes_unit_tests(self):
        self.assertIn("jobs:\n  self-check:\n", self.workflow)
        commands = workflow_job_commands(self.workflow, "self-check")
        guard = "python3 scripts/check-test-discovery.py --start-directory tests --pattern 'test_*.py'"
        unit_tests = "python3 -m unittest discover -s tests -p 'test_*.py' -q"
        self.assertEqual(commands.count(guard), 1)
        self.assertEqual(commands.count(unit_tests), 1)
        self.assertLess(commands.index(guard), commands.index(unit_tests))

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
