import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ci_scope_adapters import commands_for


def _check(workdir="."):
    return type("Check", (), {"type": "python-pytest", "workdir": workdir, "config": None, "params": {}})()


class PythonPytestAdapterTests(unittest.TestCase):
    def test_runs_pytest_when_the_project_has_a_tests_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            self.assertEqual(
                commands_for(_check(), root, ROOT, ("base", "head")),
                [["python3", "-m", "pytest", "tests", "-q"]],
            )

    def test_skips_with_exit_zero_when_there_is_no_tests_directory(self):
        # Shardrail_Web keeps its tests in apps/web/tests and planning/tests, none at the root.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "apps/web/tests").mkdir(parents=True)
            commands = commands_for(_check(), root, ROOT, ("base", "head"))
            self.assertEqual(len(commands), 1)
            self.assertNotIn("pytest", commands[0][:3])
            result = subprocess.run(commands[0], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertIn("skipped", result.stdout)

    def test_checks_the_tests_directory_of_the_configured_workdir(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service/tests").mkdir(parents=True)
            self.assertEqual(
                commands_for(_check("service"), root, ROOT, ("base", "head")),
                [["python3", "-m", "pytest", "tests", "-q"]],
            )
            self.assertIn("skipped", " ".join(commands_for(_check("."), root, ROOT, ("base", "head"))[0]))


if __name__ == "__main__":
    unittest.main()
