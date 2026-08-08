"""Regressions for the false positives and parse bugs found in the 2026-08-07 audit.

Each test names the behaviour that was wrong before, so a future rewrite that
reintroduces it fails here instead of in someone's pull request.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("linter_fixes", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["linter_fixes"] = linter
spec.loader.exec_module(linter)


class RubyTests(unittest.TestCase):
    def test_default_argument_is_not_an_endless_method(self):
        source = "def foo(a = 1)\n  if a\n    puts a\n  end\nend\n"
        self.assertEqual(linter.ruby_function_lengths(source), [("foo", 1, 5, 1)])

    def test_endless_method_still_detected(self):
        source = "def foo(a) = a * 2\n"
        self.assertEqual(linter.ruby_function_lengths(source), [("foo", 1, 1, 1)])

    def test_default_argument_does_not_desync_following_methods(self):
        source = "def a(x = 1)\n  x\nend\n\ndef b\n  2\nend\n"
        names = [item[0] for item in linter.ruby_function_lengths(source)]
        self.assertEqual(names, ["a", "b"])


class IgnoreTests(unittest.TestCase):
    def test_a_project_file_called_code_linter_py_is_not_skipped(self):
        self.assertFalse(linter.should_ignore("src/code-linter.py", linter.DEFAULT_IGNORE))

    def test_checked_out_gates_copy_is_skipped(self):
        self.assertTrue(linter.should_ignore(".ci-gates/scripts/code-linter.py", linter.DEFAULT_IGNORE))


if __name__ == "__main__":
    unittest.main()
