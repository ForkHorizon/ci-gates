"""Regressions for the false positives and parse bugs found in the 2026-08-07 audit.

Each test names the behaviour that was wrong before, so a future rewrite that
reintroduces it fails here instead of in someone's pull request.
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("linter_fixes", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["linter_fixes"] = linter
spec.loader.exec_module(linter)


class PathTests(unittest.TestCase):
    def test_symlink_pointing_outside_the_repo_does_not_crash(self):
        base = Path(tempfile.mkdtemp()).resolve()
        outside = base / "outside.py"
        outside.write_text("x = 1\n")
        root = base / "repo"
        root.mkdir()
        os.symlink(outside, root / "linked.py")
        # Reported under the in-repo path git gave us, rather than crashing.
        self.assertEqual(linter.to_relative(root, root / "linked.py"), "linked.py")


class ConfigTests(unittest.TestCase):
    def write_config(self, body):
        root = Path(tempfile.mkdtemp()).resolve()
        path = root / ".code-linter.json"
        path.write_text(body)
        return path

    def assert_rejected(self, body):
        with self.assertRaises(SystemExit) as raised:
            linter.load_config(self.write_config(body))
        self.assertEqual(raised.exception.code, 2)

    def test_non_numeric_limit_is_reported_not_crashed(self):
        self.assert_rejected('{"max_file_lines": null}')

    def test_ignore_must_be_a_list(self):
        self.assert_rejected('{"ignore": "node_modules"}')

    def test_language_overrides_must_be_an_object(self):
        self.assert_rejected('{"language_overrides": []}')

    def test_valid_config_still_loads(self):
        config = linter.load_config(self.write_config('{"max_file_lines": 120, "ignore": ["Generated"]}'))
        self.assertEqual(config["max_file_lines"], 120)
        self.assertIn("Generated", config["ignore"])
        self.assertIn("node_modules", config["ignore"])


if __name__ == "__main__":
    unittest.main()
