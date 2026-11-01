"""Tests for the PreToolUse guard protecting tracked test files."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import test_guard


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def payload(path):
    return json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(path)}})


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.com")
        git(self.root, "config", "user.name", "Test")
        (self.root / "tests").mkdir()
        (self.root / "tests/test_a.py").write_text("def test_a():\n    pass\n")
        (self.root / "app.py").write_text("x = 1\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "base")

    def tearDown(self):
        self.temp.cleanup()

    def run_guard(self, text):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(test_guard.OVERRIDE, None)
            return test_guard.main(text, self.root)

    def test_editing_a_tracked_test_is_blocked(self):
        self.assertEqual(self.run_guard(payload(self.root / "tests/test_a.py")), 2)

    def test_relative_path_is_resolved_against_the_repository(self):
        self.assertEqual(self.run_guard(json.dumps({"tool_input": {"file_path": "tests/test_a.py"}})), 2)

    def test_new_test_file_and_production_code_are_allowed(self):
        self.assertEqual(self.run_guard(payload(self.root / "tests/test_new.py")), 0)
        self.assertEqual(self.run_guard(payload(self.root / "app.py")), 0)

    def test_paths_outside_the_repository_and_bad_input_are_allowed(self):
        self.assertEqual(self.run_guard(payload("/etc/hosts")), 0)
        self.assertEqual(self.run_guard("not json"), 0)
        self.assertEqual(self.run_guard(json.dumps({"tool_input": {}})), 0)

    def test_owner_override_allows_the_edit(self):
        with mock.patch.dict(os.environ, {test_guard.OVERRIDE: "1"}):
            self.assertEqual(test_guard.main(payload(self.root / "tests/test_a.py"), self.root), 0)

    def test_project_config_can_add_protected_patterns(self):
        (self.root / ".test-protection.json").write_text(json.dumps({"patterns": [r"^specs/"]}))
        (self.root / "specs").mkdir()
        (self.root / "specs/a.rb").write_text("x\n")
        git(self.root, "add", ".")
        self.assertEqual(self.run_guard(payload(self.root / "specs/a.rb")), 2)


if __name__ == "__main__":
    unittest.main()
