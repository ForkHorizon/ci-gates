"""Tests for the existing-test protection detector."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.test_protection import is_test_path, scan


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class PathTests(unittest.TestCase):
    def test_default_patterns_cover_each_stack(self):
        for path in (
            "tests/test_a.py",
            "pkg/a_test.go",
            "src/a.spec.ts",
            "src/a.test.js",
            "Tests/AppTests.swift",
            "Assets/Tests/Edit/Foo.cs",
            "src/__tests__/x.js",
        ):
            self.assertTrue(is_test_path(path), path)
        for path in ("src/app.py", "main.go", "README.md", "scripts/check"):
            self.assertFalse(is_test_path(path), path)

    def test_extra_and_excluded_patterns(self):
        self.assertTrue(is_test_path("spec/a.rb", extra=(r"^spec/",)))
        self.assertFalse(is_test_path("tests/fixtures/data.py", excluded=(r"/fixtures/",)))


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "Test")
        (self.root / "tests").mkdir()
        (self.root / "tests/test_a.py").write_text("def test_a():\n    assert 1 == 1\n")
        (self.root / "app.py").write_text("x = 1\n")
        (self.root / "package.json").write_text(json.dumps({"scripts": {"test": "node --test"}}))
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "base")

    def tearDown(self):
        self.temp.cleanup()

    def found(self):
        return sorted((f.rule_id, f.severity) for f in scan(self.root, "worktree", "HEAD~1", "HEAD"))

    def test_clean_change_to_production_code_passes(self):
        (self.root / "app.py").write_text("x = 2\n")
        self.assertEqual(self.found(), [])

    def test_modifying_an_existing_assertion_is_high_severity(self):
        (self.root / "tests/test_a.py").write_text("def test_a():\n    assert True\n")
        self.assertEqual(self.found(), [("test-modified", "high")])

    def test_pure_additions_and_new_test_files_are_allowed(self):
        (self.root / "tests/test_a.py").write_text(
            "def test_a():\n    assert 1 == 1\n\n\ndef test_b():\n    assert 2 == 2\n"
        )
        (self.root / "tests/test_new.py").write_text("def test_new():\n    assert 3 == 3\n")
        self.assertEqual(self.found(), [])

    def test_deleting_or_renaming_an_existing_test_is_flagged(self):
        git(self.root, "mv", "tests/test_a.py", "tests/test_b.py")
        self.assertEqual(self.found(), [("test-renamed", "high")])
        git(self.root, "reset", "-q", "--hard")
        (self.root / "tests/test_a.py").unlink()
        self.assertEqual(self.found(), [("test-deleted", "high")])

    def test_new_skip_marker_is_medium_unless_justified(self):
        (self.root / "tests/test_new.py").write_text("import pytest\n\n@pytest.mark.skip\ndef test_x():\n    pass\n")
        self.assertEqual(self.found(), [("test-skip-added", "medium")])
        (self.root / "tests/test_new.py").write_text(
            "import pytest\n\n@pytest.mark.skip  # allow-skip: needs GPU\ndef test_x():\n    pass\n"
        )
        self.assertEqual(self.found(), [])

    def test_runner_config_and_package_test_script_changes_are_flagged(self):
        (self.root / "pytest.ini").write_text("[pytest]\n")
        git(self.root, "add", "pytest.ini")
        git(self.root, "commit", "-qm", "ini")
        (self.root / "pytest.ini").write_text("[pytest]\naddopts = -x\n")
        (self.root / "package.json").write_text(json.dumps({"scripts": {"test": "echo ok"}}))
        self.assertEqual(self.found(), [("runner-config-changed", "high"), ("runner-config-changed", "high")])

    def test_unrelated_package_json_change_is_ignored(self):
        (self.root / "package.json").write_text(json.dumps({"scripts": {"test": "node --test"}, "name": "x"}))
        self.assertEqual(self.found(), [])

    def test_committed_mode_compares_revisions(self):
        (self.root / "tests/test_a.py").write_text("def test_a():\n    assert True\n")
        git(self.root, "commit", "-aqm", "weaken")
        found = scan(self.root, "committed", "HEAD~1", "HEAD")
        self.assertEqual([f.rule_id for f in found], ["test-modified"])


if __name__ == "__main__":
    unittest.main()
