import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PYTHON_VERSION = "3.9.6"
SETUP_PYTHON_SHA = "ece7cb06caefa5fff74198d8649806c4678c61a1"


class PythonRuntimeProvisioningTests(unittest.TestCase):
    def test_repository_declares_supported_python_version(self):
        self.assertEqual((ROOT / ".python-version").read_text(encoding="utf-8").strip(), PYTHON_VERSION)

    def test_every_python_workflow_provisions_the_pinned_runtime(self):
        workflow_paths = sorted(WORKFLOWS.glob("*.yml"))
        self.assertTrue(workflow_paths)
        for path in workflow_paths:
            workflow = path.read_text(encoding="utf-8")
            if "python3" not in workflow:
                continue
            with self.subTest(workflow=path.name):
                self.assertIn(f"actions/setup-python@{SETUP_PYTHON_SHA}", workflow)
                self.assertIn(f'python-version: "{PYTHON_VERSION}"', workflow)

    def test_runtime_setup_is_not_satisfied_by_an_unpinned_action(self):
        for path in WORKFLOWS.glob("*.yml"):
            workflow = path.read_text(encoding="utf-8")
            if "python3" in workflow:
                self.assertNotIn("uses: actions/setup-python@v", workflow)


if __name__ == "__main__":
    unittest.main()
