import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
CONTRACT_INPUTS = (
    "runner-group",
    "runner-labels",
    "runner-label",
    "routing-generation",
    "workflow-contract-version",
    "trust-fixture-mode",
)
EXPECTED_V1 = {
    "code-linter.yml": ("Default", ["self-hosted", "macOS", "ARM64", "ci-scope"]),
    "go-quality.yml": ("Default", ["self-hosted", "macOS", "ARM64", "ci-scope"]),
    "python-quality.yml": ("Default", ["self-hosted", "macOS", "ARM64", "ci-scope"]),
    "slop-review.yml": ("Default", ["self-hosted", "macOS", "ARM64", "ci-scope"]),
    "swift-compile.yml": (
        "ci-scope-broker",
        ["self-hosted", "macOS", "ARM64", "ci-scope-broker"],
    ),
    "swift-quality.yml": (
        "ci-scope-broker",
        ["self-hosted", "macOS", "ARM64", "ci-scope-broker"],
    ),
    "unity-quality.yml": ("Default", ["self-hosted", "macOS", "ARM64", "ci-scope"]),
    "web-quality.yml": ("Default", ["self-hosted", "macOS", "ARM64", "ci-scope"]),
}
CONTRACT_GUARD = (
    "(inputs['routing-generation'] == 'v1' && inputs['workflow-contract-version'] == 'v1') "
    "|| (inputs['routing-generation'] == 'v2' && inputs['workflow-contract-version'] == 'v2')"
)


def _gate_workflows():
    return sorted(
        path
        for path in WORKFLOWS.glob("*.yml")
        if path.name != "routing-validation.yml" and "  workflow_call:" in path.read_text(encoding="utf-8")
    )


def _workflow_inputs(workflow):
    lines = workflow.splitlines()
    start = lines.index("    inputs:") + 1
    inputs = {}
    current = None
    for line in lines[start:]:
        if line == "    jobs:":
            break
        field = re.fullmatch(r"      ([a-z0-9-]+):", line)
        if field:
            current = field.group(1)
            inputs[current] = {}
            continue
        attribute = re.fullmatch(r"        (type|default):\s*(.*)", line)
        if attribute and current:
            inputs[current][attribute.group(1)] = attribute.group(2)
    return inputs


def _scalar(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


class WorkflowContractTests(unittest.TestCase):
    def test_all_reusable_gate_workflows_have_contract_inputs_and_defaults(self):
        workflows = _gate_workflows()
        self.assertEqual({path.name for path in workflows}, set(EXPECTED_V1))

        for path in workflows:
            with self.subTest(workflow=path.name):
                workflow = path.read_text(encoding="utf-8")
                inputs = _workflow_inputs(workflow)
                for name in CONTRACT_INPUTS:
                    self.assertIn(name, inputs)
                    self.assertEqual(inputs[name].get("type"), "string")
                    self.assertIn("default", inputs[name])

                labels = json.loads(_scalar(inputs["runner-labels"]["default"]))
                self.assertIsInstance(labels, list)
                self.assertTrue(labels)
                labels_expression = (
                    r"      labels: \$\{\{ fromJSON\(inputs\['runner-labels'\]\) \}\}"
                    if path.name == "code-linter.yml"
                    else r"      labels: \$\{\{ inputs\['runner-label'\] \}\}"
                )
                self.assertRegex(
                    workflow,
                    r"(?m)^    runs-on:\n"
                    r"      group: \$\{\{ inputs\['runner-group'\] \}\}\n"
                    + labels_expression + "$",
                )
                self.assertIn("uses: ./.github/workflows/routing-validation.yml", workflow)

    def test_v1_defaults_and_existing_gates_ref_behavior_are_unchanged(self):
        for path in _gate_workflows():
            with self.subTest(workflow=path.name):
                workflow = path.read_text(encoding="utf-8")
                inputs = _workflow_inputs(workflow)
                runner_group, labels = EXPECTED_V1[path.name]
                self.assertEqual(_scalar(inputs["runs-on"]["default"]), json.dumps(labels))
                self.assertEqual(_scalar(inputs["runner-group"]["default"]), runner_group)
                self.assertEqual(json.loads(_scalar(inputs["runner-labels"]["default"])), labels)
                self.assertEqual(_scalar(inputs["runner-label"]["default"]), labels[-1])
                self.assertEqual(_scalar(inputs["routing-generation"]["default"]), "v1")
                self.assertEqual(_scalar(inputs["workflow-contract-version"]["default"]), "v1")
                self.assertEqual(_scalar(inputs["trust-fixture-mode"]["default"]), "")
                self.assertEqual(_scalar(inputs["gates-ref"]["default"]), "main")
                self.assertNotIn("default: v2", workflow)

    def test_v1_and_v2_cannot_be_eligible_at_the_same_time(self):
        for path in _gate_workflows():
            with self.subTest(workflow=path.name):
                workflow = path.read_text(encoding="utf-8")
                self.assertIn("uses: ./.github/workflows/routing-validation.yml", workflow)
                self.assertIn("needs: routing-validation", workflow)
                self.assertIn("needs.routing-validation.result == 'success'", workflow)
                self.assertNotIn("runs-on: ${{ fromJSON(inputs['runs-on']) }}", workflow)

    def test_existing_pinned_checkout_refs_do_not_become_unpinned(self):
        checkout_pattern = re.compile(r"actions/checkout@([^\s#]+)")
        sha_pattern = re.compile(r"[0-9a-f]{40}")
        for path in _gate_workflows():
            refs = checkout_pattern.findall(path.read_text(encoding="utf-8"))
            if any(sha_pattern.fullmatch(ref) for ref in refs):
                with self.subTest(workflow=path.name):
                    self.assertTrue(refs)
                    self.assertTrue(all(sha_pattern.fullmatch(ref) for ref in refs))

    def test_action_references_are_pinned(self):
        action_pattern = re.compile(r"uses:\s+((?:actions|github)/[^@\s]+)@([^\s#]+)")
        sha_pattern = re.compile(r"[0-9a-f]{40}")
        for path in sorted(WORKFLOWS.glob("*.yml")):
            workflow = path.read_text(encoding="utf-8")
            for action, ref in action_pattern.findall(workflow):
                with self.subTest(workflow=path.name, action=action):
                    self.assertIsNotNone(sha_pattern.fullmatch(ref))


if __name__ == "__main__":
    unittest.main()
