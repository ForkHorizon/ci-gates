import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-test-discovery.py"


class TestDiscoveryGuardTests(unittest.TestCase):
    def create_fixture(self, root, *, package=True, broken=False):
        tests = root / "tests"
        package_dir = tests / "linter"
        package_dir.mkdir(parents=True)
        (package_dir / "test_sample.py").write_text(
            "import unittest\n"
            "\n"
            "class SampleTests(unittest.TestCase):\n"
            "    def test_sample(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )
        if package:
            (package_dir / "__init__.py").write_text("", encoding="utf-8")
        if broken:
            (package_dir / "test_broken.py").write_text("raise RuntimeError('broken import')\n", encoding="utf-8")
        (tests / "notes.py").write_text("not a test module\n", encoding="utf-8")

    def run_guard(self, root, pattern="test_*.py"):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--start-directory", "tests", "--pattern", pattern],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_guard_accepts_all_importable_test_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_fixture(root)
            result = self.run_guard(root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1/1 test module(s)", result.stdout)
        self.assertIn("1 test case(s)", result.stdout)

    def test_guard_rejects_test_file_in_non_package_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_fixture(root, package=False)
            result = self.run_guard(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tests/linter/test_sample.py", result.stderr)

    def test_guard_rejects_import_failure_instead_of_counting_discovery_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_fixture(root, broken=True)
            result = self.run_guard(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tests/linter/test_broken.py", result.stderr)

    def test_guard_uses_pattern_and_ignores_non_test_python_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_fixture(root)
            result = self.run_guard(root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("notes.py", result.stdout)

    def test_guard_rejects_invalid_absolute_pattern_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_fixture(root)
            result = self.run_guard(root, pattern="/tmp/*")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("relative filename glob", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_guard_rejects_malformed_parent_relative_and_nonmatching_patterns(self):
        patterns = ("[", "../*.py", "*; touch marker", "does_not_match_*.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_fixture(root)
            results = [self.run_guard(root, pattern=pattern) for pattern in patterns]
        for index, pattern in enumerate(patterns):
            result = results[index]
            with self.subTest(pattern=pattern):
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
