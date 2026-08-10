import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PYTHON_VERSION = "3.11.9"
SETUP_PYTHON_SHA = "ece7cb06caefa5fff74198d8649806c4678c61a1"


def workflow_steps(workflow):
    steps = []
    current = None
    for line in workflow.splitlines():
        if line.startswith("      - "):
            if current is not None:
                steps.append(current)
            current = [line]
        elif current is not None and line.startswith("        "):
            current.append(line)
    if current is not None:
        steps.append(current)
    return steps


class PythonRuntimeProvisioningTests(unittest.TestCase):
    def test_repository_declares_supported_python_version(self):
        self.assertEqual((ROOT / ".python-version").read_text(encoding="utf-8").strip(), PYTHON_VERSION)

    def test_every_python_workflow_provisions_the_pinned_runtime_before_use(self):
        workflow_paths = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
        self.assertTrue(workflow_paths)
        for path in workflow_paths:
            steps = workflow_steps(path.read_text(encoding="utf-8"))
            python_steps = [index for index, step in enumerate(steps) if "python3" in "\n".join(step)]
            if not python_steps:
                continue
            with self.subTest(workflow=path.name):
                setup_steps = [
                    index
                    for index, step in enumerate(steps)
                    if f"uses: actions/setup-python@{SETUP_PYTHON_SHA}" in "\n".join(step)
                ]
                self.assertEqual(setup_steps, [0])
                setup = "\n".join(steps[setup_steps[0]])
                self.assertIn(f'python-version: "{PYTHON_VERSION}"', setup)
                self.assertNotIn("actions/setup-python@v", setup)
                self.assertTrue(all(setup_steps[0] < index for index in python_steps))

    def test_runtime_setup_is_not_satisfied_by_an_unpinned_action(self):
        for path in list(WORKFLOWS.glob("*.yml")) + list(WORKFLOWS.glob("*.yaml")):
            workflow = path.read_text(encoding="utf-8")
            if "python3" in workflow:
                self.assertNotIn("uses: actions/setup-python@v", workflow)


if __name__ == "__main__":
    unittest.main()
