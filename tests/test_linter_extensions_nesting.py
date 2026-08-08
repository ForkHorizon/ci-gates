"""Regressions for the false positives and parse bugs found in the 2026-08-07 audit.

Each test names the behaviour that was wrong before, so a future rewrite that
reintroduces it fails here instead of in someone's pull request.
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location("linter_fixes", SCRIPTS_DIR / "code-linter.py")
linter = importlib.util.module_from_spec(spec)
sys.modules["linter_fixes"] = linter
spec.loader.exec_module(linter)


class UnsupportedExtensionTests(unittest.TestCase):
    def test_unsupported_extension_is_rejected(self):
        root = Path(tempfile.mkdtemp()).resolve()
        (root / ".code-linter.json").write_text('{"include_extensions": [".cpp"], "max_file_lines": 10}')
        with self.assertRaises(SystemExit) as raised:
            linter.load_config(root / ".code-linter.json")
        self.assertEqual(raised.exception.code, 2)


class NestingDepthTests(unittest.TestCase):
    def nesting(self, source, language, limit=4):
        return linter.check_nesting_depth("fixture", source, language, limit)

    def test_closures_and_type_declarations_do_not_add_depth(self):
        # A plain `do` two closures deep used to report depth 5.
        source = (
            "struct View {\n"
            "    func run() {\n"
            "        queue.async {\n"
            "            work.perform {\n"
            "                do {\n"
            "                    try thing()\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        self.assertEqual(self.nesting(source, "swift", 1), [])

    def test_control_flow_still_counted(self):
        source = (
            "func run() {\n"
            "    if a {\n"
            "        for b in c {\n"
            "            while d {\n"
            "                if e {\n"
            "                    work()\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        issues = self.nesting(source, "swift", 3)
        self.assertEqual([issue.line for issue in issues], [5])

    def test_allman_braces_still_counted(self):
        source = (
            "void Foo()\n{\n    if (a)\n    {\n        if (b)\n        {\n"
            "            if (c)\n            {\n                Work();\n"
            "            }\n        }\n    }\n}\n"
        )
        self.assertGreater(len(self.nesting(source, "csharp", 2)), 0)
        self.assertEqual(self.nesting(source, "csharp", 3), [])

    def test_else_branch_sits_at_the_same_depth_as_the_if_branch(self):
        source = "func run() {\n    if a {\n        x()\n    } else {\n        y()\n    }\n}\n"
        self.assertEqual(self.nesting(source, "swift", 1), [])

    def test_try_as_an_expression_prefix_does_not_open_a_block(self):
        source = "func run() {\n    let value = try loader.load()\n    Group {\n        body()\n    }\n}\n"
        self.assertEqual(self.nesting(source, "swift", 0), [])

    def test_for_loop_semicolons_do_not_break_the_carried_keyword(self):
        source = "void Foo()\n{\n    for (int i = 0; i < n; i++)\n    {\n        Work();\n    }\n}\n"
        self.assertGreater(len(self.nesting(source, "csharp", 0)), 0)

    def test_one_issue_per_block_not_per_line(self):
        source = (
            "func run() {\n    if a {\n        if b {\n"
            "            line1()\n            line2()\n            line3()\n"
            "        }\n    }\n}\n"
        )
        self.assertEqual(len(self.nesting(source, "swift", 1)), 1)


if __name__ == "__main__":
    unittest.main()
