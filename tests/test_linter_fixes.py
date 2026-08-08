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

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

spec = importlib.util.spec_from_file_location(
    "linter_fixes", SCRIPTS_DIR / "code-linter.py"
)
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
        self.assertFalse(
            linter.should_ignore("src/code-linter.py", linter.DEFAULT_IGNORE)
        )

    def test_checked_out_gates_copy_is_skipped(self):
        self.assertTrue(
            linter.should_ignore(
                ".ci-gates/scripts/code-linter.py", linter.DEFAULT_IGNORE
            )
        )


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
        config = linter.load_config(
            self.write_config('{"max_file_lines": 120, "ignore": ["Generated"]}')
        )
        self.assertEqual(config["max_file_lines"], 120)
        self.assertIn("Generated", config["ignore"])
        self.assertIn("node_modules", config["ignore"])


class UnsupportedExtensionTests(unittest.TestCase):
    def test_unsupported_extension_is_rejected(self):
        root = Path(tempfile.mkdtemp()).resolve()
        (root / ".code-linter.json").write_text(
            '{"include_extensions": [".cpp"], "max_file_lines": 10}'
        )
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


class TypesPerFileTests(unittest.TestCase):
    def types(self, source, language):
        return [name for name, _ in linter.brace_type_declarations(source, language)]

    def test_nested_swift_types_are_not_counted(self):
        source = "struct Feed {\n    struct Run {}\n    enum Job {}\n}\n"
        self.assertEqual(self.types(source, "swift"), ["Feed"])

    def test_csharp_namespace_does_not_hide_its_types(self):
        source = "namespace App\n{\n    class A\n    {\n    }\n    class B\n    {\n    }\n}\n"
        self.assertEqual(self.types(source, "csharp"), ["A", "B"])

    def test_swift_extension_does_not_hide_its_types(self):
        source = "extension Feed {\n    struct Row {}\n}\nstruct Other {}\n"
        self.assertEqual(self.types(source, "swift"), ["Row", "Other"])

    def test_allman_type_declaration_still_nests(self):
        source = "class Outer\n{\n    class Inner\n    {\n    }\n}\n"
        self.assertEqual(self.types(source, "csharp"), ["Outer"])

    def test_go_alias_does_not_swallow_the_next_declaration(self):
        source = (
            "type UserID = string\n\nfunc Handle() {\n}\n\ntype Store struct {\n}\n"
        )
        self.assertEqual(self.types(source, "go"), ["UserID", "Store"])


class CommentBlockTests(unittest.TestCase):
    def blocks(self, source, language, limit=5):
        return linter.check_comment_blocks("fixture", source, language, limit)

    def test_doc_comments_are_exempt(self):
        source = "import Foundation\n" + "".join(f"/// line {i}\n" for i in range(10))
        source += "func run() {}\n"
        self.assertEqual(self.blocks(source, "swift"), [])

    def test_javadoc_block_is_exempt(self):
        source = "import java.util.List;\n/**\n" + "".join(
            f" * line {i}\n" for i in range(10)
        )
        source += " */\nvoid run() {}\n"
        self.assertEqual(self.blocks(source, "java"), [])

    def test_plain_block_comment_is_still_flagged(self):
        source = "int seed = 0;\n/*\n" + "".join(f" * line {i}\n" for i in range(10))
        source += " */\nvoid run() {}\n"
        self.assertEqual(len(self.blocks(source, "csharp")), 1)

    def test_commented_out_code_is_still_flagged(self):
        source = "let seed = 0\n" + "".join(f"// old line {i}\n" for i in range(10))
        source += "func run() {}\n"
        self.assertEqual(len(self.blocks(source, "swift")), 1)

    def test_generic_file_header_is_not_exempt(self):
        source = "".join(f"//  line {i}\n" for i in range(10)) + "\nfunc run() {}\n"
        self.assertEqual(len(self.blocks(source, "swift")), 1)

    def test_license_file_header_is_exempt(self):
        source = "// Copyright 2026\n" + "".join(
            f"// license line {i}\n" for i in range(10)
        )
        self.assertEqual(self.blocks(source, "swift"), [])

    def test_shebang_only_exempt_on_the_first_line(self):
        source = "#!/usr/bin/env python3\n" + "".join(f"# line {i}\n" for i in range(3))
        self.assertEqual(self.blocks(source, "python", 3), [])

    def test_hash_lines_inside_a_python_string_are_not_comments(self):
        source = 'x = 1\nFIXTURE = """\n' + "".join(f"# line {i}\n" for i in range(10))
        source += '"""\n'
        self.assertEqual(self.blocks(source, "python"), [])

    def test_python_trailing_comments_do_not_form_a_block(self):
        source = "".join(f"x{i} = {i}  # note {i}\n" for i in range(10))
        self.assertEqual(self.blocks(source, "python"), [])

    def test_python_real_comment_block_still_flagged(self):
        source = "x = 1\n" + "".join(f"# line {i}\n" for i in range(10)) + "y = 2\n"
        self.assertEqual(len(self.blocks(source, "python")), 1)

    def test_unparseable_python_falls_back_to_prefix_scan(self):
        source = "x = (\n" + "".join(f"# line {i}\n" for i in range(10))
        self.assertEqual(len(self.blocks(source, "python")), 1)


if __name__ == "__main__":
    unittest.main()
