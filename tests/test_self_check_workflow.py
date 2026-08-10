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


def read_run_command(lines, index, value, minimum_indent):
    if value.startswith(("|", ">")):
        return read_block_command(lines, index + 1, minimum_indent)
    return value.split(" #", 1)[0].rstrip(), index + 1


def is_mapping_key(line, indent, key):
    if len(line) - len(line.lstrip()) != indent:
        return False
    return line[indent:].split(" #", 1)[0].strip() == f"{key}:"


def run_commands(workflow):
    lines = workflow.splitlines()
    steps_index = next(index for index, line in enumerate(lines) if line.strip().split(" #", 1)[0].strip() == "steps:")
    step_indent = next(
        len(line) - len(line.lstrip()) for line in lines[steps_index + 1 :] if line.strip().startswith("- ")
    )
    commands = []
    index = steps_index + 1
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped.startswith("- ") and indent != step_indent:
            raise ValueError("workflow step list items have inconsistent indentation")
        if indent == step_indent and stripped.startswith("- "):
            value = stripped[2:].strip()
            if value.startswith("run:"):
                command, index = read_run_command(lines, index, value[len("run:") :].strip(), step_indent)
                commands.append(command)
                continue
        if indent == step_indent + 2 and stripped.startswith("run:"):
            command, index = read_run_command(lines, index, stripped[len("run:") :].strip(), step_indent + 2)
            commands.append(command)
            continue
        index += 1
    return commands


def workflow_job_commands(workflow, job_name):
    lines = workflow.splitlines()
    jobs_index = next(index for index, line in enumerate(lines) if line.strip() == "jobs:")
    job_marker = f"  {job_name}:"
    job_indices = [
        index for index, line in enumerate(lines[jobs_index + 1 :], jobs_index + 1) if is_mapping_key(line, 2, job_name)
    ]
    if len(job_indices) != 1:
        raise ValueError(f"expected exactly one {job_marker!r} job mapping")
    job_index = job_indices[0]
    next_job = next(
        (
            index
            for index, line in enumerate(lines[job_index + 1 :], job_index + 1)
            if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":")
        ),
        len(lines),
    )
    job_lines = lines[job_index:next_job]
    step_indices = [index for index, line in enumerate(job_lines) if is_mapping_key(line, 4, "steps")]
    if len(step_indices) != 1:
        raise ValueError("expected exactly one steps mapping in self-check job")
    return run_commands("\n".join(job_lines))


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
        for command in commands:
            if "check-test-discovery.py" in command:
                self.assertEqual(command, guard)
            if "unittest discover" in command:
                self.assertEqual(command, unit_tests)
        self.assertLess(commands.index(guard), commands.index(unit_tests))

    def test_workflow_parser_includes_inline_and_annotated_run_steps(self):
        workflow = """jobs:
  self-check:
    steps:
      - run: echo inline
      - run: | # annotated block
          echo block
      - name: separate
        run: echo separate # trailing comment
"""
        self.assertEqual(
            workflow_job_commands(workflow, "self-check"),
            ["echo inline", "echo block", "echo separate"],
        )

    def test_workflow_parser_rejects_duplicate_job_and_steps_mappings(self):
        duplicate_steps = self.workflow.replace(
            "    steps:\n", "    steps: # first mapping\n    steps: # duplicate mapping\n", 1
        )
        duplicate_job = self.workflow + "\n  self-check: # duplicate job\n    steps:\n      - run: true\n"
        with self.assertRaises(ValueError):
            workflow_job_commands(duplicate_steps, "self-check")
        with self.assertRaises(ValueError):
            workflow_job_commands(duplicate_job, "self-check")

    def test_workflow_parser_rejects_malformed_step_indentation(self):
        malformed = self.workflow.replace(
            "      - name: Check test discovery", "       - name: Check test discovery", 1
        )
        with self.assertRaises(ValueError):
            workflow_job_commands(malformed, "self-check")

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
