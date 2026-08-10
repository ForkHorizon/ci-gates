import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PINNED_GATES_SHA = "441c840036ae31e9ac310ff381b6322339dfff65"


class ReusableWorkflowReferenceTests(unittest.TestCase):
    def test_all_gate_workflows_pin_ci_gates_to_one_revision(self):
        workflow_paths = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
        gate_workflows = []
        for path in workflow_paths:
            workflow = path.read_text(encoding="utf-8")
            if "ci-gates" not in workflow:
                continue
            gate_workflows.append(path)
            with self.subTest(workflow=path.name):
                self.assertNotIn("default: main", workflow)
                self.assertNotIn("ref: main", workflow)
                self.assertIn(PINNED_GATES_SHA, workflow)
        self.assertGreaterEqual(len(gate_workflows), 8)

    def test_clone_based_gate_workflows_fetch_and_detach_the_requested_sha(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            workflow = path.read_text(encoding="utf-8")
            if "git clone" not in workflow or "inputs.gates-ref" not in workflow:
                continue
            with self.subTest(workflow=path.name):
                self.assertIn("GATES_REF: ${{ inputs.gates-ref }}", workflow)
                self.assertIn('git -C "$RUNNER_TEMP/ci-gates" fetch --quiet --depth 1 origin "$GATES_REF"', workflow)
                self.assertIn('git -C "$RUNNER_TEMP/ci-gates" checkout --quiet --detach FETCH_HEAD', workflow)
                self.assertNotIn('--branch "${{ inputs.gates-ref }}"', workflow)


if __name__ == "__main__":
    unittest.main()
