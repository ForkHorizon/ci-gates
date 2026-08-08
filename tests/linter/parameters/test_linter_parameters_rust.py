"""Regressions for the false positives and parse bugs found in the 2026-08-07 audit.

Each test names the behaviour that was wrong before, so a future rewrite that
reintroduces it fails here instead of in someone's pull request.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("linter_fixes", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["linter_fixes"] = linter
spec.loader.exec_module(linter)


class ParameterCountingTests(unittest.TestCase):
    def test_go_receiver_is_not_mistaken_for_the_parameter_list(self):
        source = "func (s *Server) Handle(a, b, c, d, e, f int) {\n\treturn\n}\n"
        functions = linter.brace_function_lengths(source, "go")
        self.assertEqual(functions[0][0], "Handle")
        self.assertEqual(functions[0][3], 6)

    def test_go_plain_function_still_counted(self):
        source = "func Handle(a int, b int) {\n\treturn\n}\n"
        self.assertEqual(linter.brace_function_lengths(source, "go")[0][3], 2)

    def test_swift_init_parameters_counted(self):
        source = "init(a: Int, b: Int, c: Int) {\n    self.a = a\n}\n"
        self.assertEqual(linter.brace_function_lengths(source, "swift")[0][3], 3)


class RustLifetimeTests(unittest.TestCase):
    SOURCE = "fn foo<'a>(x: &'a str) -> &'a str {\n    if x.len() > 1 {\n        return x;\n    }\n    x\n}\n"

    def test_lifetime_does_not_swallow_the_rest_of_the_line(self):
        clean = linter.scan_c_style_lines(self.SOURCE, "rust")[0][1]
        self.assertIn("{", clean)
        self.assertIn("str", clean)

    def test_function_length_and_parameters_survive_lifetimes(self):
        functions = linter.brace_function_lengths(self.SOURCE, "rust")
        self.assertEqual(functions, [("foo", 1, 6, 1)])

    def test_char_literal_is_still_a_string(self):
        clean = linter.scan_c_style_lines("let c = 'a'; let d = 1;", "rust")[0][1]
        self.assertIn("d", clean)


if __name__ == "__main__":
    unittest.main()
